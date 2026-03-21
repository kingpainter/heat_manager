"""
Heat Manager — Season Engine (Phase 3)

Automatically resolves SeasonMode.AUTO to effective WINTER or SUMMER
based on outdoor temperature from the weather entity.

Logic
-----
- If season_mode is manually set to WINTER or SUMMER → no-op (user overrides)
- If season_mode is AUTO:
    outdoor temp > auto_off_temp_threshold for N consecutive days → SUMMER
    outdoor temp ≤ threshold → WINTER
    No weather entity configured → stays WINTER (safe fallback)

Called on every coordinator tick (60 s).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..const import (
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    SeasonMode,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class SeasonEngine:
    """
    Resolves AUTO season mode to WINTER or SUMMER each tick.

    Does not own any listeners — purely reactive to coordinator state.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._days_above: int = 0      # consecutive days outdoor temp above threshold
        self._last_date: str | None = None  # ISO date of last tick, for day-counting

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by the coordinator."""
        if self.coordinator.season_mode != SeasonMode.AUTO:
            # Manual override — do nothing
            return

        outdoor = self.coordinator.outdoor_temperature
        if outdoor is None:
            # No weather data — default to WINTER (safe: keeps heating on)
            if self.coordinator.season_mode != SeasonMode.AUTO:
                return
            return

        threshold   = float(self.coordinator.config.get(CONF_AUTO_OFF_TEMP_THRESHOLD, DEFAULT_AUTO_OFF_TEMP_THRESHOLD))
        days_needed = int(self.coordinator.config.get(CONF_AUTO_OFF_TEMP_DAYS, DEFAULT_AUTO_OFF_TEMP_DAYS))

        # Day-level tracking: increment counter once per calendar day
        from homeassistant.util.dt import now as ha_now
        today = ha_now().date().isoformat()

        if today != self._last_date:
            self._last_date = today
            if outdoor > threshold:
                self._days_above += 1
                _LOGGER.debug(
                    "SeasonEngine: %.1f°C > %.1f°C threshold — day %d/%d above",
                    outdoor, threshold, self._days_above, days_needed,
                )
            else:
                if self._days_above > 0:
                    _LOGGER.debug(
                        "SeasonEngine: %.1f°C ≤ threshold — resetting counter (was %d)",
                        outdoor, self._days_above,
                    )
                self._days_above = 0

        effective = SeasonMode.SUMMER if self._days_above >= days_needed else SeasonMode.WINTER
        self.coordinator.effective_season = effective

    @property
    def days_above_threshold(self) -> int:
        return self._days_above

    async def async_shutdown(self) -> None:
        _LOGGER.debug("SeasonEngine shut down")
