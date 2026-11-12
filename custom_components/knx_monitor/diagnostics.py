"""Diagnostics download: connection, storage and restarts, without names or values."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .api import KnxMonitorError
from .const import CONF_TOKEN
from .coordinator import KnxMonitorConfigEntry

REDACT = {CONF_TOKEN, CONF_HOST, "installation", "last_alarm", "last_alarm_address"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: KnxMonitorConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    try:
        addon: dict[str, Any] | str = await coordinator.api.diagnostics()
    except KnxMonitorError as err:
        addon = f"not reachable: {err}"
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "state": async_redact_data(coordinator.data or {}, REDACT),
        "addon": addon,
        # Box or container: the event channel (no event contents).
        "events": coordinator.channel.diagnostics() if coordinator.channel else None,
    }
