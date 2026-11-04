"""Sensors: the key figures of the add-on, as on the MQTT device."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import KnxMonitorConfigEntry
from .entity import KnxMonitorEntity


def _time(key: str) -> Callable[[dict[str, Any]], datetime | None]:
    def value(data: dict[str, Any]) -> datetime | None:
        raw = data.get(key)
        return dt_util.parse_datetime(raw) if isinstance(raw, str) else None

    return value


@dataclass(frozen=True, kw_only=True)
class KnxMonitorSensorDescription(SensorEntityDescription):
    """Sensor with the function that reads its value from the state."""

    value: Callable[[dict[str, Any]], Any]


SENSORS: tuple[KnxMonitorSensorDescription, ...] = (
    KnxMonitorSensorDescription(
        key="telegrams_per_minute",
        native_unit_of_measurement="1/min",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.get("per_minute"),
    ),
    KnxMonitorSensorDescription(
        key="repeats_per_minute",
        native_unit_of_measurement="1/min",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.get("repeats_per_minute"),
    ),
    KnxMonitorSensorDescription(
        key="telegrams_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda d: d.get("today"),
    ),
    KnxMonitorSensorDescription(
        key="last_telegram",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_time("last"),
    ),
    KnxMonitorSensorDescription(
        key="bus_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda d: d.get("bus_load"),
    ),
    KnxMonitorSensorDescription(
        key="open_alarms",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.get("open_alarms"),
    ),
    KnxMonitorSensorDescription(
        key="last_alarm",
        value=lambda d: d.get("last_alarm"),
    ),
    KnxMonitorSensorDescription(
        key="last_alarm_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_time("last_alarm_time"),
    ),
    KnxMonitorSensorDescription(
        key="availability_24h",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda d: d.get("availability_24h"),
    ),
    KnxMonitorSensorDescription(
        key="history_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.get("history_mb"),
    ),
    KnxMonitorSensorDescription(
        key="free_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: d.get("free_mb"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: KnxMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KnxMonitorSensor(coordinator, description) for description in SENSORS)


class KnxMonitorSensor(KnxMonitorEntity, SensorEntity):
    """A key figure of the add-on."""

    entity_description: KnxMonitorSensorDescription

    def __init__(self, coordinator, description: KnxMonitorSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # Like on the MQTT device: what kind of alarm, on which address, when.
        if self._key != "last_alarm":
            return None
        data = self.coordinator.data
        return {
            "kind": data.get("last_alarm_kind"),
            "address": data.get("last_alarm_address"),
            "time": data.get("last_alarm_time"),
        }
