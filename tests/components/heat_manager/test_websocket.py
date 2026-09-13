"""Tests for websocket.py — the WS command handlers the sidebar panel uses.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.

@websocket_api.async_response replaces each handler with a sync @callback
(`schedule_handler`) that fires the real coroutine via
hass.async_create_background_task and returns None immediately — calling
that wrapper directly would just schedule-and-return rather than run the
handler and let us await/assert on its effects. functools.wraps preserves
the original coroutine function on `__wrapped__`, so tests call that
directly to exercise the handler body itself, bypassing the background-task
scheduling and the wrapper's own exception handling (_handle_async_response)
which is HA framework code, not ours to test here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager import websocket
from custom_components.heat_manager.const import (
    CONF_AWAY_TEMP_OVERRIDE,
    CONF_COMFORT_TEMP,
    CONF_ROOMS,
    CONF_TRVS,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_PID_KP,
    AutoOffReason,
    ControllerState,
    EffectiveSeason,
    RoomState,
    SeasonMode,
)
from custom_components.heat_manager.migrations import migrate_room_to_trvs

# websocket_api.async_response wraps each handler in a sync scheduler that
# fires-and-forgets a background task; __wrapped__ is the real coroutine.
ws_get_state = websocket.ws_get_state.__wrapped__
ws_boost_start = websocket.ws_boost_start.__wrapped__
ws_boost_stop = websocket.ws_boost_stop.__wrapped__
ws_set_room_temp = websocket.ws_set_room_temp.__wrapped__
ws_update_config = websocket.ws_update_config.__wrapped__
ws_update_room_config = websocket.ws_update_room_config.__wrapped__
ws_get_history = websocket.ws_get_history.__wrapped__

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator(rooms=None, persons=None) -> MagicMock:
    coord = MagicMock()
    coord.rooms = rooms if rooms is not None else []
    coord.persons = persons if persons is not None else []
    coord.config = {}

    ctrl = MagicMock()
    ctrl.state = ControllerState.ON
    ctrl.auto_off_reason = AutoOffReason.NONE
    ctrl.pause_remaining_minutes = 0
    coord.controller = ctrl

    coord.season_mode = SeasonMode.AUTO
    coord.effective_season = EffectiveSeason.ACTIVE
    coord.calendar_season = SeasonMode.WINTER
    coord.outdoor_temperature = 5.0
    coord.energy_saved_today = 0.0
    coord.energy_wasted_today = 0.0
    coord.efficiency_score = 100
    coord.boost_remaining_minutes = 0
    coord.last_waste_time = None
    coord.last_saved_time = None
    coord.days_above_threshold = 0
    coord.room_offsets = {}
    coord.room_group_enabled = {}
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.get_room_current_temp = MagicMock(return_value=21.0)
    coord.get_room_blocking_sources = MagicMock(return_value=[])
    coord.global_blocking_sources = MagicMock(return_value=[])
    coord.boost_active_rooms = {}
    coord.log_event = MagicMock()

    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.services.async_call = AsyncMock()
    coord.hass = hass

    # B18: ws_set_room_temp() now fans out over get_room_trvs() /
    # get_room_write_entities() instead of the room-level get_write_entity()
    # / get_climate_entity(). Default to the flat-mirror migration the real
    # coordinator uses at read time, with no HomeKit entity configured (so
    # get_trv_write_entity falls back to the TRV's own climate_entity) —
    # matching the pre-existing single-TRV tests' fixed "climate.bathroom"
    # expectations exactly.
    def _room_trvs(room_name):
        room = next((r for r in coord.rooms if r.get("room_name") == room_name), None)
        if room is None:
            return []
        return migrate_room_to_trvs(room).get(CONF_TRVS, [])

    def _trv_write_entity(trv):
        return trv.get("homekit_climate_entity") or trv.get("climate_entity")

    def _room_write_entities(room_name):
        entities = [_trv_write_entity(trv) for trv in _room_trvs(room_name)]
        return [e for e in entities if e]

    coord.get_room_trvs = MagicMock(side_effect=_room_trvs)
    # B18 Fase 3: ws_get_state()'s per-room payload calls get_all_room_trvs()
    # (structural — ignores the group toggle) for "trv_count". Same
    # underlying data as get_room_trvs() for these fixtures (no test here
    # exercises the toggle narrowing the two apart).
    coord.get_all_room_trvs = MagicMock(side_effect=_room_trvs)
    coord.get_trv_write_entity = MagicMock(side_effect=_trv_write_entity)
    coord.get_room_write_entities = MagicMock(side_effect=_room_write_entities)

    # 2026-09 frontend-parity fix: ws_get_state() reads get_pid()/
    # calibration_engine directly for the pid_power/calibration_offset
    # fields. Default to "no PID yet" / "no calibration written yet" so
    # those fields resolve to None like every other unconfigured room
    # field, instead of a bare MagicMock leaking into the payload.
    coord.get_pid = MagicMock(return_value=None)
    calibration_engine = MagicMock()
    calibration_engine._last_written = {}
    coord.calibration_engine = calibration_engine

    # 2026-09 audit fix: ws_get_state() now resolves "calibration_entity"
    # via coordinator.get_room_calibration_entity() (TRV-aware) instead of
    # reading the room's flat field directly, and adds "open_windows" from
    # window_engine.get_open_windows() — default both so a bare MagicMock
    # doesn't leak into the payload, same rationale as get_pid() above.
    def _calibration_entity(name):
        room = next((r for r in coord.rooms if r.get("room_name") == name), None)
        return (room or {}).get("calibration_entity") or None

    coord.get_room_calibration_entity = MagicMock(side_effect=_calibration_entity)
    window_engine = MagicMock()
    window_engine.get_open_windows = MagicMock(return_value=[])
    coord.window_engine = window_engine

    # Fase 2 (2026-09-11): ws_get_state() now reads the room's resolved
    # target via coordinator.get_room_target_temp(room) instead of any
    # flat field — default to a plain float so payload["target_temp"]
    # behaves like real data in every existing test instead of leaking a
    # bare MagicMock. Tests that care about a specific value override this.
    coord.get_room_target_temp = MagicMock(return_value=21.0)

    return coord


def _make_hass_with_entry(coordinator) -> MagicMock:
    """hass whose config_entries.async_entries(DOMAIN) yields one loaded
    entry backed by `coordinator`, matching websocket._get_entry()'s lookup."""
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.options = {}

    hass = coordinator.hass
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_update_entry = MagicMock()
    return hass


