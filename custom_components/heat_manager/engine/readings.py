"""Plausibility checks for raw sensor readings (pure, no Home Assistant).

A room temperature outside this range is almost certainly a glitching
sensor (reporting e.g. -200 or 3000 instead of going unavailable), so it is
treated as unavailable and never reaches the PID, schedule or calibration
logic. Shared by the coordinator and the calibration engine (v0.68.4, T3d —
before this each kept its own copy).
"""

from __future__ import annotations

ROOM_TEMP_SANITY_MIN = -20.0
ROOM_TEMP_SANITY_MAX = 50.0


def sanity_clamp_temp(value: float) -> float | None:
    """Return `value` unchanged if plausible for an indoor temp, else None."""
    if ROOM_TEMP_SANITY_MIN <= value <= ROOM_TEMP_SANITY_MAX:
        return value
    return None
