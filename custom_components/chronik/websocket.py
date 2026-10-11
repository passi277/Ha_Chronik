"""Websocket API used by the Chronik dashboard card."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import DOMAIN
from .models import ChronikEvent
from .store import effective_end


def _label(title: str) -> str:
    """Return the title without its leading emoji (the card shows icons)."""
    first, _, rest = title.partition(" ")
    if rest and first and not any(ch.isalnum() for ch in first):
        return rest
    return title


def _serialize(ev: ChronikEvent, now) -> dict[str, Any]:
    return {
        "uid": ev.uid,
        "category": ev.category,
        "start": dt_util.as_local(ev.start).isoformat(),
        "end": dt_util.as_local(ev.end).isoformat() if ev.end else None,
        "display_end": dt_util.as_local(effective_end(ev, now)).isoformat(),
        "running": ev.is_open,
        "title": ev.title,
        "label": _label(ev.title),
        "description": ev.description,
        "source": ev.source,
        "data": ev.data,
        "origin": ev.origin,
    }


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_events)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chronik/events",
        vol.Optional("entry_id"): str,
        vol.Required("start"): str,
        vol.Required("end"): str,
    }
)
@callback
def ws_events(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return all Chronik entries in a time range."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and (not msg.get("entry_id") or entry.entry_id == msg["entry_id"])
    ]
    if not entries:
        connection.send_error(msg["id"], "not_found", "No loaded Chronik entry")
        return
    start = dt_util.parse_datetime(msg["start"])
    end = dt_util.parse_datetime(msg["end"])
    if start is None or end is None:
        connection.send_error(msg["id"], "invalid_format", "Invalid start or end")
        return
    coordinator = entries[0].runtime_data
    now = dt_util.utcnow()
    events = coordinator.events_between(dt_util.as_utc(start), dt_util.as_utc(end))
    connection.send_result(
        msg["id"],
        {
            "entry_id": entries[0].entry_id,
            "title": entries[0].title,
            "categories": coordinator.enabled_categories,
            "events": [_serialize(ev, now) for ev in events],
        },
    )
