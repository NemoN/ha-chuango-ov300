"""Firmware update entity for the Chuango OV-300 alarm system.

Checks the DreamCatcher fwinfo REST endpoint for available firmware updates.
Uses Home Assistant's native UpdateEntity which provides automatic notifications
when an update is available (sidebar badge, persistent notification).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreamcatcherCoordinator
from .utils import resolve_device_model


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Chuango firmware update entities."""
    coordinator: DreamcatcherCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if coordinator.data is None:
        await coordinator.async_config_entry_first_refresh()

    known: set[str] = set()
    entities: list[UpdateEntity] = []

    devices = (coordinator.data or {}).get("shared_devices") or {}
    if isinstance(devices, dict):
        for dev_id in devices.keys():
            if dev_id not in known:
                known.add(dev_id)
                entities.append(
                    ChuangoFirmwareUpdateEntity(coordinator, entry, dev_id)
                )

    if entities:
        async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()

    @callback
    def _on_update() -> None:
        devices_now = (coordinator.data or {}).get("shared_devices") or {}
        if not isinstance(devices_now, dict):
            return
        new: list[UpdateEntity] = []
        for dev_id in devices_now.keys():
            if dev_id not in known:
                known.add(dev_id)
                new.append(ChuangoFirmwareUpdateEntity(coordinator, entry, dev_id))
        if new:
            hass.async_create_task(platform.async_add_entities(new))

    coordinator.async_add_listener(_on_update)


class ChuangoFirmwareUpdateEntity(
    CoordinatorEntity[DreamcatcherCoordinator], UpdateEntity
):
    """Represents a firmware update check for a Chuango OV-300 device."""

    _attr_has_entity_name = True
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature(0)  # read-only, no install
    _attr_translation_key = "firmware_update"

    def __init__(
        self,
        coordinator: DreamcatcherCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_firmware_update"

    # -- helpers --

    @property
    def _dev(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("shared_devices", {})
            .get(self._device_id, {})
        )

    @property
    def _fw_info(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("firmware_info", {})
            .get(self._device_id, {})
        )

    @property
    def _best_fw(self) -> dict[str, Any] | None:
        """Return the first (most relevant) firmware entry from fwList, if any."""
        fw_list = self._fw_info.get("fwList") or []
        if isinstance(fw_list, list) and fw_list:
            return fw_list[0]
        return None

    # -- device info --

    @property
    def device_info(self) -> DeviceInfo:
        d = self._dev
        alias = d.get("alias") or self._device_id
        product_id = d.get("product_id") or d.get("mpid") or ""
        dtype = d.get("dtype") or ""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=alias,
            manufacturer="Chuango",
            model=resolve_device_model(dtype, product_id),
            model_id=str(product_id) if product_id else None,
        )

    # -- UpdateEntity properties --

    @property
    def installed_version(self) -> str | None:
        """Currently installed firmware version (from MQTT dev_conf)."""
        mqtt_state = (
            (self.coordinator.data or {})
            .get("mqtt_state", {})
            .get(self._device_id, {})
        )
        fw = mqtt_state.get("fw")
        if fw:
            return str(fw)
        # Fallback: what we sent as query param
        return self._fw_info.get("installed_version")

    @property
    def latest_version(self) -> str | None:
        """Latest available firmware version from the server."""
        best = self._best_fw
        if best:
            return best.get("version") or best.get("desc")
        # No update available → return installed version (so HA shows "up to date")
        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """No public release page — the URL is just the firmware binary."""
        return None

    @property
    def release_summary(self) -> str | None:
        """Brief description of the available update."""
        best = self._best_fw
        if not best:
            return None
        parts = []
        chip = best.get("chipname")
        version = best.get("version") or best.get("desc")
        if chip:
            parts.append(f"Chip: {chip}")
        if version:
            parts.append(f"Version: {version}")
        size = best.get("size")
        if size and int(size) > 0:
            parts.append(f"Size: {size} bytes")
        return " | ".join(parts) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self._fw_info
        attrs: dict[str, Any] = {}
        if info.get("fwCount") is not None:
            attrs["fw_count"] = info["fwCount"]
        if info.get("force") is not None:
            attrs["force_update"] = bool(info["force"])
        best = self._best_fw
        if best:
            attrs["chipname"] = best.get("chipname")
            attrs["product_id"] = best.get("productID")
            attrs["zone"] = best.get("zone")
            attrs["firmware_id"] = best.get("idfirmware")
            attrs["download_url"] = best.get("url")
        return attrs
