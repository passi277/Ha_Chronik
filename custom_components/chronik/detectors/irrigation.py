"""Irrigation runs per zone, optionally with water volume from a meter."""

from __future__ import annotations

from ..const import CAT_IRRIGATION
from ..models import ChronikEvent
from ..texts import format_number
from .base import Action, RunDetector, Snapshot, Upsert


class IrrigationDetector(RunDetector):
    """A zone entity on → off is one irrigation run."""

    category = CAT_IRRIGATION
    prefer_device_name = True

    def __init__(
        self,
        lang: str | None,
        zones: list[str],
        meter: str | None = None,
        *,
        min_minutes: float = 1,
    ) -> None:
        super().__init__(lang, zones, min_minutes=min_minutes)
        self.meter = meter
        self._meter_value: float | None = None

    @property
    def entities(self) -> list[str]:
        return [*self.run_entities, *([self.meter] if self.meter else [])]

    def feed_other(self, snap: Snapshot) -> list[Action]:
        if snap.entity_id != self.meter:
            return []
        value = snap.number()
        if value is None:
            return []
        self._meter_value = value
        actions: list[Action] = []
        for ev in self._open.values():
            if self._update_volume(ev):
                self.render(ev)
                actions.append(Upsert(ev.copy()))
        return actions

    def _update_volume(self, ev: ChronikEvent) -> bool:
        start = ev.data.get("meter_start")
        if start is None or self._meter_value is None:
            return False
        liters = round(self._meter_value - start, 1)
        if liters < 0 or liters == ev.data.get("liters"):
            return False
        ev.data["liters"] = liters
        return True

    def on_start(self, ev: ChronikEvent, snap: Snapshot) -> list[Action]:
        if self._meter_value is not None:
            ev.data["meter_start"] = self._meter_value
        return []

    def on_close(self, ev: ChronikEvent, snap: Snapshot) -> list[Action]:
        self._update_volume(ev)
        return []

    def render(self, ev: ChronikEvent) -> None:
        parts = [f"{self.emoji} {ev.data.get('name', ev.source)}", self.duration_text(ev)]
        extra = []
        if ev.data.get("liters"):
            liters = f"{format_number(ev.data['liters'], self.lang, 0)} L"
            parts.append(liters)
            extra.append(f"{self.t['water']}: {liters}")
        ev.title = " · ".join(parts)
        ev.description = self.base_description(ev, extra)
