"""
Tests for engine/pid_controller.py

All tests run completely offline — no Home Assistant imports.
"""
from __future__ import annotations

import pytest

from custom_components.heat_manager.engine.pid_controller import (
    DEFAULT_TRV_MAX_TEMP,
    DEFAULT_TRV_MIN_TEMP,
    PidController,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_pid(**kwargs) -> PidController:
    defaults = dict(kp=0.5, ki=0.02, kd=0.0, room_name="test_room")
    defaults.update(kwargs)
    return PidController(**defaults)


# ── Proportional term ──────────────────────────────────────────────────────────

def test_p_only_positive_error():
    """Positive error → positive output."""
    pid = make_pid(kp=1.0, ki=0.0)
    output = pid.update(setpoint=22.0, current=20.0)
    assert output == pytest.approx(1.0)


def test_p_only_zero_error():
    """Zero error → zero output (no integral contribution yet)."""
    pid = make_pid(kp=1.0, ki=0.0)
    output = pid.update(setpoint=21.0, current=21.0)
    assert output == pytest.approx(0.0)


def test_p_only_negative_error_clamped():
    """Room warmer than setpoint → output clamped to 0 (no cooling)."""
    pid = make_pid(kp=1.0, ki=0.0)
    output = pid.update(setpoint=20.0, current=22.0)
    assert output == pytest.approx(0.0)


def test_p_partial_output():
    """0.5 °C error with Kp=0.5 → output 0.25."""
    pid = make_pid(kp=0.5, ki=0.0)
    output = pid.update(setpoint=21.5, current=21.0)
    assert output == pytest.approx(0.25)


# ── Integral term ──────────────────────────────────────────────────────────────

def test_integral_accumulates():
    """Persistent 1 °C error accumulates over ticks."""
    pid = make_pid(kp=0.0, ki=0.1)
    out1 = pid.update(22.0, 21.0)
    out2 = pid.update(22.0, 21.0)
    assert out2 > out1


def test_integral_antiwindup():
    """Integral is clamped to INTEGRAL_MAX=5.0 regardless of tick count."""
    pid = make_pid(kp=0.0, ki=0.001)
    for _ in range(1000):
        pid.update(30.0, 0.0)
    assert pid.integral == pytest.approx(5.0)
    assert pid.last_output <= 1.0


def test_integral_negative_antiwindup():
    """Negative integral is clamped to -INTEGRAL_MAX."""
    pid = make_pid(kp=0.0, ki=0.001)
    for _ in range(1000):
        pid.update(0.0, 30.0)
    assert pid.integral == pytest.approx(-5.0)


def test_integral_resets_on_reset():
    """reset() zeroes the integral so we start fresh after away mode."""
    pid = make_pid(kp=0.0, ki=0.1)
    pid.update(22.0, 21.0)
    pid.update(22.0, 21.0)
    assert pid.integral != 0.0
    pid.reset()
    assert pid.integral == pytest.approx(0.0)
    out = pid.update(22.0, 22.0)
    assert out == pytest.approx(0.0)


# ── Derivative term ────────────────────────────────────────────────────────────

def test_derivative_zero_on_first_tick():
    """D term is 0 on the first tick because there is no previous error."""
    pid = make_pid(kp=0.0, ki=0.0, kd=1.0)
    output = pid.update(22.0, 20.0)
    assert output == pytest.approx(0.0)


def test_derivative_brakes_rapid_approach():
    """Error shrinking fast → derivative is negative, reducing output."""
    pid = make_pid(kp=0.5, ki=0.0, kd=0.3)
    pid.update(22.0, 20.0)
    out2 = pid.update(22.0, 21.5)
    assert out2 < 0.25


def test_derivative_disabled_when_kd_zero():
    """With kd=0, two identical errors produce identical outputs."""
    pid = make_pid(kp=0.5, ki=0.0, kd=0.0)
    out1 = pid.update(22.0, 20.0)
    out2 = pid.update(22.0, 20.0)
    assert out1 == pytest.approx(out2)


# ── Output clamping ────────────────────────────────────────────────────────────

def test_output_never_exceeds_max():
    pid = make_pid(kp=10.0, ki=0.0)
    output = pid.update(30.0, 10.0)
    assert output <= 1.0


def test_output_never_below_min():
    pid = make_pid(kp=10.0, ki=0.0, output_min=0.0)
    output = pid.update(10.0, 30.0)
    assert output >= 0.0


def test_custom_output_bounds():
    pid = make_pid(kp=0.1, ki=0.0, output_min=0.2, output_max=0.8)
    out = pid.update(20.0, 20.0)
    assert out == pytest.approx(0.2)


# ── power_to_setpoint ──────────────────────────────────────────────────────────

def test_power_zero_returns_trv_min():
    sp = PidController.power_to_setpoint(0.0, current_temp=20.0)
    assert sp == pytest.approx(DEFAULT_TRV_MIN_TEMP)


def test_power_one_returns_trv_max():
    sp = PidController.power_to_setpoint(1.0, current_temp=20.0)
    assert sp == pytest.approx(DEFAULT_TRV_MAX_TEMP)


def test_power_half_midpoint():
    sp = PidController.power_to_setpoint(0.5, current_temp=20.0, trv_max=28.0)
    assert sp == pytest.approx(24.0)


def test_power_to_setpoint_custom_trv_max():
    sp = PidController.power_to_setpoint(1.0, current_temp=21.0, trv_max=30.0)
    assert sp == pytest.approx(30.0)


def test_power_to_setpoint_rounds_to_one_decimal():
    sp = PidController.power_to_setpoint(0.333, current_temp=20.0, trv_max=28.0)
    assert sp == round(sp, 1)


def test_power_to_setpoint_high_current_temp():
    """If current > trv_max, result is clamped to trv_max."""
    sp = PidController.power_to_setpoint(0.5, current_temp=32.0, trv_max=28.0)
    assert sp <= DEFAULT_TRV_MAX_TEMP


# ── Reset behaviour ────────────────────────────────────────────────────────────

def test_reset_clears_prev_error_so_d_is_zero_next_tick():
    """After reset(), the D term should be 0 on the next tick."""
    pid = make_pid(kp=0.0, ki=0.0, kd=1.0)
    pid.update(22.0, 20.0)
    pid.reset()
    out = pid.update(22.0, 20.0)
    assert out == pytest.approx(0.0)


def test_last_output_updates_after_each_tick():
    pid = make_pid(kp=0.5, ki=0.0)
    pid.update(22.0, 21.0)
    assert pid.last_output == pytest.approx(0.5)
    pid.update(22.0, 22.0)
    assert pid.last_output == pytest.approx(0.0)


# ── Regression: B-PID-1 ────────────────────────────────────────────────────────

def test_bug_b_pid_1_integral_does_not_windup_during_away():
    """
    B-PID-1: Anti-windup clamp must prevent integral from growing
    arbitrarily large during away/window-open, so that on resume the
    room does not overheat.
    """
    pid = make_pid(kp=0.0, ki=0.5)
    for _ in range(200):
        pid.update(22.0, 15.0)
    assert abs(pid.integral) <= 5.0
    assert 0.0 <= pid.last_output <= 1.0


# ── Repr ───────────────────────────────────────────────────────────────────────

def test_repr_contains_room_name():
    pid = PidController(room_name="living_room")
    assert "living_room" in repr(pid)
