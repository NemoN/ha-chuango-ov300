from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator


@dataclass(frozen=True)
class _SensorDesc:
    key: str
    name: str


SENSORS = [
    _SensorDesc("user", "DreamCatcher Life User"),
    _SensorDesc("token_expire", "DreamCatcher Life Token Expire"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([DreamcatcherUserSensor(coordinator), DreamcatcherTokenExpireSensor(coordinator)])


class DreamcatcherUserSensor(CoordinatorEntity[DreamcatcherCoordinator], SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreamcatcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_user"
        self._attr_name = "DreamCatcher Life User"

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

    def __init__(self, coordinator: DreamcatcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_token_expire"
        self._attr_name = "DreamCatcher Live Token Expire"

    @property
    def native_value(self):
        expire_at = (self.coordinator.data or {}).get("expireAt")
        if not expire_at:
            return None
        return dt_util.utc_from_timestamp(int(expire_at))
