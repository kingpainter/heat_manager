"""Constants for Heat Manager."""

from __future__ import annotations

from enum import StrEnum

DOMAIN = "heat_manager"
# 2026-09-10 audit fix: this VERSION constant used to feed the panel/card
# cache-busting query string, and had drifted from manifest.json's version
# before (stuck at "0.9.0" for several releases). panel.py now reads the
# version from manifest.json directly at runtime instead — the one and only
# source of truth — so this second, independently-maintained copy has been
# removed entirely rather than left to go stale again.

# ── Config entry keys ────────────────────────────────────────────────────────

CONF_ROOMS = "rooms"
CONF_ROOM_NAME = "room_name"
CONF_CLIMATE_ENTITY = "climate_entity"

# A room's physical TRVs. list[dict], each dict holding one TRV's own
# CONF_CLIMATE_ENTITY / CONF_HOMEKIT_CLIMATE_ENTITY / CONF_TRV_TYPE /
# CONF_PI_DEMAND_ENTITY / CONF_CALIBRATION_ENTITY / CONF_SYNC_MODE — see
# config_flow._trv_schema(). Rooms saved before this existed are migrated
# by async_migrate_entry() in __init__.py: the migrated room keeps its old
# flat fields too, mirrored from trvs[0], so every module that still reads
# room.get(CONF_CLIMATE_ENTITY) directly keeps working for the room's
# first/primary TRV. Multi-TRV control (grouping, mirroring the same
# target to every TRV) is not implemented yet — that's a follow-up change
# to coordinator.py and the engines.
CONF_TRVS = "trvs"
CONF_WINDOW_SENSORS = "window_sensors"
# Per-room field, set only via the options-flow room step. v0.33.0: no
# longer read by window_engine.py — see CONF_WINDOW_DELAY_DEFAULT_MIN below.
# Left in place (not migrated away) so nothing is lost for anyone who did
# customize a room's value; may become a real per-room override again in a
# future panel "edit per room" pass.
CONF_WINDOW_DELAY_MIN = "window_delay_min"
# 2026-09 audit fix: DEFAULT_WINDOW_WARNING_MIN existed with no matching
# CONF_ key — window_engine.py read the magic string "window_warning_min"
# directly, so this option had no config_flow field to set it from.
CONF_WINDOW_WARNING_MIN = "window_warning_min"

# v0.33.0: the one global knob that actually controls every room's window
# open-delay today (window_engine.py no longer reads the per-room
# CONF_WINDOW_DELAY_MIN above). Live-editable from the panel's Indstillinger
# → Vindue section, same pattern as CONF_BOOST_DEFAULT_TEMP/_MINUTES below.
CONF_WINDOW_DELAY_DEFAULT_MIN = "window_delay_default_min"

# v0.33.0: dedicated "heat is now off" temperature for the window-open path,
# deliberately separate from CONF_AWAY_TEMP_OVERRIDE. Before this, window
# engine reused away_temp_override for its write-on-open setpoint — but that
# same value also floors the PID's own idle (0%-demand) output and the
# night/wake setback (coordinator.get_room_target_temp()), so setting it to
# a "comfortable away temp" (e.g. 18°C) silently raised the PID's minimum
# floor everywhere, not just on window-open. This field is read only by
# window_engine.py; away_temp_override's PID/setback-floor role is
# unchanged. See audit/heat_manager_target_temp_analysis_2026-09-11.md for
# the original away_temp_override design and CHANGELOG [0.33.0] for this split.
CONF_WINDOW_OFF_TEMP = "window_off_temp"

CONF_AWAY_TEMP_OVERRIDE = "away_temp_override"

# ── Interior doors (2026-09-11) ──────────────────────────────────────────────
# An interior door connects TWO rooms — unlike CONF_WINDOW_SENSORS (which
# belongs to a single room and means "heat is escaping outside, suppress
# it"), an open interior door means heat is moving BETWEEN two rooms Heat
# Manager already controls. It carries no heat-suppression meaning on its
# own; DoorEngine only logs the state change and exposes it to
# CalibrationEngine, which learns a separate heat-up-rate profile per room
# for "door open" vs "door closed" (a room heats up faster with its door
# shut). list[dict] on the config entry, each dict:
#   CONF_DOOR_SENSOR  — binary_sensor.* (door/window class) contact sensor
#   CONF_DOOR_ROOM_A  — one side's CONF_ROOM_NAME
#   CONF_DOOR_ROOM_B  — the other side's CONF_ROOM_NAME
# See config_flow._door_schema(), coordinator.get_room_doors()/
# is_room_door_open(), and engine/door_engine.py.
CONF_DOORS = "doors"
CONF_DOOR_SENSOR = "door_sensor"
CONF_DOOR_ROOM_A = "door_room_a"
CONF_DOOR_ROOM_B = "door_room_b"

