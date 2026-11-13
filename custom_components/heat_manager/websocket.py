"""
Heat Manager — WebSocket API

Registers WS commands used by the sidebar panel:
  heat_manager/get_state    → full state snapshot
  heat_manager/get_history  → event log for the last N days

Event log reads from coordinator._event_log (deque, newest first).

v0.4.2: _get_entry() uses entry.runtime_data exclusively — no hass.data lookup.
B15: room payload now includes "trv_type" (netatmo/zigbee) so the panel can
     show a TRV-type badge per room without guessing from entity IDs.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

from .const import (
    ALARM_ARMED_STATES,
    CONF_ALARM_AWAY_STATES,
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMP,
    CONF_DOOR_HEAT_SHARE_ENABLED,
    CONF_DOOR_HEAT_SHARE_MAX_REDUCTION,
    CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF,
    CONF_DOOR_HEAT_SHARE_WEIGHT,
    CONF_FF_MAX_CONTRIBUTION,
    CONF_FF_REFERENCE_OUTDOOR_TEMP,
    CONF_FF_WEIGHT,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_ISSUE_ESCALATION_MINUTES,
    CONF_MANUAL_TRV_CONTROL,
    CONF_MIN_ROOM_TEMP,
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
    CONF_PID_ENABLED,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_PID_SETPOINT_MARGIN,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_SOLAR_GAIN_ENABLED,
    CONF_SOLAR_GAIN_LUX_THRESHOLD,
    CONF_SOLAR_GAIN_MAX_REDUCTION,
    CONF_SOLAR_GAIN_WEIGHT,
    CONF_TRV_TYPE,
    CONF_WEATHER_COMPENSATION_ENABLED,
    CONF_WINDOW_DELAY_DEFAULT_MIN,
    CONF_WINDOW_OFF_TEMP,
    CONF_WINDOW_WARNING_MIN,
    DEFAULT_ALARM_AWAY_STATES,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMP,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_DOOR_HEAT_SHARE_ENABLED,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_GRACE_NIGHT_MIN,
    DEFAULT_ISSUE_ESCALATION_MINUTES,
    DEFAULT_MANUAL_TRV_CONTROL,
    DEFAULT_MIN_ROOM_TEMP,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_SETBACK_ENABLED,
    DEFAULT_NIGHT_SETBACK_TEMP,
    DEFAULT_NIGHT_START_HOUR,
    DEFAULT_PID_KD,
    DEFAULT_PID_KI,
    DEFAULT_PID_KP,
    DEFAULT_SOLAR_GAIN_ENABLED,
    DEFAULT_WEATHER_COMPENSATION_ENABLED,
    DEFAULT_WINDOW_DELAY_DEFAULT_MIN,
    DEFAULT_WINDOW_OFF_TEMP,
    DEFAULT_WINDOW_WARNING_MIN,
    DOMAIN,
    DOOR_HEAT_SHARE_MAX_REDUCTION,
    DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    DOOR_HEAT_SHARE_MIN_TEMP_DIFF,
    DOOR_HEAT_SHARE_WEIGHT,
    FF_MAX_CONTRIBUTION,
    FF_REFERENCE_OUTDOOR_TEMP,
    FF_WEIGHT,
    MIN_ROOM_TEMP_RANGE,
    PID_SETPOINT_MARGIN,
    SOLAR_GAIN_LUX_THRESHOLD,
    SOLAR_GAIN_MAX_REDUCTION,
    SOLAR_GAIN_WEIGHT,
    RoomState,
)
from .panel import _get_version
from .websocket_payload import build_state_payload

if TYPE_CHECKING:
    from .coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/boost_start",
        probatio.Optional("temperature"): probatio.Any(float, int),
        probatio.Optional("duration_minutes"): probatio.Any(float, int),
    }
)
@websocket_api.async_response
async def ws_boost_start(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WebSocket: start boost mode for all eligible rooms.

    Thin wrapper around coordinator.async_boost_start() — the single shared
    implementation also used by the heat_manager.boost_start HA service, so
    the panel and any automation trigger the exact same TRV behaviour.
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    boosted = await coordinator.async_boost_start(
        msg.get("temperature"), msg.get("duration_minutes")
    )
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "rooms_boosted": len(boosted),
            "boost_remaining_minutes": coordinator.boost_remaining_minutes,
        },
    )


@websocket_api.websocket_command({probatio.Required("type"): "heat_manager/boost_stop"})
@websocket_api.async_response
async def ws_boost_stop(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WebSocket: stop boost mode and restore boosted rooms to schedule.

    Thin wrapper around coordinator.async_boost_stop() — see ws_boost_start().
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    restored = await coordinator.async_boost_stop()
    connection.send_result(
        msg["id"], {"success": True, "rooms_restored": len(restored)}
    )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/extend_overrides",
        probatio.Optional("minutes", default=60): probatio.All(
            int, probatio.Range(min=1, max=720)
        ),
    }
)
@websocket_api.async_response
async def ws_extend_overrides(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WebSocket: push every time-limited manual override's auto-restore
    time back by `minutes` (v0.60.0 — the status line's "+1 time")."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    extended = coordinator.extend_overrides(msg["minutes"])
    connection.send_result(msg["id"], {"success": True, "rooms_extended": extended})


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/snooze_issue",
        probatio.Required("issue_id"): str,
        probatio.Optional("minutes", default=60): probatio.All(
            int, probatio.Range(min=0, max=1440)
        ),
    }
)
@websocket_api.async_response
async def ws_snooze_issue(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WebSocket: hide one status-line issue for `minutes` (v0.60.0 —
    "Skjul 1 t"). minutes=0 un-snoozes. Critical issues are never hidden;
    build_active_issues() ignores a snooze on them."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    until = coordinator.snooze_issue(msg["issue_id"], msg["minutes"])
    connection.send_result(
        msg["id"],
        {"success": True, "snoozed_until": until.isoformat() if until else None},
    )


@websocket_api.websocket_command(
    {probatio.Required("type"): "heat_manager/release_overrides"}
)
@websocket_api.async_response
async def ws_release_overrides(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WebSocket: return every manually overridden room to automatic control
    (v0.59.0 — the panel mode bar's "Tilbage til auto" button). Thin wrapper
    around coordinator.async_release_all_overrides()."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    released = await coordinator.async_release_all_overrides()
    connection.send_result(msg["id"], {"success": True, "rooms_released": released})


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/set_room_temp",
        probatio.Required("room_name"): str,
        probatio.Optional("temperature"): probatio.Any(float, int, None),
        probatio.Optional("duration_min", default=60): int,
    }
)
@websocket_api.async_response
async def ws_set_room_temp(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WebSocket: set a manual temperature override for one room.

    temperature=None restores the Netatmo cloud schedule (preset_mode: schedule)
    or the Zigbee thermostat setpoint from config.
    duration_min=0 means permanent override until manually reset.
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    room_name = msg["room_name"]
    temperature = msg.get("temperature")
    duration = int(msg.get("duration_min", 60))

    # Find room config
    room_cfg = next(
        (r for r in coordinator.rooms if r.get("room_name") == room_name), None
    )
    if room_cfg is None:
        connection.send_error(
            msg["id"], "not_found", f"Room '{room_name}' not configured"
        )
        return

    # B18: every physical TRV configured for the room receives the same
    # command, each routed by its own trv_type/write-entity policy —
    # unchanged from the pre-existing single-TRV policy per branch.
    trvs = coordinator.get_room_trvs(room_name)
    if not trvs:
        connection.send_error(
            msg["id"], "not_found", f"No write entity for room '{room_name}'"
        )
        return

    write_entity: str | None = None

    try:
        if temperature is None:
            # Restore to schedule
            for trv in trvs:
                trv_type = trv.get(CONF_TRV_TYPE, "netatmo")
                # 2026-09-16 (deep-dive audit fix): both branches below used
                # to call hass.services.async_call("climate", ...) directly,
                # bypassing coordinator.async_call_climate_service()'s
                # shared Netatmo lock/pacing. The panel's "Send til alle"
                # control calls this WS command once per room in sequence,
                # so within any ONE of those calls every TRV in that room
                # was still hit with no lock at all.
                if trv_type == "zigbee":
                    entity_id = coordinator.get_trv_write_entity(trv) or trv.get(
                        CONF_CLIMATE_ENTITY
                    )
                    if not entity_id:
                        continue
                    await coordinator.async_call_climate_service(
                        "set_hvac_mode",
                        entity_id,
                        {"hvac_mode": "heat"},
                        needs_delay=coordinator.trv_needs_cloud_delay(trv),
                    )
                else:
                    entity_id = trv.get(CONF_CLIMATE_ENTITY)
                    if not entity_id:
                        continue
                    # v0.63.0: per-room release, never the home-level preset
                    await coordinator.async_release_netatmo_room(entity_id)
                if write_entity is None:
                    write_entity = entity_id
            coordinator.log_event(
                f"{room_name}: schedule gendannet",
                reason="manuel panel",
                event_type="manual",
            )
            _LOGGER.info("Room '%s' restored to schedule", room_name)
        else:
            # Set temperature — same setpoint fanned out to every TRV,
            # each with its own trv_needs_cloud_delay() decision (2026-09-16
            # audit fix — iterates trvs directly instead of the flattened
            # write-entity list so each write keeps its TRV association).
            temp = float(temperature)
            if not trvs:
                connection.send_error(
                    msg["id"],
                    "not_found",
                    f"No write entity for room '{room_name}'",
                )
                return
            for trv in trvs:
                entity_id = coordinator.get_trv_write_entity(trv)
                if not entity_id:
                    continue
                await coordinator.async_call_climate_service(
                    "set_temperature",
                    entity_id,
                    {"temperature": temp},
                    needs_delay=coordinator.trv_needs_cloud_delay(trv),
                )
                if write_entity is None:
                    write_entity = entity_id
            dur_label = f"{duration} min" if duration > 0 else "permanent"
            coordinator.log_event(
                f"{room_name}: {temp}\u00b0C ({dur_label})",
                reason="manuel panel",
                event_type="manual",
            )
            _LOGGER.info(
                "Room '%s' set to %.1f\u00b0C for %s via %s",
                room_name,
                temp,
                dur_label,
                write_entity,
            )
            # 1.4 fix: mark the room OVERRIDE (bypassing presence/window
            # logic) and record the source, matching the behaviour of the
            # override switch and the remote-button engine — previously
            # a manual panel temperature never engaged RoomOverrideSwitch's
            # OVERRIDE state at all.
            coordinator.set_room_state(room_name, RoomState.OVERRIDE)
            coordinator.room_override_source[room_name] = "panel"
            # 2026-09 fix: duration_min was accepted and logged but never
            # actually wired to anything — a manual panel temperature stayed
            # in effect forever regardless of the requested duration. 0
            # means "permanent" (no auto-restore), matching the docstring.
            if duration > 0:
                coordinator.room_override_expires_at[room_name] = utcnow() + timedelta(
                    minutes=duration
                )
            else:
                coordinator.room_override_expires_at.pop(room_name, None)
    # broad-except-rationale: must not crash the WS connection; error goes back to frontend
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("set_room_temp failed for '%s'", room_name)
        connection.send_error(msg["id"], "service_error", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "success": True,
            "room": room_name,
            "temperature": temperature,
            "duration_min": duration,
            "write_entity": write_entity,
        },
    )


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all Heat Manager WebSocket commands."""
    websocket_api.async_register_command(hass, ws_get_state)
    websocket_api.async_register_command(hass, ws_get_history)
    websocket_api.async_register_command(hass, ws_update_config)
    websocket_api.async_register_command(hass, ws_boost_start)
    websocket_api.async_register_command(hass, ws_boost_stop)
    websocket_api.async_register_command(hass, ws_set_room_temp)
    websocket_api.async_register_command(hass, ws_update_room_config)
    websocket_api.async_register_command(hass, ws_release_overrides)
    websocket_api.async_register_command(hass, ws_extend_overrides)
    websocket_api.async_register_command(hass, ws_snooze_issue)
    _LOGGER.debug("WebSocket commands registered")


