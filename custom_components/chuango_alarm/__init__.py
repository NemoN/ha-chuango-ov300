from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DreamcatcherApiClient
from .const import DOMAIN, PLATFORMS
from .coordinator import DreamcatcherCoordinator
from .mqtt import DreamcatcherMqttManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    api = DreamcatcherApiClient(session=session, logger=_LOGGER)

    coordinator = DreamcatcherCoordinator(
        hass=hass,
        api=api,
        entry=entry,
        logger=_LOGGER,
    )

    mqtt = DreamcatcherMqttManager(hass, coordinator, _LOGGER)

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "mqtt": mqtt,
    }

    # 1) Ensure we have initial shared_devices etc.
    await coordinator.async_config_entry_first_refresh()

    # 2) Start MQTT manager (intern wartet er ggf. bis HA fully started)
    await mqtt.async_start()

    # 3) Ensure MQTT stops on reload/remove.
    # ConfigEntry will call the callback on unload and schedule the returned coroutine.
    # Do not create a Task here, otherwise HA will try to schedule a Task as a coroutine.
    entry.async_on_unload(mqtt.async_stop)

    # 4) Setup entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
    mqtt: DreamcatcherMqttManager | None = runtime.get("mqtt")

    if mqtt is not None:
        await mqtt.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        (hass.data.get(DOMAIN) or {}).pop(entry.entry_id, None)

    return unload_ok
