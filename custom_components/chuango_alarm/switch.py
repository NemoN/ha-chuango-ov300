from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[str] = set()
    entities: list[SwitchEntity] = []

    for dev_id in coordinator.get_device_ids():
        known.add(dev_id)
        entities.append(ArmDisarmBeepSwitch(coordinator, entry, dev_id))

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new = [ArmDisarmBeepSwitch(coordinator, entry, dev_id) for dev_id in now_ids if dev_id not in known]
        for e in new:
            known.add(e.device_id)
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class ArmDisarmBeepSwitch(CoordinatorEntity[DreamcatcherCoordinator], SwitchEntity):
    """Switch to enable/disable the arm/disarm beep tone."""

    _attr_has_entity_name = True
    _attr_translation_key = "arm_disarm_beep"
    _attr_icon = "mdi:volume-vibrate"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_arm_beep"

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

    @property
    def is_on(self) -> bool | None:
        val = self._st.get("arm_beep")
        if val is None:
            return None
        try:
            return int(val) == 1
        except (ValueError, TypeError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_host_conf(self.device_id, arm_beep=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_host_conf(self.device_id, arm_beep=0)
