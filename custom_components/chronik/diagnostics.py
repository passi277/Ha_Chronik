"""Diagnostics for the Chronik integration."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant

from . import ChronikConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ChronikConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    events = coordinator.store.all()
    return {
        "options": dict(entry.options),
        "detectors": [type(det).__name__ for det in coordinator.detectors],
        "entries_total": len(events),
        "entries_by_category": dict(Counter(ev.category for ev in events)),
        "entries_by_origin": dict(Counter(ev.origin for ev in events)),
        "open_entries": [ev.as_dict() for ev in events if ev.is_open],
        "latest_entries": [ev.as_dict() for ev in events[-10:]],
    }
