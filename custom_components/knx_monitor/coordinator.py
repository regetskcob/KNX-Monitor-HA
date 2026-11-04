"""Polls the add-on and keeps the repairs in Home Assistant current."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KnxMonitorApi, KnxMonitorAuthError, KnxMonitorError
from .const import BUS_LOST_REPAIR_AFTER, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type KnxMonitorConfigEntry = ConfigEntry[KnxMonitorCoordinator]


class KnxMonitorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """State of the add-on every 30 seconds."""

    config_entry: KnxMonitorConfigEntry

    def __init__(self, hass: HomeAssistant, entry: KnxMonitorConfigEntry, api: KnxMonitorApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.state()
        except KnxMonitorAuthError as err:
            # Add-on reinstalled: its discovery brings the new token and updates the entry.
            raise UpdateFailed(f"KNX Monitor add-on refused the token: {err}") from err
        except KnxMonitorError as err:
            raise UpdateFailed(f"KNX Monitor add-on not reachable: {err}") from err
        self._update_repairs(data)
        return data

    def _update_repairs(self, data: dict[str, Any]) -> None:
        """Bus gone for longer than 10 minutes, recording paused for lack of space."""
        lost = _since_lost(data)
        if lost is not None and dt_util.utcnow() - lost >= BUS_LOST_REPAIR_AFTER:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "bus_disconnected",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="bus_disconnected",
                translation_placeholders={"since": dt_util.as_local(lost).strftime("%H:%M")},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "bus_disconnected")
        if data.get("low_space"):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "low_space",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="low_space",
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "low_space")


def _since_lost(data: dict[str, Any]) -> datetime | None:
    """When the bus was lost, if the recording should run but is not connected."""
    if data.get("connected") or not data.get("recording"):
        return None
    lost = data.get("last_lost")
    return dt_util.parse_datetime(lost) if isinstance(lost, str) else None
