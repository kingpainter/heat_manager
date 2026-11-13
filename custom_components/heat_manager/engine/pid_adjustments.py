"""PID power adjustments — pure helpers used by the coordinator's PID tick.

Weather compensation adds power on a cold day; solar gain and door heat
sharing remove it. Each is a pure function of the config and the readings
passed in, so it is testable without Home Assistant (moved out of
coordinator.py in v0.68.1, T3a).
"""

from __future__ import annotations

from typing import Any

from ..const import (
    CONF_DOOR_HEAT_SHARE_ENABLED,
    CONF_DOOR_HEAT_SHARE_MAX_REDUCTION,
    CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF,
    CONF_DOOR_HEAT_SHARE_WEIGHT,
    CONF_FF_MAX_CONTRIBUTION,
    CONF_FF_REFERENCE_OUTDOOR_TEMP,
    CONF_FF_WEIGHT,
    CONF_SOLAR_GAIN_ENABLED,
    CONF_SOLAR_GAIN_LUX_THRESHOLD,
    CONF_SOLAR_GAIN_MAX_REDUCTION,
    CONF_SOLAR_GAIN_WEIGHT,
    CONF_WEATHER_COMPENSATION_ENABLED,
    DEFAULT_DOOR_HEAT_SHARE_ENABLED,
    DEFAULT_SOLAR_GAIN_ENABLED,
    DEFAULT_WEATHER_COMPENSATION_ENABLED,
    DOOR_HEAT_SHARE_MAX_REDUCTION,
    DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    DOOR_HEAT_SHARE_MIN_TEMP_DIFF,
    DOOR_HEAT_SHARE_WEIGHT,
    FF_MAX_CONTRIBUTION,
    FF_REFERENCE_OUTDOOR_TEMP,
    FF_WEIGHT,
    SOLAR_GAIN_LUX_THRESHOLD,
    SOLAR_GAIN_MAX_REDUCTION,
    SOLAR_GAIN_WEIGHT,
)


def weather_compensation_feedforward(
    config: dict[str, Any], outdoor_temp: float | None
) -> float:
    """Outdoor-temperature PID feedforward (weather compensation curve) —
    2026-09-13, architecture review #5. A proactive power contribution added
    on top of PID's reactive correction, classic "heating curve" style. This
    existed already as a hardcoded, always-on constant ("Conservative
    defaults, not yet exposed in the UI" — see const.py's FF_* comment); it's
    now configurable via CONF_WEATHER_COMPENSATION_ENABLED/CONF_FF_*, with
    the exact previous hardcoded values as fallback defaults so an existing
    install's behaviour is unchanged until these are actually edited from
    Indstillinger/options-flow. A pure function of (config, outdoor_temp) —
    no coordinator/hass access needed — so it's unit-testable in isolation;
    see the coordinator's PID tick for the call site.
    """
    if outdoor_temp is None:
        return 0.0
    if not config.get(
        CONF_WEATHER_COMPENSATION_ENABLED, DEFAULT_WEATHER_COMPENSATION_ENABLED
    ):
        return 0.0
    ff_reference = float(
        config.get(CONF_FF_REFERENCE_OUTDOOR_TEMP, FF_REFERENCE_OUTDOOR_TEMP)
    )
    ff_weight = float(config.get(CONF_FF_WEIGHT, FF_WEIGHT))
    ff_max = float(config.get(CONF_FF_MAX_CONTRIBUTION, FF_MAX_CONTRIBUTION))
    return min(ff_max, max(0.0, (ff_reference - outdoor_temp) * ff_weight))