CONF_PERSONS = "persons"
CONF_PERSON_ENTITY = "person_entity"
CONF_PERSON_TRACKING = "person_tracking"

CONF_ALARM_PANEL = "alarm_panel"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_PREHEAT_LEAD_TIME_MIN = "preheat_lead_time_min"

# Panel Config tab — "Manuel TRV-kontrol" toggle (2026-09-13). Was
# session-scoped only (a plain JS field, reset on every page reload) —
# persisted to entry.options via heat_manager/update_config so it survives
# a reload/browser restart, same live-save pattern as alarm_panel/
# notify_service.
CONF_MANUAL_TRV_CONTROL = "manual_trv_control"
DEFAULT_MANUAL_TRV_CONTROL: bool = False

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
CONF_NOTIFY_MOLD_RISK = "notify_mold_risk"

# 2026-09-13 (architecture review #4) — generic status-center issue
# escalation: a warning/critical issue (mold risk, an open window, a
# heat-up-rate anomaly) still active after this many minutes gets ONE push
# notification, on top of/instead of that category's own instant notifier
# (some categories, like heat-up anomaly, have none of their own at all).
# See coordinator.py's _report_issue().
CONF_NOTIFY_ISSUE_ESCALATION = "notify_issue_escalation"
CONF_ISSUE_ESCALATION_MINUTES = "issue_escalation_minutes"
DEFAULT_ISSUE_ESCALATION_MINUTES: int = 60

# ── PID controller ───────────────────────────────────────────────────────────

CONF_PID_KP = "pid_kp"
CONF_PID_KI = "pid_ki"
CONF_PID_KD = "pid_kd"
CONF_TRV_MAX_TEMP = "trv_max_temp"
CONF_PID_ENABLED = "pid_enabled"

# Per-room Netatmo HomeKit local entity (optional)
CONF_HOMEKIT_CLIMATE_ENTITY = "homekit_climate_entity"

# Per-room TRV type
CONF_TRV_TYPE = "trv_type"
TRV_TYPE_NETATMO = "netatmo"
TRV_TYPE_ZIGBEE = "zigbee"
TRV_TYPE_OPTIONS = [TRV_TYPE_NETATMO, TRV_TYPE_ZIGBEE]

# Per-room Z2M pi_heating_demand sensor entity (optional)
CONF_PI_DEMAND_ENTITY = "pi_demand_entity"

# Per-room TRV calibration/offset entity — a `number.*` entity the TRV's own
# integration exposes to correct its internal temperature reading (e.g.
# Zigbee2MQTT's `local_temperature_calibration`). When set together with
# CONF_ROOM_TEMP_SENSOR, CalibrationEngine writes the delta between the
# external sensor and the TRV's own raw reading, so the device's internal
# control loop stays accurate even when Heat Manager's own writes are
# temporarily unavailable (network issue, HA restart, etc.).
CONF_CALIBRATION_ENTITY = "calibration_entity"

# Per-room sync mode — see engine/sync_engine.py. Governs what happens when
# a room's write entity is changed by something other than Heat Manager
# itself (the Netatmo app, a physical TRV dial, another automation).
CONF_SYNC_MODE = "sync_mode"
SYNC_MODE_DISABLED = "disabled"
SYNC_MODE_MIRROR = "mirror"
SYNC_MODE_LOCK = "lock"
SYNC_MODE_OPTIONS = [SYNC_MODE_DISABLED, SYNC_MODE_MIRROR, SYNC_MODE_LOCK]
DEFAULT_SYNC_MODE = SYNC_MODE_DISABLED

