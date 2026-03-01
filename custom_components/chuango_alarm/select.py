from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator

# Alarm volume: 0=Mute, 1=Low, 2=Medium, 3=High
VOLUME_OPTIONS = ["mute", "low", "medium", "high"]
VOLUME_VALUE_TO_OPTION = {0: "mute", 1: "low", 2: "medium", 3: "high"}
VOLUME_OPTION_TO_VALUE = {v: k for k, v in VOLUME_VALUE_TO_OPTION.items()}

# Alarm duration in minutes (1-5)
DURATION_OPTIONS = ["1", "2", "3", "4", "5"]


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
            model=dtype or None,
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
