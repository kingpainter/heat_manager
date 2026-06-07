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

from homeassistant.util.dt import now as ha_now

from ..const import (
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_INDOOR_WAKE_SENSOR,
    CONF_INDOOR_WAKE_THRESHOLD,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_INDOOR_WAKE_THRESHOLD,
    HV_EVENT_SEASON_SUMMER,
    HV_EVENT_SEASON_WINTER,
    METEO_SEASONS,
    EffectiveSeason,
    SeasonMode,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


def _calendar_season() -> SeasonMode:
    """Return the meteorological season for today's date."""
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
        self._prev_effective_season: EffectiveSeason | None = None  # B4: was SeasonMode, now EffectiveSeason

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by the coordinator.

        B4 fix: coordinator.effective_season is now always set to a proper
        EffectiveSeason enum (DORMANT/WAKING/ACTIVE) rather than a SeasonMode.

        B9 fix: WAKING phase is now activated when indoor temperature exceeds
        CONF_INDOOR_WAKE_THRESHOLD during ACTIVE season (transitional warmth).
        """
        if self.coordinator.season_mode != SeasonMode.AUTO:
            # Manual override — map SeasonMode to EffectiveSeason
            manual = self.coordinator.season_mode
            if manual == SeasonMode.SUMMER:
                new_eff = EffectiveSeason.DORMANT
            else:
                new_eff = self._apply_waking_check(EffectiveSeason.ACTIVE)
            self.coordinator.effective_season = new_eff
            self._maybe_trigger_voice(new_eff)
            self._prev_effective_season = new_eff
            return

        cal_season = _calendar_season()

        # Summer is definitive — DORMANT (no heating).
        if cal_season == SeasonMode.SUMMER:
            self._days_above = 0
            new_eff = EffectiveSeason.DORMANT
            self.coordinator.effective_season = new_eff
            self._maybe_trigger_voice(new_eff)
            self._prev_effective_season = new_eff
            return

        # Winter is definitive — ACTIVE (full heating).
        if cal_season == SeasonMode.WINTER:
            self._days_above = 0
            new_eff = self._apply_waking_check(EffectiveSeason.ACTIVE)
            self.coordinator.effective_season = new_eff
            self._maybe_trigger_voice(new_eff)
            self._prev_effective_season = new_eff
            return

        # Spring / Autumn: apply temperature guard.
        outdoor = self.coordinator.outdoor_temperature
        if outdoor is None:
            # No weather data — safe fallback: keep heating on.
            new_eff = self._apply_waking_check(EffectiveSeason.ACTIVE)
            self.coordinator.effective_season = new_eff
            return

        threshold = float(
            self.coordinator.config.get(
                CONF_AUTO_OFF_TEMP_THRESHOLD, DEFAULT_AUTO_OFF_TEMP_THRESHOLD
            )
        )
        days_needed = int(
            self.coordinator.config.get(
                CONF_AUTO_OFF_TEMP_DAYS, DEFAULT_AUTO_OFF_TEMP_DAYS
            )
        )

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
            new_eff = EffectiveSeason.DORMANT
        else:
            # B9: transitional season but still cold — allow WAKING check
            new_eff = self._apply_waking_check(EffectiveSeason.ACTIVE)

        self.coordinator.effective_season = new_eff

        _LOGGER.debug(
            "SeasonEngine: calendar=%s outdoor=%.1f effective=%s (days_above=%d/%d)",
            cal_season.value, outdoor, new_eff.value,
            self._days_above, days_needed,
        )

        self._maybe_trigger_voice(new_eff)
        self._prev_effective_season = new_eff

    def _apply_waking_check(self, base: EffectiveSeason) -> EffectiveSeason:
        """B9: Return WAKING if indoor temperature exceeds wake threshold, else base.

        Only applies when base would be ACTIVE — DORMANT is never downgraded.
        Reads CONF_INDOOR_WAKE_SENSOR; falls back to ACTIVE if sensor absent.
        """
        if base != EffectiveSeason.ACTIVE:
            return base
        sensor_id = self.coordinator.config.get(CONF_INDOOR_WAKE_SENSOR) or None
        if not sensor_id:
            return EffectiveSeason.ACTIVE
        state = self.coordinator.hass.states.get(sensor_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return EffectiveSeason.ACTIVE
        try:
            indoor_temp = float(state.state)
        except (TypeError, ValueError):
            return EffectiveSeason.ACTIVE
        threshold = float(
            self.coordinator.config.get(CONF_INDOOR_WAKE_THRESHOLD, DEFAULT_INDOOR_WAKE_THRESHOLD)
        )
        if indoor_temp >= threshold:
            _LOGGER.debug(
                "SeasonEngine: indoor %.1f°C ≥ wake threshold %.1f°C — WAKING phase",
                indoor_temp, threshold,
            )
            return EffectiveSeason.WAKING
        return EffectiveSeason.ACTIVE

    def _maybe_trigger_voice(self, new_eff: EffectiveSeason) -> None:
        """Trigger House Voice on DORMANT↔ACTIVE transitions."""
        prev = self._prev_effective_season
        if prev is None or new_eff == prev:
            return
        import asyncio
        if new_eff == EffectiveSeason.DORMANT and prev != EffectiveSeason.DORMANT:
            asyncio.ensure_future(
                self.coordinator.async_house_voice_say(HV_EVENT_SEASON_SUMMER)
            )
        elif prev == EffectiveSeason.DORMANT and new_eff != EffectiveSeason.DORMANT:
            asyncio.ensure_future(
                self.coordinator.async_house_voice_say(HV_EVENT_SEASON_WINTER)
            )

    @property
    def days_above_threshold(self) -> int:
        return self._days_above

    @property
    def calendar_season(self) -> SeasonMode:
        """Current meteorological calendar season (read-only)."""
        return _calendar_season()

    @property
    def effective_season(self) -> EffectiveSeason:
        """Current resolved effective season (convenience read-only access).

        B4: coordinator.effective_season is now always a proper EffectiveSeason
        enum (DORMANT/WAKING/ACTIVE), never a SeasonMode.
        """
        eff = self.coordinator.effective_season
        if isinstance(eff, EffectiveSeason):
            return eff
        # Fallback guard for unexpected SeasonMode values during migration
        return EffectiveSeason.ACTIVE

    async def async_shutdown(self) -> None:
        _LOGGER.debug("SeasonEngine shut down")