# ── heat_manager/get_state ────────────────────────────────────────────────────


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/get_state",
    }
)
@websocket_api.async_response
async def ws_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return full Heat Manager state snapshot."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    # 2026-09-11: panel.py already reads manifest.json (off-thread, via
    # async_add_executor_job — it's blocking file I/O) as the cache-busting
    # query string's version — reuse that same helper/source-of-truth here
    # instead of a second, independently-maintained copy, so the number
    # shown in the panel's header can never drift from the one actually
    # bumped in manifest.json (see panel.py's _get_version docstring for
    # the const.py drift history this already burned us on once).
    integration_version = await hass.async_add_executor_job(_get_version, hass)
    connection.send_result(
        msg["id"], build_state_payload(hass, entry, integration_version)
    )


# ── heat_manager/get_history ──────────────────────────────────────────────────


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/get_history",
        probatio.Optional("days", default=7): probatio.All(
            int, probatio.Range(min=1, max=30)
        ),
    }
)
@websocket_api.async_response
async def ws_get_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return event log data."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    coordinator = entry.runtime_data
    days = msg.get("days", 7)

    events = _get_event_log(coordinator, days)

    connection.send_result(
        msg["id"],
        {
            "events": events,
        },
    )


# ── heat_manager/update_config ────────────────────────────────────────────────

