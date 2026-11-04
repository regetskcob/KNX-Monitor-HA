"""Device triggers from the add-on's events, as on the MQTT device."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_ALARM, EVENT_BUS, EVENT_WATCHER

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

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(TRIGGERS)})


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """All triggers of the device "KNX Monitor"."""
    return [
        {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: trigger}
        for trigger in TRIGGERS
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the add-on's event that belongs to the trigger."""
    event_type, event_data = TRIGGERS[config[CONF_TYPE]]
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(hass, event_config, action, trigger_info, platform_type="device")
