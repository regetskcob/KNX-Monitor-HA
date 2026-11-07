"""Event entities from the add-on's events, as on the MQTT device."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, addon_state


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_same_unique_ids_as_the_mqtt_device(hass: HomeAssistant, entry, addon) -> None:
    await _setup(hass, entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("event", DOMAIN, "knx_monitor_watcher_event") == "event.knx_monitor_watcher"
    assert registry.async_get_entity_id("event", DOMAIN, "knx_monitor_alarm_event") == "event.knx_monitor_alarm"
    watcher = hass.states.get("event.knx_monitor_watcher")
    assert watcher.state == "unknown"
    assert watcher.attributes["event_types"] == ["fired"]
    assert hass.states.get("event.knx_monitor_alarm").attributes["event_types"] == [
        "alarm_on",
        "alarm_off",
        "fault_on",
        "fault_off",
    ]


async def test_watcher_and_alarm_events(hass: HomeAssistant, entry, addon) -> None:
    await _setup(hass, entry)
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w1", "name": "Fenster Bad offen", "address": "1/1/1"})
    await hass.async_block_till_done()
    watcher = hass.states.get("event.knx_monitor_watcher")
    assert watcher.state != "unknown"
    assert watcher.attributes["event_type"] == "fired"
    assert watcher.attributes["watcher_id"] == "w1"

    for data, expected in [
        ({"kind": "fault", "active": True, "address": "8/1/1"}, "fault_on"),
        ({"kind": "alarm", "active": False, "address": "8/1/1"}, "alarm_off"),
        ({"kind": "alarm", "active": True, "address": "8/1/1"}, "alarm_on"),
    ]:
        hass.bus.async_fire("knx_monitor_alarm", data)
        await hass.async_block_till_done()
        alarm = hass.states.get("event.knx_monitor_alarm")
        assert alarm.attributes["event_type"] == expected
        assert alarm.attributes["address"] == "8/1/1"


async def test_no_event_entities_for_a_box(hass: HomeAssistant, box_entry, aioclient_mock) -> None:
    """Set up by hand: the box's events do not reach Home Assistant, so no entities that never change."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True))
    await _setup(hass, box_entry)
    assert hass.states.get("event.knx_monitor_watcher") is None
    assert hass.states.get("binary_sensor.knx_monitor_bus_connected").state == "on"
    # No watcher list either: there are no triggers to fill.
    assert not any(str(url).endswith("/api/ha/watchers") for _, url, *_ in aioclient_mock.mock_calls)
