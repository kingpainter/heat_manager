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

This is real measured heating power, not a proxy for temperature difference.

Waste (window open):
    The room is actively drawing power (heating_power_request > 0) while
    losing heat through an open window.

Saved (away mode during heating hours):
    Power that *would* have been drawn if the room were in normal schedule,
    estimated as the average of the last known non-zero heating_power_request
    for that room.  Falls back to 50% × room_watts if no history exists.

Efficiency score (0–100):
    Starts at 100.  Each 0.01 kWh wasted costs 1 point.
    Score floor is 0.

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
    DEFAULT_ROOM_WATTAGE,
    RoomState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# Fallback constant when heating_power_request is not available
# (non-Netatmo rooms) — kWh per °C per hour
_KWH_PER_DEGC_PER_HOUR: float = 0.1

# Heating hours during which away-savings are counted (inclusive start)
_HEATING_HOURS_START: int = 6
_HEATING_HOURS_END: int = 23


class WasteCalculator:
    """
    Tracks per-room energy waste and savings, resets at midnight.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._today: date = ha_now().date()
        self._wasted_kwh: float = 0.0
        self._saved_kwh: float = 0.0
        # Last known non-zero heating_power_request per room (0–100)
        # Used to estimate savings when room is in AWAY mode
        self._last_power_pct: dict[str, float] = {}

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

    # ── Tick ──────────────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS by coordinator."""
        today = ha_now().date()

        # Midnight reset
        if today != self._today:
            self._today      = today
            self._wasted_kwh = 0.0
            self._saved_kwh  = 0.0
            # Keep _last_power_pct across midnight — it's a rolling estimate
            _LOGGER.debug("WasteCalculator: reset for new day %s", today)

        tick_hours = 60.0 / 3600.0  # 60-second coordinator tick

        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not room_name or not climate_id:
                continue

            room_watts = float(room.get(CONF_ROOM_WATTAGE, DEFAULT_ROOM_WATTAGE))
            room_state = self.coordinator.get_room_state(room_name)

            # Read heating power — Netatmo attr or Z2M dedicated sensor
            pi_entity = room.get(CONF_PI_DEMAND_ENTITY) or None
            power_pct = self._get_heating_power_pct(climate_id, pi_entity)

            # Keep rolling history of non-zero power for savings estimation
            if power_pct is not None and power_pct > 0:
                self._last_power_pct[room_name] = power_pct

            # ── Waste: window open while room is heating ──────────────────────
            if room_state == RoomState.WINDOW_OPEN:
                waste_kwh = self._calc_waste_kwh(
                    climate_id, room_watts, power_pct, tick_hours
                )
                if waste_kwh > 0:
                    self._wasted_kwh += waste_kwh
                    _LOGGER.debug(
                        "Waste +%.4f kWh — %s (power_pct=%s)",
                        waste_kwh, room_name,
                        f"{power_pct:.0f}%" if power_pct is not None else "n/a",
                    )

            # ── Saved: away mode during normal heating hours ──────────────────
            if room_state == RoomState.AWAY:
                hour = ha_now().hour
                if _HEATING_HOURS_START <= hour < _HEATING_HOURS_END:
                    saved_kwh = self._calc_saved_kwh(
                        room_name, room_watts, tick_hours
                    )
                    if saved_kwh > 0:
                        self._saved_kwh += saved_kwh

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_heating_power_pct(
        self, climate_id: str, pi_entity: str | None = None
    ) -> float | None:
        """
        Read heating demand (0–100 %) from the best available source.

        Priority order:
        1. Dedicated sensor (pi_demand_entity) — Z2M TRVs expose
           `pi_heating_demand` as `sensor.<name>_pi_heating_demand`.
           This is the most reliable source for Zigbee TRVs.
        2. `heating_power_request` attribute on the climate entity
           (Netatmo cloud integration).
        3. None — fallback to Δtemp proxy in _calc_waste_kwh.
        """
        # 1. Dedicated Z2M sensor
        if pi_entity:
            state = self.coordinator.hass.states.get(pi_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (TypeError, ValueError):
                    pass

        # 2. Netatmo heating_power_request climate attribute
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
        """
        Energy wasted this tick (window open while heating).

        Uses heating_power_request when available (Netatmo); falls back to
        Δtemp × 0.1 kWh/°C/h for non-Netatmo entities.
        """
        if power_pct is not None:
            # Real data path: actual watts × time
            return (power_pct / 100.0) * room_watts / 1000.0 * tick_hours

        # Fallback: Δtemp proxy for non-Netatmo rooms
        return self._legacy_delta_kwh(climate_id, tick_hours)

    def _calc_saved_kwh(
        self,
        room_name: str,
        room_watts: float,
        tick_hours: float,
    ) -> float:
        """
        Energy saved this tick (away mode during heating hours).

        Estimate: last known heating_power_request for this room, or 50%
        of rated wattage if no history exists.
        """
        last_pct = self._last_power_pct.get(room_name, 50.0)
        return (last_pct / 100.0) * room_watts / 1000.0 * tick_hours

    def _legacy_delta_kwh(self, climate_id: str, tick_hours: float) -> float:
        """
        Phase 3 fallback: Δtemp × 0.1 kWh/°C/h.
        Used for non-Netatmo climate entities that lack heating_power_request.
        """
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
