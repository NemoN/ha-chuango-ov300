from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DreamcatcherApiClient, DreamcatcherAuthError, DreamcatcherError
from .const import (
    CONF_AM_DOMAIN,
    CONF_AM_PORT,
    CONF_COUNTRY_CODE,
    CONF_EMAIL,
    CONF_PASSWORD_MD5,
    CONF_UUID,
    CONF_TOKEN,
    CONF_EXPIRE_AT,
    CONF_LAST_LOGIN,
    CONF_USER_INFO,
    DOMAIN,
    DOCS_URL,
    PARTS_SYNC_COOLDOWN_SECONDS,
)
from .utils import alarm_source_type_label, derive_alarm_origin

_REFRESH_BEFORE_SECONDS = 12 * 60 * 60  # 12h
_DIN_DUP_WINDOW_SECONDS = 0.5
_DIN_ECHO_WINDOW_SECONDS = 2.0
_EXT_MODIFY_GRACE_SECONDS = 2.0
_MAX_IN_MEMORY_ALARM_HISTORY = 100


class DreamcatcherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: DreamcatcherApiClient,
        entry: ConfigEntry,
        logger: logging.Logger,
    ) -> None:
        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(hours=6),
        )
        self.api = api
        self.entry = entry

        # persisted (survive restarts)
        self.token: str | None = entry.data.get(CONF_TOKEN)
        self.expire_at: int | None = entry.data.get(CONF_EXPIRE_AT)
        self.last_login: str | None = entry.data.get(CONF_LAST_LOGIN)

        ui = entry.data.get(CONF_USER_INFO)
        self.user_info: dict[str, Any] = ui if isinstance(ui, dict) else {}

        # runtime: stable MQTT client_id per device for this HA run
        self._mqtt_client_ids: dict[str, str] = {}

        # runtime: last seen MQTT messages (kept in memory; can be exposed as diagnostics)
        self._mqtt_state: dict[str, dict[str, Any]] = {}

        # runtime: firmware update info per device (populated by REST fwinfo call)
        self._firmware_info: dict[str, dict[str, Any]] = {}

        # runtime: dedupe tracker for echoed/redelivered din logs (QoS1 can duplicate)
        self._last_din_rx: dict[str, tuple[str, int, float]] = {}

        # runtime: recently sent din payloads (for self-echo detection)
        self._last_din_tx: dict[str, tuple[str, int, float]] = {}

        # runtime: last time an external client sent modify_parts (per device)
        self._last_ext_modify_parts_ts: dict[str, float] = {}

        # runtime: debounced parts sync tasks (per device)
        self._parts_sync_tasks: dict[str, asyncio.Task] = {}

    # ---------- token / persistence ----------

    def _token_is_valid(self) -> bool:
        if not self.token or not self.expire_at:
            return False
        now = int(dt_util.utcnow().timestamp())
        # treat token as "needs refresh" once it has <= 12h remaining
        return now < (int(self.expire_at) - _REFRESH_BEFORE_SECONDS)

    async def _persist_auth(self) -> None:
        data = dict(self.entry.data)

        user_info_to_store: dict[str, Any] = self.user_info if isinstance(self.user_info, dict) else {}

        changed = (
            data.get(CONF_TOKEN) != self.token
            or data.get(CONF_EXPIRE_AT) != self.expire_at
            or data.get(CONF_LAST_LOGIN) != self.last_login
            or data.get(CONF_USER_INFO) != user_info_to_store
        )
        if not changed:
            return

        data[CONF_TOKEN] = self.token
        data[CONF_EXPIRE_AT] = self.expire_at
        data[CONF_LAST_LOGIN] = self.last_login
        data[CONF_USER_INFO] = user_info_to_store

        self.hass.config_entries.async_update_entry(self.entry, data=data)

    async def _ensure_login(self, force: bool = False) -> None:
        if not force and self._token_is_valid():
            return

        d = self.entry.data
        res = await self.api.login(
            am_domain=d[CONF_AM_DOMAIN],
            am_port=int(d[CONF_AM_PORT]),
            country_code=d[CONF_COUNTRY_CODE],
            email=d[CONF_EMAIL],
            password_md5=d[CONF_PASSWORD_MD5],
            uuid=d[CONF_UUID],
        )

        self.token = res.token
        self.expire_at = res.expire_at
        self.user_info = res.user_info if isinstance(res.user_info, dict) else {}
        self.last_login = dt_util.utcnow().isoformat()

        await self._persist_auth()

    # ---------- coordinator update ----------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._ensure_login(force=False)
        except DreamcatcherAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except DreamcatcherError as err:
            raise UpdateFailed(f"Update failed: {err}") from err

        if not self.token:
            raise UpdateFailed("No token available")

        d = self.entry.data

        try:
            devices = await self.api.shared_devices(
                am_domain=d[CONF_AM_DOMAIN],
                am_port=int(d[CONF_AM_PORT]),
                token=self.token,
            )
        except DreamcatcherAuthError:
            # server-side invalidation -> refresh once + retry
            try:
                await self._ensure_login(force=True)
                if not self.token:
                    raise UpdateFailed("No token available after forced login")

                devices = await self.api.shared_devices(
                    am_domain=d[CONF_AM_DOMAIN],
                    am_port=int(d[CONF_AM_PORT]),
                    token=self.token,
                )
            except DreamcatcherAuthError as err:
                raise UpdateFailed(f"Authentication failed: {err}") from err
            except DreamcatcherError as err:
                raise UpdateFailed(f"Shared devices request failed: {err}") from err
        except DreamcatcherError as err:
            raise UpdateFailed(f"Shared devices request failed: {err}") from err

        # Be robust if api.shared_devices returns either a list or {"list": [...]}
        if isinstance(devices, dict) and isinstance(devices.get("list"), list):
            devices_list = devices["list"]
        else:
            devices_list = devices

        devices_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(devices_list, list):
            for dev in devices_list:
                if not isinstance(dev, dict):
                    continue
                dev_id = dev.get("ID")
                if not dev_id:
                    continue
                devices_by_id[str(dev_id)] = dev

        for dev_id, dev in devices_by_id.items():
            dev.setdefault("ID", dev_id)
            dev.setdefault("mqtt_calc", self._build_mqtt_calc(dev_id, dev))

        if not devices_by_id:
            raise ConfigEntryError(
                "No shared devices found for this account. "
                f"Please follow the integration documentation: {DOCS_URL}"
            )

        # Check for firmware updates for each device
        for dev_id, dev in devices_by_id.items():
            await self._fetch_firmware_info(dev_id, dev)

        return {
            "userInfo": self.user_info or {},
            "expireAt": self.expire_at,
            "lastLogin": self.last_login,
            "shared_devices": devices_by_id,
            "mqtt_state": self._mqtt_state,
            "firmware_info": self._firmware_info,
        }

    # ---------- firmware update check ----------

    async def _fetch_firmware_info(self, device_id: str, dev: dict[str, Any]) -> None:
        """Check the fwinfo REST endpoint for available firmware updates."""
        dev_id_int = dev.get("devIdInt")
        if not dev_id_int:
            return

        # Get the dm endpoint for this device
        dm = dev.get("dm") or {}
        dm_domain = dm.get("domain")
        dm_port = dm.get("port")
        if dm_domain and dm_port:
            base_url = f"https://{dm_domain}:{dm_port}"
        else:
            d = self.entry.data
            base_url = f"https://{d[CONF_AM_DOMAIN]}:{d[CONF_AM_PORT]}"

        # Use current installed fw version from MQTT state (if available)
        dev_state = self._mqtt_state.get(device_id) or {}
        installed_fw = dev_state.get("fw") or ""

        try:
            result = await self.api.firmware_info(
                base_url=base_url,
                token=self.token,
                device_id_int=int(dev_id_int),
                wifi_version=installed_fw,
            )
        except Exception as err:
            self.logger.debug("Firmware info check failed for %s: %s", device_id, err)
            return

        fw_list = result.get("fwList") or []
        if not isinstance(fw_list, list):
            fw_list = []

        self._firmware_info[device_id] = {
            "code": result.get("code"),
            "fwCount": result.get("fwCount", 0),
            "force": result.get("force", 0),
            "appForce": result.get("appForce", 0),
            "fwList": fw_list,
            "installed_version": installed_fw or None,
        }

    # ---------- device + mqtt helpers ----------

    def get_device_ids(self) -> list[str]:
        devs = (self.data or {}).get("shared_devices")
        if not isinstance(devs, dict):
            return []
        return list(devs.keys())

    @staticmethod
    def _safe_json(payload: str | bytes) -> Any | None:
        try:
            if isinstance(payload, (bytes, bytearray)):
                text = bytes(payload).decode("utf-8", errors="replace")
            else:
                text = str(payload)
            return json.loads(text)
        except Exception:
            return None
        
    def _get_device(self, device_id: str) -> dict[str, Any]:
        devs = (self.data or {}).get("shared_devices") or {}
        if not isinstance(devs, dict) or device_id not in devs:
            raise HomeAssistantError(f"Unknown device_id: {device_id}")
        dev = devs[device_id]
        if not isinstance(dev, dict):
            raise HomeAssistantError(f"Invalid device payload for {device_id}")
        return dev

    def _get_mqtt_auth(self, device_id: str, dev: dict[str, Any] | None = None) -> tuple[str, int, str]:
        d = dev if isinstance(dev, dict) else self._get_device(device_id)
        mqtt = d.get("mqtt") or {}
        host = mqtt.get("domain")
        port = mqtt.get("port")
        token = mqtt.get("token")
        if not host or not port or not token:
            raise HomeAssistantError(f"MQTT auth data missing for device {device_id}")
        return str(host), int(port), str(token)

    def get_mqtt_client_id(self, device_id: str) -> str:
        # and_<device_id>_<random_8_digits>
        if device_id not in self._mqtt_client_ids:
            rnd8 = f"{secrets.randbelow(100_000_000):08d}"
            self._mqtt_client_ids[device_id] = f"and_{device_id}_{rnd8}"
        return self._mqtt_client_ids[device_id]

    def get_mqtt_username(self, device_id: str) -> str:
        # <device_id>_<Api userDB><Api userId>
        ui = self.user_info or {}
        user_db = str(ui.get("userDB") or "")
        user_id = str(ui.get("userId") or "")
        if not user_db or not user_id:
            raise HomeAssistantError("Missing userDB/userId in userInfo (required for MQTT username)")
        return f"{device_id}_{user_db}{user_id}"

    def get_mqtt_dc_id(self, device_id: str, dev: dict[str, Any] | None = None) -> str:
        d = dev if isinstance(dev, dict) else self._get_device(device_id)
        mpid = d.get("mpid")
        product_id = d.get("product_id")
        dc_id = mpid or product_id # prefer mpid (but maybe product_id is the correct one for some devices)
        if not dc_id:
            raise HomeAssistantError(f"Missing mpid/product_id for device {device_id}")
        return str(dc_id)

    def get_mqtt_subscribe_topic(self, device_id: str) -> str:
        dc_id = self.get_mqtt_dc_id(device_id)
        return f"smart/{device_id}/dc/{dc_id}/dout/#"
    
    def get_mqtt_din_config_topic(self, device_id: str) -> str:
        dc_id = self.get_mqtt_dc_id(device_id)
        return f"smart/{device_id}/dc/{dc_id}/din/config"

    def get_mqtt_credentials(self, device_id: str) -> dict[str, Any]:
        host, port, token = self._get_mqtt_auth(device_id)
        return {
            "host": host,
            "port": port,
            "tls": True,
            "client_id": self.get_mqtt_client_id(device_id),
            "username": self.get_mqtt_username(device_id),
            "password": token,  # mqtt.token
            "subscribe_topic": self.get_mqtt_subscribe_topic(device_id),
        }

    def _build_mqtt_calc(self, device_id: str, dev: dict[str, Any]) -> dict[str, Any]:
        # Non-persisted computed values useful for diagnostics
        try:
            host, port, token = self._get_mqtt_auth(device_id, dev=dev)
        except Exception:
            host, port, token = None, None, None

        try:
            username = self.get_mqtt_username(device_id)
        except Exception:
            username = None

        try:
            subscribe = self.get_mqtt_subscribe_topic(device_id)
        except Exception:
            subscribe = None

        return {
            "tls": True,
            "host": host,
            "port": port,
            "username": username,
            "client_id": self.get_mqtt_client_id(device_id),
            "subscribe_topic": subscribe,
            "password_present": bool(token),
        }

    # ---------- MQTT message ingestion (called by your future MQTT client code) ----------

    @callback
    def mark_din_tx(self, *, device_id: str, topic: str, payload: str | bytes) -> None:
        """Track outgoing din payloads to classify later din RX as self-echo/external."""
        if "/din/" not in topic:
            return
        try:
            if isinstance(payload, (bytes, bytearray)):
                payload_bytes = bytes(payload)
            else:
                payload_bytes = str(payload).encode("utf-8", errors="replace")
            self._last_din_tx[device_id] = (topic, hash(payload_bytes), time.monotonic())
        except Exception:
            # best-effort telemetry only
            return

    def _schedule_parts_sync(self, device_id: str) -> None:
        """Debounce parts_list refreshes so bursts of modify_parts do not spam device/app."""
        existing = self._parts_sync_tasks.get(device_id)
        if existing is not None and not existing.done():
            existing.cancel()

        self._parts_sync_tasks[device_id] = self.hass.async_create_task(
            self._parts_sync_after_cooldown(device_id)
        )

    async def _parts_sync_after_cooldown(self, device_id: str) -> None:
        try:
            await asyncio.sleep(PARTS_SYNC_COOLDOWN_SECONDS)
            await self.async_request_parts_list(device_id, page=1)
        except asyncio.CancelledError:
            return
        except Exception as err:
            self.logger.debug("Debounced parts sync failed for %s: %s", device_id, err)
        finally:
            task = self._parts_sync_tasks.get(device_id)
            if task is not None and task.done():
                self._parts_sync_tasks.pop(device_id, None)

    @callback
    def async_process_mqtt_message(self, *, device_id: str, topic: str, payload: bytes) -> None:
        """Parse a device dout message and update in-memory mqtt_state."""

        # Full payload for debug log
        try:
            preview = payload.decode("utf-8", errors="replace")
        except Exception:
            preview = repr(payload)

        # We also subscribe to din/config for debugging external clients.
        # Log it with a dedicated prefix and do not treat din traffic as state updates.
        if "/din/" in topic:
            now_mono = time.monotonic()
            payload_hash = hash(payload)
            last = self._last_din_rx.get(device_id)
            if last is not None:
                last_topic, last_hash, last_ts = last
                if last_topic == topic and last_hash == payload_hash and (now_mono - last_ts) <= _DIN_DUP_WINDOW_SECONDS:
                    return
            self._last_din_rx[device_id] = (topic, payload_hash, now_mono)

            src = "EXT"
            tx = self._last_din_tx.get(device_id)
            if tx is not None:
                tx_topic, tx_hash, tx_ts = tx
                if tx_topic == topic and tx_hash == payload_hash and (now_mono - tx_ts) <= _DIN_ECHO_WINDOW_SECONDS:
                    src = "ECHO"

            self.logger.debug("MQTT RX DIN %s dev=%s topic=%s payload=%s", src, device_id, topic, preview)

            # If an external client modifies parts (e.g. app), update local parts state directly
            # to avoid immediate parts_list polling bursts that can cause UI flicker.
            if src == "EXT":
                data = self._safe_json(payload)
                m = data.get("m") if isinstance(data, dict) else None
                req = m.get("req") if isinstance(m, dict) else None
                if isinstance(req, dict) and req.get("a") == "modify_parts":
                    self._last_ext_modify_parts_ts[device_id] = now_mono
                    req_parts = req.get("parts")
                    if isinstance(req_parts, list):
                        dev_state = dict(self._mqtt_state.get(device_id) or {})
                        parts_state = list(dev_state.get("parts") or [])
                        changed = False

                        for req_part in req_parts:
                            if not isinstance(req_part, dict):
                                continue
                            part_id = req_part.get("id")
                            if part_id is None:
                                continue

                            for idx, existing_part in enumerate(parts_state):
                                if not isinstance(existing_part, dict):
                                    continue
                                if existing_part.get("id") != part_id:
                                    continue

                                updated = dict(existing_part)
                                for key, value in req_part.items():
                                    if key == "id":
                                        continue
                                    updated[key] = value

                                # Keep c bitfield status in sync if e was modified.
                                if "e" in req_part and updated.get("c") is not None:
                                    try:
                                        c_int = int(updated.get("c"))
                                        if int(req_part.get("e")) == 1:
                                            c_int = c_int | 0x80
                                        else:
                                            c_int = c_int & 0x7F
                                        updated["c"] = c_int
                                    except (TypeError, ValueError):
                                        pass

                                parts_state[idx] = updated
                                changed = True
                                break

                        if changed:
                            dev_state["parts"] = parts_state
                            self._mqtt_state[device_id] = dev_state
                            cur = dict(self.data or {})
                            cur["mqtt_state"] = dict(self._mqtt_state)
                            cur["firmware_info"] = dict(self._firmware_info)
                            self.async_set_updated_data(cur)
            return

        self.logger.debug("MQTT RX DOUT dev=%s topic=%s payload=%s", device_id, topic, preview)

        data = self._safe_json(payload)

        # State pro Device in self._mqtt_state halten (damit HTTP-Refresh ihn nicht überschreibt)
        dev_state = dict(self._mqtt_state.get(device_id) or {})

        dev_state["last_topic"] = topic
        dev_state["last_seen"] = dt_util.utcnow().isoformat()

        # Online/Offline
        if topic.endswith("/dout/online") and isinstance(data, dict):
            param = str(data.get("param") or "")
            dev_state["online"] = (param == "1" or param.lower() == "true")
            dev_state["online_msg"] = data.get("msg")

        # Config
        if topic.endswith("/dout/config") and isinstance(data, dict):
            m = data.get("m")
            res = m.get("res") if isinstance(m, dict) else None
            if isinstance(res, dict):
                action = res.get("a")
                if action == "host_stat" or action is None:
                    dev_state["mode"] = res.get("mode")     # d/a/h/...
                    dev_state["alarm"] = res.get("alarm")   # 0/1
                    dev_state["trig"] = res.get("trig")
                    dev_state["power"] = res.get("power")
                    dev_state["test_mode"] = res.get("test")
                    dev_state["time"] = res.get("time")
                if action == "host_conf":
                    is_conf = res.get("IS")
                    if isinstance(is_conf, dict):
                        dev_state["alarm_volume"] = is_conf.get("v")
                        dev_state["arm_beep"] = is_conf.get("t")
                        dev_state["alarm_duration"] = is_conf.get("tm")
                    delay_conf = res.get("delay")
                    if isinstance(delay_conf, dict):
                        dev_state["exit_delay"] = delay_conf.get("o")
                        dev_state["exit_delay_tone"] = delay_conf.get("ot")
                        dev_state["entry_delay"] = delay_conf.get("i")
                        dev_state["entry_delay_tone"] = delay_conf.get("it")

        # Info
        if topic.endswith("/dout/info") and isinstance(data, dict):
            m = data.get("m")
            res = m.get("res") if isinstance(m, dict) else None
            if isinstance(res, dict):
                action = res.get("a")
                if action == "dev_conf" or action is None:
                    dev_state["tz"] = res.get("tz")
                    dev_state["fw"] = res.get("w_v")
                    dev_state["ip_local"] = res.get("ip")
                    dev_state["qs_d"] = res.get("qs_d")
                    dev_state["qs_p"] = res.get("qs_p")
                if action == "parts_list":
                    parts = res.get("parts")
                    page = res.get("page", 1)
                    finish = res.get("finish", 1)
                    if isinstance(parts, list):
                        existing = dev_state.get("parts") or []
                        if page == 1:
                            existing = []
                        existing = list(existing) + parts
                        dev_state["parts"] = existing
                    # Request next page if not finished
                    if finish == 0:
                        next_page = (page or 1) + 1
                        self.hass.async_create_task(
                            self.async_request_parts_list(device_id, page=next_page)
                        )
                if action == "modify_parts":
                    # ACK only; state updates come from optimistic local update or DIN EXT processing.
                    self._last_din_tx.pop(device_id, None)
                    now_mono = time.monotonic()
                    ext_ts = self._last_ext_modify_parts_ts.get(device_id, 0.0)
                    if (now_mono - ext_ts) > _EXT_MODIFY_GRACE_SECONDS:
                        self._schedule_parts_sync(device_id)
                    pass

        # Alarm events (who changed the mode) -> changed_by
        if topic.endswith("/dout/alarm") and isinstance(data, dict):
            nick = data.get("iN")          # "Home Assistant" / user alias
            evt = data.get("iE")           # 12 disarm, 13 arm, 14 home arm
            ts = data.get("tS")            # unix timestamp

            # Persist raw event details for debugging / attributes
            dev_state["alarm_evt_code"] = evt
            dev_state["alarm_evt_nick"] = nick
            dev_state["alarm_evt_ts"] = ts
            dev_state["alarm_evt_sn"] = data.get("sN")

            # Prepend live event to alarm_history so it appears in
            # extra_state_attributes immediately (same format as REST items).
            live_item = {
                "itemEvent": evt,
                "itemName": nick or "",
                "time": ts,
            }
            history = list(dev_state.get("alarm_history") or [])
            history.insert(0, live_item)
            if len(history) > _MAX_IN_MEMORY_ALARM_HISTORY:
                history = history[:_MAX_IN_MEMORY_ALARM_HISTORY]
            dev_state["alarm_history"] = history
            dev_state["alarm_history_total"] = dev_state.get("alarm_history_total", len(history)) + 1

            # Only treat mode-changing events as "changed_by"
            mode_map = {12: "d", 13: "a", 14: "h"}
            try:
                evt_i = int(evt)
            except Exception:
                evt_i = None

            source_type = data.get("iT")
            trigger_type = dev_state.get("trig")
            alarm_origin = derive_alarm_origin(
                event_code=evt_i,
                trigger_type=trigger_type,
                source_type=source_type,
            )
            dev_state["alarm_origin"] = alarm_origin

            if evt_i in mode_map:
                if isinstance(nick, str) and nick.strip():
                    dev_state["changed_by"] = nick.strip()
                dev_state["mode"] = mode_map[evt_i]

            # Trigger events -> triggered_by
            # iE=11: SOS (app/keyfob), iE=15: tamper, iE=26: sensor trigger
            if evt_i in (11, 15, 26):
                dev_state["triggered_by"] = nick.strip() if isinstance(nick, str) and nick.strip() else None
                dev_state["triggered_by_id"] = data.get("iI")
                dev_state["triggered_by_type"] = source_type
                dev_state["triggered_by_type_label"] = alarm_source_type_label(source_type)
                dev_state["triggered_at"] = ts

            # Fire dispatcher signal immediately so event entities
            # receive every alarm regardless of coordinator debouncing.
            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_alarm_event_{device_id}",
                {
                    "evt_code": evt_i,
                    "nick": nick,
                    "ts": ts,
                    "sn": data.get("sN"),
                    "source_id": data.get("iI"),
                    "source_type": source_type,
                    "source_type_label": alarm_source_type_label(source_type),
                    "alarm_origin": alarm_origin,
                },
            )

        # Persist in runtime state
        self._mqtt_state[device_id] = dev_state

        # Update coordinator.data sofort (Push-Update)
        cur = dict(self.data or {})
        cur["mqtt_state"] = dict(self._mqtt_state)
        cur["firmware_info"] = dict(self._firmware_info)

        self.async_set_updated_data(cur)

    async def async_request_parts_list(self, device_id: str, page: int = 1) -> None:
        """Request the parts/accessories list via MQTT (paginated)."""
        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {"m": {"req": {"a": "parts_list", "type": "all", "page": page}}}
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_request_host_conf(self, device_id: str) -> None:
        """Request the current host configuration via MQTT."""
        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {"m": {"req": {"a": "host_conf"}}}
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_host_conf(self, device_id: str, *, volume: int | None = None, arm_beep: int | None = None, alarm_duration: int | None = None) -> None:
        """Send host configuration changes via MQTT."""
        # Read current values from mqtt_state so we can send all IS fields
        dev_state = (self._mqtt_state.get(device_id) or {})
        cur_v = dev_state.get("alarm_volume", 1)
        cur_t = dev_state.get("arm_beep", 1)
        cur_tm = dev_state.get("alarm_duration", 1)

        v = volume if volume is not None else cur_v
        t = arm_beep if arm_beep is not None else cur_t
        tm = alarm_duration if alarm_duration is not None else cur_tm

        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {"m": {"req": {"a": "host_conf", "IS": {"v": v, "t": t, "tm": tm}}}}
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_host_conf_delay(
        self,
        device_id: str,
        *,
        exit_delay: int | None = None,
        exit_delay_tone: int | None = None,
        entry_delay: int | None = None,
        entry_delay_tone: int | None = None,
    ) -> None:
        """Send host_conf delay changes via MQTT.

        delay fields:
        - o: exit delay seconds (0..300)
        - ot: exit delay tone (0/1)
        - i: entry delay seconds (0..300)
        - it: entry delay tone (0/1)
        """
        dev_state = self._mqtt_state.get(device_id) or {}

        cur_o = dev_state.get("exit_delay", 0)
        cur_ot = dev_state.get("exit_delay_tone", 1)
        cur_i = dev_state.get("entry_delay", 0)
        cur_it = dev_state.get("entry_delay_tone", 1)

        try:
            o = int(exit_delay if exit_delay is not None else cur_o)
            ot = int(exit_delay_tone if exit_delay_tone is not None else cur_ot)
            i = int(entry_delay if entry_delay is not None else cur_i)
            it = int(entry_delay_tone if entry_delay_tone is not None else cur_it)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(f"Invalid delay payload: {err}") from err

        o = max(0, min(300, o))
        i = max(0, min(300, i))
        ot = 1 if ot else 0
        it = 1 if it else 0

        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {
            "m": {
                "req": {
                    "a": "host_conf",
                    "delay": {
                        "o": o,
                        "ot": ot,
                        "i": i,
                        "it": it,
                    },
                }
            }
        }
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_test_mode(self, device_id: str, enabled: bool) -> None:
        """Enable/disable accessories RF test mode via host_stat.test (1/0)."""
        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {
            "m": {
                "req": {
                    "a": "host_stat",
                    "test": 1 if enabled else 0,
                }
            }
        }
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_modify_part_zone(self, device_id: str, part_id: int, zone: int) -> None:
        """Set a part/accessory zone via modify_parts.

        Zone values:
        - 0 = 24h
        - 1 = Normal
        - 2 = Home
        - 3 = Delay
        """
        if zone not in (0, 1, 2, 3):
            raise HomeAssistantError(f"Unsupported zone value: {zone}")

        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {
            "m": {
                "req": {
                    "a": "modify_parts",
                    "parts": [
                        {
                            "id": int(part_id),
                            "z": int(zone),
                        }
                    ],
                }
            }
        }
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        # Optimistic local update so UI reflects the selection immediately
        dev_state = dict(self._mqtt_state.get(device_id) or {})
        parts = list(dev_state.get("parts") or [])
        changed = False
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if part.get("id") == part_id:
                updated = dict(part)
                updated["z"] = int(zone)
                parts[index] = updated
                changed = True
                break

        if changed:
            dev_state["parts"] = parts
            self._mqtt_state[device_id] = dev_state
            cur = dict(self.data or {})
            cur["mqtt_state"] = dict(self._mqtt_state)
            cur["firmware_info"] = dict(self._firmware_info)
            self.async_set_updated_data(cur)

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_modify_part_enabled(self, device_id: str, part_id: int, enabled: bool) -> None:
        """Enable/disable a part/accessory via modify_parts.

        Important:
        Field observations from live device logs show:
        - e=0 -> disabled (off)
        - e=1 -> enabled (on)
        """
        e_value = 1 if enabled else 0

        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {
            "m": {
                "req": {
                    "a": "modify_parts",
                    "parts": [
                        {
                            "id": int(part_id),
                            "e": int(e_value),
                        }
                    ],
                }
            }
        }
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        # Optimistic local update so UI reflects the switch immediately
        dev_state = dict(self._mqtt_state.get(device_id) or {})
        parts = list(dev_state.get("parts") or [])
        changed = False
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if part.get("id") == part_id:
                updated = dict(part)
                updated["e"] = int(e_value)

                # Keep c bitfield in sync when present (status bit is bit 7).
                c_val = updated.get("c")
                if c_val is not None:
                    try:
                        c_int = int(c_val)
                        if enabled:
                            c_int = c_int | 0x80
                        else:
                            c_int = c_int & 0x7F
                        updated["c"] = c_int
                    except (ValueError, TypeError):
                        pass

                parts[index] = updated
                changed = True
                break

        if changed:
            dev_state["parts"] = parts
            self._mqtt_state[device_id] = dev_state
            cur = dict(self.data or {})
            cur["mqtt_state"] = dict(self._mqtt_state)
            cur["firmware_info"] = dict(self._firmware_info)
            self.async_set_updated_data(cur)

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_modify_part_sos(self, device_id: str, part_id: int, sos_enabled: bool) -> None:
        """Enable/disable SOS for a keyfob/remote via modify_parts.ss.

        Observed/expected mapping:
        - ss=0 -> SOS disabled
        - ss=1 -> SOS enabled
        """
        ss_value = 1 if sos_enabled else 0

        topic = self.get_mqtt_din_config_topic(device_id)
        payload_obj = {
            "m": {
                "req": {
                    "a": "modify_parts",
                    "parts": [
                        {
                            "id": int(part_id),
                            "ss": int(ss_value),
                        }
                    ],
                }
            }
        }
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        # Optimistic local update so UI reflects the switch immediately
        dev_state = dict(self._mqtt_state.get(device_id) or {})
        parts = list(dev_state.get("parts") or [])
        changed = False
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if part.get("id") == part_id:
                updated = dict(part)
                updated["ss"] = int(ss_value)
                parts[index] = updated
                changed = True
                break

        if changed:
            dev_state["parts"] = parts
            self._mqtt_state[device_id] = dev_state
            cur = dict(self.data or {})
            cur["mqtt_state"] = dict(self._mqtt_state)
            cur["firmware_info"] = dict(self._firmware_info)
            self.async_set_updated_data(cur)

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_send_alarm_command(self, device_id: str, command: str, code: str | None = None) -> None:
        """Send alarm mode changes via MQTT using the existing per-device connection.

        Supported modes:
        - d: disarm
        - a: arm away
        - h: arm home
        - s: SOS alarm
        """

        mode = (command or "").lower().strip()
        if mode not in ("d", "a", "h", "s"):
            raise HomeAssistantError(f"Unsupported alarm mode: {command}")

        usr = str(self.entry.data.get(CONF_EMAIL) or "")
        ui = self.user_info or {}
        uid = ui.get("userId") or ui.get("userID") or ui.get("uid") or ui.get("id") or 0
        try:
           uid_int = int(uid)
        except Exception:
            uid_int = 0

        nick = ui.get("nick") or ui.get("alias") or ui.get("userName") or ui.get("username")
        if not nick and usr and "@" in usr:
            nick = usr.split("@", 1)[0]
        nick = str(nick or "")

        ts = int(dt_util.utcnow().timestamp())
        payload_obj = {"m":{"req":{"a":"host_stat","src":0,"uID":uid_int,"usr":usr,"mode":mode,"nick":nick,"time":ts}}}

        topic = self.get_mqtt_din_config_topic(device_id)
        payload = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)

        runtime = (self.hass.data.get(DOMAIN) or {}).get(self.entry.entry_id) or {}
        mqtt = runtime.get("mqtt")
        if mqtt is None:
            raise HomeAssistantError("MQTT manager not available")

        self.logger.debug("MQTT TX dev=%s topic=%s payload=%s", device_id, topic, payload)
        await mqtt.async_publish(device_id, topic, payload, qos=1, retain=False)

    async def async_fetch_alarm_history(self, device_id: str, page_size: int = 50) -> None:
        """Fetch alarm history from REST API and store in mqtt_state."""
        try:
            await self._ensure_login()
        except Exception:
            self.logger.warning("Cannot fetch alarm history: login failed")
            return

        dev = self._get_device(device_id)
        dev_id_int = dev.get("devIdInt")
        if not dev_id_int:
            self.logger.warning("Cannot fetch alarm history: no devIdInt for %s", device_id)
            return

        # Use per-device dm endpoint, fall back to am endpoint from config entry
        dm = dev.get("dm") or {}
        dm_domain = dm.get("domain")
        dm_port = dm.get("port")
        if dm_domain and dm_port:
            base_url = f"https://{dm_domain}:{dm_port}"
        else:
            d = self.entry.data
            base_url = f"https://{d[CONF_AM_DOMAIN]}:{d[CONF_AM_PORT]}"

        try:
            result = await self.api.alarm_history(
                base_url=base_url,
                token=self.token,
                dev_id_int=int(dev_id_int),
                page_size=page_size,
            )
        except Exception as err:
            self.logger.warning("Alarm history fetch failed for %s: %s", device_id, err)
            return

        items = result.get("items", [])
        total = result.get("total", 0)

        dev_state = dict(self._mqtt_state.get(device_id) or {})
        dev_state["alarm_history"] = items
        dev_state["alarm_history_total"] = total
        self._mqtt_state[device_id] = dev_state

        # Push update
        cur = dict(self.data or {})
        cur["mqtt_state"] = dict(self._mqtt_state)
        cur["firmware_info"] = dict(self._firmware_info)
        self.async_set_updated_data(cur)
