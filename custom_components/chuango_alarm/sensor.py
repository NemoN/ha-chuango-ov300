from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AM_DOMAIN,
    CONF_AM_IP,
    CONF_AM_PORT,
    CONF_MQTT_DOMAIN,
    CONF_MQTT_IP,
    CONF_MQTT_PORT,
    CONF_EMAIL,
    CONF_COUNTRY_CODE,
    CONF_UUID,
    CONF_TOKEN,
    CONF_EXPIRE_AT,
    CONF_LAST_LOGIN,
    CONF_USER_INFO,
    DOMAIN,
)
from .coordinator import DreamcatcherCoordinator


@dataclass(frozen=True, slots=True)
class _DevDiagDef:
    key: str
    name: str


DEV_DIAG_DEFS: list[_DevDiagDef] = [
    #_DevDiagDef("mqtt_endpoint", "MQTT Endpoint"),
    #_DevDiagDef("mqtt_domain", "MQTT Domain"),
    #_DevDiagDef("mqtt_ip", "MQTT IP"),
    #_DevDiagDef("mqtt_port", "MQTT Port"),
    #_DevDiagDef("mqtt_token", "MQTT Token"),
    #_DevDiagDef("mqtt_username", "MQTT Username"),
    #_DevDiagDef("mqtt_client_id", "MQTT Client ID"),
    #_DevDiagDef("mqtt_subscribe", "MQTT Subscribe Topic"),
    #_DevDiagDef("dm_endpoint", "REST Endpoint"),
    #_DevDiagDef("dm_domain", "REST Domain"),
    #_DevDiagDef("dm_ip", "REST IP"),
    #_DevDiagDef("dm_port", "REST Port"),
    # _DevDiagDef("user_auth", "User Auth"),
    _DevDiagDef("dtype", "Device Type"),
    _DevDiagDef("product_id", "Product ID"),
    _DevDiagDef("dev_id_int", "Device ID"),
    #_DevDiagDef("device_id", "Device ID (Long)"),
]

