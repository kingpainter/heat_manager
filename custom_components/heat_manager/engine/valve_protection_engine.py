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
- Prefers the HomeKit entity (local, fast); falls back to cloud climate entity.
- Logs every exercise cycle to the coordinator event log.
- Sends a notification after the full sweep (optional, uses notify_service).

Constants
---------
EXERCISE_SETPOINT_C   : temperature sent during pulse (28 °C — fully opens valve)
EXERCISE_DURATION_SEC : how long to hold the open setpoint (30 s)
EXERCISE_NIGHT_START  : hour to begin the sweep (2 — 02:00 local)
EXERCISE_NIGHT_END    : hour to end   the sweep (3 — 03:00 local)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from homeassistant.util.dt import now as ha_now

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_NOTIFY_SERVICE,
    ControllerState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
EXERCISE_SETPOINT_C: float = 28.0  # °C — fully open valve
EXERCISE_DURATION_SEC: int = 30  # seconds to hold before restoring
EXERCISE_NIGHT_START: int = 2  # 02:00 local time
EXERCISE_NIGHT_END: int = 3  # 03:00 local time


class ValveProtectionEngine:
    """
    Exercises TRV valves once per week during a quiet night-time window to
    prevent calcification during the off-season.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._last_exercise_week: int | None = None  # ISO week number
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None

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
        # 3.3 hardening: fire-and-forget rather than awaiting the sweep
        # directly — with N TRVs each held open for EXERCISE_DURATION_SEC
        # plus a stagger delay, an inline await here blocked the
        # coordinator's entire 60 s tick cycle for several minutes, once a
        # week. Running it as its own background task keeps the tick loop
        # (and every other room's PID/window/presence logic) responsive
        # while the sweep proceeds.
        self._task = self.coordinator.hass.async_create_task(
            self._run_exercise_sweep(),
            name="heat_manager_valve_exercise",
        )

    async def _run_exercise_sweep(self) -> None:
        """Background wrapper around _exercise_all_valves() — see async_tick()."""
        try:
            await self._exercise_all_valves()
        # broad-except-rationale: this runs detached from the coordinator's
        # tick loop, so a failure here would otherwise become an unlogged
        # unhandled task exception instead of a warning — next week's tick
        # simply tries again.
        except Exception:  # noqa: BLE001
            _LOGGER.exception("ValveProtectionEngine: exercise sweep failed")
        finally:
            self._running = False
            self._task = None

    # ── Exercise sweep ────────────────────────────────────────────────────────

    async def _exercise_all_valves(self) -> None:
        """B18: every physical TRV in a room is exercised individually,
        each preferring its own HomeKit entity (configured-if-present, no
        reachability check — matches this method's pre-existing single-TRV
        policy exactly) and staggered per its own trv_type.
        """
        hass = self.coordinator.hass
        rooms_done: list[str] = []

        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue

            for trv in self.coordinator.get_room_trvs(room_name):
                climate_id = trv.get(CONF_CLIMATE_ENTITY, "")
                if not climate_id:
                    continue

                # Prefer HomeKit entity (local, <100 ms) over cloud entity
                hk_id = trv.get(CONF_HOMEKIT_CLIMATE_ENTITY) or None
                write_entity = hk_id if hk_id else climate_id

                # Read current setpoint before exercising so we can restore it
                state = hass.states.get(write_entity)
                if state is None or state.state in ("unavailable", "unknown"):
                    _LOGGER.debug(
                        "ValveProtectionEngine: skipping %s (%s) — entity unavailable",
                        room_name,
                        write_entity,
                    )
                    continue

                original_setpoint = state.attributes.get("temperature")
                if original_setpoint is None:
                    _LOGGER.debug(
                        "ValveProtectionEngine: skipping %s (%s) — no temperature attribute",
                        room_name,
                        write_entity,
                    )
                    continue

                try:
                    original_setpoint = float(original_setpoint)
                except (TypeError, ValueError):
                    continue

                # 2026-09 fix: pace/lock by whether write_entity actually
                # IS the cloud entity, not by the configured trv_type — the
                # old `trv_type != TRV_TYPE_ZIGBEE` check would add the
                # delay even when write_entity above already resolved to a
                # reachable HomeKit id, needlessly holding the shared
                # Netatmo lock for a call that never touches Netatmo.
                needs_delay = write_entity == climate_id

                try:
                    # Step 1: open valve to exercise setpoint
                    await self.coordinator.async_call_climate_service(
                        "set_temperature",
                        write_entity,
                        {"temperature": EXERCISE_SETPOINT_C},
                        needs_delay=needs_delay,
                    )
                    _LOGGER.debug(
                        "ValveProtectionEngine: %s (%s) → %.0f°C (exercise open)",
                        room_name,
                        write_entity,
                        EXERCISE_SETPOINT_C,
                    )

                    # Hold for exercise duration
                    await asyncio.sleep(EXERCISE_DURATION_SEC)

                    # Step 2: restore original setpoint
                    await self.coordinator.async_call_climate_service(
                        "set_temperature",
                        write_entity,
                        {"temperature": original_setpoint},
                        needs_delay=needs_delay,
                    )
                    _LOGGER.debug(
                        "ValveProtectionEngine: %s (%s) → %.1f°C (restored)",
                        room_name,
                        write_entity,
                        original_setpoint,
                    )

                    if room_name not in rooms_done:
                        rooms_done.append(room_name)

                # broad-except-rationale: one entity failing must not abort the others in this loop
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "ValveProtectionEngine: exercise failed for %s (%s): %s",
                        room_name,
                        write_entity,
                        err,
                    )

        if rooms_done:
            rooms_str = ", ".join(rooms_done)
            self.coordinator.log_event(
                f"Valve exercise completed — {rooms_str}",
                "Valve protection",
                "normal",
            )
            _LOGGER.info(
                "ValveProtectionEngine: exercise complete for %d room(s): %s",
                len(rooms_done),
                rooms_str,
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
                domain,
                service_name,
                {"message": message, "title": "Heat Manager"},
                blocking=True,
            )
        # broad-except-rationale: one entity failing must not abort the others in this loop
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("ValveProtectionEngine notification failed: %s", err)

    async def async_shutdown(self) -> None:
        """Cancel and await the in-flight exercise sweep, if any.

        2026-09 audit fix: cancel() alone schedules cancellation but never
        waits for it — the task's cancellation could still be delivered and
        run its except/finally blocks (touching self.coordinator.hass,
        climate entities, etc.) after async_unload_entry() had already torn
        the rest of the integration down. Awaiting it here, with
        CancelledError suppressed, ensures the task has actually stopped
        before shutdown returns.
        """
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        _LOGGER.debug("ValveProtectionEngine shut down")
