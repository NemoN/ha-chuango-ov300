from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
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

    known: set[str] = set()
    entities: list[ButtonEntity] = []

    for dev_id in coordinator.get_device_ids():
        known.add(f"{dev_id}_refresh")
        known.add(f"{dev_id}_sos")
        entities.append(RefreshAccessoriesButton(coordinator, entry, dev_id))
        entities.append(SosAlarmButton(coordinator, entry, dev_id))

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new: list[ButtonEntity] = []
        for dev_id in now_ids:
            refresh_key = f"{dev_id}_refresh"
            sos_key = f"{dev_id}_sos"
            if refresh_key not in known:
                known.add(refresh_key)
                new.append(RefreshAccessoriesButton(coordinator, entry, dev_id))
            if sos_key not in known:
                known.add(sos_key)
                new.append(SosAlarmButton(coordinator, entry, dev_id))
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class RefreshAccessoriesButton(CoordinatorEntity[DreamcatcherCoordinator], ButtonEntity):
    """Button to manually refresh the accessories / parts list."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_accessories"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_refresh_parts"

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

    async def async_press(self) -> None:
        """Request fresh parts list from device."""
        await self.coordinator.async_request_parts_list(self.device_id, page=1)


class SosAlarmButton(RefreshAccessoriesButton):
    """Button to trigger SOS alarm from Home Assistant."""

    _attr_translation_key = "sos_alarm"
    _attr_icon = "mdi:alarm-light"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_sos_alarm"

    async def async_press(self) -> None:
        """Trigger SOS alarm on the device."""
        await self.coordinator.async_send_alarm_command(self.device_id, "s")
