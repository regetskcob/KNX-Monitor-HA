"""Event entities: watcher fired, alarm and fault on and off, as on the MQTT device."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_ALARM, EVENT_WATCHER
from .coordinator import KnxMonitorConfigEntry, KnxMonitorCoordinator
from .entity import KnxMonitorEntity

# Same event types as the MQTT device (mqtt_bridge.dart).
WATCHER_TYPES = ["fired"]
ALARM_TYPES = ["alarm_on", "alarm_off", "fault_on", "fault_off"]


async def async_setup_entry(
    hass: HomeAssistant, entry: KnxMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([WatcherEvent(coordinator), AlarmEvent(coordinator)])


class KnxMonitorEvent(KnxMonitorEntity, EventEntity):
    """Follows one of the add-on's Home Assistant events; no extra channel needed."""

    _event: str

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(self._event, self._handle))

    @callback
    def _handle(self, event: Event) -> None:
        event_type = self._type(event.data)
        if event_type is None:
            return
        # The event data as attributes, as the MQTT device has them.
        self._trigger_event(event_type, dict(event.data))
        self.async_write_ha_state()

    def _type(self, data: dict[str, Any]) -> str | None:
        raise NotImplementedError


class WatcherEvent(KnxMonitorEvent):
    """A watcher fired (`knx_monitor_watcher`)."""

    _attr_event_types = WATCHER_TYPES
    _event = EVENT_WATCHER

    def __init__(self, coordinator: KnxMonitorCoordinator) -> None:
        # unique_id knx_monitor_watcher_event, as on the MQTT device.
        super().__init__(coordinator, "watcher_event")

    def _type(self, data: dict[str, Any]) -> str | None:
        return "fired"


class AlarmEvent(KnxMonitorEvent):
    """An alarm or fault came or went (`knx_monitor_alarm`)."""

    _attr_event_types = ALARM_TYPES
    _event = EVENT_ALARM

    def __init__(self, coordinator: KnxMonitorCoordinator) -> None:
        # unique_id knx_monitor_alarm_event, as on the MQTT device.
        super().__init__(coordinator, "alarm_event")

    def _type(self, data: dict[str, Any]) -> str | None:
        # As the MQTT bridge derives it: anything but a fault counts as alarm.
        kind = "fault" if data.get("kind") == "fault" else "alarm"
        return f"{kind}_{'on' if data.get('active') is True else 'off'}"
