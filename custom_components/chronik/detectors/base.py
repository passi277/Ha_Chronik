"""Detector base classes.

Detectors are pure state machines: they are fed state snapshots in
chronological order and return actions (upsert/delete of entries). The same
code runs live (state change events) and for backfill (recorder history).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..const import ACTIVE_STATES, CATEGORY_EMOJI, INVALID_STATES
from ..models import ChronikEvent, make_uid
from ..texts import format_duration, texts


@dataclass(frozen=True)
class Snapshot:
    """The state of an entity at a point in time."""

    entity_id: str
    state: str
    when: datetime
    name: str
    device_name: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        """Return the entity domain."""
        return self.entity_id.split(".", 1)[0]

    @property
    def valid(self) -> bool:
        """Return False for unknown/unavailable states."""
        return self.state.lower() not in INVALID_STATES

    def number(self) -> float | None:
        """Return the state as float, or None."""
        if not self.valid:
            return None
        try:
            return float(self.state)
        except ValueError:
            return None


@dataclass
class Upsert:
    """Create or replace an entry."""

    event: ChronikEvent


@dataclass
class Delete:
    """Remove an entry."""

    uid: str


Action = Upsert | Delete


class Detector:
    """Base class of all detectors."""

    category: str

    def __init__(self, lang: str | None) -> None:
        self.lang = lang
        self.t = texts(lang)
        self.emoji = CATEGORY_EMOJI[self.category]

    @property
    def entities(self) -> list[str]:
        """Return all entities this detector listens to."""
        raise NotImplementedError

    def restore(self, events: list[ChronikEvent]) -> None:
        """Restore internal state from recent stored events of this category."""

    def feed(self, snap: Snapshot) -> list[Action]:
        """Process a new state and return resulting actions."""
        raise NotImplementedError

    def point(self, source: str, when: datetime, data: dict[str, Any]) -> ChronikEvent:
        """Create a point event (start == end)."""
        return ChronikEvent(
            uid=make_uid(self.category, source, when),
            category=self.category,
            start=when,
            end=when,
            title="",
            source=source.split("#", 1)[0],
            data=data,
        )


class RunDetector(Detector):
    """Detects periods during which an entity is active (on → off)."""

    prefer_device_name = False

    def __init__(
        self,
        lang: str | None,
        run_entities: list[str],
        *,
        merge_minutes: float = 0,
        min_minutes: float = 0,
    ) -> None:
        super().__init__(lang)
        self.run_entities = list(run_entities)
        self.merge_window = timedelta(minutes=merge_minutes)
        self.min_duration = timedelta(minutes=min_minutes)
        self._open: dict[str, ChronikEvent] = {}
        self._last_closed: dict[str, ChronikEvent] = {}

    @property
    def entities(self) -> list[str]:
        return list(self.run_entities)

    # Hooks -----------------------------------------------------------------

    def is_active(self, snap: Snapshot) -> bool | None:
        """Return whether the entity is active, None to ignore the state."""
        if not snap.valid:
            return None
        return snap.state.lower() in ACTIVE_STATES

    def render(self, ev: ChronikEvent) -> None:
        """Set title and description of an event from its data."""
        ev.title = f"{self.emoji} {ev.data.get('name', ev.source)} · {self.duration_text(ev)}"
        ev.description = self.base_description(ev)

    def on_start(self, ev: ChronikEvent, snap: Snapshot) -> list[Action]:
        """Called when a new run starts."""
        return []

    def on_close(self, ev: ChronikEvent, snap: Snapshot) -> list[Action]:
        """Called when a run ends."""
        return []

    def feed_other(self, snap: Snapshot) -> list[Action]:
        """Handle states of additional (non run) entities."""
        return []

    # Helpers ---------------------------------------------------------------

    def name_for(self, snap: Snapshot) -> str:
        """Return the display name for a run entity."""
        if self.prefer_device_name and snap.device_name:
            return snap.device_name
        return snap.name

    def duration_text(self, ev: ChronikEvent) -> str:
        """Return the run duration, or 'running'."""
        if ev.is_open:
            return self.t["running"]
        return format_duration(ev.data.get("active_s", 0))

    def base_description(self, ev: ChronikEvent, extra: list[str] | None = None) -> str:
        """Return a description with duration, extra lines and source."""
        lines = []
        if not ev.is_open:
            lines.append(f"{self.t['duration']}: {self.duration_text(ev)}")
        lines.extend(extra or [])
        lines.append(f"{self.t['source']}: {ev.source}")
        return "\n".join(lines)

    def recent_runs(self) -> list[ChronikEvent]:
        """Return open runs and the last closed run per entity."""
        return list(self._open.values()) + list(self._last_closed.values())

    # Core ------------------------------------------------------------------

    def restore(self, events: list[ChronikEvent]) -> None:
        for ev in sorted(events, key=lambda e: e.start):
            if ev.source not in self.run_entities or ev.data.get("kind") != "run":
                continue
            if ev.is_open:
                self._open[ev.source] = ev.copy()
            else:
                self._open.pop(ev.source, None)
                self._last_closed[ev.source] = ev.copy()

    def feed(self, snap: Snapshot) -> list[Action]:
        if snap.entity_id not in self.run_entities:
            return self.feed_other(snap)
        active = self.is_active(snap)
        if active is None:
            return []
        eid = snap.entity_id
        ev = self._open.get(eid)
        if active:
            return [] if ev else self._start(snap)
        return self._close(ev, snap) if ev else []

    def _start(self, snap: Snapshot) -> list[Action]:
        eid, when = snap.entity_id, snap.when
        last = self._last_closed.get(eid)
        if (
            last is not None
            and self.merge_window
            and last.end is not None
            and timedelta(0) <= when - last.end <= self.merge_window
        ):
            # Short pause: continue the previous run.
            ev = last
            del self._last_closed[eid]
            ev.end = None
            ev.data["seg_start"] = when.isoformat()
            ev.data["pauses"] = ev.data.get("pauses", 0) + 1
            actions: list[Action] = []
        else:
            ev = ChronikEvent(
                uid=make_uid(self.category, eid, when),
                category=self.category,
                start=when,
                end=None,
                title="",
                source=eid,
                data={"kind": "run", "active_s": 0, "seg_start": when.isoformat()},
            )
            actions = self.on_start(ev, snap)
        ev.data["name"] = self.name_for(snap)
        self._open[eid] = ev
        self.render(ev)
        return [*actions, Upsert(ev.copy())]

    def _close(self, ev: ChronikEvent, snap: Snapshot) -> list[Action]:
        eid = snap.entity_id
        del self._open[eid]
        end = max(snap.when, ev.start)
        seg_start = datetime.fromisoformat(ev.data.pop("seg_start", ev.start.isoformat()))
        ev.data["active_s"] = ev.data.get("active_s", 0) + max(0.0, (end - seg_start).total_seconds())
        ev.end = end
        if ev.data["active_s"] < self.min_duration.total_seconds():
            return [Delete(ev.uid)]
        actions = self.on_close(ev, snap)
        self._last_closed[eid] = ev
        self.render(ev)
        return [*actions, Upsert(ev.copy())]
