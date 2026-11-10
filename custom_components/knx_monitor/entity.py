"""Common base of the Busclear entities: one device for the add-on."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SLUG, DOMAIN, MANUFACTURER
from .coordinator import KnxMonitorCoordinator


class KnxMonitorEntity(CoordinatorEntity[KnxMonitorCoordinator]):
    """Entity of the device "Busclear"."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KnxMonitorCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        # Same unique IDs as the MQTT device had, so nothing gets confused.
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_translation_key = key
        slug = coordinator.config_entry.data.get(CONF_SLUG)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DOMAIN)},
            name="Busclear",
            manufacturer=MANUFACTURER,
            # Set up by hand: a Busclear Box or a Docker container, opened in the browser.
            model="Home Assistant add-on" if slug else "Busclear Box or container",
            sw_version=coordinator.data.get("version"),
            configuration_url=f"homeassistant://hassio/ingress/{slug}" if slug else f"{coordinator.api.url}/",
        )