def _make_hass_without_entry() -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


def _msg(**kwargs) -> dict:
    return {"id": 1, **kwargs}


def _connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _room(
    name="Bathroom",
    climate="climate.bathroom",
    trv_type="netatmo",
    calibration_entity=None,
    sync_mode=None,
    schedule_entity=None,
    window_sensors=None,
    pi_demand_entity=None,
    battery_sensor=None,
    humidity_sensor=None,
    co2_sensor=None,
) -> dict:
    room = {
        "room_name": name,
        "climate_entity": climate,
        "trv_type": trv_type,
    }
    if calibration_entity:
        room["calibration_entity"] = calibration_entity
    if sync_mode:
        room["sync_mode"] = sync_mode
    if schedule_entity:
        room["schedule_entity"] = schedule_entity
    if window_sensors:
        room["window_sensors"] = window_sensors
    if pi_demand_entity:
        room["pi_demand_entity"] = pi_demand_entity
    if battery_sensor:
        room["battery_sensor"] = battery_sensor
    if humidity_sensor:
        room["humidity_sensor"] = humidity_sensor
    if co2_sensor:
        room["co2_sensor"] = co2_sensor
    return room


# ── ws_get_state: entry lookup ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_state_no_entry_sends_not_found():
    hass = _make_hass_without_entry()
    conn = _connection()
    await ws_get_state(hass, conn, _msg())
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"
    conn.send_result.assert_not_called()


# ── ws_get_state: top-level payload shape ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_state_top_level_keys_present():
    coord = _make_coordinator(rooms=[_room()])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    conn.send_result.assert_called_once()
    payload = conn.send_result.call_args[0][1]
    for key in (
        "controller_state",
        "auto_off_reason",
        "pause_remaining",
        "season_mode",
        "effective_season",
        "outdoor_temp",
        "rooms",
        "persons",
        "energy_saved_today",
        "energy_wasted_today",
        "efficiency_score",
        "boost_remaining_minutes",
        "config",
        "blocking_sources",
    ):
        assert key in payload, f"missing key: {key}"
    assert payload["controller_state"] == "on"
    room_payload = payload["rooms"][0]
    for key in ("trv_count", "offset", "group_enabled"):
        assert key in room_payload, f"missing per-room key: {key}"


