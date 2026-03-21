"""
Heat Manager — DataUpdateCoordinator

Central hub that:
- Owns all engine instances
- Holds all shared runtime state (room_states, season_mode, etc.)
- Runs the periodic tick that drives auto-off, pause expiry, and presence checks
- Exposes helpers used by platform entities to read current state

Phase 3 additions:
- SeasonEngine: resolves AUTO → effective WINTER/SUMMER
- WasteCalculator: proper energy waste/savings tracking
- PreheatEngine: travel_time based pre-heat
- log_event(): internal event log for History tab in sidebar panel
- effective_season property: resolved season regardless of manual/auto
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_AWAY_TEMP_COLD,
    CONF_AWAY_TEMP_MILD,
    CONF_CLIMATE_ENTITY,
    CONF_MILD_THRESHOLD,
    CONF_PERSONS,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_AWAY_TEMP_COLD,
    DEFAULT_AWAY_TEMP_MILD,
    DEFAULT_MILD_THRESHOLD,
    DOMAIN,
    SCAN_INTERVAL_SECONDS,
    AutoOffReason,
    ControllerState,
    RoomState,
    SeasonMode,
)
from .engine.controller import ControllerEngine
from .engine.preheat_engine import PreheatEngine
from .engine.presence_engine import PresenceEngine
from .engine.season_engine import SeasonEngine
from .engine.waste_calculator import WasteCalculator
from .engine.window_engine import WindowEngine

_LOGGER = logging.getLogger(__name__)

# Maximum number of events kept in the in-memory log (FIFO)
_MAX_EVENT_LOG = 200


class HeatManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Central coordinator for Heat Manager.

    All engines are instantiated here. _async_update_data is the single
    periodic tick driving all time-based logic.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry

        # ── Shared runtime state ──────────────────────────────────────────────
        # room_states: only engines mutate this dict
        self.room_states: dict[str, RoomState] = {}

        # season_mode: manual setting (Auto/Winter/Summer) from select entity
        self.season_mode: SeasonMode = SeasonMode.AUTO

        # effective_season: resolved by SeasonEngine each tick
        # AUTO → WINTER or SUMMER based on outdoor temperature history
        # WINTER/SUMMER manual → same value echoed here
        self.effective_season: SeasonMode = SeasonMode.WINTER

        # Cached outdoor temperature from weather entity (°C)
        self.outdoor_temperature: float | None = None

        # In-memory event log — populated by log_event(), read by websocket
        self._event_log: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENT_LOG)

        # ── Engines ───────────────────────────────────────────────────────────
        self.controller      = ControllerEngine(self)
        self.presence_engine = PresenceEngine(self)
        self.window_engine   = WindowEngine(self)
        self.season_engine   = SeasonEngine(self)
        self.waste_calculator = WasteCalculator(self)
        self.preheat_engine  = PreheatEngine(self)

        _LOGGER.debug(
            "Coordinator initialised — %d room(s), %d person(s)",
            len(self.rooms),
            len(self.persons),
        )

    # ── Config helpers ────────────────────────────────────────────────────────

    @property
    def config(self) -> dict[str, Any]:
        """Merged config: entry.data overridden by entry.options."""
        return {**self.entry.data, **self.entry.options}

    @property
    def rooms(self) -> list[dict[str, Any]]:
        return self.config.get(CONF_ROOMS, [])

    @property
    def persons(self) -> list[dict[str, Any]]:
        return self.config.get(CONF_PERSONS, [])

    @property
    def alarm_panel(self) -> str | None:
        return self.config.get(CONF_ALARM_PANEL) or None

    @property
    def weather_entity(self) -> str | None:
        return self.config.get(CONF_WEATHER_ENTITY) or None

    # ── State helpers ─────────────────────────────────────────────────────────

    @property
    def controller_state(self) -> ControllerState:
        return self.controller.state

    @property
    def auto_off_reason(self) -> AutoOffReason:
        return self.controller.auto_off_reason

    @property
    def pause_remaining_minutes(self) -> int:
        return self.controller.pause_remaining_minutes

    def get_room_state(self, room_name: str) -> RoomState:
        return self.room_states.get(room_name, RoomState.NORMAL)

    def set_room_state(self, room_name: str, state: RoomState) -> None:
        """Called by engines to update a room's state and notify listeners."""
        old = self.room_states.get(room_name)
        if old == state:
            return
        _LOGGER.debug("Room '%s': %s → %s", room_name, old, state.value)
        self.room_states[room_name] = state
        self.async_update_listeners()

    def get_climate_entity(self, room_name: str) -> str | None:
        for room in self.rooms:
            if room.get("room_name") == room_name:
                return room.get(CONF_CLIMATE_ENTITY)
        return None

    def get_window_sensors(self, room_name: str) -> list[str]:
        for room in self.rooms:
            if room.get("room_name") == room_name:
                return room.get(CONF_WINDOW_SENSORS, [])
        return []

    def any_window_open(self) -> bool:
        """True if any configured window sensor is currently open."""
        for room in self.rooms:
            for sensor in room.get(CONF_WINDOW_SENSORS, []):
                state = self.hass.states.get(sensor)
                if state and state.state == "on":
                    return True
        return False

    def someone_home(self) -> bool:
        """True if at least one tracked person entity is currently home."""
        for person in self.persons:
            if not person.get("person_tracking", True):
                continue
            entity_id = person.get("person_entity", "")
            state = self.hass.states.get(entity_id)
            if state and state.state == "home":
                return True
        return False

    # ── Energy helpers (Phase 3) ──────────────────────────────────────────────

    @property
    def energy_wasted_today(self) -> float:
        return self.waste_calculator.energy_wasted_today

    @property
    def energy_saved_today(self) -> float:
        return self.waste_calculator.energy_saved_today

    @property
    def efficiency_score(self) -> int:
        return self.waste_calculator.efficiency_score

    # ── Event log (Phase 3) ───────────────────────────────────────────────────

    def log_event(
        self,
        description: str,
        reason: str = "",
        event_type: str = "normal",
    ) -> None:
        """
        Append an event to the in-memory log.
        Called by engines whenever a significant state change occurs.
        Read by websocket.py for the History tab.
        """
        from homeassistant.util.dt import now as ha_now
        now = ha_now()
        # Format time for display
        time_str = now.strftime("%H:%M")
        self._event_log.appendleft({
            "time":        time_str,
            "description": description,
            "reason":      reason,
            "type":        event_type,
            "timestamp":   now.isoformat(),
        })
        _LOGGER.debug("Event logged: %s (%s)", description, reason)

    # ── Outdoor temperature ───────────────────────────────────────────────────

    def _refresh_outdoor_temperature(self) -> None:
        entity_id = self.weather_entity
        if not entity_id:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return
        try:
            temp = state.attributes.get("temperature")
            if temp is not None:
                self.outdoor_temperature = float(temp)
        except (TypeError, ValueError):
            _LOGGER.debug("Could not parse outdoor temperature from %s", entity_id)

    def get_away_temperature(self) -> float:
        """Return the adaptive away temperature based on outdoor conditions."""
        mild_threshold = self.config.get(CONF_MILD_THRESHOLD, DEFAULT_MILD_THRESHOLD)
        if self.outdoor_temperature is not None and self.outdoor_temperature >= mild_threshold:
            return float(self.config.get(CONF_AWAY_TEMP_MILD, DEFAULT_AWAY_TEMP_MILD))
        return float(self.config.get(CONF_AWAY_TEMP_COLD, DEFAULT_AWAY_TEMP_COLD))

    # ── Periodic update ───────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Called every SCAN_INTERVAL_SECONDS.

        Tick order:
          1. Refresh outdoor temperature
          2. Season engine (resolve AUTO → WINTER/SUMMER)
          3. Controller (pause expiry, auto-off, auto-resume)
          4. Presence engine (grace period countdowns)
          5. Window engine (open-window escalation warnings)
          6. Waste calculator (energy accounting)
          7. Preheat engine (travel_time polling no-op)
        """
        try:
            self._refresh_outdoor_temperature()

            # Resolve effective season before controller auto-off checks
            await self.season_engine.async_tick()
            # Keep effective_season in sync with manual overrides
            if self.season_mode != SeasonMode.AUTO:
                self.effective_season = self.season_mode

            await self.controller.async_tick()
            await self.presence_engine.async_tick()
            await self.window_engine.async_tick()
            await self.waste_calculator.async_tick()
            await self.preheat_engine.async_tick()

        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Heat Manager update failed: {err}") from err

        return {
            "controller_state":     self.controller.state,
            "season_mode":          self.season_mode,
            "effective_season":     self.effective_season,
            "outdoor_temperature":  self.outdoor_temperature,
            "room_states":          dict(self.room_states),
            "pause_remaining_minutes": self.pause_remaining_minutes,
            "energy_wasted_today":  self.energy_wasted_today,
            "energy_saved_today":   self.energy_saved_today,
            "efficiency_score":     self.efficiency_score,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        """Clean up when the config entry is unloaded."""
        await self.presence_engine.async_shutdown()
        await self.window_engine.async_shutdown()
        await self.season_engine.async_shutdown()
        await self.waste_calculator.async_shutdown()
        await self.preheat_engine.async_shutdown()
        _LOGGER.debug("Coordinator shut down cleanly")
