"""Tests for engine/remote_button_engine.py (v0.14.0) — global remote-button
control (Aqara Climate Sensor W100 style: 3 configurable event.* entities)
for temp up/down and auto/manual mode toggle, applied across every
configured room at once.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import (
    BUTTON_TEMP_MAX,
    BUTTON_TEMP_MIN,
    BUTTON_TEMP_STEP,
    CONF_BUTTON_MODE_TOGGLE_ENTITY,
    CONF_BUTTON_TEMP_DOWN_ENTITY,
    CONF_BUTTON_TEMP_UP_ENTITY,
    RoomState,
)
from custom_components.heat_manager.engine.remote_button_engine import (
    RemoteButtonEngine,
)

UP_ENTITY = "event.aqara_climate_sensor_w100_button_3"
DOWN_ENTITY = "event.aqara_climate_sensor_w100_button_5"
MODE_ENTITY = "event.aqara_climate_sensor_w100_button_4"


# ── Coordinator factory ───────────────────────────────────────────────────────


def _make_coordinator(
    rooms=None,
    config=None,
    room_states=None,
    write_entities=None,
) -> MagicMock:
    coord = MagicMock()
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    # Mirrors test_sync_engine.py's pattern: return the coroutine itself so
    # tests can decide whether to drive it via the callback (assert
    # called/not-called) or await the underlying _async_* method directly.
    hass.async_create_task = MagicMock(side_effect=lambda coro, **kwargs: coro)
    hass.states.get = MagicMock(return_value=None)
    coord.hass = hass

    coord.rooms = rooms or []
    coord.config = (
        config
        if config is not None
        else {
            CONF_BUTTON_TEMP_UP_ENTITY: UP_ENTITY,
            CONF_BUTTON_TEMP_DOWN_ENTITY: DOWN_ENTITY,
            CONF_BUTTON_MODE_TOGGLE_ENTITY: MODE_ENTITY,
        }
    )

    states = dict(room_states or {})
    coord.get_room_state = MagicMock(
        side_effect=lambda name: states.get(name, RoomState.NORMAL)
    )

    def _set_state(name, state):
        states[name] = state

    coord.set_room_state = MagicMock(side_effect=_set_state)

    async def _async_set_room_override(name, enable, source="switch"):
        _set_state(name, RoomState.OVERRIDE if enable else RoomState.NORMAL)
        return True

    coord.async_set_room_override = AsyncMock(side_effect=_async_set_room_override)

    write_map = dict(write_entities or {})
    coord.get_room_write_entities = MagicMock(
        side_effect=lambda name: write_map.get(name, [])
    )

    coord.log_event = MagicMock()
    return coord


def _room(name: str) -> dict:
    return {"room_name": name}


def _press_event(event_type: str | None) -> MagicMock:
    new_state = MagicMock()
    new_state.attributes = {"event_type": event_type} if event_type is not None else {}
    event = MagicMock()
    event.data = {"new_state": new_state}
    return event


def _climate_state(temperature) -> MagicMock:
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": temperature}
    return state


# ── listener registration ────────────────────────────────────────────────────


def test_registers_a_listener_per_configured_entity():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    assert len(engine._unsubs) == 3


def test_unconfigured_entities_register_no_listeners():
    coord = _make_coordinator(config={})
    engine = RemoteButtonEngine(coord)
    assert engine._unsubs == []


def test_only_configured_entities_get_a_listener():
    coord = _make_coordinator(config={CONF_BUTTON_TEMP_UP_ENTITY: UP_ENTITY})
    engine = RemoteButtonEngine(coord)
    assert len(engine._unsubs) == 1


# ── _is_single_press ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("single", True),
        ("SINGLE", True),
        ("double", False),
        ("hold", False),
    ],
)
def test_is_single_press(event_type, expected):
    new_state = MagicMock()
    new_state.attributes = {"event_type": event_type}
    assert RemoteButtonEngine._is_single_press(new_state) is expected


def test_is_single_press_none_state_is_false():
    assert RemoteButtonEngine._is_single_press(None) is False


# ── callback guards: only "single" schedules a task ──────────────────────────


def test_temp_up_double_press_is_ignored():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("double"))
    coord.hass.async_create_task.assert_not_called()


def test_temp_up_single_press_schedules_a_task():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("single"))
    coord.hass.async_create_task.assert_called_once()


def test_temp_down_single_press_schedules_a_task():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_down(_press_event("single"))
    coord.hass.async_create_task.assert_called_once()


def test_mode_toggle_hold_press_is_ignored():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_mode_toggle(_press_event("hold"))
    coord.hass.async_create_task.assert_not_called()


def test_mode_toggle_single_press_schedules_a_task():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_mode_toggle(_press_event("single"))
    coord.hass.async_create_task.assert_called_once()


# ── _async_adjust_all_rooms: temp up/down ────────────────────────────────────


@pytest.mark.asyncio
async def test_temp_up_increases_setpoint_for_every_eligible_room():
    coord = _make_coordinator(
        rooms=[_room("Living room"), _room("Bathroom")],
        room_states={
            "Living room": RoomState.OVERRIDE,
            "Bathroom": RoomState.OVERRIDE,
        },
        write_entities={
            "Living room": ["climate.living_room"],
            "Bathroom": ["climate.bathroom"],
        },
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    calls = coord.hass.services.async_call.await_args_list
    assert len(calls) == 2
    targets = {c.args[2]["entity_id"]: c.args[2]["temperature"] for c in calls}
    assert targets == {"climate.living_room": 20.5, "climate.bathroom": 20.5}
    coord.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_temp_down_decreases_setpoint():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(-BUTTON_TEMP_STEP)

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 19.5},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_temp_up_skips_window_open_room():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.WINDOW_OPEN},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.hass.services.async_call.assert_not_called()
    coord.log_event.assert_not_called()


@pytest.mark.asyncio
async def test_temp_up_skips_away_room():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.AWAY},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_temp_up_auto_engages_override_for_normal_room():
    """Design decision: pressing +/- on a room still in auto (NORMAL)
    switches it to manual (OVERRIDE) first, so the next PID tick doesn't
    immediately overwrite the button's adjustment."""
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.NORMAL},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.async_set_room_override.assert_awaited_once_with(
        "Living room", True, source="remote"
    )
    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 20.5},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_temp_up_does_not_toggle_override_when_already_manual():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.async_set_room_override.assert_not_called()


