"""
Heat Manager — Config Flow

4-step setup wizard:
  Step 1: Season & global settings
  Step 2: Rooms (repeatable)
  Step 3: Persons (repeatable)
  Step 4: Notification preferences

Options flow allows editing global settings, managing rooms,
managing persons, and notification preferences after setup.

FIX: FlowResult → ConfigFlowResult (HA 2024+ correct type)
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_AWAY_TEMP_OVERRIDE,
    CONF_BATTERY_SENSOR,
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    CONF_BUTTON_MODE_TOGGLE_ENTITY,
    CONF_BUTTON_TEMP_DOWN_ENTITY,
    CONF_BUTTON_TEMP_UP_ENTITY,
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_CO2_SENSOR,
    CONF_CO2_THRESHOLD,
    CONF_COMFORT_TEMP,
    CONF_DOOR_ROOM_A,
    CONF_DOOR_ROOM_B,
    CONF_DOOR_SENSOR,
    CONF_DOORS,
    CONF_FF_MAX_CONTRIBUTION,
    CONF_FF_REFERENCE_OUTDOOR_TEMP,
    CONF_FF_WEIGHT,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_HOUSE_VOICE_ENABLED,
    CONF_HUMIDITY_SENSOR,
    CONF_INDOOR_WAKE_SENSOR,
    CONF_INDOOR_WAKE_THRESHOLD,
    CONF_ISSUE_ESCALATION_MINUTES,
    CONF_LUX_SENSOR,
    CONF_NIGHT_END_HOUR,
    CONF_NIGHT_SETBACK_ENABLED,
    CONF_NIGHT_SETBACK_TEMP,
    CONF_NIGHT_START_HOUR,
    CONF_NOTIFY_ISSUE_ESCALATION,
    CONF_NOTIFY_MOLD_RISK,
    CONF_NOTIFY_PREHEAT,
    CONF_NOTIFY_PRESENCE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_WINDOW_WARNING_30,
    CONF_NOTIFY_WINDOWS,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PAUSE_DURATION_MIN,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PERSONS,
    CONF_PI_DEMAND_ENTITY,
    CONF_PID_ENABLED,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_PRECIPITATION_SENSOR,
    CONF_PREHEAT_LEAD_TIME_MIN,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_SENSOR,
    CONF_ROOMS,
    CONF_SCHEDULE_ENTITY,
    CONF_SOLAR_GAIN_ENABLED,
    CONF_SOLAR_GAIN_LUX_THRESHOLD,
    CONF_SOLAR_GAIN_MAX_REDUCTION,
    CONF_SOLAR_GAIN_WEIGHT,
    CONF_SYNC_MODE,
    CONF_TRV_MAX_TEMP,
    CONF_TRV_TYPE,
    CONF_TRVS,
    CONF_WAKE_SETBACK_TEMP,
    CONF_WEATHER_COMPENSATION_ENABLED,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED_SENSOR,
    CONF_WINDOW_DELAY_DEFAULT_MIN,
    CONF_WINDOW_DELAY_MIN,
    CONF_WINDOW_OFF_TEMP,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_WARNING_MIN,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMP,
    DEFAULT_CO2_VENTILATION_THRESHOLD,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_GRACE_NIGHT_MIN,
    DEFAULT_INDOOR_WAKE_THRESHOLD,
    DEFAULT_ISSUE_ESCALATION_MINUTES,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_SETBACK_ENABLED,
    DEFAULT_NIGHT_SETBACK_TEMP,
    DEFAULT_NIGHT_START_HOUR,
    DEFAULT_PAUSE_DURATION_MIN,
    DEFAULT_PID_KD,
    DEFAULT_PID_KI,
    DEFAULT_PID_KP,
    DEFAULT_PREHEAT_LEAD_TIME_MIN,
    DEFAULT_SYNC_MODE,
    DEFAULT_TRV_MAX_TEMP,
    DEFAULT_WAKE_SETBACK_TEMP,
    DEFAULT_WEATHER_COMPENSATION_ENABLED,
    DEFAULT_WINDOW_DELAY_DEFAULT_MIN,
    DEFAULT_WINDOW_DELAY_MIN,
    DEFAULT_WINDOW_OFF_TEMP,
    DEFAULT_WINDOW_WARNING_MIN,
    DOMAIN,
    FF_MAX_CONTRIBUTION,
    FF_REFERENCE_OUTDOOR_TEMP,
    FF_WEIGHT,
    SOLAR_GAIN_LUX_THRESHOLD,
    SOLAR_GAIN_MAX_REDUCTION,
    SOLAR_GAIN_WEIGHT,
    SYNC_MODE_DISABLED,
    SYNC_MODE_LOCK,
    SYNC_MODE_MIRROR,
    TRV_TYPE_NETATMO,
)
from .migrations import migrate_room_to_trvs

_LOGGER = logging.getLogger(__name__)


# ── Shared schemas ────────────────────────────────────────────────────────────


def _step1_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            # default=vol.UNDEFINED (not "") — the entity selector rejects ""
            # as an invalid entity ID, which blocked saving whenever this
            # optional field was left empty. See B17.
            vol.Optional(
                CONF_WEATHER_ENTITY,
                default=defaults.get(CONF_WEATHER_ENTITY) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "weather"}}),
            # 2026-09-11 UX fix: these four were left on a raw text box (type
            # the entity_id yourself, no autocomplete, easy to typo) because
            # the entity selector used to reject an empty default outright.
            # CONF_WEATHER_ENTITY above and CONF_SCHEDULE_ENTITY below already
            # proved the fix — `default=... or vol.UNDEFINED` instead of
            # `default=..., ""` — so there's no reason left for these four to
            # be worse pickers than every other entity field in this flow.
            # Also makes it trivial to find e.g. an Indeklima room sensor:
            # type "indeklima" or the room name into the picker's own search.
            vol.Optional(
                CONF_OUTDOOR_TEMP_SENSOR,
                default=defaults.get(CONF_OUTDOOR_TEMP_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),
            vol.Optional(
                CONF_OUTDOOR_HUMIDITY_SENSOR,
                default=defaults.get(CONF_OUTDOOR_HUMIDITY_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),
            vol.Optional(
                CONF_PRECIPITATION_SENSOR,
                default=defaults.get(CONF_PRECIPITATION_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),
            vol.Optional(
                CONF_WIND_SPEED_SENSOR,
                default=defaults.get(CONF_WIND_SPEED_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),
            vol.Optional(
                CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, "")
            ): selector.selector({"text": {}}),
            vol.Optional(
                CONF_WINDOW_WARNING_MIN,
                default=defaults.get(
                    CONF_WINDOW_WARNING_MIN, DEFAULT_WINDOW_WARNING_MIN
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 5,
                        "max": 180,
                        "step": 5,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            # ── Window delay/off-temp defaults (v0.33.0) ─────────────────
            # window_delay_default_min is the ONE knob every room's window
            # open-delay actually uses today (window_engine.py no longer
            # reads the old per-room CONF_WINDOW_DELAY_MIN). window_off_temp
            # is the setpoint written on open — deliberately separate from
            # CONF_AWAY_TEMP_OVERRIDE below, which still floors the PID's
            # own idle output and the night/wake setback. See const.py.
            vol.Optional(
                CONF_WINDOW_DELAY_DEFAULT_MIN,
                default=defaults.get(
                    CONF_WINDOW_DELAY_DEFAULT_MIN, DEFAULT_WINDOW_DELAY_DEFAULT_MIN
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 0,
                        "max": 60,
                        "step": 1,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            vol.Optional(
                CONF_WINDOW_OFF_TEMP,
                default=defaults.get(CONF_WINDOW_OFF_TEMP, DEFAULT_WINDOW_OFF_TEMP),
            ): selector.selector(
                {
                    "number": {
                        "min": 5,
                        "max": 20,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            vol.Optional(
                CONF_GRACE_DAY_MIN,
                default=defaults.get(CONF_GRACE_DAY_MIN, DEFAULT_GRACE_DAY_MIN),
            ): selector.selector(
                {
                    "number": {
                        "min": 5,
                        "max": 120,
                        "step": 5,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            vol.Optional(
                CONF_GRACE_NIGHT_MIN,
                default=defaults.get(CONF_GRACE_NIGHT_MIN, DEFAULT_GRACE_NIGHT_MIN),
            ): selector.selector(
                {
                    "number": {
                        "min": 5,
                        "max": 60,
                        "step": 5,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            vol.Optional(
                CONF_AUTO_OFF_TEMP_THRESHOLD,
                default=defaults.get(
                    CONF_AUTO_OFF_TEMP_THRESHOLD, DEFAULT_AUTO_OFF_TEMP_THRESHOLD
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 10,
                        "max": 30,
                        "step": 1,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            vol.Optional(
                CONF_AUTO_OFF_TEMP_DAYS,
                default=defaults.get(
                    CONF_AUTO_OFF_TEMP_DAYS, DEFAULT_AUTO_OFF_TEMP_DAYS
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 1,
                        "max": 14,
                        "step": 1,
                        "unit_of_measurement": "days",
                    }
                }
            ),
            vol.Optional(
                CONF_NIGHT_SETBACK_ENABLED,
                default=defaults.get(
                    CONF_NIGHT_SETBACK_ENABLED, DEFAULT_NIGHT_SETBACK_ENABLED
                ),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_NIGHT_SETBACK_TEMP,
                default=defaults.get(
                    CONF_NIGHT_SETBACK_TEMP, DEFAULT_NIGHT_SETBACK_TEMP
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 0.5,
                        "max": 5.0,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            vol.Optional(
                CONF_NIGHT_START_HOUR,
                default=defaults.get(CONF_NIGHT_START_HOUR, DEFAULT_NIGHT_START_HOUR),
            ): selector.selector(
                {
                    "number": {
                        "min": 18,
                        "max": 23,
                        "step": 1,
                        "unit_of_measurement": "h",
                    }
                }
            ),
            vol.Optional(
                CONF_NIGHT_END_HOUR,
                default=defaults.get(CONF_NIGHT_END_HOUR, DEFAULT_NIGHT_END_HOUR),
            ): selector.selector(
                {"number": {"min": 4, "max": 10, "step": 1, "unit_of_measurement": "h"}}
            ),
            vol.Optional(
                CONF_HOUSE_VOICE_ENABLED,
                default=defaults.get(CONF_HOUSE_VOICE_ENABLED, False),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_PAUSE_DURATION_MIN,
                default=defaults.get(
                    CONF_PAUSE_DURATION_MIN, DEFAULT_PAUSE_DURATION_MIN
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 15,
                        "max": 480,
                        "step": 15,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            # ── Boost defaults (2026-09-13) ─────────────────────────────
            # Used by heat_manager.boost_start / heat_manager/boost_start
            # whenever the caller doesn't specify its own temperature/
            # duration_minutes — same bounds as services.yaml's own
            # boost_start selectors.
            vol.Optional(
                CONF_BOOST_DEFAULT_TEMP,
                default=defaults.get(CONF_BOOST_DEFAULT_TEMP, DEFAULT_BOOST_TEMP),
            ): selector.selector(
                {
                    "number": {
                        "min": 15,
                        "max": 32,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            vol.Optional(
                CONF_BOOST_DEFAULT_MINUTES,
                default=defaults.get(
                    CONF_BOOST_DEFAULT_MINUTES, DEFAULT_BOOST_MINUTES
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 1,
                        "max": 240,
                        "step": 1,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            # ── PID controller ─────────────────────────────────────────
            vol.Optional(
                CONF_PID_ENABLED,
                default=defaults.get(CONF_PID_ENABLED, True),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_PID_KP,
                default=defaults.get(CONF_PID_KP, DEFAULT_PID_KP),
            ): selector.selector({"number": {"min": 0, "max": 5, "step": 0.05}}),
            vol.Optional(
                CONF_PID_KI,
                default=defaults.get(CONF_PID_KI, DEFAULT_PID_KI),
            ): selector.selector({"number": {"min": 0, "max": 0.5, "step": 0.01}}),
            vol.Optional(
                CONF_PID_KD,
                default=defaults.get(CONF_PID_KD, DEFAULT_PID_KD),
            ): selector.selector({"number": {"min": 0, "max": 2, "step": 0.05}}),
            vol.Optional(
                CONF_TRV_MAX_TEMP,
                default=defaults.get(CONF_TRV_MAX_TEMP, DEFAULT_TRV_MAX_TEMP),
            ): selector.selector(
                {
                    "number": {
                        "min": 20,
                        "max": 32,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            # ── Weather compensation curve (2026-09-13, architecture review
            # #5) — the outdoor-temperature PID feedforward existed already
            # (const.py's FF_REFERENCE_OUTDOOR_TEMP/FF_WEIGHT/FF_MAX_CONTRIBUTION,
            # "Conservative defaults, not yet exposed in the UI") but was a
            # hardcoded, always-on constant with no toggle and no per-install
            # tuning. Defaults below match those exact hardcoded values, so an
            # existing install's behaviour is unchanged until it's actually
            # edited — only "exposed", nothing silently switched off.
            vol.Optional(
                CONF_WEATHER_COMPENSATION_ENABLED,
                default=defaults.get(
                    CONF_WEATHER_COMPENSATION_ENABLED,
                    DEFAULT_WEATHER_COMPENSATION_ENABLED,
                ),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_FF_REFERENCE_OUTDOOR_TEMP,
                default=defaults.get(
                    CONF_FF_REFERENCE_OUTDOOR_TEMP, FF_REFERENCE_OUTDOOR_TEMP
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": -10,
                        "max": 22,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            vol.Optional(
                CONF_FF_WEIGHT,
                default=defaults.get(CONF_FF_WEIGHT, FF_WEIGHT),
            ): selector.selector({"number": {"min": 0, "max": 0.1, "step": 0.005}}),
            vol.Optional(
                CONF_FF_MAX_CONTRIBUTION,
                default=defaults.get(CONF_FF_MAX_CONTRIBUTION, FF_MAX_CONTRIBUTION),
            ): selector.selector({"number": {"min": 0, "max": 0.6, "step": 0.05}}),
            # ── Solar gain (2026-09-14, punkt 7) ────────────────────
            # Per-room lux sensor (CONF_LUX_SENSOR, set on the room itself —
            # see _room_schema below) reduces PID power while the sun is up
            # and the room reads bright. Off by default — unlike weather
            # compensation above, there is no prior always-on behaviour to
            # preserve, so an upgrading install sees no change until this is
            # turned on AND at least one room has a lux sensor configured.
            vol.Optional(
                CONF_SOLAR_GAIN_ENABLED,
                default=defaults.get(
                    CONF_SOLAR_GAIN_ENABLED, DEFAULT_SOLAR_GAIN_ENABLED
                ),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_SOLAR_GAIN_LUX_THRESHOLD,
                default=defaults.get(
                    CONF_SOLAR_GAIN_LUX_THRESHOLD, SOLAR_GAIN_LUX_THRESHOLD
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 500,
                        "max": 30000,
                        "step": 500,
                        "unit_of_measurement": "lux",
                    }
                }
            ),
            vol.Optional(
                CONF_SOLAR_GAIN_WEIGHT,
                default=defaults.get(CONF_SOLAR_GAIN_WEIGHT, SOLAR_GAIN_WEIGHT),
            ): selector.selector({"number": {"min": 0, "max": 0.5, "step": 0.01}}),
            vol.Optional(
                CONF_SOLAR_GAIN_MAX_REDUCTION,
                default=defaults.get(
                    CONF_SOLAR_GAIN_MAX_REDUCTION, SOLAR_GAIN_MAX_REDUCTION
                ),
            ): selector.selector({"number": {"min": 0, "max": 0.8, "step": 0.05}}),
            # ── Wake / WAKING phase ────────────────────────────────────
            vol.Optional(
                CONF_INDOOR_WAKE_SENSOR,
                default=defaults.get(CONF_INDOOR_WAKE_SENSOR) or vol.UNDEFINED,
            ): selector.selector(
                {"entity": {"domain": "sensor"}}
            ),  # shared indoor temperature probe
            vol.Optional(
                CONF_INDOOR_WAKE_THRESHOLD,
                default=defaults.get(
                    CONF_INDOOR_WAKE_THRESHOLD, DEFAULT_INDOOR_WAKE_THRESHOLD
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 15,
                        "max": 25,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            vol.Optional(
                CONF_WAKE_SETBACK_TEMP,
                default=defaults.get(CONF_WAKE_SETBACK_TEMP, DEFAULT_WAKE_SETBACK_TEMP),
            ): selector.selector(
                {
                    "number": {
                        "min": 0.5,
                        "max": 5.0,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
        }
    )


def _trv_schema(defaults: dict | None = None) -> vol.Schema:
    """Schema for a single physical TRV within a room — see CONF_TRVS."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_CLIMATE_ENTITY, default=defaults.get(CONF_CLIMATE_ENTITY, "")
            ): selector.selector({"entity": {"domain": "climate"}}),
            vol.Optional(
                CONF_HOMEKIT_CLIMATE_ENTITY,
                default=defaults.get(CONF_HOMEKIT_CLIMATE_ENTITY, ""),
            ): selector.selector({"text": {}}),
            vol.Optional(
                CONF_TRV_TYPE, default=defaults.get(CONF_TRV_TYPE, TRV_TYPE_NETATMO)
            ): selector.selector(
                {
                    "select": {
                        "options": [
                            {
                                "value": "netatmo",
                                "label": "Netatmo NRV (preset_mode: away/schedule)",
                            },
                            {
                                "value": "zigbee",
                                "label": "Zigbee TRV via Z2M (hvac_mode: off/heat)",
                            },
                        ]
                    }
                }
            ),
            vol.Optional(
                CONF_PI_DEMAND_ENTITY, default=defaults.get(CONF_PI_DEMAND_ENTITY, "")
            ): selector.selector({"text": {}}),
            # ── Calibration & Sync (v0.9.0) ─────────────────────────────────────
            # number.* entity the TRV's own integration exposes to correct its
            # internal reading (e.g. Zigbee2MQTT local_temperature_calibration).
            # Only used when the room's CONF_ROOM_TEMP_SENSOR is also set —
            # see engine/calibration_engine.py.
            # default=vol.UNDEFINED (not "") — the entity selector rejects ""
            # as an invalid entity ID, which blocked saving whenever this
            # optional field was left empty. See B17.
            vol.Optional(
                CONF_CALIBRATION_ENTITY,
                default=defaults.get(CONF_CALIBRATION_ENTITY) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "number"}}),
            vol.Optional(
                CONF_SYNC_MODE,
                default=defaults.get(CONF_SYNC_MODE, DEFAULT_SYNC_MODE),
            ): selector.selector(
                {
                    "select": {
                        "options": [
                            {
                                "value": SYNC_MODE_DISABLED,
                                "label": "Disabled — ignore manual changes",
                            },
                            {
                                "value": SYNC_MODE_MIRROR,
                                "label": "Mirror — accept manual changes (switches room to override)",
                            },
                            {
                                "value": SYNC_MODE_LOCK,
                                "label": "Lock — revert manual changes back to the expected setpoint",
                            },
                        ]
                    }
                }
            ),
        }
    )


