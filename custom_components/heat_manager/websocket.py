"""
Heat Manager — WebSocket API

Registers WS commands used by the sidebar panel:
  heat_manager/get_state    → full state snapshot
  heat_manager/get_history  → event log for the last N days

Phase 3: energy values now come directly from coordinator.waste_calculator.
         Event log reads from coordinator._event_log (deque, newest first).
         Daily energy chart shows live today + zeros for past days.

v0.4.2: _get_entry() uses entry.runtime_data exclusively — no hass.data lookup.
"""

from __future__ import annotations

import contextlib
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
    CONF_HOUSE_VOICE_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command({vol.Required("type"): "heat_manager/boost_start"})
@websocket_api.async_response
async def ws_boost_start(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """WebSocket: start boost mode for all rooms.

    Sets boost_active_rooms flag on coordinator and triggers a load()
    from the frontend. Actual TRV commands are handled by the boost engine
    when it is implemented. For now, sets the flag and notifies the panel.
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    for room in coordinator.rooms:
        name = room.get("room_name", "")
        if name:
            coordinator.boost_active_rooms[name] = True
    coordinator.log_event("Boost aktiveret", reason="manuel", event_type="boost")
    _LOGGER.info("Boost started — %d rooms", len(coordinator.boost_active_rooms))
    connection.send_result(msg["id"], {"success": True, "rooms_boosted": len(coordinator.boost_active_rooms)})


@websocket_api.websocket_command({vol.Required("type"): "heat_manager/boost_stop"})
@websocket_api.async_response
async def ws_boost_stop(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """WebSocket: stop boost mode."""
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager not loaded")
        return
    coordinator: HeatManagerCoordinator = entry.runtime_data
    coordinator.boost_active_rooms.clear()
    coordinator.log_event("Boost deaktiveret", reason="manuel", event_type="boost")
    _LOGGER.info("Boost stopped")
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command({
    vol.Required("type"): "heat_manager/set_room_temp",
    vol.Required("room_name"): str,
    vol.Optional("temperature"): vol.Any(float, int, None),
    vol.Optional("duration_min", default=60): int,
})
@websocket_api.async_response
async def ws_set_room_temp(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
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
    room_name   = msg["room_name"]
    temperature = msg.get("temperature")
    duration    = int(msg.get("duration_min", 60))

    # Find room config
    room_cfg = next(
        (r for r in coordinator.rooms if r.get("room_name") == room_name), None
    )
    if room_cfg is None:
        connection.send_error(msg["id"], "not_found", f"Room '{room_name}' not configured")
        return

    write_entity = coordinator.get_write_entity(room_name)
    if write_entity is None:
        connection.send_error(msg["id"], "not_found", f"No write entity for room '{room_name}'")
        return

    trv_type = room_cfg.get("trv_type", "netatmo")

    try:
        if temperature is None:
            # Restore to schedule
            if trv_type == "zigbee":
                await hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": write_entity, "hvac_mode": "heat"},
                    blocking=True,
                )
            else:
                cloud_entity = coordinator.get_climate_entity(room_name)
                await hass.services.async_call(
                    "climate", "set_preset_mode",
                    {"entity_id": cloud_entity, "preset_mode": "schedule"},
                    blocking=True,
                )
            coordinator.log_event(
                f"{room_name}: schedule gendannet", reason="manuel panel", event_type="manual"
            )
            _LOGGER.info("Room '%s' restored to schedule", room_name)
        else:
            # Set temperature
            temp = float(temperature)
            await hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": write_entity, "temperature": temp},
                blocking=True,
            )
            dur_label = f"{duration} min" if duration > 0 else "permanent"
            coordinator.log_event(
                f"{room_name}: {temp}\u00b0C ({dur_label})",
                reason="manuel panel",
                event_type="manual",
            )
            _LOGGER.info(
                "Room '%s' set to %.1f\u00b0C for %s via %s",
                room_name, temp, dur_label, write_entity,
            )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("set_room_temp failed for '%s': %s", room_name, err)
        connection.send_error(msg["id"], "service_error", str(err))
        return

    connection.send_result(msg["id"], {
        "success": True,
        "room": room_name,
        "temperature": temperature,
        "duration_min": duration,
        "write_entity": write_entity,
    })


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all Heat Manager WebSocket commands."""
    websocket_api.async_register_command(hass, ws_get_state)
    websocket_api.async_register_command(hass, ws_get_history)
    websocket_api.async_register_command(hass, ws_update_config)
    websocket_api.async_register_command(hass, ws_boost_start)
    websocket_api.async_register_command(hass, ws_boost_stop)
    websocket_api.async_register_command(hass, ws_set_room_temp)
    _LOGGER.debug("WebSocket commands registered")


# ── heat_manager/get_state ────────────────────────────────────────────────────


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heat_manager/get_state",
    }
)
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
    cfg = coordinator.config

    # ── Rooms ─────────────────────────────────────────────────────────────────
    rooms = []
    for room in coordinator.rooms:
        name = room.get("room_name", "")
        climate_id = room.get("climate_entity", "")
        sensors = room.get(CONF_WINDOW_SENSORS, [])
        room_state = coordinator.get_room_state(name)

        current_temp: float | None = coordinator.get_room_current_temp(name, climate_id)
        heating_power: float | None = None
        valve_position: float | None = None  # B1: valve % for Zigbee and Netatmo
        boost_active: bool = False  # B2: boost state per room

        if climate_id:
            cs = hass.states.get(climate_id)
            if cs:
                raw = cs.attributes.get("heating_power_request")
                if raw is not None:
                    with contextlib.suppress(TypeError, ValueError):
                        heating_power = float(raw)
                        valve_position = (
                            heating_power  # Netatmo: heating_power_request IS valve %
                        )

        # B1: Zigbee pi_demand_entity overrides Netatmo valve when present
        from .const import CONF_PI_DEMAND_ENTITY

        pi_entity = room.get(CONF_PI_DEMAND_ENTITY) or None
        if pi_entity:
            pi_state = hass.states.get(pi_entity)
            if pi_state and pi_state.state not in ("unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    valve_position = float(pi_state.state)

        # B2: boost_active — read from coordinator boost state when available
        boost_state = getattr(coordinator, "boost_active_rooms", {})
        boost_active = bool(boost_state.get(name, False))

        windows_open = any(
            (s := hass.states.get(sid)) is not None and s.state == "on"
            for sid in sensors
        )

        rooms.append(
            {
                "name": name,
                "climate_entity": climate_id,
                "state": room_state.value,
                "current_temp": current_temp,
                "heating_power": heating_power,
                "valve_position": valve_position,  # B1
                "boost_active": boost_active,  # B2
                "windows_open": windows_open,
                "why": _why_label(room_state),
            }
        )

    # ── Persons ───────────────────────────────────────────────────────────────
    persons = []
    for person in coordinator.persons:
        entity_id = person.get(CONF_PERSON_ENTITY, "")
        tracking = person.get(CONF_PERSON_TRACKING, True)
        ps = hass.states.get(entity_id) if entity_id else None
        state_str = ps.state if ps else "unknown"
        since: str | None = None
        if ps and ps.last_changed:
            since = _fmt_time(ps.last_changed)
        if ps:
            name = ps.attributes.get("friendly_name") or entity_id.split(".")[-1]
        else:
            name = entity_id.split(".")[-1] if entity_id else ""

        persons.append(
            {
                "name": name,
                "entity": entity_id,
                "state": state_str,
                "tracking": tracking,
                "since": since,
            }
        )

    # ── Outdoor temperature ───────────────────────────────────────────────────
    outdoor_temp: float | None = coordinator.outdoor_temperature

    # ── Config snapshot ────────────────────────────────────────────────────────
    config_snap = {
        "weather_entity": cfg.get(CONF_WEATHER_ENTITY, ""),
        "grace_day_min": cfg.get(CONF_GRACE_DAY_MIN),
        "grace_night_min": cfg.get(CONF_GRACE_NIGHT_MIN),
        "away_temp_mild": cfg.get(CONF_AWAY_TEMP_MILD),
        "away_temp_cold": cfg.get(CONF_AWAY_TEMP_COLD),
        "auto_off_temp_threshold": cfg.get(CONF_AUTO_OFF_TEMP_THRESHOLD),
        "auto_off_temp_days": cfg.get(CONF_AUTO_OFF_TEMP_DAYS),
        "alarm_panel": cfg.get(CONF_ALARM_PANEL, ""),
        "notify_service": cfg.get(CONF_NOTIFY_SERVICE, ""),
        "house_voice_enabled": cfg.get(CONF_HOUSE_VOICE_ENABLED, False),
    }

    payload: dict[str, Any] = {
        "controller_state": ctrl.state.value,
        "auto_off_reason": ctrl.auto_off_reason.value,
        "pause_remaining": ctrl.pause_remaining_minutes,
        "season_mode": coordinator.season_mode.value,
        "effective_season": coordinator.effective_season.value,
        "outdoor_temp": outdoor_temp,
        "rooms": rooms,
        "persons": persons,
        "energy_saved_today": coordinator.energy_saved_today,
        "energy_wasted_today": coordinator.energy_wasted_today,
        "efficiency_score": coordinator.efficiency_score,
        "last_waste_time": coordinator.last_waste_time,
        "last_saved_time": coordinator.last_saved_time,
        "calendar_season": coordinator.calendar_season.value,
        "auto_off_days": coordinator.days_above_threshold,
        "auto_off_days_required": cfg.get(CONF_AUTO_OFF_TEMP_DAYS, 5),
        "auto_off_threshold": cfg.get(CONF_AUTO_OFF_TEMP_THRESHOLD, 18.0),
        "config": config_snap,
    }

    connection.send_result(msg["id"], payload)


# ── heat_manager/get_history ──────────────────────────────────────────────────


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heat_manager/get_history",
        vol.Optional("days", default=7): vol.All(int, vol.Range(min=1, max=30)),
    }
)
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
    daily = _build_daily_energy(coordinator, days)

    connection.send_result(
        msg["id"],
        {
            "events": events,
            "days": daily,
        },
    )