# Per-room schedule/calendar entity — see engine/schedule_engine.py. When
# set, a `schedule.*` entity's per-block "Additional data" (native HA
# feature) or a `calendar.*` entity's active-event "Description" (parsed as
# YAML, mirroring climate_group_helper's format) supplies a `temperature`
# that overrides CONF_COMFORT_TEMP for as long as the block/event is active.
# SeasonEngine is untouched — this is an optional extra layer, applied before
# the group offset and setbacks so both still stack on top of it.
CONF_SCHEDULE_ENTITY = "schedule_entity"

# ── Sensor inputs (optional, per-room) ───────────────────────────────────────

# CO₂ sensor — used for context-aware window notifications and waste
# classification.  When set, Heat Manager knows whether an open window is
# purposeful ventilation (high CO₂) or unnecessary heat loss (low CO₂).
CONF_CO2_SENSOR = "co2_sensor"

# Humidity sensor — used for mold risk detection (F6).
# When set together with CONF_ROOM_TEMP_SENSOR, the mold risk binary_sensor
# calculates whether surface temperature is below dewpoint at the current
# humidity level (DIN 4108-2 simplified: RH > 70% AND T_surface < T_dewpoint).
CONF_HUMIDITY_SENSOR = "humidity_sensor"

# Lux/illuminance sensor (2026-09-14, punkt 7 — solar gain) — optional,
# per-room. When set, PID's proactive power is reduced while the sun is up
# (sun.sun's elevation > 0) and this room's measured lux exceeds
# CONF_SOLAR_GAIN_LUX_THRESHOLD — a room getting direct/bright sun through
# its windows needs less TRV-delivered heat right now than the schedule
# alone would call for. Deliberately a MEASURED signal rather than a
# computed sun-position/window-orientation model: a lux reading already
# reflects cloud cover, curtains, and the season automatically, without
# needing the user to configure a room's compass orientation or Heat
# Manager to model shading. Only ever REDUCES power, never adds any — see
# coordinator._solar_gain_reduction(). Not every room needs one: only
# rooms with a lux sensor configured are affected, exactly like
# CONF_HUMIDITY_SENSOR/CONF_CO2_SENSOR above; a room without one is
# entirely unaffected, same today-and-forever fallback the rest of this
# codebase's optional per-room sensors already follow.
CONF_LUX_SENSOR = "lux_sensor"

# Room temperature sensor — external, independent of the TRV's own probe.
# When set, the PID controller reads current_temperature from here instead
# of from the climate entity.  Improves accuracy for Zigbee TRVs whose
# built-in probe sits on the hot radiator body (typically 1–3 °C high).
CONF_ROOM_TEMP_SENSOR = "room_temp_sensor"

# TRV battery level (%). Optional — Zigbee TRVs typically expose battery
# as a separate sensor.* entity (set this). When left empty, ws_get_state
# falls back to the "battery_level" attribute on the room's climate entity,
# which some Netatmo setups expose directly.
CONF_BATTERY_SENSOR = "battery_sensor"

# Outdoor temperature sensor — local weather station, Netatmo outdoor
# module, Aqara, etc.  When set, overrides the temperature attribute read
# from the weather entity for all outdoor-temperature decisions
# (adaptive away setpoint, SeasonEngine, auto-off).
# Falls back to weather entity if this sensor is unavailable.
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"

# Outdoor humidity sensor — Netatmo outdoor module etc.
# Used to amplify mold risk calculation when outdoor RH is high.
CONF_OUTDOOR_HUMIDITY_SENSOR = "outdoor_humidity_sensor"

# Precipitation sensor — mm/h or mm. When > 0 a window is classified as
# pure heat loss regardless of CO₂ level (nobody ventilates in rain).
CONF_PRECIPITATION_SENSOR = "precipitation_sensor"

