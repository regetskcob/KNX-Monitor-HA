"""Fix flow of the repair "an address stopped sending": ignore it in the add-on."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .api import KnxMonitorError, KnxMonitorNotFoundError
from .const import DOMAIN
from .coordinator import KnxMonitorCoordinator


class IgnoreSilentFlow(RepairsFlow):
    """Ignore: the add-on stops reporting the addresses until they send again."""

    def __init__(self, addresses: list[str]) -> None:
        self._addresses = addresses

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> RepairsFlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> RepairsFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            coordinator = _coordinator(self.hass)
            if coordinator is None:
                return self.async_abort(reason="not_loaded")
            try:
                for address in self._addresses:
                    try:
                        await coordinator.api.ignore_silent(address)
                    except KnxMonitorNotFoundError:
                        pass  # sends again meanwhile: nothing to ignore
            except KnxMonitorError:
                errors["base"] = "cannot_connect"
            else:
                await coordinator.async_request_refresh()
                return self.async_create_entry(data={})
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders=issue.translation_placeholders if issue else None,
        )


def _coordinator(hass: HomeAssistant) -> KnxMonitorCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """The silence repairs carry their addresses (comma separated) in `data`."""
    raw = (data or {}).get("addresses")
    addresses = [a for a in raw.split(",") if a] if isinstance(raw, str) else []
    return IgnoreSilentFlow(addresses)
