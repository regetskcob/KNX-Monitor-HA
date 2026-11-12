"""Binary sensors: bus connected, space running low."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KnxMonitorConfigEntry
from .entity import KnxMonitorEntity

# The coordinator fetches for all entities at once; nothing here calls the server per entity.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: KnxMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([BusConnected(coordinator), LowSpace(coordinator)])


class BusConnected(KnxMonitorEntity, BinarySensorEntity):
    """Whether the add-on is connected to the bus."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "bus_connected")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("connected"))


class LowSpace(KnxMonitorEntity, BinarySensorEntity):
    """Recording pauses because the disk is full."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "low_space")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("low_space"))
