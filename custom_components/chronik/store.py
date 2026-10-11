"""Persistent storage of Chronik entries."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, POINT_DISPLAY, STORAGE_VERSION
from .models import ChronikEvent

SAVE_DELAY = 10


def effective_end(ev: ChronikEvent, now: datetime) -> datetime:
    """Return the end used for display: now for open runs, a minimum for points."""
    if ev.end is None:
        return max(now, ev.start) + timedelta(minutes=1)
    if ev.end <= ev.start:
        return ev.start + POINT_DISPLAY
    return ev.end


class ChronikStore:
    """Keeps all entries in memory and persists them to .storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self._events: dict[str, ChronikEvent] = {}
        self._sorted: list[ChronikEvent] | None = None

    async def async_load(self) -> None:
        """Load entries from disk."""
        data = await self._store.async_load() or {}
        self._events = {raw["uid"]: ChronikEvent.from_dict(raw) for raw in data.get("events", [])}
        self._sorted = None

    async def async_save(self) -> None:
        """Write entries to disk immediately."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the storage file."""
        await self._store.async_remove()

    def _data(self) -> dict[str, Any]:
        return {"events": [ev.as_dict() for ev in self.all()]}

    def _changed(self) -> None:
        self._sorted = None
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def __len__(self) -> int:
        return len(self._events)

    def get(self, uid: str) -> ChronikEvent | None:
        """Return an entry by uid."""
        return self._events.get(uid)

    def all(self) -> list[ChronikEvent]:
        """Return all entries sorted by start."""
        if self._sorted is None:
            self._sorted = sorted(self._events.values(), key=lambda e: (e.start, e.uid))
        return self._sorted

    def upsert(self, ev: ChronikEvent) -> None:
        """Create or replace an entry."""
        self._events[ev.uid] = ev.copy()
        self._changed()

    def delete(self, uid: str) -> bool:
        """Remove an entry; return True if it existed."""
        if self._events.pop(uid, None) is None:
            return False
        self._changed()
        return True

    def between(
        self,
        start: datetime,
        end: datetime,
        categories: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> list[ChronikEvent]:
        """Return entries overlapping [start, end)."""
        now = now or dt_util.utcnow()
        cats = set(categories) if categories is not None else None
        result = []
        for ev in self.all():
            if ev.start >= end:
                break
            if cats is not None and ev.category not in cats:
                continue
            if effective_end(ev, now) > start:
                result.append(ev)
        return result

    def recent(self, category: str, since: datetime) -> list[ChronikEvent]:
        """Return entries of a category that started after since or are open."""
        return [ev for ev in self.all() if ev.category == category and (ev.start >= since or ev.is_open)]

    def overlapping_other(self, ev: ChronikEvent, origins: set[str]) -> bool:
        """Return True if another entry of the same source and given origin overlaps."""
        now = dt_util.utcnow()
        end = effective_end(ev, now)
        for other in self.all():
            if other.start >= end:
                break
            if (
                other.uid != ev.uid
                and other.category == ev.category
                and other.source == ev.source
                and other.origin in origins
                and other.data.get("kind") == ev.data.get("kind")
                and effective_end(other, now) > ev.start
            ):
                return True
        return False

    def purge(self, before: datetime) -> int:
        """Remove closed entries that ended before a date."""
        old = [uid for uid, ev in self._events.items() if ev.end is not None and ev.end < before]
        for uid in old:
            del self._events[uid]
        if old:
            self._changed()
        return len(old)
