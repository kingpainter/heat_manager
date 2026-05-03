"""
Heat Manager — Controller Engine

Top-level ON / PAUSE / OFF state machine.
All handler methods in other engines are guarded by @guarded.

FIX: async_tick no longer holds _lock while calling private methods.
     Lock is only held for the minimal critical section of reading/writing
     self._state — not for the full await chain. This prevents the lock
     being held across awaits which could block manual transitions.
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
    NETATMO_API_CALL_DELAY_SEC,
    PRESET_SCHEDULE,
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
        # S-1 FIX: day-counter instead of raw timestamp list — survives HA restart
        self._days_above_high: int = 0
        self._last_high_date: str | None = None
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
            _LOGGER.info("Controller state: %s → %s (manual)", old_state.value, new_state.value)
            if new_state == ControllerState.PAUSE:
                duration = self.coordinator.config.get("pause_duration_min", DEFAULT_PAUSE_DURATION_MIN)
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
        if self._state == ControllerState.OFF:
            return
        if self.coordinator.season_mode == SeasonMode.SUMMER:
            _LOGGER.info("Auto-off triggered: season = SUMMER")
            await self._auto_off(AutoOffReason.SEASON)
            return
        if await self._outdoor_temp_sustained_high():
            _LOGGER.info("Auto-off triggered: outdoor temp sustained high")
            await self._auto_off(AutoOffReason.TEMPERATURE)

    async def _auto_off(self, reason: AutoOffReason) -> None:
        self._auto_off_reason = reason
        await self._apply_off_fallback()
        self._reset_room_states()
        async with self._lock:
            self._state = ControllerState.OFF
        self.coordinator.async_update_listeners()

    # ── Auto-resume checks ────────────────────────────────────────────────────

    async def _check_auto_resume(self) -> None:
        if self._state != ControllerState.OFF:
            return
        if self._auto_off_reason == AutoOffReason.NONE:
            return  # Manual OFF — never auto-resume

        should_resume = False
        if self._auto_off_reason == AutoOffReason.SEASON:
            should_resume = self.coordinator.season_mode != SeasonMode.SUMMER
        elif self._auto_off_reason == AutoOffReason.TEMPERATURE:
            should_resume = not await self._outdoor_temp_sustained_high()

        if should_resume:
            _LOGGER.info("Auto-resume: condition reversed")
            async with self._lock:
                self._state = ControllerState.ON
                self._auto_off_reason = AutoOffReason.NONE
            self.coordinator.async_update_listeners()

    # ── Outdoor temperature tracking ──────────────────────────────────────────

    async def _outdoor_temp_sustained_high(self) -> bool:
        """S-1 FIX: Use a per-day counter instead of a raw timestamp list.

        The old list was lost on every HA restart, resetting the N-day clock.
        This counter increments once per calendar day. On restart the counter
        begins at 0 again — correct safe default: we need N days of confirmed
        high temp, not partial evidence from before the restart.
        """
        threshold     = float(self.coordinator.config.get(
            "auto_off_temp_threshold", DEFAULT_AUTO_OFF_TEMP_THRESHOLD
        ))
        days_required = int(self.coordinator.config.get(
            "auto_off_temp_days", DEFAULT_AUTO_OFF_TEMP_DAYS
        ))

        current_temp = self.coordinator.outdoor_temperature
        if current_temp is None:
            return False

        today = utcnow().date().isoformat()
        if today != self._last_high_date:
            self._last_high_date = today
            if current_temp > threshold:
                self._days_above_high += 1
                _LOGGER.debug(
                    "ControllerEngine: %.1f°C > %.1f°C — day %d/%d above threshold",
                    current_temp, threshold, self._days_above_high, days_required,
                )
            else:
                if self._days_above_high > 0:
                    _LOGGER.debug(
                        "ControllerEngine: %.1f°C ≤ threshold — resetting counter (was %d)",
                        current_temp, self._days_above_high,
                    )
                self._days_above_high = 0

        return self._days_above_high >= days_required

    # ── Climate fallback on OFF ────────────────────────────────────────────────

    async def _apply_off_fallback(self) -> None:
        """S-5 FIX: Use effective_season (not season_mode) so AUTO resolves correctly.

        H-5: For SUMMER (hvac_mode: off) we prefer the HomeKit entity — it is
        a local set_hvac_mode call that does not touch Netatmo's cloud schedule.
        For WINTER restore (preset_mode: schedule) we must use the cloud entity
        because preset_mode is not exposed via HomeKit HAP.
        H-6: Delay is only applied when writing to the cloud entity.
        """
        season = self.coordinator.effective_season
        hass = self.coordinator.hass

        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            cloud_id   = room.get("climate_entity", "")
            if not cloud_id:
                continue
            try:
                if season == SeasonMode.SUMMER:
                    # H-5: prefer HomeKit for local hvac_mode: off
                    write_id = self.coordinator.get_write_entity(room_name) or cloud_id
                    await hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": write_id, "hvac_mode": HVAC_OFF},
                        blocking=True,
                    )
                else:
                    # preset_mode: schedule must go to cloud — not supported via HomeKit
                    await hass.services.async_call(
                        "climate", "set_preset_mode",
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
