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
    CONF_CALIBRATION_ENTITY,
    CONF_ROOM_TEMP_SENSOR,
    DEFAULT_CALIBRATION_HEARTBEAT_MIN,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class CalibrationEngine:
    """Per-room TRV calibration offset writer with a timeout-guarding heartbeat."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._last_written: dict[str, float] = {}
        self._last_write_time: dict[str, datetime] = {}

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS from the coordinator's main tick."""
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            calibration_entity = room.get(CONF_CALIBRATION_ENTITY) or None
            room_temp_sensor = room.get(CONF_ROOM_TEMP_SENSOR) or None
            climate_entity = room.get("climate_entity", "")
            if not room_name or not calibration_entity or not room_temp_sensor:
                continue
            await self._async_update_room(
                room_name, climate_entity, room_temp_sensor, calibration_entity
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

        offset = max(CALIBRATION_OFFSET_MIN, min(CALIBRATION_OFFSET_MAX, truth - raw))

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
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _read_trv_raw_temperature(self, climate_entity: str) -> float | None:
        """Return the TRV's own, uncorrected current_temperature reading.

        Deliberately reads the raw climate entity directly rather than via
        coordinator.get_room_current_temp() — that helper already *prefers*
        CONF_ROOM_TEMP_SENSOR, which would make truth and raw the same value
        and always compute a zero offset.
        """
        if not climate_entity:
            return None
        state = self.coordinator.hass.states.get(climate_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            val = state.attributes.get("current_temperature")
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    async def async_shutdown(self) -> None:
        """No listeners or timers to release — present for interface consistency
        with the other engines the coordinator shuts down."""
        return None
