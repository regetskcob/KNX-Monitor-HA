"""Setup through the add-on's discovery."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, TOKEN, addon_state

DISCOVERY = HassioServiceInfo(
    config={"host": "127.0.0.1", "port": 8765, "token": TOKEN},
    name="KNX Monitor",
    slug="2541da37_knx_monitor",
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
    assert result["data"] == {"host": "127.0.0.1", "port": 8765, "token": TOKEN, "slug": "2541da37_knx_monitor"}


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


async def test_user_step_takes_the_add_on_announcement(hass: HomeAssistant, aioclient_mock) -> None:
    """Added by hand while the add-on runs: same as the discovery."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    message = SimpleNamespace(
        service="knx_monitor", addon="2541da37_knx_monitor", config={"host": "127.0.0.1", "port": 8765, "token": TOKEN}
    )
    client = SimpleNamespace(discovery=SimpleNamespace(list=AsyncMock(return_value=[message])))
    with (
        patch("custom_components.knx_monitor.config_flow.is_hassio", return_value=True),
        patch("homeassistant.components.hassio.get_supervisor_client", return_value=client),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["step_id"] == "hassio_confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["slug"] == "2541da37_knx_monitor"


async def test_rediscovery_updates_token(hass: HomeAssistant, entry, addon) -> None:
    entry.add_to_hass(hass)
    new = HassioServiceInfo(
        config={"host": "127.0.0.1", "port": 8765, "token": "b" * 64},
        name="KNX Monitor",
        slug="2541da37_knx_monitor",
        uuid="1",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=new
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["token"] == "b" * 64


async def test_discovery_from_another_add_on_is_ignored(hass: HomeAssistant, aioclient_mock) -> None:
    foreign = HassioServiceInfo(
        config={"host": "127.0.0.1", "port": 8765, "token": TOKEN}, name="Evil", slug="1234abcd_evil", uuid="2"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=foreign
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_knx_monitor_addon"
    assert not aioclient_mock.mock_calls


async def test_foreign_rediscovery_keeps_the_entry(hass: HomeAssistant, entry, addon) -> None:
    """Another add-on cannot redirect host, port and token of the set-up entry."""
    entry.add_to_hass(hass)
    for slug in (
        "1234abcd_evil",
        "1234abcd_evil_knx_monitor",
        "knx_monitor_evil",
        "deadbeef_knx_monitor",
        "knx_monitor",
        "",
    ):
        foreign = HassioServiceInfo(
            config={"host": "evil.example", "port": 1, "token": "e" * 64}, name="Evil", slug=slug, uuid="3"
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=foreign
        )
        assert result["reason"] == "not_knx_monitor_addon"
    assert entry.data["token"] == TOKEN
    assert entry.data["host"] == "127.0.0.1"


async def test_user_step_skips_announcements_of_other_add_ons(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    foreign = SimpleNamespace(
        service="knx_monitor", addon="1234abcd_evil", config={"host": "evil.example", "port": 1, "token": "e" * 64}
    )
    ours = SimpleNamespace(
        service="knx_monitor", addon="local_knx_monitor", config={"host": "127.0.0.1", "port": 8765, "token": TOKEN}
    )
    client = SimpleNamespace(discovery=SimpleNamespace(list=AsyncMock(return_value=[foreign, ours])))
    with (
        patch("custom_components.knx_monitor.config_flow.is_hassio", return_value=True),
        patch("homeassistant.components.hassio.get_supervisor_client", return_value=client),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["token"] == TOKEN
    assert result["data"]["slug"] == "local_knx_monitor"


async def test_user_step_only_other_add_ons(hass: HomeAssistant) -> None:
    foreign = SimpleNamespace(
        service="knx_monitor", addon="1234abcd_evil", config={"host": "evil.example", "port": 1, "token": "e" * 64}
    )
    client = SimpleNamespace(discovery=SimpleNamespace(list=AsyncMock(return_value=[foreign])))
    with (
        patch("custom_components.knx_monitor.config_flow.is_hassio", return_value=True),
        patch("homeassistant.components.hassio.get_supervisor_client", return_value=client),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "addon_required"