_REFRESH_BEFORE_SECONDS = 12 * 60 * 60  # 12h


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Ensure we have initial data so we can create per-device entities immediately.
    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    base_entities: list[SensorEntity] = [
        DreamcatcherUserSensor(coordinator, entry),
        DreamcatcherTokenExpireSensor(coordinator, entry),
        #DreamcatcherRestEndpointSensor(entry),
        #DreamcatcherMqttEndpointSensor(entry),
    ]

    per_device_entities: list[SensorEntity] = []
    known: set[tuple[str, str]] = set()

    devices = (coordinator.data or {}).get("shared_devices") or {}
    if isinstance(devices, dict):
        for dev_id in devices.keys():
            for d in DEV_DIAG_DEFS:
                known.add((dev_id, d.key))
                per_device_entities.append(DreamcatcherDeviceDiagSensor(coordinator, entry, dev_id, d))

    async_add_entities(base_entities + per_device_entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        devices_now = (coordinator.data or {}).get("shared_devices") or {}
        if not isinstance(devices_now, dict):
            return

        new_entities: list[SensorEntity] = []
        for dev_id in devices_now.keys():
            for d in DEV_DIAG_DEFS:
                k = (dev_id, d.key)
                if k in known:
                    continue
                known.add(k)
                new_entities.append(DreamcatcherDeviceDiagSensor(coordinator, entry, dev_id, d))

        if new_entities:
            hass.async_create_task(platform.async_add_entities(new_entities))

    coordinator.async_add_listener(_on_update)


class DreamcatcherUserSensor(CoordinatorEntity[DreamcatcherCoordinator], SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_user"
        self._attr_name = "DreamCatcher Life User"
        self._attr_icon = "mdi:account"

    @property
    def native_value(self) -> str | None:
        ui_runtime = (self.coordinator.data or {}).get("userInfo") or {}
        if ui_runtime.get("alias") or ui_runtime.get("email"):
            return ui_runtime.get("alias") or ui_runtime.get("email")

        ui_persisted = self._entry.data.get(CONF_USER_INFO) or {}
        if isinstance(ui_persisted, dict) and (ui_persisted.get("alias") or ui_persisted.get("email")):
            return ui_persisted.get("alias") or ui_persisted.get("email")

        return self._entry.data.get(CONF_EMAIL)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ui_runtime = (self.coordinator.data or {}).get("userInfo") or {}
        ui_persisted = self._entry.data.get(CONF_USER_INFO) or {}
        if not isinstance(ui_persisted, dict):
            ui_persisted = {}

        ui_effective = ui_runtime if (ui_runtime.get("alias") or ui_runtime.get("email")) else ui_persisted

        d = self._entry.data

        expire_at_runtime = (self.coordinator.data or {}).get("expireAt")
        expire_at_persisted = d.get(CONF_EXPIRE_AT)
        expire_at_effective = expire_at_runtime or expire_at_persisted

        last_login_runtime = (self.coordinator.data or {}).get("lastLogin")
        last_login_persisted = self._entry.data.get(CONF_LAST_LOGIN)
        last_login_effective = last_login_runtime or last_login_persisted

        now = int(dt_util.utcnow().timestamp())
        remaining = None
        refresh_due = None
        if expire_at_effective:
            remaining = int(expire_at_effective) - now
            refresh_due = remaining <= _REFRESH_BEFORE_SECONDS

        return {
            # Persisted (config entry)
            "config_email": d.get(CONF_EMAIL),
            "config_country_code": d.get(CONF_COUNTRY_CODE),
            "config_uuid": d.get(CONF_UUID),
            "token_persisted_present": bool(d.get(CONF_TOKEN)),
            "expireAt_persisted": expire_at_persisted,
            "lastLogin_persisted": last_login_persisted,
            "userInfo_persisted": ui_persisted,

            # Runtime (API/coordinator)
            "api_alias": ui_runtime.get("alias"),
            "api_email": ui_runtime.get("email"),
            "api_userId": ui_runtime.get("userId"),
            "api_region": ui_runtime.get("region"),
            "api_userDB": ui_runtime.get("userDB"),
            "api_userIdType": ui_runtime.get("userIdType"),
            "lastLogin": (self.coordinator.data or {}).get("lastLogin"),
            "expireAt_runtime": expire_at_runtime,
            "lastLogin_runtime": last_login_runtime,
            "userInfo_runtime": ui_runtime,

            # Derived / consistency helpers
            "expireAt_effective": expire_at_effective,
            "lastLogin_effective": last_login_effective,
            "userInfo_effective": ui_effective,
            "token_runtime_present": bool(getattr(self.coordinator, "token", None)),
            "remaining_seconds": remaining,
            "refresh_due_12h": refresh_due,
            "value_source": "api" if (ui_runtime.get("alias") or ui_runtime.get("email")) else "config",
        }

class DreamcatcherTokenExpireSensor(CoordinatorEntity[DreamcatcherCoordinator], SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_token_expire"
        self._attr_name = "DreamCatcher Life Token Expire"
        self._attr_icon = "mdi:clock-end"

    @property
    def native_value(self):
        # Prefer runtime value; fallback to persisted
        expire_at_runtime = (self.coordinator.data or {}).get("expireAt")
        expire_at_persisted = self._entry.data.get(CONF_EXPIRE_AT)
        expire_at = expire_at_runtime or expire_at_persisted
        if not expire_at:
            return None
        return dt_util.utc_from_timestamp(int(expire_at))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._entry.data

        expire_at_runtime = (self.coordinator.data or {}).get("expireAt")
        expire_at_persisted = d.get(CONF_EXPIRE_AT)
        expire_at_effective = expire_at_runtime or expire_at_persisted

        last_login_runtime = (self.coordinator.data or {}).get("lastLogin")
        last_login_persisted = self._entry.data.get(CONF_LAST_LOGIN)
        last_login_effective = last_login_runtime or last_login_persisted

        now = int(dt_util.utcnow().timestamp())

        def _remaining(x: Any) -> int | None:
            if not x:
                return None
            try:
                return int(x) - now
            except Exception:
                return None

        rem_effective = _remaining(expire_at_effective)

        def _ts_to_local_dt(ts: Any):
            try:
                if not ts:
                    return None
                return dt_util.as_local(dt_util.utc_from_timestamp(int(ts)))
            except Exception:
                return None

        return {
            # Persisted vs runtime
            "expireAt_persisted": _ts_to_local_dt(expire_at_persisted),
            "expireAt_runtime": _ts_to_local_dt(expire_at_runtime),
            "expireAt_effective": _ts_to_local_dt(expire_at_effective),

            "lastLogin_persisted": last_login_persisted,
            "lastLogin_runtime": last_login_runtime,
            "lastLogin_effective": last_login_effective,

            # Token presence (no full token in attributes)
            "token_persisted_present": bool(d.get(CONF_TOKEN)),
            "token_runtime_present": bool(getattr(self.coordinator, "token", None)),

            # Derived
            "remaining_seconds_effective": rem_effective,
            "refresh_due_12h": (rem_effective is not None and rem_effective <= _REFRESH_BEFORE_SECONDS),
            "value_source": "runtime" if expire_at_runtime else ("persisted" if expire_at_persisted else None),
        }


# class DreamcatcherRestEndpointSensor(SensorEntity):
#     _attr_entity_category = EntityCategory.DIAGNOSTIC

#     def __init__(self, entry: ConfigEntry) -> None:
#         self._entry = entry
#         self._attr_unique_id = f"{entry.entry_id}_rest_endpoint"
#         self._attr_name = "DreamCatcher REST Endpoint"
#         self._attr_icon = "mdi:web"

#     @property
#     def should_poll(self) -> bool:
#         return False

#     @property
#     def native_value(self) -> str | None:
#         d = self._entry.data
#         host = d.get(CONF_AM_DOMAIN)
#         port = d.get(CONF_AM_PORT)
#         if not host or not port:
#             return None
#         return f"https://{host}:{port}"

#     @property
#     def extra_state_attributes(self) -> dict[str, Any]:
#         d = self._entry.data
#         return {
#             "am_domain": d.get(CONF_AM_DOMAIN),
#             "am_ip": d.get(CONF_AM_IP),
#             "am_port": d.get(CONF_AM_PORT),
#         }


# class DreamcatcherMqttEndpointSensor(SensorEntity):
#     _attr_entity_category = EntityCategory.DIAGNOSTIC

#     def __init__(self, entry: ConfigEntry) -> None:
#         self._entry = entry
#         self._attr_unique_id = f"{entry.entry_id}_mqtt_endpoint"
#         self._attr_name = "DreamCatcher MQTT Endpoint"
#         self._attr_icon = "mdi:web"

#     @property
#     def should_poll(self) -> bool:
#         return False

#     @property
#     def native_value(self) -> str | None:
#         d = self._entry.data
#         host = d.get(CONF_MQTT_DOMAIN)
#         port = d.get(CONF_MQTT_PORT)
#         if not host or not port:
#             return None
#         return f"{host}:{port}"

#     @property
#     def extra_state_attributes(self) -> dict[str, Any]:
#         d = self._entry.data
#         return {
#             "mqtt_domain": d.get(CONF_MQTT_DOMAIN),
#             "mqtt_ip": d.get(CONF_MQTT_IP),
#             "mqtt_port": d.get(CONF_MQTT_PORT),
#         }


class DreamcatcherDeviceDiagSensor(CoordinatorEntity[DreamcatcherCoordinator], SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DreamcatcherCoordinator,
        entry: ConfigEntry,
        device_id: str,
        definition: _DevDiagDef,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._def = definition
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_{definition.key}"
        self._attr_name = definition.name

    @property
    def _dev(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("shared_devices", {}).get(self._device_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        d = self._dev
        alias = d.get("alias") or self._device_id
        product_id = d.get("product_id") or d.get("mpid") or ""
        dtype = d.get("dtype") or ""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=alias,
            manufacturer="Chuango",
            model=dtype or None,
            model_id=str(product_id) if product_id else None,
        )

    @property
    def native_value(self):
        d = self._dev
        mqtt = d.get("mqtt") or {}
        dm = d.get("dm") or {}

        k = self._def.key

        if k == "device_id":
            return self._device_id

        if k == "mqtt_endpoint":
            dom = mqtt.get("domain")
            port = mqtt.get("port")
            if dom and port:
                return f"{dom}:{port}"
            return None

        if k == "mqtt_domain":
            return mqtt.get("domain")

        if k == "mqtt_ip":
            return mqtt.get("ip")

        if k == "mqtt_port":
            return mqtt.get("port")

        if k == "mqtt_token":
            tok = mqtt.get("token")
            if not tok:
                return None
            if isinstance(tok, str) and len(tok) > 12:
                return f"{tok[:4]}…{tok[-4:]}"
            return tok

        if k == "mqtt_username":
            try:
                return self.coordinator.get_mqtt_username(self._device_id)
            except Exception:
                return None

        if k == "mqtt_client_id":
            try:
                return self.coordinator.get_mqtt_client_id(self._device_id)
            except Exception:
                return None
        
        if k == "mqtt_subscribe":
            try:
                return self.coordinator.get_mqtt_subscribe_topic(self._device_id)
            except Exception:
                return None

        if k == "dm_endpoint":
            dom = dm.get("domain")
            port = dm.get("port")
            if dom and port:
                return f"https://{dom}:{port}"
            return None

        if k == "dm_domain":
            return dm.get("domain")

        if k == "dm_ip":
            return dm.get("ip")

        if k == "dm_port":
            return dm.get("port")

        if k == "user_auth":
            return d.get("userAuth")

        if k == "dtype":
            return d.get("dtype")

        if k == "product_id":
            return d.get("product_id")

        if k == "dev_id_int":
            return d.get("devIdInt")

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._def.key != "mqtt_token":
            return None
        mqtt = (self._dev.get("mqtt") or {})
        tok = mqtt.get("token")
        return {"token": tok} if tok else None
