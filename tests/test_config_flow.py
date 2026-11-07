"""Setup through the add-on's discovery."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from custom_components.knx_monitor.config_flow import Target, parse_pairing
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


async def test_user_step_without_supervisor_asks_for_the_box(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


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
    # No KNX Monitor add-on: a KNX box or container can still be set up by hand.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


# --- Set up by hand: KNX box or Docker container ------------------------------

KEY = "k" * 43
FP = "A" * 43
BOX = "http://192.168.1.20:8765"


def _link(url: str = "http://10.42.0.1/", key: str = KEY, fp: str | None = None) -> str:
    return f"knxmonitor://box?url={url}&key={key}&name=KNX-Box" + (f"&fp={fp}" if fp else "")


@pytest.mark.parametrize(
    ("link", "address", "expected"),
    [
        # Address from the link, port 80 by default.
        (_link(), "", Target("10.42.0.1", 80, False, None)),
        # The address replaces host (and port, if given) from the link.
        (_link(), "knx-box.local", Target("knx-box.local", 80, False, None)),
        (_link(), "192.168.1.20:8765", Target("192.168.1.20", 8765, False, None)),
        (_link("http://localhost:8765/"), "192.168.1.20", Target("192.168.1.20", 8765, False, None)),
        (_link(), "https://box.example:8443", Target("box.example", 8443, True, None)),
        (_link(), "[fd00::5]:8765", Target("fd00::5", 8765, False, None)),
        # With the box's certificate always HTTPS: 443, or the port of an https address.
        (_link(fp=FP), "", Target("10.42.0.1", 443, True, FP)),
        (_link(fp=FP), "192.168.1.20:80", Target("192.168.1.20", 443, True, FP)),
        (_link("https://localhost:8443/", fp=FP), "192.168.1.20", Target("192.168.1.20", 8443, True, FP)),
        (_link(fp=FP), "https://192.168.1.20:9443", Target("192.168.1.20", 9443, True, FP)),
        (_link(fp=FP), "http://192.168.1.20:8765", Target("192.168.1.20", 443, True, FP)),
    ],
)
def test_pairing_link(link: str, address: str, expected: Target) -> None:
    assert parse_pairing(link, address) == (expected, KEY)


@pytest.mark.parametrize(
    ("link", "address"),
    [
        ("", ""),
        ("http://10.42.0.1/pair?key=" + KEY, ""),
        ("knxmonitor://box?url=http://10.42.0.1/", ""),  # setup link without device key
        ("knxmonitor://other?url=http://10.42.0.1/&key=" + KEY, ""),
        (_link(key="a b"), ""),
        (_link(fp="short"), ""),
        (_link("ftp://10.42.0.1/"), ""),
        (_link(), "user:pw@evil.example"),
        (_link(), "evil.example/path"),
        (_link(), "evil.example?x=1"),
        (_link(), "ftp://evil.example"),
        (_link(), "host:99999"),
    ],
)
def test_invalid_pairing_link(link: str, address: str) -> None:
    assert parse_pairing(link, address) is None


async def test_manual_creates_entry(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BOX}/api/ha/state", json=addon_state())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "192.168.1.20:8765", "link": _link()}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": "192.168.1.20", "port": 8765, "token": KEY, "ssl": False}
    # Only the entered address got the key (also once the entry is set up).
    assert all(str(url).startswith(f"{BOX}/api/ha/") for _, url, *_ in aioclient_mock.mock_calls)
    _, _, _, headers = aioclient_mock.mock_calls[0]
    assert headers["Authorization"] == f"Bearer {KEY}"


async def test_manual_with_certificate_keeps_the_fingerprint(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get("https://192.168.1.20:443/api/ha/state", json=addon_state())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "192.168.1.20", "link": _link(fp=FP)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": "192.168.1.20", "port": 443, "token": KEY, "ssl": True, "fingerprint": FP}


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"status": 401}, "invalid_auth"),
        # A device without admin rights, or no access from the network.
        ({"status": 403}, "invalid_auth"),
        ({"exc": TimeoutError()}, "box_unreachable"),
        ({"status": 500}, "box_unreachable"),
        # The box redirects to /pair while the sticker password is valid: not followed.
        ({"status": 303}, "box_unreachable"),
        ({"exc": aiohttp.ServerFingerprintMismatch(b"a", b"b", "192.168.1.20", 443)}, "tls_mismatch"),
    ],
)
async def test_manual_errors(hass: HomeAssistant, aioclient_mock, answer: dict, error: str) -> None:
    aioclient_mock.get("https://192.168.1.20:443/api/ha/state", **answer)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "192.168.1.20", "link": _link(fp=FP)}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_manual_invalid_link_sends_nothing(hass: HomeAssistant, aioclient_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "", "link": "knxmonitor://box?url=http://10.42.0.1/"}
    )
    assert result["errors"] == {"base": "invalid_link"}
    assert not aioclient_mock.mock_calls


async def test_manual_only_once(hass: HomeAssistant, box_entry) -> None:
    box_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_add_on_discovery_does_not_take_over_a_box(hass: HomeAssistant, box_entry) -> None:
    box_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["reason"] == "already_configured"
    assert box_entry.data["token"] == TOKEN
    assert "slug" not in box_entry.data
