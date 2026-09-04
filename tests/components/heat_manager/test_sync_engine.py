"""Tests for SyncEngine (v0.9.0).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.heat_manager.const import (
    CONF_TRVS,
    SYNC_MODE_DISABLED,
    SYNC_MODE_LOCK,
    SYNC_MODE_MIRROR,
    ControllerState,
    RoomState,
)
from custom_components.heat_manager.engine.sync_engine import SyncEngine
from custom_components.heat_manager.migrations import migrate_room_to_trvs


def _make_coordinator(rooms=None, controller_state=ControllerState.ON) -> MagicMock:
    coord = MagicMock()
    coord.rooms = rooms or []
    coord.controller_state = controller_state
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    # B18: sync_engine now resolves the *active TRV's* write entity via
    # get_trv_write_entity(trv) instead of the room-level get_write_entity().
    # Default to a fixed value (as the old get_write_entity mock did) — every
    # existing single-TRV test in this file drives exactly one room/TRV.
    coord.get_trv_write_entity = MagicMock(return_value="climate.living_room")
    coord.last_expected_setpoint = {}
    coord.log_event = MagicMock()
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    coord.hass = hass

    # B18: _build_entity_map() now reads get_room_trvs() instead of the
    # room dict directly. Default to the flat-mirror migration the real
    # coordinator uses at read time, so every existing single-TRV test
    # (built with _room()'s flat fields, including its "sync_mode" field)
    # keeps mapping to exactly the same entity/TRV as before.
    def _room_trvs(room_name):
        room = next((r for r in coord.rooms if r.get("room_name") == room_name), None)
        if room is None:
            return []
        return migrate_room_to_trvs(room).get(CONF_TRVS, [])

    coord.get_room_trvs = MagicMock(side_effect=_room_trvs)

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
    coord.get_trv_write_entity = MagicMock(return_value="climate.living_room_homekit")
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


@pytest.mark.asyncio
async def test_async_act_stale_write_entity_takes_no_action():
    """The room's active write entity changed (e.g. HomeKit <-> cloud
    switch) during the SYNC_CONFIRM_DELAY_SEC wait — acting on the now-stale
    entity_id the confirm callback captured would be wrong; the room's
    *current* write entity is climate.living_room_homekit, not the
    climate.living_room this callback was scheduled for."""
    coord = _make_coordinator(rooms=[_room(sync_mode=SYNC_MODE_LOCK)])
    coord.last_expected_setpoint = {"living_room": 20.0}
    coord.get_trv_write_entity = MagicMock(return_value="climate.living_room_homekit")
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": 22.0}
    coord.hass.states.get = MagicMock(return_value=state)
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


# ── B18: multi-TRV grouping — sync_mode is a per-TRV field ───────────────────

def _multi_trv_room(name="living_room", trvs=None):
    return {"room_name": name, "trvs": trvs or []}


def test_multi_trv_room_maps_each_trv_independently():
    """Two TRVs in one room, different sync_mode each — only the enabled
    one is mapped, and each maps to its own TRV dict."""
    room = _multi_trv_room(
        trvs=[
            {"climate_entity": "climate.living_room", "sync_mode": SYNC_MODE_MIRROR},
            {
                "climate_entity": "climate.living_room_trv2",
                "sync_mode": SYNC_MODE_DISABLED,
            },
        ]
    )
    coord = _make_coordinator(rooms=[room])
    engine = SyncEngine(coord)

    assert "climate.living_room" in engine._entity_to_room
    assert "climate.living_room_trv2" not in engine._entity_to_room
    assert (
        engine._entity_to_trv["climate.living_room"]["sync_mode"] == SYNC_MODE_MIRROR
    )


@pytest.mark.asyncio
async def test_async_act_uses_the_changed_trvs_own_sync_mode():
    """The secondary TRV is in lock mode while the primary is mirror —
    a mismatch on the secondary must revert (lock), not switch the whole
    room to OVERRIDE (which would be the primary's mirror behaviour)."""
    room = _multi_trv_room(
        trvs=[
            {"climate_entity": "climate.living_room", "sync_mode": SYNC_MODE_MIRROR},
            {
                "climate_entity": "climate.living_room_trv2",
                "sync_mode": SYNC_MODE_LOCK,
            },
        ]
    )
    coord = _make_coordinator(rooms=[room])
    coord.get_trv_write_entity = MagicMock(
        side_effect=lambda trv: trv.get("climate_entity")
    )
    coord.last_expected_setpoint = {"living_room": 20.0}
    state = MagicMock()
    state.state = "heat"
    state.attributes = {"temperature": 22.0}
    coord.hass.states.get = MagicMock(return_value=state)
    engine = SyncEngine(coord)

    await engine._async_act("living_room", "climate.living_room_trv2")

    coord.hass.services.async_call.assert_called_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room_trv2", "temperature": 20.0},
        blocking=True,
    )
    coord.set_room_state.assert_not_called()


