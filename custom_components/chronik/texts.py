"""Localised texts and formatting helpers (pure Python, no Home Assistant)."""

from __future__ import annotations

from typing import Any

_TEXTS: dict[str, dict[str, Any]] = {
    "de": {
        "running": "läuft",
        "rain": "Regen",
        "mowing": "Mähen",
        "error": "Fehler",
        "triggered": "ausgelöst",
        "after": "nach {value}",
        "reset": "{name} zurückgesetzt (vorher {value})",
        "duration": "Dauer",
        "amount": "Menge",
        "water": "Wasser",
        "source": "Quelle",
        "text": "Befund",
        "backwash": "Rückspülen",
        "summary": "Tagesbilanz",
        "finding": "Befund",
        "findings": "Befunde",
        "runs": "Läufe",
        "arming": {
            "armed_away": "scharf (abwesend)",
            "armed_home": "scharf (zuhause)",
            "armed_night": "scharf (Nacht)",
            "armed_vacation": "scharf (Urlaub)",
            "armed_custom_bypass": "scharf (benutzerdefiniert)",
            "disarmed": "unscharf",
        },
    },
    "en": {
        "running": "running",
        "rain": "Rain",
        "mowing": "Mowing",
        "error": "error",
        "triggered": "triggered",
        "after": "after {value}",
        "reset": "{name} reset (was {value})",
        "duration": "Duration",
        "amount": "Amount",
        "water": "Water",
        "source": "Source",
        "text": "Finding",
        "backwash": "Backwash",
        "summary": "Daily summary",
        "finding": "finding",
        "findings": "findings",
        "runs": "runs",
        "arming": {
            "armed_away": "armed (away)",
            "armed_home": "armed (home)",
            "armed_night": "armed (night)",
            "armed_vacation": "armed (vacation)",
            "armed_custom_bypass": "armed (custom)",
            "disarmed": "disarmed",
        },
    },
}


def texts(lang: str | None) -> dict[str, Any]:
    """Return the text table for a language (German or English)."""
    return _TEXTS["de"] if (lang or "").lower().startswith("de") else _TEXTS["en"]


def is_german(lang: str | None) -> bool:
    """Return True if the language uses German number formatting."""
    return (lang or "").lower().startswith("de")


def format_number(value: float, lang: str | None, digits: int = 1) -> str:
    """Format a number with the decimal separator of the language."""
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if is_german(lang) else text


def format_duration(seconds: float) -> str:
    """Format a duration as '18 min' or '1 h 20 min'."""
    minutes = int(round(seconds / 60))
    if seconds > 0 and minutes == 0:
        return "<1 min"
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def truncate(text: str, length: int) -> str:
    """Shorten text to a maximum length, adding an ellipsis."""
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"
