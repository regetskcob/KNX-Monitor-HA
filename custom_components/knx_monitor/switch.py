"""Switch: continuous recording of the add-on."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import KnxMonitorError
from .coordinator import KnxMonitorConfigEntry
from .entity import KnxMonitorEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KnxMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([Recording(entry.runtime_data)])


class Recording(KnxMonitorEntity, SwitchEntity):
    """Continuous recording on or off (the add-on's bus connection)."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "recording")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("recording"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        try:
            state = await self.coordinator.api.set_recording(on)
        except KnxMonitorError as err:
            raise HomeAssistantError(f"Busclear: {err}") from err
        self.coordinator.async_set_updated_data(state)