# Fase 2, del 1 (2026-09-13) — panel "Indstillinger" tab: generalizes what
# used to be two hand-written string branches (alarm_panel/notify_service)
# plus one hand-written bool branch (manual_trv_control) into three small
# per-type tables, so adding a new live-editable field to the panel is a
# one-line addition here instead of a new if-branch. See
# planning/heat_manager_fase2_spec_2026-09-11.md, "Del 1".
#
# Each table's value is the field's DEFAULT_* fallback (matching const.py/
# config_flow.py) — used both to read the field's *current* value out of
# entry.options for change-detection, and to interpret an absent key the
# same way the rest of the codebase already does (coordinator.config,
# config_flow defaults). Getting this default wrong would make a field that
# happens to already be at its "unset" value un-toggleable from the panel
# (the "changed" check would never trigger), so keep these in sync with
# const.py's DEFAULT_* constants.
_STRING_CONFIG_FIELDS: tuple[str, ...] = (
    CONF_ALARM_PANEL,
    CONF_NOTIFY_SERVICE,
)

_BOOL_CONFIG_FIELD_DEFAULTS: dict[str, bool] = {
    CONF_MANUAL_TRV_CONTROL: DEFAULT_MANUAL_TRV_CONTROL,
    CONF_PID_ENABLED: True,
    CONF_NOTIFY_WINDOWS: True,
    CONF_NOTIFY_WINDOW_WARNING_30: True,
    CONF_NIGHT_SETBACK_ENABLED: DEFAULT_NIGHT_SETBACK_ENABLED,
    CONF_NOTIFY_PRESENCE: True,
    CONF_NOTIFY_PREHEAT: True,
    CONF_NOTIFY_MOLD_RISK: True,
    CONF_NOTIFY_ISSUE_ESCALATION: True,
    CONF_WEATHER_COMPENSATION_ENABLED: DEFAULT_WEATHER_COMPENSATION_ENABLED,
    CONF_SOLAR_GAIN_ENABLED: DEFAULT_SOLAR_GAIN_ENABLED,
    CONF_DOOR_HEAT_SHARE_ENABLED: DEFAULT_DOOR_HEAT_SHARE_ENABLED,
}