# ── B18 Fase 3: rebuild_entity_map() — group toggle changes at runtime ───────


def test_rebuild_entity_map_drops_a_now_ungrouped_trv():
    """coordinator.set_room_group_enabled() calls this after get_room_trvs()
    starts narrowing to just the primary TRV — the secondary's entities
    must disappear from the map (and stop being listened to) without a
    reload."""
    room = _multi_trv_room(
        trvs=[
            {"climate_entity": "climate.living_room", "sync_mode": SYNC_MODE_MIRROR},
            {
                "climate_entity": "climate.living_room_trv2",
                "sync_mode": SYNC_MODE_MIRROR,
            },
        ]
    )
    coord = _make_coordinator(rooms=[room])
    engine = SyncEngine(coord)
    assert "climate.living_room_trv2" in engine._entity_to_room

    # Simulate the toggle switching off: get_room_trvs() now narrows to
    # just the primary TRV, same as coordinator.get_room_trvs() would.
    coord.get_room_trvs = MagicMock(
        side_effect=lambda room_name: (
            migrate_room_to_trvs(room).get(CONF_TRVS, [])[:1]
            if room_name == "living_room"
            else []
        )
    )

    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_track_state_change_event"
    ) as mock_track:
        engine.rebuild_entity_map()
        mock_track.assert_called_once()

    assert "climate.living_room" in engine._entity_to_room
    assert "climate.living_room_trv2" not in engine._entity_to_room


def test_rebuild_entity_map_unsubscribes_old_listener():
    coord = _make_coordinator(rooms=[_room()])
    engine = SyncEngine(coord)
    old_unsub = MagicMock()
    engine._unsubs = [old_unsub]

    with patch(
        "custom_components.heat_manager.engine.sync_engine.async_track_state_change_event"
    ):
        engine.rebuild_entity_map()

    old_unsub.assert_called_once()


def test_rebuild_entity_map_regrouped_trv_becomes_watched_again():
    """The reverse of the drop case — toggling back on must pick the
    secondary TRV's entities back up."""
    room = _multi_trv_room(
        trvs=[
            {"climate_entity": "climate.living_room", "sync_mode": SYNC_MODE_MIRROR},
            {
                "climate_entity": "climate.living_room_trv2",
                "sync_mode": SYNC_MODE_MIRROR,
            },
        ]
    )
    coord = _make_coordinator(rooms=[room])
    # Start "ungrouped" — only the primary TRV in the map.
    coord.get_room_trvs = MagicMock(
        side_effect=lambda room_name: (
            migrate_room_to_trvs(room).get(CONF_TRVS, [])[:1]
            if room_name == "living_room"
            else []
        )
    )
    engine = SyncEngine(coord)
    assert "climate.living_room_trv2" not in engine._entity_to_room

    # Toggle back on: get_room_trvs() returns every TRV again.
    coord.get_room_trvs = MagicMock(
        side_effect=lambda room_name: (
            migrate_room_to_trvs(room).get(CONF_TRVS, [])
            if room_name == "living_room"
            else []
        )
    )
    engine.rebuild_entity_map()

    assert "climate.living_room_trv2" in engine._entity_to_room


@pytest.mark.asyncio
async def test_stale_pending_confirm_after_rebuild_is_a_noop():
    """A confirm callback scheduled for a TRV that a rebuild just dropped
    from the map must not raise or act — _async_act() re-looks-up the TRV
    and finds nothing."""
    room = _multi_trv_room(
        trvs=[
            {"climate_entity": "climate.living_room", "sync_mode": SYNC_MODE_MIRROR},
            {
                "climate_entity": "climate.living_room_trv2",
                "sync_mode": SYNC_MODE_MIRROR,
            },
        ]
    )
    coord = _make_coordinator(rooms=[room])
    coord.last_expected_setpoint = {"living_room": 20.0}
    engine = SyncEngine(coord)

    coord.get_room_trvs = MagicMock(
        side_effect=lambda room_name: (
            migrate_room_to_trvs(room).get(CONF_TRVS, [])[:1]
            if room_name == "living_room"
            else []
        )
    )
    engine.rebuild_entity_map()

    await engine._async_act("living_room", "climate.living_room_trv2")  # must not raise

    coord.hass.services.async_call.assert_not_called()
    coord.set_room_state.assert_not_called()
