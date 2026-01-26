from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelState,
    AlarmControlPanelEntityFeature,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
# from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[str] = set()
    entities: list[AlarmControlPanelEntity] = []

    for dev_id in coordinator.get_device_ids():
        known.add(dev_id)
        entities.append(DreamcatcherAlarmPanel(coordinator, entry, dev_id))

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new = [DreamcatcherAlarmPanel(coordinator, entry, dev_id) for dev_id in now_ids if dev_id not in known]
        for e in new:
            known.add(e.device_id)
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)

# https://developers.home-assistant.io/docs/core/entity/alarm-control-panel/
class DreamcatcherAlarmPanel(CoordinatorEntity[DreamcatcherCoordinator], AlarmControlPanelEntity):
    _attr_has_entity_name = True
    _attr_code_arm_required = False
    _attr_code_format = None

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_alarm"
        self._attr_name = "Alarm"
        self._attr_supported_features = (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
        )
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
        return bool(online) if online is not None else True # unknown -> not unavailable

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        st = self._st
        mode = st.get("mode")
        alarm = st.get("alarm")

        # Alarm/Triggered: wenn alarm==1 oder trig>0
        try:
            if int(alarm or 0) == 1:
                return AlarmControlPanelState.TRIGGERED
        except Exception:
            pass

        #trig = st.get("trig")
        #try:
        #    if int(trig or 0) > 0:
        #        return AlarmControlPanelState.TRIGGERED
        #except Exception:
        #    pass

        if mode == "d":
            return AlarmControlPanelState.DISARMED
        if mode in ("a", "A"):
            return AlarmControlPanelState.ARMED_AWAY
        if mode in ("h", "H"):
            return AlarmControlPanelState.ARMED_HOME

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self._st
        return {
            "online": st.get("online"),
            "online_msg": st.get("online_msg"),
            "mode": st.get("mode"),
            "alarm": st.get("alarm"),
            "trig": st.get("trig"),
            "power": st.get("power"),
            "device_time": st.get("time"),
            "last_seen": st.get("last_seen"),
            "tz": st.get("tz"),
            "fw": st.get("fw"),
            "ip_local": st.get("ip_local"),
            "last_topic": st.get("last_topic"),
        }
    
    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        #await self.coordinator.async_send_alarm_command(self.device_id, "h", code=code)
        await self.coordinator.async_send_alarm_command(self.device_id, "h")

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        #await self.coordinator.async_send_alarm_command(self.device_id, "a", code=code)
        await self.coordinator.async_send_alarm_command(self.device_id, "a")

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        #await self.coordinator.async_send_alarm_command(self.device_id, "d", code=code)
        await self.coordinator.async_send_alarm_command(self.device_id, "d")