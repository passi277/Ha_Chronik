"""Rain episodes from a daily (or total) rain amount sensor."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..const import CAT_RAIN, RAIN_LEAD
from ..models import ChronikEvent, make_uid
from ..texts import format_duration, format_number
from .base import Action, Detector, Snapshot, Upsert


class RainDetector(Detector):
    """Each increase of the sensor adds rain; a gap ends the episode."""

    category = CAT_RAIN

    def __init__(self, lang: str | None, sensor: str, *, gap_minutes: float = 60) -> None:
        super().__init__(lang)
        self.sensor = sensor
        self.gap = timedelta(minutes=gap_minutes)
        self._value: float | None = None
        self._value_when: datetime | None = None
        self._episode: ChronikEvent | None = None

    @property
    def entities(self) -> list[str]:
        return [self.sensor]

    def restore(self, events: list[ChronikEvent]) -> None:
        mine = [e for e in events if e.source == self.sensor and e.end]
        if mine:
            self._episode = max(mine, key=lambda e: e.end).copy()

    def feed(self, snap: Snapshot) -> list[Action]:
        if snap.entity_id != self.sensor:
            return []
        value = snap.number()
        if value is None:
            return []
        previous, previous_when = self._value, self._value_when
        self._value, self._value_when = value, snap.when
        if previous is None:
            return []
        # A drop means the daily counter was reset; the new value is new rain.
        delta = value - previous if value >= previous else value
        if delta <= 0:
            return []
        ep = self._episode
        if ep is not None and ep.end is not None and timedelta(0) <= snap.when - ep.end <= self.gap:
            ep.end = snap.when
            ep.data["mm"] = round(ep.data.get("mm", 0) + delta, 2)
        else:
            start = snap.when - RAIN_LEAD
            if previous_when is not None:
                start = max(start, previous_when)
            ep = ChronikEvent(
                uid=make_uid(self.category, self.sensor, start),
                category=self.category,
                start=start,
                end=snap.when,
                title="",
                source=self.sensor,
                data={"kind": "rain", "mm": round(delta, 2)},
            )
            self._episode = ep
        unit = snap.attributes.get("unit_of_measurement") or "mm"
        ep.data["unit"] = unit
        self.render(ep)
        return [Upsert(ep.copy())]

    def render(self, ev: ChronikEvent) -> None:
        amount = f"{format_number(ev.data.get('mm', 0), self.lang)} {ev.data.get('unit', 'mm')}"
        ev.title = f"{self.emoji} {self.t['rain']} · {amount}"
        duration = format_duration(((ev.end or ev.start) - ev.start).total_seconds())
        ev.description = "\n".join(
            [
                f"{self.t['amount']}: {amount}",
                f"{self.t['duration']}: {duration}",
                f"{self.t['source']}: {ev.source}",
            ]
        )
