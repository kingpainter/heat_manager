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

import contextlib
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.dt import utcnow

from .const import (
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_BATTERY_SENSOR,
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    CONF_CLIMATE_ENTITY,
    CONF_CO2_SENSOR,
    CONF_DOOR_ROOM_A,
    CONF_DOOR_ROOM_B,
    CONF_DOOR_SENSOR,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_HOUSE_VOICE_ENABLED,
    CONF_HUMIDITY_SENSOR,
    CONF_MANUAL_TRV_CONTROL,
    CONF_NIGHT_END_HOUR,
    CONF_NIGHT_SETBACK_ENABLED,
    CONF_NIGHT_SETBACK_TEMP,
    CONF_NIGHT_START_HOUR,
    CONF_NOTIFY_MOLD_RISK,
    CONF_NOTIFY_PREHEAT,
    CONF_NOTIFY_PRESENCE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_WINDOW_WARNING_30,
    CONF_NOTIFY_WINDOWS,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PI_DEMAND_ENTITY,
    CONF_PID_ENABLED,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_SCHEDULE_ENTITY,
    CONF_SYNC_MODE,
    CONF_TRV_TYPE,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_WARNING_MIN,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMP,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_GRACE_NIGHT_MIN,
    DEFAULT_MANUAL_TRV_CONTROL,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_SETBACK_ENABLED,
    DEFAULT_NIGHT_SETBACK_TEMP,
    DEFAULT_NIGHT_START_HOUR,
    DEFAULT_PID_KD,
    DEFAULT_PID_KI,
    DEFAULT_PID_KP,
    DEFAULT_WINDOW_WARNING_MIN,
    DOMAIN,
    RoomState,
)
from .panel import _get_version

if TYPE_CHECKING:
    from .coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# 2026-09-07 audit fix (5.3) — mold-risk thresholds, intentionally duplicated
# from binary_sensor.py's MoldRiskSensor (_RH_THRESHOLD/_SURFACE_MARGIN) so
# ws_get_state can surface the same signal without importing the
# binary_sensor platform module. Keep these in sync if the algorithm changes.
_MOLD_RH_THRESHOLD = 70.0  # % — DIN 4108-2 critical humidity
_MOLD_SURFACE_MARGIN = 1.0  # °C — wall surface is ~1 °C cooler than air


def _mold_dewpoint(temp_c: float, rh_pct: float) -> float:
    """Magnus formula (Lawrence 2005) — valid for 0-60 °C, 1-100% RH."""
    import math

    b, c = 17.625, 243.04
    gamma = math.log(max(rh_pct, 0.01) / 100.0) + (b * temp_c) / (c + temp_c)
    return (c * gamma) / (b - gamma)


