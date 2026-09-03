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
    AutoOffReason,
    ControllerState,
    EffectiveSeason,
    RoomState,
    SeasonMode,
)

# websocket_api.async_response wraps each handler in a sync scheduler that
# fires-and-forgets a background task; __wrapped__ is the real coroutine.
ws_get_state = websocket.ws_get_state.__wrapped__
ws_boost_start = websocket.ws_boost_start.__wrapped__
ws_boost_stop = websocket.ws_boost_stop.__wrapped__
ws_set_room_temp = websocket.ws_set_room_temp.__wrapped__
ws_update_config = websocket.ws_update_config.__wrapped__
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
    coord.group_offset = 0.0
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
        "group_offset",
        "blocking_sources",
    ):
        assert key in payload, f"missing key: {key}"
    assert payload["controller_state"] == "on"


@pytest.mark.asyncio
async def test_get_state_group_offset_and_global_blocking_sources_passed_through():
    coord = _make_coordinator(rooms=[_room()])
    coord.group_offset = 1.5
    coord.global_blocking_sources = MagicMock(
        return_value=["controller_pause", "window"]
    )
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_get_state(hass, conn, _msg())

    payload = conn.send_result.call_args[0][1]
    assert payload["group_offset"] == 1.5
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
    assert room["heating_power"] == 42.0


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
    coord.get_write_entity = MagicMock(return_value=None)
    hass = _make_hass_with_entry(coord)
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom"))

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "not_found"


@pytest.mark.asyncio
async def test_set_room_temp_sets_temperature_and_logs():
    coord = _make_coordinator(rooms=[_room(name="Bathroom")])
    coord.get_write_entity = MagicMock(return_value="climate.bathroom")
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
    coord.get_write_entity = MagicMock(return_value="climate.bathroom")
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
    coord.get_write_entity = MagicMock(return_value="climate.bathroom_homekit")
    coord.get_climate_entity = MagicMock(return_value="climate.bathroom")
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
    coord.get_write_entity = MagicMock(return_value="climate.bathroom")
    hass = _make_hass_with_entry(coord)
    hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    conn = _connection()

    await ws_set_room_temp(hass, conn, _msg(room_name="Bathroom", temperature=21.0))

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args[0][1] == "service_error"
    conn.send_result.assert_not_called()


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
