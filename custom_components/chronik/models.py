"""Data model of a Chronik entry (pure Python, no Home Assistant)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .const import ORIGIN_LIVE


def make_uid(category: str, source: str, start: datetime) -> str:
    """Build a deterministic uid so live and backfill produce the same id."""
    return f"{category}:{source}:{start.astimezone(UTC).strftime('%Y%m%dT%H%M%S')}"


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class ChronikEvent:
    """A single entry of the Chronik."""

    uid: str
    category: str
    start: datetime
    end: datetime | None
    title: str
    description: str = ""
    source: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    origin: str = ORIGIN_LIVE

    @property
    def is_open(self) -> bool:
        """Return True while the event is still running."""
        return self.end is None

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage."""
        result = asdict(self)
        result["start"] = self.start.isoformat()
        result["end"] = self.end.isoformat() if self.end else None
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronikEvent:
        """Deserialise from storage."""
        return cls(
            uid=data["uid"],
            category=data["category"],
            start=datetime.fromisoformat(data["start"]),
            end=_parse(data.get("end")),
            title=data.get("title", ""),
            description=data.get("description", ""),
            source=data.get("source"),
            data=dict(data.get("data") or {}),
            origin=data.get("origin", ORIGIN_LIVE),
        )

    def copy(self) -> ChronikEvent:
        """Return an independent copy."""
        return ChronikEvent.from_dict(self.as_dict())