# Wind speed sensor — m/s. When above WIND_FAST_MS the window delay is
# reduced to DEFAULT_WINDOW_DELAY_WIND_MIN to react faster to heat loss.
CONF_WIND_SPEED_SENSOR = "wind_speed_sensor"

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_WINDOW_DELAY_MIN = 5
DEFAULT_WINDOW_CLOSE_DELAY_MIN = 2
DEFAULT_WINDOW_WARNING_MIN = 30
DEFAULT_WINDOW_DELAY_WIND_MIN = 1  # reduced delay when wind > threshold
WIND_FAST_MS: float = 6.0  # m/s — window heat loss accelerates above this
# v0.33.0 — fallback for CONF_WINDOW_DELAY_DEFAULT_MIN when unset (fresh
# installs, pre-upgrade config entries). Reuses the same 5 min value the
# old per-room field defaulted to, so upgrading changes nothing until the
# global setting is actually edited.
DEFAULT_WINDOW_DELAY_DEFAULT_MIN = DEFAULT_WINDOW_DELAY_MIN
# v0.33.0 — fallback for CONF_WINDOW_OFF_TEMP when unset. Same 10°C value
# CONF_AWAY_TEMP_OVERRIDE already defaulted to, so upgrading changes
# nothing until the new setting is actually edited.
DEFAULT_WINDOW_OFF_TEMP: float = 10.0
DEFAULT_GRACE_DAY_MIN = 30
DEFAULT_GRACE_NIGHT_MIN = 15
DEFAULT_NIGHT_START_HOUR = 23
DEFAULT_NIGHT_END_HOUR = 7
DEFAULT_PREHEAT_LEAD_TIME_MIN = 20
DEFAULT_AUTO_OFF_TEMP_THRESHOLD = 18.0
DEFAULT_AUTO_OFF_TEMP_DAYS = 5
DEFAULT_PAUSE_DURATION_MIN = 120
CONF_PAUSE_DURATION_MIN = "pause_duration_min"  # B5: was missing, causing config reads to fall back to default always

# Night setback — reduce PID target temperature during night hours.
# Applied on top of the Netatmo cloud schedule setpoint.
# Set to 0.0 to disable.
CONF_NIGHT_SETBACK_ENABLED = "night_setback_enabled"
CONF_NIGHT_SETBACK_TEMP = "night_setback_temp"
DEFAULT_NIGHT_SETBACK_ENABLED = False
DEFAULT_NIGHT_SETBACK_TEMP: float = 2.0  # °C — subtracted from schedule setpoint

# Per-room comfort temperature — the PID target for ALL rooms, regardless of
# TRV manufacturer (v0.19.0). Combined with RoomState (AWAY/NORMAL) and
# night_setback_delta() for presence + day/night.
# Before 0.19.0 this was only used for rooms WITHOUT a homekit_climate_entity
# (Zigbee/Matter/Thread); Netatmo rooms instead read the cloud entity's own
# schedule 'temperature' attribute, which meant this field was silently
# ignored for them — see audit/heat_manager_target_temp_analysis_2026-09-11.md.
CONF_COMFORT_TEMP = "comfort_temp"
DEFAULT_COMFORT_TEMP: float = 20.0

# ── PID outdoor feedforward (weather compensation) ──────────────────────────
# Adds a small proactive power contribution based on outdoor temperature, on
# top of PID's reactive correction — classic "heating curve" style weather
# compensation used in boiler control. With a 60 s tick and several minutes
# of TRV thermal lag, pure PID only starts correcting once the room has
# already begun cooling; feedforward starts pushing power up as soon as the
# outdoor temperature drops, before the room itself has drifted.
# Conservative defaults, not yet exposed in the UI.
FF_REFERENCE_OUTDOOR_TEMP: float = (
    15.0  # °C — outdoor temp at/above which feedforward is 0
)
FF_WEIGHT: float = 0.02  # power fraction added per °C outdoor temp is below reference
FF_MAX_CONTRIBUTION: float = 0.3  # cap — feedforward alone never exceeds 30% power

# 2026-09-13 (architecture review #5) — the three constants above are now
# also readable/writable as per-install config (config_flow.py's "Season &
# global settings" step + websocket.py's live panel editing), with these
# same values as their DEFAULT_* fallback so an upgrading install's behaviour
# is unchanged until the fields are actually edited. CONF_WEATHER_COMPENSATION_ENABLED
# defaults to True for the same reason — the feedforward was always-on
# before this, so "exposing" it must not silently turn it off.
CONF_WEATHER_COMPENSATION_ENABLED = "weather_compensation_enabled"
DEFAULT_WEATHER_COMPENSATION_ENABLED: bool = True
CONF_FF_REFERENCE_OUTDOOR_TEMP = "ff_reference_outdoor_temp"
CONF_FF_WEIGHT = "ff_weight"
CONF_FF_MAX_CONTRIBUTION = "ff_max_contribution"

