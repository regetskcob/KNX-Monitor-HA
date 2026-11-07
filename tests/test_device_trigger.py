"""Device triggers from the add-on's events."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_get_device_automations

from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, WATCHERS, addon_state


async def test_triggers_listed_and_fire(hass: HomeAssistant, entry, addon) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    types = {t["type"] for t in triggers}
    assert {"watcher_fired", "alarm_on", "fault_off", "bus_disconnected"} <= types

    calls = []
    hass.services.async_register("test", "automation", lambda call: calls.append(call))
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": "fault_on"},
                    "action": {"service": "test.automation"},
                }
            ]
        },
    )
    # An alarm (not a fault) does not trigger it, a fault does.
    hass.bus.async_fire("knx_monitor_alarm", {"kind": "alarm", "active": True, "address": "1/2/3"})
    hass.bus.async_fire("knx_monitor_alarm", {"kind": "fault", "active": True, "address": "1/2/3"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def _device(hass: HomeAssistant, entry) -> dr.DeviceEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]


async def test_one_trigger_per_watcher(hass: HomeAssistant, entry, addon) -> None:
    device = await _device(hass, entry)
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    named = [t for t in triggers if t["type"] == "specific_watcher_fired"]
    assert [(t["subtype"], t["watcher_id"]) for t in named] == [("Fenster Bad offen", "w1"), ("Wind", "w2")]
    # The general one stays.
    assert any(t["type"] == "watcher_fired" for t in triggers)

    calls = []
    hass.services.async_register("test", "automation", lambda call: calls.append(call))
    trigger = {k: v for k, v in named[0].items() if k != "metadata"}
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {automation.DOMAIN: [{"trigger": trigger, "action": {"service": "test.automation"}}]},
    )
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w2", "name": "Wind"})
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w1", "name": "Fenster Bad offen"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_unknown_watcher_reloads_the_list(hass: HomeAssistant, entry, addon) -> None:
    await _device(hass, entry)
    coordinator = entry.runtime_data
    assert set(coordinator.watchers) == {"w1", "w2"}
    addon.clear_requests()
    addon.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True))
    addon.get(f"{BASE}/api/ha/watchers", json=[*WATCHERS, {"id": "w3", "name": "Tür"}])
    # Within the first minute after loading it waits; afterwards it reloads.
    coordinator._watchers_at -= timedelta(minutes=2)
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w3", "name": "Tür"})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.watchers["w3"] == "Tür"
    # A known id does not ask again.
    calls = len(addon.mock_calls)
    hass.bus.async_fire("knx_monitor_watcher", {"watcher_id": "w1"})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(addon.mock_calls) == calls


async def test_older_add_on_only_general_trigger(hass: HomeAssistant, entry, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", status=404)
    device = await _device(hass, entry)
    assert entry.runtime_data.watchers is None
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    ours = {t["type"] for t in triggers if t["domain"] == DOMAIN}
    assert "watcher_fired" in ours
    assert "specific_watcher_fired" not in ours


async def test_no_triggers_for_a_box(hass: HomeAssistant, box_entry, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(claimed=True))
    device = await _device(hass, box_entry)
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    assert not [t for t in triggers if t["domain"] == DOMAIN]
