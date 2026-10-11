"""Daily summary of all entries (pure Python, no Home Assistant)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .const import (
    CAT_AI,
    CAT_ALARM,
    CAT_IRRIGATION,
    CAT_MOWING,
    CAT_POOL,
    CAT_RAIN,
    CATEGORY_EMOJI,
)
from .models import ChronikEvent
from .texts import format_duration, format_number, texts


def _run_seconds(ev: ChronikEvent) -> float:
    if "active_s" in ev.data and not ev.is_open:
        return float(ev.data["active_s"])
    if ev.end:
        return (ev.end - ev.start).total_seconds()
    return 0.0


def build_summary(
    events: list[ChronikEvent],
    lang: str | None,
    to_local: Callable[[datetime], datetime],
) -> tuple[str, str] | None:
    """Return (title, description) for the entries of one day, or None."""
    if not events:
        return None
    t = texts(lang)
    by_cat: dict[str, list[ChronikEvent]] = {}
    for ev in events:
        by_cat.setdefault(ev.category, []).append(ev)

    parts: list[str] = []
    if rain := by_cat.get(CAT_RAIN):
        mm = sum(float(ev.data.get("mm", 0)) for ev in rain)
        unit = rain[0].data.get("unit", "mm")
        parts.append(f"{CATEGORY_EMOJI[CAT_RAIN]} {format_number(mm, lang)} {unit}")
    if irrigation := [e for e in by_cat.get(CAT_IRRIGATION, []) if e.data.get("kind") == "run"]:
        duration = format_duration(sum(map(_run_seconds, irrigation)))
        text = f"{CATEGORY_EMOJI[CAT_IRRIGATION]} {len(irrigation)}× · {duration}"
        liters = sum(float(e.data.get("liters") or 0) for e in irrigation)
        if liters:
            text += f" · {format_number(liters, lang, 0)} L"
        parts.append(text)
    if mowing := [e for e in by_cat.get(CAT_MOWING, []) if e.data.get("kind") == "run"]:
        parts.append(f"{CATEGORY_EMOJI[CAT_MOWING]} {format_duration(sum(map(_run_seconds, mowing)))}")
    if pool := by_cat.get(CAT_POOL):
        parts.append(f"{CATEGORY_EMOJI[CAT_POOL]} {len(pool)}×")
    if alarm := [e for e in by_cat.get(CAT_ALARM, []) if e.data.get("kind") != "arming"]:
        parts.append(f"{CATEGORY_EMOJI[CAT_ALARM]} {len(alarm)}")
    if ai := by_cat.get(CAT_AI):
        parts.append(f"{CATEGORY_EMOJI[CAT_AI]} {len(ai)} {t['finding'] if len(ai) == 1 else t['findings']}")
    # Categories without a dedicated formatter (e.g. manual notes).
    known = {CAT_RAIN, CAT_IRRIGATION, CAT_MOWING, CAT_POOL, CAT_ALARM, CAT_AI}
    other = [e for e in events if e.category not in known]
    if other:
        parts.append(f"📝 {len(other)}")
    if not parts:
        parts.append(f"📝 {len(events)}")

    title = f"{CATEGORY_EMOJI['summary']} " + " · ".join(parts)
    lines = [
        f"{to_local(ev.start).strftime('%H:%M')} {ev.title}" for ev in sorted(events, key=lambda e: e.start)
    ]
    return title, "\n".join(lines)
