"""Backfill from the recorder history."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.chronik.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_db_url: str, enable_custom_integrations: None) -> None:
    """Set up the recorder database before hass (overrides the conftest fixture)."""


ZONE = "binary_sensor.zone_haus"
MOWER = "lawn_mower.leopard"


async def _summaries(hass: HomeAssistant, entity_id: str) -> list[str]:
    now = dt_util.now()
    result = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": now - timedelta(days=5),
            "end_date_time": now + timedelta(days=1),
        },
        blocking=True,
        return_response=True,
    )
    return [e["summary"] for e in result[entity_id]["events"]]


async def test_backfill(recorder_mock: Recorder, hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """History recorded before setup is turned into entries, without duplicates."""
    hass.config.language = "de"
    zone_attrs = {"friendly_name": "Haus"}
    mower_attrs = {"friendly_name": "Leopard 2"}
    freezer.move_to(dt_util.utcnow() - timedelta(days=2))
    hass.states.async_set(ZONE, "off", zone_attrs)
    hass.states.async_set(MOWER, "docked", mower_attrs)
    await async_wait_recording_done(hass)
    for zone_state, mower_state, minutes in (
        ("on", "docked", 60),
        ("off", "mowing", 15),
        ("off", "docked", 30),  # short pause, merged
        ("off", "mowing", 10),
        ("off", "docked", 40),
    ):
        freezer.tick(timedelta(minutes=minutes))
        hass.states.async_set(ZONE, zone_state, zone_attrs)
        hass.states.async_set(MOWER, mower_state, mower_attrs)
        await async_wait_recording_done(hass)
    freezer.move_to(dt_util.utcnow() + timedelta(days=2))

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Chronik",
        options={"irrigation_entities": [ZONE], "mowing_entities": [MOWER]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await _summaries(hass, "calendar.chronik_bewasserung") == []

    response = await hass.services.async_call(
        DOMAIN, "backfill", {"days": 3}, blocking=True, return_response=True
    )
    assert response == {"added": 2}
    assert await _summaries(hass, "calendar.chronik_bewasserung") == ["💧 Haus · 15 min"]
    assert await _summaries(hass, "calendar.chronik_mahen") == ["🌱 Mähen · 1 h 10 min"]

    # Running it again does not create duplicates.
    response = await hass.services.async_call(
        DOMAIN, "backfill", {"days": 3}, blocking=True, return_response=True
    )
    assert response == {"added": 0}
