"""Tests of the pure detector state machines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.chronik.detectors import Delete, Snapshot, Upsert
from custom_components.chronik.detectors.ai import AiDetector
from custom_components.chronik.detectors.alarm import AlarmDetector
from custom_components.chronik.detectors.irrigation import IrrigationDetector
from custom_components.chronik.detectors.mowing import MowingDetector
from custom_components.chronik.detectors.pool import PoolDetector
from custom_components.chronik.detectors.rain import RainDetector

T0 = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def snap(entity_id: str, state: str, minutes: float, name: str = "X", **kw) -> Snapshot:
    return Snapshot(entity_id=entity_id, state=state, when=at(minutes), name=name, **kw)


def upserts(actions):
    return [a.event for a in actions if isinstance(a, Upsert)]


def test_irrigation_run_with_volume() -> None:
    det = IrrigationDetector("de", ["binary_sensor.haus"], "sensor.meter", min_minutes=1)
    assert det.feed(snap("sensor.meter", "1000", -5)) == []
    assert det.feed(snap("binary_sensor.haus", "off", -1, device_name="Haus")) == []
    started = upserts(det.feed(snap("binary_sensor.haus", "on", 0, device_name="Haus")))
    assert started[0].is_open
    assert started[0].title == "💧 Haus · läuft"
    det.feed(snap("sensor.meter", "1040.5", 10))
    ended = upserts(det.feed(snap("binary_sensor.haus", "off", 18, device_name="Haus")))
    ev = ended[-1]
    assert ev.end == at(18)
    assert ev.data["liters"] == 40.5
    assert ev.title == "💧 Haus · 18 min · 40 L" or ev.title == "💧 Haus · 18 min · 41 L"
    assert ev.uid == started[0].uid


def test_irrigation_too_short_is_deleted_and_unavailable_ignored() -> None:
    det = IrrigationDetector("en", ["switch.zone"], min_minutes=1)
    started = upserts(det.feed(snap("switch.zone", "on", 0)))
    assert det.feed(snap("switch.zone", "unavailable", 0.2)) == []
    actions = det.feed(snap("switch.zone", "off", 0.5))
    assert actions == [Delete(started[0].uid)]


def test_irrigation_restore_continues_and_closes() -> None:
    det = IrrigationDetector("de", ["binary_sensor.haus"])
    ev = upserts(det.feed(snap("binary_sensor.haus", "on", 0)))[0]
    # Restart: new detector restored from storage.
    det2 = IrrigationDetector("de", ["binary_sensor.haus"])
    det2.restore([ev])
    assert det2.feed(snap("binary_sensor.haus", "on", 5)) == []
    closed = upserts(det2.feed(snap("binary_sensor.haus", "off", 12)))[0]
    assert closed.uid == ev.uid and closed.end == at(12)
    assert closed.data["active_s"] == 12 * 60


def test_mowing_merges_short_pauses_and_logs_errors() -> None:
    det = MowingDetector("de", ["lawn_mower.leopard"], merge_minutes=20)
    det.feed(snap("lawn_mower.leopard", "docked", -10))
    first = upserts(det.feed(snap("lawn_mower.leopard", "mowing", 0)))[0]
    det.feed(snap("lawn_mower.leopard", "docked", 40))
    resumed = upserts(det.feed(snap("lawn_mower.leopard", "mowing", 55)))[0]
    assert resumed.uid == first.uid and resumed.is_open
    ended = upserts(det.feed(snap("lawn_mower.leopard", "returning", 95)))[0]
    assert ended.data["active_s"] == 80 * 60
    assert ended.title == "🌱 Mähen · 1 h 20 min"
    det.feed(snap("lawn_mower.leopard", "docked", 100))
    # New session after a long break.
    second = upserts(det.feed(snap("lawn_mower.leopard", "mowing", 300)))[0]
    assert second.uid != first.uid
    error = upserts(det.feed(snap("lawn_mower.leopard", "error", 310, name="Leopard 2")))
    assert any(e.data["kind"] == "error" for e in error)


def test_rain_episodes() -> None:
    det = RainDetector("de", "sensor.rain", gap_minutes=60)
    attrs = {"unit_of_measurement": "mm"}
    assert det.feed(snap("sensor.rain", "0.0", 0, attributes=attrs)) == []
    ev = upserts(det.feed(snap("sensor.rain", "1.2", 120, attributes=attrs)))[0]
    assert ev.start == at(105)  # RAIN_LEAD before first increase
    ev = upserts(det.feed(snap("sensor.rain", "4.2", 150, attributes=attrs)))[0]
    assert ev.data["mm"] == 4.2 and ev.end == at(150)
    assert ev.title == "🌧️ Regen · 4,2 mm"
    # Gap of more than 60 minutes: new episode.
    ev2 = upserts(det.feed(snap("sensor.rain", "5.0", 300, attributes=attrs)))[0]
    assert ev2.uid != ev.uid and ev2.data["mm"] == 0.8
    # Daily reset to 0 is not rain, reset with new rain counts the new value.
    assert det.feed(snap("sensor.rain", "0.0", 1000, attributes=attrs)) == []
    assert det.feed(snap("sensor.rain", "unavailable", 1001)) == []
    ev3 = upserts(det.feed(snap("sensor.rain", "0.3", 1010, attributes=attrs)))[0]
    assert ev3.data["mm"] == 0.3


def test_pool_counter_reset_attaches_to_run() -> None:
    det = PoolDetector("de", ["timer.backwash"], ["sensor.hours"], threshold=1)
    attrs = {"unit_of_measurement": "h"}
    det.feed(snap("sensor.hours", "41.5", -60, attributes=attrs))
    run = upserts(det.feed(snap("timer.backwash", "active", 0, name="Pool Rückspülen")))[0]
    det.feed(snap("timer.backwash", "idle", 3))
    updated = upserts(det.feed(snap("sensor.hours", "0", 4, name="Pumpenstunden", attributes=attrs)))
    assert updated[0].uid == run.uid
    assert updated[0].title == "🏊 Pool Rückspülen · 3 min · nach 41,5 h"


def test_pool_counter_reset_without_run_then_run_merges() -> None:
    det = PoolDetector("de", ["timer.backwash"], ["sensor.hours"], threshold=1)
    det.feed(snap("sensor.hours", "30", -60))
    point = upserts(det.feed(snap("sensor.hours", "0.1", 0, name="Pumpenstunden")))[0]
    assert point.data["kind"] == "reset" and point.start == point.end
    actions = det.feed(snap("timer.backwash", "active", 5, name="Pool Rückspülen"))
    assert Delete(point.uid) in actions
    assert upserts(actions)[0].data["counter_before"] == 30


def test_alarm_triggered_and_arming() -> None:
    det = AlarmDetector("de", ["alarm_control_panel.garten", "siren.haus"], log_arming=True)
    assert det.feed(snap("alarm_control_panel.garten", "disarmed", 0, name="Garten")) == []
    arming = upserts(det.feed(snap("alarm_control_panel.garten", "armed_away", 1, name="Garten")))
    assert arming[0].title == "🔒 Garten: scharf (abwesend)"
    trig = upserts(det.feed(snap("alarm_control_panel.garten", "triggered", 10, name="Garten")))
    assert trig[0].title == "🚨 Garten ausgelöst · läuft"
    done = upserts(det.feed(snap("alarm_control_panel.garten", "armed_away", 12, name="Garten")))
    assert done[0].title == "🚨 Garten ausgelöst · 2 min"
    siren = upserts(det.feed(snap("siren.haus", "on", 10, name="Sirene")))
    assert siren[0].title == "🚨 Sirene · läuft"


def test_ai_findings_baseline_and_changes() -> None:
    det = AiDetector("de", ["input_text.pool_ki"])
    assert det.feed(snap("input_text.pool_ki", "Wasser trüb", 0, name="Pool KI-Befund")) == []
    ev = upserts(det.feed(snap("input_text.pool_ki", "Wasser klar · sauber", 60, name="Pool KI-Befund")))[0]
    assert ev.title == "🤖 Pool KI-Befund: Wasser klar · sauber"
    assert ev.start == ev.end == at(60)
    assert det.feed(snap("input_text.pool_ki", "Wasser klar · sauber", 61)) == []
    # After restart the restored text is not logged again.
    det2 = AiDetector("de", ["input_text.pool_ki"])
    det2.restore([ev])
    assert det2.feed(snap("input_text.pool_ki", "Wasser klar · sauber", 500)) == []
    assert upserts(det2.feed(snap("input_text.pool_ki", "Algen sichtbar", 600)))
