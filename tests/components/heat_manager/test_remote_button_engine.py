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
    # 2026-10-30: the engine writes through coordinator.async_call_climate_
    # service() per TRV (2026-09-16 audit fix) — model one TRV per write
    # entity so tests observe the real write path instead of the bypassed
    # hass.services.async_call the original tests asserted on.
    coord.get_room_trvs = MagicMock(
        side_effect=lambda name: [{"write": e} for e in write_map.get(name, [])]
    )
    coord.get_trv_write_entity = MagicMock(side_effect=lambda trv: trv["write"])
    coord.trv_needs_cloud_delay = MagicMock(return_value=False)
    coord.async_call_climate_service = AsyncMock()
    coord.set_remote_last_action = MagicMock()

    coord.log_event = MagicMock()
    return coord


def _room(name: str) -> dict:
    return {"room_name": name}


def _press_event(
    event_type: str | None,
    old_state: str | None = "2026-10-30T17:00:00+00:00",
    new_state_value: str = "2026-10-30T18:00:00+00:00",
) -> MagicMock:
    """A state-change event for an event.* entity. By default a genuine
    press: the state (the event's timestamp) changes from one valid
    timestamp to a newer one. old_state=None models the entity being added
    at startup; old_state="unavailable" models it being restored."""
    new_state = MagicMock()
    new_state.entity_id = UP_ENTITY
    new_state.state = new_state_value
    new_state.attributes = {"event_type": event_type} if event_type is not None else {}
    old = None
    if old_state is not None:
        old = MagicMock()
        old.state = old_state
    event = MagicMock()
    event.data = {"new_state": new_state, "old_state": old}
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


# ── callback guards: only "single" schedules a task ──────────────────────────


def test_temp_up_release_is_ignored():
    # A double press is now two steps (B22) and a hold starts boost (v0.60.0,
    # see test_status_line.py) — only the release of a hold does nothing.
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("release"))
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


def test_mode_toggle_long_release_is_ignored():
    # A hold on this button releases every override (v0.60.0); the release
    # event that follows it must not act a second time.
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_mode_toggle(_press_event("long_release"))
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

    calls = coord.async_call_climate_service.await_args_list
    assert len(calls) == 2
    targets = {c.args[1]: c.args[2]["temperature"] for c in calls}
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

    coord.async_call_climate_service.assert_awaited_once_with(
        "set_temperature",
        "climate.living_room",
        {"temperature": 19.5},
        needs_delay=False,
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

    coord.async_call_climate_service.assert_not_called()
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

    coord.async_call_climate_service.assert_not_called()


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
    coord.async_call_climate_service.assert_awaited_once_with(
        "set_temperature",
        "climate.living_room",
        {"temperature": 20.5},
        needs_delay=False,
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

    coord.async_call_climate_service.assert_not_called()
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

    coord.async_call_climate_service.assert_not_called()


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

    calls = coord.async_call_climate_service.await_args_list
    assert len(calls) == 2
    entities = {c.args[1] for c in calls}
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

    coord.async_call_climate_service.assert_not_called()


@pytest.mark.asyncio
async def test_temp_up_ignores_room_with_no_write_entities():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={},
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)  # must not raise

    coord.async_call_climate_service.assert_not_called()


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


# ── B22: Matter / Zigbee2MQTT press types ────────────────────────────────────


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("multi_press_1", 1),
        ("multi_press_2", 2),
        ("single", 1),
        ("single_minus", 1),
        ("double", 2),
        ("double_plus", 2),
        ("long_press", 0),
        ("long_release", 0),
        ("hold", 0),
        ("", 0),
        (None, 0),
    ],
)
def test_press_type_count(event_type, expected):
    assert RemoteButtonEngine._press_type_count(event_type) == expected


def test_bug_b22_matter_single_press_triggers_temp_up():
    """Regression: an Aqara W100 paired via Matter reports "multi_press_1"
    for a single press — the original "single"-only match ignored every
    press, so the remote silently never did anything."""
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._async_adjust_all_rooms = MagicMock(return_value="coro")

    engine._handle_temp_up(_press_event("multi_press_1"))

    engine._async_adjust_all_rooms.assert_called_once_with(BUTTON_TEMP_STEP)
    coord.hass.async_create_task.assert_called_once()


def test_double_press_applies_two_steps_up():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._async_adjust_all_rooms = MagicMock(return_value="coro")

    engine._handle_temp_up(_press_event("multi_press_2"))

    engine._async_adjust_all_rooms.assert_called_once_with(BUTTON_TEMP_STEP * 2)


def test_double_press_applies_two_steps_down():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._async_adjust_all_rooms = MagicMock(return_value="coro")

    engine._handle_temp_down(_press_event("multi_press_2"))

    engine._async_adjust_all_rooms.assert_called_once_with(-BUTTON_TEMP_STEP * 2)