def solar_gain_reduction(
    config: dict[str, Any], lux: float | None, sun_elevation: float | None
) -> float:
    """Solar-gain PID power REDUCTION (2026-09-14, punkt 7) — a room reading
    bright sunlight right now needs less TRV-delivered heat than the
    schedule alone would call for. Deliberately the mirror image of
    weather_compensation_feedforward() above: that one only ever ADDS
    power (colder outside → more proactive heat); this one only ever
    SUBTRACTS it (brighter inside → less needed) — the two are meant to
    partially cancel on a cold-but-sunny day, which is exactly the case a
    lux-based signal is good at catching and a pure outdoor-temperature
    curve is not.

    Returns 0.0 (no effect) unless ALL of: the feature is enabled, this
    room has a lux reading, sun.sun reports the sun above the horizon
    (elevation > 0 — a negative/zero elevation is dusk/night, where no lux
    reading should physically be able to exceed the threshold anyway, but
    checking explicitly avoids ever trusting a lux sensor's own glitch
    after dark), and the lux reading exceeds CONF_SOLAR_GAIN_LUX_THRESHOLD.
    A pure function of (config, lux, sun_elevation) — no coordinator/hass
    access needed — same testability rationale as the feedforward helper
    above; see the coordinator's PID tick for how lux/elevation are read.
    """
    if lux is None or sun_elevation is None or sun_elevation <= 0:
        return 0.0
    if not config.get(CONF_SOLAR_GAIN_ENABLED, DEFAULT_SOLAR_GAIN_ENABLED):
        return 0.0
    threshold = float(
        config.get(CONF_SOLAR_GAIN_LUX_THRESHOLD, SOLAR_GAIN_LUX_THRESHOLD)
    )
    if lux <= threshold or threshold <= 0:
        return 0.0
    weight = float(config.get(CONF_SOLAR_GAIN_WEIGHT, SOLAR_GAIN_WEIGHT))
    max_reduction = float(
        config.get(CONF_SOLAR_GAIN_MAX_REDUCTION, SOLAR_GAIN_MAX_REDUCTION)
    )
    excess_ratio = (lux - threshold) / threshold
    return min(max_reduction, excess_ratio * weight)


def door_heat_share_reduction(
    config: dict[str, Any],
    neighbor_power: float | None,
    temp_diff: float | None,
) -> float:
    """Door-heat-sharing PID power REDUCTION (2026-09-16, punkt 8) — a room
    with an open interior door to a warmer, actively-heating neighbour
    needs less TRV-delivered heat than the schedule alone would call for,
    since part of the work is already being done for free through the
    doorway. Same shape as solar_gain_reduction() above (only ever
    SUBTRACTS power, never adds) and the same reason it's a power
    reduction rather than a target_temp change: see const.py's
    CONF_DOOR_HEAT_SHARE_ENABLED docstring for the ownership-question
    rationale this design sidesteps entirely.

    Returns 0.0 (no effect) unless ALL of: the feature is enabled, both
    `neighbor_power` and `temp_diff` are known (None means "no open door
    to a room with an active PID" — see the coordinator's PID tick for
    how these are resolved across a room's open doors), the neighbour's
    own PID power meets CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER (it must
    actually be delivering heat right now, not just be warmer from
    residual heat earlier), and the temperature gap meets
    CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF (a real gradient, not noise). A
    pure function of its three arguments — no coordinator/hass access
    needed — same testability rationale as the feedforward/solar-gain
    helpers above.
    """
    if neighbor_power is None or temp_diff is None:
        return 0.0
    if not config.get(CONF_DOOR_HEAT_SHARE_ENABLED, DEFAULT_DOOR_HEAT_SHARE_ENABLED):
        return 0.0
    min_neighbor_power = float(
        config.get(
            CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
            DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
        )
    )
    if neighbor_power < min_neighbor_power:
        return 0.0
    min_temp_diff = float(
        config.get(CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF, DOOR_HEAT_SHARE_MIN_TEMP_DIFF)
    )
    if temp_diff < min_temp_diff:
        return 0.0
    weight = float(config.get(CONF_DOOR_HEAT_SHARE_WEIGHT, DOOR_HEAT_SHARE_WEIGHT))
    max_reduction = float(
        config.get(CONF_DOOR_HEAT_SHARE_MAX_REDUCTION, DOOR_HEAT_SHARE_MAX_REDUCTION)
    )
    return min(max_reduction, temp_diff * weight)