# ── Solar gain (2026-09-14, punkt 7) ─────────────────────────────────────────
# A per-room, lux-sensor-driven REDUCTION of PID power while the sun is up —
# see CONF_LUX_SENSOR above for the "why a lux sensor instead of a geometric
# sun-position model" rationale, and coordinator._solar_gain_reduction() for
# the formula. Off by default (unlike weather compensation, which was
# always-on before it became configurable) since it's a genuinely new
# behaviour with no prior always-on equivalent to preserve — an install
# upgrading to this version sees no change until both this is turned on AND
# at least one room has a CONF_LUX_SENSOR configured (currently: Stuen,
# Køkken, Gang).
CONF_SOLAR_GAIN_ENABLED = "solar_gain_enabled"
DEFAULT_SOLAR_GAIN_ENABLED: bool = False
# Lux level (indoor, at the sensor) above which a room is considered to be
# getting meaningful solar gain right now. Indoor lux near a window on an
# overcast day is typically a few hundred to ~1500 lux; direct or
# bright-but-hazy sun through glass commonly reads several thousand to
# 10 000+ lux depending on sensor placement/angle — 5000 is a conservative
# "this is real sun, not just daylight" line to start from.
CONF_SOLAR_GAIN_LUX_THRESHOLD = "solar_gain_lux_threshold"
SOLAR_GAIN_LUX_THRESHOLD: float = 5000.0
# Power-fraction reduction per full multiple of the threshold the room's lux
# exceeds it by — e.g. at the default 0.15, a room reading exactly 2×
# threshold (excess == threshold) loses 0.15 (15%) of PID's commanded power.
CONF_SOLAR_GAIN_WEIGHT = "solar_gain_weight"
SOLAR_GAIN_WEIGHT: float = 0.15
# Cap — solar gain alone never removes more than this fraction of PID's
# commanded power, regardless of how bright the room reads. Deliberately
# conservative: this is a comfort/efficiency nudge, not a licence to let a
# room drift cold on a bright-but-freezing day just because the sun is out.
CONF_SOLAR_GAIN_MAX_REDUCTION = "solar_gain_max_reduction"
SOLAR_GAIN_MAX_REDUCTION: float = 0.4

# PID defaults
DEFAULT_PID_KP: float = 0.5
DEFAULT_PID_KI: float = 0.02
DEFAULT_PID_KD: float = 0.0

# ── PID setpoint margin (2026-09-15, overshoot investigation) ───────────
# PidController.power_to_setpoint() maps a power fraction straight onto the
# range [trv_min, trv_max] — at 100% power (which Kp alone reaches at just
# a couple of degrees' error, well before the room is actually close to
# target) it commands trv_max outright, regardless of how close trv_max
# happens to sit to the room's own target_temp. With a small gap between
# target and trv_max (e.g. target 21°C, trv_max 24°C) this means an
# everyday few-degree call-for-heat sends the TRV to 24°C, not 21°C —
# combined with district-heating/TRV thermal lag, this is what caused the
# 21°C-target rooms to be observed holding at 22-25°C (2026-09-15
# overshoot investigation). CONF_PID_SETPOINT_MARGIN caps the setpoint
# actually written to a TRV at `target_temp + margin` — relative to each
# room's OWN target, not the single global trv_max — so full PID power
# still drives the TRV hard while genuinely far from target, but never past
# a controlled, tunable overshoot allowance once close. trv_max remains the
# absolute hardware ceiling (still applied via power_to_setpoint's own
# clamp); this margin is a second, tighter cap applied on top in
# coordinator._async_pid_tick(). Default 2.0°C is deliberately generous
# enough to still drive normal proportional heating response — tune down
# per install once behaviour is confirmed.
CONF_PID_SETPOINT_MARGIN = "pid_setpoint_margin"
PID_SETPOINT_MARGIN: float = 2.0
DEFAULT_TRV_MAX_TEMP: float = 28.0

# CO₂ threshold — above this level an open window is considered intentional
# ventilation rather than pure heat waste.  Used by WindowEngine to select
# notification wording.
# Can be overridden per room via CONF_CO2_THRESHOLD.
DEFAULT_CO2_VENTILATION_THRESHOLD: int = 900  # ppm

