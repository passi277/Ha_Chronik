"""Detectors turning entity states into Chronik entries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import (
    CONF_AI_ENTITIES,
    CONF_ALARM_ENTITIES,
    CONF_ALARM_LOG_ARMING,
    CONF_IRRIGATION_ENTITIES,
    CONF_IRRIGATION_METER,
    CONF_IRRIGATION_MIN,
    CONF_MOWING_ENTITIES,
    CONF_MOWING_MERGE,
    CONF_MOWING_MIN,
    CONF_POOL_COUNTERS,
    CONF_POOL_ENTITIES,
    CONF_POOL_THRESHOLD,
    CONF_RAIN_GAP,
    CONF_RAIN_SENSOR,
    DEFAULTS,
)
from .ai import AiDetector
from .alarm import AlarmDetector
from .base import Action, Delete, Detector, Snapshot, Upsert
from .irrigation import IrrigationDetector
from .mowing import MowingDetector
from .pool import PoolDetector
from .rain import RainDetector

__all__ = ["Action", "Delete", "Detector", "Snapshot", "Upsert", "build_detectors"]


def build_detectors(options: Mapping[str, Any], lang: str | None) -> list[Detector]:
    """Create the detectors configured in the options."""

    def opt(key: str) -> Any:
        return options.get(key, DEFAULTS.get(key))

    detectors: list[Detector] = []
    if opt(CONF_RAIN_SENSOR):
        detectors.append(RainDetector(lang, opt(CONF_RAIN_SENSOR), gap_minutes=opt(CONF_RAIN_GAP)))
    if opt(CONF_IRRIGATION_ENTITIES):
        detectors.append(
            IrrigationDetector(
                lang,
                opt(CONF_IRRIGATION_ENTITIES),
                opt(CONF_IRRIGATION_METER) or None,
                min_minutes=opt(CONF_IRRIGATION_MIN),
            )
        )
    if opt(CONF_MOWING_ENTITIES):
        detectors.append(
            MowingDetector(
                lang,
                opt(CONF_MOWING_ENTITIES),
                merge_minutes=opt(CONF_MOWING_MERGE),
                min_minutes=opt(CONF_MOWING_MIN),
            )
        )
    if opt(CONF_POOL_ENTITIES) or opt(CONF_POOL_COUNTERS):
        detectors.append(
            PoolDetector(
                lang,
                opt(CONF_POOL_ENTITIES) or [],
                opt(CONF_POOL_COUNTERS) or [],
                threshold=float(opt(CONF_POOL_THRESHOLD)),
            )
        )
    if opt(CONF_ALARM_ENTITIES):
        detectors.append(
            AlarmDetector(lang, opt(CONF_ALARM_ENTITIES), log_arming=bool(opt(CONF_ALARM_LOG_ARMING)))
        )
    if opt(CONF_AI_ENTITIES):
        detectors.append(AiDetector(lang, opt(CONF_AI_ENTITIES)))
    return detectors
