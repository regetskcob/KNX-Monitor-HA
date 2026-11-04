"""Services: create the installation report, export the history."""

from __future__ import annotations

import re
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import KnxMonitorError
from .const import DOMAIN, SERVICE_CREATE_REPORT, SERVICE_EXPORT_HISTORY
from .coordinator import KnxMonitorCoordinator

EXPORT_SCHEMA = vol.Schema(
    {
        vol.Optional("days", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
        vol.Optional("everything", default=False): cv.boolean,
    }
)

# Subfolder of the configuration directory the exports go to.
EXPORT_DIR = "knx_monitor"


def _coordinator(hass: HomeAssistant) -> KnxMonitorCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services of KNX Monitor."""

    async def create_report(call: ServiceCall) -> ServiceResponse:
        try:
            report = await _coordinator(hass).api.create_report()
        except KnxMonitorError as err:
            raise HomeAssistantError(f"KNX Monitor: {err}") from err
        return report

    async def export_history(call: ServiceCall) -> ServiceResponse:
        days = None if call.data["everything"] else call.data["days"]
        try:
            content, disposition = await _coordinator(hass).api.history(days)
        except KnxMonitorError as err:
            raise HomeAssistantError(f"KNX Monitor: {err}") from err
        match = re.search(r'filename="([A-Za-z0-9._+-]+)"', disposition)
        name = match.group(1) if match else ("knx-monitor-history.zip" if days is None else "knx-monitor-history.xml")
        folder = Path(hass.config.path(EXPORT_DIR))

        def write() -> Path:
            folder.mkdir(exist_ok=True)
            target = folder / name
            target.write_bytes(content)
            return target

        target = await hass.async_add_executor_job(write)
        return {"path": str(target), "bytes": len(content)}

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_REPORT, create_report, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_HISTORY,
        export_history,
        schema=EXPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
