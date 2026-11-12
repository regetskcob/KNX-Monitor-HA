"""Polls the add-on and keeps the repairs in Home Assistant current."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KnxMonitorApi, KnxMonitorAuthError, KnxMonitorError, KnxMonitorNotFoundError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    BUS_LOST_REPAIR_AFTER,
    CONF_SLUG,
    DOMAIN,
    EVENT_WATCHER,
    EVENTS_FORMAT,
    SCAN_INTERVAL,
    SILENT_SUMMARY_FROM,
    WATCHERS_INTERVAL,
    WATCHERS_RELOAD_MIN,
)
from .events import EventChannelClient

_LOGGER = logging.getLogger(__name__)

type KnxMonitorConfigEntry = ConfigEntry[KnxMonitorCoordinator]

# Repair of one silent address: `silent_1_2_3`; the summary is `silent`.
SILENT_ISSUE = "silent"
SILENT_PREFIX = "silent_"


def silent_issue_id(address: str) -> str:
    """Repair id of a silent group address, e.g. `silent_1_2_3` for 1/2/3."""
    return SILENT_PREFIX + re.sub(r"[^0-9A-Za-z]", "_", address)


def via_supervisor(entry: ConfigEntry) -> bool:
    """Whether the entry is the add-on, set up through the Supervisor's discovery.

    The add-on fires its events on Home Assistant's event bus itself. A Busclear Box
    or a container set up by hand gets them through its event channel instead
    (events.py), if the server has one.
    """
    return CONF_SLUG in entry.data


def owns_event(entry: ConfigEntry, data: Mapping[str, Any]) -> bool:
    """Whether an event on the bus is [entry]'s (see KnxMonitorCoordinator.owns_event)."""
    if via_supervisor(entry):
        return ATTR_CONFIG_ENTRY_ID not in data
    return data.get(ATTR_CONFIG_ENTRY_ID) == entry.entry_id


def has_channel(data: dict[str, Any]) -> bool:
    """Whether the server has the event channel in our format (`events` in the state, since 1.12.0)."""
    return data.get("events") == EVENTS_FORMAT


class KnxMonitorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """State of the add-on every 30 seconds, watchers every 10 minutes, silent addresses when there are any."""

    config_entry: KnxMonitorConfigEntry

    def __init__(self, hass: HomeAssistant, entry: KnxMonitorConfigEntry, api: KnxMonitorApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.api = api
        # Watcher id → name; `None` while unknown or with an add-on before 1.9.10
        # (then only the general watcher trigger exists).
        self.watchers: dict[str, str] | None = None
        self._watchers_at: datetime | None = None
        # Last answer of /api/ha/silent, for the repairs and the fix flow.
        self.silent: list[dict[str, Any]] = []
        # Whether events reach Home Assistant: through the Supervisor, or the event
        # channel of a box or container (decided with the first answer).
        self.has_events = via_supervisor(entry)
        self.channel: EventChannelClient | None = None

    @property
    def platforms(self) -> list[Platform]:
        """Platforms of the entry: event entities only where events arrive."""
        base = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]
        return [*base, Platform.EVENT] if self.has_events else base

    def start_channel(self) -> None:
        """Box or container: listen to its event channel while the entry is loaded."""
        if self.has_events and not via_supervisor(self.config_entry) and self.channel is None:
            self.channel = EventChannelClient(self.hass, self.config_entry, self.api)
            self.channel.start()

    def owns_event(self, data: Mapping[str, Any]) -> bool:
        """Whether an event on the bus is this entry's.

        The add-on fires its events through the Supervisor without a marker; it
        takes only those, never what an event channel of a box fired (marked with
        `config_entry_id`). A box or container takes only what its own event
        channel fired, never the events of an add-on next to it.
        """
        return owns_event(self.config_entry, data)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.state()
        except KnxMonitorAuthError as err:
            if not via_supervisor(self.config_entry):
                # Busclear Box or container: the device was revoked or lost its admin
                # rights. Home Assistant asks for a new pairing link (reauth).
                raise ConfigEntryAuthFailed(f"Busclear refused the pairing key: {err}") from err
            # Add-on reinstalled: its discovery brings the new token and updates the entry.
            raise UpdateFailed(f"Busclear add-on refused the token: {err}") from err
        except KnxMonitorError as err:
            raise UpdateFailed(f"Busclear add-on not reachable: {err}") from err
        if self.data is None:
            self.has_events = via_supervisor(self.config_entry) or has_channel(data)
        elif not self.has_events and has_channel(data):
            # The box or container was updated to a version with the event channel.
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        self._update_repairs(data)
        await self._update_silent(data)
        if self.has_events:
            await self._update_watchers()
        return data

    async def _update_watchers(self, *, force: bool = False) -> None:
        """Reloads the watcher list every 10 minutes (or when forced, at most once a minute)."""
        now = dt_util.utcnow()
        last = self._watchers_at
        if last is not None and now - last < (WATCHERS_RELOAD_MIN if force else WATCHERS_INTERVAL):
            return
        self._watchers_at = now
        try:
            self.watchers = await self.api.watchers()
        except KnxMonitorNotFoundError:
            self.watchers = None
        except KnxMonitorError as err:
            # Keep the list we have; the next poll tries again.
            _LOGGER.debug("Busclear: watcher list not loaded: %s", err)

    @callback
    def async_watcher_event(self, event: Event) -> None:
        """A watcher fired: an id we do not know means the list changed."""
        if not self.owns_event(event.data):
            return
        watcher_id = event.data.get("watcher_id")
        if self.watchers is None or not isinstance(watcher_id, str) or watcher_id in self.watchers:
            return
        self.config_entry.async_create_background_task(
            self.hass, self._update_watchers(force=True), "knx_monitor watchers"
        )

    def listen_for_watchers(self) -> None:
        """Follows the watcher events while the entry is loaded."""
        if self.has_events:
            self.config_entry.async_on_unload(self.hass.bus.async_listen(EVENT_WATCHER, self.async_watcher_event))

    async def _update_silent(self, data: dict[str, Any]) -> None:
        """Repairs for addresses that stopped sending (count in `silent` of the state)."""
        count = data.get("silent")
        if not isinstance(count, int):
            # Add-on before 1.9.10 (or downgraded): no silence check, so repairs
            # of an earlier add-on would stay forever.
            self.silent = []
            self._update_silent_repairs(0)
            return
        if count > 0:
            try:
                self.silent = await self.api.silent()
            except KnxMonitorError as err:
                # Leave the repairs as they are until the list can be read.
                _LOGGER.debug("Busclear: silent addresses not loaded: %s", err)
                return
        else:
            self.silent = []
        self._update_silent_repairs(count)

    def _update_silent_repairs(self, count: int) -> None:
        registry = ir.async_get(self.hass)
        wanted: set[str] = set()
        if count >= SILENT_SUMMARY_FROM:
            wanted.add(SILENT_ISSUE)
            addresses = [s["address"] for s in self.silent]
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                SILENT_ISSUE,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="silent_many",
                translation_placeholders={"count": str(count), "list": _list(self.silent, count)},
                data={"addresses": ",".join(addresses)},
            )
        else:
            for s in self.silent:
                issue_id = silent_issue_id(s["address"])
                wanted.add(issue_id)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="silent",
                    translation_placeholders=_placeholders(s),
                    data={"addresses": s["address"]},
                )
        # Sends again (or ignored): its repair goes.
        for domain, issue_id in list(registry.issues):
            ours = domain == DOMAIN and (issue_id == SILENT_ISSUE or issue_id.startswith(SILENT_PREFIX))
            if ours and issue_id not in wanted:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

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


def _interval(seconds: Any) -> str:
    """Usual interval in a short form that reads the same in every language."""
    if not isinstance(seconds, int | float) or seconds <= 0:
        return "?"
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 3600, 1):g} h"


def _last(raw: Any) -> str:
    """Time of the last telegram: only the time today, otherwise with the date."""
    last = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
    if last is None:
        return "?"
    local = dt_util.as_local(last)
    return local.strftime("%H:%M" if local.date() == dt_util.now().date() else "%Y-%m-%d %H:%M")


def _placeholders(silent: dict[str, Any]) -> dict[str, str]:
    address = silent["address"]
    name = silent.get("name")
    return {
        "address": address,
        "label": f"{address} {name}" if isinstance(name, str) and name else address,
        "interval": _interval(silent.get("interval_s")),
        "last": _last(silent.get("last")),
    }


def _line(silent: dict[str, Any]) -> str:
    p = _placeholders(silent)
    return f"- {p['label']} ({p['interval']}, {p['last']})"


def _list(silent: list[dict[str, Any]], count: int) -> str:
    """The listed addresses (the add-on lists at most 20) and how many more there are."""
    lines = [_line(s) for s in silent]
    if count > len(silent):
        lines.append(f"- … +{count - len(silent)}")
    return "\n".join(lines)