# Per-room CO₂ threshold override.  When set, overrides DEFAULT_CO2_VENTILATION_THRESHOLD
# for that room only.  Useful when rooms have different ventilation needs
# (e.g. bedrooms vs. living rooms vs. offices).
CONF_CO2_THRESHOLD = "co2_threshold"

# ── Boost ─────────────────────────────────────────────────────────────────────

# Default TRV setpoint applied by the heat_manager/boost_start WS command when
# no "temperature" is given. Mirrors heat-manager-card.js's own boost_temp
# default (24°C) so panel and card boost to the same temperature by default.
DEFAULT_BOOST_TEMP: float = 24.0

# Default boost duration (minutes) before the coordinator auto-restores every
# boosted room, when no "duration_minutes" is given.
DEFAULT_BOOST_MINUTES: float = 30.0

# 2026-09-13: these two used to be hardcoded constants used directly by
# async_boost_start() — no way to change the "no temperature/duration given"
# fallback without editing code. Now configurable via the options flow
# ("Season & global settings", same step as PID gains / pause duration);
# DEFAULT_BOOST_TEMP/DEFAULT_BOOST_MINUTES above remain the fallback when
# these config keys are themselves absent (fresh installs, pre-upgrade
# config entries).
CONF_BOOST_DEFAULT_TEMP = "boost_default_temp"
CONF_BOOST_DEFAULT_MINUTES = "boost_default_minutes"

# ── Room offset (v0.9.0 global → B18 Fase 3 per-room) ────────────────────────
# Non-destructive temperature shift applied on top of a room's PID target
# every tick — see number.py RoomOffsetNumber (created per-room for rooms
# with 2+ TRVs). Mirrors climate_group_helper's "Group Offset" number
# entity. Bounds/step/default kept as-is from the v0.9.0 global entity they
# replace — only the coordinator attribute they're read into is now
# per-room (coordinator.room_offsets) rather than a single float.

DEFAULT_GROUP_OFFSET: float = 0.0
GROUP_OFFSET_MIN: float = -5.0
GROUP_OFFSET_MAX: float = 5.0
GROUP_OFFSET_STEP: float = 0.5

# ── Remote button control (v0.14.0) ──────────────────────────────────────────
# Global (not per-room) physical remote — e.g. an Aqara Climate Sensor W100,
# which exposes 3 separate `event.*` entities (one per physical button).
# Configurable in the options flow's "Remote control" step so any `event.*`
# entity can be assigned — not tied to one specific device model. See
# engine/remote_button_engine.py.
#
# CONF_BUTTON_TEMP_UP_ENTITY / CONF_BUTTON_TEMP_DOWN_ENTITY: pressing these
# nudges EVERY room's TRV setpoint by ±BUTTON_TEMP_STEP (clamped between
# BUTTON_TEMP_MIN/MAX), skipping rooms currently WINDOW_OPEN or AWAY. A room
# still in NORMAL (auto) is switched to OVERRIDE (manual) first so the next
# PID tick doesn't immediately overwrite the button's adjustment.
#
# CONF_BUTTON_MODE_TOGGLE_ENTITY: pressing this toggles ALL eligible rooms
# (same WINDOW_OPEN/AWAY exclusion) between OVERRIDE (manual) and NORMAL
# (auto) together — if any eligible room is still NORMAL, all eligible
# rooms are switched to OVERRIDE; otherwise all are switched back to NORMAL.
CONF_BUTTON_TEMP_UP_ENTITY = "button_temp_up_entity"
CONF_BUTTON_TEMP_DOWN_ENTITY = "button_temp_down_entity"
CONF_BUTTON_MODE_TOGGLE_ENTITY = "button_mode_toggle_entity"

BUTTON_TEMP_STEP: float = 0.5
BUTTON_TEMP_MIN: float = 15.0
BUTTON_TEMP_MAX: float = DEFAULT_TRV_MAX_TEMP

# ── Device calibration (v0.9.0) ──────────────────────────────────────────────
# See engine/calibration_engine.py and CONF_CALIBRATION_ENTITY above.

# How often (minutes) to re-send the calibration value even when it hasn't
# changed — guards against Zigbee number entities silently reverting/timing
# out, mirroring climate_group_helper's calibration "heartbeat".
DEFAULT_CALIBRATION_HEARTBEAT_MIN: int = 30

