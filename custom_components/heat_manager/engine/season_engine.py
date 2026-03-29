"""
Heat Manager — Season Engine

Resolves SeasonMode.AUTO to an effective heating season each tick.

Calendar + temperature logic
-----------------------------
When season_mode is AUTO the engine applies a two-layer decision:

  1. Calendar season (meteorological, internationally standard):
       Spring : 1 Mar – 31 May
       Summer : 1 Jun – 31 Aug
       Autumn : 1 Sep – 30 Nov
       Winter : 1 Dec – 28/29 Feb

  2. Temperature guard — keeps heating ON in the transitional seasons
     (spring / autumn) as long as it is still cold:
       If calendar is SPRING or AUTUMN:
         outdoor temp > threshold for N consecutive days → SUMMER (heating off)
         else → WINTER (heating on)
       If calendar is SUMMER → always SUMMER (heating off)
       If calendar is WINTER → always WINTER (heating on)

Manual overrides (WINTER / SPRING / SUMMER / AUTUMN) bypass all logic.

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
    METEO_SEASONS,
    SeasonMode,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


def _calendar_season() -> SeasonMode:
    """Return the meteorological season for today's date."""
    from homeassistant.util.dt import now as ha_now
    today = ha_now().date()
    month, day = today.month, today.day
    for m, d, season in METEO_SEASONS:
        if (month, day) >= (m, d):
            return season
    # Fallback: Jan/Feb → still Winter (loop didn't match Dec 1 going backwards)
    return SeasonMode.WINTER


class SeasonEngine:
    """
    Resolves AUTO season mode to an effective season each tick.

    effective_season drives whether heating is allowed:
      WINTER / SPRING / AUTUMN  → ControllerEngine may heat
      SUMMER                    → ControllerEngine turns off
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._days_above: int = 0
        self._last_date: str | None = None

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by the coordinator."""
        if self.coordinator.season_mode != SeasonMode.AUTO:
            # Manual override — propagate it directly as effective season
            self.coordinator.effective_season = self.coordinator.season_mode
            return

        cal_season = _calendar_season()

        # Summer is definitive — no temperature check needed.
        if cal_season == SeasonMode.SUMMER:
            self._days_above = 0
            self.coordinator.effective_season = SeasonMode.SUMMER
            return

        # Winter is definitive — always heat.
        if cal_season == SeasonMode.WINTER:
            self._days_above = 0
            self.coordinator.effective_season = SeasonMode.WINTER
            return

        # Spring / Autumn: apply temperature guard.
        outdoor = self.coordinator.outdoor_temperature
        if outdoor is None:
            # No weather data — safe fallback: keep heating on.
            self.coordinator.effective_season = SeasonMode.WINTER
            return

        threshold   = float(self.coordinator.config.get(
            CONF_AUTO_OFF_TEMP_THRESHOLD, DEFAULT_AUTO_OFF_TEMP_THRESHOLD
        ))
        days_needed = int(self.coordinator.config.get(
            CONF_AUTO_OFF_TEMP_DAYS, DEFAULT_AUTO_OFF_TEMP_DAYS
        ))

        from homeassistant.util.dt import now as ha_now
        today = ha_now().date().isoformat()

        if today != self._last_date:
            self._last_date = today
            if outdoor > threshold:
                self._days_above += 1
                _LOGGER.debug(
                    "SeasonEngine [%s]: %.1f°C > %.1f°C — day %d/%d above threshold",
                    cal_season.value, outdoor, threshold,
                    self._days_above, days_needed,
                )
            else:
                if self._days_above > 0:
                    _LOGGER.debug(
                        "SeasonEngine [%s]: %.1f°C ≤ threshold — resetting counter (was %d)",
                        cal_season.value, outdoor, self._days_above,
                    )
                self._days_above = 0

        if self._days_above >= days_needed:
            # Warm enough for long enough — suspend heating.
            self.coordinator.effective_season = SeasonMode.SUMMER
        else:
            # Still cold despite spring/autumn calendar — keep heating on.
            self.coordinator.effective_season = SeasonMode.WINTER

        _LOGGER.debug(
            "SeasonEngine: calendar=%s outdoor=%.1f effective=%s (days_above=%d/%d)",
            cal_season.value, outdoor,
            self.coordinator.effective_season.value,
            self._days_above, days_needed,
        )

    @property
    def days_above_threshold(self) -> int:
        return self._days_above

    @property
    def calendar_season(self) -> SeasonMode:
        """Current meteorological calendar season (read-only)."""
        return _calendar_season()

    async def async_shutdown(self) -> None:
        _LOGGER.debug("SeasonEngine shut down")