def _coerce_float(value: Any) -> float | None:
    """Best-effort float conversion for a raw climate-entity attribute —
    Fase 2 (2026-09-11): these come straight from another integration's
    entity and are never guaranteed numeric (unavailable/unknown/None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heat_manager/boost_start",
        vol.Optional("temperature"): vol.Any(float, int),
        vol.Optional("duration_minutes"): vol.Any(float, int),
    }
)
@websocket_api.async_response
async def ws_boost_start(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
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


@websocket_api.websocket_command({vol.Required("type"): "heat_manager/boost_stop"})
@websocket_api.async_response
async def ws_boost_stop(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
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
        vol.Required("type"): "heat_manager/set_room_temp",
        vol.Required("room_name"): str,
        vol.Optional("temperature"): vol.Any(float, int, None),
        vol.Optional("duration_min", default=60): int,
    }
)
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
    # command, each routed by its own trv_type/write-entity policy \u2014
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
                if trv_type == "zigbee":
                    entity_id = coordinator.get_trv_write_entity(trv) or trv.get(
                        CONF_CLIMATE_ENTITY
                    )
                    if not entity_id:
                        continue
                    await hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": "heat"},
                        blocking=True,
                    )
                else:
                    entity_id = trv.get(CONF_CLIMATE_ENTITY)
                    if not entity_id:
                        continue
                    await hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": entity_id, "preset_mode": "schedule"},
                        blocking=True,
                    )
                if write_entity is None:
                    write_entity = entity_id
            coordinator.log_event(
                f"{room_name}: schedule gendannet",
                reason="manuel panel",
                event_type="manual",
            )
            _LOGGER.info("Room '%s' restored to schedule", room_name)
        else:
            # Set temperature \u2014 same setpoint fanned out to every TRV's
            # write entity (HomeKit-preferred, matching the pre-existing
            # single-TRV policy).
            temp = float(temperature)
            write_entities = coordinator.get_room_write_entities(room_name)
            if not write_entities:
                connection.send_error(
                    msg["id"],
                    "not_found",
                    f"No write entity for room '{room_name}'",
                )
                return
            for entity_id in write_entities:
                await hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": temp},
                    blocking=True,
                )
            write_entity = write_entities[0]
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
            # override switch and the remote-button engine \u2014 previously
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

    # 2026-09-11: panel.py already reads manifest.json (off-thread, via
    # async_add_executor_job — it's blocking file I/O) as the cache-busting
    # query string's version — reuse that same helper/source-of-truth here
    # instead of a second, independently-maintained copy, so the number
    # shown in the panel's header can never drift from the one actually
    # bumped in manifest.json (see panel.py's _get_version docstring for
    # the const.py drift history this already burned us on once).
    integration_version = await hass.async_add_executor_job(_get_version, hass)

    # ── Rooms ─────────────────────────────────────────────────────────────────
    rooms = []
    for room in coordinator.rooms:
        name = room.get("room_name", "")
        # B18/room-detail fix: resolve via the primary TRV (CONF_TRVS),
        # not the room's flat climate_entity/trv_type/pi_demand_entity
        # fields — those are only ever mirrored from trvs[0] in memory by
        # migrate_room_to_trvs() and are never re-persisted to the config
        # entry once a room has been saved through the per-TRV edit UI,
        # which writes CONF_TRVS only. Reading the flat fields directly
        # left climate_id empty for any such room, which cascaded into
        # missing setpoint/TRV-temp/valve % in the panel.
        primary_trv = next(iter(coordinator.get_all_room_trvs(name)), {})
        climate_id = primary_trv.get(CONF_CLIMATE_ENTITY, "")
        sensors = room.get(CONF_WINDOW_SENSORS, [])
        room_state = coordinator.get_room_state(name)

        current_temp: float | None = coordinator.get_room_current_temp(name, climate_id)
        heating_power: float | None = None
        valve_position: float | None = None  # B1: valve % for Zigbee and Netatmo
        boost_active: bool = False  # B2: boost state per room

        # Fase 2 (2026-09-11) — Heat Manager's own resolved target, shared
        # with _async_pid_tick() via get_room_target_temp() so this can never
        # show a different number than what the PID actually chases (the gap
        # that made the B21 target-temp bug invisible in the first place).
        # 2026-09-11 (monitoring-only rooms): get_room_target_temp() always
        # returns a computed number regardless of whether the room has a
        # TRV — it's a pure function of comfort_temp/offsets/setbacks. For a
        # room with no TRV at all (climate_id empty — e.g. a hallway with
        # only a temp sensor), _async_pid_tick() never runs for it and
        # nothing ever chases that number, so showing it as a real
        # "Sætpunkt" would be actively misleading. None here instead.
        target_temp: float | None = (
            coordinator.get_room_target_temp(room) if climate_id else None
        )

        # Fase 2 — raw attributes straight from the room's cloud climate
        # entity (Netatmo rooms only; stay None for Zigbee/local rooms,
        # which have no separate cloud entity). Read-only diagnostics: shows
        # what Netatmo itself currently reports (its own last-applied
        # setpoint, schedule, hvac/preset state) side by side with
        # Heat Manager's own target_temp above, so the two are never
        # confused again — see
        # audit/heat_manager_target_temp_analysis_2026-09-11.md. Also the
        # user's `select.mit_hjem`-style visibility request: hvac_modes/
        # preset_modes/min_temp/max_temp/target_temp_step describe what the
        # entity supports; NetatmoPresetModeSelect (select.py) is the actual
        # control surface for preset_mode.
        cloud_temperature: float | None = None
        cloud_hvac_action: str | None = None
        cloud_preset_mode: str | None = None
        cloud_preset_modes: list[str] | None = None
        cloud_selected_schedule: str | None = None
        cloud_hvac_modes: list[str] | None = None
        cloud_min_temp: float | None = None
        cloud_max_temp: float | None = None
        cloud_target_temp_step: float | None = None

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
                cloud_temperature = _coerce_float(cs.attributes.get("temperature"))
                cloud_hvac_action = cs.attributes.get("hvac_action")
                cloud_preset_mode = cs.attributes.get("preset_mode")
                cloud_preset_modes = cs.attributes.get("preset_modes")
                cloud_selected_schedule = cs.attributes.get("selected_schedule")
                cloud_hvac_modes = cs.attributes.get("hvac_modes")
                cloud_min_temp = _coerce_float(cs.attributes.get("min_temp"))
                cloud_max_temp = _coerce_float(cs.attributes.get("max_temp"))
                cloud_target_temp_step = _coerce_float(
                    cs.attributes.get("target_temp_step")
                )

        # B1: Zigbee pi_demand_entity overrides Netatmo valve when present
        pi_entity = primary_trv.get(CONF_PI_DEMAND_ENTITY) or None
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

        # Room detail cards: TRV battery (%), humidity (%) and CO2 (ppm) —
        # only surfaced when the room has the relevant sensor configured, so
        # the frontend can omit fields that don't apply to a given room.
        battery_level: float | None = None
        battery_entity = room.get(CONF_BATTERY_SENSOR) or None
        if battery_entity:
            bs = hass.states.get(battery_entity)
            if bs and bs.state not in ("unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    battery_level = float(bs.state)
        elif climate_id:
            # Fallback: some Netatmo setups expose battery as an attribute
            # on the climate entity itself rather than a separate sensor.
            cs = hass.states.get(climate_id)
            raw_batt = cs.attributes.get("battery_level") if cs else None
            if raw_batt is not None:
                with contextlib.suppress(TypeError, ValueError):
                    battery_level = float(raw_batt)

        humidity: float | None = None
        humidity_entity = room.get(CONF_HUMIDITY_SENSOR) or None
        if humidity_entity:
            hs = hass.states.get(humidity_entity)
            if hs and hs.state not in ("unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    humidity = float(hs.state)

        co2: float | None = None
        co2_entity = room.get(CONF_CO2_SENSOR) or None
        if co2_entity:
            c2s = hass.states.get(co2_entity)
            if c2s and c2s.state not in ("unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    co2 = float(c2s.state)

        # 2026-09-07 audit fix (5.3): MoldRiskSensor (binary_sensor.py)
        # computes this per room but it was never surfaced in either
        # frontend — a real, quietly-computed safety signal invisible to
        # the user. Recomputed here from the same humidity/current_temp
        # values already fetched above (rather than looking up the sensor
        # entity by its generated entity_id) — same pattern already used
        # for heating_power/valve_position in this function. The formula
        # and thresholds are intentionally duplicated from
        # MoldRiskSensor._dewpoint()/_RH_THRESHOLD/_SURFACE_MARGIN to avoid
        # importing the binary_sensor platform module from here.
        mold_risk = (
            humidity is not None
            and current_temp is not None
            and humidity >= _MOLD_RH_THRESHOLD
            and current_temp
            <= _mold_dewpoint(current_temp, humidity) + _MOLD_SURFACE_MARGIN
        )

        # 2026-09 frontend-parity fix — PID power, calibration offset and
        # window-open-minutes-today were computed but only ever visible via
        # HA's own entity page (diagnostic sensors, off by default until
        # this session flipped them to enabled-by-default in sensor.py).
        # PID power and calibration offset already live directly on the
        # coordinator/engine — read the same underlying value the sensors
        # themselves read, no entity lookup needed. Window-duration's
        # running total (accumulated across possibly several open/close
        # cycles today) only exists inside RoomWindowDurationSensor's own
        # instance state, so it's resolved via the entity registry by
        # unique_id (not by guessing the entity_id) and read like any other
        # entity this function already reads.
        pid_power: float | None = None
        pid = coordinator.get_pid(name)
        if pid is not None:
            raw_pid = getattr(pid, "_last_output", None)
            if raw_pid is not None:
                pid_power = round(raw_pid * 100.0, 1)

        calibration_offset = coordinator.calibration_engine._last_written.get(name)

        window_duration_today: int | None = None
        safe_name = name.lower().replace(" ", "_")
        window_duration_uid = f"{entry.entry_id}_{safe_name}_window_duration"
        window_duration_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, window_duration_uid
        )
        if window_duration_id:
            wds = hass.states.get(window_duration_id)
            if wds and wds.state not in ("unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    window_duration_today = int(float(wds.state))

        # 2026-09 audit fix (UI/UX #8) — the old cloud-status check (panel.js
        # _cloudStatus()) only ever looked at the room's *primary* TRV. Give
        # the frontend the full picture instead: every configured entity
        # this room actually depends on (all TRVs, not just the primary —
        # multi-TRV rooms have secondary TRVs the old check never saw —
        # plus window/humidity/CO2/battery sensors), so it can tell "Netatmo
        # cloud is down" apart from "some other sensor/TRV is unavailable"
        # instead of only ever detecting the former.
        unavailable_entities: list[str] = []
        for trv in coordinator.get_all_room_trvs(name):
            trv_id = trv.get(CONF_CLIMATE_ENTITY, "")
            if trv_id:
                trv_state = hass.states.get(trv_id)
                if trv_state is None or trv_state.state in ("unknown", "unavailable"):
                    unavailable_entities.append(trv_id)
        for sensor_id in sensors:
            sensor_state = hass.states.get(sensor_id)
            if sensor_state is None or sensor_state.state in (
                "unknown",
                "unavailable",
            ):
                unavailable_entities.append(sensor_id)
        for extra_id in (battery_entity, humidity_entity, co2_entity):
            if extra_id:
                extra_state = hass.states.get(extra_id)
                if extra_state is None or extra_state.state in (
                    "unknown",
                    "unavailable",
                ):
                    unavailable_entities.append(extra_id)

        rooms.append(
            {
                "name": name,
                "climate_entity": climate_id,
                # B15: for UI badge. 2026-09-11: None (not a fake "netatmo"
                # default) when the room has no TRV at all — a monitoring-only
                # room (e.g. a hallway) shouldn't show a misleading TRV-type
                # badge for hardware it doesn't have.
                "trv_type": primary_trv.get(CONF_TRV_TYPE, "netatmo")
                if primary_trv
                else None,
                "state": room_state.value,
                "current_temp": current_temp,
                # 2026-09 audit fix (frontend dead-code sweep): "heating_power"
                # used to be sent here too, but it's always exactly equal to
                # valve_position for Netatmo rooms (that's where it comes
                # from, see above) and stale/unset for Zigbee rooms once
                # pi_demand_entity overrides valve_position — no reader in
                # either frontend file ever used it separately. Dropped as a
                # redundant duplicate of valve_position; the raw
                # heating_power_request value is still read locally above,
                # just no longer echoed to the frontend under its own key.
                "valve_position": valve_position,  # B1
                "boost_active": boost_active,  # B2
                "windows_open": windows_open,
                "battery_level": battery_level,  # % — Rum-detaljer/oversigt
                "humidity": humidity,  # % — only set when humidity_sensor is configured
                "co2": co2,  # ppm — only set when co2_sensor is configured
                "mold_risk": mold_risk,  # 2026-09-07 audit fix (5.3)
                "pid_power": pid_power,  # 2026-09 frontend-parity fix
                "calibration_offset": calibration_offset,  # 2026-09 frontend-parity fix
                "window_duration_today": window_duration_today,  # 2026-09 frontend-parity fix
                "unavailable_entities": unavailable_entities,  # 2026-09 audit fix (UI/UX #8)
                # v0.14.0: which caller ("switch"/"remote") currently holds
                # this room in OVERRIDE, if any — None otherwise. Purely for
                # the frontend badge (see coordinator.room_override_source).
                "override_source": coordinator.room_override_source.get(name),
                # v0.9.0: self-reporting diagnostics — why this room's
                # heating commands are currently held back, if at all.
                "blocking_sources": coordinator.get_room_blocking_sources(name),
                # v0.9.0: optional per-room engines — raw config values only,
                # the panel/card own the display labels (config-flow wizard
                # remains the way to configure these).
                "calibration_entity": coordinator.get_room_calibration_entity(name),
                "sync_mode": room.get(CONF_SYNC_MODE) or None,
                "schedule_entity": room.get(CONF_SCHEDULE_ENTITY) or None,
                # B18 Fase 3: per-room replacement for the old single global
                # "group_offset" below — not yet consumed by panel.js/
                # card.js (Fase 4), forward-compatible additions only.
                "trv_count": len(coordinator.get_all_room_trvs(name)),
                "offset": coordinator.room_offsets.get(name, 0.0),
                "group_enabled": coordinator.room_group_enabled.get(name, True),
                # Fase 2 (2026-09-11) — see comment block above where these
                # are read. target_temp is Heat Manager's own resolved
                # target (get_room_target_temp() — same value the PID
                # chases); the cloud_* fields are Netatmo's own raw
                # attributes, only populated for rooms with a Netatmo cloud
                # climate entity (None for Zigbee/local rooms).
                "target_temp": target_temp,
                "cloud_temperature": cloud_temperature,
                "cloud_hvac_action": cloud_hvac_action,
                "cloud_preset_mode": cloud_preset_mode,
                "cloud_preset_modes": cloud_preset_modes,
                "cloud_selected_schedule": cloud_selected_schedule,
                "cloud_hvac_modes": cloud_hvac_modes,
                "cloud_min_temp": cloud_min_temp,
                "cloud_max_temp": cloud_max_temp,
                "cloud_target_temp_step": cloud_target_temp_step,
                # 2026-09-11 door feature (level A visibility + level B
                # learning) — door_open is read live via coordinator, never
                # cached, so it can't drift from the actual sensor state.
                # The two heatup_rate_* fields are None until CalibrationEngine
                # has observed enough genuine heating to learn a rate — see
                # engine/calibration_engine.py's "Heat-up-rate learning".
                "door_open": coordinator.is_room_door_open(name),
                "heatup_rate_door_open": coordinator.calibration_engine.get_room_heatup_rate(
                    name, True
                ),
                "heatup_rate_door_closed": coordinator.calibration_engine.get_room_heatup_rate(
                    name, False
                ),
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

    # ── Interior doors (2026-09-11) ──────────────────────────────────────────
    doors = []
    for door in coordinator.doors:
        sensor_id = door.get(CONF_DOOR_SENSOR, "")
        room_a = door.get(CONF_DOOR_ROOM_A, "")
        room_b = door.get(CONF_DOOR_ROOM_B, "")
        ds = hass.states.get(sensor_id) if sensor_id else None
        doors.append(
            {
                "sensor": sensor_id,
                "room_a": room_a,
                "room_b": room_b,
                "is_open": bool(ds and ds.state == "on"),
                "available": ds is not None
                and ds.state not in ("unknown", "unavailable"),
            }
        )

    # ── Outdoor temperature ───────────────────────────────────────────────────
    outdoor_temp: float | None = coordinator.outdoor_temperature

    # ── Config snapshot ────────────────────────────────────────────────────────
    config_snap = {
        "weather_entity": cfg.get(CONF_WEATHER_ENTITY, ""),
        # 2026-09 audit fix (frontend dead-field sweep): the panel's config
        # tab has always shown an "Outdoor temp sensor" row, but this key
        # was never in the payload — CONF_OUTDOOR_TEMP_SENSOR is a real,
        # functional setting (coordinator.py prefers it over the weather
        # entity for outdoor temperature), it just never reached the
        # display. Wired up rather than removing the row, since the
        # underlying setting is genuinely in use.
        "outdoor_temp_sensor": cfg.get(CONF_OUTDOOR_TEMP_SENSOR, ""),
        "grace_day_min": cfg.get(CONF_GRACE_DAY_MIN),
        "grace_night_min": cfg.get(CONF_GRACE_NIGHT_MIN),
        "auto_off_temp_threshold": cfg.get(CONF_AUTO_OFF_TEMP_THRESHOLD),
        "auto_off_temp_days": cfg.get(CONF_AUTO_OFF_TEMP_DAYS),
        "alarm_panel": cfg.get(CONF_ALARM_PANEL, ""),
        "notify_service": cfg.get(CONF_NOTIFY_SERVICE, ""),
        "house_voice_enabled": cfg.get(CONF_HOUSE_VOICE_ENABLED, False),
        # 2026-09-13: was session-scoped only (plain JS field, reset on every
        # page reload) — now read from entry.options so the panel can
        # initialize the toggle to its actual persisted state on load.
        "manual_trv_control": cfg.get(CONF_MANUAL_TRV_CONTROL, False),
        # Fase 2, del 1 (2026-09-13) — panel "Indstillinger" tab: current
        # values for every field ws_update_config() now accepts, so the tab
        # can render live-editable fields pre-filled with the actual current
        # config instead of only the read-only summary above.
        "pid_enabled": cfg.get(CONF_PID_ENABLED, True),
        "pid_kp": cfg.get(CONF_PID_KP, DEFAULT_PID_KP),
        "pid_ki": cfg.get(CONF_PID_KI, DEFAULT_PID_KI),
        "pid_kd": cfg.get(CONF_PID_KD, DEFAULT_PID_KD),
        "boost_default_temp": cfg.get(CONF_BOOST_DEFAULT_TEMP, DEFAULT_BOOST_TEMP),
        "boost_default_minutes": cfg.get(
            CONF_BOOST_DEFAULT_MINUTES, DEFAULT_BOOST_MINUTES
        ),
        "window_warning_min": cfg.get(
            CONF_WINDOW_WARNING_MIN, DEFAULT_WINDOW_WARNING_MIN
        ),
        "notify_windows": cfg.get(CONF_NOTIFY_WINDOWS, True),
        "notify_window_warning_30": cfg.get(CONF_NOTIFY_WINDOW_WARNING_30, True),
        "night_setback_enabled": cfg.get(
            CONF_NIGHT_SETBACK_ENABLED, DEFAULT_NIGHT_SETBACK_ENABLED
        ),
        "night_setback_temp": cfg.get(
            CONF_NIGHT_SETBACK_TEMP, DEFAULT_NIGHT_SETBACK_TEMP
        ),
        "night_start_hour": cfg.get(CONF_NIGHT_START_HOUR, DEFAULT_NIGHT_START_HOUR),
        "night_end_hour": cfg.get(CONF_NIGHT_END_HOUR, DEFAULT_NIGHT_END_HOUR),
        "notify_presence": cfg.get(CONF_NOTIFY_PRESENCE, True),
        "notify_preheat": cfg.get(CONF_NOTIFY_PREHEAT, True),
        "notify_mold_risk": cfg.get(CONF_NOTIFY_MOLD_RISK, True),
    }

    payload: dict[str, Any] = {
        "version": integration_version,
        "controller_state": ctrl.state.value,
        "auto_off_reason": ctrl.auto_off_reason.value,
        "pause_remaining": ctrl.pause_remaining_minutes,
        "season_mode": coordinator.season_mode.value,
        "effective_season": coordinator.effective_season.value,
        "outdoor_temp": outdoor_temp,
        "rooms": rooms,
        "persons": persons,
        "doors": doors,
        # 2026-09 audit fix: window_engine already tracks this — it just
        # was never surfaced to the panel/card, so an open window's
        # heat-reduction effect had no visible confirmation in the UI.
        "open_windows": coordinator.window_engine.get_open_windows(),
        "boost_remaining_minutes": coordinator.boost_remaining_minutes,
        "calendar_season": coordinator.calendar_season.value,
        "auto_off_days": coordinator.days_above_threshold,
        "auto_off_days_required": cfg.get(CONF_AUTO_OFF_TEMP_DAYS, 5),
        "auto_off_threshold": cfg.get(CONF_AUTO_OFF_TEMP_THRESHOLD, 18.0),
        "config": config_snap,
        # B18 Fase 3: the old global "group_offset" (v0.9.0) is gone —
        # replaced by each room's own "offset"/"group_enabled" above. The
        # existing panel.js/card.js read this via `?? 0` and degrade to an
        # inert 0/no-op slider until Fase 4 wires up the per-room controls.
        "blocking_sources": coordinator.global_blocking_sources(),
        # 2026-09-07 audit fix (5.4, 5.8): these were already computed by the
        # coordinator/engines but never reached the panel/card payload at
        # all — the only way to see them was the raw HA entity/attribute.
        "remote_last_action": coordinator.remote_last_action,
        "wind_speed": coordinator.get_wind_speed(),
        "precipitation": coordinator.get_precipitation(),
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
}

# value = (python type to cast the raw WS value to, DEFAULT_* fallback)
_NUMERIC_CONFIG_FIELDS: dict[str, tuple[type, float | int]] = {
    CONF_PID_KP: (float, DEFAULT_PID_KP),
    CONF_PID_KI: (float, DEFAULT_PID_KI),
    CONF_PID_KD: (float, DEFAULT_PID_KD),
    CONF_BOOST_DEFAULT_TEMP: (float, DEFAULT_BOOST_TEMP),
    CONF_BOOST_DEFAULT_MINUTES: (float, DEFAULT_BOOST_MINUTES),
    CONF_WINDOW_WARNING_MIN: (int, DEFAULT_WINDOW_WARNING_MIN),
    CONF_NIGHT_SETBACK_TEMP: (float, DEFAULT_NIGHT_SETBACK_TEMP),
    CONF_NIGHT_START_HOUR: (int, DEFAULT_NIGHT_START_HOUR),
    CONF_NIGHT_END_HOUR: (int, DEFAULT_NIGHT_END_HOUR),
    CONF_GRACE_DAY_MIN: (int, DEFAULT_GRACE_DAY_MIN),
    CONF_GRACE_NIGHT_MIN: (int, DEFAULT_GRACE_NIGHT_MIN),
    CONF_AUTO_OFF_TEMP_THRESHOLD: (float, DEFAULT_AUTO_OFF_TEMP_THRESHOLD),
    CONF_AUTO_OFF_TEMP_DAYS: (int, DEFAULT_AUTO_OFF_TEMP_DAYS),
}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heat_manager/update_config",
        vol.Optional(CONF_ALARM_PANEL): vol.Any(str, None),
        vol.Optional(CONF_NOTIFY_SERVICE): vol.Any(str, None),
        vol.Optional(CONF_MANUAL_TRV_CONTROL): bool,
        vol.Optional(CONF_PID_ENABLED): bool,
        vol.Optional(CONF_NOTIFY_WINDOWS): bool,
        vol.Optional(CONF_NOTIFY_WINDOW_WARNING_30): bool,
        vol.Optional(CONF_NIGHT_SETBACK_ENABLED): bool,
        vol.Optional(CONF_NOTIFY_PRESENCE): bool,
        vol.Optional(CONF_NOTIFY_PREHEAT): bool,
        vol.Optional(CONF_NOTIFY_MOLD_RISK): bool,
        vol.Optional(CONF_PID_KP): vol.Any(float, int),
        vol.Optional(CONF_PID_KI): vol.Any(float, int),
        vol.Optional(CONF_PID_KD): vol.Any(float, int),
        vol.Optional(CONF_BOOST_DEFAULT_TEMP): vol.Any(float, int),
        vol.Optional(CONF_BOOST_DEFAULT_MINUTES): vol.Any(float, int),
        vol.Optional(CONF_WINDOW_WARNING_MIN): vol.Any(float, int),
        vol.Optional(CONF_NIGHT_SETBACK_TEMP): vol.Any(float, int),
        vol.Optional(CONF_NIGHT_START_HOUR): vol.Any(float, int),
        vol.Optional(CONF_NIGHT_END_HOUR): vol.Any(float, int),
        vol.Optional(CONF_GRACE_DAY_MIN): vol.Any(float, int),
        vol.Optional(CONF_GRACE_NIGHT_MIN): vol.Any(float, int),
        vol.Optional(CONF_AUTO_OFF_TEMP_THRESHOLD): vol.Any(float, int),
        vol.Optional(CONF_AUTO_OFF_TEMP_DAYS): vol.Any(float, int),
    }
)
@websocket_api.async_response
async def ws_update_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
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

    for key, (cast, default) in _NUMERIC_CONFIG_FIELDS.items():
        if key in msg:
            try:
                new_num = cast(msg[key])
            except (TypeError, ValueError):
                connection.send_error(
                    msg["id"], "invalid_value", f"Invalid value for {key}"
                )
                return
            if current_options.get(key, default) != new_num:
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
