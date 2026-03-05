from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator
from .utils import part_md_label, part_zone_change_allowed, resolve_device_model

# Alarm volume: 0=Mute, 1=Low, 2=Medium, 3=High
VOLUME_OPTIONS = ["mute", "low", "medium", "high"]
VOLUME_VALUE_TO_OPTION = {0: "mute", 1: "low", 2: "medium", 3: "high"}
VOLUME_OPTION_TO_VALUE = {v: k for k, v in VOLUME_VALUE_TO_OPTION.items()}

# Alarm duration in minutes (1-5)
DURATION_OPTIONS = ["1", "2", "3", "4", "5"]

# Part zone mapping (OV300Zone)
ZONE_OPTIONS = ["zone_24h", "zone_normal", "zone_home", "zone_delay"]
ZONE_VALUE_TO_OPTION = {0: "zone_24h", 1: "zone_normal", 2: "zone_home", 3: "zone_delay"}
ZONE_OPTION_TO_VALUE = {v: k for k, v in ZONE_VALUE_TO_OPTION.items()}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[tuple[str, str]] = set()
    entities: list[SelectEntity] = []

    for dev_id in coordinator.get_device_ids():
        known.add((dev_id, "alarm_volume"))
        known.add((dev_id, "alarm_duration"))
        entities.append(AlarmVolumeSelect(coordinator, entry, dev_id))
        entities.append(AlarmDurationSelect(coordinator, entry, dev_id))

    def _build_part_zone_entities() -> list[SelectEntity]:
        built: list[SelectEntity] = []
        mqtt_state = (coordinator.data or {}).get("mqtt_state") or {}
        if not isinstance(mqtt_state, dict):
            return built

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
                if "z" not in part:
                    continue
                key = (dev_id, f"part_zone_{part_id}")
                if key in known:
                    continue
                known.add(key)
                built.append(PartZoneSelect(coordinator, entry, dev_id, int(part_id)))
        return built

    entities.extend(_build_part_zone_entities())

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new: list[SelectEntity] = []
        for dev_id in now_ids:
            if (dev_id, "alarm_volume") not in known:
                known.add((dev_id, "alarm_volume"))
                new.append(AlarmVolumeSelect(coordinator, entry, dev_id))
            if (dev_id, "alarm_duration") not in known:
                known.add((dev_id, "alarm_duration"))
                new.append(AlarmDurationSelect(coordinator, entry, dev_id))
        new.extend(_build_part_zone_entities())
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class _BaseChuangoSelect(CoordinatorEntity[DreamcatcherCoordinator], SelectEntity):
    """Base class for Chuango select entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.device_id = device_id

    @property
    def _dev(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("shared_devices", {}).get(self.device_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        d = self._dev
        alias = d.get("alias") or self.device_id
        product_id = d.get("product_id") or d.get("mpid") or ""
        dtype = d.get("dtype") or ""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=alias,
            manufacturer="Chuango",
            model=resolve_device_model(dtype, product_id),
            model_id=str(product_id) if product_id else None,
        )

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self.device_id) or {}
            return st if isinstance(st, dict) else {}
        return {}

    @property
    def available(self) -> bool:
        online = self._st.get("online")
        return bool(online) if online is not None else True


class AlarmVolumeSelect(_BaseChuangoSelect):
    """Select entity for alarm volume (Mute / Low / Medium / High)."""

    _attr_translation_key = "alarm_volume"
    _attr_icon = "mdi:volume-high"
    _attr_options = VOLUME_OPTIONS

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_alarm_volume"

    @property
    def current_option(self) -> str | None:
        val = self._st.get("alarm_volume")
        if val is None:
            return None
        try:
            return VOLUME_VALUE_TO_OPTION.get(int(val))
        except (ValueError, TypeError):
            return None

    async def async_select_option(self, option: str) -> None:
        value = VOLUME_OPTION_TO_VALUE.get(option)
        if value is None:
            return
        await self.coordinator.async_send_host_conf(self.device_id, volume=value)


class AlarmDurationSelect(_BaseChuangoSelect):
    """Select entity for alarm duration in minutes."""

    _attr_translation_key = "alarm_duration"
    _attr_icon = "mdi:timer-outline"
    _attr_options = DURATION_OPTIONS

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_alarm_duration"

    @property
    def current_option(self) -> str | None:
        val = self._st.get("alarm_duration")
        if val is None:
            return None
        try:
            s = str(int(val))
            return s if s in DURATION_OPTIONS else None
        except (ValueError, TypeError):
            return None

    async def async_select_option(self, option: str) -> None:
        try:
            minutes = int(option)
        except (ValueError, TypeError):
            return
        await self.coordinator.async_send_host_conf(self.device_id, alarm_duration=minutes)


class PartZoneSelect(CoordinatorEntity[DreamcatcherCoordinator], SelectEntity):
    """Select entity for a part/accessory zone assignment."""

    _attr_has_entity_name = True
    _attr_translation_key = "part_zone"
    _attr_options = ZONE_OPTIONS
    _attr_icon = "mdi:vector-square"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str, part_id: int) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._part_id = part_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_part_{part_id}_zone"

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self._device_id) or {}
            return st if isinstance(st, dict) else {}
        return {}

    @property
    def _part(self) -> dict[str, Any] | None:
        parts = self._st.get("parts") or []
        if not isinstance(parts, list):
            return None
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("id") == self._part_id:
                return part
        return None

    @property
    def available(self) -> bool:
        online = self._st.get("online")
        part_exists = self._part is not None
        return (bool(online) if online is not None else True) and part_exists

    @property
    def device_info(self) -> DeviceInfo:
        part = self._part or {}
        part_name = part.get("n") or f"Part {self._part_id}"
        category = part.get("c")
        ptype = part.get("t")
        model = "Sensor" if category == 129 else ("Key Fob" if category == 130 else f"Accessory (c={category}, t={ptype})")

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device_id}_part_{self._part_id}")},
            name=part_name,
            manufacturer="Chuango",
            model=model,
            via_device=(DOMAIN, self._device_id),
        )

    @property
    def current_option(self) -> str | None:
        part = self._part
        if not part:
            return None
        z = part.get("z")
        if z is None:
            return None
        try:
            return ZONE_VALUE_TO_OPTION.get(int(z))
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        part = self._part or {}
        md_raw = part.get("md")
        zone_raw = part.get("z")
        try:
            md = int(md_raw) if md_raw is not None else None
        except (TypeError, ValueError):
            md = None
        try:
            zone = int(zone_raw) if zone_raw is not None else None
        except (TypeError, ValueError):
            zone = None

        return {
            "part_id": self._part_id,
            "mode": md_raw,
            "mode_label": part_md_label(md),
            "zone": zone_raw,
            "zone_change_allowed": part_zone_change_allowed(md, zone),
        }

    async def async_select_option(self, option: str) -> None:
        part = self._part
        if not part:
            return

        md_raw = part.get("md")
        zone_raw = part.get("z")
        try:
            md = int(md_raw) if md_raw is not None else None
        except (TypeError, ValueError):
            md = None
        try:
            current_zone = int(zone_raw) if zone_raw is not None else None
        except (TypeError, ValueError):
            current_zone = None

        if not part_zone_change_allowed(md, current_zone):
            raise HomeAssistantError("Zone change is blocked for this accessory (md=0 in zone 0).")

        zone = ZONE_OPTION_TO_VALUE.get(option)
        if zone is None:
            return
        await self.coordinator.async_send_modify_part_zone(self._device_id, self._part_id, zone)
