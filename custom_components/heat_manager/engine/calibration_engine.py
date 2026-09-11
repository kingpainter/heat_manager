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

Heat-up-rate learning (2026-09-11, door feature point 1+2 level B)
-------------------------------------------------------------------
Separate from the sensor-offset writer above, this engine also learns how
fast each room's temperature actually rises while heating is genuinely
being called for — split into two running averages per room, one for
"interior door open" and one for "door closed" (see coordinator.
is_room_door_open()). This is a DIFFERENT thing from the offset above: the
offset corrects a TRV's raw thermometer reading (a constant hardware
property, independent of door state); this instead tracks the room's
thermal RESPONSE, which the physics genuinely does depend on — Flemming's
own observation that a room with its door shut heats up faster than one
with the door open. Purely observational for now: nothing reads these
learned rates yet to change any control decision (level C — using them to
actively adjust a neighbouring room's target — is a separate, larger,
not-yet-approved step). Learned rates live in memory only and reset on
restart, same as the offset-writer's own state above.
"""

from __future__ import annotations

import logging
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
_HEATUP_EMA_ALPHA = 0.15


def _sanity_clamp_temp(value: float) -> float | None:
    """Return `value` unchanged if plausible for an indoor temp, else None."""
    if _ROOM_TEMP_SANITY_MIN <= value <= _ROOM_TEMP_SANITY_MAX:
        return value
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
        # Learned EMA in °C/hour, keyed by (room_name, door_open).
        self._heatup_rate_ema: dict[tuple[str, bool], float] = {}

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

        if is_actively_heating and delta_temp > 0.05:
            rate_per_hour = delta_temp / elapsed * 3600
            if abs(rate_per_hour) <= _HEATUP_RATE_SANITY_MAX:
                key = (room_name, baseline_door_open)
                previous = self._heatup_rate_ema.get(key)
                self._heatup_rate_ema[key] = (
                    rate_per_hour
                    if previous is None
                    else previous + _HEATUP_EMA_ALPHA * (rate_per_hour - previous)
                )
                _LOGGER.debug(
                    "Heat-up rate [%s, door_open=%s]: sample=%.2f°C/h → ema=%.2f°C/h",
                    room_name,
                    baseline_door_open,
                    rate_per_hour,
                    self._heatup_rate_ema[key],
                )

        self._heatup_reset_baseline(room_name, current_temp, now)

    def _heatup_reset_baseline(self, room_name: str, temp: float, at: datetime) -> None:
        self._heatup_baseline_temp[room_name] = temp
        self._heatup_baseline_time[room_name] = at
        self._heatup_baseline_door_open[room_name] = self.coordinator.is_room_door_open(
            room_name
        )

    def get_room_heatup_rate(self, room_name: str, door_open: bool) -> float | None:
        """Learned heat-up rate for this room (°C/hour) with the door in the
        given state, or None if not enough data has been observed yet."""
        return self._heatup_rate_ema.get((room_name, door_open))

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
        current_offset = self._read_float(calibration_entity)
        if current_offset is None:
            current_offset = 0.0
        offset = max(
            CALIBRATION_OFFSET_MIN,
            min(CALIBRATION_OFFSET_MAX, current_offset + (truth - raw)),
        )

        last_value = self._last_written.get(room_name)
        last_time = self._last_write_time.get(room_name)
        now = utcnow()

        needs_heartbeat = last_time is None or (
            now - last_time >= timedelta(minutes=DEFAULT_CALIBRATION_HEARTBEAT_MIN)
        )
        needs_change_write = (
            last_value is None
            or abs(offset - last_value) >= CALIBRATION_CHANGE_THRESHOLD
        )

        if not needs_heartbeat and not needs_change_write:
            return

        try:
            await self.coordinator.hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": calibration_entity, "value": round(offset, 1)},
                blocking=True,
            )
            self._last_written[room_name] = offset
            self._last_write_time[room_name] = now
            _LOGGER.debug(
                "Calibration [%s]: truth=%.1f°C raw=%.1f°C → offset=%.1f°C written to %s"
                " (%s)",
                room_name,
                truth,
                raw,
                offset,
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
