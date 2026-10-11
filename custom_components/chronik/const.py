"""Constants for the Chronik integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "chronik"

CAT_RAIN = "rain"
CAT_IRRIGATION = "irrigation"
CAT_MOWING = "mowing"
CAT_POOL = "pool"
CAT_ALARM = "alarm"
CAT_AI = "ai"
CAT_SUMMARY = "summary"

CATEGORIES = [CAT_RAIN, CAT_IRRIGATION, CAT_MOWING, CAT_POOL, CAT_ALARM, CAT_AI]

CATEGORY_EMOJI = {
    CAT_RAIN: "🌧️",
    CAT_IRRIGATION: "💧",
    CAT_MOWING: "🌱",
    CAT_POOL: "🏊",
    CAT_ALARM: "🚨",
    CAT_AI: "🤖",
    CAT_SUMMARY: "📅",
}

ORIGIN_LIVE = "live"
ORIGIN_BACKFILL = "backfill"
ORIGIN_MANUAL = "manual"
ORIGIN_SERVICE = "service"

# Options
CONF_RAIN_SENSOR = "rain_sensor"
CONF_RAIN_GAP = "rain_gap_minutes"
CONF_IRRIGATION_ENTITIES = "irrigation_entities"
CONF_IRRIGATION_METER = "irrigation_meter"
CONF_IRRIGATION_MIN = "irrigation_min_minutes"
CONF_MOWING_ENTITIES = "mowing_entities"
CONF_MOWING_MERGE = "mowing_merge_minutes"
CONF_MOWING_MIN = "mowing_min_minutes"
CONF_POOL_ENTITIES = "pool_entities"
CONF_POOL_COUNTERS = "pool_counters"
CONF_POOL_THRESHOLD = "pool_reset_threshold"
CONF_ALARM_ENTITIES = "alarm_entities"
CONF_ALARM_LOG_ARMING = "alarm_log_arming"
CONF_AI_ENTITIES = "ai_entities"
CONF_RETENTION_DAYS = "retention_days"

DEFAULTS: dict[str, object] = {
    CONF_RAIN_GAP: 60,
    CONF_IRRIGATION_MIN: 1,
    CONF_MOWING_MERGE: 20,
    CONF_MOWING_MIN: 1,
    CONF_POOL_THRESHOLD: 1.0,
    CONF_ALARM_LOG_ARMING: False,
    CONF_RETENTION_DAYS: 1095,
}

# Which option keys hold the source entities of each category.
CATEGORY_SOURCES = {
    CAT_RAIN: [CONF_RAIN_SENSOR],
    CAT_IRRIGATION: [CONF_IRRIGATION_ENTITIES],
    CAT_MOWING: [CONF_MOWING_ENTITIES],
    CAT_POOL: [CONF_POOL_ENTITIES, CONF_POOL_COUNTERS],
    CAT_ALARM: [CONF_ALARM_ENTITIES],
    CAT_AI: [CONF_AI_ENTITIES],
}

INVALID_STATES = {"unknown", "unavailable", "none", ""}
ACTIVE_STATES = {"on", "open", "opening", "active", "paused"}

# How long a point event (start == end) is shown in the calendar.
POINT_DISPLAY = timedelta(minutes=5)
# A counter reset this close to a pool run is attached to that run.
POOL_ATTACH_WINDOW = timedelta(minutes=60)
# Rain episodes are assumed to begin at most this long before the first increase.
RAIN_LEAD = timedelta(minutes=15)
# Live detectors restore their state from events of this period.
RESTORE_WINDOW = timedelta(days=3)

STORAGE_VERSION = 1


def signal_updated(entry_id: str) -> str:
    """Dispatcher signal sent when the events of an entry changed."""
    return f"{DOMAIN}_updated_{entry_id}"
