"""Find image files (e.g. LLM Vision snapshots) that belong to an entry."""

from __future__ import annotations

from datetime import datetime, timedelta
import os

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
# Files written slightly after the finding (clock skew, slow writes) still count.
AFTER_SLACK = timedelta(seconds=30)
MAX_IMAGES = 6


def parse_dirs(value: str | list[str] | None) -> list[str]:
    """Split the configured folders (one per line or comma separated)."""
    if not value:
        return []
    items = value if isinstance(value, list) else value.replace(",", "\n").splitlines()
    return [item.strip().rstrip("/") for item in items if item.strip()]


def find_images(dirs: list[str], when: datetime, window: timedelta) -> list[str]:
    """Return image paths modified within `window` before `when` (blocking I/O)."""
    start = (when - window).timestamp()
    end = (when + AFTER_SLACK).timestamp()
    found: list[tuple[float, str]] = []
    for folder in dirs:
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if os.path.splitext(entry.name)[1].lower() not in IMAGE_EXTENSIONS:
                        continue
                    try:
                        if not entry.is_file():
                            continue
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    if start <= mtime <= end:
                        found.append((mtime, entry.path))
        except OSError:
            continue
    found.sort()
    return [path for _mtime, path in found[-MAX_IMAGES:]]
