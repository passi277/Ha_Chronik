"""Connects detectors, storage and calendar entities."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from functools import partial
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    CAT_AI,
    CATEGORIES,
    CATEGORY_SOURCES,
    CONF_AI_IMAGE_DIRS,
    CONF_AI_IMAGE_WINDOW,
    CONF_RETENTION_DAYS,
    DEFAULTS,
    ORIGIN_BACKFILL,
    ORIGIN_LIVE,
    ORIGIN_MANUAL,
    RESTORE_WINDOW,
    signal_updated,
)
from .detectors import Action, Delete, Detector, Snapshot, Upsert, build_detectors
from .images import find_images, parse_dirs
from .models import ChronikEvent
from .store import ChronikStore

_LOGGER = logging.getLogger(__name__)


class ChronikCoordinator:
    """Runs the detectors of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.options: dict[str, Any] = {**DEFAULTS, **entry.options}
        self.lang = hass.config.language
        self.store = ChronikStore(hass, entry.entry_id)
        self.detectors: list[Detector] = build_detectors(self.options, self.lang)
        self._by_entity = self._index(self.detectors)
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def enabled_categories(self) -> list[str]:
        """Return the categories that have sources configured."""
        return [cat for cat in CATEGORIES if any(self.options.get(key) for key in CATEGORY_SOURCES[cat])]

    @staticmethod
    def _index(detectors: list[Detector]) -> dict[str, list[Detector]]:
        index: dict[str, list[Detector]] = defaultdict(list)
        for det in detectors:
            for entity_id in det.entities:
                index[entity_id].append(det)
        return index

    # Lifecycle ---------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load storage, restore detectors and start listening."""
        await self.store.async_load()
        self._purge()
        since = dt_util.utcnow() - RESTORE_WINDOW
        for det in self.detectors:
            det.restore(self.store.recent(det.category, since))

        if self._by_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, list(self._by_entity), self._handle_state_event)
            )
        self._unsubs.append(async_at_started(self.hass, self._feed_current_states))
        self._unsubs.append(
            async_track_time_change(self.hass, self._handle_purge, hour=3, minute=17, second=0)
        )

    async def async_shutdown(self) -> None:
        """Stop listening and flush storage."""
        while self._unsubs:
            self._unsubs.pop()()
        await self.store.async_save()

    @callback
    def _feed_current_states(self, _hass: HomeAssistant) -> None:
        """Feed current states once HA is running (closes or continues open runs)."""
        changed = False
        for entity_id, detectors in self._by_entity.items():
            if (state := self.hass.states.get(entity_id)) is None:
                continue
            snap = self._snapshot(state)
            for det in detectors:
                changed |= self._apply(det.feed(snap), ORIGIN_LIVE)
        if changed:
            self._notify()

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        if (state := event.data["new_state"]) is None:
            return
        snap = self._snapshot(state)
        changed = False
        for det in self._by_entity.get(state.entity_id, []):
            changed |= self._apply(det.feed(snap), ORIGIN_LIVE)
        if changed:
            self._notify()

    @callback
    def _handle_purge(self, _now: datetime) -> None:
        if self._purge():
            self._notify()

    def _purge(self) -> int:
        days = int(self.options.get(CONF_RETENTION_DAYS) or 0)
        if days <= 0:
            return 0
        return self.store.purge(dt_util.utcnow() - timedelta(days=days))

    # Helpers -----------------------------------------------------------------

    def _snapshot(self, state: State, current: State | None = None) -> Snapshot:
        """Build a detector snapshot; names come from the current registry."""
        current = current or self.hass.states.get(state.entity_id) or state
        device_name = None
        entry = er.async_get(self.hass).async_get(state.entity_id)
        if entry and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            if device:
                device_name = device.name_by_user or device.name
        return Snapshot(
            entity_id=state.entity_id,
            state=state.state,
            when=state.last_changed,
            name=current.name,
            device_name=device_name,
            attributes=state.attributes,
        )

    def _apply(self, actions: list[Action], origin: str) -> bool:
        changed = False
        for action in actions:
            if isinstance(action, Upsert):
                ev = action.event
                existing = self.store.get(ev.uid)
                if origin == ORIGIN_BACKFILL:
                    if existing is not None and existing.origin != ORIGIN_BACKFILL:
                        continue
                    if self.store.overlapping_other(ev, {ORIGIN_LIVE, ORIGIN_MANUAL}):
                        continue
                ev.origin = existing.origin if existing and origin == ORIGIN_LIVE else origin
                if existing and existing.data.get("images") and not ev.data.get("images"):
                    ev.data["images"] = existing.data["images"]
                self.store.upsert(ev)
                changed = True
                if origin == ORIGIN_LIVE and self._wants_images(ev):
                    self.hass.async_create_task(self._async_attach_images(ev.uid))
            elif isinstance(action, Delete):
                existing = self.store.get(action.uid)
                if existing and (origin != ORIGIN_BACKFILL or existing.origin == ORIGIN_BACKFILL):
                    changed |= self.store.delete(action.uid)
        return changed

    # Images -----------------------------------------------------------------

    def _wants_images(self, ev: ChronikEvent) -> bool:
        return (
            ev.category == CAT_AI
            and not ev.data.get("images")
            and bool(parse_dirs(self.options.get(CONF_AI_IMAGE_DIRS)))
        )

    async def _async_find_images(self, ev: ChronikEvent) -> list[str]:
        dirs = parse_dirs(self.options.get(CONF_AI_IMAGE_DIRS))
        window = timedelta(minutes=float(self.options.get(CONF_AI_IMAGE_WINDOW) or 3))
        return await self.hass.async_add_executor_job(find_images, dirs, ev.start, window)

    async def _async_attach_images(self, uid: str, notify: bool = True) -> bool:
        """Link snapshots saved shortly before an AI finding to the entry."""
        ev = self.store.get(uid)
        if ev is None or not self._wants_images(ev):
            return False
        images = await self._async_find_images(ev)
        if not images:
            return False
        ev = ev.copy()
        ev.data["images"] = images
        self.store.upsert(ev)
        if notify:
            self._notify()
        return True

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_updated(self.entry.entry_id))

    # Public API ---------------------------------------------------------------

    def events_between(
        self, start: datetime, end: datetime, categories: list[str] | None = None
    ) -> list[ChronikEvent]:
        """Return entries overlapping a time range."""
        return self.store.between(start, end, categories)

    @callback
    def add_entry(
        self,
        category: str,
        title: str,
        start: datetime,
        end: datetime | None = None,
        description: str = "",
        data: dict[str, Any] | None = None,
        origin: str = ORIGIN_MANUAL,
    ) -> ChronikEvent:
        """Add an entry (service call or calendar UI)."""
        start = dt_util.as_utc(start)
        end = dt_util.as_utc(end) if end else start
        if end < start:
            raise HomeAssistantError("end must not be before start")
        ev = ChronikEvent(
            uid=f"{origin}:{uuid.uuid4().hex}",
            category=category,
            start=start,
            end=end,
            title=title,
            description=description,
            data={"kind": origin, **(data or {})},
            origin=origin,
        )
        self.store.upsert(ev)
        self._notify()
        return ev

    @callback
    def update_entry(self, uid: str, **changes: Any) -> None:
        """Change title, description, start or end of an entry."""
        if (ev := self.store.get(uid)) is None:
            raise HomeAssistantError(f"Unknown Chronik entry {uid}")
        ev = ev.copy()
        for key in ("title", "description"):
            if changes.get(key) is not None:
                setattr(ev, key, changes[key])
        for key in ("start", "end"):
            if changes.get(key) is not None:
                setattr(ev, key, dt_util.as_utc(changes[key]))
        ev.origin = ORIGIN_MANUAL
        self.store.upsert(ev)
        self._notify()

    @callback
    def delete_entry(self, uid: str) -> bool:
        """Delete an entry."""
        removed = self.store.delete(uid)
        if removed:
            self._notify()
        return removed

    async def async_backfill(self, days: int, categories: list[str] | None = None) -> int:
        """Rebuild entries of the last days from the recorder history."""
        if "recorder" not in self.hass.config.components:
            raise HomeAssistantError("The recorder integration is not loaded")
        # Imported lazily: the recorder is only needed for backfill.
        from homeassistant.components.recorder import get_instance, history  # noqa: PLC0415

        detectors = [
            det
            for det in build_detectors(self.options, self.lang)
            if categories is None or det.category in categories
        ]
        index = self._index(detectors)
        if not index:
            return 0
        end = dt_util.utcnow()
        start = end - timedelta(days=days)
        states: dict[str, list[State]] = await get_instance(self.hass).async_add_executor_job(
            partial(
                history.get_significant_states,
                self.hass,
                start,
                end,
                list(index),
                None,
                True,  # include_start_time_state
                False,  # significant_changes_only
                False,  # minimal_response
                False,  # no_attributes
            )
        )
        timeline = sorted(
            (
                (state.last_changed, entity_id, state)
                for entity_id, entity_states in states.items()
                for state in entity_states
                if isinstance(state, State)
            ),
            key=lambda item: (item[0], item[1]),
        )
        before = {ev.uid for ev in self.store.all()}
        for _when, entity_id, state in timeline:
            snap = self._snapshot(state, self.hass.states.get(entity_id))
            for det in index[entity_id]:
                self._apply(det.feed(snap), ORIGIN_BACKFILL)
        added = len({ev.uid for ev in self.store.all()} - before)
        # Link images to all AI findings of the period that have none yet.
        for ev in self.store.between(start, end, [CAT_AI]):
            await self._async_attach_images(ev.uid, notify=False)
        _LOGGER.debug("Backfill of %s days added %s entries", days, added)
        self._notify()
        return added