def _room_schema(defaults: dict | None = None) -> vol.Schema:
    """Schema for a room's own fields — its TRVs are managed separately
    through the room-TRV sub-flow (see _trv_schema and CONF_TRVS)."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ROOM_NAME, default=defaults.get(CONF_ROOM_NAME, "")
            ): selector.selector({"text": {}}),
            vol.Optional(
                CONF_WINDOW_SENSORS, default=defaults.get(CONF_WINDOW_SENSORS, [])
            ): selector.selector(
                {"entity": {"domain": "binary_sensor", "multiple": True}}
            ),
            vol.Optional(
                CONF_WINDOW_DELAY_MIN,
                default=defaults.get(CONF_WINDOW_DELAY_MIN, DEFAULT_WINDOW_DELAY_MIN),
            ): selector.selector(
                {
                    "number": {
                        "min": 1,
                        "max": 30,
                        "step": 1,
                        "unit_of_measurement": "min",
                    }
                }
            ),
            vol.Optional(
                CONF_AWAY_TEMP_OVERRIDE,
                default=defaults.get(CONF_AWAY_TEMP_OVERRIDE, 10),
            ): selector.selector(
                {
                    "number": {
                        "min": 5,
                        "max": 20,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            # PID target temperature — v0.19.0: authoritative for ALL room
            # types, Netatmo included (previously ignored for Netatmo rooms,
            # which used the cloud entity's own schedule setpoint instead).
            vol.Optional(
                CONF_COMFORT_TEMP,
                default=defaults.get(CONF_COMFORT_TEMP, DEFAULT_COMFORT_TEMP),
            ): selector.selector(
                {
                    "number": {
                        "min": 15,
                        "max": 26,
                        "step": 0.5,
                        "unit_of_measurement": "°C",
                    }
                }
            ),
            # ── Sensor inputs ─────────────────────────────────────────────────
            # 2026-09-11 UX fix: same as _step1_schema above — real entity
            # pickers (searchable, no typos) instead of raw text boxes, now
            # that the `default=... or vol.UNDEFINED` pattern is proven safe
            # for an optional entity selector. Also makes it trivial to pick
            # e.g. this room's own Indeklima sensor by typing "indeklima" or
            # the room name into the picker's search — no hard dependency on
            # Indeklima, any sensor entity still works exactly as before.
            vol.Optional(
                CONF_CO2_SENSOR,
                default=defaults.get(CONF_CO2_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),  # CO₂ in ppm
            vol.Optional(
                CONF_CO2_THRESHOLD,
                default=defaults.get(
                    CONF_CO2_THRESHOLD, DEFAULT_CO2_VENTILATION_THRESHOLD
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 500,
                        "max": 2000,
                        "step": 50,
                        "unit_of_measurement": "ppm",
                    }
                }
            ),
            vol.Optional(
                CONF_ROOM_TEMP_SENSOR,
                default=defaults.get(CONF_ROOM_TEMP_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),  # room temp °C
            vol.Optional(
                CONF_BATTERY_SENSOR,
                default=defaults.get(CONF_BATTERY_SENSOR) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "sensor"}}),  # TRV battery %
            vol.Optional(
                CONF_HUMIDITY_SENSOR,
                default=defaults.get(CONF_HUMIDITY_SENSOR) or vol.UNDEFINED,
            ): selector.selector(
                {"entity": {"domain": "sensor"}}
            ),  # relative humidity %
            # ── Schedule / calendar override (v0.9.0, Fase D) ───────────────────
            # schedule.* or calendar.* entity — see engine/schedule_engine.py.
            # While a block/event is active, its temperature overrides this
            # room's normal target. Optional; leave empty to disable.
            # default=vol.UNDEFINED (not "") — the entity selector rejects ""
            # as an invalid entity ID, which blocked saving whenever this
            # optional field was left empty. See B17.
            vol.Optional(
                CONF_SCHEDULE_ENTITY,
                default=defaults.get(CONF_SCHEDULE_ENTITY) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": ["schedule", "calendar"]}}),
        }
    )


def _person_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_PERSON_ENTITY, default=defaults.get(CONF_PERSON_ENTITY, "")
            ): selector.selector({"entity": {"domain": "person"}}),
            vol.Optional(
                CONF_PERSON_TRACKING, default=defaults.get(CONF_PERSON_TRACKING, True)
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_PREHEAT_LEAD_TIME_MIN,
                default=defaults.get(
                    CONF_PREHEAT_LEAD_TIME_MIN, DEFAULT_PREHEAT_LEAD_TIME_MIN
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 5,
                        "max": 90,
                        "step": 5,
                        "unit_of_measurement": "min",
                    }
                }
            ),
        }
    )


def _door_schema(
    defaults: dict | None = None, room_names: list[str] | None = None
) -> vol.Schema:
    """Schema for one interior door — a contact sensor plus the two rooms it
    connects (see CONF_DOORS in const.py for the modeling rationale: unlike
    CONF_WINDOW_SENSORS, a door belongs to a PAIR of rooms, not one)."""
    defaults = defaults or {}
    room_names = room_names or []
    room_options = [{"value": name, "label": name} for name in room_names]
    return vol.Schema(
        {
            vol.Required(
                CONF_DOOR_SENSOR, default=defaults.get(CONF_DOOR_SENSOR, "")
            ): selector.selector({"entity": {"domain": "binary_sensor"}}),
            vol.Required(
                CONF_DOOR_ROOM_A, default=defaults.get(CONF_DOOR_ROOM_A, "")
            ): selector.selector({"select": {"options": room_options}}),
            vol.Required(
                CONF_DOOR_ROOM_B, default=defaults.get(CONF_DOOR_ROOM_B, "")
            ): selector.selector({"select": {"options": room_options}}),
        }
    )


def _notifications_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_NOTIFY_PRESENCE, default=defaults.get(CONF_NOTIFY_PRESENCE, True)
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_NOTIFY_WINDOWS, default=defaults.get(CONF_NOTIFY_WINDOWS, True)
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_NOTIFY_WINDOW_WARNING_30,
                default=defaults.get(CONF_NOTIFY_WINDOW_WARNING_30, True),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_NOTIFY_PREHEAT, default=defaults.get(CONF_NOTIFY_PREHEAT, True)
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_NOTIFY_MOLD_RISK,
                default=defaults.get(CONF_NOTIFY_MOLD_RISK, True),
            ): selector.selector({"boolean": {}}),
            # 2026-09-13 (architecture review #4) — generic escalation net on
            # top of every category above (plus categories with no dedicated
            # notifier of their own, e.g. heat-up-rate anomaly): one push once
            # an issue's been continuously active this many minutes. See
            # coordinator.py's _report_issue().
            vol.Optional(
                CONF_NOTIFY_ISSUE_ESCALATION,
                default=defaults.get(CONF_NOTIFY_ISSUE_ESCALATION, True),
            ): selector.selector({"boolean": {}}),
            vol.Optional(
                CONF_ISSUE_ESCALATION_MINUTES,
                default=defaults.get(
                    CONF_ISSUE_ESCALATION_MINUTES, DEFAULT_ISSUE_ESCALATION_MINUTES
                ),
            ): selector.selector(
                {
                    "number": {
                        "min": 10,
                        "max": 360,
                        "step": 10,
                        "unit_of_measurement": "min",
                    }
                }
            ),
        }
    )


def _remote_control_schema(defaults: dict | None = None) -> vol.Schema:
    """Global physical remote (e.g. Aqara Climate Sensor W100) — see
    const.py's "Remote button control" section and engine/remote_button_engine.py.
    All 3 fields are optional `event.*` entities, independently configurable
    so any button/remote hardware can be assigned, not just one specific model.
    """
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_BUTTON_TEMP_UP_ENTITY,
                default=defaults.get(CONF_BUTTON_TEMP_UP_ENTITY) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "event"}}),
            vol.Optional(
                CONF_BUTTON_TEMP_DOWN_ENTITY,
                default=defaults.get(CONF_BUTTON_TEMP_DOWN_ENTITY) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "event"}}),
            vol.Optional(
                CONF_BUTTON_MODE_TOGGLE_ENTITY,
                default=defaults.get(CONF_BUTTON_MODE_TOGGLE_ENTITY) or vol.UNDEFINED,
            ): selector.selector({"entity": {"domain": "event"}}),
        }
    )


# ── Config Flow ───────────────────────────────────────────────────────────────


class HeatManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup wizard."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict] = []
        self._persons: list[dict] = []
        self._room_draft: dict[str, Any] | None = None
        self._trv_draft: list[dict] = []
        self._editing_trv_index: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            weather = user_input.get(CONF_WEATHER_ENTITY, "")
            if weather and self.hass.states.get(weather) is None:
                errors[CONF_WEATHER_ENTITY] = "entity_not_found"
            if not errors:
                self._data.update(user_input)
                return await self.async_step_room()

        return self.async_show_form(
            step_id="user",
            data_schema=_step1_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()

            if room_name:
                existing_names = [r[CONF_ROOM_NAME].lower() for r in self._rooms]
                if room_name.lower() in existing_names:
                    errors[CONF_ROOM_NAME] = "duplicate_room"
                else:
                    user_input[CONF_ROOM_NAME] = room_name
                    self._room_draft = user_input
                    self._trv_draft = []
                    return await self.async_step_room_trvs_menu()

        return self.async_show_form(
            step_id="room",
            data_schema=_room_schema(user_input or {}),
            errors=errors,
            description_placeholders={"room_count": str(len(self._rooms))},
        )

    async def async_step_room_trvs_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add/edit/delete this room's TRVs before it's saved.

        2026-09-11: zero TRVs is a deliberate, supported choice (a
        monitoring-only room — temp/humidity sensor, no heat source of its
        own, e.g. a hallway) — previously required at least one, mirroring
        CONF_CLIMATE_ENTITY's old Required status at the room level, but
        every engine already tolerates an empty TRV list gracefully."""
        assert self._room_draft is not None

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_room_trv_add()
            if action and action.startswith("edit:"):
                self._editing_trv_index = int(action[len("edit:") :])
                return await self.async_step_room_trv_edit()
            if action and action.startswith("delete:"):
                del self._trv_draft[int(action[len("delete:") :])]
                return await self.async_step_room_trvs_menu()
            if action in ("done_add_room", "done"):
                self._room_draft[CONF_TRVS] = self._trv_draft
                # 2026-09 audit fix: mirror trvs[0]'s fields back onto the
                # room's flat keys (climate_entity, homekit_climate_entity,
                # trv_type, pi_demand_entity, calibration_entity) at save
                # time. Without this, a room saved through this per-TRV UI
                # had CONF_TRVS but no flat climate_entity at all — every
                # reader now goes through coordinator.get_climate_entity()
                # and friends instead, so this is now purely a compatibility
                # mirror (diagnostics/tests that still read the flat field
                # directly), not a functional dependency.
                self._room_draft = migrate_room_to_trvs(self._room_draft)
                self._rooms.append(self._room_draft)
                self._room_draft = None
                self._trv_draft = []
                if action == "done_add_room":
                    return await self.async_step_room()
                self._data[CONF_ROOMS] = self._rooms
                return await self.async_step_person()

        options = [
            {
                "value": f"edit:{i}",
                "label": f"Edit: {trv[CONF_CLIMATE_ENTITY]}",
            }
            for i, trv in enumerate(self._trv_draft)
        ]
        options += [
            {
                "value": f"delete:{i}",
                "label": f"Delete: {trv[CONF_CLIMATE_ENTITY]}",
            }
            for i, trv in enumerate(self._trv_draft)
        ]
        options.append({"value": "add", "label": "Add a TRV"})
        if self._trv_draft:
            options.append(
                {"value": "done_add_room", "label": "Save room and add another room"}
            )
            options.append({"value": "done", "label": "Save room and continue"})
        else:
            # 2026-09-11: a room with zero TRVs is a deliberate, supported
            # choice — a monitoring-only room (temp/humidity sensor, no
            # heat source of its own, e.g. a hallway connecting every other
            # room) that every engine already tolerates gracefully:
            # get_climate_entity() returns None for it, and every "for trv
            # in get_room_trvs(room_name)" loop across the codebase simply
            # no-ops on an empty list. migrate_room_to_trvs() already had an
            # explicit `if not trvs: return room` early-out for exactly this
            # case. Labelled explicitly here so it reads as an intentional
            # choice on the "Save room" button itself, not a silently
            # accepted gap — see planning/heat_manager_features_2026-09-11.md
            # follow-up conversation (the "Gang" hallway case).
            options.append(
                {
                    "value": "done_add_room",
                    "label": "Save room without a TRV (monitoring only) and add another room",
                }
            )
            options.append(
                {
                    "value": "done",
                    "label": "Save room without a TRV (monitoring only)",
                }
            )

        return self.async_show_form(
            step_id="room_trvs_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.selector(
                        {"select": {"options": options}}
                    )
                }
            ),
            description_placeholders={
                "room_name": self._room_draft[CONF_ROOM_NAME],
                "trv_count": str(len(self._trv_draft)),
            },
        )

    async def async_step_room_trv_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            climate = user_input.get(CONF_CLIMATE_ENTITY, "")
            if self.hass.states.get(climate) is None:
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            else:
                self._trv_draft.append(user_input)
                return await self.async_step_room_trvs_menu()

        return self.async_show_form(
            step_id="room_trv_add", data_schema=_trv_schema(), errors=errors
        )

    async def async_step_room_trv_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        idx = self._editing_trv_index
        assert idx is not None

        if user_input is not None:
            climate = user_input.get(CONF_CLIMATE_ENTITY, "")
            if self.hass.states.get(climate) is None:
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            else:
                self._trv_draft[idx] = user_input
                return await self.async_step_room_trvs_menu()

        return self.async_show_form(
            step_id="room_trv_edit",
            data_schema=_trv_schema(self._trv_draft[idx]),
            errors=errors,
        )

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.pop("_action", "add_more")
            person = user_input.get(CONF_PERSON_ENTITY, "")

            if person:
                existing = [p[CONF_PERSON_ENTITY] for p in self._persons]
                if person in existing:
                    errors[CONF_PERSON_ENTITY] = "duplicate_person"
                elif self.hass.states.get(person) is None:
                    errors[CONF_PERSON_ENTITY] = "entity_not_found"
                else:
                    self._persons.append(dict(user_input))

            if not errors and action == "done":
                self._data[CONF_PERSONS] = self._persons
                return await self.async_step_presence_global()

        schema = vol.Schema(
            {
                **_person_schema(user_input or {}).schema,
                vol.Optional("_action", default="add_more"): selector.selector(
                    {
                        "select": {
                            "options": [
                                {
                                    "value": "add_more",
                                    "label": "Save and add another person",
                                },
                                {"value": "done", "label": "Save and continue"},
                            ]
                        }
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="person",
            data_schema=schema,
            errors=errors,
            description_placeholders={"person_count": str(len(self._persons))},
        )

    async def async_step_presence_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_notifications()

        return self.async_show_form(
            step_id="presence_global",
            data_schema=vol.Schema(
                {
                    # default=vol.UNDEFINED (not "") — the entity selector
                    # rejects "" as an invalid entity ID, which blocked
                    # saving whenever this optional field was left empty.
                    # See B17.
                    vol.Optional(
                        CONF_ALARM_PANEL, default=vol.UNDEFINED
                    ): selector.selector({"entity": {"domain": "alarm_control_panel"}}),
                }
            ),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="Heat Manager", data=self._data)

        return self.async_show_form(
            step_id="notifications",
            data_schema=_notifications_schema(),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HeatManagerOptionsFlow:
        return HeatManagerOptionsFlow(config_entry)


# ── Options Flow ──────────────────────────────────────────────────────────────


class HeatManagerOptionsFlow(config_entries.OptionsFlow):
    """Post-setup options: edit global, manage rooms/persons, notifications."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._rooms: list[dict] = []
        self._persons: list[dict] = []
        self._doors: list[dict] = []
        self._editing_room_name: str | None = None
        self._editing_person_entity: str | None = None
        self._editing_door_sensor: str | None = None
        self._room_draft: dict[str, Any] | None = None
        self._trv_draft: list[dict] = []
        self._editing_trv_index: int | None = None

    def _current(self) -> dict:
        return {**self._config_entry.data, **self._config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            section = user_input.get("section")
            if section == "global":
                return await self.async_step_global()
            if section == "rooms":
                return await self.async_step_rooms_menu()
            if section == "persons":
                return await self.async_step_persons_menu()
            if section == "doors":
                return await self.async_step_doors_menu()
            if section == "notifications":
                return await self.async_step_notifications()
            if section == "remote_control":
                return await self.async_step_remote_control()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("section"): selector.selector(
                        {
                            "select": {
                                "options": [
                                    {
                                        "value": "global",
                                        "label": "Season & global settings",
                                    },
                                    {"value": "rooms", "label": "Manage rooms"},
                                    {"value": "persons", "label": "Manage persons"},
                                    {
                                        "value": "doors",
                                        "label": "Manage interior doors",
                                    },
                                    {
                                        "value": "notifications",
                                        "label": "Notification preferences",
                                    },
                                    {
                                        "value": "remote_control",
                                        "label": "Remote control",
                                    },
                                ]
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._current(), **user_input})
        return self.async_show_form(
            step_id="global",
            data_schema=_step1_schema(self._current()),
        )

    async def async_step_rooms_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current_rooms = self._current().get(CONF_ROOMS, [])

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._rooms = list(current_rooms)
                return await self.async_step_room_add()
            if action and action.startswith("edit:"):
                room_name = action[len("edit:") :]
                self._rooms = list(current_rooms)
                self._editing_room_name = room_name
                return await self.async_step_room_edit()
            if action and action.startswith("delete:"):
                room_name = action[len("delete:") :]
                updated = [
                    r for r in current_rooms if r.get(CONF_ROOM_NAME) != room_name
                ]
                return self.async_create_entry(
                    data={**self._current(), CONF_ROOMS: updated}
                )

        options = [
            {
                "value": f"edit:{r[CONF_ROOM_NAME]}",
                "label": f"Edit: {r[CONF_ROOM_NAME]}",
            }
            for r in current_rooms
        ]
        options += [
            {
                "value": f"delete:{r[CONF_ROOM_NAME]}",
                "label": f"Delete: {r[CONF_ROOM_NAME]}",
            }
            for r in current_rooms
        ]
        options.append({"value": "add", "label": "Add a new room"})

        return self.async_show_form(
            step_id="rooms_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.selector(
                        {"select": {"options": options}}
                    )
                }
            ),
            description_placeholders={"room_count": str(len(current_rooms))},
        )

    async def async_step_room_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        original_name = self._editing_room_name
        current_room = next(
            (r for r in self._rooms if r.get(CONF_ROOM_NAME) == original_name), None
        )
        if current_room is None:
            return await self.async_step_rooms_menu()

        if user_input is not None:
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()
            other_names = [
                r[CONF_ROOM_NAME].lower()
                for r in self._rooms
                if r.get(CONF_ROOM_NAME) != original_name
            ]

            if room_name.lower() in other_names:
                errors[CONF_ROOM_NAME] = "duplicate_room"
            else:
                user_input[CONF_ROOM_NAME] = room_name
                self._room_draft = user_input
                self._trv_draft = list(current_room.get(CONF_TRVS, []))
                return await self.async_step_room_trvs_menu()

        # Read-only summary of this room's already-configured TRVs, shown on
        # this first screen — the actual add/edit/delete UI for them is the
        # next step (room_trvs_menu), but users kept expecting to see what's
        # already there before getting that far.
        trv_summary = (
            ", ".join(
                trv.get(CONF_CLIMATE_ENTITY, "?")
                for trv in current_room.get(CONF_TRVS, [])
            )
            or "none yet"
        )

        return self.async_show_form(
            step_id="room_edit",
            data_schema=_room_schema(current_room),
            errors=errors,
            description_placeholders={
                "room_name": original_name,
                "trv_summary": trv_summary,
            },
        )

    async def async_step_room_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()
            existing_names = [r[CONF_ROOM_NAME].lower() for r in self._rooms]

            if room_name.lower() in existing_names:
                errors[CONF_ROOM_NAME] = "duplicate_room"
            else:
                user_input[CONF_ROOM_NAME] = room_name
                self._room_draft = user_input
                self._trv_draft = []
                return await self.async_step_room_trvs_menu()

        return self.async_show_form(
            step_id="room_add",
            data_schema=_room_schema(),
            errors=errors,
        )

    async def async_step_room_trvs_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add/edit/delete this room's TRVs before it's saved.

        2026-09-11: zero TRVs is a deliberate, supported choice (a
        monitoring-only room — temp/humidity sensor, no heat source of its
        own, e.g. a hallway) — previously required at least one, mirroring
        CONF_CLIMATE_ENTITY's old Required status at the room level, but
        every engine already tolerates an empty TRV list gracefully."""
        assert self._room_draft is not None

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_room_trv_add()
            if action and action.startswith("edit:"):
                self._editing_trv_index = int(action[len("edit:") :])
                return await self.async_step_room_trv_edit()
            if action and action.startswith("delete:"):
                del self._trv_draft[int(action[len("delete:") :])]
                return await self.async_step_room_trvs_menu()
            if action == "done":
                self._room_draft[CONF_TRVS] = self._trv_draft
                # 2026-09 audit fix — see the identical comment in the
                # initial config flow's async_step_room_trvs_menu().
                self._room_draft = migrate_room_to_trvs(self._room_draft)
                original_name = self._editing_room_name
                if original_name is not None:
                    updated_rooms = [
                        self._room_draft
                        if r.get(CONF_ROOM_NAME) == original_name
                        else r
                        for r in self._rooms
                    ]
                else:
                    updated_rooms = [*self._rooms, self._room_draft]
                return self.async_create_entry(
                    data={**self._current(), CONF_ROOMS: updated_rooms}
                )

        options = [
            {
                "value": f"edit:{i}",
                "label": f"Edit: {trv[CONF_CLIMATE_ENTITY]}",
            }
            for i, trv in enumerate(self._trv_draft)
        ]
        options += [
            {
                "value": f"delete:{i}",
                "label": f"Delete: {trv[CONF_CLIMATE_ENTITY]}",
            }
            for i, trv in enumerate(self._trv_draft)
        ]
        options.append({"value": "add", "label": "Add a TRV"})
        # 2026-09-11: a room with zero TRVs is a deliberate, supported choice
        # (monitoring-only room, e.g. a hallway) — see the identical comment
        # in the initial config flow's async_step_room_trvs_menu() for why
        # this is safe everywhere else in the codebase. Always offer "Save
        # room" now, just with a label that makes the zero-TRV case explicit
        # rather than silently allowed.
        options.append(
            {
                "value": "done",
                "label": "Save room"
                if self._trv_draft
                else "Save room without a TRV (monitoring only)",
            }
        )

        return self.async_show_form(
            step_id="room_trvs_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.selector(
                        {"select": {"options": options}}
                    )
                }
            ),
            description_placeholders={
                "room_name": self._room_draft[CONF_ROOM_NAME],
                "trv_count": str(len(self._trv_draft)),
            },
        )

    async def async_step_room_trv_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            climate = user_input.get(CONF_CLIMATE_ENTITY, "")
            if self.hass.states.get(climate) is None:
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            else:
                self._trv_draft.append(user_input)
                return await self.async_step_room_trvs_menu()

        return self.async_show_form(
            step_id="room_trv_add", data_schema=_trv_schema(), errors=errors
        )

    async def async_step_room_trv_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        idx = self._editing_trv_index
        assert idx is not None

        if user_input is not None:
            climate = user_input.get(CONF_CLIMATE_ENTITY, "")
            if self.hass.states.get(climate) is None:
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            else:
                self._trv_draft[idx] = user_input
                return await self.async_step_room_trvs_menu()

        return self.async_show_form(
            step_id="room_trv_edit",
            data_schema=_trv_schema(self._trv_draft[idx]),
            errors=errors,
        )

    async def async_step_persons_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current_persons = self._current().get(CONF_PERSONS, [])

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._persons = list(current_persons)
                return await self.async_step_person_add()
            if action and action.startswith("edit:"):
                entity_id = action[len("edit:") :]
                self._persons = list(current_persons)
                self._editing_person_entity = entity_id
                return await self.async_step_person_edit()
            if action and action.startswith("delete:"):
                entity_id = action[len("delete:") :]
                updated = [
                    p for p in current_persons if p.get(CONF_PERSON_ENTITY) != entity_id
                ]
                return self.async_create_entry(
                    data={**self._current(), CONF_PERSONS: updated}
                )

        options = [
            {
                "value": f"edit:{p[CONF_PERSON_ENTITY]}",
                "label": f"Edit: {p[CONF_PERSON_ENTITY].split('.')[-1]}",
            }
            for p in current_persons
        ]
        options += [
            {
                "value": f"delete:{p[CONF_PERSON_ENTITY]}",
                "label": f"Delete: {p[CONF_PERSON_ENTITY].split('.')[-1]}",
            }
            for p in current_persons
        ]
        options.append({"value": "add", "label": "Add a new person"})

        return self.async_show_form(
            step_id="persons_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.selector(
                        {"select": {"options": options}}
                    )
                }
            ),
            description_placeholders={"person_count": str(len(current_persons))},
        )

    async def async_step_person_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        original_entity = self._editing_person_entity
        current_person = next(
            (p for p in self._persons if p.get(CONF_PERSON_ENTITY) == original_entity),
            None,
        )
        if current_person is None:
            return await self.async_step_persons_menu()

        if user_input is not None:
            person = user_input.get(CONF_PERSON_ENTITY, "")
            other_entities = [
                p[CONF_PERSON_ENTITY]
                for p in self._persons
                if p.get(CONF_PERSON_ENTITY) != original_entity
            ]

            if person in other_entities:
                errors[CONF_PERSON_ENTITY] = "duplicate_person"
            elif person and self.hass.states.get(person) is None:
                errors[CONF_PERSON_ENTITY] = "entity_not_found"
            else:
                updated_persons = [
                    dict(user_input)
                    if p.get(CONF_PERSON_ENTITY) == original_entity
                    else p
                    for p in self._persons
                ]
                return self.async_create_entry(
                    data={**self._current(), CONF_PERSONS: updated_persons}
                )

        return self.async_show_form(
            step_id="person_edit",
            data_schema=_person_schema(current_person),
            errors=errors,
            description_placeholders={"person_entity": original_entity},
        )

    async def async_step_person_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            person = user_input.get(CONF_PERSON_ENTITY, "")
            existing = [p[CONF_PERSON_ENTITY] for p in self._persons]
            if person in existing:
                errors[CONF_PERSON_ENTITY] = "duplicate_person"
            elif person and self.hass.states.get(person) is None:
                errors[CONF_PERSON_ENTITY] = "entity_not_found"
            else:
                self._persons.append(dict(user_input))
                return self.async_create_entry(
                    data={**self._current(), CONF_PERSONS: self._persons}
                )

        return self.async_show_form(
            step_id="person_add",
            data_schema=_person_schema(),
            errors=errors,
        )

    def _door_room_pair(self, door: dict[str, Any]) -> frozenset:
        return frozenset({door.get(CONF_DOOR_ROOM_A), door.get(CONF_DOOR_ROOM_B)})

    def _validate_door(
        self, user_input: dict[str, Any], other_doors: list[dict]
    ) -> dict[str, str]:
        """Shared validation for door add/edit. Returns an errors dict (empty
        if valid). Room-pair uniqueness and room_a != room_b are hard errors —
        a door is defined by its pair of rooms, so either mistake silently
        produces a meaningless or duplicate config. A door sensor that is
        ALSO configured as a window sensor elsewhere is only logged (2026-09-11
        proposal, item 1/2: soft warning, not a blocker — some contact sensors
        legitimately sit on a door that is both an interior passage and, in
        some floor plans, worth keeping as a window-suppression trigger too)."""
        errors: dict[str, str] = {}
        sensor = user_input.get(CONF_DOOR_SENSOR, "")
        room_a = user_input.get(CONF_DOOR_ROOM_A, "")
        room_b = user_input.get(CONF_DOOR_ROOM_B, "")

        if room_a and room_b and room_a == room_b:
            errors[CONF_DOOR_ROOM_B] = "same_room"
        elif frozenset({room_a, room_b}) in {
            self._door_room_pair(d) for d in other_doors
        }:
            errors["base"] = "duplicate_door_pair"
        elif sensor and self.hass.states.get(sensor) is None:
            errors[CONF_DOOR_SENSOR] = "entity_not_found"
        elif sensor in {d.get(CONF_DOOR_SENSOR) for d in other_doors}:
            errors[CONF_DOOR_SENSOR] = "duplicate_door_sensor"

        if not errors and sensor:
            current_rooms = self._current().get(CONF_ROOMS, [])
            for room in current_rooms:
                if sensor in room.get(CONF_WINDOW_SENSORS, []):
                    _LOGGER.warning(
                        "Door sensor '%s' is already configured as a window "
                        "sensor on room '%s' — this is allowed, but the same "
                        "contact will now drive both WindowEngine and "
                        "DoorEngine logic.",
                        sensor,
                        room.get(CONF_ROOM_NAME),
                    )
        return errors

    async def async_step_doors_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current_doors = self._current().get(CONF_DOORS, [])

        def _label(door: dict[str, Any]) -> str:
            sensor_name = door.get(CONF_DOOR_SENSOR, "").split(".")[-1]
            return (
                f"{door.get(CONF_DOOR_ROOM_A)} ↔ {door.get(CONF_DOOR_ROOM_B)} "
                f"({sensor_name})"
            )

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._doors = list(current_doors)
                return await self.async_step_door_add()
            if action and action.startswith("edit:"):
                sensor_id = action[len("edit:") :]
                self._doors = list(current_doors)
                self._editing_door_sensor = sensor_id
                return await self.async_step_door_edit()
            if action and action.startswith("delete:"):
                sensor_id = action[len("delete:") :]
                updated = [
                    d for d in current_doors if d.get(CONF_DOOR_SENSOR) != sensor_id
                ]
                return self.async_create_entry(
                    data={**self._current(), CONF_DOORS: updated}
                )

        options = [
            {"value": f"edit:{d[CONF_DOOR_SENSOR]}", "label": f"Edit: {_label(d)}"}
            for d in current_doors
        ]
        options += [
            {"value": f"delete:{d[CONF_DOOR_SENSOR]}", "label": f"Delete: {_label(d)}"}
            for d in current_doors
        ]
        options.append({"value": "add", "label": "Add a new interior door"})

        return self.async_show_form(
            step_id="doors_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.selector(
                        {"select": {"options": options}}
                    )
                }
            ),
            description_placeholders={"door_count": str(len(current_doors))},
        )

    async def async_step_door_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        original_sensor = self._editing_door_sensor
        current_door = next(
            (d for d in self._doors if d.get(CONF_DOOR_SENSOR) == original_sensor),
            None,
        )
        if current_door is None:
            return await self.async_step_doors_menu()

        other_doors = [
            d for d in self._doors if d.get(CONF_DOOR_SENSOR) != original_sensor
        ]
        room_names = [r[CONF_ROOM_NAME] for r in self._current().get(CONF_ROOMS, [])]

        if user_input is not None:
            errors = self._validate_door(user_input, other_doors)
            if not errors:
                updated_doors = [
                    dict(user_input)
                    if d.get(CONF_DOOR_SENSOR) == original_sensor
                    else d
                    for d in self._doors
                ]
                return self.async_create_entry(
                    data={**self._current(), CONF_DOORS: updated_doors}
                )

        return self.async_show_form(
            step_id="door_edit",
            data_schema=_door_schema(current_door, room_names),
            errors=errors,
            description_placeholders={"door_sensor": original_sensor},
        )

    async def async_step_door_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        room_names = [r[CONF_ROOM_NAME] for r in self._current().get(CONF_ROOMS, [])]

        if user_input is not None:
            errors = self._validate_door(user_input, self._doors)
            if not errors:
                self._doors.append(dict(user_input))
                return self.async_create_entry(
                    data={**self._current(), CONF_DOORS: self._doors}
                )

        return self.async_show_form(
            step_id="door_add",
            data_schema=_door_schema(room_names=room_names),
            errors=errors,
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._current(), **user_input})
        return self.async_show_form(
            step_id="notifications",
            data_schema=_notifications_schema(self._current()),
        )

    async def async_step_remote_control(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._current(), **user_input})
        return self.async_show_form(
            step_id="remote_control",
            data_schema=_remote_control_schema(self._current()),
        )
