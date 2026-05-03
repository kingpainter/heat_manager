"""
Heat Manager — Valve Protection Engine  (F4)

Purpose
-------
Prevents TRV valve calcification by exercising every valve once per week
during a configurable night-time window.  When radiators sit idle for months
(typically the entire heating off-season) mineral deposits can cause valves
to seize.  A brief open/close pulse keeps the mechanism free.

Behaviour
---------
- Runs a check every coordinator tick (60 s).
- Fires at most once per calendar week, within the configured night window
  (default 02:00–03:00 local time).
- Only activates when the controller is OFF (summer / manual off) — if the
  heating is ON there is no risk of calcification.
- For each room: sends set_temperature to a low "exercise" setpoint, waits
  EXERCISE_DURATION_SEC, then restores the previous setpoint.
- Uses the HomeKit entity if available (local, fast), falls back to the
  cloud climate entity.
- Logs every exercise cycle to the coordinator event log.
- A notification is sent after the full sweep (optional, uses same
  notify_service as other engines).

Constants
---------
EXERCISE_SETPOINT_C   : temperature sent during pulse (default 28 °C — open valve fully)
EXERCISE_DURATION_SEC : how long to hold the open setpoint  (default 30 s)
EXERCISE_NIGHT_START  : hour to begin the sweep (default 2 — 02:00 local)
EXERCISE_NIGHT_END    : hour to end   the sweep (default 3 — 03:00 local)
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.util.dt import now as ha_now

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_NOTIFY_SERVICE,
    CONF_TRV_TYPE,
    ControllerState,
    NETATMO_API_CALL_DELAY_SEC,
    TRV_TYPE_ZIGBEE,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
EXERCISE_SETPOINT_C: float = 28.0   # °C — fully open valve
EXERCISE_DURATION_SEC: int = 30     # seconds to hold before restoring
EXERCISE_NIGHT_START: int  = 2      # 02:00 local time
EXERCISE_NIGHT_END:   int  = 3      # 03:00 local time


class ValveProtectionEngine:
    """
    Exercises TRV valves once per week during a quiet night-time window to
    prevent calcification during the off-season.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._last_exercise_week: int | None = None   # ISO week number
        self._running: bool = False

    # ── Tick ──────────────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by the coordinator."""
        if self._running:
            return

        # Only exercise when heating is OFF (summer / manual off)
        if self.coordinator.controller.state != ControllerState.OFF:
            return

        now = ha_now()

        # Only within the night window
        if not (EXERCISE_NIGHT_START <= now.hour < EXERCISE_NIGHT_END):
            return

        # Only once per ISO calendar week
        current_week = now.isocalendar()[1]
        if current_week == self._last_exercise_week:
            return

        _LOGGER.info(
            "ValveProtectionEngine: starting weekly valve exercise (week %d)",
            current_week,
        )
        self._last_exercise_week = current_week
        self._running = True
        try:
            await self._exercise_all_valves()
        finally:
            self._running = False

    # ── Exercise sweep ────────────────────────────────────────────────────────

    async def _exercise_all_valves(self) -> None:
        hass = self.coordinator.hass
        rooms_done: list[str] = []

        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not room_name or not climate_id:
                continue

            # Prefer HomeKit entity (local, <100 ms) over cloud entity
            hk_id = room.get(CONF_HOMEKIT_CLIMATE_ENTITY) or None
            write_entity = hk_id if hk_id else climate_id

            # Read current setpoint before exercising so we can restore it
            state = hass.states.get(write_entity)
            if state is None or state.state in ("unavailable", "unknown"):
                _LOGGER.debug(
                    "ValveProtectionEngine: skipping %s — entity unavailable", room_name
                )
                continue

            original_setpoint = state.attributes.get("temperature")
            if original_setpoint is None:
                _LOGGER.debug(
                    "ValveProtectionEngine: skipping %s — no temperature attribute",
                    room_name,
                )
                continue

            try:
                original_setpoint = float(original_setpoint)
            except (TypeError, ValueError):
                continue

            trv_type = room.get(CONF_TRV_TYPE, "netatmo")

            try:
                # Step 1: open valve to exercise setpoint
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": write_entity, "temperature": EXERCISE_SETPOINT_C},
                    blocking=True,
                )
                _LOGGER.debug(
                    "ValveProtectionEngine: %s → %.0f°C (exercise open)",
                    room_name, EXERCISE_SETPOINT_C,
                )

                # Hold for exercise duration
                await asyncio.sleep(EXERCISE_DURATION_SEC)

                # Step 2: restore original setpoint
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": write_entity, "temperature": original_setpoint},
                    blocking=True,
                )
                _LOGGER.debug(
                    "ValveProtectionEngine: %s → %.1f°C (restored)",
                    room_name, original_setpoint,
                )

                rooms_done.append(room_name)

            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "ValveProtectionEngine: exercise failed for %s: %s",
                    room_name, err,
                )

            # Stagger calls for Netatmo rooms
            if trv_type != TRV_TYPE_ZIGBEE:
                await asyncio.sleep(NETATMO_API_CALL_DELAY_SEC)

        if rooms_done:
            rooms_str = ", ".join(rooms_done)
            self.coordinator.log_event(
                f"Valve exercise completed — {rooms_str}",
                "Valve protection",
                "normal",
            )
            _LOGGER.info(
                "ValveProtectionEngine: exercise complete for %d room(s): %s",
                len(rooms_done), rooms_str,
            )
            await self._notify(
                f"Ventilbeskyttelse: {len(rooms_done)} rum gennemkørt ({rooms_str})"
            )
        else:
            _LOGGER.info("ValveProtectionEngine: no rooms exercised this week")

    # ── Notification ──────────────────────────────────────────────────────────

    async def _notify(self, message: str) -> None:
        service = self.coordinator.config.get(CONF_NOTIFY_SERVICE, "")
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not service_name:
            return
        try:
            await self.coordinator.hass.services.async_call(
                domain, service_name,
                {"message": message, "title": "Heat Manager"},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("ValveProtectionEngine notification failed: %s", err)

    async def async_shutdown(self) -> None:
        _LOGGER.debug("ValveProtectionEngine shut down")
