"""Events without Supervisor: the event channel `/ws/events` of a Busclear Box or Docker container.

With Supervisor the add-on fires its events on Home Assistant's event bus itself. A box or a
container cannot, so the integration listens to its event channel and fires the same events here,
marked with its config entry (`config_entry_id`). Event entities, device triggers and the watcher
list then work as with the add-on. The format is described in `docs/event-channel.md` of the
development repository.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import EventOrigin, HomeAssistant

from .api import KnxMonitorApi, KnxMonitorAuthError, KnxMonitorError, KnxMonitorNotFoundError
from .const import ATTR_CONFIG_ENTRY_ID, EVENT_ALARM, EVENT_BUS, EVENT_WATCHER, EVENTS_BACKOFF, EVENTS_FORMAT

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Only these are fired on the bus, whatever else the server might send.
EVENT_TYPES = frozenset({EVENT_WATCHER, EVENT_ALARM, EVENT_BUS})

# Heartbeats this many intervals missing: the connection counts as dead.
MISSED_HEARTBEATS = 3
DEFAULT_HEARTBEAT = 30


class EventChannelClient:
    """Keeps the connection to `/ws/events` while the entry is loaded and fires its events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: KnxMonitorApi) -> None:
        self._hass = hass
        self._entry = entry
        self._api = api
        # Position in the server's sequence: after a dropout the server sends what was missed.
        self.epoch: str | None = None
        self.seq: int | None = None
        self.connected = False
        # Times events may have been missed (server restarted, away too long); for diagnostics.
        self.gaps = 0
        self.received = 0
        self._timeout = float(DEFAULT_HEARTBEAT * MISSED_HEARTBEATS)
        # Lost and already logged once: the next hello says it is back.
        self._lost = False

    def start(self) -> None:
        """Runs until the entry is unloaded (the task ends with it)."""
        self._entry.async_create_background_task(self._hass, self._run(), "knx_monitor event channel")

    async def _run(self) -> None:
        failures = 0
        while True:
            try:
                await self._listen()
            except KnxMonitorAuthError as err:
                # Device revoked on the box: the same reauth step as for the polling.
                self.connected = False
                _LOGGER.warning("Busclear: the event channel refused the pairing key (%s)", err)
                self._entry.async_start_reauth(self._hass)
                return
            except KnxMonitorNotFoundError:
                # Server went back to a version without the channel: stay as before it.
                self.connected = False
                _LOGGER.info("Busclear: the server has no event channel any more; events stay off until reloaded")
                return
            except KnxMonitorError as err:
                # Once per outage, not on every attempt.
                if not self._lost:
                    _LOGGER.warning("Busclear: event channel lost (%s), reconnecting", err)
                else:
                    _LOGGER.debug("Busclear: event channel still unreachable: %s", err)
                self._lost = True
            if self.connected:
                # It was up: start again with the shortest pause.
                failures = 0
            self.connected = False
            await asyncio.sleep(EVENTS_BACKOFF[min(failures, len(EVENTS_BACKOFF) - 1)])
            failures += 1

    async def _listen(self) -> None:
        """One connection, until the server closes it. Raises KnxMonitorError on failures."""
        async with self._api.events(since=self.seq, epoch=self.epoch) as ws:
            while True:
                try:
                    msg = await ws.receive(timeout=self._timeout)
                except TimeoutError as err:
                    raise KnxMonitorError("no heartbeat") from err
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        message = msg.json()
                    except ValueError:
                        continue
                    self.handle(message)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                    # Closed by the server (access changed, shutdown): connect again.
                    return
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise KnxMonitorError(str(ws.exception() or "websocket error"))

    def handle(self, message: Any) -> None:
        """One message of the server; anything unknown is ignored."""
        if not isinstance(message, dict) or message.get("v") != EVENTS_FORMAT:
            return
        kind = message.get("type")
        seq = message.get("seq")
        if not isinstance(seq, int):
            return
        if kind == "hello":
            self._hello(message, seq)
        elif kind == "event":
            if self.seq is not None and seq <= self.seq:
                return  # Already fired (sent again after a reconnect).
            self._advance(seq)
            event_type = message.get("event")
            data = message.get("data")
            if event_type in EVENT_TYPES and isinstance(data, dict):
                self.received += 1
                self._hass.bus.async_fire(
                    event_type, {**data, ATTR_CONFIG_ENTRY_ID: self._entry.entry_id}, EventOrigin.remote
                )
        elif kind == "heartbeat" and self.seq is not None and seq > self.seq:
            # An event never arrived.
            self._advance(seq)

    def _hello(self, message: dict[str, Any], seq: int) -> None:
        epoch = message.get("epoch")
        heartbeat = message.get("heartbeat_s")
        if isinstance(heartbeat, int) and heartbeat > 0:
            self._timeout = float(heartbeat * MISSED_HEARTBEATS)
        if self.epoch is not None and (epoch != self.epoch or message.get("resumed") is not True):
            self.gaps += 1
            _LOGGER.debug("Busclear: events may have been missed while the event channel was down")
        if epoch != self.epoch or self.seq is None:
            # First connection or server restarted: count from its current position.
            self.epoch = epoch if isinstance(epoch, str) else None
            self.seq = seq
        self.connected = True
        if self._lost:
            _LOGGER.info("Busclear: event channel connected again")
            self._lost = False
        _LOGGER.debug("Busclear: event channel connected (seq %s)", seq)

    def _advance(self, seq: int) -> None:
        if self.seq is not None and seq != self.seq + 1:
            self.gaps += 1
        self.seq = seq

    def diagnostics(self) -> dict[str, Any]:
        return {"connected": self.connected, "received": self.received, "gaps": self.gaps}
