"""Events without Supervisor: the event channel /ws/events of a Busclear Box or Docker container."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_get_device_automations

from custom_components.knx_monitor.api import KnxMonitorApi, KnxMonitorAuthError, KnxMonitorError
from custom_components.knx_monitor.const import DOMAIN
from custom_components.knx_monitor.events import EventChannelClient

from .conftest import BASE, WATCHERS, addon_state


class FakeSocket:
    """One connection of the fake server: messages are handed in by the test."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[aiohttp.WSMessage] = asyncio.Queue()

    def send(self, message: dict[str, Any]) -> None:
        self._queue.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(message), None))

    def close(self) -> None:
        self._queue.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, 1008, "access changed"))

    async def receive(self, timeout: float | None = None) -> aiohttp.WSMessage:
        return await self._queue.get()

    def exception(self) -> None:
        return None


class FakeChannel:
    """Stands in for KnxMonitorApi.events: each connection is a FakeSocket or an error, in order."""

    def __init__(self) -> None:
        self.connects: list[tuple[int | None, str | None]] = []
        self._next: asyncio.Queue[FakeSocket | Exception] = asyncio.Queue()
        self.connected = asyncio.Event()

    def accept(self) -> FakeSocket:
        socket = FakeSocket()
        self._next.put_nowait(socket)
        return socket

    def refuse(self, error: Exception) -> None:
        self._next.put_nowait(error)

    def patch(self):
        channel = self

        @asynccontextmanager
        async def events(api: KnxMonitorApi, *, since: int | None = None, epoch: str | None = None) -> AsyncIterator:
            item = await channel._next.get()
            channel.connects.append((since, epoch))
            channel.connected.set()
            if isinstance(item, Exception):
                raise item
            yield item

        return patch.object(KnxMonitorApi, "events", events)


def hello(seq: int = 0, epoch: str = "e1", *, resumed: bool = False) -> dict[str, Any]:
    return {
        "v": 1,
        "type": "hello",
        "seq": seq,
        "epoch": epoch,
        "server": "1.12.0",
        "heartbeat_s": 30,
        "resumed": resumed,
    }


def event(seq: int, name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"v": 1, "type": "event", "seq": seq, "time": "2026-11-11T10:00:00.000Z", "event": name, "data": data}


@pytest.fixture
def channel():
    fake = FakeChannel()
    with fake.patch(), patch("custom_components.knx_monitor.events.EVENTS_BACKOFF", (0,)):
        yield fake