# value = (python type to cast the raw WS value to, DEFAULT_* fallback)
_NUMERIC_CONFIG_FIELDS: dict[str, tuple[type, float | int]] = {
    CONF_PID_KP: (float, DEFAULT_PID_KP),
    CONF_PID_KI: (float, DEFAULT_PID_KI),
    CONF_PID_KD: (float, DEFAULT_PID_KD),
    CONF_PID_SETPOINT_MARGIN: (float, PID_SETPOINT_MARGIN),
    CONF_BOOST_DEFAULT_TEMP: (float, DEFAULT_BOOST_TEMP),
    CONF_BOOST_DEFAULT_MINUTES: (float, DEFAULT_BOOST_MINUTES),
    CONF_WINDOW_WARNING_MIN: (int, DEFAULT_WINDOW_WARNING_MIN),
    CONF_WINDOW_DELAY_DEFAULT_MIN: (int, DEFAULT_WINDOW_DELAY_DEFAULT_MIN),
    CONF_WINDOW_OFF_TEMP: (float, DEFAULT_WINDOW_OFF_TEMP),
    CONF_MIN_ROOM_TEMP: (float, DEFAULT_MIN_ROOM_TEMP),
    CONF_NIGHT_SETBACK_TEMP: (float, DEFAULT_NIGHT_SETBACK_TEMP),
    CONF_NIGHT_START_HOUR: (int, DEFAULT_NIGHT_START_HOUR),
    CONF_NIGHT_END_HOUR: (int, DEFAULT_NIGHT_END_HOUR),
    CONF_GRACE_DAY_MIN: (int, DEFAULT_GRACE_DAY_MIN),
    CONF_GRACE_NIGHT_MIN: (int, DEFAULT_GRACE_NIGHT_MIN),
    CONF_AUTO_OFF_TEMP_THRESHOLD: (float, DEFAULT_AUTO_OFF_TEMP_THRESHOLD),
    CONF_AUTO_OFF_TEMP_DAYS: (int, DEFAULT_AUTO_OFF_TEMP_DAYS),
    CONF_ISSUE_ESCALATION_MINUTES: (int, DEFAULT_ISSUE_ESCALATION_MINUTES),
    CONF_FF_REFERENCE_OUTDOOR_TEMP: (float, FF_REFERENCE_OUTDOOR_TEMP),
    CONF_FF_WEIGHT: (float, FF_WEIGHT),
    CONF_FF_MAX_CONTRIBUTION: (float, FF_MAX_CONTRIBUTION),
    CONF_SOLAR_GAIN_LUX_THRESHOLD: (float, SOLAR_GAIN_LUX_THRESHOLD),
    CONF_SOLAR_GAIN_WEIGHT: (float, SOLAR_GAIN_WEIGHT),
    CONF_SOLAR_GAIN_MAX_REDUCTION: (float, SOLAR_GAIN_MAX_REDUCTION),
    CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER: (
        float,
        DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    ),
    CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF: (float, DOOR_HEAT_SHARE_MIN_TEMP_DIFF),
    CONF_DOOR_HEAT_SHARE_WEIGHT: (float, DOOR_HEAT_SHARE_WEIGHT),
    CONF_DOOR_HEAT_SHARE_MAX_REDUCTION: (float, DOOR_HEAT_SHARE_MAX_REDUCTION),
}


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/update_config",
        probatio.Optional(CONF_ALARM_PANEL): probatio.Any(str, None),
        probatio.Optional(CONF_ALARM_AWAY_STATES): [probatio.In(ALARM_ARMED_STATES)],
        probatio.Optional(CONF_NOTIFY_SERVICE): probatio.Any(str, None),
        probatio.Optional(CONF_MANUAL_TRV_CONTROL): bool,
        probatio.Optional(CONF_PID_ENABLED): bool,
        probatio.Optional(CONF_NOTIFY_WINDOWS): bool,
        probatio.Optional(CONF_NOTIFY_WINDOW_WARNING_30): bool,
        probatio.Optional(CONF_NIGHT_SETBACK_ENABLED): bool,
        probatio.Optional(CONF_NOTIFY_PRESENCE): bool,
        probatio.Optional(CONF_NOTIFY_PREHEAT): bool,
        probatio.Optional(CONF_NOTIFY_MOLD_RISK): bool,
        probatio.Optional(CONF_NOTIFY_ISSUE_ESCALATION): bool,
        probatio.Optional(CONF_WEATHER_COMPENSATION_ENABLED): bool,
        probatio.Optional(CONF_SOLAR_GAIN_ENABLED): bool,
        probatio.Optional(CONF_DOOR_HEAT_SHARE_ENABLED): bool,
        probatio.Optional(CONF_FF_REFERENCE_OUTDOOR_TEMP): probatio.Any(float, int),
        probatio.Optional(CONF_FF_WEIGHT): probatio.Any(float, int),
        probatio.Optional(CONF_FF_MAX_CONTRIBUTION): probatio.Any(float, int),
        probatio.Optional(CONF_SOLAR_GAIN_LUX_THRESHOLD): probatio.Any(float, int),
        probatio.Optional(CONF_SOLAR_GAIN_WEIGHT): probatio.Any(float, int),
        probatio.Optional(CONF_SOLAR_GAIN_MAX_REDUCTION): probatio.Any(float, int),
        probatio.Optional(CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER): probatio.Any(
            float, int
        ),
        probatio.Optional(CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF): probatio.Any(float, int),
        probatio.Optional(CONF_DOOR_HEAT_SHARE_WEIGHT): probatio.Any(float, int),
        probatio.Optional(CONF_DOOR_HEAT_SHARE_MAX_REDUCTION): probatio.Any(float, int),
        probatio.Optional(CONF_PID_KP): probatio.Any(float, int),
        probatio.Optional(CONF_PID_KI): probatio.Any(float, int),
        probatio.Optional(CONF_PID_KD): probatio.Any(float, int),
        probatio.Optional(CONF_PID_SETPOINT_MARGIN): probatio.Any(float, int),
        probatio.Optional(CONF_BOOST_DEFAULT_TEMP): probatio.Any(float, int),
        probatio.Optional(CONF_BOOST_DEFAULT_MINUTES): probatio.Any(float, int),
        probatio.Optional(CONF_WINDOW_WARNING_MIN): probatio.Any(float, int),
        probatio.Optional(CONF_WINDOW_DELAY_DEFAULT_MIN): probatio.Any(float, int),
        probatio.Optional(CONF_WINDOW_OFF_TEMP): probatio.Any(float, int),
        probatio.Optional(CONF_MIN_ROOM_TEMP): probatio.All(
            probatio.Any(float, int),
            probatio.Range(min=MIN_ROOM_TEMP_RANGE[0], max=MIN_ROOM_TEMP_RANGE[1]),
        ),
        probatio.Optional(CONF_NIGHT_SETBACK_TEMP): probatio.Any(float, int),
        probatio.Optional(CONF_NIGHT_START_HOUR): probatio.Any(float, int),
        probatio.Optional(CONF_NIGHT_END_HOUR): probatio.Any(float, int),
        probatio.Optional(CONF_GRACE_DAY_MIN): probatio.Any(float, int),
        probatio.Optional(CONF_GRACE_NIGHT_MIN): probatio.Any(float, int),
        probatio.Optional(CONF_AUTO_OFF_TEMP_THRESHOLD): probatio.Any(float, int),
        probatio.Optional(CONF_AUTO_OFF_TEMP_DAYS): probatio.Any(float, int),
        probatio.Optional(CONF_ISSUE_ESCALATION_MINUTES): probatio.Any(float, int),
    }
)
@websocket_api.async_response
async def ws_update_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update editable global config fields from the sidebar panel.

    Fase 2, del 1 (2026-09-13): supports every field in _STRING_CONFIG_FIELDS/
    _BOOL_CONFIG_FIELD_DEFAULTS/_NUMERIC_CONFIG_FIELDS above — string fields
    (alarm_panel, notify_service), bool toggles (manual_trv_control, PID
    enabled, window/presence/preheat notify toggles, night setback enabled),
    and numeric fields (PID gains, boost defaults, window warning threshold,
    night setback temp/hours, grace day/night, auto-off threshold/days).
    Changes are persisted to entry.options and take effect immediately
    (no HA restart needed) because the coordinator reads config dynamically.
    An invalid numeric value returns an "invalid_value" WS error instead of
    silently writing a wrong type to entry.options.
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    # Build updated options dict — only touch keys that were sent
    current_options = dict(entry.options)
    changed: list[str] = []

    for key in _STRING_CONFIG_FIELDS:
        if key in msg:
            new_val = (msg[key] or "").strip()
            if current_options.get(key, "") != new_val:
                current_options[key] = new_val
                changed.append(key)

    for key, default in _BOOL_CONFIG_FIELD_DEFAULTS.items():
        if key in msg:
            new_bool = bool(msg[key])
            if current_options.get(key, default) != new_bool:
                current_options[key] = new_bool
                changed.append(key)

    # v0.67.7: alarm states that mean "house empty" (list of armed states).
    if CONF_ALARM_AWAY_STATES in msg:
        wanted = msg[CONF_ALARM_AWAY_STATES] or []
        new_states = [s for s in ALARM_ARMED_STATES if s in wanted]
        current_states = list(
            entry.options.get(
                CONF_ALARM_AWAY_STATES,
                entry.data.get(CONF_ALARM_AWAY_STATES, list(DEFAULT_ALARM_AWAY_STATES)),
            )
        )
        if current_states != new_states:
            current_options[CONF_ALARM_AWAY_STATES] = new_states
            changed.append(CONF_ALARM_AWAY_STATES)

    for key, (cast, numeric_default) in _NUMERIC_CONFIG_FIELDS.items():
        if key in msg:
            try:
                new_num = cast(msg[key])
            except (TypeError, ValueError):
                connection.send_error(
                    msg["id"], "invalid_value", f"Invalid value for {key}"
                )
                return
            if current_options.get(key, numeric_default) != new_num:
                current_options[key] = new_num
                changed.append(key)

    if not changed:
        connection.send_result(msg["id"], {"updated": False, "changed": []})
        return

    hass.config_entries.async_update_entry(entry, options=current_options)
    _LOGGER.info("Heat Manager config updated via panel: %s", changed)

    coordinator = entry.runtime_data
    coordinator.log_event(f"Config updated: {', '.join(changed)}", "Panel", "normal")

    connection.send_result(msg["id"], {"updated": True, "changed": changed})


