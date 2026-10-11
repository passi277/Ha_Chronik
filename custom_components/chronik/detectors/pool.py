"""Pool maintenance: backwash runs and counter resets."""

from __future__ import annotations

from datetime import timedelta

from ..const import CAT_POOL, POOL_ATTACH_WINDOW
from ..models import ChronikEvent
from ..texts import format_number
from .base import Action, Delete, RunDetector, Snapshot, Upsert


class PoolDetector(RunDetector):
    """Active timer/switch = backwash run; counter drop to ~0 = backwash done."""

    category = CAT_POOL

    def __init__(
        self,
        lang: str | None,
        run_entities: list[str],
        counters: list[str] | None = None,
        *,
        threshold: float = 1.0,
    ) -> None:
        super().__init__(lang, run_entities)
        self.counters = list(counters or [])
        self.threshold = threshold
        self._counter_values: dict[str, float] = {}
        self._last_reset: ChronikEvent | None = None

    @property
    def entities(self) -> list[str]:
        return [*self.run_entities, *self.counters]

    def restore(self, events: list[ChronikEvent]) -> None:
        super().restore(events)
        resets = [e for e in events if e.data.get("kind") == "reset"]
        if resets:
            self._last_reset = max(resets, key=lambda e: e.start).copy()

    def feed_other(self, snap: Snapshot) -> list[Action]:
        if snap.entity_id not in self.counters:
            return []
        value = snap.number()
        if value is None:
            return []
        previous = self._counter_values.get(snap.entity_id)
        self._counter_values[snap.entity_id] = value
        if previous is None or not (value < previous and value <= self.threshold < previous):
            return []
        info = {
            "counter_before": previous,
            "counter_unit": snap.attributes.get("unit_of_measurement", ""),
            "counter_name": snap.name,
        }
        # Attach to a run that is running or ended shortly before.
        for run in self.recent_runs():
            end = run.end or snap.when
            if snap.when - end <= POOL_ATTACH_WINDOW and run.start - POOL_ATTACH_WINDOW <= snap.when:
                run.data.update(info)
                self.render(run)
                return [Upsert(run.copy())]
        ev = self.point(f"{snap.entity_id}#reset", snap.when, {"kind": "reset", **info})
        self.render(ev)
        self._last_reset = ev
        return [Upsert(ev.copy())]

    def on_start(self, ev: ChronikEvent, snap: Snapshot) -> list[Action]:
        reset = self._last_reset
        if reset is not None and timedelta(0) <= snap.when - reset.start <= POOL_ATTACH_WINDOW:
            # The counter was reset just before the run: merge both.
            self._last_reset = None
            for key in ("counter_before", "counter_unit", "counter_name"):
                ev.data[key] = reset.data.get(key)
            return [Delete(reset.uid)]
        return []

    def _after(self, ev: ChronikEvent) -> str | None:
        if ev.data.get("counter_before") is None:
            return None
        unit = ev.data.get("counter_unit") or ""
        return f"{format_number(ev.data['counter_before'], self.lang)} {unit}".strip()

    def render(self, ev: ChronikEvent) -> None:
        after = self._after(ev)
        if ev.data.get("kind") == "reset":
            ev.title = f"{self.emoji} " + self.t["reset"].format(
                name=ev.data.get("counter_name"), value=after
            )
            ev.description = f"{self.t['source']}: {ev.source}"
            return
        parts = [f"{self.emoji} {ev.data.get('name', ev.source)}", self.duration_text(ev)]
        extra = []
        if after:
            parts.append(self.t["after"].format(value=after))
            extra.append(f"{ev.data.get('counter_name')}: {after}")
        ev.title = " · ".join(parts)
        ev.description = self.base_description(ev, extra)
