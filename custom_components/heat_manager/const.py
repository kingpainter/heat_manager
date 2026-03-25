"""Constants for Heat Manager."""
from __future__ import annotations

from enum import StrEnum

DOMAIN = "heat_manager"
VERSION = "0.2.1"

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

# ── Controller state ──────────────────────────────────────────────────────────

class ControllerState(StrEnum):
    ON = "on"
    PAUSE = "pause"
    OFF = "off"

CONTROLLER_STATE_OPTIONS = [s.value for s in ControllerState]

# ── Season mode ───────────────────────────────────────────────────────────────

class SeasonMode(StrEnum):
    AUTO = "auto"
    WINTER = "winter"
    SUMMER = "summer"

SEASON_MODE_OPTIONS = [s.value for s in SeasonMode]

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

# ── Lovelace card resource path ───────────────────────────────────────────────

LOVELACE_RESOURCE_PATH = "/heat_manager/heat-manager-card.js"
