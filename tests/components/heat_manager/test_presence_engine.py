"""Tests for engine/presence_engine.py — B4 regression + core behaviour."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch
import asyncio

import pytest

from custom_components.heat_manager.const import (
    ControllerState,
    RoomState,
    SeasonMode,
)
from custom_components.heat_manager.engine.presence_engine import PresenceEngine


# ── Coordinator factory ───────────────────────────────────────────────────────

def _make_coordinator(
    persons=None,
    rooms=None,
    someone_home=False,
    any_window_open=False,
    alarm_panel=None,
    config=None,
):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.hass.services.async_call = AsyncMock()
    coordinator.hass.states.get = MagicMock(return_value=None)

    coordinator.persons = persons or []
    coordinator.rooms = rooms or []
    coordinator.alarm_panel = alarm_panel
    coordinator.config = config or {
        "notify_service": "",
        "notify_presence": False,
        "grace_day_min": 30,
        "grace_night_min": 15,
        "night_start_hour": 23,
        "night_end_hour": 7,
    }

    coordinator.someone_home = MagicMock(return_value=someone_home)
    coordinator.any_window_open = MagicMock(return_value=any_window_open)
    coordinator.get_away_temperature = MagicMock(return_value=17.0)
    coordinator.get_climate_entity = MagicMock(return_value="climate.kitchen")
    coordinator.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coordinator.set_room_state = MagicMock()
    coordinator.async_update_listeners = MagicMock()

    coordinator.controller = MagicMock()
    coordinator.controller.state = ControllerState.ON

    return coordinator


def _make_person(entity_id="person.flemming", tracking=True):
    return {"person_entity": entity_id, "person_tracking": tracking}


def _make_room(name="Kitchen", climate="climate.kitchen"):
    return {"room_name": name, "climate_entity": climate, "window_sensors": []}


# ── Arrival: windows closed → schedule restored ───────────────────────────────

@pytest.mark.asyncio
async def test_arrival_with_windows_closed_restores_schedule():
    coordinator = _make_coordinator(
        persons=[_make_person()],
        rooms=[_make_room()],
        someone_home=True,
        any_window_open=False,
    )
    engine = PresenceEngine(coordinator)

    await engine._handle_arrival()

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.kitchen", "preset_mode": "schedule"},
        blocking=True,
    )
    coordinator.set_room_state.assert_called_once_with("Kitchen", RoomState.NORMAL)


# ── Arrival: windows open → notify, no schedule restore ──────────────────────

@pytest.mark.asyncio
async def test_arrival_with_windows_open_does_not_restore_schedule():
    coordinator = _make_coordinator(
        persons=[_make_person()],
        rooms=[_make_room()],
        someone_home=True,
        any_window_open=True,
        config={
            "notify_service": "notify.test",
            "notify_presence": True,
            "grace_day_min": 30,
            "grace_night_min": 15,
            "night_start_hour": 23,
            "night_end_hour": 7,
        },
    )
    engine = PresenceEngine(coordinator)

    await engine._handle_arrival()

    # Climate service should NOT have been called
    coordinator.hass.services.async_call.assert_not_awaited()


# ── Departure: everyone left → grace timer starts ────────────────────────────

@pytest.mark.asyncio
async def test_departure_starts_grace_timer_when_nobody_home():
    coordinator = _make_coordinator(
        persons=[_make_person()],
        rooms=[_make_room()],
        someone_home=False,
    )
    engine = PresenceEngine(coordinator)

    await engine._handle_departure()

    assert engine._all_left_at is not None
    assert engine._grace_timer_task is not None
    engine._cancel_grace_timer()


# ── Departure: someone still home → no timer ─────────────────────────────────

@pytest.mark.asyncio
async def test_departure_does_not_start_timer_if_someone_home():
    coordinator = _make_coordinator(
        persons=[_make_person()],
        someone_home=True,
    )
    engine = PresenceEngine(coordinator)

    await engine._handle_departure()

    assert engine._all_left_at is None
    assert engine._grace_timer_task is None


# ── Away: correct preset called on all rooms ──────────────────────────────────

@pytest.mark.asyncio
async def test_set_all_away_calls_preset_on_all_rooms():
    rooms = [
        _make_room("Kitchen", "climate.kitchen"),
        _make_room("Living room", "climate.living_room"),
    ]
    coordinator = _make_coordinator(rooms=rooms)

    state_mock = MagicMock()
    state_mock.attributes = {"preset_mode": "schedule"}
    coordinator.hass.states.get = MagicMock(return_value=state_mock)

    engine = PresenceEngine(coordinator)
    await engine._set_all_away()

    assert coordinator.hass.services.async_call.await_count == 2


# ── restore_all_schedule: skips WINDOW_OPEN rooms ────────────────────────────

@pytest.mark.asyncio
async def test_restore_all_schedule_skips_window_open_rooms():
    rooms = [
        _make_room("Kitchen", "climate.kitchen"),
        _make_room("Lukas", "climate.lukas"),
    ]
    coordinator = _make_coordinator(rooms=rooms)

    def get_room_state(name):
        if name == "Lukas":
            return RoomState.WINDOW_OPEN
        return RoomState.AWAY

    coordinator.get_room_state = MagicMock(side_effect=get_room_state)

    engine = PresenceEngine(coordinator)
    await engine._restore_all_schedule()

    # Only Kitchen should have been restored — Lukas is WINDOW_OPEN
    calls = coordinator.hass.services.async_call.await_args_list
    entity_ids = [c.args[2]["entity_id"] for c in calls]
    assert "climate.kitchen" in entity_ids
    assert "climate.lukas" not in entity_ids


# ── Bug B4: alarm disarmed → re-evaluates presence ───────────────────────────

@pytest.mark.asyncio
async def test_bug_b4_alarm_disarmed_restores_heating_when_someone_home():
    """
    Regression test for B4.
    Old behaviour: alarm disarm had no handler — heating stayed off forever.
    New behaviour: disarm re-evaluates presence and restores if someone is home.
    """
    coordinator = _make_coordinator(
        rooms=[_make_room()],
        someone_home=True,
        any_window_open=False,
        alarm_panel="alarm_control_panel.alarmo",
    )
    engine = PresenceEngine(coordinator)

    # Simulate alarm disarmed event
    new_state = MagicMock()
    new_state.state = "disarmed"
    event = MagicMock()
    event.data = {
        "entity_id": "alarm_control_panel.alarmo",
        "new_state": new_state,
        "old_state": MagicMock(state="armed_away"),
    }

    await engine._async_handle_alarm_change(event)

    # Heating should have been restored to schedule
    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.kitchen", "preset_mode": "schedule"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_bug_b4_alarm_disarmed_does_nothing_when_nobody_home():
    """
    B4 edge case: alarm disarms but nobody is actually home yet.
    Heating should NOT be restored.
    """
    coordinator = _make_coordinator(
        rooms=[_make_room()],
        someone_home=False,
        alarm_panel="alarm_control_panel.alarmo",
    )
    engine = PresenceEngine(coordinator)

    new_state = MagicMock()
    new_state.state = "disarmed"
    event = MagicMock()
    event.data = {
        "entity_id": "alarm_control_panel.alarmo",
        "new_state": new_state,
        "old_state": MagicMock(state="armed_away"),
    }

    await engine._async_handle_alarm_change(event)

    coordinator.hass.services.async_call.assert_not_awaited()


# ── force_room_on service ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_room_on_sets_schedule():
    coordinator = _make_coordinator(rooms=[_make_room()])
    coordinator.any_window_open = MagicMock(return_value=False)
    engine = PresenceEngine(coordinator)

    await engine.force_room_on("Kitchen")

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.kitchen", "preset_mode": "schedule"},
        blocking=True,
    )
    coordinator.set_room_state.assert_called_once_with("Kitchen", RoomState.NORMAL)


@pytest.mark.asyncio
async def test_force_room_on_unknown_room_logs_warning():
    coordinator = _make_coordinator()
    coordinator.get_climate_entity = MagicMock(return_value=None)
    engine = PresenceEngine(coordinator)

    # Should not raise — just log a warning
    await engine.force_room_on("NonExistentRoom")

    coordinator.hass.services.async_call.assert_not_awaited()


# ── Grace period day/night selection ─────────────────────────────────────────

def test_grace_period_returns_night_value_during_night_hours():
    coordinator = _make_coordinator(config={
        "grace_day_min": 30,
        "grace_night_min": 15,
        "night_start_hour": 23,
        "night_end_hour": 7,
        "notify_service": "",
    })
    engine = PresenceEngine(coordinator)

    with patch(
        "custom_components.heat_manager.engine.presence_engine.utcnow"
    ) as mock_now:
        mock_now.return_value.hour = 2  # 02:00 — night
        result = engine._grace_period_minutes()

    assert result == 15


def test_grace_period_returns_day_value_during_day_hours():
    coordinator = _make_coordinator(config={
        "grace_day_min": 30,
        "grace_night_min": 15,
        "night_start_hour": 23,
        "night_end_hour": 7,
        "notify_service": "",
    })
    engine = PresenceEngine(coordinator)

    with patch(
        "custom_components.heat_manager.engine.presence_engine.utcnow"
    ) as mock_now:
        mock_now.return_value.hour = 14  # 14:00 — day
        result = engine._grace_period_minutes()

    assert result == 30


# ── Guarded: blocked when OFF ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_all_away_blocked_when_controller_off():
    coordinator = _make_coordinator(rooms=[_make_room()])
    coordinator.controller.state = ControllerState.OFF
    engine = PresenceEngine(coordinator)

    await engine._set_all_away()

    coordinator.hass.services.async_call.assert_not_awaited()
