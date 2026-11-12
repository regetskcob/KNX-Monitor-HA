"""Sensors: the key figures of the add-on, as on the MQTT device, and its health check."""

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
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


def _health(data: dict[str, Any] | None) -> dict[str, Any]:
    """`health_check` of the state: on or off on the server, and the last run."""
    health = (data or {}).get("health_check")
    return health if isinstance(health, dict) else {}


def _health_counts(data: dict[str, Any] | None) -> dict[str, Any]:
    counts = _health(data).get("counts")
    return counts if isinstance(counts, dict) else {}


HEALTH_STATES = ["ok", "hints", "faults"]

# Only while the server reports its health check as switched on (add-on option
# `health_check`, `HEALTH_CHECK=true` for Docker and the box).
HEALTH_SENSORS: tuple[KnxMonitorSensorDescription, ...] = (
    KnxMonitorSensorDescription(
        key="health",
        device_class=SensorDeviceClass.ENUM,
        options=HEALTH_STATES,
        value=lambda d: _health(d).get("status") if _health(d).get("status") in HEALTH_STATES else None,
    ),
    KnxMonitorSensorDescription(
        key="health_findings",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda d: _health_counts(d).get("total"),
    ),
)


# The coordinator fetches for all entities at once; nothing here calls the server per entity.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: KnxMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KnxMonitorSensor(coordinator, description) for description in SENSORS)

    added = False

    @callback
    def add_health() -> None:
        # Also later: the option can be switched on while Home Assistant runs.
        nonlocal added
        if added or _health(coordinator.data).get("enabled") is not True:
            return
        added = True
        async_add_entities(KnxMonitorHealthSensor(coordinator, description) for description in HEALTH_SENSORS)

    add_health()
    if not added:
        # Switched off on the server since the last start: the sensors go, not just "unavailable".
        registry = er.async_get(hass)
        for description in HEALTH_SENSORS:
            if entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{description.key}"):
                registry.async_remove(entity_id)
    entry.async_on_unload(coordinator.async_add_listener(add_health))


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


class KnxMonitorHealthSensor(KnxMonitorSensor):
    """State or number of findings of the server's health check."""

    @property
    def available(self) -> bool:
        return super().available and _health(self.coordinator.data).get("enabled") is True

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._key != "health":
            return None
        health = _health(self.coordinator.data)
        counts = _health_counts(self.coordinator.data)
        return {
            "last_run": health.get("time"),
            "findings": counts.get("total"),
            "errors": counts.get("errors"),
            "warnings": counts.get("warnings"),
            "infos": counts.get("infos"),
        }
