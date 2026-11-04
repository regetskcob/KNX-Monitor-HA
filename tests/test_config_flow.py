"""Setup through the add-on's discovery."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, TOKEN, addon_state

DISCOVERY = HassioServiceInfo(
    config={"host": "127.0.0.1", "port": 8765, "token": TOKEN},
    name="KNX Monitor",
    slug="knx_monitor",
    uuid="1234",
)


async def test_discovery_confirm_creates_entry(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    aioclient_mock.post(f"{BASE}/api/ha/claim", json={"claimed": True})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": "127.0.0.1", "port": 8765, "token": TOKEN, "slug": "knx_monitor"}


async def test_discovery_add_on_not_answering(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=DISCOVERY
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_needs_the_add_on(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "addon_required"


async def test_rediscovery_updates_token(hass: HomeAssistant, entry, addon) -> None:
    entry.add_to_hass(hass)
    new = HassioServiceInfo(
        config={"host": "127.0.0.1", "port": 8765, "token": "b" * 64}, name="KNX Monitor", slug="knx_monitor", uuid="1"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=new
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["token"] == "b" * 64
