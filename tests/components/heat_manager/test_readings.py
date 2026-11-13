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
