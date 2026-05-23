"""
Heat Manager — Controller Engine

Top-level ON / PAUSE / OFF state machine.
All handler methods in other engines are guarded by @guarded.

FIX: async_tick no longer holds _lock while calling private methods.
     Lock is only held for the minimal critical section of reading/writing
     self._state — not for the full await chain. This prevents the lock
     being held across awaits which could block manual transitions.

v0.5.0: Outdoor temperature auto-off logic removed from ControllerEngine.
         SeasonEngine is now the single source of truth for EffectiveSeason.
         ControllerEngine only reacts to coordinator.effective_season.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.util.dt import utcnow

from ..const import (
    DEFAULT_PAUSE_DURATION_MIN,
    HVAC_OFF,
    NETATMO_API_CALL_DELAY_SEC,
    PRESET_SCHEDULE,
    AutoOffReason,
    ControllerState,
    EffectiveSeason,
    SeasonMode,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


def guarded(func: Callable) -> Callable:
    """
    Decorator for engine handler methods.
    Skips execution silently when the controller is OFF or PAUSED.
    """

    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
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
    """Manages the top-level ON / PAUSE / OFF state of Heat Manager."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._state: ControllerState = ControllerState.ON
        self._auto_off_reason: AutoOffReason = AutoOffReason.NONE
        self._pause_until: datetime | None = None
        # Lock only guards _state reads/writes, not full async chains
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
            if new_state == ControllerState.PAUSE:
                duration = self.coordinator.config.get(
                    "pause_duration_min", DEFAULT_PAUSE_DURATION_MIN
                )
                self._pause_until = utcnow() + timedelta(minutes=duration)
                _LOGGER.info("Paused for %d min until %s", duration, self._pause_until)
            elif new_state == ControllerState.ON:
                self._pause_until = None
                self._auto_off_reason = AutoOffReason.NONE
            elif new_state == ControllerState.OFF:
                self._auto_off_reason = AutoOffReason.NONE
                self._pause_until = None
            self._state = new_state

        # Run side-effects outside the lock
        if new_state == ControllerState.OFF:
            await self._apply_off_fallback()
            self._reset_room_states()

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

    # ── Periodic tick ─────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """
        Called every SCAN_INTERVAL_SECONDS by the coordinator.
        FIX: State is read once under the lock, then released before awaiting.
        This prevents the lock being held across long await chains.
        """
        async with self._lock:
            current_state = self._state

        if current_state == ControllerState.PAUSE:
            await self._check_pause_expiry()
            return

        await self._check_auto_off()
        await self._check_auto_resume()

    # ── Pause expiry ──────────────────────────────────────────────────────────

    async def _check_pause_expiry(self) -> None:
        if self._pause_until is None:
            return
        if utcnow() >= self._pause_until:
            async with self._lock:
                self._state = ControllerState.ON
                self._pause_until = None
            _LOGGER.info("Pause timer expired — resuming")
            self.coordinator.async_update_listeners()

    # ── Auto-off checks ───────────────────────────────────────────────────────

    async def _check_auto_off(self) -> None:
        """Trigger auto-off when SeasonEngine resolves to DORMANT.

        SeasonEngine is the single source of truth for effective season.
        ControllerEngine no longer tracks outdoor temperature directly.
        """
        if self._state == ControllerState.OFF:
            return
        if self.coordinator.effective_season == EffectiveSeason.DORMANT:
            _LOGGER.info("Auto-off triggered: effective_season = DORMANT")
            await self._auto_off(AutoOffReason.SEASON)

    async def _auto_off(self, reason: AutoOffReason) -> None:
        self._auto_off_reason = reason
        await self._apply_off_fallback()
        self._reset_room_states()
        async with self._lock:
            self._state = ControllerState.OFF
        self.coordinator.async_update_listeners()

    # ── Auto-resume checks ────────────────────────────────────────────────────

    async def _check_auto_resume(self) -> None:
        """Auto-resume whenever effective_season leaves DORMANT.

        This covers both calendar-driven (summer end) and temperature-driven
        (sustained warmth reversal) dormancy in a single check.
        """
        if self._state != ControllerState.OFF:
            return
        if self._auto_off_reason == AutoOffReason.NONE:
            return  # Manual OFF — never auto-resume

        if self.coordinator.effective_season != EffectiveSeason.DORMANT:
            _LOGGER.info(
                "Auto-resume: effective_season = %s",
                self.coordinator.effective_season.value,
            )
            async with self._lock:
                self._state = ControllerState.ON
                self._auto_off_reason = AutoOffReason.NONE
            self.coordinator.async_update_listeners()

    # ── Climate fallback on OFF ────────────────────────────────────────────────

    async def _apply_off_fallback(self) -> None:
        """Apply climate state when controller transitions to OFF.

        For DORMANT (summer): turn off TRVs via hvac_mode off (HomeKit preferred).
        For WAKING/ACTIVE restore: set preset_mode schedule (cloud entity required).

        H-5: HomeKit entity preferred for hvac_mode writes (local, no rate limit).
        H-6: Delay only applied when writing to Netatmo cloud entity.
        """
        season = self.coordinator.effective_season
        hass = self.coordinator.hass

        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            cloud_id = room.get("climate_entity", "")
            if not cloud_id:
                continue
            try:
                if season == EffectiveSeason.DORMANT:
                    # H-5: prefer HomeKit for local hvac_mode: off
                    write_id = self.coordinator.get_write_entity(room_name) or cloud_id
                    await hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": write_id, "hvac_mode": HVAC_OFF},
                        blocking=True,
                    )
                else:
                    # preset_mode: schedule must go to cloud — not supported via HomeKit
                    await hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": cloud_id, "preset_mode": PRESET_SCHEDULE},
                        blocking=True,
                    )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to set OFF fallback on %s: %s", cloud_id, err)
            # H-6: only delay when writing to Netatmo cloud
            if self.coordinator.needs_cloud_delay(room_name):
                await asyncio.sleep(NETATMO_API_CALL_DELAY_SEC)

    # ── Room state reset ──────────────────────────────────────────────────────

    def _reset_room_states(self) -> None:
        if hasattr(self.coordinator, "room_states"):
            self.coordinator.room_states.clear()
            _LOGGER.debug("Room states reset")
