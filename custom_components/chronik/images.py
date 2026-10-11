"""Find image files (e.g. LLM Vision snapshots) that belong to an entry."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import os
import re
import shutil

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


MEDIA_SOURCE_PREFIX = "media-source://media_source/local/"
STORE_FOLDER = "chronik"


def copy_images(paths: list[str], uid: str, media_root: str) -> list[str]:
    """Copy images into <media_root>/chronik so they survive cleanups (blocking I/O).

    Returns media-source URIs of the copies (falls back to the original path).
    """
    target = os.path.join(media_root, STORE_FOLDER)
    os.makedirs(target, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", uid)
    result = []
    for index, path in enumerate(paths):
        ext = os.path.splitext(path)[1].lower() or ".jpg"
        name = f"{stem}-{index}{ext}"
        try:
            shutil.copy2(path, os.path.join(target, name))
        except OSError:
            result.append(path)
            continue
        result.append(f"{MEDIA_SOURCE_PREFIX}{STORE_FOLDER}/{name}")
    return result


def delete_copies(paths: list[str], media_root: str) -> None:
    """Delete copies made by copy_images (blocking I/O)."""
    prefix = f"{MEDIA_SOURCE_PREFIX}{STORE_FOLDER}/"
    for path in paths:
        if path.startswith(prefix):
            with contextlib.suppress(OSError):
                os.remove(os.path.join(media_root, STORE_FOLDER, os.path.basename(path)))