@pytest.mark.asyncio
async def test_temp_up_clamps_to_max():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(BUTTON_TEMP_MAX))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.hass.services.async_call.assert_not_called()
    coord.log_event.assert_not_called()


@pytest.mark.asyncio
async def test_temp_down_clamps_to_min():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(BUTTON_TEMP_MIN))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(-BUTTON_TEMP_STEP)

    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_temp_up_fans_out_to_every_trv_in_multi_trv_room():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={
            "Living room": ["climate.living_room", "climate.living_room_trv2"]
        },
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    calls = coord.hass.services.async_call.await_args_list
    assert len(calls) == 2
    entities = {c.args[2]["entity_id"] for c in calls}
    assert entities == {"climate.living_room", "climate.living_room_trv2"}
    coord.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_temp_up_skips_room_with_no_readable_setpoint():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=None)
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_temp_up_ignores_room_with_no_write_entities():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={},
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)  # must not raise

    coord.hass.services.async_call.assert_not_called()


# ── _async_toggle_all_rooms: mode toggle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_mode_toggle_any_normal_switches_all_eligible_to_override():
    coord = _make_coordinator(
        rooms=[_room("Living room"), _room("Bathroom")],
        room_states={
            "Living room": RoomState.NORMAL,
            "Bathroom": RoomState.OVERRIDE,
        },
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    # Bathroom is already OVERRIDE (the target state) — only Living room,
    # which is still NORMAL, actually needs a command.
    coord.async_set_room_override.assert_awaited_once_with(
        "Living room", True, source="remote"
    )
    coord.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_mode_toggle_all_override_switches_all_back_to_normal():
    coord = _make_coordinator(
        rooms=[_room("Living room"), _room("Bathroom")],
        room_states={
            "Living room": RoomState.OVERRIDE,
            "Bathroom": RoomState.OVERRIDE,
        },
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    calls = {c.args for c in coord.async_set_room_override.await_args_list}
    assert calls == {("Living room", False), ("Bathroom", False)}
    coord.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_mode_toggle_skips_window_open_and_away_rooms():
    coord = _make_coordinator(
        rooms=[_room("Living room"), _room("Hallway"), _room("Bathroom")],
        room_states={
            "Living room": RoomState.NORMAL,
            "Hallway": RoomState.WINDOW_OPEN,
            "Bathroom": RoomState.AWAY,
        },
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    coord.async_set_room_override.assert_awaited_once_with(
        "Living room", True, source="remote"
    )


@pytest.mark.asyncio
async def test_mode_toggle_no_eligible_rooms_is_noop():
    coord = _make_coordinator(
        rooms=[_room("Hallway")],
        room_states={"Hallway": RoomState.AWAY},
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    coord.async_set_room_override.assert_not_called()
    coord.log_event.assert_not_called()


@pytest.mark.asyncio
async def test_mode_toggle_skips_room_already_in_target_state():
    """Idempotent: a room already OVERRIDE when everything is switching to
    OVERRIDE is left alone (no redundant TRV command)."""
    coord = _make_coordinator(
        rooms=[_room("Living room"), _room("Bathroom")],
        room_states={
            "Living room": RoomState.NORMAL,
            "Bathroom": RoomState.OVERRIDE,
        },
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    coord.async_set_room_override.assert_awaited_once_with(
        "Living room", True, source="remote"
    )


# ── lifecycle ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shutdown_calls_every_unsub():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    unsub1 = MagicMock()
    unsub2 = MagicMock()
    engine._unsubs = [unsub1, unsub2]

    await engine.async_shutdown()

    unsub1.assert_called_once()
    unsub2.assert_called_once()
    assert engine._unsubs == []


@pytest.mark.asyncio
async def test_async_tick_is_a_noop():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    await engine.async_tick()  # must not raise
