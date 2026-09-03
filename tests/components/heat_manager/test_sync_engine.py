"""Tests for SyncEngine (v0.9.0).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.heat_manager.const import (
    ControllerState,
    RoomState,
    SYNC_MODE_DISABLED,
    SYNC_MODE_LOCK,
    SYNC_MODE_MIRROR,
)
from custom_components.heat_manager.engine.sync_engine import SyncEngine


def _make_coordinator(rooms=None, controller_state=ControllerState.ON) -> MagicMock:
    coord = MagicMock()
    coord.rooms = rooms or []
    coord.controller_state = controller_state
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.get_write_entity = MagicMock(return_value="climate.living_room")
    coord.last_expected_setpoint = {}
    coord.log_event = MagicMock()
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    coord.hass = hass
    return coord


def _room(name="living_room", climate="climate.living_room", sync_mode=SYNC_MODE_MIRROR) -> dict:
    return {"room_name": name, "climate_entity": climate, "sync_mode": sync_mode}


def _event(entity_id: str, temperature, state: str = "heat") -> MagicMock:
    new_state = MagicMock()
    new_state.state = state
    new_state.attributes = {"temperature": temperature}
    event = MagicMock()
    event.data = {"entity_id": entity_id, "new_state": new_state}
    return event


# ── entity map / registration ───────────────────────────────────────────────

def test_disabled_room_not_in_entity_map():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_DISABLED)])
    engine = SyncEngine(coord)
    assert engine._entity_to_room == {}


def test_enabled_room_maps_climate_entity():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_MIRROR)])
    engine = SyncEngine(coord)
    assert engine._entity_to_room["climate.living_room"] == "living_room"


def test_no_entities_registers_no_listener():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_DISABLED)])
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_track_state_change_event"
    ) as mock_track:
        SyncEngine(coord)
        mock_track.assert_not_called()


def test_entities_present_registers_listener():
    coord = _make_coordinator(rooms=[_room()])
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_track_state_change_event"
    ) as mock_track:
        SyncEngine(coord)
        mock_track.assert_called_once()


# ── _handle_entity_change guards ────────────────────────────────────────────

def test_unmapped_entity_is_ignored():
    coord = _make_coordinator(rooms=[_room()])
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.other_room", 25.0))
        mock_later.assert_not_called()


def test_unavailable_state_is_ignored():
    coord = _make_coordinator(rooms=[_room()])
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 25.0, state="unavailable"))
        mock_later.assert_not_called()


def test_inactive_write_entity_is_ignored():
    """Room's active write entity is the HomeKit one — the cloud entity firing is stale."""
    coord = _make_coordinator(rooms=[_room()])
    coord.get_write_entity = MagicMock(return_value="climate.living_room_homekit")
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 25.0))
        mock_later.assert_not_called()


def test_controller_not_on_is_ignored():
    coord = _make_coordinator(rooms=[_room()], controller_state=ControllerState.PAUSE)
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 25.0))
        mock_later.assert_not_called()


def test_room_not_normal_is_ignored():
    coord = _make_coordinator(rooms=[_room()])
    coord.get_room_state = MagicMock(return_value=RoomState.AWAY)
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 25.0))
        mock_later.assert_not_called()


def test_no_expected_setpoint_yet_is_ignored():
    coord = _make_coordinator(rooms=[_room()])
    # last_expected_setpoint stays empty — PID hasn't ticked yet.
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 25.0))
        mock_later.assert_not_called()


def test_delta_below_threshold_is_ignored():
    coord = _make_coordinator(rooms=[_room()])
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 20.2))
        mock_later.assert_not_called()


def test_delta_above_threshold_schedules_confirm():
    coord = _make_coordinator(rooms=[_room()])
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        mock_later.return_value = MagicMock()
        engine._handle_entity_change(_event("climate.living_room", 22.0))
        mock_later.assert_called_once()
        assert "living_room" in engine._pending_confirm


def test_already_pending_does_not_schedule_again():
    coord = _make_coordinator(rooms=[_room()])
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    engine._pending_confirm["living_room"] = MagicMock()
    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_call_later"
    ) as mock_later:
        engine._handle_entity_change(_event("climate.living_room", 22.0))
        mock_later.assert_not_called()


def test_resolved_mismatch_cancels_pending():
    coord = _make_coordinator(rooms=[_room()])
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)
    cancel = MagicMock()
    engine._pending_confirm["living_room"] = cancel
    engine._handle_entity_change(_event("climate.living_room", 20.1))
    cancel.assert_called_once()
    assert "living_room" not in engine._pending_confirm


# ── _async_act: mirror mode ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_act_mirror_switches_to_override():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_MIRROR)])
    coord.last_expected_setpoint = {"living_room": 20.0}
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": 22.0}
    coord.hass.states.get = MagicMock(return_value=state)
    engine = SyncEngine(coord)

    await engine._async_act("living_room", "climate.living_room")

    coord.set_room_state.assert_called_once_with("living_room", RoomState.OVERRIDE)
    coord.hass.services.async_call.assert_not_called()


# ── _async_act: lock mode ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_act_lock_reverts_setpoint():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_LOCK)])
    coord.last_expected_setpoint = {"living_room": 20.0}
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": 22.0}
    coord.hass.states.get = MagicMock(return_value=state)
    engine = SyncEngine(coord)

    await engine._async_act("living_room", "climate.living_room")

    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][0] == "climate"
    assert call_args[0][1] == "set_temperature"
    assert call_args[0][2] == {"entity_id": "climate.living_room", "temperature": 20.0}
    coord.set_room_state.assert_not_called()


@pytest.mark.asyncio
async def test_async_act_lock_revert_failure_is_caught():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_LOCK)])
    coord.last_expected_setpoint = {"living_room": 20.0}
    coord.hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": 22.0}
    coord.hass.states.get = MagicMock(return_value=state)
    engine = SyncEngine(coord)

    await engine._async_act("living_room", "climate.living_room")  # must not raise


@pytest.mark.asyncio
async def test_async_act_resolved_by_itself_takes_no_action():
    """Between scheduling the confirm and it firing, the entity settled back
    to the expected value — nothing to do."""
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_LOCK)])
    coord.last_expected_setpoint = {"living_room": 20.0}
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": 20.1}
    coord.hass.states.get = MagicMock(return_value=state)
    engine = SyncEngine(coord)

    await engine._async_act("living_room", "climate.living_room")

    coord.hass.services.async_call.assert_not_called()
    coord.set_room_state.assert_not_called()


@pytest.mark.asyncio
async def test_async_act_room_no_longer_normal_takes_no_action():
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_MIRROR)])
    coord.last_expected_setpoint = {"living_room": 20.0}
    coord.get_room_state = MagicMock(return_value=RoomState.AWAY)
    engine = SyncEngine(coord)

    await engine._async_act("living_room", "climate.living_room")

    coord.set_room_state.assert_not_called()
    coord.hass.services.async_call.assert_not_called()


# ── shutdown ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shutdown_unsubscribes_and_cancels_pending():
    coord = _make_coordinator(rooms=[_room()])
    engine = SyncEngine(coord)
    unsub = MagicMock()
    engine._unsubs = [unsub]
    cancel = MagicMock()
    engine._pending_confirm = {"living_room": cancel}

    await engine.async_shutdown()

    unsub.assert_called_once()
    cancel.assert_called_once()
    assert engine._unsubs == []
    assert engine._pending_confirm == {}