# Only re-write the calibration entity when the computed offset has moved
# by at least this much since the last write (outside of a heartbeat
# resend) — avoids chattering the entity on sensor noise.
CALIBRATION_CHANGE_THRESHOLD: float = 0.2

# Defensive clamp on the computed offset before it is ever sent — a sensor
# glitch (external probe reporting a wildly wrong value) should never be
# able to push a TRV's calibration far out of a sane range. The target
# `number.*` entity's own min/max (set by its own integration) still
# applies on top of this.
CALIBRATION_OFFSET_MIN: float = -10.0
CALIBRATION_OFFSET_MAX: float = 10.0

# ── Sync engine (v0.9.0) ──────────────────────────────────────────────────────
# See engine/sync_engine.py and CONF_SYNC_MODE above.

# A state change on a room's write entity must differ from
# coordinator.last_expected_setpoint by at least this much to be considered
# a genuine external/manual change rather than device write-back noise —
# matches the PID tick's own suppress threshold.
SYNC_CHANGE_THRESHOLD: float = 0.5

# Seconds a mismatched temperature must persist before SyncEngine acts.
# Absorbs the brief window right after Heat Manager's own write where a
# slow device (Zigbee, cloud round-trip) may still report its old value.
SYNC_CONFIRM_DELAY_SEC: float = 12.0

# ── Schedule engine (v0.9.0) ──────────────────────────────────────────────────
# See engine/schedule_engine.py and CONF_SCHEDULE_ENTITY above.

# Sanity clamp on a temperature parsed out of a schedule block or calendar
# event description — a malformed or malicious "Additional data" / event
# description should never be able to drive a room target outside a livable
# range.
SCHEDULE_TEMP_MIN: float = 5.0
SCHEDULE_TEMP_MAX: float = 30.0

# ── Repair issue identifiers ────────────────────────────────────────────────────

# Raised when a configured climate entity does not exist in HA at startup.
# Cleared automatically when the entity becomes available on next reload.
REPAIR_ISSUE_MISSING_CLIMATE = "missing_climate_entity"

# 2026-09-14 (implementeringsplan punkt 2, gruppe B) — generic repair issue
# for a status-center category (see coordinator.py's _report_issue()) that
# has stayed continuously active past CONF_ISSUE_ESCALATION_MINUTES. One
# shared translation key with {message}/{duration_min} placeholders, used
# for every repair-worthy category (cloud down, persistent mold risk, a
# room stuck in manual override) instead of a separate translation key per
# category — keeps strings.json/translations from growing one block per
# future category. Cleared automatically the moment the category's own
# active/inactive check reports it inactive again.
REPAIR_ISSUE_PERSISTENT = "persistent_issue"

# ── Effective season (resolved — three-tier) ─────────────────────────────────


class EffectiveSeason(StrEnum):
    """Resolved heating phase — drives controller and PID behaviour.

    DORMANT : Full summer sleep.  Heating disabled, TRVs set to hvac_mode off.
    WAKING  : Transitional (early autumn / late spring).  Heating allowed but
              setpoints are reduced by CONF_WAKE_SETBACK_TEMP.  Pre-heat
              suspended.  Triggered when indoor temp > CONF_INDOOR_WAKE_THRESHOLD.
    ACTIVE  : Full winter operation.  Normal setpoints, pre-heat enabled.
    """

    DORMANT = "dormant"
    WAKING = "waking"
    ACTIVE = "active"


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
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"


SEASON_MODE_OPTIONS = [s.value for s in SeasonMode]

# Meteorological season boundaries (month, day) — internationally standard.
# Spring: Mar 1, Summer: Jun 1, Autumn: Sep 1, Winter: Dec 1.
METEO_SEASONS: list[tuple[int, int, SeasonMode]] = [
    (12, 1, SeasonMode.WINTER),
    (9, 1, SeasonMode.AUTUMN),
    (6, 1, SeasonMode.SUMMER),
    (3, 1, SeasonMode.SPRING),
]

# ── Room state ────────────────────────────────────────────────────────────────


class RoomState(StrEnum):
    NORMAL = "normal"
    WINDOW_OPEN = "window_open"
    AWAY = "away"
    PRE_HEAT = "pre_heat"
    OVERRIDE = "override"


