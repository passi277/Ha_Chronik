"""Alarms: triggered alarm panels, sirens and problem binary sensors."""

from __future__ import annotations

from ..const import CAT_ALARM
from ..models import ChronikEvent
from .base import Action, RunDetector, Snapshot, Upsert


class AlarmDetector(RunDetector):
    """Alarm panel 'triggered' or entity 'on' is one alarm."""

    category = CAT_ALARM

    def __init__(self, lang: str | None, entities: list[str], *, log_arming: bool = False) -> None:
        super().__init__(lang, entities)
        self.log_arming = log_arming
        self._last_state: dict[str, str] = {}

    def is_active(self, snap: Snapshot) -> bool | None:
        if not snap.valid:
            return None
        if snap.domain == "alarm_control_panel":
            return snap.state.lower() == "triggered"
        return snap.state.lower() == "on"

    def feed(self, snap: Snapshot) -> list[Action]:
        actions = super().feed(snap)
        if not snap.valid or snap.domain != "alarm_control_panel":
            return actions
        state = snap.state.lower()
        previous = self._last_state.get(snap.entity_id)
        self._last_state[snap.entity_id] = state
        label = self.t["arming"].get(state)
        if self.log_arming and label and previous is not None and previous != state:
            ev = self.point(f"{snap.entity_id}#{state}", snap.when, {"kind": "arming", "state": state})
            icon = "🔓" if state == "disarmed" else "🔒"
            ev.title = f"{icon} {snap.name}: {label}"
            ev.description = f"{self.t['source']}: {snap.entity_id}"
            actions.append(Upsert(ev))
        return actions

    def render(self, ev: ChronikEvent) -> None:
        name = ev.data.get("name", ev.source)
        if (ev.source or "").startswith("alarm_control_panel."):
            name = f"{name} {self.t['triggered']}"
        ev.title = f"{self.emoji} {name} · {self.duration_text(ev)}"
        ev.description = self.base_description(ev)
