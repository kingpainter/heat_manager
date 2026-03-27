"""
Heat Manager — PID Controller Engine

A discrete-time PI(D) controller that converts a room temperature error
into a proportional heating *power fraction* (0.0 – 1.0).  The power
fraction is then mapped to a TRV setpoint by the calling engine via:

    trv_setpoint = current_temp + power × (TRV_MAX − current_temp)

This produces smooth, graduated TRV setpoints instead of binary on/off
or the legacy hardcoded 10 °C floor used in window_engine.py.

Design decisions
----------------
- **PI only by default** (Kd = 0.0): TRVs respond slowly (~5–15 min
  thermal lag). A derivative term amplifies measurement noise and causes
  chattering on 60-second ticks. Kd is exposed for experimentation but
  its default is 0.
- **Anti-windup clamp**: The integral accumulator is clamped to
  [-INTEGRAL_MAX, +INTEGRAL_MAX] each tick.  This prevents the
  integrator from building up a large debt during away/window-open
  periods, which would cause prolonged overshoot on resume.
- **dt fixed at SCAN_INTERVAL_SECONDS** (60 s): The coordinator drives
  this every tick, so dt is predictable. No wall-clock drift correction
  is needed.
- **Stateless until first ``update()``**: The controller starts neutral.
  ``reset()`` returns it to that state — call it whenever the room
  transitions to AWAY, WINDOW_OPEN, or any state where the TRV is no
  longer under PID authority.

Gains
-----
Sensible defaults for a panel radiator / TRV in a typical room
(10–20 m²) with a 60-second tick:

    Kp = 0.5   — proportional band ≈ 2 °C error → 100% power
    Ki = 0.02  — integral ramp: 1 °C offset cleared in ~50 ticks (50 min)
    Kd = 0.0   — off

Users can override these per room via the config flow.  The coordinator
stores them in ``entry.options`` under keys defined in const.py.

This engine has **no Home Assistant imports** — it is fully testable
offline with plain pytest.
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# Maximum absolute value of the integral accumulator (anti-windup)
_INTEGRAL_MAX: float = 5.0

# TRV setpoint ceiling when power = 1.0 (°C)
DEFAULT_TRV_MAX_TEMP: float = 28.0

# Floor setpoint when power = 0.0 (°C) — replaces the hardcoded 10 °C
DEFAULT_TRV_MIN_TEMP: float = 10.0


class PidController:
    """
    Discrete-time PI(D) controller for one room.

    Parameters
    ----------
    kp:
        Proportional gain.
    ki:
        Integral gain (per tick).
    kd:
        Derivative gain (per tick).  Default 0 — disabled.
    output_min:
        Minimum output clamp (default 0.0 — no cooling).
    output_max:
        Maximum output clamp (default 1.0 — full power).
    room_name:
        Used only for log messages.
    """

    def __init__(
        self,
        kp: float = 0.5,
        ki: float = 0.02,
        kd: float = 0.0,
        output_min: float = 0.0,
        output_max: float = 1.0,
        room_name: str = "",
    ) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_min = output_min
        self.output_max = output_max
        self.room_name = room_name

        self._integral: float = 0.0
        self._prev_error: float | None = None
        self._last_output: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, setpoint: float, current: float) -> float:
        """
        Compute one PID tick.

        Parameters
        ----------
        setpoint:
            Desired room temperature (°C).
        current:
            Measured room temperature (°C).

        Returns
        -------
        float
            Power fraction in [output_min, output_max].
            Typically 0.0 (no heat) to 1.0 (full heat).
        """
        error = setpoint - current

        # ── Proportional term ────────────────────────────────────────────────
        p_term = self.kp * error

        # ── Integral term with anti-windup clamp ─────────────────────────────
        self._integral += error
        self._integral = max(-_INTEGRAL_MAX, min(_INTEGRAL_MAX, self._integral))
        i_term = self.ki * self._integral

        # ── Derivative term (disabled when kd == 0 or first tick) ────────────
        if self.kd != 0.0 and self._prev_error is not None:
            d_term = self.kd * (error - self._prev_error)
        else:
            d_term = 0.0
        self._prev_error = error

        # ── Sum and clamp ─────────────────────────────────────────────────────
        raw = p_term + i_term + d_term
        output = max(self.output_min, min(self.output_max, raw))

        _LOGGER.debug(
            "PID[%s] sp=%.1f cur=%.1f err=%.2f  P=%.3f I=%.3f D=%.3f → %.3f",
            self.room_name, setpoint, current, error,
            p_term, i_term, d_term, output,
        )

        self._last_output = output
        return output

    def reset(self) -> None:
        """
        Clear the integral accumulator and derivative memory.

        Call this whenever the room leaves PID authority:
        - transitions to AWAY
        - window opens (WINDOW_OPEN)
        - controller switched OFF
        - any manual override

        This prevents integral windup debt from accumulating during
        periods when the PID is not in control.
        """
        self._integral = 0.0
        self._prev_error = None
        self._last_output = 0.0
        _LOGGER.debug("PID[%s] reset", self.room_name)

    @property
    def last_output(self) -> float:
        """Most recent output value, for diagnostics / sensors."""
        return self._last_output

    @property
    def integral(self) -> float:
        """Current integral accumulator value, for diagnostics."""
        return round(self._integral, 4)

    # ── Setpoint mapper ───────────────────────────────────────────────────────

    @staticmethod
    def power_to_setpoint(
        power: float,
        current_temp: float,
        trv_max: float = DEFAULT_TRV_MAX_TEMP,
        trv_min: float = DEFAULT_TRV_MIN_TEMP,
    ) -> float:
        """
        Convert a PID power fraction (0–1) to a TRV temperature setpoint.

        Formula (same as RoomMind's proportional boost):
            setpoint = current + power × (trv_max − current)

        Edge cases
        ----------
        - power == 0.0  →  trv_min (floor, not current)
        - power == 1.0  →  trv_max (full push)
        - current > trv_max  →  result clamped to trv_max

        Returns
        -------
        float
            Rounded to one decimal place to avoid spammy TRV commands.
        """
        if power <= 0.0:
            return float(trv_min)
        boosted = current_temp + power * (trv_max - current_temp)
        clamped = max(trv_min, min(trv_max, boosted))
        return round(clamped, 1)

    def __repr__(self) -> str:
        return (
            f"PidController(room={self.room_name!r}, "
            f"kp={self.kp}, ki={self.ki}, kd={self.kd}, "
            f"integral={self._integral:.3f}, last={self._last_output:.3f})"
        )
