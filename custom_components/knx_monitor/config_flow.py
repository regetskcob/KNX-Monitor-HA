"""Setup of KNX Monitor: only through the add-on's discovery."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.hassio import is_hassio
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import KnxMonitorApi, KnxMonitorError
from .const import CONF_SLUG, CONF_TOKEN, DOMAIN


class KnxMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """The add-on announces host, port and token; the user only confirms."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Added by hand: take the running add-on's announcement, if there is one."""
        if not is_hassio(self.hass):
            return self.async_abort(reason="addon_required")
        try:
            from homeassistant.components.hassio import get_supervisor_client

            messages = await get_supervisor_client(self.hass).discovery.list()
        except Exception:  # noqa: BLE001 - Supervisor not ready or too old: same hint
            return self.async_abort(reason="addon_required")
        message = next((m for m in messages if m.service == DOMAIN), None)
        if message is None:
            return self.async_abort(reason="addon_required")
        return await self._discovered(message.config, message.addon)

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The KNX Monitor add-on announced itself."""
        return await self._discovered(discovery_info.config, discovery_info.slug)

    async def _discovered(self, config: dict[str, Any], slug: str) -> ConfigFlowResult:
        self._discovery = {
            CONF_HOST: config["host"],
            CONF_PORT: int(config["port"]),
            CONF_TOKEN: config["token"],
            # Add-on slug with the repository prefix, for the link to its panel.
            CONF_SLUG: slug,
        }
        await self.async_set_unique_id(DOMAIN)
        # Add-on reinstalled (new token) or moved: update the existing entry.
        self._abort_if_unique_id_configured(updates=self._discovery)
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask once, then check that the add-on answers."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = KnxMonitorApi(
                async_get_clientsession(self.hass),
                self._discovery[CONF_HOST],
                self._discovery[CONF_PORT],
                self._discovery[CONF_TOKEN],
            )
            try:
                await api.state()
            except KnxMonitorError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="KNX Monitor", data=self._discovery)
        return self.async_show_form(step_id="hassio_confirm", errors=errors)
