"""Entities, switch, takeover of the MQTT device, repairs, services, diagnostics."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.knx_monitor import services
from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, TOKEN, addon_state


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_and_takeover(hass: HomeAssistant, entry, addon) -> None:
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    # Took over the entities from the MQTT device.
    assert any(m == "POST" and str(u).endswith("/api/ha/claim") for m, u, *_ in addon.mock_calls)
    assert hass.states.get("binary_sensor.knx_monitor_bus_connected").state == "on"
    assert hass.states.get("switch.knx_monitor_recording").state == "on"
    assert hass.states.get("sensor.knx_monitor_bus_load").state == "1.4"
    assert hass.states.get("sensor.knx_monitor_telegrams_today").state == "5329"
    alarm = hass.states.get("sensor.knx_monitor_last_alarm")
    assert alarm.state == "Wind"
    assert alarm.attributes["address"] == "8/1/1"
    device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    assert device.sw_version == "1.9.7"
    assert device.configuration_url == "homeassistant://hassio/ingress/2541da37_knx_monitor"


async def test_switch_turns_recording_off(hass: HomeAssistant, entry, addon) -> None:
    addon.post(f"{BASE}/api/ha/recording", json=addon_state(recording=False))
    await _setup(hass, entry)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.knx_monitor_recording"}, blocking=True)
    call = next(c for c in addon.mock_calls if str(c[1]).endswith("/api/ha/recording"))
    assert call[2] == {"on": False}
    assert hass.states.get("switch.knx_monitor_recording").state == "off"


async def test_remove_gives_entities_back(hass: HomeAssistant, entry, addon) -> None:
    await _setup(hass, entry)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert any(m == "DELETE" and str(u).endswith("/api/ha/claim") for m, u, *_ in addon.mock_calls)


async def test_repairs_for_lost_bus_and_full_disk(hass: HomeAssistant, entry, aioclient_mock) -> None:
    lost = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    aioclient_mock.get(
        f"{BASE}/api/ha/state",
        json=addon_state(connected=False, state="disconnected", last_lost=lost, low_space=True, claimed=True),
    )
    await _setup(hass, entry)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "bus_disconnected") is not None
    assert issues.async_get_issue(DOMAIN, "low_space") is not None


async def test_no_repair_for_a_short_dropout(hass: HomeAssistant, entry, aioclient_mock) -> None:
    lost = (dt_util.utcnow() - timedelta(minutes=2)).isoformat()
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(connected=False, last_lost=lost, claimed=True))
    await _setup(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "bus_disconnected") is None


async def test_services(hass: HomeAssistant, entry, addon, tmp_path) -> None:
    addon.post(f"{BASE}/api/ha/report", json={"id": "2026-11-04", "alarms": 1})
    addon.get(
        f"{BASE}/api/ha/history",
        text="<?xml version='1.0'?><CommunicationLog/>",
        headers={"Content-Disposition": 'attachment; filename="knx-monitor-2026-11-04-2026-11-04.xml"'},
    )
    hass.config.config_dir = str(tmp_path)
    await _setup(hass, entry)
    report = await hass.services.async_call(DOMAIN, "create_report", {}, blocking=True, return_response=True)
    assert report == {"id": "2026-11-04", "alarms": 1}
    result = await hass.services.async_call(DOMAIN, "export_history", {"days": 1}, blocking=True, return_response=True)
    assert result["path"].endswith("knx_monitor/knx-monitor-2026-11-04-2026-11-04.xml")
    assert (tmp_path / "knx_monitor" / "knx-monitor-2026-11-04-2026-11-04.xml").read_text().startswith("<?xml")
    assert result["bytes"] == len("<?xml version='1.0'?><CommunicationLog/>")
    assert not list((tmp_path / "knx_monitor").glob("*.part"))


@pytest.mark.parametrize(("service", "data"), [("create_report", {}), ("export_history", {"days": 1})])
async def test_services_only_for_admins(
    hass: HomeAssistant, entry, addon, hass_read_only_user, service: str, data: dict
) -> None:
    """The report and the history name the whole installation: administrators only."""
    await _setup(hass, entry)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, service, data, blocking=True, return_response=True, context=Context(user_id=hass_read_only_user.id)
        )
    assert not any(str(u).endswith(("/api/ha/report", "/api/ha/history")) for _, u, *_ in addon.mock_calls)


async def test_export_too_large_is_aborted(hass: HomeAssistant, entry, addon, tmp_path) -> None:
    addon.get(
        f"{BASE}/api/ha/history",
        content=b"x" * 5000,
        headers={"Content-Disposition": 'attachment; filename="knx-monitor-history.zip"'},
    )
    hass.config.config_dir = str(tmp_path)
    await _setup(hass, entry)
    with (
        patch.object(services, "MAX_EXPORT_BYTES", 3000),
        patch.object(services, "CHUNK_BYTES", 1024),
        pytest.raises(HomeAssistantError) as err,
    ):
        await hass.services.async_call(
            DOMAIN, "export_history", {"everything": True}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "export_too_large"
    # Neither the partial file nor a truncated export stays behind.
    assert list((tmp_path / "knx_monitor").iterdir()) == []


async def test_export_announced_too_large_is_refused(hass: HomeAssistant, entry, addon, tmp_path) -> None:
    addon.get(f"{BASE}/api/ha/history", content=b"x", headers={"Content-Length": str(600 * 1024 * 1024)})
    hass.config.config_dir = str(tmp_path)
    await _setup(hass, entry)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "export_history", {"days": 2}, blocking=True, return_response=True)
    assert err.value.translation_key == "export_too_large"
    assert not (tmp_path / "knx_monitor").exists()


async def test_only_one_export_at_a_time(hass: HomeAssistant, entry, addon, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    await _setup(hass, entry)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(*args):
        started.set()
        await release.wait()
        return {"path": "x", "bytes": 0}

    with patch.object(services, "_download", side_effect=slow):
        first = hass.async_create_task(
            hass.services.async_call(DOMAIN, "export_history", {"days": 1}, blocking=True, return_response=True)
        )
        await started.wait()
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(DOMAIN, "export_history", {"days": 1}, blocking=True, return_response=True)
        assert err.value.translation_key == "export_running"
        release.set()
        assert (await first)["bytes"] == 0


async def test_diagnostics_without_token_and_names(hass: HomeAssistant, hass_client, entry, addon) -> None:
    addon.get(f"{BASE}/api/ha/diagnostics", json={"version": "1.9.7", "state": "connected"})
    assert await async_setup_component(hass, "diagnostics", {})
    await _setup(hass, entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = str(result)
    assert TOKEN not in text
    assert "Zuhause" not in text
    assert result["addon"]["version"] == "1.9.7"


async def test_failed_takeover_retries_later(hass: HomeAssistant, entry, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state())
    aioclient_mock.post(f"{BASE}/api/ha/claim", status=500)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Not alongside the MQTT entities: no entities, Home Assistant retries.
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.states.get("switch.knx_monitor_recording") is None
