"""Mold risk — one shared algorithm (DIN 4108-2 simplified).

Mold risk = RH ≥ 70 %  AND  room temperature ≤ dewpoint + 1 °C margin.

The 1 °C margin accounts for wall surfaces being about 1 °C cooler than the
room air. MoldRiskSensor (binary_sensor.py), the panel payload
(websocket.py) and the push notification (coordinator) all use these
functions, so the three can no longer drift apart (v0.68.1, T3a — before
this the formula and thresholds were copied into each of them).
"""

from __future__ import annotations

import math

MOLD_RH_THRESHOLD = 70.0  # % — DIN 4108-2 critical humidity
MOLD_SURFACE_MARGIN = 1.0  # °C — wall surface is ~1 °C cooler than air


def dewpoint(temp_c: float, rh_pct: float) -> float:
    """Magnus formula (Lawrence 2005) — valid for 0–60 °C, 1–100 % RH."""
    b, c = 17.625, 243.04
    gamma = math.log(max(rh_pct, 0.01) / 100.0) + (b * temp_c) / (c + temp_c)
    return (c * gamma) / (b - gamma)


def is_mold_risk(temp_c: float, rh_pct: float) -> bool:
    """True when the room air is within the surface margin of the dewpoint
    at a humidity at or above the critical threshold."""
    if rh_pct < MOLD_RH_THRESHOLD:
        return False
    return temp_c <= dewpoint(temp_c, rh_pct) + MOLD_SURFACE_MARGIN