# ── Wake / indoor threshold config keys ─────────────────────────────────────

# Primary indoor temperature sensor — used to decide WAKING vs ACTIVE.
# Typically a shared sensor in the main living area or a computed average.
# Falls back to reading the first available room temperature sensor when absent.
CONF_INDOOR_WAKE_SENSOR = "indoor_wake_sensor"

# Indoor temperature above which the system enters WAKING instead of ACTIVE
# during the transitional seasons (spring / autumn).  Default 21 °C.
CONF_INDOOR_WAKE_THRESHOLD = "indoor_wake_threshold"
DEFAULT_INDOOR_WAKE_THRESHOLD: float = 21.0

# Setpoint reduction applied to all rooms while in WAKING phase.
# Expressed as °C subtracted from the normal schedule setpoint.
# Default 2 °C — gentle warmth without full winter consumption.
CONF_WAKE_SETBACK_TEMP = "wake_setback_temp"
DEFAULT_WAKE_SETBACK_TEMP: float = 2.0


# ── Auto-off reason ───────────────────────────────────────────────────────────


class AutoOffReason(StrEnum):
    NONE = "none"
    SEASON = "season"
    TEMPERATURE = "temperature"


# ── Preset modes ──────────────────────────────────────────────────────────────

PRESET_AWAY = "away"
PRESET_SCHEDULE = "schedule"
# Fase 2 (2026-09-11): not written by Heat Manager itself, only used as a
# NetatmoPresetModeSelect fallback options list when the live entity's own
# 'preset_modes' attribute is unavailable — the real options always come
# from that attribute when present.
PRESET_BOOST = "boost"
PRESET_FROST_GUARD = "frost_guard"
HVAC_OFF = "off"

# Fallback option list for NetatmoPresetModeSelect when the live climate
# entity's own 'preset_modes' attribute is unavailable. Order matches the
# entity's own reported order in the common case (schedule/away/frost_guard/
# boost) so the UI doesn't visibly reorder once the real attribute appears.
NETATMO_PRESET_MODE_FALLBACK_OPTIONS = [
    PRESET_SCHEDULE,
    PRESET_AWAY,
    PRESET_FROST_GUARD,
    PRESET_BOOST,
]

# ── Notification action identifiers ───────────────────────────────────────────

ACTION_FORCE_HEATING_ON = "HM_FORCE_HEATING_ON"
ACTION_VIEW_WINDOWS = "HM_VIEW_WINDOWS"
ACTION_DISMISS = "HM_DISMISS"
ACTION_PAUSE_1H = "HM_PAUSE_1H"
ACTION_PAUSE_TODAY = "HM_PAUSE_TODAY"

# ── House Voice integration ──────────────────────────────────────────────────

CONF_HOUSE_VOICE_ENABLED = "house_voice_enabled"
HOUSE_VOICE_DOMAIN = "house_voice"
HOUSE_VOICE_SERVICE_SAY = "say"

# Event IDs — must match events created in House Voice
HV_EVENT_CONTROLLER_PAUSED = "heat_manager_controller_paused"
HV_EVENT_CONTROLLER_OFF = "heat_manager_controller_off"
HV_EVENT_SEASON_SUMMER = "heat_manager_season_summer"
HV_EVENT_SEASON_WINTER = "heat_manager_season_winter"

# ── Services ──────────────────────────────────────────────────────────────────

SERVICE_SET_CONTROLLER_STATE = "set_controller_state"
SERVICE_PAUSE = "pause"
SERVICE_RESUME = "resume"
SERVICE_FORCE_ROOM_ON = "force_room_on"
SERVICE_BOOST_START = "boost_start"
SERVICE_BOOST_STOP = "boost_stop"

# ── Platforms ─────────────────────────────────────────────────────────────────

PLATFORMS: list[str] = ["sensor", "binary_sensor", "select", "switch", "number"]

# ── Coordinator update interval ───────────────────────────────────────────────

SCAN_INTERVAL_SECONDS = 60

# Netatmo cloud API — stagger multi-room calls to avoid 429 rate-limit errors
NETATMO_API_CALL_DELAY_SEC: float = 0.6

# ── Lovelace card resource path ───────────────────────────────────────────────

LOVELACE_RESOURCE_PATH = "/heat_manager/heat-manager-card.js"
