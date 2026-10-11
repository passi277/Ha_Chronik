"""AI findings: every new text of a text entity is one entry."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..const import CAT_AI
from ..models import ChronikEvent
from ..texts import truncate
from .base import Action, Detector, Snapshot, Upsert

TITLE_TEXT_LENGTH = 70
# A text that already appeared this recently is not a new finding
# (e.g. an automation restoring the previous value).
REPEAT_WINDOW = timedelta(hours=24)


class AiDetector(Detector):
    """Logs content changes of input_text/sensor entities holding AI results."""

    category = CAT_AI

    def __init__(self, lang: str | None, entities: list[str]) -> None:
        super().__init__(lang)
        self._entities = list(entities)
        self._last: dict[str, str] = {}
        self._seen: dict[str, dict[str, datetime]] = {}

    @property
    def entities(self) -> list[str]:
        return list(self._entities)

    def restore(self, events: list[ChronikEvent]) -> None:
        for ev in sorted(events, key=lambda e: e.start):
            if ev.source in self._entities and "text" in ev.data:
                self._last[ev.source] = ev.data["text"]
                self._seen.setdefault(ev.source, {})[ev.data["text"]] = ev.start

    def feed(self, snap: Snapshot) -> list[Action]:
        if snap.entity_id not in self._entities or not snap.valid:
            return []
        text = snap.state.strip()
        previous = self._last.get(snap.entity_id)
        self._last[snap.entity_id] = text
        seen = self._seen.setdefault(snap.entity_id, {})
        last_seen = seen.get(text)
        seen[text] = snap.when
        for old_text, when in list(seen.items()):
            if snap.when - when > REPEAT_WINDOW:
                del seen[old_text]
        if previous is None or previous == text:
            # First value seen is only the baseline.
            return []
        if last_seen is not None and timedelta(0) <= snap.when - last_seen <= REPEAT_WINDOW:
            return []
        ev = self.point(snap.entity_id, snap.when, {"kind": "finding", "text": text, "name": snap.name})
        ev.title = f"{self.emoji} {snap.name}: {truncate(text, TITLE_TEXT_LENGTH)}"
        ev.description = f"{text}\n\n{self.t['source']}: {snap.entity_id}"
        return [Upsert(ev)]
