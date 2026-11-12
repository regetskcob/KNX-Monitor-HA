"""Fixtures: the add-on's answers and a set-up entry."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.knx_monitor.const import DOMAIN

BASE = "http://127.0.0.1:8765"
TOKEN = "a" * 64

# `health_check` of GET /api/ha/state while the server's health check is on.
HEALTH = {
    "enabled": True,
    "status": "faults",
    "time": "2026-11-11T02:00:00.000Z",
    "counts": {"total": 3, "errors": 1, "warnings": 2, "infos": 0, "by_kind": {"dpt_size": 1, "stuck": 2}},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/knx_monitor in every test."""
    yield


def addon_state(**changes: Any) -> dict[str, Any]:
    """State as GET /api/ha/state returns it."""
    state = {
        "connected": True,
        "recording": True,
        "per_minute": 26.0,
        "repeats_per_minute": 0.5,
        "today": 5329,
        "last": "2026-11-04T11:19:35+00:00",
        "installation": "Zuhause",
        "bus_load": 1.4,
        "open_alarms": 1,
        "last_alarm": "Wind",
        "last_alarm_kind": "alarm",
        "last_alarm_address": "8/1/1",
        "last_alarm_time": "2026-11-04T10:00:00+00:00",
        "history_mb": 32.5,
        "free_mb": 61150.0,
        "low_space": False,
        "availability_24h": 99.8,
        "version": "1.9.7",
        "state": "connected",
        "since": "2026-11-04T08:39:00+00:00",
        "last_lost": None,
        "read_only": True,
        "claimed": False,
        "silent": 0,
    }
    state.update(changes)
    return state


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Busclear",
        data={"host": "127.0.0.1", "port": 8765, "token": TOKEN, "slug": "2541da37_knx_monitor"},
    )


@pytest.fixture
def box_entry() -> MockConfigEntry:
    """Set up by hand for a Busclear Box (no add-on slug, no Supervisor events)."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Busclear",
        data={"host": "127.0.0.1", "port": 8765, "token": TOKEN, "ssl": False},
    )


WATCHERS = [{"id": "w1", "name": "Fenster Bad offen"}, {"id": "w2", "name": "Wind"}]


@pytest.fixture
def addon(aioclient_mock):
    """The add-on answers with addon_state(); returns the mock for more answers."""
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    aioclient_mock.post(f"{BASE}/api/ha/claim", json={"claimed": True})
    aioclient_mock.delete(f"{BASE}/api/ha/claim", json={"claimed": False})
    return aioclient_mock
