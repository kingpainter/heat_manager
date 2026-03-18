"""
Heat Manager — Controller Engine

Top-level state machine: ON → PAUSE → OFF and back.
All other engines check this before acting via the @guarded decorator.

States
------
ON      Full logic active. All engines run normally.
PAUSE   Engines frozen. Room states preserved in memory.
        A pause_until timestamp is set; when it expires the
        controller auto-resumes to ON.
        If manually resumed, jumps directly to ON.
OFF     Permanent until manually changed.
        Room state machines are reset.
        Climate entities are set according to season:
          Winter → preset_mode: schedule  (HA timetable takes over)
          Summer → hvac_mode: off          (units fully off)

Auto-off triggers (configured in options flow)
----------------------------------------------
A. season_mode == SeasonMode.SUMMER
B. outdoor temperature > threshold for N consecutive days

Both are checked every SCAN_INTERVAL_SECONDS.
When auto-off fires, auto_off_reason is stored so the system
knows to auto-resume when conditions reverse — without asking.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from homeassistant.util.dt import utcnow

from ..const import (
    AutoOffReason,
    ControllerState,
    SeasonMode,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_PAUSE_DURATION_MIN,
    HVAC_OFF,
    PRESET_SCHEDULE,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


def guarded(func: Callable) -> Callable:
    """
    Decorator for engine handler methods.

    Skips execution when the controller is OFF or PAUSED.
    The room state is preserved during PAUSE so it can be
    restored on resume without side-effects.
    """
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        coordinator: HeatManagerCoordinator = getattr(self, "coordinator", None)
        if coordinator is None:
            return await func(self, *args, **kwargs)
        state = coordinator.controller.state
        if state == ControllerState.OFF:
            _LOGGER.debug("Guard blocked %s — controller is OFF", func.__name__)
            return
        if state == ControllerState.PAUSE:
            _LOGGER.debug("Guard blocked %s — controller is PAUSED", func.__name__)
            return
        return await func(self, *args, **kwargs)
    return wrapper


class ControllerEngine:
    """
    Manages the top-level ON / PAUSE / OFF state of Heat Manager.

    Responsibilities
    ----------------
    - Expose current state and auto_off_reason
    - Handle manual transitions (set_state, pause, resume)
    - Run the pause countdown and auto-resume
    - Poll auto-off conditions (season, outdoor temp)
    - Apply climate fallback on OFF transitions
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._state: ControllerState = ControllerState.ON
        self._auto_off_reason: AutoOffReason = AutoOffReason.NONE
        self._pause_until: datetime | None = None
        self._outdoor_temp_history: list[tuple[datetime, float]] = []
        self._lock = asyncio.Lock()

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def state(self) -> ControllerState:
        return self._state

    @property
    def auto_off_reason(self) -> AutoOffReason:
        return self._auto_off_reason

    @property
    def pause_remaining_minutes(self) -> int:
        """Minutes left in pause. 0 if not paused or timer already expired."""
        if self._state != ControllerState.PAUSE or self._pause_until is None:
            return 0
        remaining = (self._pause_until - utcnow()).total_seconds()
        return max(0, int(remaining / 60))

    # ── Manual transitions ────────────────────────────────────────────────────

    async def set_state(self, new_state: ControllerState) -> None:
        """Manual state change from UI select or service call."""
        async with self._lock:
            old_state = self._state
            if new_state == old_state:
                return

            _LOGGER.info(
                "Controller state: %s → %s (manual)", old_state.value, new_state.value
            )

            if new_state == ControllerState.OFF:
                await self._apply_off_fallback()
                self._reset_room_states()
                self._auto_off_reason = AutoOffReason.NONE
                self._pause_until = None

            elif new_state == ControllerState.PAUSE:
                duration = self.coordinator.config.get(
                    "pause_duration_min", DEFAULT_PAUSE_DURATION_MIN
                )
                self._pause_until = utcnow() + timedelta(minutes=duration)
                _LOGGER.info(
                    "Paused for %d min, until %s", duration, self._pause_until
                )

            elif new_state == ControllerState.ON:
                self._pause_until = None
                # If resuming from auto-off, clear the reason
                self._auto_off_reason = AutoOffReason.NONE

            self._state = new_state
            self.coordinator.async_update_listeners()

    async def pause(self, duration_minutes: int = DEFAULT_PAUSE_DURATION_MIN) -> None:
        """Service call: pause for a specific duration."""
        async with self._lock:
            self._pause_until = utcnow() + timedelta(minutes=duration_minutes)
            self._state = ControllerState.PAUSE
            _LOGGER.info("Paused for %d minutes", duration_minutes)
            self.coordinator.async_update_listeners()

    async def resume(self) -> None:
        """Service call: resume from pause back to ON."""
        async with self._lock:
            if self._state != ControllerState.PAUSE:
                return
            self._state = ControllerState.ON
            self._pause_until = None
            _LOGGER.info("Resumed from pause")
            self.coordinator.async_update_listeners()

    # ── Periodic tick (called by coordinator every SCAN_INTERVAL_SECONDS) ────

    async def async_tick(self) -> None:
        """
        Called on every coordinator refresh.
        Handles:
          1. Pause timer expiry → auto-resume
          2. Auto-off condition checks (season + temp)
          3. Auto-on when conditions reverse after auto-off
        """
        async with self._lock:
            if self._state == ControllerState.PAUSE:
                await self._check_pause_expiry()
                return  # Don't run auto-off checks while paused

            await self._check_auto_off()
            await self._check_auto_resume()

    # ── Pause expiry ──────────────────────────────────────────────────────────

    async def _check_pause_expiry(self) -> None:
        if self._pause_until and utcnow() >= self._pause_until:
            _LOGGER.info("Pause timer expired — resuming")
            self._state = ControllerState.ON
            self._pause_until = None
            self.coordinator.async_update_listeners()

    # ── Auto-off checks ───────────────────────────────────────────────────────

    async def _check_auto_off(self) -> None:
        """Fire auto-off if season or temperature conditions are met."""
        if self._state == ControllerState.OFF:
            return

        # Condition A: season_mode set to SUMMER
        if self.coordinator.season_mode == SeasonMode.SUMMER:
            _LOGGER.info("Auto-off triggered: season = SUMMER")
            await self._auto_off(AutoOffReason.SEASON)
            return

        # Condition B: outdoor temp above threshold for N days
        if await self._outdoor_temp_sustained_high():
            _LOGGER.info("Auto-off triggered: outdoor temp sustained high")
            await self._auto_off(AutoOffReason.TEMPERATURE)

    async def _auto_off(self, reason: AutoOffReason) -> None:
        """Apply OFF with a recorded reason — does not reset auto_off_reason to NONE."""
        self._auto_off_reason = reason
        await self._apply_off_fallback()
        self._reset_room_states()
        self._state = ControllerState.OFF
        self.coordinator.async_update_listeners()

    # ── Auto-resume checks ────────────────────────────────────────────────────

    async def _check_auto_resume(self) -> None:
        """
        If controller was auto-OFF, check if the triggering condition
        has reversed. If so, automatically resume to ON.
        Only runs when state is OFF and auto_off_reason is not NONE.
        """
        if self._state != ControllerState.OFF:
            return
        if self._auto_off_reason == AutoOffReason.NONE:
            return  # Manual OFF — never auto-resume

        if self._auto_off_reason == AutoOffReason.SEASON:
            if self.coordinator.season_mode != SeasonMode.SUMMER:
                _LOGGER.info("Auto-resume: season no longer SUMMER")
                await self._do_auto_resume()

        elif self._auto_off_reason == AutoOffReason.TEMPERATURE:
            if not await self._outdoor_temp_sustained_high():
                _LOGGER.info("Auto-resume: outdoor temp dropped below threshold")
                await self._do_auto_resume()

    async def _do_auto_resume(self) -> None:
        self._state = ControllerState.ON
        self._auto_off_reason = AutoOffReason.NONE
        self.coordinator.async_update_listeners()

    # ── Outdoor temperature tracking ──────────────────────────────────────────

    async def _outdoor_temp_sustained_high(self) -> bool:
        """
        Returns True if the outdoor temperature has been above the configured
        threshold for the configured number of consecutive days.
        Uses a rolling list of (timestamp, temp) readings.
        """
        threshold = self.coordinator.config.get(
            "auto_off_temp_threshold", DEFAULT_AUTO_OFF_TEMP_THRESHOLD
        )
        days_required = self.coordinator.config.get(
            "auto_off_temp_days", DEFAULT_AUTO_OFF_TEMP_DAYS
        )

        current_temp = self.coordinator.outdoor_temperature
        if current_temp is None:
            return False

        now = utcnow()
        self._outdoor_temp_history.append((now, current_temp))

        # Trim history older than days_required + 1 day buffer
        cutoff = now - timedelta(days=days_required + 1)
        self._outdoor_temp_history = [
            (ts, t) for ts, t in self._outdoor_temp_history if ts >= cutoff
        ]

        window_start = now - timedelta(days=days_required)
        window_readings = [
            t for ts, t in self._outdoor_temp_history if ts >= window_start
        ]

        if len(window_readings) < days_required:
            return False

        return all(t > threshold for t in window_readings)

    # ── Climate fallback on OFF ────────────────────────────────────────────────

    async def _apply_off_fallback(self) -> None:
        """
        Set all climate entities to the appropriate fallback based on season.
          Winter → preset_mode: schedule
          Summer → hvac_mode: off
        """
        season = self.coordinator.season_mode
        hass = self.coordinator.hass

        for room in self.coordinator.rooms:
            entity_id = room["climate_entity"]
            try:
                if season == SeasonMode.SUMMER:
                    await hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": HVAC_OFF},
                        blocking=True,
                    )
                    _LOGGER.debug("OFF fallback: %s → hvac_mode off", entity_id)
                else:
                    await hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": entity_id, "preset_mode": PRESET_SCHEDULE},
                        blocking=True,
                    )
                    _LOGGER.debug("OFF fallback: %s → preset schedule", entity_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to set fallback on %s: %s", entity_id, err)

    # ── Room state reset ──────────────────────────────────────────────────────

    def _reset_room_states(self) -> None:
        """Clear all frozen room states when going to OFF."""
        if hasattr(self.coordinator, "room_states"):
            self.coordinator.room_states.clear()
            _LOGGER.debug("Room states reset")
