"""
Heat Manager — WebSocket API

Registers WS commands used by the sidebar panel:
  heat_manager/get_state    → full state snapshot
  heat_manager/get_history  → event log for the last N days

Phase 3: energy values now come directly from coordinator.waste_calculator.
         Event log reads from coordinator._event_log (deque, newest first).
         Daily energy chart shows live today + zeros for past days.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_AWAY_TEMP_COLD,
    CONF_AWAY_TEMP_MILD,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_NOTIFY_SERVICE,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all Heat Manager WebSocket commands."""
    websocket_api.async_register_command(hass, ws_get_state)
    websocket_api.async_register_command(hass, ws_get_history)
    _LOGGER.debug("WebSocket commands registered")


# ── heat_manager/get_state ────────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"): "heat_manager/get_state",
})
@websocket_api.async_response
async def ws_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return full Heat Manager state snapshot."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    coordinator = entry.runtime_data
    ctrl = coordinator.controller
    cfg  = coordinator.config

    # ── Rooms ─────────────────────────────────────────────────────────────────
    rooms = []
    for room in coordinator.rooms:
        name       = room.get("room_name", "")
        climate_id = room.get("climate_entity", "")
        sensors    = room.get(CONF_WINDOW_SENSORS, [])
        room_state = coordinator.get_room_state(name)

        current_temp: float | None = None
        if climate_id:
            cs = hass.states.get(climate_id)
            if cs:
                t = cs.attributes.get("current_temperature")
                if t is not None:
                    try:
                        current_temp = float(t)
                    except (TypeError, ValueError):
                        pass

        windows_open = any(
            (s := hass.states.get(sid)) is not None and s.state == "on"
            for sid in sensors
        )

        rooms.append({
            "name":           name,
            "climate_entity": climate_id,
            "state":          room_state.value,
            "current_temp":   current_temp,
            "windows_open":   windows_open,
            "why":            _why_label(room_state),
        })

    # ── Persons ───────────────────────────────────────────────────────────────
    persons = []
    for person in coordinator.persons:
        entity_id = person.get(CONF_PERSON_ENTITY, "")
        tracking  = person.get(CONF_PERSON_TRACKING, True)
        ps        = hass.states.get(entity_id) if entity_id else None
        state_str = ps.state if ps else "unknown"
        since: str | None = None
        if ps and ps.last_changed:
            since = _fmt_time(ps.last_changed)
        if ps:
            name = ps.attributes.get("friendly_name") or entity_id.split(".")[-1]
        else:
            name = entity_id.split(".")[-1] if entity_id else ""

        persons.append({
            "name":     name,
            "entity":   entity_id,
            "state":    state_str,
            "tracking": tracking,
            "since":    since,
        })

    # ── Outdoor temperature ───────────────────────────────────────────────────
    outdoor_temp: float | None = coordinator.outdoor_temperature

    # ── Config snapshot ────────────────────────────────────────────────────────
    config_snap = {
        "weather_entity":          cfg.get(CONF_WEATHER_ENTITY, ""),
        "grace_day_min":           cfg.get(CONF_GRACE_DAY_MIN),
        "grace_night_min":         cfg.get(CONF_GRACE_NIGHT_MIN),
        "away_temp_mild":          cfg.get(CONF_AWAY_TEMP_MILD),
        "away_temp_cold":          cfg.get(CONF_AWAY_TEMP_COLD),
        "auto_off_temp_threshold": cfg.get(CONF_AUTO_OFF_TEMP_THRESHOLD),
        "auto_off_temp_days":      cfg.get(CONF_AUTO_OFF_TEMP_DAYS),
        "alarm_panel":             cfg.get(CONF_ALARM_PANEL, ""),
        "notify_service":          cfg.get(CONF_NOTIFY_SERVICE, ""),
    }

    payload: dict[str, Any] = {
        "controller_state":       ctrl.state.value,
        "auto_off_reason":        ctrl.auto_off_reason.value,
        "pause_remaining":        ctrl.pause_remaining_minutes,
        "season_mode":            coordinator.season_mode.value,
        "effective_season":       coordinator.effective_season.value,
        "outdoor_temp":           outdoor_temp,
        "rooms":                  rooms,
        "persons":                persons,
        "energy_saved_today":     coordinator.energy_saved_today,
        "energy_wasted_today":    coordinator.energy_wasted_today,
        "efficiency_score":       coordinator.efficiency_score,
        "auto_off_days":          coordinator.season_engine.days_above_threshold,
        "auto_off_days_required": cfg.get(CONF_AUTO_OFF_TEMP_DAYS, 5),
        "auto_off_threshold":     cfg.get(CONF_AUTO_OFF_TEMP_THRESHOLD, 18.0),
        "config":                 config_snap,
    }

    connection.send_result(msg["id"], payload)


# ── heat_manager/get_history ──────────────────────────────────────────────────

@websocket_api.websocket_command({
    vol.Required("type"): "heat_manager/get_history",
    vol.Optional("days", default=7): vol.All(int, vol.Range(min=1, max=30)),
})
@websocket_api.async_response
async def ws_get_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return event log and daily energy chart data."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    coordinator = entry.runtime_data
    days = msg.get("days", 7)

    events = _get_event_log(coordinator, days)
    daily  = _build_daily_energy(coordinator, days)

    connection.send_result(msg["id"], {
        "events": events,
        "days":   daily,
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_entry(hass: HomeAssistant) -> Any:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, "runtime_data") and entry.runtime_data is not None:
            return entry
    return None


def _why_label(state: Any) -> str:
    from .const import RoomState
    return {
        RoomState.NORMAL:      "Active — someone home",
        RoomState.AWAY:        "Nobody home → away mode",
        RoomState.WINDOW_OPEN: "Window open → heating suppressed",
        RoomState.PRE_HEAT:    "Pre-heating before arrival",
        RoomState.OVERRIDE:    "Manual override active",
    }.get(state, "")


def _fmt_time(dt: datetime) -> str:
    from homeassistant.util.dt import now as ha_now
    local_now = ha_now()
    local_dt  = dt.astimezone(local_now.tzinfo)
    if local_dt.date() == local_now.date():
        return local_dt.strftime("%H:%M")
    if local_dt.date() == (local_now - timedelta(days=1)).date():
        return "i går " + local_dt.strftime("%H:%M")
    return local_dt.strftime("%d/%m %H:%M")


def _get_event_log(coordinator: Any, days: int) -> list[dict]:
    """Return events from coordinator._event_log deque, newest first, capped at 50."""
    from homeassistant.util.dt import now as ha_now
    cutoff    = ha_now() - timedelta(days=days)
    event_log = list(getattr(coordinator, "_event_log", []))
    result    = []
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


def _build_daily_energy(coordinator: Any, days: int) -> list[dict]:
    """Today uses live WasteCalculator values; past days are 0 until persistent storage exists."""
    from homeassistant.util.dt import now as ha_now
    today      = ha_now().date()
    day_labels = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]
    result = []
    for i in range(days - 1, -1, -1):
        d        = today - timedelta(days=i)
        is_today = (i == 0)
        result.append({
            "label":  day_labels[d.weekday()],
            "date":   d.isoformat(),
            "saved":  round(coordinator.energy_saved_today, 3) if is_today else 0.0,
            "wasted": round(coordinator.energy_wasted_today, 3) if is_today else 0.0,
        })
    return result
