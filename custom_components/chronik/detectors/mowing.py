"""Lawn mower sessions; short pauses are merged into one session."""

from __future__ import annotations

from ..const import CAT_MOWING
from ..models import ChronikEvent
from .base import Action, RunDetector, Snapshot, Upsert


class MowingDetector(RunDetector):
    """'mowing' → anything else is one mowing session; 'error' is logged."""

    category = CAT_MOWING
    prefer_device_name = True

    def __init__(
        self,
        lang: str | None,
        mowers: list[str],
        *,
        merge_minutes: float = 20,
        min_minutes: float = 1,
    ) -> None:
        super().__init__(lang, mowers, merge_minutes=merge_minutes, min_minutes=min_minutes)
        self._last_state: dict[str, str] = {}

    def is_active(self, snap: Snapshot) -> bool | None:
        if not snap.valid:
            return None
        return snap.state.lower() == "mowing"

    def feed(self, snap: Snapshot) -> list[Action]:
        actions = super().feed(snap)
        if not snap.valid:
            return actions
        state = snap.state.lower()
        previous = self._last_state.get(snap.entity_id)
        self._last_state[snap.entity_id] = state
        if state == "error" and previous is not None and previous != "error":
            name = self.name_for(snap)
            ev = self.point(f"{snap.entity_id}#error", snap.when, {"kind": "error", "name": name})
            ev.title = f"⚠️ {name}: {self.t['error']}"
            ev.description = f"{self.t['source']}: {snap.entity_id}"
            actions.append(Upsert(ev))
        return actions

    def render(self, ev: ChronikEvent) -> None:
        label = self.t["mowing"]
        if len(self.run_entities) > 1:
            label = f"{label} {ev.data.get('name', ev.source)}"
        ev.title = f"{self.emoji} {label} · {self.duration_text(ev)}"
        ev.description = self.base_description(ev, [f"{ev.data.get('name', ev.source)}"])
