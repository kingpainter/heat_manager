"""Tests for engine/readings.py — plausibility of raw room temperatures."""

from __future__ import annotations

from custom_components.heat_manager.engine.readings import (
    ROOM_TEMP_SANITY_MAX,
    ROOM_TEMP_SANITY_MIN,
    sanity_clamp_temp,
)


def test_plausible_reading_passes_unchanged():
    assert sanity_clamp_temp(21.5) == 21.5


def test_range_limits_are_inclusive():
    assert sanity_clamp_temp(ROOM_TEMP_SANITY_MIN) == ROOM_TEMP_SANITY_MIN
    assert sanity_clamp_temp(ROOM_TEMP_SANITY_MAX) == ROOM_TEMP_SANITY_MAX


def test_glitch_readings_are_rejected():
    assert sanity_clamp_temp(-200.0) is None
    assert sanity_clamp_temp(3000.0) is None


# ── seconds_since_report (v0.69.1) ───────────────────────────────────────────

from datetime import UTC, datetime, timedelta  # noqa: E402

from custom_components.heat_manager.engine.readings import (  # noqa: E402
    seconds_since_report,
)

_NOW = datetime(2026, 11, 13, 19, 24, tzinfo=UTC)


def test_newest_of_updated_and_reported_wins():
    updated = _NOW - timedelta(minutes=19)
    reported = _NOW - timedelta(minutes=2)
    assert seconds_since_report(_NOW, updated, reported) == 120.0


def test_only_last_updated_is_used_when_reported_missing():
    assert seconds_since_report(_NOW, _NOW - timedelta(minutes=5)) == 300.0


def test_naive_timestamp_is_taken_as_utc():
    naive = (_NOW - timedelta(minutes=1)).replace(tzinfo=None)
    assert seconds_since_report(_NOW, naive) == 60.0


def test_non_datetime_inputs_are_ignored():
    assert seconds_since_report(_NOW, None, object()) is None
    assert seconds_since_report(_NOW, _NOW - timedelta(seconds=30), "x") == 30.0
