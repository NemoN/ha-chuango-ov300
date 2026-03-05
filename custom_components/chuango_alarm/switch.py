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
from .utils import resolve_device_model

MTYPE_KEYFOB = 2


def _part_is_keyfob(part: dict[str, Any]) -> bool:
    c_val = part.get("c")
    if c_val is not None:
        try:
            return (int(c_val) & 0x0F) == MTYPE_KEYFOB
        except (ValueError, TypeError):
            pass

    t_val = part.get("t")
    try:
        return int(t_val) == 44
    except (ValueError, TypeError):
        return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[tuple[str, str]] = set()
    entities: list[SwitchEntity] = []

    for dev_id in coordinator.get_device_ids():
        known.add((dev_id, "arm_disarm_beep"))
        known.add((dev_id, "entry_delay_tone"))
        known.add((dev_id, "exit_delay_tone"))
        known.add((dev_id, "test_mode"))
        entities.append(ArmDisarmBeepSwitch(coordinator, entry, dev_id))
        entities.append(EntryDelayToneSwitch(coordinator, entry, dev_id))
        entities.append(ExitDelayToneSwitch(coordinator, entry, dev_id))
        entities.append(TestModeSwitch(coordinator, entry, dev_id))

    def _build_part_switch_entities() -> list[SwitchEntity]:
        built: list[SwitchEntity] = []
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

                key = (dev_id, f"part_enabled_{part_id}")
                if key in known:
                    pass
                else:
                    known.add(key)
                    built.append(PartEnabledSwitch(coordinator, entry, dev_id, int(part_id)))

                if _part_is_keyfob(part):
                    sos_key = (dev_id, f"part_sos_{part_id}")
                    if sos_key in known:
                        continue
                    known.add(sos_key)
                    built.append(PartSosSwitch(coordinator, entry, dev_id, int(part_id)))

        return built

    entities.extend(_build_part_switch_entities())

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        now_ids = set(coordinator.get_device_ids())
        new: list[SwitchEntity] = []
        for dev_id in now_ids:
            if (dev_id, "arm_disarm_beep") not in known:
                known.add((dev_id, "arm_disarm_beep"))
                new.append(ArmDisarmBeepSwitch(coordinator, entry, dev_id))
            if (dev_id, "entry_delay_tone") not in known:
                known.add((dev_id, "entry_delay_tone"))
                new.append(EntryDelayToneSwitch(coordinator, entry, dev_id))
            if (dev_id, "exit_delay_tone") not in known:
                known.add((dev_id, "exit_delay_tone"))
                new.append(ExitDelayToneSwitch(coordinator, entry, dev_id))
            if (dev_id, "test_mode") not in known:
                known.add((dev_id, "test_mode"))
                new.append(TestModeSwitch(coordinator, entry, dev_id))
        new.extend(_build_part_switch_entities())
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


class EntryDelayToneSwitch(ArmDisarmBeepSwitch):
    """Switch to enable/disable the entry delay reminder tone."""

    _attr_translation_key = "entry_delay_tone"
    _attr_icon = "mdi:timer-alert-outline"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_entry_delay_tone"

    @property
    def is_on(self) -> bool | None:
        val = self._st.get("entry_delay_tone")
        if val is None:
            return None
        try:
            return int(val) == 1
        except (ValueError, TypeError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_host_conf_delay(self.device_id, entry_delay_tone=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_host_conf_delay(self.device_id, entry_delay_tone=0)


class ExitDelayToneSwitch(ArmDisarmBeepSwitch):
    """Switch to enable/disable the exit delay reminder tone."""

    _attr_translation_key = "exit_delay_tone"
    _attr_icon = "mdi:timer-play-outline"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_exit_delay_tone"

    @property
    def is_on(self) -> bool | None:
        val = self._st.get("exit_delay_tone")
        if val is None:
            return None
        try:
            return int(val) == 1
        except (ValueError, TypeError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_host_conf_delay(self.device_id, exit_delay_tone=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_host_conf_delay(self.device_id, exit_delay_tone=0)


class TestModeSwitch(ArmDisarmBeepSwitch):
    """Switch to enable/disable accessories RF test mode."""

    _attr_translation_key = "test_mode"
    _attr_icon = "mdi:radio-tower"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_test_mode"

    @property
    def is_on(self) -> bool | None:
        val = self._st.get("test_mode")
        if val is None:
            return None
        try:
            return int(val) == 1
        except (ValueError, TypeError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_test_mode(self.device_id, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_test_mode(self.device_id, enabled=False)


class PartEnabledSwitch(CoordinatorEntity[DreamcatcherCoordinator], SwitchEntity):
    """Switch to enable/disable a single accessory part via modify_parts.e."""

    _attr_has_entity_name = True
    _attr_translation_key = "part_enabled"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str, part_id: int) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.device_id = device_id
        self._part_id = part_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_part_{part_id}_enabled"

    @property
    def _st(self) -> dict[str, Any]:
        mqtt_state = (self.coordinator.data or {}).get("mqtt_state") or {}
        if isinstance(mqtt_state, dict):
            st = mqtt_state.get(self.device_id) or {}
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
            identifiers={(DOMAIN, f"{self.device_id}_part_{self._part_id}")},
            name=part_name,
            manufacturer="Chuango",
            model=model,
            via_device=(DOMAIN, self.device_id),
        )

    @property
    def is_on(self) -> bool | None:
        part = self._part
        if not part:
            return None

        # Primary source (if present): explicit enable flag.
        val = part.get("e")
        if val is not None:
            try:
                # Live logs indicate: e=0 -> disabled, e=1 -> enabled
                return int(val) == 1
            except (ValueError, TypeError):
                pass

        # Fallback source: c bitfield from parts_list.
        # Observed behavior:
        # - c=129 (1000_0001) -> enabled
        # - c=1   (0000_0001) -> disabled
        c_val = part.get("c")
        if c_val is not None:
            try:
                c_int = int(c_val)
                status_bit = (c_int >> 7) & 0x01
                return status_bit == 1
            except (ValueError, TypeError):
                return None

        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_modify_part_enabled(self.device_id, self._part_id, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_modify_part_enabled(self.device_id, self._part_id, enabled=False)


class PartSosSwitch(PartEnabledSwitch):
    """Switch to enable/disable SOS for a keyfob/remote via modify_parts.ss."""

    _attr_translation_key = "part_sos"
    _attr_icon = "mdi:alarm-light"

    def __init__(self, coordinator: DreamcatcherCoordinator, entry: ConfigEntry, device_id: str, part_id: int) -> None:
        super().__init__(coordinator, entry, device_id, part_id)
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_part_{part_id}_sos"

    @property
    def is_on(self) -> bool | None:
        part = self._part
        if not part:
            return None
        val = part.get("ss")
        if val is None:
            return None
        try:
            return int(val) == 1
        except (ValueError, TypeError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_modify_part_sos(self.device_id, self._part_id, sos_enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_modify_part_sos(self.device_id, self._part_id, sos_enabled=False)