@pytest.mark.asyncio
async def test_get_state_room_offset_group_enabled_and_global_blocking_sources():
    coord = _make_coordinator(rooms=[_room()])
    coord.room_offsets = {"Bathroom": 1.5}
    coord.room_group_enabled = {"Bathroom": False}
    coord.global_blocking_sources = MagicMock(
        return_value=["controller_pause", "window"]
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    payload = conn.send_result.call_args[0][1]
    room_payload = payload["rooms"][0]
    assert room_payload["offset"] == 1.5
    assert room_payload["group_enabled"] is False
    assert payload["blocking_sources"] == ["controller_pause", "window"]


# ── ws_get_state: per-room payload shape (v0.9.0 fields) ───────────────────


@pytest.mark.asyncio
async def test_get_state_room_includes_blocking_sources():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    coord.get_room_blocking_sources = MagicMock(
        side_effect=lambda name: ["controller_off"] if name == "Bathroom" else []
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["blocking_sources"] == ["controller_off"]


@pytest.mark.asyncio
async def test_get_state_room_v090_config_fields_default_to_none():
    """A room with none of the optional v0.9.0 engines configured must
    report them as None, not an empty string or missing key — the panel's
    Konfiguration tab treats falsy as "not configured"."""
    coord = _make_coordinator(rooms=[_room()])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["calibration_entity"] is None
    assert room["sync_mode"] is None
    assert room["schedule_entity"] is None


@pytest.mark.asyncio
async def test_get_state_room_v090_config_fields_passed_through_when_set():
    coord = _make_coordinator(
        rooms=[
            _room(
                calibration_entity="number.bathroom_calibration",
                sync_mode="mirror",
                schedule_entity="schedule.bathroom",
            )
        ]
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["calibration_entity"] == "number.bathroom_calibration"
    assert room["sync_mode"] == "mirror"
    assert room["schedule_entity"] == "schedule.bathroom"


@pytest.mark.asyncio
async def test_get_state_room_sync_mode_disabled_string_passes_through_unfiltered():
    """The backend sends the raw value including the "disabled" default —
    filtering it out of display is the frontend's job, not this payload's."""
    coord = _make_coordinator(rooms=[_room(sync_mode="disabled")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["sync_mode"] == "disabled"


# ── ws_get_state: room valve/boost/window derivation ────────────────────────


@pytest.mark.asyncio
async def test_get_state_netatmo_valve_position_from_heating_power_request():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    climate_state = MagicMock()
    climate_state.attributes = {"heating_power_request": 42}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: climate_state if eid == "climate.bathroom" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["valve_position"] == 42.0
    # "heating_power" was dropped from the payload in 0.18.1 (frontend
    # dead-code sweep) — it always duplicated valve_position for Netatmo
    # rooms and no frontend ever read it separately.
    assert "heating_power" not in room


@pytest.mark.asyncio
async def test_get_state_zigbee_pi_demand_overrides_netatmo_valve():
    coord = _make_coordinator(
        rooms=[
            _room(
                climate="climate.bathroom",
                trv_type="zigbee",
                pi_demand_entity="sensor.bathroom_pi_demand",
            )
        ]
    )
    climate_state = MagicMock()
    climate_state.attributes = {"heating_power_request": 10}
    pi_state = MagicMock()
    pi_state.state = "77"

    def _get(eid):
        if eid == "climate.bathroom":
            return climate_state
        if eid == "sensor.bathroom_pi_demand":
            return pi_state
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["valve_position"] == 77.0  # pi_demand wins over heating_power_request


@pytest.mark.asyncio
async def test_get_state_boost_active_reflects_coordinator_boost_map():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    coord.boost_active_rooms = {"Bathroom": True}
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["boost_active"] is True


@pytest.mark.asyncio
async def test_get_state_windows_open_true_when_any_sensor_on():
    coord = _make_coordinator(
        rooms=[_room(window_sensors=["binary_sensor.bathroom_window"])]
    )
    win_state = MagicMock()
    win_state.state = "on"
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: (
            win_state if eid == "binary_sensor.bathroom_window" else None
        )
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["windows_open"] is True


# ── ws_get_state: battery / humidity / CO2 (Rum-detaljer) ───────────────────


@pytest.mark.asyncio
async def test_get_state_battery_from_dedicated_sensor():
    coord = _make_coordinator(
        rooms=[
            _room(
                climate="climate.bathroom", battery_sensor="sensor.bathroom_trv_battery"
            )
        ]
    )
    battery_state = MagicMock()
    battery_state.state = "63"
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: (
            battery_state if eid == "sensor.bathroom_trv_battery" else None
        )
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["battery_level"] == 63.0


@pytest.mark.asyncio
async def test_get_state_battery_falls_back_to_climate_attribute():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    climate_state = MagicMock()
    climate_state.attributes = {"battery_level": 88}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: climate_state if eid == "climate.bathroom" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["battery_level"] == 88.0


@pytest.mark.asyncio
async def test_get_state_battery_none_when_no_source_configured():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    climate_state = MagicMock()
    climate_state.attributes = {}  # no battery_level attribute either
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: climate_state if eid == "climate.bathroom" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["battery_level"] is None


@pytest.mark.asyncio
async def test_get_state_dedicated_battery_sensor_takes_priority_over_attribute():
    coord = _make_coordinator(
        rooms=[
            _room(
                climate="climate.bathroom", battery_sensor="sensor.bathroom_trv_battery"
            )
        ]
    )
    climate_state = MagicMock()
    climate_state.attributes = {"battery_level": 10}  # should be ignored
    battery_state = MagicMock()
    battery_state.state = "95"

    def _get(eid):
        if eid == "climate.bathroom":
            return climate_state
        if eid == "sensor.bathroom_trv_battery":
            return battery_state
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["battery_level"] == 95.0


@pytest.mark.asyncio
async def test_get_state_humidity_and_co2_passed_through_when_configured():
    coord = _make_coordinator(
        rooms=[
            _room(
                climate="climate.bathroom",
                humidity_sensor="sensor.bathroom_humidity",
                co2_sensor="sensor.bathroom_co2",
            )
        ]
    )
    humidity_state = MagicMock()
    humidity_state.state = "54.5"
    co2_state = MagicMock()
    co2_state.state = "612"

    def _get(eid):
        if eid == "sensor.bathroom_humidity":
            return humidity_state
        if eid == "sensor.bathroom_co2":
            return co2_state
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["humidity"] == 54.5
    assert room["co2"] == 612.0


@pytest.mark.asyncio
async def test_get_state_humidity_and_co2_default_to_none_when_not_configured():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["humidity"] is None
    assert room["co2"] is None


# ── ws_get_state: PID power / calibration offset / window duration / health
#    (2026-09 frontend-parity fix — these were computed but only ever
#    visible via HA's own entity page) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_state_pid_calibration_window_duration_default_to_none():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["pid_power"] is None
    assert room["calibration_offset"] is None
    assert room["window_duration_today"] is None
    # No state at all for climate.bathroom in this fixture — correctly
    # counted as unavailable, matching a real HA instance where a missing
    # state means the entity truly isn't reporting.
    assert room["unavailable_entities"] == ["climate.bathroom"]


@pytest.mark.asyncio
async def test_get_state_pid_power_computed_from_pid_last_output():
    coord = _make_coordinator(
        rooms=[_room(name="Bathroom", climate="climate.bathroom")]
    )
    pid = MagicMock()
    pid._last_output = 0.35
    coord.get_pid = MagicMock(
        side_effect=lambda name: pid if name == "Bathroom" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["pid_power"] == 35.0


@pytest.mark.asyncio
async def test_get_state_calibration_offset_from_calibration_engine_last_written():
    coord = _make_coordinator(
        rooms=[_room(name="Bathroom", climate="climate.bathroom")]
    )
    coord.calibration_engine._last_written = {"Bathroom": -0.5}
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["calibration_offset"] == -0.5


@pytest.mark.asyncio
async def test_get_state_unavailable_entities_lists_missing_or_unavailable():
    coord = _make_coordinator(
        rooms=[
            _room(
                climate="climate.bathroom",
                window_sensors=["binary_sensor.bathroom_window"],
                humidity_sensor="sensor.bathroom_humidity",
            )
        ]
    )
    climate_state = MagicMock()
    climate_state.state = "heat"
    climate_state.attributes = {}
    window_state = MagicMock()
    window_state.state = "unavailable"

    def _get(eid):
        if eid == "climate.bathroom":
            return climate_state
        if eid == "binary_sensor.bathroom_window":
            return window_state
        return None  # sensor.bathroom_humidity has no state at all

    coord.hass.states.get = MagicMock(side_effect=_get)
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert "climate.bathroom" not in room["unavailable_entities"]
    assert "binary_sensor.bathroom_window" in room["unavailable_entities"]
    assert "sensor.bathroom_humidity" in room["unavailable_entities"]


@pytest.mark.asyncio
async def test_get_state_unavailable_entities_empty_when_everything_reporting():
    coord = _make_coordinator(
        rooms=[
            _room(
                climate="climate.bathroom",
                window_sensors=["binary_sensor.bathroom_window"],
            )
        ]
    )
    ok_state = MagicMock()
    ok_state.state = "heat"
    ok_state.attributes = {}
    window_state = MagicMock()
    window_state.state = "off"

    def _get(eid):
        if eid == "climate.bathroom":
            return ok_state
        if eid == "binary_sensor.bathroom_window":
            return window_state
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["unavailable_entities"] == []


# ── ws_get_state: Fase 2 (2026-09-11) target_temp / cloud_* diagnostics ─────


@pytest.mark.asyncio
async def test_get_state_target_temp_comes_from_coordinator_helper():
    """target_temp must be whatever get_room_target_temp() resolves — this
    is the single source of truth shared with _async_pid_tick() so the
    panel can never show a different target than the one the PID actually
    chases (the gap that hid the B21 bug)."""
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    coord.get_room_target_temp = MagicMock(
        side_effect=lambda room: 19.5 if room.get("room_name") == "Bathroom" else 21.0
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["target_temp"] == 19.5


@pytest.mark.asyncio
async def test_get_state_cloud_fields_default_to_none_without_climate_state():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    hass = _make_hass_with_entry(coord)  # states.get() default MagicMock returns None
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    for key in (
        "cloud_temperature",
        "cloud_hvac_action",
        "cloud_preset_mode",
        "cloud_preset_modes",
        "cloud_selected_schedule",
        "cloud_hvac_modes",
        "cloud_min_temp",
        "cloud_max_temp",
        "cloud_target_temp_step",
    ):
        assert room[key] is None, f"{key} should default to None"


@pytest.mark.asyncio
async def test_get_state_cloud_fields_populated_from_climate_attributes():
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    climate_state = MagicMock()
    climate_state.attributes = {
        "temperature": 18.0,
        "hvac_action": "idle",
        "preset_mode": "away",
        "preset_modes": ["schedule", "away", "frost_guard", "boost"],
        "selected_schedule": "Vinter",
        "hvac_modes": ["auto", "heat"],
        "min_temp": 7,
        "max_temp": 30,
        "target_temp_step": 0.5,
    }
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: climate_state if eid == "climate.bathroom" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["cloud_temperature"] == 18.0
    assert room["cloud_hvac_action"] == "idle"
    assert room["cloud_preset_mode"] == "away"
    assert room["cloud_preset_modes"] == ["schedule", "away", "frost_guard", "boost"]
    assert room["cloud_selected_schedule"] == "Vinter"
    assert room["cloud_hvac_modes"] == ["auto", "heat"]
    assert room["cloud_min_temp"] == 7.0
    assert room["cloud_max_temp"] == 30.0
    assert room["cloud_target_temp_step"] == 0.5


@pytest.mark.asyncio
async def test_get_state_cloud_temperature_non_numeric_coerces_to_none():
    """_coerce_float() must swallow a non-numeric attribute (e.g. Netatmo
    entity briefly reporting 'unknown' as an attribute string) rather than
    raising and breaking the whole get_state response."""
    coord = _make_coordinator(rooms=[_room(climate="climate.bathroom")])
    climate_state = MagicMock()
    climate_state.attributes = {"temperature": "unknown"}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: climate_state if eid == "climate.bathroom" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["cloud_temperature"] is None


# ── ws_get_state: climate entity resolved via CONF_TRVS (regression) ────────


@pytest.mark.asyncio
async def test_get_state_resolves_climate_entity_from_trvs_only_room():
    """Regression: a room saved through the per-TRV edit UI has CONF_TRVS
    but no flat climate_entity/trv_type/pi_demand_entity field — the old
    code read those flat fields directly and got empty/default values for
    every such room (Sætpunkt, TRV temp, valve % all blank in the panel)."""
    coord = _make_coordinator(
        rooms=[
            {
                "room_name": "Køkken",
                CONF_TRVS: [{"climate_entity": "climate.kokken", "trv_type": "zigbee"}],
            }
        ]
    )
    climate_state = MagicMock()
    climate_state.attributes = {"heating_power_request": 37}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: climate_state if eid == "climate.kokken" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["climate_entity"] == "climate.kokken"
    assert room["trv_type"] == "zigbee"
    assert room["valve_position"] == 37.0


@pytest.mark.asyncio
async def test_get_state_pi_demand_entity_resolved_from_trvs_only_room():
    coord = _make_coordinator(
        rooms=[
            {
                "room_name": "Køkken",
                CONF_TRVS: [
                    {
                        "climate_entity": "climate.kokken",
                        "trv_type": "zigbee",
                        "pi_demand_entity": "sensor.kokken_pi_demand",
                    }
                ],
            }
        ]
    )
    pi_state = MagicMock()
    pi_state.state = "55"
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: pi_state if eid == "sensor.kokken_pi_demand" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    room = conn.send_result.call_args[0][1]["rooms"][0]
    assert room["valve_position"] == 55.0


# ── ws_get_state: persons ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_state_person_shape():
    coord = _make_coordinator(
        persons=[{"person_entity": "person.flemming", "person_tracking": True}]
    )
    p_state = MagicMock()
    p_state.state = "home"
    p_state.last_changed = None
    p_state.attributes = {"friendly_name": "Flemming"}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: p_state if eid == "person.flemming" else None
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    person = conn.send_result.call_args[0][1]["persons"][0]
    assert person["name"] == "Flemming"
    assert person["state"] == "home"
    assert person["tracking"] is True


# ── ws_boost_start / ws_boost_stop ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_boost_start_no_entry_sends_not_found():
    hass = _make_hass_without_entry()
    conn = _connection()
    await ws_boost_start(hass, conn, _msg())
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_boost_start_delegates_to_coordinator_and_reports_count():
    coord = _make_coordinator()
    coord.async_boost_start = AsyncMock(return_value=["Bathroom", "Kitchen"])
    coord.boost_remaining_minutes = 30
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_boost_start(hass, conn, _msg(temperature=23.0, duration_minutes=30))

    coord.async_boost_start.assert_awaited_once_with(23.0, 30)
    result = conn.send_result.call_args[0][1]
    assert result["success"] is True
    assert result["rooms_boosted"] == 2
    assert result["boost_remaining_minutes"] == 30


@pytest.mark.asyncio
async def test_boost_stop_delegates_to_coordinator_and_reports_count():
    coord = _make_coordinator()
    coord.async_boost_stop = AsyncMock(return_value=["Bathroom"])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_boost_stop(hass, conn, _msg())

    coord.async_boost_stop.assert_awaited_once()
    result = conn.send_result.call_args[0][1]
    assert result["success"] is True
    assert result["rooms_restored"] == 1


# ── ws_set_room_temp ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_room_temp_no_entry_sends_not_found():
    hass = _make_hass_without_entry()
    conn = _connection()
    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom"))
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_set_room_temp_unknown_room_sends_not_found():
    coord = _make_coordinator(rooms=[_room(name="Kitchen")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom"))

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_set_room_temp_no_write_entity_sends_not_found():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    coord.get_room_trvs = MagicMock(return_value=[])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom"))

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_set_room_temp_sets_temperature_and_logs():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(
        hass, conn, _msg(room_name="Bathroom", temperature=22.5, duration_min=60)
    )

    hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bathroom", "temperature": 22.5},
        blocking=True,
    )
    coord.log_event.assert_called_once()
    result = conn.send_result.call_args[0][1]
    assert result["success"] is True
    assert result["temperature"] == 22.5


@pytest.mark.asyncio
async def test_set_room_temp_none_restores_zigbee_hvac_mode():
    coord = _make_coordinator(rooms=[_room(name="Bathroom", trv_type="zigbee")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom", temperature=None))

    hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.bathroom", "hvac_mode": "heat"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_set_room_temp_none_restores_netatmo_schedule_preset():
    coord = _make_coordinator(rooms=[_room(name="Bathroom", trv_type="netatmo")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom", temperature=None))

    hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.bathroom", "preset_mode": "schedule"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_set_room_temp_service_failure_sends_service_error():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    hass = _make_hass_with_entry(coord)
    hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom", temperature=21.0))

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "service_error"
    conn.send_result.assert_not_called()


# ── ws_set_room_temp: B18 multi-TRV grouping ──────────────────────────────────


@pytest.mark.asyncio
async def test_set_room_temp_multi_trv_room_sends_to_every_trv():
    coord = _make_coordinator(
        rooms=[
            {
                "room_name": "Living room",
                "trvs": [
                    {"climate_entity": "climate.living_room"},
                    {"climate_entity": "climate.living_room_trv2"},
                ],
            }
        ]
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(
        hass, conn, _msg(room_name="Living room", temperature=22.0, duration_min=60)
    )

    calls = hass.services.async_call.await_args_list
    assert len(calls) == 2
    sent = {c.args[2]["entity_id"]: c.args[2]["temperature"] for c in calls}
    assert set(sent) == {"climate.living_room", "climate.living_room_trv2"}
    assert sent["climate.living_room"] == sent["climate.living_room_trv2"] == 22.0
    result = conn.send_result.call_args[0][1]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_set_room_temp_none_multi_trv_room_restores_each_by_own_trv_type():
    coord = _make_coordinator(
        rooms=[
            {
                "room_name": "Living room",
                "trvs": [
                    {
                        "climate_entity": "climate.living_room",
                        "trv_type": "netatmo",
                    },
                    {
                        "climate_entity": "climate.living_room_trv2",
                        "trv_type": "zigbee",
                    },
                ],
            }
        ]
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Living room", temperature=None))

    calls = hass.services.async_call.await_args_list
    assert len(calls) == 2
    by_entity = {c.args[2]["entity_id"]: c for c in calls}
    assert by_entity["climate.living_room"].args[1] == "set_preset_mode"
    assert by_entity["climate.living_room_trv2"].args[1] == "set_hvac_mode"


# ── ws_update_config ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_config_no_entry_sends_not_found():
    hass = _make_hass_without_entry()
    conn = _connection()
    await ws_update_config(hass, conn, _msg())
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_update_config_no_fields_sent_reports_unchanged():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_config(hass, conn, _msg())

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_config_changed_field_persists_and_logs():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_config(hass, conn, _msg(alarm_panel="alarm_control_panel.house"))

    hass.config_entries.async_update_entry.assert_called_once()
    coord.log_event.assert_called_once()
    result = conn.send_result.call_args[0][1]
    assert result["updated"] is True
    assert result["changed"] == ["alarm_panel"]


@pytest.mark.asyncio
async def test_update_config_same_value_is_not_reported_as_changed():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    hass.config_entries.async_entries.return_value[0].options = {
        "alarm_panel": "alarm_control_panel.house"
    }
    conn = _connection()

    await ws_update_config(hass, conn, _msg(alarm_panel="alarm_control_panel.house"))

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}


# ── ws_update_config — manual_trv_control (2026-09-13) ──────────────────────
#
# Was session-scoped only (a plain panel.js field, reset on every reload) —
# now persisted the same way alarm_panel/notify_service already are.


@pytest.mark.asyncio
async def test_update_config_manual_trv_control_true_persists_and_logs():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_config(hass, conn, _msg(manual_trv_control=True))

    hass.config_entries.async_update_entry.assert_called_once()
    persisted_options = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ]
    assert persisted_options["manual_trv_control"] is True
    coord.log_event.assert_called_once()
    result = conn.send_result.call_args[0][1]
    assert result == {"updated": True, "changed": ["manual_trv_control"]}


@pytest.mark.asyncio
async def test_update_config_manual_trv_control_same_value_is_not_reported_as_changed():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    hass.config_entries.async_entries.return_value[0].options = {
        "manual_trv_control": True
    }
    conn = _connection()

    await ws_update_config(hass, conn, _msg(manual_trv_control=True))

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_config_manual_trv_control_false_persists_when_previously_true():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    hass.config_entries.async_entries.return_value[0].options = {
        "manual_trv_control": True
    }
    conn = _connection()

    await ws_update_config(hass, conn, _msg(manual_trv_control=False))

    persisted_options = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ]
    assert persisted_options["manual_trv_control"] is False
    result = conn.send_result.call_args[0][1]
    assert result == {"updated": True, "changed": ["manual_trv_control"]}


# ── ws_update_config — Fase 2, del 1 (2026-09-13) ────────────────────────────
#
# Generalizes ws_update_config() from hand-written string/bool branches into
# three per-type tables (_STRING_CONFIG_FIELDS/_BOOL_CONFIG_FIELD_DEFAULTS/
# _NUMERIC_CONFIG_FIELDS) so the panel's new "Indstillinger" tab (PID, Boost
# defaults, window warning, night setback, grace, auto-off, more notify
# toggles) can all save live through the same command. The critical
# correctness property these tests guard: change-detection must compare
# against each field's real DEFAULT_* fallback, not a blanket 0/False/"" —
# a bool field whose true default is True (e.g. pid_enabled, notify_windows)
# must NOT be reported as "changed" when the panel sends back that same
# default while entry.options has never stored the key at all.


@pytest.mark.asyncio
async def test_update_config_numeric_field_persists_as_declared_type():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_config(hass, conn, _msg(pid_kp=0.75))

    persisted_options = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ]
    assert persisted_options["pid_kp"] == 0.75
    assert isinstance(persisted_options["pid_kp"], float)
    result = conn.send_result.call_args[0][1]
    assert result == {"updated": True, "changed": ["pid_kp"]}


@pytest.mark.asyncio
async def test_update_config_numeric_field_casts_int_fields_to_int():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    # HA's number selector can hand back a float even for a whole-number
    # field (e.g. 45.0) — grace_day_min is declared int in
    # _NUMERIC_CONFIG_FIELDS, so it must be stored as a real int.
    await ws_update_config(hass, conn, _msg(grace_day_min=45.0))

    persisted_options = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ]
    assert persisted_options["grace_day_min"] == 45
    assert isinstance(persisted_options["grace_day_min"], int)


@pytest.mark.asyncio
async def test_update_config_numeric_field_at_default_when_unset_is_not_changed():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)  # entry.options == {} — key never stored
    conn = _connection()

    # Sending exactly the constant's own DEFAULT_* value must NOT be reported
    # as a change — the field's absence from entry.options already means
    # "at default", the same value coordinator.config would resolve to.
    await ws_update_config(
        hass, conn, _msg(pid_kp=DEFAULT_PID_KP, grace_day_min=DEFAULT_GRACE_DAY_MIN)
    )

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_config_bool_field_at_true_default_when_unset_is_not_changed():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)  # entry.options == {} — key never stored
    conn = _connection()

    # pid_enabled/notify_windows/etc. default to True (not False like
    # manual_trv_control) — sending True back with nothing persisted yet
    # must not be treated as a change, or the panel could never turn one of
    # these OFF from a fresh install (the very bug this table structure
    # exists to avoid — see _BOOL_CONFIG_FIELD_DEFAULTS).
    await ws_update_config(hass, conn, _msg(pid_enabled=True, notify_windows=True))

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_config_bool_field_true_default_can_be_turned_off():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)  # entry.options == {} — key never stored
    conn = _connection()

    await ws_update_config(hass, conn, _msg(notify_windows=False))

    persisted_options = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ]
    assert persisted_options["notify_windows"] is False
    result = conn.send_result.call_args[0][1]
    assert result == {"updated": True, "changed": ["notify_windows"]}


@pytest.mark.asyncio
async def test_update_config_invalid_numeric_value_sends_invalid_value_error():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_config(hass, conn, _msg(pid_kp="not-a-number"))

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "invalid_value"
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_config_multiple_fields_in_one_message_all_persist():
    coord = _make_coordinator()
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_config(
        hass,
        conn,
        _msg(pid_kp=0.9, notify_windows=False, alarm_panel="alarm_control_panel.x"),
    )

    persisted_options = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ]
    assert persisted_options["pid_kp"] == 0.9
    assert persisted_options["notify_windows"] is False
    assert persisted_options["alarm_panel"] == "alarm_control_panel.x"
    result = conn.send_result.call_args[0][1]
    assert set(result["changed"]) == {"pid_kp", "notify_windows", "alarm_panel"}


# ── ws_update_room_config — punkt 3 (2026-09-13) ────────────────────────────
#
# Per-room live editing from the Rum-fane's room cards, without going through
# the options-flow config wizard. Deliberately scoped to just comfort_temp
# (Target temp) and away_temp_override (Away temp override) — the two fields
# picked over CO2 threshold etc, which stays options-flow-only. Mirrors
# ws_update_config's own change-detection-against-the-real-default property
# (see that section's comment above), plus min/max bounds ws_update_config
# doesn't need since its fields aren't HA-selector-range-limited the way
# _room_schema()'s comfort_temp/away_temp_override are.


@pytest.mark.asyncio
async def test_update_room_config_no_entry_sends_not_found():
    hass = _make_hass_without_entry()
    conn = _connection()
    await ws_update_room_config(hass, conn, _msg(room_name="Bathroom"))
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_update_room_config_unknown_room_sends_not_found():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Attic", comfort_temp=21.0)
    )

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_room_config_no_fields_sent_reports_unchanged():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(hass, conn, _msg(room_name="Bathroom"))

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_room_config_comfort_temp_persists_and_logs():
    room = _room(name="Bathroom")
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", comfort_temp=22.5)
    )

    hass.config_entries.async_update_entry.assert_called_once()
    persisted_rooms = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ][CONF_ROOMS]
    assert persisted_rooms[0][CONF_COMFORT_TEMP] == 22.5
    coord.log_event.assert_called_once()
    result = conn.send_result.call_args[0][1]
    assert result == {"updated": True, "changed": ["comfort_temp"]}


@pytest.mark.asyncio
async def test_update_room_config_away_temp_override_persists():
    room = _room(name="Bathroom")
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", away_temp_override=15.0)
    )

    persisted_rooms = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ][CONF_ROOMS]
    assert persisted_rooms[0][CONF_AWAY_TEMP_OVERRIDE] == 15.0
    result = conn.send_result.call_args[0][1]
    assert result == {"updated": True, "changed": ["away_temp_override"]}


