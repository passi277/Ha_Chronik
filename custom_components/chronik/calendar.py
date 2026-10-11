"""Calendar entities of the Chronik."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    DOMAIN as CALENDAR_DOMAIN,
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ChronikConfigEntry
from .const import CAT_SUMMARY, DOMAIN, ORIGIN_MANUAL, signal_updated
from .coordinator import ChronikCoordinator
from .models import ChronikEvent
from .store import effective_end
from .summary import build_summary


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChronikConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one calendar per category plus the daily summary."""
    coordinator = entry.runtime_data
    entities: list[CalendarEntity] = [
        ChronikCategoryCalendar(coordinator, category) for category in coordinator.enabled_categories
    ]
    entities.append(ChronikSummaryCalendar(coordinator))

    # Remove calendars of categories that are no longer configured.
    wanted = {entity.unique_id for entity in entities}
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == CALENDAR_DOMAIN and reg_entry.unique_id not in wanted:
            registry.async_remove(reg_entry.entity_id)

    async_add_entities(entities)


def _to_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.start_of_local_day(value)


class ChronikCalendarBase(CalendarEntity):
    """Common parts of all Chronik calendars."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: ChronikCoordinator, key: str) -> None:
        self.coordinator = coordinator
        entry = coordinator.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Refresh when entries change."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_updated(self.coordinator.entry.entry_id), self._updated
            )
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()


class ChronikCategoryCalendar(ChronikCalendarBase):
    """All entries of one category."""

    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, coordinator: ChronikCoordinator, category: str) -> None:
        super().__init__(coordinator, category)
        self.category = category

    def _calendar_event(self, ev: ChronikEvent) -> CalendarEvent:
        now = dt_util.utcnow()
        return CalendarEvent(
            start=dt_util.as_local(ev.start),
            end=dt_util.as_local(effective_end(ev, now)),
            summary=ev.title,
            description=ev.description or None,
            uid=ev.uid,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the entry currently in progress, if any."""
        now = dt_util.utcnow()
        current = self.coordinator.events_between(now, now + timedelta(seconds=1), [self.category])
        current = [ev for ev in current if ev.start <= now]
        return self._calendar_event(current[-1]) if current else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return entries in a time range."""
        return [
            self._calendar_event(ev)
            for ev in self.coordinator.events_between(
                dt_util.as_utc(start_date), dt_util.as_utc(end_date), [self.category]
            )
        ]

    async def async_create_event(self, **kwargs: Any) -> None:
        """Add a manual note from the calendar UI."""
        self.coordinator.add_entry(
            category=self.category,
            title=kwargs["summary"],
            description=kwargs.get("description") or "",
            start=_to_datetime(kwargs["dtstart"]),
            end=_to_datetime(kwargs["dtend"]),
            origin=ORIGIN_MANUAL,
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an entry."""
        self.coordinator.delete_entry(uid)

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Edit an entry."""
        self.coordinator.update_entry(
            uid,
            title=event.get("summary"),
            description=event.get("description"),
            start=_to_datetime(event["dtstart"]) if event.get("dtstart") else None,
            end=_to_datetime(event["dtend"]) if event.get("dtend") else None,
        )


class ChronikSummaryCalendar(ChronikCalendarBase):
    """One all-day entry per day summarising everything."""

    def __init__(self, coordinator: ChronikCoordinator) -> None:
        super().__init__(coordinator, CAT_SUMMARY)

    def _summaries(self, first: date, last: date) -> list[CalendarEvent]:
        start = dt_util.as_utc(dt_util.start_of_local_day(first))
        end = dt_util.as_utc(dt_util.start_of_local_day(last + timedelta(days=1)))
        by_day: dict[date, list[ChronikEvent]] = {}
        for ev in self.coordinator.events_between(start, end):
            if start <= ev.start < end:
                by_day.setdefault(dt_util.as_local(ev.start).date(), []).append(ev)
        result = []
        for day, events in sorted(by_day.items()):
            summary = build_summary(events, self.coordinator.lang, dt_util.as_local)
            if summary is None:
                continue
            title, description = summary
            result.append(
                CalendarEvent(
                    start=day,
                    end=day + timedelta(days=1),
                    summary=title,
                    description=description,
                    uid=f"summary:{day.isoformat()}",
                )
            )
        return result

    @property
    def event(self) -> CalendarEvent | None:
        """Return today's summary."""
        today = dt_util.now().date()
        summaries = self._summaries(today, today)
        return summaries[0] if summaries else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return one summary per day in the range."""
        return self._summaries(
            dt_util.as_local(start_date).date(),
            dt_util.as_local(end_date - timedelta(microseconds=1)).date(),
        )
