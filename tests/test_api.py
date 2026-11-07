"""The token only goes to the address the add-on announced."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.knx_monitor.api import KnxMonitorApi, KnxMonitorError, fingerprint_bytes

from .conftest import BASE, TOKEN, addon_state


async def test_no_fallback_to_localhost(hass: HomeAssistant, aioclient_mock) -> None:
    """A host name that does not answer is an error, not a reason to try 127.0.0.1."""
    aioclient_mock.get("http://2541da37-knx-monitor:8765/api/ha/state", exc=TimeoutError())
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    api = KnxMonitorApi(async_get_clientsession(hass), "2541da37-knx-monitor", 8765, TOKEN)
    with pytest.raises(KnxMonitorError):
        await api.state()
    assert [str(url) for _, url, *_ in aioclient_mock.mock_calls] == ["http://2541da37-knx-monitor:8765/api/ha/state"]
    assert api.base is None


async def test_announced_localhost_is_used(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    api = KnxMonitorApi(async_get_clientsession(hass), "127.0.0.1", 8765, TOKEN)
    assert (await api.state())["version"] == "1.9.7"
    assert api.base == BASE
    _, _, _, headers = aioclient_mock.mock_calls[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"


async def test_fingerprint_pins_the_certificate(hass: HomeAssistant) -> None:
    """With the box's fingerprint: HTTPS, exactly that certificate, no redirects."""
    response = MagicMock(status=200, json=AsyncMock(return_value={"version": "1.10.0"}))
    request = MagicMock()
    request.return_value.__aenter__ = AsyncMock(return_value=response)
    request.return_value.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock(request=request)
    fp = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    api = KnxMonitorApi(session, "192.168.1.20", 443, TOKEN, fingerprint=fp)
    assert (await api.state())["version"] == "1.10.0"
    args, kwargs = request.call_args
    assert args == ("GET", "https://192.168.1.20:443/api/ha/state")
    assert isinstance(kwargs["ssl"], aiohttp.Fingerprint)
    assert kwargs["ssl"].fingerprint == bytes(range(32))
    assert kwargs["allow_redirects"] is False


async def test_without_fingerprint_normal_verification(hass: HomeAssistant) -> None:
    request = MagicMock()
    request.return_value.__aenter__ = AsyncMock(return_value=MagicMock(status=200, json=AsyncMock(return_value={})))
    request.return_value.__aexit__ = AsyncMock(return_value=False)
    api = KnxMonitorApi(MagicMock(request=request), "fd00::5", 8765, TOKEN)
    await api.state()
    args, kwargs = request.call_args
    assert args[1] == "http://[fd00::5]:8765/api/ha/state"
    assert kwargs["ssl"] is True


def test_fingerprint_must_be_sha256() -> None:
    with pytest.raises(ValueError):
        fingerprint_bytes("AAAA")
