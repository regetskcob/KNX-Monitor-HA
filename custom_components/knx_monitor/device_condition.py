"""Device conditions: bus connected or not, recording on, alarm open, low space.

Evaluated from the state of the integration's own entities, not with a new
request: a condition answers at once, also while the add-on is unreachable,
and is then not met.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.const import (
    CONF_CONDITION,
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_TYPE,
    STATE_ON,
    Platform,
)
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.condition import ConditionCheckerType
from homeassistant.helpers.config_validation import DEVICE_CONDITION_BASE_SCHEMA
from homeassistant.helpers.typing import ConfigType, TemplateVarsType

from .const import DOMAIN


def _on(state: State) -> bool:
    return state.state == STATE_ON


def _off(state: State) -> bool:
    # Unavailable or unknown is neither connected nor disconnected.
    return state.state == "off"


def _alarms(state: State) -> bool:
    try:
        return float(state.state) > 0
    except ValueError:
        return False


# Condition type → entity (platform and key of its unique_id) and the test of its state.
CONDITIONS: dict[str, tuple[Platform, str, Callable[[State], bool]]] = {
    "bus_connected": (Platform.BINARY_SENSOR, "bus_connected", _on),
    "bus_disconnected": (Platform.BINARY_SENSOR, "bus_connected", _off),
    "recording_on": (Platform.SWITCH, "recording", _on),
    "alarm_open": (Platform.SENSOR, "open_alarms", _alarms),
    "low_space": (Platform.BINARY_SENSOR, "low_space", _on),
}

CONDITION_SCHEMA = DEVICE_CONDITION_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(CONDITIONS)})


async def async_get_conditions(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """All conditions of the device "KNX Monitor"."""
    return [
        {CONF_CONDITION: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: condition}
        for condition in CONDITIONS
    ]


@callback
def async_condition_from_config(hass: HomeAssistant, config: ConfigType) -> ConditionCheckerType:
    """Checks the state of the entity behind the condition."""
    platform, key, test = CONDITIONS[config[CONF_TYPE]]

    @callback
    def check(hass: HomeAssistant, variables: TemplateVarsType = None) -> bool:
        # Looked up on every check: the entity may have been renamed meanwhile.
        entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{DOMAIN}_{key}")
        state = hass.states.get(entity_id) if entity_id else None
        return state is not None and test(state)

    return check