# Punkt 3 (2026-09-13): per-room live editing from the Rum-fane's room cards,
# without going through the options-flow config wizard. Deliberately scoped
# to comfort_temp (v0.67.0: away_temp_override was replaced by the global
# min_room_temp) — CO₂ threshold stays options-flow-only. Bounds must mirror config_flow.py's _room_schema() selectors exactly,
# since this bypasses that schema's own validation entirely.
_ROOM_NUMERIC_FIELDS: dict[str, tuple[type, float, float, float]] = {
    # key -> (cast, default, min, max)
    CONF_COMFORT_TEMP: (float, DEFAULT_COMFORT_TEMP, 15.0, 26.0),
}


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "heat_manager/update_room_config",
        probatio.Required("room_name"): str,
        probatio.Optional(CONF_COMFORT_TEMP): probatio.Any(float, int),
    }
)
@websocket_api.async_response
async def ws_update_room_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update editable per-room config fields from the Rum-fane's room cards.

    Punkt 3 (2026-09-13): supports comfort_temp, the field chosen for inline
    panel editing (away_temp_override removed in v0.67.0). Writes the entire updated CONF_ROOMS list back to
    entry.options (mirroring the options-flow room-edit step's own write
    pattern), which coordinator.rooms/coordinator.config pick up immediately
    since they read entry.options fresh on every access — no reload needed.
    An out-of-range or non-numeric value returns an "invalid_value" WS error
    instead of silently writing a wrong value to entry.options.
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    coordinator = entry.runtime_data
    room_name = msg["room_name"]
    rooms = list(coordinator.rooms)
    room_idx = next(
        (i for i, r in enumerate(rooms) if r.get(CONF_ROOM_NAME) == room_name), None
    )
    if room_idx is None:
        connection.send_error(
            msg["id"], "not_found", f"Room '{room_name}' not configured"
        )
        return

    updated_room = dict(rooms[room_idx])
    changed: list[str] = []

    for key, (cast, default, min_val, max_val) in _ROOM_NUMERIC_FIELDS.items():
        if key not in msg:
            continue
        try:
            new_num = cast(msg[key])
        except (TypeError, ValueError):
            connection.send_error(
                msg["id"], "invalid_value", f"Invalid value for {key}"
            )
            return
        if not (min_val <= new_num <= max_val):
            connection.send_error(
                msg["id"],
                "invalid_value",
                f"{key} must be between {min_val} and {max_val}",
            )
            return
        if updated_room.get(key, default) != new_num:
            updated_room[key] = new_num
            changed.append(key)

    if not changed:
        connection.send_result(msg["id"], {"updated": False, "changed": []})
        return

    rooms[room_idx] = updated_room
    current_options = dict(entry.options)
    current_options[CONF_ROOMS] = rooms
    hass.config_entries.async_update_entry(entry, options=current_options)
    _LOGGER.info("Room '%s' config updated via panel: %s", room_name, changed)

    coordinator.log_event(
        f"{room_name}: {', '.join(changed)} updated",
        reason="manuel panel",
        event_type="normal",
    )

    connection.send_result(msg["id"], {"updated": True, "changed": changed})


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_entry(hass: HomeAssistant) -> Any:
    """Return the active Heat Manager config entry.

    Iterates loaded entries and returns the first one that has a live
    coordinator in runtime_data.  No hass.data lookup needed — entry.runtime_data
    is the single source of truth (IQS pattern).
    """
    candidates = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if hasattr(e, "runtime_data") and e.runtime_data is not None
    ]
    return candidates[0] if candidates else None


def _get_event_log(coordinator: Any, days: int) -> list[dict[str, Any]]:
    """Return events from coordinator._event_log deque, newest first, capped at 50."""
    from homeassistant.util.dt import now as ha_now

    cutoff = ha_now() - timedelta(days=days)
    event_log = list(getattr(coordinator, "_event_log", []))
    result = []
    for e in event_log:
        ts = e.get("timestamp")
        if not ts:
            result.append(e)
            continue
        try:
            from datetime import datetime as _dt

            dt = _dt.fromisoformat(ts)
            if dt.tzinfo is None:
                from homeassistant.util.dt import UTC

                dt = dt.replace(tzinfo=UTC)
            if dt >= cutoff:
                result.append(e)
        except (ValueError, TypeError):
            result.append(e)
    return result[:50]
