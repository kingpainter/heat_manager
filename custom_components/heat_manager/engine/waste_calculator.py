"""
Heat Manager — Waste Calculator Engine (Phase 3)

Replaces the tick-accumulator placeholder in sensor.py with a proper
per-room energy waste estimate based on:

  - climate entity's current_temperature and target temperature
  - duration the room has been in WINDOW_OPEN state
  - a configurable per-room wattage estimate (default: 1000 W)

Formula per room:
  waste_kWh = Δtemp × duration_hours × efficiency_factor

Where:
  Δtemp            = target_setpoint - current_temp (°C) when window is open
  duration_hours   = seconds in WINDOW_OPEN / 3600
  efficiency_factor = assumed 0.1 kWh/°C/hour (typical radiator panel)

The engine accumulates values each coordinator tick and resets at midnight.
Results are exposed via coordinator.energy_wasted_today and
coordinator.energy_saved_today (away mode savings vs baseline).

Called on every coordinator tick.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from homeassistant.util.dt import now as ha_now

from ..const import (
    CONF_CLIMATE_ENTITY,
    RoomState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# kWh saved or wasted per °C per hour — approximate for a typical panel radiator
_KWH_PER_DEGC_PER_HOUR: float = 0.1

# Baseline heating hours per day (used for "saved" calculation)
_BASELINE_HOURS_PER_DAY: float = 8.0


class WasteCalculator:
    """
    Tracks per-room energy waste and savings, resets at midnight.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._today: date = ha_now().date()
        self._wasted_kwh: float = 0.0
        self._saved_kwh: float = 0.0
        # Track how long each room has been in WINDOW_OPEN this tick
        self._window_seconds: dict[str, float] = {}

    # ── Public read-only properties ───────────────────────────────────────────

    @property
    def energy_wasted_today(self) -> float:
        return round(self._wasted_kwh, 3)

    @property
    def energy_saved_today(self) -> float:
        return round(self._saved_kwh, 3)

    @property
    def efficiency_score(self) -> int:
        """
        Score 0–100.
        Starts at 100, loses 10 points per 0.1 kWh wasted, floor 0.
        Gains are not reflected (score can only decrease on waste).
        """
        return max(0, min(100, 100 - int(self._wasted_kwh * 100)))

    # ── Tick ──────────────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by coordinator."""
        today = ha_now().date()

        # Midnight reset
        if today != self._today:
            self._today          = today
            self._wasted_kwh     = 0.0
            self._saved_kwh      = 0.0
            self._window_seconds = {}
            _LOGGER.debug("WasteCalculator: reset for new day %s", today)

        tick_hours = 60.0 / 3600.0  # coordinator ticks every 60 s

        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not room_name or not climate_id:
                continue

            room_state = self.coordinator.get_room_state(room_name)

            # ── Energy wasted (window open) ───────────────────────────────────
            if room_state == RoomState.WINDOW_OPEN:
                delta = self._temp_delta(climate_id)
                if delta > 0:
                    waste = delta * tick_hours * _KWH_PER_DEGC_PER_HOUR
                    self._wasted_kwh += waste
                    _LOGGER.debug(
                        "Waste +%.4f kWh — %s Δtemp=%.1f°C",
                        waste, room_name, delta,
                    )

            # ── Energy saved (away mode during expected heating hours) ─────────
            if room_state == RoomState.AWAY:
                hour = ha_now().hour
                # Only count savings during typical heating hours (6–23)
                if 6 <= hour < 23:
                    baseline_delta = self._baseline_delta(climate_id)
                    if baseline_delta > 0:
                        saved = baseline_delta * tick_hours * _KWH_PER_DEGC_PER_HOUR
                        self._saved_kwh += saved

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _temp_delta(self, climate_id: str) -> float:
        """
        Δtemp = setpoint - current_temp when window is open.
        Positive means the room is trying to heat despite the open window.
        """
        state = self.coordinator.hass.states.get(climate_id)
        if not state:
            return 0.0
        setpoint = state.attributes.get("temperature")
        current  = state.attributes.get("current_temperature")
        if setpoint is None or current is None:
            return 0.0
        try:
            delta = float(setpoint) - float(current)
            return max(0.0, delta)
        except (TypeError, ValueError):
            return 0.0

    def _baseline_delta(self, climate_id: str) -> float:
        """
        Expected Δtemp if the room were at normal schedule.
        Uses (21°C baseline - current outdoor temp) as a proxy.
        """
        outdoor = self.coordinator.outdoor_temperature
        if outdoor is None:
            return 0.0
        delta = 21.0 - outdoor
        return max(0.0, delta)

    async def async_shutdown(self) -> None:
        _LOGGER.debug("WasteCalculator shut down")
