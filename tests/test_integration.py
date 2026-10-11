"""Integration tests: config flow, live recording, calendars and services."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chronik.const import DOMAIN

OPTIONS = {
    "rain_sensor": "sensor.rain_today",
    "irrigation_entities": ["binary_sensor.zone_haus"],
    "mowing_entities": ["lawn_mower.leopard"],
    "ai_entities": ["input_text.pool_ki"],
}


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a Chronik entry with a few sources."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.config.language = "de"
    hass.states.async_set("sensor.rain_today", "0.0", {"unit_of_measurement": "mm"})
    hass.states.async_set("binary_sensor.zone_haus", "off", {"friendly_name": "Haus Bewässert gerade"})
    hass.states.async_set("lawn_mower.leopard", "docked", {"friendly_name": "Leopard 2"})
    hass.states.async_set("input_text.pool_ki", "Wasser trüb", {"friendly_name": "Pool KI-Befund"})
    entry = MockConfigEntry(domain=DOMAIN, title="Chronik", data={}, options=OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _events(hass: HomeAssistant, entity_id: str, days: int = 2) -> list[dict]:
    now = dt_util.now()
    result = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": now - timedelta(days=days),
            "end_date_time": now + timedelta(days=1),
        },
        blocking=True,
        return_response=True,
    )
    return result[entity_id]["events"]


async def test_config_flow(hass: HomeAssistant) -> None:
    """The setup walks through name and one page per category."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Garten"})
    assert result["step_id"] == "rain"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rain_sensor": "sensor.rain_today", "rain_gap_minutes": 30}
    )
    assert result["step_id"] == "irrigation"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"irrigation_entities": ["binary_sensor.zone_haus"], "irrigation_min_minutes": 1}
    )
    for step in ("mowing", "pool", "alarm", "ai"):
        assert result["step_id"] == step
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garten"
    assert result["options"]["rain_sensor"] == "sensor.rain_today"
    assert result["options"]["rain_gap_minutes"] == 30
    assert "mowing_entities" not in result["options"]


async def test_options_flow(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Options can be changed per category and cleared."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "mowing"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"mowing_merge_minutes": 20, "mowing_min_minutes": 1}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "mowing_entities" not in entry.options
    assert hass.states.get("calendar.chronik_mahen") is None


async def test_calendars_created(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """One calendar per configured category plus the summary."""
    registry = er.async_get(hass)
    ids = sorted(e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id))
    assert len(ids) == 5
    assert "calendar.chronik_tagesbilanz" in ids


async def test_live_recording(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """State changes become calendar events."""
    irrigation = "calendar.chronik_bewasserung"
    attrs = {"friendly_name": "Haus Bewässert gerade"}
    hass.states.async_set("binary_sensor.zone_haus", "on", attrs)
    await hass.async_block_till_done()
    assert hass.states.get(irrigation).state == "on"
    freezer.tick(timedelta(minutes=18))
    hass.states.async_set("binary_sensor.zone_haus", "off", attrs)
    await hass.async_block_till_done()
    events = await _events(hass, irrigation)
    assert len(events) == 1
    assert events[0]["summary"] == "💧 Haus Bewässert gerade · 18 min"

    hass.states.async_set("sensor.rain_today", "2.5", {"unit_of_measurement": "mm"})
    hass.states.async_set("input_text.pool_ki", "Wasser klar", {"friendly_name": "Pool KI-Befund"})
    await hass.async_block_till_done()
    assert (await _events(hass, "calendar.chronik_regen"))[0]["summary"] == "🌧️ Regen · 2,5 mm"
    assert (await _events(hass, "calendar.chronik_ki_befunde"))[0][
        "summary"
    ] == "🤖 Pool KI-Befund: Wasser klar"

    summary = await _events(hass, "calendar.chronik_tagesbilanz")
    assert len(summary) == 1
    assert "🌧️ 2,5 mm" in summary[0]["summary"]
    assert "💧 1× · 18 min" in summary[0]["summary"]
    assert "🤖 1 Befunde" in summary[0]["summary"]


async def test_open_run_survives_restart(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """An irrigation run that is open during a reload is continued."""
    hass.states.async_set("binary_sensor.zone_haus", "on")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10))
    hass.states.async_set("binary_sensor.zone_haus", "off")
    await hass.async_block_till_done()
    events = await _events(hass, "calendar.chronik_bewasserung")
    assert len(events) == 1
    assert events[0]["summary"].endswith("10 min")


async def test_services_and_calendar_editing(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Entries can be added via service and edited/deleted via the calendar."""
    response = await hass.services.async_call(
        DOMAIN,
        "add_entry",
        {"category": "ai", "title": "🤖 Unwetter vorbei", "description": "Keine Schäden"},
        blocking=True,
        return_response=True,
    )
    uid = response["uid"]
    events = await _events(hass, "calendar.chronik_ki_befunde")
    assert [e["summary"] for e in events] == ["🤖 Unwetter vorbei"]

    await hass.services.async_call(
        CALENDAR_DOMAIN,
        "create_event",
        {
            "entity_id": "calendar.chronik_bewasserung",
            "summary": "Dünger gestreut",
            "start_date_time": dt_util.now() - timedelta(hours=1),
            "end_date_time": dt_util.now() - timedelta(minutes=30),
        },
        blocking=True,
    )
    assert [e["summary"] for e in await _events(hass, "calendar.chronik_bewasserung")] == ["Dünger gestreut"]

    response = await hass.services.async_call(
        DOMAIN, "delete_entry", {"uid": uid}, blocking=True, return_response=True
    )
    assert response == {"deleted": True}
    assert await _events(hass, "calendar.chronik_ki_befunde") == []


async def test_entries_persist(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Entries are written to storage and loaded again."""
    await hass.services.async_call(DOMAIN, "add_entry", {"category": "rain", "title": "Notiz"}, blocking=True)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert [e["summary"] for e in await _events(hass, "calendar.chronik_regen")] == ["Notiz"]
