"""Event platform for Chuango Alarm – live alarm events + REST history."""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator

# itemEvent / iE code → event type string
EVENT_CODE_MAP: dict[int, str] = {
    11: "sos",
    12: "disarmed",
    13: "armed",
    14: "armed_home",
    15: "tamper",
    20: "ac_power_lost",
    21: "ac_power_restored",
    26: "sensor_triggered",
}

EVENT_TYPES: list[str] = list(EVENT_CODE_MAP.values())


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[str] = set()
    entities: list[ChuangoAlarmEvent] = []

    for dev_id in coordinator.get_device_ids():
        known.add(dev_id)
        entities.append(ChuangoAlarmEvent(coordinator, entry, dev_id))

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new = [
            ChuangoAlarmEvent(coordinator, entry, d)
            for d in now_ids
            if d not in known
        ]
        for e in new:
            known.add(e.device_id)
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class ChuangoAlarmEvent(
    CoordinatorEntity[DreamcatcherCoordinator], EventEntity
):
    """Alarm event entity – fires on every dout/alarm MQTT event."""

    _attr_has_entity_name = True
    _attr_translation_key = "alarm_event"
    _attr_icon = "mdi:history"
    _attr_event_types = EVENT_TYPES

    def __init__(
        self,
        coordinator: DreamcatcherCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_alarm_event"
        self._last_sn: int | None = None
        self._history_initial_fired: bool = False

    # ---- device linkage ----

    @property
    def _dev(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("shared_devices", {})
            .get(self.device_id, {})
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self.device_id)})

    # ---- mqtt state shortcut ----

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self.device_id) or {}
            return st if isinstance(st, dict) else {}
        return {}

    # ---- history as extra attributes ----

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self._st
        history = st.get("alarm_history")
        if not isinstance(history, list):
            return {"history_total": 0}

        formatted: list[dict[str, Any]] = []
        for item in history[:50]:
            evt_code = item.get("itemEvent")
            try:
                evt_i = int(evt_code)
            except (TypeError, ValueError):
                evt_i = None
            evt_type = EVENT_CODE_MAP.get(evt_i, f"unknown_{evt_code}")
            formatted.append(
                {
                    "type": evt_type,
                    "name": item.get("itemName", ""),
                    "time": item.get("time"),
                }
            )
        return {
            "history": formatted,
            "history_total": st.get("alarm_history_total", len(history)),
        }

    # ---- lifecycle ----

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Remember current sn so we don't re-fire a pre-existing event
        self._last_sn = self._st.get("alarm_evt_sn")
        # Fetch REST history in the background
        self.hass.async_create_task(
            self.coordinator.async_fetch_alarm_history(self.device_id)
        )

    # ---- coordinator update → trigger event if new ----

    @callback
    def _handle_coordinator_update(self) -> None:
        st = self._st
        sn = st.get("alarm_evt_sn")

        # Live MQTT event (new sequence number)
        if sn is not None and sn != self._last_sn:
            self._last_sn = sn
            evt_code = st.get("alarm_evt_code")
            try:
                evt_i = int(evt_code)
            except (TypeError, ValueError):
                evt_i = None

            event_type = EVENT_CODE_MAP.get(evt_i)
            if event_type:
                self._trigger_event(
                    event_type,
                    {
                        "name": st.get("alarm_evt_nick", ""),
                        "event_code": evt_i,
                        "timestamp": st.get("alarm_evt_ts"),
                    },
                )
                self._history_initial_fired = True
                return  # _trigger_event already calls async_write_ha_state

        # Fire the most recent REST history entry once to avoid "Unknown" state
        if not self._history_initial_fired:
            history = st.get("alarm_history")
            if isinstance(history, list) and history:
                latest = history[0]
                evt_code = latest.get("itemEvent")
                try:
                    evt_i = int(evt_code)
                except (TypeError, ValueError):
                    evt_i = None
                event_type = EVENT_CODE_MAP.get(evt_i)
                if event_type:
                    self._history_initial_fired = True
                    self._trigger_event(
                        event_type,
                        {
                            "name": latest.get("itemName", ""),
                            "event_code": evt_i,
                            "timestamp": latest.get("time"),
                        },
                    )
                    return

        self.async_write_ha_state()
