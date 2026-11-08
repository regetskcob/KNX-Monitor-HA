"""Device conditions from the integration's own entities."""

from __future__ import annotations

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_get_device_automations

from custom_components.knx_monitor.const import DOMAIN
from custom_components.knx_monitor.device_condition import async_condition_from_config

from .conftest import addon_state


async def _device(hass: HomeAssistant, entry) -> dr.DeviceEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]


def _check(hass: HomeAssistant, device: dr.DeviceEntry, condition: str) -> bool:
    config = {"condition": "device", "domain": DOMAIN, "device_id": device.id, "type": condition}
    return async_condition_from_config(hass, config)(hass, {})


async def test_conditions_listed(hass: HomeAssistant, entry, addon) -> None:
    device = await _device(hass, entry)
    conditions = await async_get_device_automations(hass, DeviceAutomationType.CONDITION, device.id)
    # Next to the entity conditions Home Assistant adds for the sensors and the switch.
    ours = {c["type"] for c in conditions if c["domain"] == DOMAIN}
    assert ours == {"bus_connected", "bus_disconnected", "recording_on", "alarm_open", "low_space"}


async def test_conditions_follow_the_entities(hass: HomeAssistant, entry, addon) -> None:
    device = await _device(hass, entry)
    coordinator = entry.runtime_data
    # addon_state(): connected, recording, one open alarm, enough space.
    assert _check(hass, device, "bus_connected")
    assert not _check(hass, device, "bus_disconnected")
    assert _check(hass, device, "recording_on")
    assert _check(hass, device, "alarm_open")
    assert not _check(hass, device, "low_space")

    coordinator.async_set_updated_data(
        addon_state(connected=False, recording=False, open_alarms=0, low_space=True, claimed=True)
    )
    await hass.async_block_till_done()
    assert not _check(hass, device, "bus_connected")
    assert _check(hass, device, "bus_disconnected")
    assert not _check(hass, device, "recording_on")
    assert not _check(hass, device, "alarm_open")
    assert _check(hass, device, "low_space")


async def test_not_met_while_the_add_on_is_unreachable(hass: HomeAssistant, entry, addon) -> None:
    device = await _device(hass, entry)
    coordinator = entry.runtime_data
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.busclear_bus_connected").state == "unavailable"
    for condition in ("bus_connected", "bus_disconnected", "recording_on", "alarm_open", "low_space"):
        assert not _check(hass, device, condition), condition


async def test_condition_in_an_automation(hass: HomeAssistant, entry, addon) -> None:
    device = await _device(hass, entry)
    calls = []
    hass.services.async_register("test", "automation", lambda call: calls.append(call))
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {"platform": "event", "event_type": "test_event"},
                    "condition": {
                        "condition": "device",
                        "domain": DOMAIN,
                        "device_id": device.id,
                        "type": "alarm_open",
                    },
                    "action": {"service": "test.automation"},
                }
            ]
        },
    )
    hass.bus.async_fire("test_event")
    await hass.async_block_till_done()
    assert len(calls) == 1
    entry.runtime_data.async_set_updated_data(addon_state(open_alarms=0, claimed=True))
    hass.bus.async_fire("test_event")
    await hass.async_block_till_done()
    assert len(calls) == 1