# ── heat_manager/update_config ────────────────────────────────────────────────


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heat_manager/update_config",
        vol.Optional(CONF_ALARM_PANEL): vol.Any(str, None),
        vol.Optional(CONF_NOTIFY_SERVICE): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_update_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Update editable global config fields from the sidebar panel.

    Currently supports: alarm_panel, notify_service.
    Changes are persisted to entry.options and take effect immediately
    (no HA restart needed) because the coordinator reads config dynamically.
    """
    entry = _get_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Heat Manager is not configured")
        return

    # Build updated options dict — only touch keys that were sent
    current_options = dict(entry.options)
    changed: list[str] = []

    for key in (CONF_ALARM_PANEL, CONF_NOTIFY_SERVICE):
        if key in msg:
            new_val = (msg[key] or "").strip()
            if current_options.get(key, "") != new_val:
                current_options[key] = new_val
                changed.append(key)

    if not changed:
        connection.send_result(msg["id"], {"updated": False, "changed": []})
        return

    hass.config_entries.async_update_entry(entry, options=current_options)
    _LOGGER.info("Heat Manager config updated via panel: %s", changed)

    coordinator = entry.runtime_data
    coordinator.log_event(f"Config updated: {', '.join(changed)}", "Panel", "normal")

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


def _why_label(state: Any) -> str:
    from .const import RoomState

    return {
        RoomState.NORMAL: "Active — someone home",
        RoomState.AWAY: "Nobody home → away mode",
        RoomState.WINDOW_OPEN: "Window open → heating suppressed",
        RoomState.PRE_HEAT: "Pre-heating before arrival",
        RoomState.OVERRIDE: "Manual override active",
    }.get(state, "")


def _fmt_time(dt: datetime) -> str:
    # S-7 FIX: neutral date format — panel JS handles locale-specific labels
    from homeassistant.util.dt import now as ha_now

    local_now = ha_now()
    local_dt = dt.astimezone(local_now.tzinfo)
    if local_dt.date() == local_now.date():
        return local_dt.strftime("%H:%M")
    return local_dt.strftime("%d/%m %H:%M")


def _get_event_log(coordinator: Any, days: int) -> list[dict]:
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


def _build_daily_energy(coordinator: Any, days: int) -> list[dict]:
    """B3/B7: Today from live WasteCalculator; past days from persistent snapshot.

    Energy snapshots are saved to coordinator._energy_history (dict keyed by
    ISO date string) each midnight via _persist_energy_snapshot(). This gives
    meaningful historical bars without requiring a database.
    """
    from homeassistant.util.dt import now as ha_now

    today = ha_now().date()
    day_labels = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]
    history: dict = getattr(coordinator, "_energy_history", {})

    result = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        is_today = i == 0
        if is_today:
            saved = round(coordinator.energy_saved_today, 3)
            wasted = round(coordinator.energy_wasted_today, 3)
        else:
            snap = history.get(d.isoformat(), {})
            saved = round(float(snap.get("saved", 0.0)), 3)
            wasted = round(float(snap.get("wasted", 0.0)), 3)
        result.append(
            {
                "label": day_labels[d.weekday()],
                "date": d.isoformat(),
                "saved": saved,
                "wasted": wasted,
            }
        )
    return result
