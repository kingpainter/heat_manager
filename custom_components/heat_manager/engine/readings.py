"""Plausibility checks for raw sensor readings (pure, no Home Assistant).

A room temperature outside this range is almost certainly a glitching
sensor (reporting e.g. -200 or 3000 instead of going unavailable), so it is
treated as unavailable and never reaches the PID, schedule or calibration
logic. Shared by the coordinator and the calibration engine (v0.68.4, T3d —
before this each kept its own copy). Also: how long ago an entity last
reported (v0.69.1).
"""

from __future__ import annotations

from datetime import UTC, datetime

ROOM_TEMP_SANITY_MIN = -20.0
ROOM_TEMP_SANITY_MAX = 50.0


def sanity_clamp_temp(value: float) -> float | None:
    """Return `value` unchanged if plausible for an indoor temp, else None."""
    if ROOM_TEMP_SANITY_MIN <= value <= ROOM_TEMP_SANITY_MAX:
        return value
    return None


def seconds_since_report(
    now: datetime, last_updated: object, last_reported: object = None
) -> float | None:
    """Seconds since an entity was last reported by its integration.

    v0.69.1: Home Assistant only moves ``last_updated`` when the state or an
    attribute actually changes; ``last_reported`` (HA 2024.3+) also moves when
    the integration re-writes an unchanged value. Using ``last_updated`` alone
    flagged a perfectly fresh Netatmo room as "not updated in 10+ min" just
    because its temperature had not changed. Non-datetime inputs are ignored
    (mocks, missing attributes); naive datetimes are taken as UTC.
    """
    stamps = [
        ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
        for ts in (last_updated, last_reported)
        if isinstance(ts, datetime)
    ]
    if not stamps:
        return None
    return (now - max(stamps)).total_seconds()
