"""Constants for Heat Manager."""
from __future__ import annotations

from enum import StrEnum

DOMAIN = "heat_manager"
VERSION = "0.3.4"

# ── Config entry keys ────────────────────────────────────────────────────────

CONF_ROOMS = "rooms"
CONF_ROOM_NAME = "room_name"
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_WINDOW_SENSORS = "window_sensors"
CONF_WINDOW_DELAY_MIN = "window_delay_min"
CONF_AWAY_TEMP_OVERRIDE = "away_temp_override"

CONF_PERSONS = "persons"
CONF_PERSON_ENTITY = "person_entity"
CONF_PERSON_TRACKING = "person_tracking"

CONF_ALARM_PANEL = "alarm_panel"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_PREHEAT_LEAD_TIME_MIN = "preheat_lead_time_min"

CONF_AWAY_TEMP_MILD = "away_temp_mild"
CONF_AWAY_TEMP_COLD = "away_temp_cold"
CONF_MILD_THRESHOLD = "mild_threshold"

CONF_GRACE_DAY_MIN = "grace_day_min"
CONF_GRACE_NIGHT_MIN = "grace_night_min"
CONF_NIGHT_START_HOUR = "night_start_hour"
CONF_NIGHT_END_HOUR = "night_end_hour"

CONF_AUTO_OFF_TEMP_THRESHOLD = "auto_off_temp_threshold"
CONF_AUTO_OFF_TEMP_DAYS = "auto_off_temp_days"

CONF_NOTIFY_PRESENCE = "notify_presence"
CONF_NOTIFY_WINDOWS = "notify_windows"
CONF_NOTIFY_PREHEAT = "notify_preheat"
CONF_NOTIFY_WINDOW_WARNING_30 = "notify_window_warning_30"
CONF_ENERGY_TRACKING = "energy_tracking"

# ── PID controller ───────────────────────────────────────────────────────────

CONF_PID_KP = "pid_kp"
CONF_PID_KI = "pid_ki"
CONF_PID_KD = "pid_kd"
CONF_TRV_MAX_TEMP = "trv_max_temp"
CONF_PID_ENABLED = "pid_enabled"

# Per-room Netatmo HomeKit local entity (optional)
CONF_HOMEKIT_CLIMATE_ENTITY = "homekit_climate_entity"

# Per-room rated wattage for energy calculations
CONF_ROOM_WATTAGE = "room_wattage"

# Per-room TRV type
CONF_TRV_TYPE = "trv_type"
TRV_TYPE_NETATMO = "netatmo"
TRV_TYPE_ZIGBEE  = "zigbee"
TRV_TYPE_OPTIONS = [TRV_TYPE_NETATMO, TRV_TYPE_ZIGBEE]

# Per-room Z2M pi_heating_demand sensor entity (optional)
CONF_PI_DEMAND_ENTITY = "pi_demand_entity"

# ── Sensor inputs (optional, per-room) ───────────────────────────────────────

# CO₂ sensor — used for context-aware window notifications and waste
# classification.  When set, Heat Manager knows whether an open window is
# purposeful ventilation (high CO₂) or unnecessary heat loss (low CO₂).
CONF_CO2_SENSOR = "co2_sensor"

# Room temperature sensor — external, independent of the TRV's own probe.
# When set, the PID controller reads current_temperature from here instead
# of from the climate entity.  Improves accuracy for Zigbee TRVs whose
# built-in probe sits on the hot radiator body (typically 1–3 °C high).
CONF_ROOM_TEMP_SENSOR = "room_temp_sensor"

