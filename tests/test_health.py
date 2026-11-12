"""The server's health check: service, sensors, and what happens while it is off."""

from __future__ import annotations

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import entity_registry as er

from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, HEALTH, WATCHERS, addon_state

RESULT = {
    "enabled": True,
    "running": False,
    "format": 1,
    "status": "hints",
    "time": "2026-11-11T13:00:00.000Z",
    "trigger": "manual",
    "read_test": False,
    "telegrams": 5329,
    "truncated": False,
    "counts": {"total": 1, "errors": 0, "warnings": 1, "infos": 0, "by_kind": {"stuck": 1}},
    "findings": [
        {
            "kind": "stuck",
            "severity": "warning",
            "area": "readings",
            "text": "healthStuck",
            "address": "2/1/0",
            "name": "EG FL Feuchte",
            "value": 45.0,
            "unit": "%",
            "since": "2026-11-10T23:00:00.000Z",
        }
    ],
}


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _server(mock, **state) -> None:
    mock.get(f"{BASE}/api/ha/state", json=addon_state(**state))
    mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    mock.post(f"{BASE}/api/ha/claim", json={"claimed": True})
    mock.delete(f"{BASE}/api/ha/claim", json={"claimed": False})


async def test_sensors_while_the_server_has_it_on(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _server(aioclient_mock, health_check=HEALTH)
    await _setup(hass, entry)
    health = hass.states.get("sensor.busclear_health")
    assert health.state == "faults"
    assert health.attributes["options"] == ["ok", "hints", "faults"]
    assert health.attributes["last_run"] == "2026-11-11T02:00:00.000Z"
    assert health.attributes["findings"] == 3
    assert health.attributes["errors"] == 1
    assert health.attributes["warnings"] == 2
    assert health.attributes["infos"] == 0
    findings = hass.states.get("sensor.busclear_health_findings")
    assert findings.state == "3"
    registry = er.async_get(hass)
    assert registry.async_get("sensor.busclear_health_findings").entity_category is er.EntityCategory.DIAGNOSTIC
    assert registry.async_get("sensor.busclear_health").entity_category is None


async def test_on_but_never_run_is_unknown(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _server(aioclient_mock, health_check={"enabled": True, "status": None, "time": None, "counts": None})
    await _setup(hass, entry)
    assert hass.states.get("sensor.busclear_health").state == "unknown"
    assert hass.states.get("sensor.busclear_health_findings").state == "unknown"


@pytest.mark.parametrize("state", [{}, {"health_check": {"enabled": False}}])
async def test_no_sensors_while_it_is_off_or_the_server_is_older(
    hass: HomeAssistant, entry, aioclient_mock, state: dict
) -> None:
    _server(aioclient_mock, **state)
    await _setup(hass, entry)
    assert hass.states.get("sensor.busclear_health") is None
    assert hass.states.get("sensor.busclear_health_findings") is None
    # The other sensors are there as before.
    assert hass.states.get("sensor.busclear_bus_load").state == "1.4"


async def test_sensors_appear_when_it_is_switched_on_and_go_when_off(
    hass: HomeAssistant, entry, aioclient_mock
) -> None:
    _server(aioclient_mock, health_check={"enabled": False})
    await _setup(hass, entry)
    assert hass.states.get("sensor.busclear_health") is None
    # The add-on restarted with the option on: no reload of the integration needed.
    aioclient_mock.clear_requests()
    _server(aioclient_mock, health_check=HEALTH)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.busclear_health").state == "faults"
    # Switched off again: unavailable at once, gone after the next start.
    aioclient_mock.clear_requests()
    _server(aioclient_mock, health_check={"enabled": False})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.busclear_health").state == "unavailable"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.busclear_health") is None
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_health") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_health_findings") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_bus_load") is not None


async def test_service_returns_the_result_and_refreshes_the_sensors(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _server(aioclient_mock, health_check=HEALTH)
    aioclient_mock.post(f"{BASE}/api/ha/health/run", json=RESULT)
    await _setup(hass, entry)
    aioclient_mock.clear_requests()
    _server(
        aioclient_mock, health_check={**HEALTH, "status": "hints", "time": RESULT["time"], "counts": RESULT["counts"]}
    )
    aioclient_mock.post(f"{BASE}/api/ha/health/run", json=RESULT)
    result = await hass.services.async_call(DOMAIN, "run_health_check", {}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    # The whole result for automations: state, counts, findings.
    assert result == RESULT
    assert result["findings"][0]["address"] == "2/1/0"
    call = next(c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/api/ha/health/run"))
    assert call[0] == "POST"
    # Never asks for read requests.
    assert call[2] == {}
    assert hass.states.get("sensor.busclear_health").state == "hints"
    assert hass.states.get("sensor.busclear_health_findings").state == "1"


async def test_service_only_for_admins(hass: HomeAssistant, entry, aioclient_mock, hass_read_only_user) -> None:
    _server(aioclient_mock, health_check=HEALTH)
    aioclient_mock.post(f"{BASE}/api/ha/health/run", json=RESULT)
    await _setup(hass, entry)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "run_health_check",
            {},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert not any(str(u).endswith("/api/ha/health/run") for _, u, *_ in aioclient_mock.mock_calls)


@pytest.mark.parametrize(("status", "key"), [(409, "health_check_off"), (404, "health_check_unsupported")])
async def test_service_says_how_to_switch_it_on(
    hass: HomeAssistant, entry, aioclient_mock, status: int, key: str
) -> None:
    _server(aioclient_mock)
    aioclient_mock.post(
        f"{BASE}/api/ha/health/run",
        status=status,
        json={"enabled": False, "error": "not_enabled", "option": "health_check", "env": "HEALTH_CHECK"},
    )
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "run_health_check", {}, blocking=True, return_response=True)
    assert err.value.translation_key == key
    assert err.value.translation_domain == DOMAIN


async def test_service_reports_a_server_that_fails(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _server(aioclient_mock, health_check=HEALTH)
    aioclient_mock.post(f"{BASE}/api/ha/health/run", status=500)
    await _setup(hass, entry)
    with pytest.raises(HomeAssistantError, match="HTTP 500"):
        await hass.services.async_call(DOMAIN, "run_health_check", {}, blocking=True, return_response=True)
