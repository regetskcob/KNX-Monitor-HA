"""KNX Monitor: the add-on as a device in Home Assistant.

Sensors, recording switch, device triggers, services, diagnostics and repairs
for the KNX Monitor add-on. Set up through the add-on's discovery; while set
up, the add-on stops announcing the same entities over MQTT.
"""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import KnxMonitorApi, KnxMonitorError
from .const import CONF_TOKEN, DOMAIN
from .coordinator import KnxMonitorConfigEntry, KnxMonitorCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services exist once, independent of the entry."""
    async_setup_services(hass)
    return True


def _api(hass: HomeAssistant, entry: KnxMonitorConfigEntry) -> KnxMonitorApi:
    return KnxMonitorApi(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_TOKEN]
    )


async def async_setup_entry(hass: HomeAssistant, entry: KnxMonitorConfigEntry) -> bool:
    """Connect to the add-on and take over the entities from MQTT."""
    coordinator = KnxMonitorCoordinator(hass, entry, _api(hass, entry))
    await coordinator.async_config_entry_first_refresh()
    if not coordinator.data.get("claimed"):
        try:
            await coordinator.api.claim(True)
        except KnxMonitorError as err:
            # Not alongside the MQTT entities: Home Assistant tries again later.
            raise ConfigEntryNotReady(f"KNX Monitor: could not take over the MQTT entities: {err}") from err
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KnxMonitorConfigEntry) -> bool:
    """Unload the platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: KnxMonitorConfigEntry) -> None:
    """Integration removed: the add-on announces its MQTT entities again.

    If the add-on is not reachable now, it gives them back by itself after an
    hour without a request from the integration.
    """
    try:
        await _api(hass, entry).claim(False)
    except KnxMonitorError as err:
        _LOGGER.warning("KNX Monitor: could not give the entities back to MQTT: %s", err)
