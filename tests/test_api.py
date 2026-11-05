"""The token only goes to the address the add-on announced."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.knx_monitor.api import KnxMonitorApi, KnxMonitorError

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
