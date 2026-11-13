"""Heat Manager — payload builders for the panel and card.

build_state_payload() assembles the heat_manager/get_state snapshot and
build_active_issues() the status line's issue list. Split out of
websocket.py in v0.68.9 (T3i) so the WebSocket handlers stay thin; this
module only reads state and never registers commands.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.dt import utcnow

from .const import (
    CONF_ALARM_AWAY_STATES,
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_BATTERY_SENSOR,
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    CONF_CLIMATE_ENTITY,
    CONF_CO2_SENSOR,
    CONF_COMFORT_TEMP,
    CONF_DOOR_HEAT_SHARE_ENABLED,
    CONF_DOOR_HEAT_SHARE_MAX_REDUCTION,
    CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
    CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF,
    CONF_DOOR_HEAT_SHARE_WEIGHT,
    CONF_DOOR_ROOM_A,
    CONF_DOOR_ROOM_B,
    CONF_DOOR_SENSOR,
    CONF_FF_MAX_CONTRIBUTION,
    CONF_FF_REFERENCE_OUTDOOR_TEMP,
    CONF_FF_WEIGHT,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_HOUSE_VOICE_ENABLED,
    CONF_HUMIDITY_SENSOR,
    CONF_ISSUE_ESCALATION_MINUTES,
    CONF_LUX_SENSOR,
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
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PI_DEMAND_ENTITY,
    CONF_PID_ENABLED,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_PID_SETPOINT_MARGIN,
    CONF_SCHEDULE_ENTITY,
    CONF_SOLAR_GAIN_ENABLED,
    CONF_SOLAR_GAIN_LUX_THRESHOLD,
    CONF_SOLAR_GAIN_MAX_REDUCTION,
    CONF_SOLAR_GAIN_WEIGHT,
    CONF_SYNC_MODE,
    CONF_TRV_TYPE,
    CONF_WEATHER_COMPENSATION_ENABLED,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_DELAY_DEFAULT_MIN,
    CONF_WINDOW_OFF_TEMP,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_WARNING_MIN,
    DEFAULT_ALARM_AWAY_STATES,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMP,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_DOOR_HEAT_SHARE_ENABLED,
    DEFAULT_ISSUE_ESCALATION_MINUTES,
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
    PID_SETPOINT_MARGIN,
    SOLAR_GAIN_LUX_THRESHOLD,
    SOLAR_GAIN_MAX_REDUCTION,
    SOLAR_GAIN_WEIGHT,
    RoomState,
)
from .engine.mold import is_mold_risk
from .engine.readings import seconds_since_report

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


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


# ── Status center (v0.32.0) ───────────────────────────────────────────────────
# Consolidates what used to be three independently-computed, client-side-only
# indicators — heat-manager-panel.js's #cloud-chip/#health-chip/#ws-error-chip,
# each re-deriving its own "is something wrong" heuristic straight from
# hass.states (see CHANGELOG [0.21.0]) — plus the separate Oversigt-only
# remote-last-action strip (CHANGELOG [0.17.0]-era), into one server-computed,
# ordered list. The panel's header status field renders this directly instead
# of duplicating any of these heuristics itself. One thing deliberately stays
# client-side: a dead websocket connection can't be reported *by* the server
# whose connection is dead — the panel still injects its own "Ingen
# forbindelse" entry into the same list locally when polling fails.
def build_active_issues(
    coordinator: Any, rooms: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Return every currently-active status/warning/error as
    {"severity": "critical"|"warning"|"info", "icon": str, "message": str},
    ordered critical -> warning -> info (stable within each severity)."""
    hass = coordinator.hass
    issues: list[dict[str, Any]] = []

    # 1. Netatmo/cloud TRV connectivity — mirrors binary_sensor.py's
    # CloudAvailableSensor algorithm (kept independent rather than importing
    # the binary_sensor platform module from here). A
    # room's HomeKit-local twin is excluded — that one being briefly
    # unavailable isn't a cloud/gateway problem.
    unavailable_rooms: list[str] = []
    stale_rooms: list[str] = []
    total = 0
    for room in coordinator.rooms:
        room_name = room.get("room_name", "")
        climate_id = coordinator.get_climate_entity(room_name) or ""
        hk_id = coordinator.get_homekit_climate_entity(room_name) or ""
        if not climate_id or climate_id == hk_id:
            continue
        total += 1
        state = hass.states.get(climate_id)
        if state is None or state.state in ("unavailable", "unknown"):
            unavailable_rooms.append(room_name)
            continue
        # v0.69.1: newest of last_updated/last_reported — see
        # engine/readings.seconds_since_report() for why.
        age = seconds_since_report(
            utcnow(), state.last_updated, getattr(state, "last_reported", None)
        )
        if age is not None and age >= 600:
            stale_rooms.append(room_name)

    # v0.62.0: valve health from the Netatmo integration's own sensors. A
    # room whose valve is reported offline gets that precise cause below
    # instead of the generic "Netatmo utilgængelig" line.
    health = coordinator.get_netatmo_health()
    offline_rooms: list[str] = list(health.get("offline_rooms", []))
    if offline_rooms and len(unavailable_rooms) < total:
        unavailable_rooms = [r for r in unavailable_rooms if r not in offline_rooms]

    if total and unavailable_rooms and len(unavailable_rooms) == total:
        issues.append(
            {
                "id": "cloud_down",
                "severity": "critical",
                "icon": "☁️",
                "message": "Netatmo cloud/gateway nede — alle rum utilgængelige",
            }
        )
    elif unavailable_rooms:
        issues.append(
            {
                "id": _issue_id("cloud_unavailable", unavailable_rooms),
                "severity": "warning",
                "icon": "☁️",
                "message": f"Netatmo utilgængelig: {', '.join(unavailable_rooms)}",
            }
        )
    elif stale_rooms:
        issues.append(
            {
                "id": _issue_id("cloud_stale", stale_rooms),
                "severity": "warning",
                "icon": "☁️",
                "message": f"Netatmo-data ikke opdateret i 10+ min: {', '.join(stale_rooms)}",
            }
        )

    if offline_rooms:
        issues.append(
            {
                "id": _issue_id("valve_offline", offline_rooms),
                "severity": "warning",
                "icon": "📡",
                "message": f"Ventil offline: {', '.join(offline_rooms)}",
            }
        )
    low_battery_rooms: list[str] = list(health.get("low_battery_rooms", []))
    if low_battery_rooms:
        issues.append(
            {
                "id": _issue_id("battery_low", low_battery_rooms),
                "severity": "warning",
                "icon": "🪫",
                "message": f"Lavt batteri: {', '.join(low_battery_rooms)}",
            }
        )
    if health.get("webhook_down"):
        issues.append(
            {
                "id": "webhook_down",
                "severity": "info",
                "icon": "⏱️",
                "message": "Netatmo-realtid (webhook) nede — opdateres hvert minut",
            }
        )

    # 2. Other unavailable entities per room (window/humidity/CO2/battery/
    # secondary TRVs) — reuses each room's own "unavailable_entities" already
    # computed above in this same payload, just filtered to non-climate.
    # 2026-09-14 (punkt 3, dedup): collapsed into ONE grouped line once more
    # than one room is affected, instead of one separate line per room — "5
    # rum har utilgængelige sensorer" reads far better than 5 near-identical
    # lines drowning out the rest of the status center.
    unavailable_entity_rooms: list[tuple[str, int]] = []
    for room in rooms:
        others = [
            e
            for e in room.get("unavailable_entities", [])
            if not e.startswith("climate.")
        ]
        if others:
            unavailable_entity_rooms.append((room["name"], len(others)))
    if len(unavailable_entity_rooms) == 1:
        room_name, count = unavailable_entity_rooms[0]
        issues.append(
            {
                "id": _issue_id("entities_unavailable", [room_name]),
                "severity": "warning",
                "icon": "⚠️",
                "message": f"{room_name}: {count} sensor(er)/enhed(er) utilgængelig(e)",
            }
        )
    elif unavailable_entity_rooms:
        total_entities = sum(c for _, c in unavailable_entity_rooms)
        names = ", ".join(n for n, _ in unavailable_entity_rooms)
        issues.append(
            {
                "id": _issue_id(
                    "entities_unavailable", [n for n, _ in unavailable_entity_rooms]
                ),
                "severity": "warning",
                "icon": "⚠️",
                "message": f"{len(unavailable_entity_rooms)} rum har utilgængelige"
                f" sensorer/enheder ({total_entities} i alt): {names}",
            }
        )

    # 3. Mold risk (already computed per room above) — grouped, see punkt 3
    # above: one line total once more than one room is at risk.
    mold_rooms = [room["name"] for room in rooms if room.get("mold_risk")]
    if len(mold_rooms) == 1:
        issues.append(
            {
                "id": _issue_id("mold_risk", mold_rooms),
                "severity": "warning",
                "icon": "💧",
                "message": f"Skimmelrisiko — {mold_rooms[0]}",
            }
        )
    elif mold_rooms:
        issues.append(
            {
                "id": _issue_id("mold_risk", mold_rooms),
                "severity": "warning",
                "icon": "💧",
                "message": f"Skimmelrisiko ({len(mold_rooms)} rum): {', '.join(mold_rooms)}",
            }
        )

    # 4. Windows currently open (already computed per room above) — grouped.
    window_rooms = [room["name"] for room in rooms if room.get("windows_open")]
    if len(window_rooms) == 1:
        issues.append(
            {
                "id": _issue_id("window_open", window_rooms),
                "severity": "warning",
                "icon": "🪟",
                "message": f"Vindue åbent — {window_rooms[0]}",
            }
        )
    elif window_rooms:
        issues.append(
            {
                "id": _issue_id("window_open", window_rooms),
                "severity": "warning",
                "icon": "🪟",
                "message": f"Vindue åbent ({len(window_rooms)} rum): {', '.join(window_rooms)}",
            }
        )

    # 4b. Heat-up-rate anomaly (2026-09-13, architecture review #3) — a room
    # heating markedly slower than its OWN learned baseline for several
    # samples in a row. See CalibrationEngine.get_room_heatup_anomaly().
    # Grouped the same way as 3/4 above.
    anomaly_rooms = [
        room.get("room_name", "")
        for room in coordinator.rooms
        if room.get("room_name")
        and coordinator.calibration_engine.get_room_heatup_anomaly(
            room.get("room_name", "")
        )
    ]
    if len(anomaly_rooms) == 1:
        issues.append(
            {
                "id": _issue_id("heatup_anomaly", anomaly_rooms),
                "severity": "warning",
                "icon": "🐌",
                "message": f"{anomaly_rooms[0]}: varmer langsommere end normalt — muligvis"
                " fastsiddende ventil",
            }
        )
    elif anomaly_rooms:
        issues.append(
            {
                "id": _issue_id("heatup_anomaly", anomaly_rooms),
                "severity": "warning",
                "icon": "🐌",
                "message": f"{len(anomaly_rooms)} rum varmer langsommere end normalt —"
                f" muligvis fastsiddende ventil: {', '.join(anomaly_rooms)}",
            }
        )

    # 5. Boost active (info — not a problem, just currently-notable state)
    remaining = coordinator.boost_remaining_minutes
    if remaining and remaining > 0:
        active_rooms = sorted(
            name for name, active in coordinator.boost_active_rooms.items() if active
        )
        rooms_str = f" ({', '.join(active_rooms)})" if active_rooms else ""
        issues.append(
            {
                "id": "boost",
                "severity": "info",
                "icon": "🔥",
                "message": f"Boost aktivt{rooms_str} — {remaining} min tilbage",
            }
        )

    # 5b. v0.61.2: PID enabled but a room's Netatmo valves have no HomeKit
    # entity — the room follows the Netatmo schedule instead of the PID.
    pid_hk_rooms = coordinator.get_rooms_pid_needs_homekit()
    if pid_hk_rooms:
        issues.append(
            {
                "id": _issue_id("pid_needs_homekit", pid_hk_rooms),
                "severity": "info",
                "icon": "🏠",
                "message": "PID kræver HomeKit — følger Netatmo-tidsplanen:"
                f" {', '.join(pid_hk_rooms)}",
            }
        )

    # 6. Remote last action (info, < 30 min old) — folds the removed
    # Oversigt-only #remote-last-action-box into the header so it's visible
    # from every tab, not just Oversigt (same 30-min freshness window the
    # old box used).
    rla = coordinator.remote_last_action
    if rla and rla.get("timestamp"):
        age_min: float | None = None
        with contextlib.suppress(TypeError, ValueError):
            age_min = (
                utcnow() - datetime.fromisoformat(rla["timestamp"])
            ).total_seconds() / 60
        if age_min is not None and 0 <= age_min < 30:
            description = rla.get("description", "")
            # B26: RemoteButtonEngine's own descriptions already list the
            # rooms ("... — Stue → 21.5°C, Køkken → 21.5°C"); appending them
            # again doubled every room name in the header. Only append the
            # room list when the description doesn't already name them.
            rla_room_names = [
                r for r in (rla.get("rooms") or []) if r not in description
            ]
            rla_rooms = ", ".join(rla_room_names)
            issues.append(
                {
                    "id": "remote_action",
                    "severity": "info",
                    "icon": "📡",
                    "message": f"Fjernbetjening: {description}"
                    + (f" — {rla_rooms}" if rla_rooms else ""),
                }
            )

    # v0.60.0: snoozed issues stay in the list (the panel shows them dimmed
    # in its expanded view) but are flagged, so the status line and the
    # status sensor skip them. Critical issues can never be snoozed.
    for issue in issues:
        until = coordinator.get_issue_snoozed_until(issue.get("id", ""))
        snoozed = until is not None and issue["severity"] != "critical"
        issue["snoozed"] = snoozed
        issue["snoozed_until"] = until.isoformat() if snoozed and until else None

    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i["severity"], 3))
    return issues


