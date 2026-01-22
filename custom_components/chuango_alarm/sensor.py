from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    DOMAIN,
)
from .coordinator import DreamcatcherCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            DreamcatcherUserSensor(coordinator, entry),
            DreamcatcherTokenExpireSensor(coordinator, entry),
            DreamcatcherRestEndpointSensor(entry),
            DreamcatcherMqttEndpointSensor(entry),
        ]
    )


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
        ui = (self.coordinator.data or {}).get("userInfo") or {}
        return ui.get("alias") or ui.get("email")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ui = (self.coordinator.data or {}).get("userInfo") or {}
        return {
            "userId": ui.get("userId"),
            "region": ui.get("region"),
            "userDB": ui.get("userDB"),
            "userIdType": ui.get("userIdType"),
            "lastLogin": (self.coordinator.data or {}).get("lastLogin"),
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
        expire_at = (self.coordinator.data or {}).get("expireAt")
        if not expire_at:
            return None
        return dt_util.utc_from_timestamp(int(expire_at))


class DreamcatcherRestEndpointSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_rest_endpoint"
        self._attr_name = "DreamCatcher REST API Endpoint"
        self._attr_icon = "mdi:web"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def native_value(self) -> str | None:
        d = self._entry.data
        host = d.get(CONF_AM_DOMAIN)
        port = d.get(CONF_AM_PORT)
        if not host or not port:
            return None
        return f"https://{host}:{port}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._entry.data
        return {
            "am_domain": d.get(CONF_AM_DOMAIN),
            "am_ip": d.get(CONF_AM_IP),
            "am_port": d.get(CONF_AM_PORT),
        }


class DreamcatcherMqttEndpointSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mqtt_endpoint"
        self._attr_name = "DreamCatcher MQTT Endpoint"
        self._attr_icon = "mdi:web"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def native_value(self) -> str | None:
        d = self._entry.data
        host = d.get(CONF_MQTT_DOMAIN)
        port = d.get(CONF_MQTT_PORT)
        if not host or not port:
            return None
        return f"{host}:{port}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._entry.data
        return {
            "mqtt_domain": d.get(CONF_MQTT_DOMAIN),
            "mqtt_ip": d.get(CONF_MQTT_IP),
            "mqtt_port": d.get(CONF_MQTT_PORT),
        }
