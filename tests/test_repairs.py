"""Repairs "an address stopped sending", with "Ignore"."""

from __future__ import annotations

import re
from datetime import timedelta

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.knx_monitor.const import DOMAIN

from .conftest import BASE, WATCHERS, addon_state


def _silent(address: str, name: str | None = None, minutes_ago: int = 60) -> dict:
    last = (dt_util.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
    return {"address": address, "name": name, "last": last, "interval_s": 300}


def _answers(aioclient_mock, silent: list[dict], *, count: int | None = None) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(silent=len(silent) if count is None else count))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    aioclient_mock.get(f"{BASE}/api/ha/silent", json=silent)
    aioclient_mock.post(f"{BASE}/api/ha/claim", json={"claimed": True})
    aioclient_mock.post(f"{BASE}/api/ha/silent/ignore", json={"ignored": True})


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _ours(hass: HomeAssistant) -> set[str]:
    return {issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN}


async def test_one_repair_per_address_until_it_sends_again(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _answers(aioclient_mock, [_silent("1/2/3", "Temperatur Bad"), _silent("1/2/4")])
    await _setup(hass, entry)
    assert _ours(hass) == {"silent_1_2_3", "silent_1_2_4"}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "silent_1_2_3")
    assert issue.is_fixable
    assert issue.translation_key == "silent"
    assert issue.translation_placeholders["label"] == "1/2/3 Temperatur Bad"
    assert issue.translation_placeholders["interval"] == "5 min"
    # Local time, with the date only if it was not today.
    assert re.fullmatch(r"(\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}", issue.translation_placeholders["last"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "silent_1_2_4").translation_placeholders["label"] == "1/2/4"

    # 1/2/4 sends again: its repair goes, the other stays.
    _answers(aioclient_mock, [_silent("1/2/3", "Temperatur Bad")])
    await entry.runtime_data.async_refresh()
    assert _ours(hass) == {"silent_1_2_3"}
    # Recording off or bus gone: the add-on reports none, all go.
    _answers(aioclient_mock, [], count=0)
    await entry.runtime_data.async_refresh()
    assert _ours(hass) == set()
    assert not any(str(url).endswith("/api/ha/silent") for _, url, *_ in aioclient_mock.mock_calls)


async def test_summary_from_five_addresses(hass: HomeAssistant, entry, aioclient_mock) -> None:
    silent = [_silent(f"1/2/{i}") for i in range(1, 8)]
    _answers(aioclient_mock, silent)
    await _setup(hass, entry)
    assert _ours(hass) == {"silent"}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "silent")
    assert issue.translation_key == "silent_many"
    assert issue.translation_placeholders["count"] == "7"
    assert "- 1/2/7 (5 min," in issue.translation_placeholders["list"]
    # Back to two: one each again.
    _answers(aioclient_mock, silent[:2])
    await entry.runtime_data.async_refresh()
    assert _ours(hass) == {"silent_1_2_1", "silent_1_2_2"}


async def test_ignore_tells_the_add_on(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _answers(aioclient_mock, [_silent("1/2/3", "Temperatur Bad")])
    await _setup(hass, entry)
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": "silent_1_2_3"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["label"] == "1/2/3 Temperatur Bad"
    # After ignoring, the add-on no longer lists it.
    ignore = f"{BASE}/api/ha/silent/ignore"
    aioclient_mock.clear_requests()
    aioclient_mock.post(ignore, json={"ignored": "1/2/3"})
    aioclient_mock.get(f"{BASE}/api/ha/state", json=addon_state(silent=0))
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    result = await manager.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    call = next(c for c in aioclient_mock.mock_calls if str(c[1]) == ignore)
    assert call[2] == {"address": "1/2/3"}
    assert _ours(hass) == set()


async def test_ignore_all_of_the_summary(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _answers(aioclient_mock, [_silent(f"1/2/{i}") for i in range(1, 6)])
    await _setup(hass, entry)
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": "silent"})
    assert result["description_placeholders"]["count"] == "5"
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    ignored = [c[2]["address"] for c in aioclient_mock.mock_calls if str(c[1]).endswith("/api/ha/silent/ignore")]
    assert ignored == [f"1/2/{i}" for i in range(1, 6)]


async def test_ignore_fails_while_the_add_on_is_away(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _answers(aioclient_mock, [_silent("1/2/3")])
    await _setup(hass, entry)
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": "silent_1_2_3"})
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/api/ha/silent/ignore", exc=TimeoutError())
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "silent_1_2_3" in _ours(hass)


async def test_older_add_on_without_silent(hass: HomeAssistant, entry, aioclient_mock) -> None:
    state = addon_state()
    del state["silent"]
    aioclient_mock.get(f"{BASE}/api/ha/state", json=state)
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    aioclient_mock.post(f"{BASE}/api/ha/claim", json={"claimed": True})
    await _setup(hass, entry)
    assert _ours(hass) == set()
    assert not any(str(url).endswith("/api/ha/silent") for _, url, *_ in aioclient_mock.mock_calls)


async def test_summary_names_addresses_beyond_the_list(hass: HomeAssistant, entry, aioclient_mock) -> None:
    # The add-on lists at most 20; the summary says how many more there are.
    silent = [_silent(f"1/3/{i}") for i in range(1, 21)]
    _answers(aioclient_mock, silent, count=27)
    await _setup(hass, entry)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "silent")
    assert issue.translation_placeholders["count"] == "27"
    assert issue.translation_placeholders["list"].endswith("- … +7")


async def test_downgraded_add_on_clears_the_repairs(hass: HomeAssistant, entry, aioclient_mock) -> None:
    _answers(aioclient_mock, [_silent("1/2/3")])
    await _setup(hass, entry)
    assert _ours(hass) == {"silent_1_2_3"}
    state = addon_state()
    del state["silent"]
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/ha/state", json=state)
    aioclient_mock.get(f"{BASE}/api/ha/watchers", json=WATCHERS)
    aioclient_mock.post(f"{BASE}/api/ha/claim", json={"claimed": True})
    await entry.runtime_data.async_refresh()
    assert _ours(hass) == set()
