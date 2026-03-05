from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator
from .utils import resolve_device_model


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[tuple[str, str]] = set()
    entities: list[NumberEntity] = []

    for dev_id in coordinator.get_device_ids():
        known.add((dev_id, "entry_delay"))
        known.add((dev_id, "exit_delay"))
        entities.append(EntryDelayNumber(coordinator, entry, dev_id))
        entities.append(ExitDelayNumber(coordinator, entry, dev_id))

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new: list[NumberEntity] = []
        for dev_id in now_ids:
            if (dev_id, "entry_delay") not in known:
                known.add((dev_id, "entry_delay"))
                new.append(EntryDelayNumber(coordinator, entry, dev_id))
            if (dev_id, "exit_delay") not in known:
                known.add((dev_id, "exit_delay"))
                new.append(ExitDelayNumber(coordinator, entry, dev_id))
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class _BaseDelayNumber(CoordinatorEntity[DreamcatcherCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 300
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.device_id = device_id

    @property
    def _dev(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("shared_devices", {}).get(self.device_id, {})

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self.device_id) or {}
            return st if isinstance(st, dict) else {}
        return {}

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
    def available(self) -> bool:
        online = self._st.get("online")
        return bool(online) if online is not None else True


class EntryDelayNumber(_BaseDelayNumber):
    _attr_translation_key = "entry_delay"
    _attr_icon = "mdi:timer-arrow-down"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_entry_delay"

    @property
    def native_value(self) -> float | None:
        val = self._st.get("entry_delay")
        if val is None:
            return None
        try:
            return float(int(val))
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send_host_conf_delay(self.device_id, entry_delay=int(round(value)))


class ExitDelayNumber(_BaseDelayNumber):
    _attr_translation_key = "exit_delay"
    _attr_icon = "mdi:timer-arrow-up"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_exit_delay"

    @property
    def native_value(self) -> float | None:
        val = self._st.get("exit_delay")
        if val is None:
            return None
        try:
            return float(int(val))
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send_host_conf_delay(self.device_id, exit_delay=int(round(value)))