def _issue_id(category: str, rooms: list[str]) -> str:
    """Stable id for an active issue (v0.60.0): category + the rooms it
    covers. Including the rooms means a snoozed "window open — Bad" comes
    straight back if another room's window opens too."""
    return f"{category}:{','.join(sorted(rooms))}"


def _netatmo_away_temp(hass: HomeAssistant, coordinator: Any) -> dict[str, Any] | None:
    """v0.67.0: NET-TRV's away temperature number as panel data — entity_id,
    current value, bounds and the Netatmo schedule it belongs to (the value
    is stored per schedule). None when there is no such entity."""
    entity_id = coordinator.get_netatmo_away_temp_entity()
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    attrs = state.attributes if state else {}
    value: float | None = None
    if state and state.state not in ("unknown", "unavailable"):
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            value = None
    return {
        "entity_id": entity_id,
        "value": value,
        "min": attrs.get("min"),
        "max": attrs.get("max"),
        "step": attrs.get("step"),
        "schedule": attrs.get("schedule"),
    }


def _iso_or_none(value: datetime | None) -> str | None:
    """ISO 8601 string for an optional datetime (WS payloads are JSON)."""
    return value.isoformat() if value is not None else None


def _fmt_time(dt: datetime) -> str:
    # S-7 FIX: neutral date format — panel JS handles locale-specific labels
    from homeassistant.util.dt import now as ha_now

    local_now = ha_now()
    local_dt = dt.astimezone(local_now.tzinfo)
    if local_dt.date() == local_now.date():
        return local_dt.strftime("%H:%M")
    return local_dt.strftime("%d/%m %H:%M")


