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

v0.2.9 additions:
- CONF_OUTDOOR_TEMP_SENSOR: local sensor overrides weather entity temperature
- CONF_CO2_SENSOR per room: get_room_co2() helper for WindowEngine/WasteCalculator
- CONF_ROOM_TEMP_SENSOR per room: get_room_current_temp() feeds PID with an
  independent probe instead of the TRV's own (radiator-biased) sensor
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
    CONF_CO2_SENSOR,
    CONF_MILD_THRESHOLD,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PERSONS,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_PID_ENABLED,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_PRECIPITATION_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_ROOMS,
    CONF_TRV_MAX_TEMP,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED_SENSOR,
    CONF_WINDOW_SENSORS,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_AWAY_TEMP_COLD,
    DEFAULT_AWAY_TEMP_MILD,
    DEFAULT_MILD_THRESHOLD,
    DEFAULT_PID_KD,
    DEFAULT_PID_KI,
    DEFAULT_PID_KP,
    DEFAULT_TRV_MAX_TEMP,
    DOMAIN,
    SCAN_INTERVAL_SECONDS,
    AutoOffReason,
    ControllerState,
    RoomState,
    SeasonMode,
)
from .engine.controller import ControllerEngine
from .engine.pid_controller import PidController
from .engine.preheat_engine import PreheatEngine
from .engine.presence_engine import PresenceEngine
from .engine.season_engine import SeasonEngine
from .engine.waste_calculator import WasteCalculator
from .engine.valve_protection_engine import ValveProtectionEngine
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
        self.room_states: dict[str, RoomState] = {}
        # Restore persisted season_mode if present (set via select entity)
        _saved_season = self.config.get("season_mode", SeasonMode.AUTO.value)
        try:
            self.season_mode: SeasonMode = SeasonMode(_saved_season)
        except ValueError:
            self.season_mode = SeasonMode.AUTO
        self.effective_season: SeasonMode = SeasonMode.WINTER
        self.outdoor_temperature: float | None = None
        self._event_log: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENT_LOG)

        # ── Engines ───────────────────────────────────────────────────────────
        self.controller      = ControllerEngine(self)
        self.presence_engine = PresenceEngine(self)
        self.window_engine   = WindowEngine(self)
        self.season_engine   = SeasonEngine(self)
        self.waste_calculator    = WasteCalculator(self)
        self.preheat_engine      = PreheatEngine(self)
        self.valve_protection    = ValveProtectionEngine(self)

        self.pid_controllers: dict[str, PidController] = {}
        self._init_pid_controllers()

        _LOGGER.debug(
            "Coordinator initialised — %d room(s), %d person(s)",
            len(self.rooms),
            len(self.persons),
        )

    # ── Config helpers ────────────────────────────────────────────────────────

    @property
    def config(self) -> dict[str, Any]:
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

    def _init_pid_controllers(self) -> None:
        kp  = float(self.config.get(CONF_PID_KP,  DEFAULT_PID_KP))
        ki  = float(self.config.get(CONF_PID_KI,  DEFAULT_PID_KI))
        kd  = float(self.config.get(CONF_PID_KD,  DEFAULT_PID_KD))
        for room in self.rooms:
            name = room.get("room_name", "")
            if name:
                self.pid_controllers[name] = PidController(
                    kp=kp, ki=ki, kd=kd, room_name=name
                )

    @property
    def pid_enabled(self) -> bool:
        return bool(self.config.get(CONF_PID_ENABLED, True))

    @property
    def trv_max_temp(self) -> float:
        return float(self.config.get(CONF_TRV_MAX_TEMP, DEFAULT_TRV_MAX_TEMP))

    def get_pid(self, room_name: str) -> PidController | None:
        return self.pid_controllers.get(room_name)

    def get_homekit_climate_entity(self, room_name: str) -> str | None:
        for room in self.rooms:
            if room.get("room_name") == room_name:
                val = room.get(CONF_HOMEKIT_CLIMATE_ENTITY)
                return val if val else None
        return None

    def get_write_entity(self, room_name: str) -> str | None:
        """H-4: Return the preferred write entity for a room.

        Priority:
          1. HomeKit climate entity (local LAN, <100 ms, no rate limits)
          2. Cloud climate entity (fallback)

        Use this for all set_temperature writes. Do NOT use for
        preset_mode writes (away/schedule) — those must still go to the
        cloud entity because preset_mode is not supported via HomeKit HAP.
        """
        hk_id = self.get_homekit_climate_entity(room_name)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return hk_id
        return self.get_climate_entity(room_name)

    def needs_cloud_delay(self, room_name: str) -> bool:
        """H-6: Return True if the write entity for this room is the cloud entity.

        Used to decide whether NETATMO_API_CALL_DELAY_SEC should be applied
        after a service call. HomeKit writes are local and need no stagger.
        """
        hk_id = self.get_homekit_climate_entity(room_name)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return False  # Writing to HomeKit — no delay needed
        return True  # Writing to cloud — stagger to avoid 429

    def get_window_sensors(self, room_name: str) -> list[str]:
        for room in self.rooms:
            if room.get("room_name") == room_name:
                return room.get(CONF_WINDOW_SENSORS, [])
        return []

    def any_window_open(self) -> bool:
        for room in self.rooms:
            for sensor in room.get(CONF_WINDOW_SENSORS, []):
                state = self.hass.states.get(sensor)
                if state and state.state == "on":
                    return True
        return False

    def someone_home(self) -> bool:
        for person in self.persons:
            if not person.get("person_tracking", True):
                continue
            entity_id = person.get("person_entity", "")
            state = self.hass.states.get(entity_id)
            if state and state.state == "home":
                return True
        return False

    # ── Sensor input helpers (v0.2.9) ─────────────────────────────────────────

    def get_room_co2(self, room_name: str) -> float | None:
        """Return current CO₂ level (ppm) for a room, or None."""
        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            entity_id = room.get(CONF_CO2_SENSOR) or None
            if not entity_id:
                return None
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                return None
            try:
                return float(state.state)
            except (TypeError, ValueError):
                return None
        return None

    def get_outdoor_humidity(self) -> float | None:
        """Return outdoor relative humidity (%) from CONF_OUTDOOR_HUMIDITY_SENSOR."""
        entity_id = self.config.get(CONF_OUTDOOR_HUMIDITY_SENSOR) or None
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def get_precipitation(self) -> float | None:
        """Return current precipitation (mm or mm/h) from CONF_PRECIPITATION_SENSOR."""
        entity_id = self.config.get(CONF_PRECIPITATION_SENSOR) or None
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def get_wind_speed(self) -> float | None:
        """Return current wind speed (m/s) from CONF_WIND_SPEED_SENSOR."""
        entity_id = self.config.get(CONF_WIND_SPEED_SENSOR) or None
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def is_raining(self) -> bool:
        """Return True when precipitation sensor reads > 0."""
        precip = self.get_precipitation()
        return precip is not None and precip > 0.0

    def get_room_current_temp(self, room_name: str, climate_id: str) -> float | None:
        """
        Return the best available current temperature for a room (°C).

        Priority:
        1. CONF_ROOM_TEMP_SENSOR — external probe, independent of the TRV body.
           Zigbee TRVs especially benefit: their built-in sensor sits on the
           hot radiator and reads 1–3 °C higher than actual room temperature.
        2. HomeKit climate entity current_temperature (Netatmo local HAP).
        3. Cloud climate entity current_temperature (fallback).

        Returns None only if all sources are unavailable.
        """
        # 1. External room temperature sensor
        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            entity_id = room.get(CONF_ROOM_TEMP_SENSOR) or None
            if entity_id:
                state = self.hass.states.get(entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        return float(state.state)
                    except (TypeError, ValueError):
                        pass
            break  # room found, external sensor absent or unavailable

        # 2. HomeKit entity (Netatmo local HAP — fresher than cloud)
        hk_id = self.get_homekit_climate_entity(room_name)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                try:
                    val = state.attributes.get("current_temperature")
                    if val is not None:
                        return float(val)
                except (TypeError, ValueError):
                    pass

        # 3. Cloud / primary climate entity
        if climate_id:
            state = self.hass.states.get(climate_id)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    val = state.attributes.get("current_temperature")
                    if val is not None:
                        return float(val)
                except (TypeError, ValueError):
                    pass

        return None

    # ── Season engine helpers (I-2) ──────────────────────────────────────────

    @property
    def calendar_season(self) -> SeasonMode:
        """Isolated access to season_engine — avoids direct engine coupling in platforms."""
        return self.season_engine.calendar_season

    @property
    def days_above_threshold(self) -> int:
        """Isolated access to season_engine — avoids direct engine coupling in platforms."""
        return self.season_engine.days_above_threshold

    # ── Energy helpers ────────────────────────────────────────────────────────

    @property
    def energy_wasted_today(self) -> float:
        return self.waste_calculator.energy_wasted_today

    @property
    def energy_saved_today(self) -> float:
        return self.waste_calculator.energy_saved_today

    @property
    def efficiency_score(self) -> int:
        return self.waste_calculator.efficiency_score

    @property
    def last_waste_time(self) -> str | None:
        return self.waste_calculator.last_waste_time

    @property
    def last_saved_time(self) -> str | None:
        return self.waste_calculator.last_saved_time

    # ── Event log ─────────────────────────────────────────────────────────────

    def log_event(
        self,
        description: str,
        reason: str = "",
        event_type: str = "normal",
    ) -> None:
        from homeassistant.util.dt import now as ha_now
        now = ha_now()
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
        """
        Update self.outdoor_temperature from the best available source.

        Priority:
        1. CONF_OUTDOOR_TEMP_SENSOR — local weather station / Netatmo outdoor
           module / Aqara etc.  Updates every 5 min or faster; reflects the
           actual microclimate at the property rather than a forecast grid point.
        2. weather.* entity temperature attribute — existing behaviour, used as
           fallback when the dedicated sensor is absent or unavailable.
        """
        # 1. Local outdoor temperature sensor (v0.2.9)
        outdoor_sensor = self.config.get(CONF_OUTDOOR_TEMP_SENSOR) or None
        if outdoor_sensor:
            state = self.hass.states.get(outdoor_sensor)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    self.outdoor_temperature = float(state.state)
                    return
                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "Could not parse outdoor temperature from sensor %s",
                        outdoor_sensor,
                    )

        # 2. Fallback: weather entity attribute
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
        mild_threshold = self.config.get(CONF_MILD_THRESHOLD, DEFAULT_MILD_THRESHOLD)
        if self.outdoor_temperature is not None and self.outdoor_temperature >= mild_threshold:
            return float(self.config.get(CONF_AWAY_TEMP_MILD, DEFAULT_AWAY_TEMP_MILD))
        return float(self.config.get(CONF_AWAY_TEMP_COLD, DEFAULT_AWAY_TEMP_COLD))

    # ── Periodic update ───────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Called every SCAN_INTERVAL_SECONDS.

        Tick order:
          1. Refresh outdoor temperature (local sensor preferred, weather fallback)
          2. Season engine (resolve AUTO → WINTER/SUMMER)
          3. Controller (pause expiry, auto-off, auto-resume)
          4. Presence engine (grace period countdowns)
          5. Window engine (open-window escalation warnings)
          6. Waste calculator (energy accounting)
          7. Preheat engine (travel_time polling no-op)
          8. PID tick (proportional TRV setpoints for NORMAL rooms)
        """
        try:
            self._refresh_outdoor_temperature()

            await self.season_engine.async_tick()
            if self.season_mode != SeasonMode.AUTO:
                self.effective_season = self.season_mode

            await self.controller.async_tick()
            await self.presence_engine.async_tick()
            await self.window_engine.async_tick()
            await self.waste_calculator.async_tick()
            await self.preheat_engine.async_tick()
            await self.valve_protection.async_tick()
            await self._async_pid_tick()

        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Heat Manager update failed: {err}") from err

        return {
            "controller_state":        self.controller.state,
            "season_mode":             self.season_mode,
            "effective_season":        self.effective_season,
            "outdoor_temperature":     self.outdoor_temperature,
            "room_states":             dict(self.room_states),
            "pause_remaining_minutes": self.pause_remaining_minutes,
            "energy_wasted_today":     self.energy_wasted_today,
            "energy_saved_today":      self.energy_saved_today,
            "efficiency_score":        self.efficiency_score,
        }

    async def _async_pid_tick(self) -> None:
        """
        Drive the PID controller for every room currently in NORMAL state.

        v0.2.9: current_temperature is now read via get_room_current_temp()
        which prefers CONF_ROOM_TEMP_SENSOR over HomeKit entity over cloud entity.
        This improves PID accuracy for Zigbee TRV rooms where the TRV's built-in
        probe sits on the hot radiator body and reads 1–3 °C above actual room temp.
        """
        if not self.pid_enabled:
            return
        if self.controller_state != ControllerState.ON:
            for pid in self.pid_controllers.values():
                pid.reset()
            return
        if self.effective_season != SeasonMode.WINTER:
            for pid in self.pid_controllers.values():
                pid.reset()
            return

        for room in self.rooms:
            room_name  = room.get("room_name", "")
            cloud_id   = room.get(CONF_CLIMATE_ENTITY, "")
            if not room_name or not cloud_id:
                continue

            pid = self.pid_controllers.get(room_name)
            if pid is None:
                continue

            if self.get_room_state(room_name) != RoomState.NORMAL:
                pid.reset()
                continue

            # H-4: use get_write_entity() — HomeKit preferred, cloud fallback
            # PID setpoints should only be written locally (HomeKit) to avoid
            # disturbing Netatmo's cloud schedule. Skip rooms without HomeKit.
            hk_id = self.get_homekit_climate_entity(room_name)
            if not hk_id:
                pid.reset()
                continue
            write_id = hk_id  # confirmed local write channel

            # ── Read current temperature via unified helper ────────────────
            # Preference: room_temp_sensor → HomeKit entity → cloud entity
            current_temp = self.get_room_current_temp(room_name, cloud_id)
            if current_temp is None:
                pid.reset()
                continue

            # ── Read schedule setpoint from cloud entity ──────────────────
            cloud_state = self.hass.states.get(cloud_id)
            if cloud_state is None or cloud_state.state in ("unavailable", "unknown"):
                pid.reset()
                continue

            target_temp = cloud_state.attributes.get("temperature")
            if target_temp is None:
                continue

            try:
                target_temp = float(target_temp)
            except (TypeError, ValueError):
                continue

            # ── PID tick → power fraction 0..1 ──────────────────────────
            power = pid.update(setpoint=target_temp, current=current_temp)

            trv_setpoint = PidController.power_to_setpoint(
                power=power,
                current_temp=current_temp,
                trv_max=self.trv_max_temp,
                trv_min=float(room.get("away_temp_override", 10.0)),
            )

            # Suppress command if change < 0.5 °C
            hk_state = self.hass.states.get(write_id)
            if hk_state is None or hk_state.state in ("unavailable", "unknown", "off"):
                pid.reset()
                continue
            hk_current_setpoint = hk_state.attributes.get("temperature", 0.0)
            if abs(trv_setpoint - float(hk_current_setpoint)) < 0.5:
                continue

            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": write_id, "temperature": trv_setpoint},
                    blocking=True,
                )
                _LOGGER.debug(
                    "PID tick [%s]: schedule_sp=%.1f cur=%.1f pwr=%.2f → HAP %.1f°C"
                    "  (heating_power_request=%s%%)",
                    room_name, target_temp, current_temp, power, trv_setpoint,
                    cloud_state.attributes.get("heating_power_request", "?"),
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "PID setpoint failed for '%s' via HomeKit: %s", room_name, err
                )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        await self.presence_engine.async_shutdown()
        await self.window_engine.async_shutdown()
        await self.season_engine.async_shutdown()
        await self.waste_calculator.async_shutdown()
        await self.preheat_engine.async_shutdown()
        await self.valve_protection.async_shutdown()
        _LOGGER.debug("Coordinator shut down cleanly")
