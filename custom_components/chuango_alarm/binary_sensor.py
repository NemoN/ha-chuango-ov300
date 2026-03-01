from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator

# Category 129 = sensors (door/window/PIR), category 130 = key fobs / remotes
CATEGORY_SENSOR = 129
CATEGORY_KEYFOB = 130

# Zone mapping: z=1 -> perimeter (instant), z=2 -> interior (delay/PIR)
ZONE_PERIMETER = 1
ZONE_INTERIOR = 2


def _infer_device_class(part: dict[str, Any]) -> BinarySensorDeviceClass:
    """Infer device class from part name and zone."""
    name = (part.get("n") or "").lower()
    zone = part.get("z")

    # PIR / motion sensors
    if "pir" in name or zone == ZONE_INTERIOR:
        return BinarySensorDeviceClass.MOTION

    # Door sensors
    if "tuer" in name or "tür" in name or "door" in name or "haustuer" in name or "haustür" in name:
        return BinarySensorDeviceClass.DOOR

    # Window sensors
    if "fenster" in name or "window" in name:
        return BinarySensorDeviceClass.WINDOW

    # Terrace door (treat as door)
    if "terasse" in name or "terrasse" in name or "terrace" in name:
        return BinarySensorDeviceClass.DOOR

    # Default for perimeter zone: opening
    if zone == ZONE_PERIMETER:
        return BinarySensorDeviceClass.OPENING

    return BinarySensorDeviceClass.OPENING


def _zone_label(zone: int | None) -> str:
    if zone == ZONE_PERIMETER:
        return "Perimeter"
    if zone == ZONE_INTERIOR:
        return "Interior"
    return f"Zone {zone}" if zone is not None else "Unknown"


def _model_from_part(part: dict[str, Any]) -> str:
    """Derive a model string from part category and type."""
    c = part.get("c")
    t = part.get("t")
    if c == CATEGORY_SENSOR:
        return "Sensor"
    if c == CATEGORY_KEYFOB:
        return "Key Fob"
    return f"Accessory (c={c}, t={t})"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[str] = set()  # unique_id set

    def _build_entities() -> list[BinarySensorEntity]:
        """Build entities for all known parts across all devices."""
        entities: list[BinarySensorEntity] = []
        mqtt_state = (coordinator.data or {}).get("mqtt_state") or {}
        if not isinstance(mqtt_state, dict):
            return entities

        for dev_id in coordinator.get_device_ids():
            dev_state = mqtt_state.get(dev_id) or {}
            parts = dev_state.get("parts") or []
            if not isinstance(parts, list):
                continue

            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_id = part.get("id")
                if part_id is None:
                    continue

                uid = f"{entry.entry_id}_{dev_id}_part_{part_id}"
                if uid in known:
                    continue
                known.add(uid)

                cat = part.get("c")
                if cat == CATEGORY_SENSOR:
                    entities.append(
                        ChuangoAccessorySensor(coordinator, entry, dev_id, part)
                    )
                elif cat == CATEGORY_KEYFOB:
                    entities.append(
                        ChuangoKeyfobSensor(coordinator, entry, dev_id, part)
                    )
        return entities

    # Initial entities from already-loaded parts (if any)
    initial = _build_entities()
    if initial:
        async_add_entities(initial)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        new = _build_entities()
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class ChuangoAccessorySensor(CoordinatorEntity[DreamcatcherCoordinator], BinarySensorEntity):
    """Binary sensor for a Chuango alarm accessory (door/window/PIR sensor).

    State is unknown (None) because the alarm panel only reports
    which sensor triggered an alarm, not continuous open/close status.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DreamcatcherCoordinator,
        entry: ConfigEntry,
        device_id: str,
        part: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._part_id = part.get("id")
        self._part_name = part.get("n") or f"Sensor {self._part_id}"
        self._part = dict(part)

        self._attr_unique_id = f"{entry.entry_id}_{device_id}_part_{self._part_id}"
        self._attr_name = self._part_name
        self._attr_device_class = _infer_device_class(part)

    @property
    def device_info(self) -> DeviceInfo:
        """Register as sub-device of the alarm panel."""
        d = (self.coordinator.data or {}).get("shared_devices", {}).get(self._device_id, {})
        alias = d.get("alias") or self._device_id

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device_id}_part_{self._part_id}")},
            name=self._part_name,
            manufacturer="Chuango",
            model=_model_from_part(self._part),
            via_device=(DOMAIN, self._device_id),
        )

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self._device_id) or {}
            return st if isinstance(st, dict) else {}
        return {}

    @property
    def available(self) -> bool:
        online = self._st.get("online")
        return bool(online) if online is not None else True

    @property
    def is_on(self) -> bool | None:
        """We don't have real-time sensor status; return None (unknown)."""
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "part_id": self._part.get("id"),
            "sensor_index": self._part.get("si"),
            "category": self._part.get("c"),
            "type": self._part.get("t"),
            "zone": self._part.get("z"),
            "zone_label": _zone_label(self._part.get("z")),
            "mode": self._part.get("md"),
        }


class ChuangoKeyfobSensor(CoordinatorEntity[DreamcatcherCoordinator], BinarySensorEntity):
    """Binary sensor for a Chuango key fob / remote.

    State represents whether the key fob is active (ss=0 -> active).
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(
        self,
        coordinator: DreamcatcherCoordinator,
        entry: ConfigEntry,
        device_id: str,
        part: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._part_id = part.get("id")
        self._part_name = part.get("n") or f"Key Fob {self._part_id}"
        self._part = dict(part)

        self._attr_unique_id = f"{entry.entry_id}_{device_id}_part_{self._part_id}"
        self._attr_name = self._part_name

    @property
    def device_info(self) -> DeviceInfo:
        """Register as sub-device of the alarm panel."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device_id}_part_{self._part_id}")},
            name=self._part_name,
            manufacturer="Chuango",
            model=_model_from_part(self._part),
            via_device=(DOMAIN, self._device_id),
        )

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self._device_id) or {}
            return st if isinstance(st, dict) else {}
        return {}

    @property
    def available(self) -> bool:
        online = self._st.get("online")
        return bool(online) if online is not None else True

    @property
    def is_on(self) -> bool | None:
        """Key fob presence: ss=0 means active/present."""
        ss = self._part.get("ss")
        if ss is None:
            return None
        try:
            return int(ss) == 0
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "part_id": self._part.get("id"),
            "sensor_index": self._part.get("si"),
            "category": self._part.get("c"),
            "type": self._part.get("t"),
            "status": self._part.get("ss"),
        }
