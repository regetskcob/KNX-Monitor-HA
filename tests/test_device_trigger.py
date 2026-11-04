"""Device triggers from the add-on's events."""

from __future__ import annotations

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_get_device_automations

from custom_components.knx_monitor.const import DOMAIN


async def test_triggers_listed_and_fire(hass: HomeAssistant, entry, addon) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, DOMAIN), entry.entry_id)
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
