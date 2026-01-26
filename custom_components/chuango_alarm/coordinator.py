from __future__ import annotations

import json
import logging
import secrets
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
)

_REFRESH_BEFORE_SECONDS = 12 * 60 * 60  # 12h


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
            raise UpdateFailed("No shared devices found for this account")

        return {
            "userInfo": self.user_info or {},
            "expireAt": self.expire_at,
            "lastLogin": self.last_login,
            "shared_devices": devices_by_id,
            "mqtt_state": self._mqtt_state,
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
    def async_process_mqtt_message(self, *, device_id: str, topic: str, payload: bytes) -> None:
        """Parse a device dout message and update in-memory mqtt_state."""

        # Preview fürs Log (lesbar, ohne Formatfehler)
        try:
            preview = payload[:200].decode("utf-8", errors="replace")
        except Exception:
            preview = repr(payload[:200])

        self.logger.debug("MQTT RX dev=%s topic=%s payload=%s", device_id, topic, preview)

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
                dev_state["mode"] = res.get("mode")     # d/a/h/...
                dev_state["alarm"] = res.get("alarm")   # 0/1
                dev_state["trig"] = res.get("trig")
                dev_state["power"] = res.get("power")
                dev_state["time"] = res.get("time")

        # Info
        if topic.endswith("/dout/info") and isinstance(data, dict):
            m = data.get("m")
            res = m.get("res") if isinstance(m, dict) else None
            if isinstance(res, dict):
                dev_state["tz"] = res.get("tz")
                dev_state["fw"] = res.get("w_v")
                dev_state["ip_local"] = res.get("ip")
                dev_state["qs_d"] = res.get("qs_d")
                dev_state["qs_p"] = res.get("qs_p")

        # Persist in runtime state
        self._mqtt_state[device_id] = dev_state

        # Update coordinator.data sofort (Push-Update)
        cur = dict(self.data or {})
        cur["mqtt_state"] = dict(self._mqtt_state)

        self.async_set_updated_data(cur)

    async def async_send_alarm_command(self, device_id: str, command: str, code: str | None = None) -> None:
        """Send arm/disarm via MQTT using the existing per-device connection."""
        
        mode = (command or "").lower().strip()
        if mode not in ("d", "a", "h"):
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
