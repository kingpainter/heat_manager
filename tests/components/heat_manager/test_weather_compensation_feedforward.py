"""Tests for the outdoor-temperature PID feedforward (weather compensation
curve, 2026-09-13, architecture review #5) — coordinator.py's module-level
pure helper `_weather_compensation_feedforward(config, outdoor_temp)`.

This existed already as a hardcoded, always-on constant (FF_REFERENCE_OUTDOOR_TEMP
= 15.0, FF_WEIGHT = 0.02, FF_MAX_CONTRIBUTION = 0.3) — "Conservative defaults,
not yet exposed in the UI". It's now configurable via
CONF_WEATHER_COMPENSATION_ENABLED/CONF_FF_*, with those exact values as
fallback defaults. The critical regression-safety property these tests
protect: an install with no config for these fields (the common case, right
after upgrading) must compute IDENTICAL feedforward to the old hardcoded
formula — "exposing" a setting must never silently change existing heating
behaviour.

Pure function of (config: dict, outdoor_temp: float | None) — no
coordinator/hass mocking needed at all.
"""

from __future__ import annotations

from custom_components.heat_manager.coordinator import (
    _weather_compensation_feedforward,
)


# ── default (no config) == old hardcoded behaviour ──────────────────────────


def test_empty_config_matches_old_hardcoded_formula_at_0c():
    # Old formula: min(0.3, max(0.0, (15.0 - outdoor) * 0.02)) — at 0°C
    # outdoor that's min(0.3, 0.3) == 0.3 exactly (the cap and the raw
    # value coincide at this particular outdoor temperature).
    assert _weather_compensation_feedforward({}, 0.0) == 0.3


def test_empty_config_matches_old_hardcoded_formula_below_cap():
    # (15 - 5) * 0.02 = 0.2, under the 0.3 cap.
    result = _weather_compensation_feedforward({}, 5.0)
    assert abs(result - 0.2) < 1e-9


def test_empty_config_is_capped_at_old_max_contribution():
    # Very cold outdoor temp would exceed 0.3 uncapped — must clamp to it,
    # exactly as the old hardcoded FF_MAX_CONTRIBUTION did.
    result = _weather_compensation_feedforward({}, -20.0)
    assert result == 0.3


def test_empty_config_is_zero_at_or_above_reference_temp():
    assert _weather_compensation_feedforward({}, 15.0) == 0.0
    assert _weather_compensation_feedforward({}, 20.0) == 0.0


def test_none_outdoor_temp_is_zero_regardless_of_config():
    assert _weather_compensation_feedforward({}, None) == 0.0
    assert (
        _weather_compensation_feedforward(
            {"weather_compensation_enabled": True, "ff_weight": 1.0}, None
        )
        == 0.0
    )


# ── configurable toggle/values ───────────────────────────────────────────────


def test_disabled_via_config_returns_zero_even_when_cold():
    config = {"weather_compensation_enabled": False}
    assert _weather_compensation_feedforward(config, -10.0) == 0.0


def test_custom_reference_temp_shifts_the_zero_point():
    config = {"ff_reference_outdoor_temp": 10.0, "ff_weight": 0.02}
    assert _weather_compensation_feedforward(config, 10.0) == 0.0
    assert _weather_compensation_feedforward(config, 12.0) == 0.0  # above reference


def test_custom_weight_scales_contribution():
    config = {
        "ff_reference_outdoor_temp": 15.0,
        "ff_weight": 0.05,
        "ff_max_contribution": 1.0,
    }
    # (15 - 5) * 0.05 = 0.5
    result = _weather_compensation_feedforward(config, 5.0)
    assert abs(result - 0.5) < 1e-9


def test_custom_max_contribution_caps_lower_than_default():
    config = {
        "ff_reference_outdoor_temp": 15.0,
        "ff_weight": 0.02,
        "ff_max_contribution": 0.1,
    }
    # Uncapped would be (15 - (-20)) * 0.02 = 0.7, but capped to 0.1.
    result = _weather_compensation_feedforward(config, -20.0)
    assert result == 0.1


def test_enabled_explicitly_true_behaves_same_as_default():
    config_explicit = {"weather_compensation_enabled": True}
    config_default = {}
    assert _weather_compensation_feedforward(
        config_explicit, 5.0
    ) == _weather_compensation_feedforward(config_default, 5.0)
