"""Device triggers from the add-on's events, as on the MQTT device."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, Event, HassJob, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_ALARM, EVENT_BUS, EVENT_WATCHER
from .coordinator import KnxMonitorCoordinator, owns_event

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


def _entry(hass: HomeAssistant, device_id: str) -> ConfigEntry | None:
    """The device's entry, loaded or not (automations attach before it loads)."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            return entry
    return None


def _coordinator(hass: HomeAssistant, device_id: str) -> KnxMonitorCoordinator | None:
    entry = _entry(hass, device_id)
    return entry.runtime_data if entry is not None and entry.state is ConfigEntryState.LOADED else None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """All triggers of the device "Busclear": the general ones and one per watcher.

    None for a Busclear Box or container whose server has no event channel yet
    (before 1.12.0). Add-ons before 1.9.10 have no watcher list; then only the
    general watcher trigger is offered.
    """
    coordinator = _coordinator(hass, device_id)
    if coordinator is not None and not coordinator.has_events:
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
    """Listen for the server's event that belongs to the trigger.

    Only events of this device's entry (owns_event): the add-on takes those
    without a marker, a box or container those its event channel fired. A plain
    event trigger cannot ask for a missing key, hence the own listener; the
    variables are the same as an event trigger's (`trigger.event`).
    """
    if config[CONF_TYPE] == WATCHER_TRIGGER:
        event_type, event_data = EVENT_WATCHER, {CONF_WATCHER_ID: config[CONF_WATCHER_ID]}
    else:
        event_type, event_data = TRIGGERS[config[CONF_TYPE]]
    entry = _entry(hass, config[CONF_DEVICE_ID])
    wanted = event_data.items()
    job = HassJob(action, f"knx_monitor device trigger {trigger_info}")
    trigger_data = trigger_info["trigger_data"]

    @callback
    def matches(data: Mapping[str, Any]) -> bool:
        # Without an entry (device removed) nothing is ours.
        return entry is not None and data.items() >= wanted and owns_event(entry, data)

    @callback
    def handle(event: Event) -> None:
        hass.async_run_hass_job(
            job,
            {
                "trigger": {
                    **trigger_data,
                    "platform": "device",
                    "event": event,
                    "description": f"event '{event.event_type}'",
                }
            },
            event.context,
        )

    return hass.bus.async_listen(event_type, handle, event_filter=matches)