@pytest.mark.parametrize("event_type", ["long_release", "release_plus"])
def test_long_press_release_is_ignored(event_type):
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event(event_type))
    coord.hass.async_create_task.assert_not_called()


def test_mode_toggle_matter_single_press_schedules_a_task():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_mode_toggle(_press_event("multi_press_1"))
    coord.hass.async_create_task.assert_called_once()


def test_mode_toggle_double_press_is_ignored():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_mode_toggle(_press_event("multi_press_2"))
    coord.hass.async_create_task.assert_not_called()


# ── B25: restart / attribute-only updates are not presses ────────────────────


def test_bug_b25_entity_added_at_startup_is_not_a_press():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("multi_press_1", old_state=None))
    coord.hass.async_create_task.assert_not_called()


def test_bug_b25_restore_from_unavailable_is_not_a_press():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("multi_press_1", old_state="unavailable"))
    coord.hass.async_create_task.assert_not_called()


def test_attribute_only_update_is_not_a_press():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    same = "2026-10-30T18:00:00+00:00"
    engine._handle_temp_up(
        _press_event("multi_press_1", old_state=same, new_state_value=same)
    )
    coord.hass.async_create_task.assert_not_called()


def test_new_state_unavailable_is_not_a_press():
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("multi_press_1", new_state_value="unavailable"))
    coord.hass.async_create_task.assert_not_called()


def test_first_press_after_unknown_state_counts():
    """A never-pressed event entity starts as "unknown" — its first real
    press must still count (only "unavailable"/missing is a restore)."""
    coord = _make_coordinator()
    engine = RemoteButtonEngine(coord)
    engine._handle_temp_up(_press_event("multi_press_1", old_state="unknown"))
    coord.hass.async_create_task.assert_called_once()


# ── B24: fast presses build on each other ────────────────────────────────────


@pytest.mark.asyncio
async def test_bug_b24_second_press_builds_on_first_despite_stale_state():
    """Regression: Netatmo reports the new setpoint back only after several
    seconds. Two quick presses used to both read 20.0 and both write 20.5."""
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)
    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    written = [
        c.args[2]["temperature"]
        for c in coord.async_call_climate_service.await_args_list
    ]
    assert written == [20.5, 21.0]


@pytest.mark.asyncio
async def test_pending_setpoint_expires():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)
    engine._pending_setpoints["Living room"] = (23.0, -1e9)  # long expired

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.async_call_climate_service.assert_awaited_once()
    assert coord.async_call_climate_service.await_args.args[2] == {"temperature": 20.5}


@pytest.mark.asyncio
async def test_room_coming_from_auto_ignores_old_pending_setpoint():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.NORMAL},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    engine = RemoteButtonEngine(coord)
    engine._pending_setpoints["Living room"] = (23.0, 10**12)  # fresh but stale-by-mode

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    assert coord.async_call_climate_service.await_args.args[2] == {"temperature": 20.5}


@pytest.mark.asyncio
async def test_failed_write_reports_nothing_and_stores_no_pending():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    coord.async_call_climate_service = AsyncMock(side_effect=RuntimeError("429"))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.log_event.assert_not_called()
    coord.set_remote_last_action.assert_not_called()
    assert "Living room" not in engine._pending_setpoints


@pytest.mark.asyncio
async def test_toggle_back_to_auto_clears_pending_setpoint():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
    )
    engine = RemoteButtonEngine(coord)
    engine._pending_setpoints["Living room"] = (22.0, 10**12)

    await engine._async_toggle_all_rooms()

    assert "Living room" not in engine._pending_setpoints


# ── v0.59.0: auto-restore countdown ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_temp_press_restarts_auto_restore_countdown_per_room():
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

    rooms = {c.args[0] for c in coord.set_remote_override_expiry.call_args_list}
    assert rooms == {"Living room", "Bathroom"}


@pytest.mark.asyncio
async def test_failed_write_does_not_start_countdown():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
        write_entities={"Living room": ["climate.living_room"]},
    )
    coord.hass.states.get = MagicMock(return_value=_climate_state(20.0))
    coord.async_call_climate_service = AsyncMock(side_effect=RuntimeError("429"))
    engine = RemoteButtonEngine(coord)

    await engine._async_adjust_all_rooms(BUTTON_TEMP_STEP)

    coord.set_remote_override_expiry.assert_not_called()


@pytest.mark.asyncio
async def test_toggle_to_manual_starts_countdown():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.NORMAL},
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    coord.set_remote_override_expiry.assert_called_once_with("Living room")


@pytest.mark.asyncio
async def test_toggle_back_to_auto_starts_no_countdown():
    coord = _make_coordinator(
        rooms=[_room("Living room")],
        room_states={"Living room": RoomState.OVERRIDE},
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_toggle_all_rooms()

    coord.set_remote_override_expiry.assert_not_called()
