"""Heat Manager coordinator — sensors layer: readings from the house.

Room temperature, CO2, lux, outdoor weather, doors and windows, presence.
Read-only lookups over Home Assistant states; nothing here writes to a
device (v0.68.4, T3d).
"""

from __future__ import annotations

import logging
from typing import Any

from ..const import (
    CONF_CO2_SENSOR,
    CONF_DOOR_ROOM_A,
    CONF_DOOR_ROOM_B,
    CONF_DOOR_SENSOR,
    CONF_DOOR_STYLED_SENSORS,
    CONF_HEATED_DOOR_SENSORS,
    CONF_LUX_SENSOR,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PRECIPITATION_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_TRV_TYPE,
    CONF_TRV_WINDOW_DETECTION,
    CONF_WIND_SPEED_SENSOR,
    CONF_WINDOW_SENSORS,
)
from ..engine.netatmo_backend import (
    TEMP_SOURCE_HOMEKIT,
    temp_source_order,
    window_source_open,
)
from ..engine.readings import sanity_clamp_temp
from .persistence import CoordinatorPersistence

_LOGGER = logging.getLogger(__name__)


class CoordinatorSensors(CoordinatorPersistence):
    """Heat Manager coordinator — sensors layer: readings from the house."""

    def get_room_doors(self, room_name: str) -> list[dict[str, Any]]:
        """Every configured interior door touching this room, either side."""
        return [
            d
            for d in self.doors
            if d.get(CONF_DOOR_ROOM_A) == room_name
            or d.get(CONF_DOOR_ROOM_B) == room_name
        ]

    def get_door_other_room(self, door: dict[str, Any], room_name: str) -> str:
        """Given a door dict and one of its two rooms, return the other one."""
        if door.get(CONF_DOOR_ROOM_A) == room_name:
            return str(door.get(CONF_DOOR_ROOM_B, ""))
        return str(door.get(CONF_DOOR_ROOM_A, ""))

    def is_room_door_open(self, room_name: str) -> bool:
        """True if ANY interior door connected to this room is currently open.

        Used by CalibrationEngine to pick which of a room's two learned
        heat-up-rate profiles to use — see engine/calibration_engine.py.
        """
        for door in self.get_room_doors(room_name):
            sensor_id = door.get(CONF_DOOR_SENSOR)
            if not sensor_id:
                continue
            state = self.hass.states.get(sensor_id)
            if state and state.state == "on":
                return True
        return False

    def get_door_heat_share_inputs(
        self, room_name: str, current_temp: float
    ) -> tuple[float | None, float | None]:
        """For punkt 8 (door heat sharing, 2026-09-16): among this room's
        open interior doors, find the neighbouring room best positioned to
        be sharing heat right now and return (neighbor_power, temp_diff)
        for it — or (None, None) if no door is open, no neighbour has an
        active PID, or the neighbour's temperature isn't known.

        Only ever considers a neighbour WARMER than this room (a colder
        neighbour isn't sharing anything in); "best" means the neighbour
        with the highest current PID power, since that's the one most
        likely to actually be delivering heat through the doorway right
        now. Feeds directly into door_heat_share_reduction() (engine/pid_adjustments.py) — see that
        function for the thresholds these two values are checked against.
        A room with multiple open doors is deliberately capped at its
        single best neighbour rather than summing across all of them, to
        avoid over-crediting a room with several doors open at once.
        """
        best_power: float | None = None
        best_diff: float | None = None
        for door in self.get_room_doors(room_name):
            sensor_id = door.get(CONF_DOOR_SENSOR)
            if not sensor_id:
                continue
            state = self.hass.states.get(sensor_id)
            if state is None or state.state != "on":
                continue
            neighbor_name = self.get_door_other_room(door, room_name)
            if not neighbor_name:
                continue
            neighbor_pid = self.pid_controllers.get(neighbor_name)
            if neighbor_pid is None:
                continue
            neighbor_power = getattr(neighbor_pid, "_last_output", None)
            if neighbor_power is None:
                continue
            neighbor_climate_id = self.get_climate_entity(neighbor_name) or ""
            neighbor_temp = self.get_room_current_temp(
                neighbor_name, neighbor_climate_id
            )
            if neighbor_temp is None:
                continue
            diff = neighbor_temp - current_temp
            if diff <= 0:
                continue
            if best_power is None or neighbor_power > best_power:
                best_power = float(neighbor_power)
                best_diff = diff
        return best_power, best_diff

    def get_room_door_styled_sensors(self, room_name: str) -> list[str]:
        """Subset of a room's CONF_WINDOW_SENSORS that should show/log as a
        door rather than a window — purely cosmetic, same grace/off-temp/
        warning behaviour either way. See const.py's
        CONF_DOOR_STYLED_SENSORS."""
        for room in self.rooms:
            if room.get("room_name") == room_name:
                return list(room.get(CONF_DOOR_STYLED_SENSORS, []) or [])
        return []

    def get_room_heated_doors(self, room_name: str) -> list[str]:
        """A room's configured heated-area door sensors (front door onto a
        heated stairwell, etc.) — no heat-suppression meaning, visibility +
        log only. See const.py's CONF_HEATED_DOOR_SENSORS."""
        for room in self.rooms:
            if room.get("room_name") == room_name:
                return list(room.get(CONF_HEATED_DOOR_SENSORS, []) or [])
        return []

    def is_room_heated_door_open(self, room_name: str) -> bool:
        """True if ANY of this room's heated-area doors is currently open."""
        for sensor_id in self.get_room_heated_doors(room_name):
            state = self.hass.states.get(sensor_id)
            if state and state.state == "on":
                return True
        return False

    def get_room_window_sources(self, room: dict[str, Any]) -> list[str]:
        """Everything that counts as a window for this room (v0.64.0): its
        contact sensors plus — when CONF_TRV_WINDOW_DETECTION is on — the
        climate entities of its Netatmo valves, whose `open_window`
        attribute is Netatmo's own detection."""
        sources = [s for s in room.get(CONF_WINDOW_SENSORS, []) or [] if s]
        if room.get(CONF_TRV_WINDOW_DETECTION):
            for trv in self.get_room_trvs(room.get("room_name", "")):
                climate_id = self.get_trv_climate_entity(trv)
                if (
                    climate_id
                    and climate_id not in sources
                    and trv.get(CONF_TRV_TYPE, "netatmo") == "netatmo"
                ):
                    sources.append(climate_id)
        return sources

    def is_window_source_open(self, entity_id: str) -> bool:
        """True if a window source reports open — see window_source_open()."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return bool(
            window_source_open(
                entity_id.split(".", 1)[0],
                state.state,
                state.attributes.get("open_window"),
            )
        )

    def any_window_open(self) -> bool:
        return any(
            self.is_window_source_open(sid)
            for room in self.rooms
            for sid in self.get_room_window_sources(room)
        )

    def someone_home(self) -> bool:
        for person in self.persons:
            if not person.get("person_tracking", True):
                continue
            entity_id = person.get("person_entity", "")
            state = self.hass.states.get(entity_id)
            if state and state.state == "home":
                return True
        return False

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

    def get_room_co2_threshold(self, room_name: str) -> int:
        """Return the CO₂ ventilation threshold (ppm) for a room.

        Uses per-room CONF_CO2_THRESHOLD when configured, otherwise falls
        back to the global DEFAULT_CO2_VENTILATION_THRESHOLD.
        """
        from ..const import CONF_CO2_THRESHOLD, DEFAULT_CO2_VENTILATION_THRESHOLD

        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            val = room.get(CONF_CO2_THRESHOLD)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
            break
        return DEFAULT_CO2_VENTILATION_THRESHOLD

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

    def get_room_lux(self, room_name: str) -> float | None:
        """Return current illuminance (lux) for a room, or None (2026-09-14,
        punkt 7 — solar gain). Same optional-per-room pattern as
        get_room_co2() above — only rooms with CONF_LUX_SENSOR configured
        return a value; every other room is simply unaffected by solar gain.
        """
        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            entity_id = room.get(CONF_LUX_SENSOR) or None
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

    def get_sun_elevation(self) -> float | None:
        """Return sun.sun's current elevation (degrees above/below the
        horizon), or None if that entity doesn't exist (2026-09-14, punkt
        7). sun.sun is a built-in HA entity, always present on a normal HA
        install with no configuration needed — the None case only covers a
        genuinely broken/disabled core integration, not a missing setup
        step on the user's part, unlike every other optional sensor this
        coordinator reads.
        """
        state = self.hass.states.get("sun.sun")
        if state is None:
            return None
        raw = state.attributes.get("elevation")
        if raw is None:
            return None
        try:
            return float(raw)
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
        2./3. The room's HomeKit and cloud climate entities'
           current_temperature, in the order temp_source_order() gives for
           the cloud entity's owner (v0.62.1): NET-TRV (webhook, 0.1 °C)
           before HomeKit; HomeKit (local, live) before core netatmo
           (polled) and anything else.

        Returns None only if all sources are unavailable — a value outside
        _ROOM_TEMP_SANITY_MIN/_MAX (3.5 hardening: a glitching sensor can
        report e.g. -200 or 3000 instead of going unavailable) also counts
        as unavailable rather than being fed into the PID/schedule logic.
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
                        val = sanity_clamp_temp(float(state.state))
                        if val is not None:
                            return val
                    except (TypeError, ValueError):
                        pass
            break  # room found, external sensor absent or unavailable

        hk_id = self.get_homekit_climate_entity(room_name)
        for source in temp_source_order(self._entity_netatmo_backend(climate_id)):
            if source == TEMP_SOURCE_HOMEKIT:
                # HomeKit reports "off" when unreachable — not a usable reading
                val = self._climate_current_temp(
                    hk_id, ("unavailable", "unknown", "off")
                )
            else:
                val = self._climate_current_temp(climate_id, ("unavailable", "unknown"))
            if val is not None:
                return val

        return None

    def _climate_current_temp(
        self, entity_id: str | None, bad_states: tuple[str, ...]
    ) -> float | None:
        """current_temperature of a climate entity, sanity-clamped; None if
        missing, in one of bad_states, or not a number."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if not state or state.state in bad_states:
            return None
        try:
            raw = state.attributes.get("current_temperature")
            return None if raw is None else sanity_clamp_temp(float(raw))
        except (TypeError, ValueError):
            return None

    def _refresh_outdoor_temperature(self) -> None:
        """
        Update self.outdoor_temperature from the best available source.

        Priority:
        1. CONF_OUTDOOR_TEMP_SENSOR — local weather station / Netatmo outdoor
           module / Aqara etc.  Updates every 5 min or faster; reflects the
           actual microclimate at the property rather than a forecast grid point.
        2. weather.* entity temperature attribute — existing behaviour, used as
           fallback when the dedicated sensor is absent or unavailable.
           Tries "temperature", "current_temperature" and "temp" attribute
           keys in that order (B12 fix), since not all weather integrations
           expose the same attribute name.
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
        for temp_key in ("temperature", "current_temperature", "temp"):
            temp = state.attributes.get(temp_key)
            if temp is None:
                continue
            try:
                self.outdoor_temperature = float(temp)
                break
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "Could not parse outdoor temperature '%s' from %s (%s)",
                    temp,
                    entity_id,
                    temp_key,
                )
                continue
