"""
Heat Manager — Calibration Engine (v0.9.0)

Writes the delta between an external, independent room-temperature sensor
(CONF_ROOM_TEMP_SENSOR) and a TRV's own raw temperature reading to a
`number.*` calibration/offset entity (CONF_CALIBRATION_ENTITY), so the TRV's
own internal control loop uses an accurate reading too — not just the value
Heat Manager itself writes via PID.

Why this exists
----------------
Heat Manager's PID controller already reads CONF_ROOM_TEMP_SENSOR in
preference to a TRV's built-in probe (see coordinator.get_room_current_temp).
That fixes *Heat Manager's own* decisions, but the TRV keeps regulating
against its own uncorrected sensor whenever Heat Manager isn't actively
writing to it — during a network hiccup, an HA restart, or simply between
60 s ticks. Writing the correction back to the device's own calibration
entity (Zigbee2MQTT's `local_temperature_calibration` is the supported
target today) closes that gap.

Scope
-----
Zigbee2MQTT-style calibration entities take an OFFSET (not an absolute
value) — the delta between truth and the device's own raw reading. Netatmo
rooms have no such entity in Home Assistant today and are silently skipped.
Entirely opt-in: a room needs both CONF_ROOM_TEMP_SENSOR and
CONF_CALIBRATION_ENTITY configured before this engine touches it.

2026-09-13 (select-entity support, better_thermostat-inspired): not every
integration exposes calibration as a continuous `number` entity — some
(e.g. HomematicIP) expose it as a `select` entity with a fixed set of
discrete offset steps ("-1.0", "0.0", "+0.5", ... — the exact option
strings vary by device). CONF_CALIBRATION_ENTITY may now point at either
domain: a `number` entity is written to directly via `number.set_value` as
before; a `select` entity has its computed offset snapped to the nearest
available option (parsed from the option strings themselves — see
_parse_offset_option()) and written via `select.select_option`. Any other
domain is unsupported and silently skipped, same as an entity that doesn't
exist at all.

Heat-up-rate learning (2026-09-11, door feature point 1+2 level B)
-------------------------------------------------------------------
Separate from the sensor-offset writer above, this engine also learns how
fast each room's temperature actually rises while heating is genuinely
being called for — split into two running estimates per room, one for
"interior door open" and one for "door closed" (see coordinator.
is_room_door_open()). This is a DIFFERENT thing from the offset above: the
offset corrects a TRV's raw thermometer reading (a constant hardware
property, independent of door state); this instead tracks the room's
thermal RESPONSE, which the physics genuinely does depend on — Flemming's
own observation that a room with its door shut heats up faster than one
with the door open. Purely observational for now: nothing reads these
learned rates yet to change any control decision (level C — using them to
actively adjust a neighbouring room's target — is a separate, larger,
not-yet-approved step). Learned state lives in memory only and resets on
restart, same as the offset-writer's own state above.

2026-09-14 (punkt 5, outdoor-temperature covariate): each (room, door_open)
estimate used to be a single flat EMA — one number, averaged across
whatever mix of outdoor temperatures the room happened to be sampled at.
That's a real source of noise: a room's heat-up response to a given
call-for-heat genuinely depends on the temperature differential to the
outside (the same physical intuition already used for PID's own weather-
compensation feedforward, coordinator._weather_compensation_feedforward) —
heating a room from 19->20°C measurably takes longer against a -5°C sky
than a +5°C one, purely from ongoing radiative/convective loss during the
sample window. This is now modelled as an exponentially-weighted linear
regression, rate ≈ intercept + slope × outdoor_temp, so
get_room_heatup_rate() can return a prediction for the CURRENT outdoor
temperature instead of one number averaged away across every outdoor
temperature ever observed. Deliberately not a full recursive-least-squares
fit (no covariance matrix, no per-sample weighting) — an exponentially-
weighted running mean/variance/covariance, updated with the same EMA alpha
the rate itself always used, needs only four floats per key (same "resets
on restart, no persisted history" footprint the old flat EMA had) and is
plenty for this sample rate/noise level. Falls back to the flat mean
(the old EMA's exact behaviour) whenever there isn't yet enough spread in
the observed outdoor temperatures to fit a slope reliably, or when the
install has no outdoor-temperature source configured at all — expected and
normal for at least the first weeks of a heating season, matching the
implementation plan's own note that this needs "more validation across a
temperature range than a pure EMA adjustment" before it's trustworthy.
This is explicit forarbejde for punkt 6 (an EKF thermal model) — see the
plan's own recommendation to let this run a full heating season first.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.util.dt import utcnow

from ..const import (
    CALIBRATION_CHANGE_THRESHOLD,
    CALIBRATION_OFFSET_MAX,
    CALIBRATION_OFFSET_MIN,
    CONF_ROOM_TEMP_SENSOR,
    DEFAULT_CALIBRATION_HEARTBEAT_MIN,
    RoomState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# 3.5 hardening: reject implausible readings (a glitching sensor reporting
# e.g. -200 or 3000 instead of going unavailable) before they turn into a
# bogus calibration offset — mirrors coordinator._sanity_clamp_temp's range.
_ROOM_TEMP_SANITY_MIN = -20.0
_ROOM_TEMP_SANITY_MAX = 50.0

# ── Heat-up-rate learning tuning ────────────────────────────────────────────
# A sample needs at least this long between baseline and comparison reading
# so a genuine rate is distinguishable from typical 0.1°C sensor resolution
# noise (a real 0.5–2°C/h room rate needs several minutes to clear that
# resolution floor).
_HEATUP_MIN_SAMPLE_SEC = 300  # 5 min
# A gap longer than this (HA restart, integration reload, a radio dropout)
# makes the two readings incomparable — the baseline is simply reset rather
# than treated as one (very wrong) multi-hour sample.
_HEATUP_MAX_SAMPLE_SEC = 1800  # 30 min
# Discard a computed rate outside this range as a sensor glitch rather than
# folding it into the learned average.
_HEATUP_RATE_SANITY_MAX = 15.0  # °C/hour
# Exponential-moving-average weight for each new valid sample — deliberately
# slow-moving since a room's thermal behaviour doesn't change tick to tick.
# Reused (2026-09-14, punkt 5) as the decay weight for the outdoor-
# temperature regression's running mean/variance/covariance estimates too.
_HEATUP_EMA_ALPHA = 0.15

# 2026-09-14 (punkt 5) — the regression's fitted slope is only trusted once
# the room has actually been sampled across a meaningful spread of outdoor
# temperatures; with too little spread the divide (covariance / variance)
# is numerically unstable and would happily fit a wild slope to what's
# really just noise around one outdoor temperature. Below this variance
# (°C²) the flat mean is used instead, same as the old plain-EMA rate.
# ~4.0 corresponds to roughly ±2°C of observed spread.
_HEATUP_REGRESSION_MIN_VAR = 4.0

# ── Heat-up-rate anomaly detection (2026-09-13, architecture review #3) ────
# A room's learned rate is only a meaningful baseline once it's actually
# been observed a few times — comparing against a brand-new EMA (a single
# sample) would flag every room as "anomalous" the moment it starts
# learning. Require this many valid samples before the baseline is trusted
# enough to compare new samples against at all.
_HEATUP_ANOMALY_MIN_SAMPLES = 5
# A single sample coming in well below the learned baseline is still
# ordinary noise (draught from an opened door, a person standing near the
# sensor, etc.) — only flag a room once several samples IN A ROW undershoot
# the baseline, so this reflects a sustained pattern, not one weird tick.
_HEATUP_ANOMALY_STREAK_THRESHOLD = 3
# A sample below this fraction of the room's own learned baseline counts as
# "underperforming" for the streak above.
_HEATUP_ANOMALY_RATIO = 0.4


def _sanity_clamp_temp(value: float) -> float | None:
    """Return `value` unchanged if plausible for an indoor temp, else None."""
    if _ROOM_TEMP_SANITY_MIN <= value <= _ROOM_TEMP_SANITY_MAX:
        return value
    return None


# 2026-09-13 select-entity support: matches the first signed/unsigned
# decimal number in an option string ("-1.0", "+0.5K", "2.0 °C" all match)
# so the numeric step a select-based calibration control represents can be
# recovered without knowing the exact unit/suffix convention a given
# integration uses.
_OFFSET_OPTION_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _parse_offset_option(text: str) -> float | None:
    """Extract the numeric offset value from a select entity's option
    string (e.g. "-1.0", "+0.5K"), or None if it contains no number."""
    match = _OFFSET_OPTION_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


class CalibrationEngine:
    """Per-room TRV calibration offset writer with a timeout-guarding heartbeat.

    Also learns per-room, per-door-state heat-up rates — see module
    docstring's "Heat-up-rate learning" section.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._last_written: dict[str, float] = {}
        self._last_write_time: dict[str, datetime] = {}

        # Heat-up-rate learning state — keyed by room_name.
        self._heatup_baseline_temp: dict[str, float] = {}
        self._heatup_baseline_time: dict[str, datetime] = {}
        self._heatup_baseline_door_open: dict[str, bool] = {}
        # 2026-09-14 (punkt 5) — exponentially-weighted linear regression of
        # heat-up rate against outdoor temperature, keyed by
        # (room_name, door_open). mean_y alone (no mean_x/_xy/_xx yet, or
        # not enough variance in mean_x) is exactly the old flat EMA
        # behaviour — see _heatup_regression_coeffs()/_predict_heatup_rate().
        self._heatup_mean_x: dict[tuple[str, bool], float] = {}  # outdoor temp EMA
        self._heatup_mean_y: dict[tuple[str, bool], float] = {}  # rate EMA (was _heatup_rate_ema)
        self._heatup_mean_xy: dict[tuple[str, bool], float] = {}
        self._heatup_mean_xx: dict[tuple[str, bool], float] = {}
        # 2026-09-13 anomaly detection — how many valid samples have gone
        # into each (room, door_open) EMA so far, so a brand-new baseline
        # isn't compared against yet (see _HEATUP_ANOMALY_MIN_SAMPLES).
        self._heatup_sample_count: dict[tuple[str, bool], int] = {}
        # Consecutive samples per room that undershot their own learned
        # baseline — reset to 0 on any sample that doesn't undershoot, or
        # when the room stops actively heating. Exposed via
        # get_room_heatup_anomaly() once it reaches the streak threshold.
        self._heatup_anomaly_streak: dict[str, int] = {}

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS from the coordinator's main tick."""
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            climate_entity = self.coordinator.get_climate_entity(room_name) or ""

            self._async_update_heatup_learning(room_name, climate_entity)

            calibration_entity = self.coordinator.get_room_calibration_entity(room_name)
            room_temp_sensor = room.get(CONF_ROOM_TEMP_SENSOR) or None
            if not calibration_entity or not room_temp_sensor:
                continue
            await self._async_update_room(
                room_name, climate_entity, room_temp_sensor, calibration_entity
            )

    # ── Heat-up-rate learning ────────────────────────────────────────────────

    def _async_update_heatup_learning(
        self, room_name: str, climate_entity: str
    ) -> None:
        """Update the running heat-up-rate estimate for one room.

        Uses coordinator.get_room_current_temp() (room sensor when
        configured, TRV's own reading otherwise) so every room with a
        climate entity is covered, not only rooms with a dedicated external
        sensor. See the tuning constants above for the sampling window and
        sanity bounds, and the module docstring for why this is tracked
        separately from the sensor-offset writer below.
        """
        current_temp = self.coordinator.get_room_current_temp(room_name, climate_entity)
        if current_temp is None:
            return
        current_temp = _sanity_clamp_temp(current_temp)
        if current_temp is None:
            return

        now = utcnow()
        baseline_temp = self._heatup_baseline_temp.get(room_name)
        baseline_time = self._heatup_baseline_time.get(room_name)
        baseline_door_open = self._heatup_baseline_door_open.get(room_name, False)

        if baseline_temp is None or baseline_time is None:
            self._heatup_reset_baseline(room_name, current_temp, now)
            return

        elapsed = (now - baseline_time).total_seconds()
        if elapsed < _HEATUP_MIN_SAMPLE_SEC:
            return  # keep accumulating against the same baseline
        if elapsed > _HEATUP_MAX_SAMPLE_SEC:
            # Too long a gap to compare (restart/reload/dropout) — restart
            # the baseline from here rather than treat it as one sample.
            self._heatup_reset_baseline(room_name, current_temp, now)
            return

        delta_temp = current_temp - baseline_temp
        room_state = self.coordinator.get_room_state(room_name)
        is_actively_heating = room_state in (RoomState.NORMAL, RoomState.PRE_HEAT)

        if not is_actively_heating:
            # 2026-09-13 anomaly detection: a room that isn't actively
            # heating (away/window-open/override) has no baseline to judge
            # — clear any streak so a real, current problem doesn't linger
            # as a stale flag once heating resumes.
            self._heatup_anomaly_streak[room_name] = 0

        if is_actively_heating and delta_temp > 0.05:
            rate_per_hour = delta_temp / elapsed * 3600
            if abs(rate_per_hour) <= _HEATUP_RATE_SANITY_MAX:
                key = (room_name, baseline_door_open)
                # 2026-09-14 (punkt 5): the outdoor temperature during THIS
                # sample window — read once so the anomaly comparison below
                # and the regression update after it use the exact same
                # value (a tick boundary could otherwise see it change
                # between the two reads).
                outdoor_temp = self.coordinator.outdoor_temperature
                sample_count = self._heatup_sample_count.get(key, 0)

                # 2026-09-13 anomaly detection (architecture review #3): a
                # sample well below this room's OWN established baseline,
                # several times in a row, is a cheap, concrete signal
                # something's physically wrong (stuck valve, closed
                # radiator lockshield, empty system) — compared against the
                # room's own history, not a fixed global threshold, since
                # "normal" heat-up rate varies hugely by room size/
                # insulation. Only evaluated once the baseline itself is
                # trustworthy (enough prior samples). 2026-09-14 (punkt 5):
                # the baseline is now the regression's PREDICTED rate for
                # today's actual outdoor temperature rather than one flat
                # average across every outdoor temperature ever observed —
                # a room heating slower purely because it's much colder out
                # right now is no longer mistaken for an anomaly.
                predicted = self._predict_heatup_rate(key, outdoor_temp)
                if predicted is not None and sample_count >= _HEATUP_ANOMALY_MIN_SAMPLES:
                    if rate_per_hour < predicted * _HEATUP_ANOMALY_RATIO:
                        self._heatup_anomaly_streak[room_name] = (
                            self._heatup_anomaly_streak.get(room_name, 0) + 1
                        )
                        _LOGGER.debug(
                            "Heat-up rate [%s]: sample=%.2f°C/h well below own"
                            " predicted=%.2f°C/h (streak=%d)",
                            room_name,
                            rate_per_hour,
                            predicted,
                            self._heatup_anomaly_streak[room_name],
                        )
                    else:
                        self._heatup_anomaly_streak[room_name] = 0

                self._heatup_update_regression(key, outdoor_temp, rate_per_hour)
                self._heatup_sample_count[key] = sample_count + 1
                _LOGGER.debug(
                    "Heat-up rate [%s, door_open=%s]: sample=%.2f°C/h"
                    " (outdoor=%s) → mean_y=%.2f°C/h",
                    room_name,
                    baseline_door_open,
                    rate_per_hour,
                    f"{outdoor_temp:.1f}°C" if outdoor_temp is not None else "n/a",
                    self._heatup_mean_y.get(key, rate_per_hour),
                )

        self._heatup_reset_baseline(room_name, current_temp, now)

    def _heatup_update_regression(
        self, key: tuple[str, bool], outdoor_temp: float | None, rate_per_hour: float
    ) -> None:
        """Fold one new (outdoor_temp, rate) sample into this key's
        exponentially-weighted regression state (punkt 5, 2026-09-14).

        mean_y is updated unconditionally — a room with no outdoor-
        temperature source configured still gets the old flat-EMA learning
        behaviour, it just never accumulates enough for a slope
        (_heatup_regression_coeffs always falls back to flat mean_y for it).
        """
        mean_y = self._heatup_mean_y.get(key)
        self._heatup_mean_y[key] = (
            rate_per_hour if mean_y is None else mean_y + _HEATUP_EMA_ALPHA * (rate_per_hour - mean_y)
        )
        if outdoor_temp is None:
            return  # no x sample this tick — regression state untouched
        mean_x = self._heatup_mean_x.get(key)
        if mean_x is None:
            self._heatup_mean_x[key] = outdoor_temp
            self._heatup_mean_xy[key] = outdoor_temp * self._heatup_mean_y[key]
            self._heatup_mean_xx[key] = outdoor_temp * outdoor_temp
            return
        mean_xy = self._heatup_mean_xy.get(key, mean_x * mean_y if mean_y is not None else 0.0)
        mean_xx = self._heatup_mean_xx.get(key, mean_x * mean_x)
        self._heatup_mean_x[key] = mean_x + _HEATUP_EMA_ALPHA * (outdoor_temp - mean_x)
        self._heatup_mean_xy[key] = mean_xy + _HEATUP_EMA_ALPHA * (
            outdoor_temp * rate_per_hour - mean_xy
        )
        self._heatup_mean_xx[key] = mean_xx + _HEATUP_EMA_ALPHA * (
            outdoor_temp * outdoor_temp - mean_xx
        )

    def _heatup_regression_coeffs(
        self, key: tuple[str, bool]
    ) -> tuple[float, float] | None:
        """Return (intercept, slope) for this key's outdoor-temperature
        regression, or None if no sample has been observed for this key at
        all yet. slope is 0.0 (flat fallback — old plain-EMA behaviour)
        whenever there isn't enough observed outdoor-temperature spread to
        fit a reliable slope; see _HEATUP_REGRESSION_MIN_VAR."""
        mean_y = self._heatup_mean_y.get(key)
        if mean_y is None:
            return None
        mean_x = self._heatup_mean_x.get(key)
        if mean_x is None:
            return (mean_y, 0.0)
        mean_xy = self._heatup_mean_xy.get(key, mean_x * mean_y)
        mean_xx = self._heatup_mean_xx.get(key, mean_x * mean_x)
        var_x = mean_xx - mean_x * mean_x
        if var_x < _HEATUP_REGRESSION_MIN_VAR:
            return (mean_y, 0.0)
        cov_xy = mean_xy - mean_x * mean_y
        slope = cov_xy / var_x
        intercept = mean_y - slope * mean_x
        return (intercept, slope)

    def _predict_heatup_rate(
        self, key: tuple[str, bool], outdoor_temp: float | None
    ) -> float | None:
        """Predicted heat-up rate (°C/hour) for this key at `outdoor_temp`,
        or the flat learned mean when no outdoor temperature is available
        or no slope has been fitted yet. None only when this key has no
        samples at all."""
        coeffs = self._heatup_regression_coeffs(key)
        if coeffs is None:
            return None
        intercept, slope = coeffs
        if outdoor_temp is None or slope == 0.0:
            return self._heatup_mean_y.get(key)
        return intercept + slope * outdoor_temp

    def _heatup_reset_baseline(self, room_name: str, temp: float, at: datetime) -> None:
        self._heatup_baseline_temp[room_name] = temp
        self._heatup_baseline_time[room_name] = at
        self._heatup_baseline_door_open[room_name] = self.coordinator.is_room_door_open(
            room_name
        )

    def get_room_heatup_rate(
        self, room_name: str, door_open: bool, outdoor_temp: float | None = None
    ) -> float | None:
        """Learned heat-up rate for this room (°C/hour) with the door in the
        given state, or None if not enough data has been observed yet.

        2026-09-14 (punkt 5): predicted via an exponentially-weighted linear
        regression against outdoor temperature, once enough outdoor-
        temperature spread has been observed to fit a slope (falls back to
        the flat learned mean otherwise — the exact value this method
        always returned before punkt 5). `outdoor_temp` defaults to the
        coordinator's current reading when not given explicitly, so every
        existing caller (websocket.py's room payload, the anomaly check
        above) transparently gets the temperature-aware prediction without
        needing to pass it themselves.
        """
        if outdoor_temp is None:
            outdoor_temp = self.coordinator.outdoor_temperature
        return self._predict_heatup_rate((room_name, door_open), outdoor_temp)

    def get_room_heatup_anomaly(self, room_name: str) -> bool:
        """True when this room has heated up markedly slower than its own
        learned baseline for several samples in a row (architecture review
        #3, 2026-09-13) — a cheap, room-relative signal worth surfacing in
        the status center (websocket.py's _build_active_issues), e.g. a
        stuck valve, a closed lockshield, or an empty radiator. Never gates
        any control decision — purely diagnostic, same as the heat-up rate
        itself."""
        return (
            self._heatup_anomaly_streak.get(room_name, 0)
            >= _HEATUP_ANOMALY_STREAK_THRESHOLD
        )

    async def _async_update_room(
        self,
        room_name: str,
        climate_entity: str,
        room_temp_sensor: str,
        calibration_entity: str,
    ) -> None:
        truth = self._read_float(room_temp_sensor)
        if truth is None:
            return

        raw = self._read_trv_raw_temperature(climate_entity)
        if raw is None:
            return

        domain = calibration_entity.split(".", 1)[0]
        if domain not in ("number", "select"):
            _LOGGER.debug(
                "Calibration entity '%s' for room '%s' has unsupported domain"
                " '%s' — skipped",
                calibration_entity,
                room_name,
                domain,
            )
            return

        # `raw` already reflects whatever calibration is currently applied
        # (see _read_trv_raw_temperature's docstring), so (truth - raw) is
        # only the *residual* error left after that offset — not the
        # absolute offset to write. Writing the residual directly as an
        # absolute value would oscillate: e.g. tick 1 computes +1.0°C and
        # writes it: the device then reports a corrected temperature; tick 2
        # sees a ~0 residual against that now-corrected reading and writes
        # 0.0°C, undoing tick 1's correction; tick 3 is back to computing
        # +1.0°C — forever. Reading the entity's own current value and
        # adding the residual on top gives the correct absolute target and
        # converges to a stable value instead.
        current_offset = self._read_calibration_value(calibration_entity, domain)
        if current_offset is None:
            current_offset = 0.0
        desired_offset = max(
            CALIBRATION_OFFSET_MIN,
            min(CALIBRATION_OFFSET_MAX, current_offset + (truth - raw)),
        )

        if domain == "select":
            option = self._nearest_select_option(calibration_entity, desired_offset)
            if option is None:
                _LOGGER.debug(
                    "Calibration select entity '%s' for room '%s' has no"
                    " parseable numeric options — skipped",
                    calibration_entity,
                    room_name,
                )
                return
            write_value = option["value"]
            service_domain, service_name = "select", "select_option"
            service_data = {"entity_id": calibration_entity, "option": option["label"]}
        else:
            write_value = round(desired_offset, 1)
            service_domain, service_name = "number", "set_value"
            service_data = {"entity_id": calibration_entity, "value": write_value}

        last_value = self._last_written.get(room_name)
        last_time = self._last_write_time.get(room_name)
        now = utcnow()

        needs_heartbeat = last_time is None or (
            now - last_time >= timedelta(minutes=DEFAULT_CALIBRATION_HEARTBEAT_MIN)
        )
        needs_change_write = (
            last_value is None
            or abs(write_value - last_value) >= CALIBRATION_CHANGE_THRESHOLD
        )

        if not needs_heartbeat and not needs_change_write:
            return

        try:
            await self.coordinator.hass.services.async_call(
                service_domain,
                service_name,
                service_data,
                blocking=True,
            )
            self._last_written[room_name] = write_value
            self._last_write_time[room_name] = now
            _LOGGER.debug(
                "Calibration [%s]: truth=%.1f°C raw=%.1f°C → offset=%.1f°C written to %s"
                " (%s)",
                room_name,
                truth,
                raw,
                write_value,
                calibration_entity,
                "heartbeat"
                if needs_heartbeat and not needs_change_write
                else "changed",
            )
        # broad-except-rationale: one entity failing must not abort the others in this loop
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Calibration write failed for '%s' (%s): %s",
                room_name,
                calibration_entity,
                err,
            )

    def _read_calibration_value(self, entity_id: str, domain: str) -> float | None:
        """Current calibration value, however the entity represents it —
        a plain number for `number.*`, or the parsed numeric equivalent of
        the currently-selected option for `select.*`."""
        if domain == "number":
            return self._read_float(entity_id)
        state = self.coordinator.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return _parse_offset_option(state.state)

    def _nearest_select_option(
        self, entity_id: str, desired_offset: float
    ) -> dict[str, float | str] | None:
        """Return {"label": <option string>, "value": <parsed float>} for
        the select entity's own option closest to `desired_offset`, or None
        if the entity is missing or none of its options parse as a number."""
        state = self.coordinator.hass.states.get(entity_id)
        if state is None:
            return None
        options = state.attributes.get("options") or []
        parsed = [
            (opt, val)
            for opt in options
            if (val := _parse_offset_option(opt)) is not None
        ]
        if not parsed:
            return None
        label, value = min(parsed, key=lambda p: abs(p[1] - desired_offset))
        return {"label": label, "value": value}

    def _read_float(self, entity_id: str) -> float | None:
        state = self.coordinator.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return _sanity_clamp_temp(float(state.state))
        except (TypeError, ValueError):
            return None

    def _read_trv_raw_temperature(self, climate_entity: str) -> float | None:
        """Return the TRV's own current_temperature reading.

        Deliberately reads the raw climate entity directly rather than via
        coordinator.get_room_current_temp() — that helper already *prefers*
        CONF_ROOM_TEMP_SENSOR, which would make truth and raw the same value
        and always compute a zero residual.

        Note this is NOT an uncalibrated value: on real Zigbee2MQTT TRVs the
        device firmware applies `local_temperature_calibration` internally
        before reporting `local_temperature`/current_temperature at all — the
        whole point of a calibration setting is to correct what the device
        itself reports and regulates against. See _async_update_room() for
        why this matters for how the offset is computed.
        """
        if not climate_entity:
            return None
        state = self.coordinator.hass.states.get(climate_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            val = state.attributes.get("current_temperature")
            return _sanity_clamp_temp(float(val)) if val is not None else None
        except (TypeError, ValueError):
            return None

    async def async_shutdown(self) -> None:
        """No listeners or timers to release — present for interface consistency
        with the other engines the coordinator shuts down."""
        return None
