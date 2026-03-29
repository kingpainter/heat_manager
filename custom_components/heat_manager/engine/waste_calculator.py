"""
Heat Manager — Waste Calculator Engine (Phase 4)

Tracks per-room energy waste and savings using real Netatmo data.

Phase 4 changes vs Phase 3
---------------------------
Phase 3 used a fixed fictional constant (0.1 kWh/°C/h) to estimate energy.
Phase 4 uses the actual `heating_power_request` attribute (0–100 %) that
Netatmo's cloud exposes on every NRV climate entity, combined with a
per-room rated wattage (default 1000 W).

Formula per room per tick:
    actual_kWh = (heating_power_request / 100) × room_watts × tick_hours

v0.2.9 — CO₂-weighted waste
-----------------------------
When CONF_CO2_SENSOR is configured for a room, waste attribution is reduced
when CO₂ is elevated.  The rationale: if CO₂ ≥ DEFAULT_CO2_VENTILATION_THRESHOLD
the open window is purposeful ventilation, not careless heat loss.  A 50 %
reduction is applied to waste_kWh in that case so the efficiency score
stays fair and the energy-wasted sensor reflects true wasted heat rather
than penalising necessary ventilation.

Waste weight table
  CO₂ (ppm)         waste_weight
  ─────────────────────────────
  no sensor          1.00  (unchanged behaviour)
  < threshold        1.00  (window open without ventilation need — full waste)
  ≥ threshold        0.50  (ventilation justified — half waste)

Fallback:
    If `heating_power_request` is not present (non-Netatmo climate entity),
    the engine falls back to the Phase 3 Δtemp × 0.1 kWh/°C/h formula so
    non-Netatmo rooms still get an estimate.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from homeassistant.util.dt import now as ha_now

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_PI_DEMAND_ENTITY,
    CONF_ROOM_WATTAGE,
    DEFAULT_CO2_VENTILATION_THRESHOLD,
    DEFAULT_ROOM_WATTAGE,
    RoomState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

_KWH_PER_DEGC_PER_HOUR: float = 0.1
_HEATING_HOURS_START: int = 6
_HEATING_HOURS_END: int = 23

# Waste weight when CO₂ is elevated — window open for ventilation, not heat loss
_WASTE_WEIGHT_VENTILATION: float = 0.50


class WasteCalculator:
    """Tracks per-room energy waste and savings, resets at midnight."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._today: date = ha_now().date()
        self._wasted_kwh: float = 0.0
        self._saved_kwh: float = 0.0
        self._last_power_pct: dict[str, float] = {}
        self._last_waste_time: str | None = None
        self._last_saved_time: str | None = None

    # ── Public read-only properties ───────────────────────────────────────────

    @property
    def energy_wasted_today(self) -> float:
        return round(self._wasted_kwh, 3)

    @property
    def energy_saved_today(self) -> float:
        return round(self._saved_kwh, 3)

    @property
    def efficiency_score(self) -> int:
        """Score 0–100. Starts at 100, loses 1 point per 0.01 kWh wasted."""
        return max(0, min(100, 100 - int(self._wasted_kwh * 100)))

    @property
    def last_waste_time(self) -> str | None:
        """ISO timestamp of the last waste event today, or None."""
        return self._last_waste_time

    @property
    def last_saved_time(self) -> str | None:
        """ISO timestamp of the last saved event today, or None."""
        return self._last_saved_time

    # ── Tick ──────────────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by coordinator."""
        today = ha_now().date()

        if today != self._today:
            self._today           = today
            self._wasted_kwh      = 0.0
            self._saved_kwh       = 0.0
            self._last_waste_time = None
            self._last_saved_time = None
            _LOGGER.debug("WasteCalculator: reset for new day %s", today)

        tick_hours = 60.0 / 3600.0

        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not room_name or not climate_id:
                continue

            room_watts = float(room.get(CONF_ROOM_WATTAGE, DEFAULT_ROOM_WATTAGE))
            room_state = self.coordinator.get_room_state(room_name)

            pi_entity  = room.get(CONF_PI_DEMAND_ENTITY) or None
            power_pct  = self._get_heating_power_pct(climate_id, pi_entity)

            if power_pct is not None and power_pct > 0:
                self._last_power_pct[room_name] = power_pct

            # ── Waste: window open while room is heating ──────────────────
            if room_state == RoomState.WINDOW_OPEN:
                raw_waste_kwh = self._calc_waste_kwh(
                    climate_id, room_watts, power_pct, tick_hours
                )
                if raw_waste_kwh > 0:
                    # v0.2.9 — apply CO₂ weight: ventilation reduces waste attribution
                    weight    = self._co2_waste_weight(room_name)
                    waste_kwh = raw_waste_kwh * weight
                    self._wasted_kwh      += waste_kwh
                    self._last_waste_time  = ha_now().isoformat()
                    _LOGGER.debug(
                        "Waste +%.4f kWh — %s (power=%s%%, co2_weight=%.2f)",
                        waste_kwh, room_name,
                        f"{power_pct:.0f}" if power_pct is not None else "n/a",
                        weight,
                    )

            # ── Saved: away mode during normal heating hours ──────────────
            if room_state == RoomState.AWAY:
                hour = ha_now().hour
                if _HEATING_HOURS_START <= hour < _HEATING_HOURS_END:
                    saved_kwh = self._calc_saved_kwh(room_name, room_watts, tick_hours)
                    if saved_kwh > 0:
                        self._saved_kwh       += saved_kwh
                        self._last_saved_time  = ha_now().isoformat()

    # ── CO₂ waste weighting (v0.2.9) ─────────────────────────────────────────

    def _co2_waste_weight(self, room_name: str) -> float:
        """
        Return a multiplier (0.0–1.0) for waste attribution based on CO₂.

        1.00 → full waste (no sensor, or CO₂ below ventilation threshold)
        0.50 → half waste (CO₂ elevated — window open for ventilation)
        """
        co2 = self.coordinator.get_room_co2(room_name)
        if co2 is None:
            return 1.0
        if co2 >= DEFAULT_CO2_VENTILATION_THRESHOLD:
            return _WASTE_WEIGHT_VENTILATION
        return 1.0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_heating_power_pct(
        self, climate_id: str, pi_entity: str | None = None
    ) -> float | None:
        if pi_entity:
            state = self.coordinator.hass.states.get(pi_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (TypeError, ValueError):
                    pass

        state = self.coordinator.hass.states.get(climate_id)
        if not state:
            return None
        raw = state.attributes.get("heating_power_request")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _calc_waste_kwh(
        self,
        climate_id: str,
        room_watts: float,
        power_pct: float | None,
        tick_hours: float,
    ) -> float:
        if power_pct is not None:
            return (power_pct / 100.0) * room_watts / 1000.0 * tick_hours
        return self._legacy_delta_kwh(climate_id, tick_hours)

    def _calc_saved_kwh(
        self,
        room_name: str,
        room_watts: float,
        tick_hours: float,
    ) -> float:
        last_pct = self._last_power_pct.get(room_name, 50.0)
        return (last_pct / 100.0) * room_watts / 1000.0 * tick_hours

    def _legacy_delta_kwh(self, climate_id: str, tick_hours: float) -> float:
        state = self.coordinator.hass.states.get(climate_id)
        if not state:
            return 0.0
        try:
            setpoint = float(state.attributes.get("temperature", 0))
            current  = float(state.attributes.get("current_temperature", 0))
        except (TypeError, ValueError):
            return 0.0
        delta = setpoint - current
        return max(0.0, delta * tick_hours * _KWH_PER_DEGC_PER_HOUR)

    async def async_shutdown(self) -> None:
        _LOGGER.debug("WasteCalculator shut down")
