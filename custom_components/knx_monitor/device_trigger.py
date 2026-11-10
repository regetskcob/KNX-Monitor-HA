"""Device triggers from the add-on's events, as on the MQTT device."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_ALARM, EVENT_BUS, EVENT_WATCHER
from .coordinator import KnxMonitorCoordinator, has_events

CONF_SUBTYPE = "subtype"
CONF_WATCHER_ID = "watcher_id"

# Trigger type → event and the data it must carry.
TRIGGERS: dict[str, tuple[str, dict[str, Any]]] = {
    "watcher_fired": (EVENT_WATCHER, {}),
    "alarm_on": (EVENT_ALARM, {"kind": "alarm", "active": True}),
    "alarm_off": (EVENT_ALARM, {"kind": "alarm", "active": False}),
    "fault_on": (EVENT_ALARM, {"kind": "fault", "active": True}),
    "fault_off": (EVENT_ALARM, {"kind": "fault", "active": False}),
    "bus_connected": (EVENT_BUS, {"connected": True}),
    "bus_disconnected": (EVENT_BUS, {"connected": False}),
}

# One trigger per watcher, with its name as subtype ("Watcher 'Bathroom window
# open' fired"), filtered by its id in the event data. A type of its own: the
# text of `watcher_fired` ("A watcher fired") has no place for the name.
WATCHER_TRIGGER = "specific_watcher_fired"

TRIGGER_SCHEMA = vol.Any(
    DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(TRIGGERS)}),
    DEVICE_TRIGGER_BASE_SCHEMA.extend(
        {
            vol.Required(CONF_TYPE): WATCHER_TRIGGER,
            vol.Required(CONF_WATCHER_ID): cv.string,
            vol.Optional(CONF_SUBTYPE): cv.string,
        }
    ),
)


def _coordinator(hass: HomeAssistant, device_id: str) -> KnxMonitorCoordinator | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """All triggers of the device "Busclear": the general ones and one per watcher.

    None for a Busclear Box or container set up by hand: their events do not reach
    Home Assistant yet. Add-ons before 1.9.10 have no watcher list; then only the
    general watcher trigger is offered.
    """
    coordinator = _coordinator(hass, device_id)
    if coordinator is not None and not has_events(coordinator.config_entry):
        return []
    base = {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id}
    triggers = [{**base, CONF_TYPE: trigger} for trigger in TRIGGERS]
    watchers = coordinator.watchers if coordinator is not None else None
    for watcher_id, name in sorted((watchers or {}).items(), key=lambda w: w[1].casefold()):
        triggers.append({**base, CONF_TYPE: WATCHER_TRIGGER, CONF_SUBTYPE: name, CONF_WATCHER_ID: watcher_id})
    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the add-on's event that belongs to the trigger."""
    if config[CONF_TYPE] == WATCHER_TRIGGER:
        event_type, event_data = EVENT_WATCHER, {CONF_WATCHER_ID: config[CONF_WATCHER_ID]}
    else:
        event_type, event_data = TRIGGERS[config[CONF_TYPE]]
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(hass, event_config, action, trigger_info, platform_type="device")
