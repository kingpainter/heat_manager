"""Tests for engine/mold.py — the one shared mold-risk algorithm."""

from __future__ import annotations

from custom_components.heat_manager.engine.mold import (
    MOLD_RH_THRESHOLD,
    dewpoint,
    is_mold_risk,
)


def test_dewpoint_magnus_known_values():
    # 20 °C / 50 % RH -> ~9.3 °C; 100 % RH -> dewpoint equals air temperature.
    assert abs(dewpoint(20.0, 50.0) - 9.26) < 0.05
    assert abs(dewpoint(15.0, 100.0) - 15.0) < 1e-6


def test_below_rh_threshold_is_never_risk():
    assert is_mold_risk(5.0, MOLD_RH_THRESHOLD - 0.1) is False


def test_cold_humid_room_is_risk():
    # 95 % / 10 °C -> dewpoint ~9.24 °C -> 10.0 <= 10.24 -> risk.
    assert is_mold_risk(10.0, 95.0) is True


def test_warm_room_at_threshold_is_not_risk():
    # 70 % / 21 °C -> dewpoint ~15.3 °C -> 21 > 16.3 -> no risk.
    assert is_mold_risk(21.0, 70.0) is False