@pytest.fixture
def box(aioclient_mock):
    """A box whose server has the event channel."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True, events=1))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    return aioclient_mock


async def _setup(hass: HomeAssistant, entry) -> dr.DeviceEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]


async def _settle(hass: HomeAssistant) -> None:
    """Lets the channel task read what the test handed in."""
    for _ in range(5):
        await asyncio.sleep(0)
    await hass.async_block_till_done()


async def _automation(hass: HomeAssistant, device_id: str, trigger: dict[str, Any]) -> list:
    calls: list = []
    hass.services.async_register("test", "automation", lambda call: calls.append(call))
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {"platform": "device", "domain": DOMAIN, "device_id": device_id, **trigger},
                    "action": {"service": "test.automation"},
                }
            ]
        },
    )
    return calls


async def test_box_events_become_entities_and_triggers(hass: HomeAssistant, box_entry, box, channel) -> None:
    socket = channel.accept()
    device = await _setup(hass, box_entry)
    await _settle(hass)
    assert channel.connects == [(None, None)]
    socket.send(hello())
    # Event entities and device triggers as with the add-on, one per watcher too.
    assert hass.states.get("event.busclear_watcher").state == "unknown"
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    assert {"watcher_fired", "fault_on", "bus_disconnected"} <= {t["type"] for t in triggers}
    assert [t["watcher_id"] for t in triggers if t["type"] == "specific_watcher_fired"] == ["w1", "w2"]
    calls = await _automation(hass, device.id, {"type": "specific_watcher_fired", "watcher_id": "w1"})

    socket.send(event(1, "knx_monitor_watcher", {"watcher_id": "w1", "name": "Fenster Bad offen", "address": "1/1/1"}))
    socket.send(event(2, "knx_monitor_alarm", {"kind": "fault", "active": True, "address": "8/1/1"}))
    await _settle(hass)
    watcher = hass.states.get("event.busclear_watcher")
    assert watcher.attributes["event_type"] == "fired"
    assert watcher.attributes["watcher_id"] == "w1"
    # The marker of the entry stays internal, the attributes are as with the add-on.
    assert "config_entry_id" not in watcher.attributes
    assert hass.states.get("event.busclear_alarm").attributes["event_type"] == "fault_on"
    assert len(calls) == 1
    assert box_entry.runtime_data.channel.diagnostics() == {"connected": True, "received": 2, "gaps": 0}


async def test_box_ignores_events_of_an_addon_next_to_it(hass: HomeAssistant, box_entry, box, channel) -> None:
    socket = channel.accept()
    device = await _setup(hass, box_entry)
    await _settle(hass)
    socket.send(hello())
    calls = await _automation(hass, device.id, {"type": "alarm_on"})
    # Fired through the Supervisor by an add-on, not by this box.
    hass.bus.async_fire("knx_monitor_alarm", {"kind": "alarm", "active": True, "address": "1/2/3"})
    await hass.async_block_till_done()
    assert hass.states.get("event.busclear_alarm").state == "unknown"
    assert calls == []


async def test_reconnects_and_fetches_what_it_missed(hass: HomeAssistant, box_entry, box, channel) -> None:
    first = channel.accept()
    await _setup(hass, box_entry)
    await _settle(hass)
    fired: list[int] = []
    hass.bus.async_listen("knx_monitor_bus", lambda e: fired.append(e.data["n"]))
    first.send(hello(seq=4))
    first.send(event(5, "knx_monitor_bus", {"connected": False, "n": 5}))
    await _settle(hass)
    # The server closes (access changed), the next attempt fails, the one after works.
    first.close()
    channel.refuse(KnxMonitorError("connection refused"))
    second = channel.accept()
    await _settle(hass)
    assert channel.connects[1:] == [(5, "e1"), (5, "e1")]
    second.send(hello(seq=6, resumed=True))
    second.send(event(5, "knx_monitor_bus", {"connected": False, "n": 5}))  # already fired
    second.send(event(6, "knx_monitor_bus", {"connected": True, "n": 6}))
    await _settle(hass)
    assert fired == [5, 6]
    assert box_entry.runtime_data.channel.gaps == 0


async def test_refused_key_starts_reauth(hass: HomeAssistant, box_entry, box, channel) -> None:
    channel.refuse(KnxMonitorAuthError("HTTP 401"))
    await _setup(hass, box_entry)
    await _settle(hass)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [config_entries.SOURCE_REAUTH]
    # No further attempts with a key the box refuses.
    assert len(channel.connects) == 1


async def test_supervisor_no_channel_no_duplicates(hass: HomeAssistant, entry, aioclient_mock, channel) -> None:
    """The add-on fires through the Supervisor; the integration must not add the channel's copy."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True, events=1))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    channel.accept()
    device = await _setup(hass, entry)
    await _settle(hass)
    assert channel.connects == []
    assert entry.runtime_data.channel is None
    calls = await _automation(hass, device.id, {"type": "alarm_on"})
    hass.bus.async_fire("knx_monitor_alarm", {"kind": "alarm", "active": True, "address": "1/2/3"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_older_box_without_channel(hass: HomeAssistant, box_entry, aioclient_mock, channel) -> None:
    """Server before the channel: as before, no connection attempts, no event entities."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True))
    await _setup(hass, box_entry)
    await _settle(hass)
    assert channel.connects == []
    assert hass.states.get("event.busclear_watcher") is None

    # Updated to a server with the channel: the entry reloads and gets it.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True, events=1))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    channel.accept()
    await box_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    await _settle(hass)
    assert hass.states.get("event.busclear_watcher") is not None
    assert channel.connects == [(None, None)]


def test_gaps_and_unknown_messages(hass: HomeAssistant, box_entry) -> None:
    client = EventChannelClient(hass, box_entry, None)  # type: ignore[arg-type]
    client.handle(hello(seq=3))
    assert (client.seq, client.epoch) == (3, "e1")
    # Other format version, unknown event type, nonsense: ignored, nothing fired.
    client.handle({"v": 2, "type": "event", "seq": 4, "event": "knx_monitor_bus", "data": {}})
    client.handle(event(4, "call_service", {"domain": "lock"}))
    client.handle("x")
    assert client.received == 0
    assert client.seq == 4
    # A heartbeat ahead of the last event: one went missing.
    client.handle({"v": 1, "type": "heartbeat", "seq": 6, "time": "x"})
    assert (client.seq, client.gaps) == (6, 1)
    # Server restarted: a new epoch counts as a gap, numbering starts again.
    client.handle(hello(seq=0, epoch="e2"))
    assert (client.seq, client.epoch, client.gaps) == (0, "e2", 2)


async def test_addon_ignores_events_of_a_box_next_to_it(hass: HomeAssistant, entry, aioclient_mock) -> None:
    """Counterpart: what a box's event channel fired (marked) never reaches the add-on's device."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    device = await _setup(hass, entry)
    alarms: list = []
    watcher: list = []
    hass.services.async_register("test", "alarm", lambda call: alarms.append(call))
    hass.services.async_register("test", "watcher", lambda call: watcher.append(call))
    base = {"platform": "device", "domain": DOMAIN, "device_id": device.id}
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {"trigger": {**base, "type": "alarm_on"}, "action": {"service": "test.alarm"}},
                {
                    "trigger": {**base, "type": "specific_watcher_fired", "watcher_id": "w1"},
                    "action": {"service": "test.watcher", "data": {"id": "{{ trigger.event.data.watcher_id }}"}},
                },
            ]
        },
    )
    watchers_before = sum(str(u).endswith("/api/ha/watchers") for _, u, *_ in aioclient_mock.mock_calls)
    box = {"config_entry_id": "other-entry"}
    hass.bus.async_fire("knx_monitor_alarm", {"kind": "alarm", "active": True, "address": "1/2/3", **box})
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w1", "name": "Fenster Bad offen", **box})
    # An unknown watcher id would reload the list; from a box it must not.
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "neu", "name": "Neu", **box})
    await hass.async_block_till_done()
    assert hass.states.get("event.busclear_alarm").state == "unknown"
    assert hass.states.get("event.busclear_watcher").state == "unknown"
    assert alarms == [] and watcher == []
    assert sum(str(u).endswith("/api/ha/watchers") for _, u, *_ in aioclient_mock.mock_calls) == watchers_before

    # Its own events (through the Supervisor, without a marker) still work, with the event in the variables.
    hass.bus.async_fire("knx_monitor_alarm", {"kind": "alarm", "active": True, "address": "1/2/3"})
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w1", "name": "Fenster Bad offen"})
    await hass.async_block_till_done()
    assert hass.states.get("event.busclear_alarm").attributes["event_type"] == "alarm_on"
    assert len(alarms) == 1 and len(watcher) == 1
    assert watcher[0].data["id"] == "w1"