def build_state_payload(
    hass: HomeAssistant, entry: Any, integration_version: str
) -> dict[str, Any]:
    """Build the heat_manager/get_state snapshot for the panel and card."""
    coordinator = entry.runtime_data
    ctrl = coordinator.controller
    cfg = coordinator.config

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
        primary_trv: dict[str, Any] = next(
            iter(coordinator.get_all_room_trvs(name)), {}
        )
        climate_id = primary_trv.get(CONF_CLIMATE_ENTITY, "")
        sensors = room.get(CONF_WINDOW_SENSORS, [])
        room_state = coordinator.get_room_state(name)

        current_temp: float | None = coordinator.get_room_current_temp(name, climate_id)
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
        # v0.65.3: who controls the room right now in Netatmo's own terms
        # (NET-TRV attributes; absent with core netatmo) — "schedule",
        # "home", "manual", "max", "away", "hg", "off" — and when a manual
        # setpoint expires. Display only.
        cloud_setpoint_mode: str | None = None
        cloud_setpoint_end_time: str | None = None
        cloud_hvac_modes: list[str] | None = None
        cloud_min_temp: float | None = None
        cloud_max_temp: float | None = None
        cloud_target_temp_step: float | None = None

        if climate_id:
            cs = hass.states.get(climate_id)
            if cs:
                # 2026-09-14 fix: valve_position used to be set straight
                # from Netatmo's own self-reported heating_power_request
                # here. That value can lag several minutes behind what Heat
                # Manager has actually just commanded (cloud/valve lag) — a
                # room already back at target could still show 70-100%
                # "demand" from Netatmo's side, looking like a stuck PID
                # when the PID itself had already dropped to 0.
                # valve_position for Netatmo rooms is now set from Heat
                # Manager's own pid_power further down instead. 2026-10-30:
                # the raw value was still read into an unused local
                # (ruff F841) — no longer read at all.
                cloud_temperature = _coerce_float(cs.attributes.get("temperature"))
                cloud_hvac_action = cs.attributes.get("hvac_action")
                cloud_preset_mode = cs.attributes.get("preset_mode")
                cloud_preset_modes = cs.attributes.get("preset_modes")
                cloud_selected_schedule = cs.attributes.get("selected_schedule")
                cloud_setpoint_mode = cs.attributes.get("netatmo_setpoint_mode")
                cloud_setpoint_end_time = cs.attributes.get("setpoint_end_time")
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

        # v0.64.0: includes opt-in Netatmo open-window detection
        windows_open = any(
            coordinator.is_window_source_open(sid)
            for sid in coordinator.get_room_window_sources(room)
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

        # Lux/illuminance (2026-09-14, punkt 7 — solar gain) — same optional
        # per-room pattern as humidity/co2 above. Purely a diagnostic read
        # here (the actual PID power reduction is computed independently in
        # engine/pid_adjustments.solar_gain_reduction() during the PID tick); shown so
        # the panel/card can display what the room is currently reading,
        # not just whether solar gain is configured.
        lux: float | None = None
        lux_entity = room.get(CONF_LUX_SENSOR) or None
        if lux_entity:
            lxs = hass.states.get(lux_entity)
            if lxs and lxs.state not in ("unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    lux = float(lxs.state)

        # 2026-09-07 audit fix (5.3): MoldRiskSensor (binary_sensor.py)
        # computes this per room but it was never surfaced in either
        # frontend — a real, quietly-computed safety signal invisible to
        # the user. Recomputed here from the same humidity/current_temp
        # values already fetched above (rather than looking up the sensor
        # entity by its generated entity_id), with the shared
        # engine/mold.py algorithm.
        mold_risk = (
            humidity is not None
            and current_temp is not None
            and is_mold_risk(current_temp, humidity)
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
        # v0.66.0: a room without a valve ("Kun sensorer") has nothing for the
        # PID to drive — don't report a meaningless "PID 0%" for it.
        pid = coordinator.get_pid(name) if climate_id else None
        if pid is not None:
            # v0.69.1: the power the setpoint was computed from (PID plus
            # weather compensation minus solar/door reductions), not the
            # PID-only term — see PidController.applied_output.
            raw_pid = getattr(pid, "applied_output", None)
            if not isinstance(raw_pid, (int, float)):
                raw_pid = getattr(pid, "_last_output", None)
            if raw_pid is not None:
                pid_power = round(raw_pid * 100.0, 1)

        # 2026-09-14 fix: Netatmo rooms' valve_position now reflects Heat
        # Manager's own commanded power (pid_power) rather than Netatmo's
        # self-reported heating_power_request — see the comment above where
        # heating_power is read for why. Only applies to Netatmo/HomeKit-
        # split rooms; a Zigbee room's pi_demand_entity override above (an
        # actual physical valve-position sensor) is untouched by this and
        # still takes precedence when configured, since Zigbee rooms have
        # no HomeKit entity and this condition is False for them.
        if coordinator.get_homekit_climate_entity(name) and pid_power is not None:
            valve_position = pid_power

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

        # 2026-09-14 (punkt 4) — per-room health score: combines signals that
        # already exist individually (battery, mold risk, unavailable
        # entities, heat-up-rate anomaly) into one weighted 0-100 indicator,
        # instead of the user mentally combining several separate badges
        # themselves. Weights are deliberately simple/additive, not a real
        # statistical model — easy to reason about and to retune later.
        # Moved here (after unavailable_entities is populated, 2026-09-14
        # hotfix) — an earlier revision referenced it before this point,
        # which raised NameError and took down ws_get_state() entirely (see
        # CHANGELOG [0.41.1]).
        heatup_anomaly = (
            bool(coordinator.calibration_engine.get_room_heatup_anomaly(name))
            if name
            else False
        )
        _health_penalty = 0
        if battery_level is not None:
            if battery_level < 20:
                _health_penalty += 30
            elif battery_level < 40:
                _health_penalty += 10
        if mold_risk:
            _health_penalty += 25
        if unavailable_entities:
            _health_penalty += min(30, 10 * len(unavailable_entities))
        if heatup_anomaly:
            _health_penalty += 20
        health_score = max(0, 100 - _health_penalty)
        if health_score >= 80:
            health_label = "god"
        elif health_score >= 50:
            health_label = "ok"
        else:
            health_label = "dårlig"

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
                # v0.61.0: integration owning the room's Netatmo valves —
                # "net_trv" / "netatmo" / "mixed" / "none".
                "netatmo_backend": coordinator.get_room_netatmo_backend(name),
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
                "lux": lux,  # 2026-09-14 (punkt 7) — only set when lux_sensor is configured
                "mold_risk": mold_risk,  # 2026-09-07 audit fix (5.3)
                "pid_power": pid_power,  # 2026-09 frontend-parity fix
                "calibration_offset": calibration_offset,  # 2026-09 frontend-parity fix
                "window_duration_today": window_duration_today,  # 2026-09 frontend-parity fix
                "unavailable_entities": unavailable_entities,  # 2026-09 audit fix (UI/UX #8)
                # v0.14.0: which caller ("switch"/"remote") currently holds
                # this room in OVERRIDE, if any — None otherwise. Purely for
                # the frontend badge (see coordinator.room_override_source).
                "override_source": coordinator.room_override_source.get(name),
                # v0.59.0: when a manual override auto-restores to schedule
                # (None = no expiry) and when it started (None = unknown,
                # e.g. restored after a restart) — "manual until 20:42".
                "override_expires_at": _iso_or_none(
                    coordinator.room_override_expires_at.get(name)
                ),
                "override_since": _iso_or_none(
                    coordinator.room_override_since.get(name)
                ),
                # v0.9.0: self-reporting diagnostics — why this room's
                # heating commands are currently held back, if at all.
                "blocking_sources": coordinator.get_room_blocking_sources(name),
                # v0.9.0: optional per-room engines — raw config values only,
                # the panel/card own the display labels (config-flow wizard
                # remains the way to configure these).
                "calibration_entity": coordinator.get_room_calibration_entity(name),
                "sync_mode": room.get(CONF_SYNC_MODE) or None,
                "schedule_entity": room.get(CONF_SCHEDULE_ENTITY) or None,
                # Punkt 3 (2026-09-13): raw config values for the two fields
                # now inline-editable from the Rum-fane's room cards (see
                # ws_update_room_config below) — distinct from "target_temp"
                # above, which is the PID's fully-resolved live setpoint
                # (offsets/night-setback/away-mode already applied). These
                # are the plain config-flow values the edit fields need to
                # prefill with, same as sync_mode/schedule_entity above.
                "comfort_temp": room.get(CONF_COMFORT_TEMP, DEFAULT_COMFORT_TEMP),
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
                # 2026-09-16 ("hvad er hvad"-forvirring) — the setpoint PID
                # actually computed and wrote to the TRV(s) during its last
                # active cycle for this room (coordinator._async_pid_tick(),
                # after power->setpoint mapping AND the setpoint-margin cap
                # — see that method for the full chain). Distinct from
                # target_temp above: target_temp is what Heat Manager is
                # trying to reach; this is what it's actually telling the
                # valve to do right now, which can sit noticeably above
                # target_temp while the room is still far from it.
                # last_expected_setpoint is NEVER cleared once written (see
                # sync_engine.py's own reliance on that), so it would hold a
                # stale value indefinitely for a room that has left NORMAL
                # — gated on room_state here so the frontend only ever sees
                # a value while it's actually live/meaningful.
                "trv_setpoint": (
                    coordinator.last_expected_setpoint.get(name)
                    if room_state == RoomState.NORMAL
                    else None
                ),
                "cloud_temperature": cloud_temperature,
                "cloud_hvac_action": cloud_hvac_action,
                "cloud_preset_mode": cloud_preset_mode,
                "cloud_preset_modes": cloud_preset_modes,
                "cloud_selected_schedule": cloud_selected_schedule,
                "cloud_setpoint_mode": cloud_setpoint_mode,
                "cloud_setpoint_end_time": cloud_setpoint_end_time,
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
                # 2026-09-15 ("vindue vs dør") — heated-area doors (front
                # door onto a heated stairwell, etc.) are a SEPARATE concept
                # from the interior door_open above: no heat-suppression
                # meaning at all, visibility-only. has_heated_doors lets the
                # panel decide whether to show the row at all for this room.
                "has_heated_doors": bool(coordinator.get_room_heated_doors(name)),
                "heated_door_open": coordinator.is_room_heated_door_open(name),
                "heatup_rate_door_open": coordinator.calibration_engine.get_room_heatup_rate(
                    name, True
                ),
                "heatup_rate_door_closed": coordinator.calibration_engine.get_room_heatup_rate(
                    name, False
                ),
                # 2026-09-14 (punkt 4) — combined per-room health indicator,
                # see computation above.
                "health_score": health_score,
                "health_label": health_label,
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

    # ── Status center (v0.32.0) ───────────────────────────────────────────────
    active_issues = build_active_issues(coordinator, rooms)
    control_mode, manual_rooms = coordinator.get_control_mode()

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
        "alarm_away_states": list(
            cfg.get(CONF_ALARM_AWAY_STATES, DEFAULT_ALARM_AWAY_STATES)
        ),
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
        "pid_setpoint_margin": cfg.get(CONF_PID_SETPOINT_MARGIN, PID_SETPOINT_MARGIN),
        "boost_default_temp": cfg.get(CONF_BOOST_DEFAULT_TEMP, DEFAULT_BOOST_TEMP),
        "boost_default_minutes": cfg.get(
            CONF_BOOST_DEFAULT_MINUTES, DEFAULT_BOOST_MINUTES
        ),
        "window_warning_min": cfg.get(
            CONF_WINDOW_WARNING_MIN, DEFAULT_WINDOW_WARNING_MIN
        ),
        # v0.33.0 — the global knob every room's window open-delay actually
        # uses now (window_engine.py no longer reads the old per-room
        # CONF_WINDOW_DELAY_MIN), plus the dedicated window-open-off
        # temperature, split out from CONF_AWAY_TEMP_OVERRIDE. See const.py.
        "window_delay_default_min": cfg.get(
            CONF_WINDOW_DELAY_DEFAULT_MIN, DEFAULT_WINDOW_DELAY_DEFAULT_MIN
        ),
        "window_off_temp": cfg.get(CONF_WINDOW_OFF_TEMP, DEFAULT_WINDOW_OFF_TEMP),
        # v0.67.0: global lowest room temperature (PID + setback floor).
        "min_room_temp": cfg.get(CONF_MIN_ROOM_TEMP, DEFAULT_MIN_ROOM_TEMP),
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
        "notify_issue_escalation": cfg.get(CONF_NOTIFY_ISSUE_ESCALATION, True),
        "issue_escalation_minutes": cfg.get(
            CONF_ISSUE_ESCALATION_MINUTES, DEFAULT_ISSUE_ESCALATION_MINUTES
        ),
        "weather_compensation_enabled": cfg.get(
            CONF_WEATHER_COMPENSATION_ENABLED, DEFAULT_WEATHER_COMPENSATION_ENABLED
        ),
        "ff_reference_outdoor_temp": cfg.get(
            CONF_FF_REFERENCE_OUTDOOR_TEMP, FF_REFERENCE_OUTDOOR_TEMP
        ),
        "ff_weight": cfg.get(CONF_FF_WEIGHT, FF_WEIGHT),
        "ff_max_contribution": cfg.get(CONF_FF_MAX_CONTRIBUTION, FF_MAX_CONTRIBUTION),
        # 2026-09-14 (punkt 7) — solar gain, same panel-editable pattern as
        # weather compensation above.
        "solar_gain_enabled": cfg.get(
            CONF_SOLAR_GAIN_ENABLED, DEFAULT_SOLAR_GAIN_ENABLED
        ),
        "solar_gain_lux_threshold": cfg.get(
            CONF_SOLAR_GAIN_LUX_THRESHOLD, SOLAR_GAIN_LUX_THRESHOLD
        ),
        "solar_gain_weight": cfg.get(CONF_SOLAR_GAIN_WEIGHT, SOLAR_GAIN_WEIGHT),
        "solar_gain_max_reduction": cfg.get(
            CONF_SOLAR_GAIN_MAX_REDUCTION, SOLAR_GAIN_MAX_REDUCTION
        ),
        # 2026-09-16 (punkt 8) — door heat sharing, same panel-editable
        # pattern as solar gain above.
        "door_heat_share_enabled": cfg.get(
            CONF_DOOR_HEAT_SHARE_ENABLED, DEFAULT_DOOR_HEAT_SHARE_ENABLED
        ),
        "door_heat_share_min_neighbor_power": cfg.get(
            CONF_DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
            DOOR_HEAT_SHARE_MIN_NEIGHBOR_POWER,
        ),
        "door_heat_share_min_temp_diff": cfg.get(
            CONF_DOOR_HEAT_SHARE_MIN_TEMP_DIFF, DOOR_HEAT_SHARE_MIN_TEMP_DIFF
        ),
        "door_heat_share_weight": cfg.get(
            CONF_DOOR_HEAT_SHARE_WEIGHT, DOOR_HEAT_SHARE_WEIGHT
        ),
        "door_heat_share_max_reduction": cfg.get(
            CONF_DOOR_HEAT_SHARE_MAX_REDUCTION, DOOR_HEAT_SHARE_MAX_REDUCTION
        ),
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
        # v0.67.0: Netatmo's home-level away temperature (NET-TRV number on
        # the relay), editable from the panel. None with core netatmo.
        "netatmo_away_temp": _netatmo_away_temp(hass, coordinator),
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
        # v0.59.0: house-wide auto/manual/mixed — drives the panel's mode bar.
        "control_mode": control_mode,
        "manual_rooms": manual_rooms,
        "wind_speed": coordinator.get_wind_speed(),
        "precipitation": coordinator.get_precipitation(),
        "active_issues": active_issues,  # v0.32.0 — status center, see build_active_issues()
    }

    return payload