@pytest.mark.asyncio
async def test_update_room_config_same_value_is_not_reported_as_changed():
    room = _room(name="Bathroom")
    room[CONF_COMFORT_TEMP] = 20.0
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", comfort_temp=20.0)
    )

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_room_config_default_when_unset_is_not_changed():
    # Room dict has no comfort_temp key at all — sending exactly
    # DEFAULT_COMFORT_TEMP back must not be treated as a change, same
    # "absence == at default" property ws_update_config's own numeric/bool
    # tables guard (see that section's comment above).
    room = _room(name="Bathroom")
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", comfort_temp=DEFAULT_COMFORT_TEMP)
    )

    result = conn.send_result.call_args[0][1]
    assert result == {"updated": False, "changed": []}
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_room_config_out_of_range_value_sends_invalid_value_error():
    room = _room(name="Bathroom")
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    # _room_schema()'s comfort_temp selector caps at 26.0 — a raw WS write
    # must enforce the same bound instead of silently writing an out-of-range
    # value straight to entry.options.
    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", comfort_temp=30.0)
    )

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "invalid_value"
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_room_config_invalid_type_sends_invalid_value_error():
    room = _room(name="Bathroom")
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", comfort_temp="not-a-number")
    )

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "invalid_value"
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_update_room_config_preserves_other_rooms_untouched():
    bathroom = _room(name="Bathroom")
    bathroom[CONF_COMFORT_TEMP] = 19.0
    kitchen = _room(name="Kitchen")
    kitchen[CONF_COMFORT_TEMP] = 21.0
    coord = _make_coordinator(rooms=[bathroom, kitchen])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass, conn, _msg(room_name="Bathroom", comfort_temp=23.0)
    )

    persisted_rooms = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ][CONF_ROOMS]
    assert persisted_rooms[0]["room_name"] == "Bathroom"
    assert persisted_rooms[0][CONF_COMFORT_TEMP] == 23.0
    assert persisted_rooms[1]["room_name"] == "Kitchen"
    assert persisted_rooms[1][CONF_COMFORT_TEMP] == 21.0  # untouched


