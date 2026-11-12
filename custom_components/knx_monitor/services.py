"""Services: create the installation report, export the history, run the health check."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import BinaryIO

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api import KnxMonitorError, KnxMonitorNotEnabledError, KnxMonitorNotFoundError
from .const import DOMAIN, SERVICE_CREATE_REPORT, SERVICE_EXPORT_HISTORY, SERVICE_RUN_HEALTH_CHECK
from .coordinator import KnxMonitorCoordinator

EXPORT_SCHEMA = vol.Schema(
    {
        vol.Optional("days", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
        vol.Optional("everything", default=False): cv.boolean,
    }
)

# Subfolder of the configuration directory the exports go to.
EXPORT_DIR = "knx_monitor"
# Hard cap of one export: beyond it the download is aborted and the partial
# file removed, so a runaway answer cannot fill the disk of Home Assistant.
MAX_EXPORT_BYTES = 500 * 1024 * 1024
# The body goes to disk in pieces of this size, never as a whole into memory.
CHUNK_BYTES = 1024 * 1024


def _coordinator(hass: HomeAssistant) -> KnxMonitorCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


def _too_large() -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="export_too_large",
        translation_placeholders={"limit": str(MAX_EXPORT_BYTES // (1024 * 1024))},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services of Busclear.

    All only for administrators: the report, the history and the findings of
    the health check name the whole installation, and the export writes into
    the configuration directory.
    """
    # One export at a time: two parallel downloads of the whole history would
    # double the load on the add-on and on the disk.
    export_lock = asyncio.Lock()

    async def create_report(call: ServiceCall) -> ServiceResponse:
        try:
            report = await _coordinator(hass).api.create_report()
        except KnxMonitorError as err:
            raise HomeAssistantError(f"Busclear: {err}") from err
        return report

    async def export_history(call: ServiceCall) -> ServiceResponse:
        if export_lock.locked():
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="export_running")
        async with export_lock:
            days = None if call.data["everything"] else call.data["days"]
            try:
                return await _download(hass, _coordinator(hass), days)
            except KnxMonitorError as err:
                raise HomeAssistantError(f"Busclear: {err}") from err

    async def run_health_check(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass)
        try:
            result = await coordinator.api.run_health_check()
        except KnxMonitorNotEnabledError as err:
            # Off on the server: say where to switch it on instead of "HTTP 409".
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="health_check_off") from err
        except KnxMonitorNotFoundError as err:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="health_check_unsupported") from err
        except KnxMonitorError as err:
            raise HomeAssistantError(f"Busclear: {err}") from err
        # The sensors show the new result at once, not at the next poll.
        await coordinator.async_request_refresh()
        return result

    async_register_admin_service(
        hass, DOMAIN, SERVICE_CREATE_REPORT, create_report, supports_response=SupportsResponse.OPTIONAL
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_RUN_HEALTH_CHECK, run_health_check, supports_response=SupportsResponse.OPTIONAL
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_EXPORT_HISTORY,
        export_history,
        schema=EXPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def _download(hass: HomeAssistant, coordinator: KnxMonitorCoordinator, days: int | None) -> dict[str, object]:
    """Streams the export into the configuration folder, at most MAX_EXPORT_BYTES."""
    async with coordinator.api.history(days) as resp:
        announced = resp.headers.get("Content-Length")
        if announced is not None and announced.isdigit() and int(announced) > MAX_EXPORT_BYTES:
            raise _too_large()
        match = re.search(r'filename="([A-Za-z0-9._+-]+)"', resp.headers.get("Content-Disposition", ""))
        name = match.group(1) if match else ("knx-monitor-history.zip" if days is None else "knx-monitor-history.xml")
        folder = Path(hass.config.path(EXPORT_DIR))
        target = folder / name
        # Written next to the target and renamed at the end: an aborted export
        # never leaves a truncated file under the real name.
        partial = folder / f".{name}.part"

        def open_partial() -> BinaryIO:
            folder.mkdir(exist_ok=True)
            return partial.open("wb")

        def discard(handle: BinaryIO) -> None:
            handle.close()
            partial.unlink(missing_ok=True)

        def finish(handle: BinaryIO) -> None:
            handle.close()
            partial.replace(target)

        handle = await hass.async_add_executor_job(open_partial)
        size = 0
        try:
            async for chunk in resp.content.iter_chunked(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_EXPORT_BYTES:
                    raise _too_large()
                await hass.async_add_executor_job(handle.write, chunk)
        except BaseException:
            await hass.async_add_executor_job(discard, handle)
            raise
        await hass.async_add_executor_job(finish, handle)
    return {"path": str(target), "bytes": size}
