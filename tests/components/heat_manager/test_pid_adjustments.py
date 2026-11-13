"""Tests for engine/pid_adjustments.py — solar gain and door heat sharing.

Weather compensation has its own file (test_weather_compensation_feedforward.py).
All three are pure functions of (config, readings): no coordinator or hass.
"""

from __future__ import annotations

from custom_components.heat_manager.const import (
    CONF_DOOR_HEAT_SHARE_ENABLED,
    CONF_DOOR_HEAT_SHARE_MAX_REDUCTION,
    CONF_SOLAR_GAIN_ENABLED,
    CONF_SOLAR_GAIN_LUX_THRESHOLD,
    CONF_SOLAR_GAIN_MAX_REDUCTION,
    CONF_SOLAR_GAIN_WEIGHT,
    DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    DOOR_HEAT_SHARE_MIN_TEMP_DIFF,
    DOOR_HEAT_SHARE_WEIGHT,
)
from custom_components.heat_manager.engine.pid_adjustments import (
    door_heat_share_reduction,
    solar_gain_reduction,
)

_SOLAR_ON = {
    CONF_SOLAR_GAIN_ENABLED: True,
    CONF_SOLAR_GAIN_LUX_THRESHOLD: 1000,
    CONF_SOLAR_GAIN_WEIGHT: 0.1,
    CONF_SOLAR_GAIN_MAX_REDUCTION: 0.3,
}


def test_solar_no_effect_without_reading_or_at_night():
    assert solar_gain_reduction(_SOLAR_ON, None, 30.0) == 0.0
    assert solar_gain_reduction(_SOLAR_ON, 5000.0, None) == 0.0
    assert solar_gain_reduction(_SOLAR_ON, 5000.0, 0.0) == 0.0


def test_solar_disabled_has_no_effect():
    cfg = {**_SOLAR_ON, CONF_SOLAR_GAIN_ENABLED: False}
    assert solar_gain_reduction(cfg, 5000.0, 30.0) == 0.0


def test_solar_below_threshold_has_no_effect():
    assert solar_gain_reduction(_SOLAR_ON, 1000.0, 30.0) == 0.0


def test_solar_scales_with_excess_and_is_capped():
    # (2000 - 1000) / 1000 * 0.1 = 0.1
    assert abs(solar_gain_reduction(_SOLAR_ON, 2000.0, 30.0) - 0.1) < 1e-9
    # (11000 - 1000) / 1000 * 0.1 = 1.0 -> capped at 0.3
    assert solar_gain_reduction(_SOLAR_ON, 11000.0, 30.0) == 0.3


def test_door_needs_both_inputs():
    cfg = {CONF_DOOR_HEAT_SHARE_ENABLED: True}
    assert door_heat_share_reduction(cfg, None, 3.0) == 0.0
    assert door_heat_share_reduction(cfg, 0.8, None) == 0.0


def test_door_disabled_has_no_effect():
    cfg = {CONF_DOOR_HEAT_SHARE_ENABLED: False}
    assert door_heat_share_reduction(cfg, 1.0, 5.0) == 0.0


def test_door_requires_active_neighbour_and_real_gradient():
    cfg = {CONF_DOOR_HEAT_SHARE_ENABLED: True}
    weak = DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER - 0.01
    assert door_heat_share_reduction(cfg, weak, 5.0) == 0.0
    small = DOOR_HEAT_SHARE_MIN_TEMP_DIFF - 0.01
    assert door_heat_share_reduction(cfg, 1.0, small) == 0.0


def test_door_reduction_scales_with_gap_and_is_capped():
    cfg = {CONF_DOOR_HEAT_SHARE_ENABLED: True, CONF_DOOR_HEAT_SHARE_MAX_REDUCTION: 0.5}
    gap = DOOR_HEAT_SHARE_MIN_TEMP_DIFF + 0.5
    expected = min(0.5, gap * DOOR_HEAT_SHARE_WEIGHT)
    assert abs(door_heat_share_reduction(cfg, 1.0, gap) - expected) < 1e-9
    assert door_heat_share_reduction(cfg, 1.0, 1000.0) == 0.5