# Outdoor temperature sensor — local weather station, Netatmo outdoor
# module, Aqara, etc.  When set, overrides the temperature attribute read
# from the weather entity for all outdoor-temperature decisions
# (adaptive away setpoint, SeasonEngine, auto-off).
# Falls back to weather entity if this sensor is unavailable.
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_WINDOW_DELAY_MIN = 5
DEFAULT_WINDOW_CLOSE_DELAY_MIN = 2
DEFAULT_WINDOW_WARNING_MIN = 30
DEFAULT_AWAY_TEMP_MILD = 17.0
DEFAULT_AWAY_TEMP_COLD = 15.0
DEFAULT_MILD_THRESHOLD = 8.0
DEFAULT_GRACE_DAY_MIN = 30
DEFAULT_GRACE_NIGHT_MIN = 15
DEFAULT_NIGHT_START_HOUR = 23
DEFAULT_NIGHT_END_HOUR = 7
DEFAULT_PREHEAT_LEAD_TIME_MIN = 20
DEFAULT_AUTO_OFF_TEMP_THRESHOLD = 18.0
DEFAULT_AUTO_OFF_TEMP_DAYS = 5
DEFAULT_PAUSE_DURATION_MIN = 120

# PID defaults
DEFAULT_PID_KP: float = 0.5
DEFAULT_PID_KI: float = 0.02
DEFAULT_PID_KD: float = 0.0
DEFAULT_TRV_MAX_TEMP: float = 28.0
DEFAULT_ROOM_WATTAGE: int = 1000  # watts — typical panel radiator

# CO₂ threshold — above this level an open window is considered intentional
# ventilation rather than pure heat waste.  Used by WindowEngine to select
# notification wording and by WasteCalculator to reduce waste attribution.
DEFAULT_CO2_VENTILATION_THRESHOLD: int = 900  # ppm

# ── Controller state ──────────────────────────────────────────────────────────

class ControllerState(StrEnum):
    ON = "on"
    PAUSE = "pause"
    OFF = "off"

CONTROLLER_STATE_OPTIONS = [s.value for s in ControllerState]

# ── Season mode ───────────────────────────────────────────────────────────────

class SeasonMode(StrEnum):
    AUTO   = "auto"
    WINTER = "winter"
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"

SEASON_MODE_OPTIONS = [s.value for s in SeasonMode]

# Meteorological season boundaries (month, day) — internationally standard.
# Spring: Mar 1, Summer: Jun 1, Autumn: Sep 1, Winter: Dec 1.
METEO_SEASONS: list[tuple[int, int, SeasonMode]] = [
    (12, 1, SeasonMode.WINTER),
    (9,  1, SeasonMode.AUTUMN),
    (6,  1, SeasonMode.SUMMER),
    (3,  1, SeasonMode.SPRING),
]

# ── Room state ────────────────────────────────────────────────────────────────

class RoomState(StrEnum):
    NORMAL = "normal"
    WINDOW_OPEN = "window_open"
    AWAY = "away"
    PRE_HEAT = "pre_heat"
    OVERRIDE = "override"

# ── Auto-off reason ───────────────────────────────────────────────────────────

class AutoOffReason(StrEnum):
    NONE = "none"
    SEASON = "season"
    TEMPERATURE = "temperature"

# ── Preset modes ──────────────────────────────────────────────────────────────

PRESET_AWAY = "away"
PRESET_SCHEDULE = "schedule"
HVAC_OFF = "off"

# ── Notification action identifiers ───────────────────────────────────────────

ACTION_FORCE_HEATING_ON = "HM_FORCE_HEATING_ON"
ACTION_VIEW_WINDOWS = "HM_VIEW_WINDOWS"
ACTION_DISMISS = "HM_DISMISS"
ACTION_PAUSE_1H = "HM_PAUSE_1H"
ACTION_PAUSE_TODAY = "HM_PAUSE_TODAY"

# ── Services ──────────────────────────────────────────────────────────────────

SERVICE_SET_CONTROLLER_STATE = "set_controller_state"
SERVICE_PAUSE = "pause"
SERVICE_RESUME = "resume"
SERVICE_FORCE_ROOM_ON = "force_room_on"

# ── Platforms ─────────────────────────────────────────────────────────────────

PLATFORMS: list[str] = ["sensor", "binary_sensor", "select", "switch"]

# ── Coordinator update interval ───────────────────────────────────────────────

SCAN_INTERVAL_SECONDS = 60

# Netatmo cloud API — stagger multi-room calls to avoid 429 rate-limit errors
NETATMO_API_CALL_DELAY_SEC: float = 0.6

# ── Lovelace card resource path ───────────────────────────────────────────────

LOVELACE_RESOURCE_PATH = "/heat_manager/heat-manager-card.js"
