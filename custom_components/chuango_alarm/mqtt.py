from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any, Callable

import aiomqtt
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .coordinator import DreamcatcherCoordinator


class DreamcatcherMqttManager:
    def __init__(self, hass: HomeAssistant, coordinator: DreamcatcherCoordinator, logger: logging.Logger) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._log = logger

        self._stop = asyncio.Event()
        self._tasks: dict[str, asyncio.Task] = {}

        # active per-device client (same connection used for subscribe + publish)
        self._clients: dict[str, aiomqtt.Client] = {}
        self._connected: dict[str, asyncio.Event] = {}
        self._pub_locks: dict[str, asyncio.Lock] = {}

        self._tls: ssl.SSLContext | None = None

        self._remove_coord_listener: Callable[[], None] | None = None
        self._remove_ha_started_listener: Callable[[], None] | None = None
        self._started = False

    async def async_start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()

        if self.hass.state != CoreState.running:
            @callback
            def _on_started(_: Any) -> None:
                self._remove_ha_started_listener = None
                self.hass.async_create_task(self._async_start_now())

            self._remove_ha_started_listener = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _on_started
            )
            return

        await self._async_start_now()

    async def _async_start_now(self) -> None:
        if self._tls is None:
            # ssl.create_default_context() lädt u.a. Default-Certs und ist blockierend -> in Executor
            self._tls = await self.hass.async_add_executor_job(ssl.create_default_context)

        self._refresh_tasks()

        if self._remove_coord_listener is None:
            self._remove_coord_listener = self.coordinator.async_add_listener(self._refresh_tasks)

    async def async_stop(self) -> None:
        self._stop.set()

        if self._remove_ha_started_listener is not None:
            self._remove_ha_started_listener()
            self._remove_ha_started_listener = None

        if self._remove_coord_listener is not None:
            self._remove_coord_listener()
            self._remove_coord_listener = None

        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

        self._started = False

    @callback
    def _refresh_tasks(self) -> None:
        try:
            device_ids = set(self.coordinator.get_device_ids())
        except Exception:
            device_ids = set()

        for dev_id in list(self._tasks.keys()):
            if dev_id not in device_ids:
                self._tasks[dev_id].cancel()
                self._tasks.pop(dev_id, None)

        for dev_id in device_ids:
            if dev_id in self._tasks:
                continue
            self._tasks[dev_id] = self.hass.async_create_task(self._device_loop(dev_id))

    def _get_connected_event(self, device_id: str) -> asyncio.Event:
        ev = self._connected.get(device_id)
        if ev is None:
            ev = asyncio.Event()
            self._connected[device_id] = ev
        return ev

    def _get_pub_lock(self, device_id: str) -> asyncio.Lock:
        lock = self._pub_locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._pub_locks[device_id] = lock
        return lock

    def _clear_client(self, device_id: str) -> None:
        self._clients.pop(device_id, None)
        ev = self._connected.get(device_id)
        if ev is not None:
            ev.clear()

    async def async_publish(
        self,
        device_id: str,
        topic: str,
        payload: str | bytes,
        *,
        qos: int = 1,
        retain: bool = False,
        timeout: float = 10.0,
    ) -> None:
        """Publish on the existing per-device MQTT connection (same client_id)."""
        ev = self._get_connected_event(device_id)
        if not ev.is_set():
            try:
                await asyncio.wait_for(ev.wait(), timeout=timeout)
            except asyncio.TimeoutError as err:
                raise HomeAssistantError(f"MQTT not connected for {device_id}") from err

        client = self._clients.get(device_id)
        if client is None:
            raise HomeAssistantError(f"MQTT client missing for {device_id}")

        lock = self._get_pub_lock(device_id)
        async with lock:
            await client.publish(topic, payload, qos=qos, retain=retain)

    async def _device_loop(self, device_id: str) -> None:
        interval = 5
        interval_max = 60

        while not self._stop.is_set():
            try:
                creds = self.coordinator.get_mqtt_credentials(device_id)
                host = str(creds["host"])
                port = int(creds["port"])
                client_id = str(creds["client_id"])
                username = str(creds["username"])
                password = str(creds["password"])

                topic = self.coordinator.get_mqtt_subscribe_topic(device_id)

                tls_ctx = self._tls
                if tls_ctx is None:
                    tls_ctx = await self.hass.async_add_executor_job(ssl.create_default_context)
                    self._tls = tls_ctx

                client = aiomqtt.Client(
                    hostname=host,
                    port=port,
                    username=username,
                    password=password,
                    identifier=client_id,
                    tls_context=tls_ctx,
                    keepalive=60,
                )

                async with client:
                    await client.subscribe(topic)
                    self._log.debug(
                        "MQTT subscribed for %s: host=%s:%s client_id=%s topic=%s",
                        device_id, host, port, client_id, topic
                    )

                    # expose connected client for publishes (same connection / client_id)
                    self._clients[device_id] = client
                    self._get_connected_event(device_id).set()

                    interval = 5

                    async for msg in client.messages:
                        if self._stop.is_set():
                            break

                        try:
                            self.coordinator.async_process_mqtt_message(
                                device_id=device_id,
                                topic=str(msg.topic),
                                payload=msg.payload,
                            )
                        except Exception as err:
                            self._log.debug("MQTT message processing error for %s: %s", device_id, err)

                self._clear_client(device_id)
            except asyncio.CancelledError:
                self._clear_client(device_id)
                raise
            except aiomqtt.MqttError as err:
                self._clear_client(device_id)
                self._log.debug(
                    "MQTT connection lost for %s (%s); reconnecting in %ss",
                    device_id, err, interval
                )
                await asyncio.sleep(interval)
                interval = min(interval_max, interval * 2)
            except Exception as err:
                self._clear_client(device_id)
                self._log.exception("MQTT loop error for %s: %s", device_id, err)
                await asyncio.sleep(interval)
                interval = min(interval_max, interval * 2)
