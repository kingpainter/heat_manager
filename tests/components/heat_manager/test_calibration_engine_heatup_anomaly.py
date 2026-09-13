"""Tests for CalibrationEngine's heat-up-rate anomaly detection
(2026-09-13, architecture review #3 — a cheap, room-relative "possible
stuck valve" signal built entirely from data the engine already learns).

A room's heat-up rate is only compared against ITS OWN learned baseline
(never a fixed global threshold — "normal" varies hugely by room), only
once that baseline is backed by enough prior samples
(_HEATUP_ANOMALY_MIN_SAMPLES), and only flagged after several consecutive
underperforming samples in a row (_HEATUP_ANOMALY_STREAK_THRESHOLD) rather
than a single noisy tick. get_room_heatup_anomaly() is what
websocket.py's _build_active_issues() reads to surface this in the panel's
status center.

All tests run completely offline — HA core is mocked with MagicMock;
`_async_update_heatup_learning` is driven directly, tick by tick, with a
patched `utcnow()` advancing a fixed 600s (10 min) per call — inside the
engine's [_HEATUP_MIN_SAMPLE_SEC, _HEATUP_MAX_SAMPLE_SEC] sampling window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from custom_components.heat_manager.const import RoomState
from custom_components.heat_manager.engine.calibration_engine import (
    _HEATUP_ANOMALY_STREAK_THRESHOLD,
    CalibrationEngine,
)

_START = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
_STEP = timedelta(seconds=600)  # 10 min — within the engine's sampling window


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.is_room_door_open = MagicMock(return_value=False)
    return coord


def _run_ticks(engine, coord, temps, room_name="Bathroom", climate_entity="climate.bathroom"):
    """Feed one temperature reading per tick, 10 minutes apart, through
    _async_update_heatup_learning(). temps[0] only sets the initial
    baseline (no sample produced from it)."""
    now = _START
    for temp in temps:
        coord.get_room_current_temp = MagicMock(return_value=temp)
        with patch(
            "custom_components.heat_manager.engine.calibration_engine.utcnow",
            return_value=now,
        ):
            engine._async_update_heatup_learning(room_name, climate_entity)
        now += _STEP


def test_anomaly_false_before_baseline_is_established():
    """Only 3 samples in (well under _HEATUP_ANOMALY_MIN_SAMPLES=5) — even
    a badly underperforming run must not be flagged yet; the baseline
    itself isn't trusted."""
    coord = _make_coordinator()
    engine = CalibrationEngine(coord)

    # 20.0 (baseline) -> three very slow +0.1 samples in a row.
    _run_ticks(engine, coord, [20.0, 20.1, 20.2, 20.3])

    assert engine.get_room_heatup_anomaly("Bathroom") is False


def test_anomaly_flagged_after_streak_of_underperforming_samples():
    coord = _make_coordinator()
    engine = CalibrationEngine(coord)

    # Establish a healthy ~1.8°C/h baseline over 6 good samples (+0.3 every
    # 10 min), then 3 samples in a row at ~0.6°C/h (well under 40% of 1.8).
    good = [20.0, 20.3, 20.6, 20.9, 21.2, 21.5, 21.8]
    bad = [21.9, 22.0, 22.1]
    _run_ticks(engine, coord, good)
    assert engine.get_room_heatup_anomaly("Bathroom") is False  # not yet

    # Continue the same baseline chain — feed the bad samples as a
    # continuation (not a fresh _run_ticks call, so the baseline carries on
    # from good[-1] at the right elapsed offset).
    now = _START + len(good) * _STEP
    for temp in bad:
        coord.get_room_current_temp = MagicMock(return_value=temp)
        with patch(
            "custom_components.heat_manager.engine.calibration_engine.utcnow",
            return_value=now,
        ):
            engine._async_update_heatup_learning("Bathroom", "climate.bathroom")
        now += _STEP

    assert engine.get_room_heatup_anomaly("Bathroom") is True


def test_anomaly_clears_on_a_good_sample():
    coord = _make_coordinator()
    engine = CalibrationEngine(coord)

    good = [20.0, 20.3, 20.6, 20.9, 21.2, 21.5, 21.8]
    _run_ticks(engine, coord, good)

    now = _START + len(good) * _STEP
    for temp in (21.9, 22.0, 22.1):  # 3 bad samples -> flagged
        coord.get_room_current_temp = MagicMock(return_value=temp)
        with patch(
            "custom_components.heat_manager.engine.calibration_engine.utcnow",
            return_value=now,
        ):
            engine._async_update_heatup_learning("Bathroom", "climate.bathroom")
        now += _STEP
    assert engine.get_room_heatup_anomaly("Bathroom") is True

    # One good-rate sample (+0.3, matching the original baseline) clears it.
    coord.get_room_current_temp = MagicMock(return_value=22.4)
    with patch(
        "custom_components.heat_manager.engine.calibration_engine.utcnow",
        return_value=now,
    ):
        engine._async_update_heatup_learning("Bathroom", "climate.bathroom")

    assert engine.get_room_heatup_anomaly("Bathroom") is False


def test_anomaly_streak_resets_when_room_stops_actively_heating():
    coord = _make_coordinator()
    engine = CalibrationEngine(coord)

    good = [20.0, 20.3, 20.6, 20.9, 21.2, 21.5, 21.8]
    _run_ticks(engine, coord, good)

    now = _START + len(good) * _STEP
    for temp in (21.9, 22.0):  # 2 bad samples — one short of the threshold
        coord.get_room_current_temp = MagicMock(return_value=temp)
        with patch(
            "custom_components.heat_manager.engine.calibration_engine.utcnow",
            return_value=now,
        ):
            engine._async_update_heatup_learning("Bathroom", "climate.bathroom")
        now += _STEP
    assert engine.get_room_heatup_anomaly("Bathroom") is False

    # Room leaves NORMAL (e.g. window opens) — streak must reset even
    # without a new temperature sample being meaningfully comparable.
    coord.get_room_state = MagicMock(return_value=RoomState.WINDOW_OPEN)
    coord.get_room_current_temp = MagicMock(return_value=22.05)
    with patch(
        "custom_components.heat_manager.engine.calibration_engine.utcnow",
        return_value=now,
    ):
        engine._async_update_heatup_learning("Bathroom", "climate.bathroom")

    assert engine._heatup_anomaly_streak.get("Bathroom", 0) == 0


def test_anomaly_threshold_constant_is_at_least_two():
    """Sanity check on the tuning constant itself — a threshold of 1 would
    mean a single noisy sample could flag a room, defeating the point of
    requiring a streak at all."""
    assert _HEATUP_ANOMALY_STREAK_THRESHOLD >= 2
