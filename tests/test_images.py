"""Linking snapshot images to AI findings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chronik.const import DOMAIN
from custom_components.chronik.images import copy_images, delete_copies, find_images, parse_dirs


def _touch(path: Path, when: datetime) -> None:
    path.write_bytes(b"x")
    os.utime(path, (when.timestamp(), when.timestamp()))


def test_find_images(tmp_path: Path) -> None:
    now = datetime(2026, 10, 11, 12, 30, tzinfo=UTC)
    _touch(tmp_path / "old.jpg", now - timedelta(minutes=20))
    _touch(tmp_path / "pool.jpg", now - timedelta(minutes=1))
    _touch(tmp_path / "cam2.png", now - timedelta(seconds=30))
    _touch(tmp_path / "notes.txt", now - timedelta(seconds=10))
    found = find_images([str(tmp_path), "/does/not/exist"], now, timedelta(minutes=3))
    assert [Path(p).name for p in found] == ["pool.jpg", "cam2.png"]
    assert parse_dirs("/a/, /b\n\n/c") == ["/a", "/b", "/c"]

    media = tmp_path / "media"
    copies = copy_images([str(tmp_path / "pool.jpg"), "/missing.jpg"], "ai:x:1", str(media))
    assert copies == ["media-source://media_source/local/chronik/ai_x_1-0.jpg", "/missing.jpg"]
    assert (media / "chronik" / "ai_x_1-0.jpg").exists()
    delete_copies(copies, str(media))
    assert not (media / "chronik" / "ai_x_1-0.jpg").exists()


async def test_ai_finding_gets_images(hass: HomeAssistant, tmp_path: Path, hass_ws_client) -> None:
    """A new AI text picks up the snapshot written just before it."""
    hass.config.language = "de"
    hass.states.async_set("input_text.pool_ki", "Wasser trüb", {"friendly_name": "Pool KI-Befund"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={"ai_entities": ["input_text.pool_ki"], "ai_image_dirs": str(tmp_path)},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    snapshot = tmp_path / "pool_snapshot.jpg"
    snapshot.write_bytes(b"x")
    hass.states.async_set("input_text.pool_ki", "Wasser klar", {"friendly_name": "Pool KI-Befund"})
    await hass.async_block_till_done()

    events = entry.runtime_data.store.all()
    assert len(events) == 1
    # The snapshot is copied into <media>/chronik and referenced via media source.
    [image] = events[0].data["images"]
    assert image.startswith("media-source://media_source/local/chronik/")
    media_root = hass.config.media_dirs.get("local") or hass.config.path("media")
    copy = Path(media_root, "chronik", image.rsplit("/", 1)[1])
    assert copy.read_bytes() == b"x"

    # Deleting the entry removes the copy.
    await hass.services.async_call(DOMAIN, "delete_entry", {"uid": events[0].uid}, blocking=True)
    await hass.async_block_till_done()
    assert not copy.exists()

    # Images given to add_entry are stored as well.
    await hass.services.async_call(
        DOMAIN,
        "add_entry",
        {"category": "ai", "title": "Manuell", "images": ["/local/a.jpg"]},
        blocking=True,
    )
    manual = [ev for ev in entry.runtime_data.store.all() if ev.title == "Manuell"][0]
    assert manual.data["images"] == ["/local/a.jpg"]