@pytest.mark.asyncio
async def test_update_room_config_multiple_fields_in_one_message_all_persist():
    room = _room(name="Bathroom")
    coord = _make_coordinator(rooms=[room])
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_update_room_config(
        hass,
        conn,
        _msg(room_name="Bathroom", comfort_temp=22.0, away_temp_override=16.0),
    )

    persisted_rooms = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
    ][CONF_ROOMS]
    assert persisted_rooms[0][CONF_COMFORT_TEMP] == 22.0
    assert persisted_rooms[0][CONF_AWAY_TEMP_OVERRIDE] == 16.0
    result = conn.send_result.call_args[0][1]
    assert set(result["changed"]) == {"comfort_temp", "away_temp_override"}


# ── ws_get_history ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_history_no_entry_sends_not_found():
    hass = _make_hass_without_entry()
    conn = _connection()
    await ws_get_history(hass, conn, _msg())
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_get_history_returns_events_and_days_shape():
    coord = _make_coordinator()
    coord._event_log = []
    coord._energy_history = {}
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_history(hass, conn, _msg(days=3))

    result = conn.send_result.call_args[0][1]
    assert result["events"] == []
    assert len(result["days"]) == 3
    assert set(result["days"][0].keys()) == {"label", "date", "saved", "wasted"}


# ── _get_entry helper ────────────────────────────────────────────────────────


def test_get_entry_returns_none_when_no_loaded_entries():
    hass = _make_hass_without_entry()
    assert websocket._get_entry(hass) is None


def test_get_entry_skips_entries_without_runtime_data():
    hass = MagicMock()
    dead_entry = MagicMock()
    dead_entry.runtime_data = None
    live_entry = MagicMock()
    live_entry.runtime_data = _make_coordinator()
    hass.config_entries.async_entries = MagicMock(return_value=[dead_entry, live_entry])
    assert websocket._get_entry(hass) is live_entry
