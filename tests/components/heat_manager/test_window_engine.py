"""Tests for engine/window_engine.py — B1, B2, B3 regression + core behaviour."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta
import asyncio

import pytest

from custom_components.heat_manager.const import (
    ControllerState,
    RoomState,
)
from custom_components.heat_manager.engine.window_engine import WindowEngine


# ── Coordinator factory ───────────────────────────────────────────────────────

def _make_coordinator(rooms=None, someone_home=True, config=None):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.hass.services.async_call = AsyncMock()

    coordinator.rooms = rooms or []
    coordinator.config = config or {
        "notify_service": "",
        "notify_windows": False,
        "window_warning_min": 30,
    }

    coordinator.someone_home = MagicMock(return_value=someone_home)
    coordinator.get_climate_entity = MagicMock(return_value="climate.kitchen")
    coordinator.set_room_state = MagicMock()
    coordinator.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coordinator.async_update_listeners = MagicMock()

    coordinator.controller = MagicMock()
    coordinator.controller.state = ControllerState.ON

    return coordinator


def _make_room(
    name="Kitchen",
    climate="climate.kitchen",
    sensors=None,
    away_temp=10.0,
    delay=5,
):
    return {
        "room_name": name,
        "climate_entity": climate,
        "window_sensors": sensors or ["binary_sensor.kitchen_window"],
        "away_temp_override": away_temp,
        "window_delay_min": delay,
    }


def _sensor_state(is_open: bool) -> MagicMock:
    state = MagicMock()
    state.state = "on" if is_open else "off"
    return state


# ── Bug B1: entity ID typo prevention ────────────────────────────────────────

def test_bug_b1_sensor_map_strips_no_leading_dots():
    """
    Regression test for B1.
    The old YAML had '.binary_sensor.lukas_vindue_contact' (leading dot).
    Entity IDs in config now come from the HA entity selector — they never
    contain a leading dot. This test verifies that the sensor map built by
    the engine stores the IDs exactly as configured, with no transformation
    that could hide a bad entity ID.
    """
    rooms = [
        _make_room(
            name="Lukas",
            sensors=["binary_sensor.lukas_vindue_contact"],
        )
    ]
    coordinator = _make_coordinator(rooms=rooms)
    engine = WindowEngine(coordinator)

    assert "binary_sensor.lukas_vindue_contact" in engine._sensor_to_room
    assert engine._sensor_to_room["binary_sensor.lukas_vindue_contact"] == "Lukas"


def test_bug_b1_leading_dot_entity_id_is_not_found_in_sensor_map():
    """
    If someone somehow passes a leading-dot entity ID, it will not match any
    real HA state and will simply not appear in sensor_to_room as a valid key.
    This verifies the engine does not silently paper over bad IDs.
    """
    rooms = [
        _make_room(
            name="Lukas",
            sensors=[".binary_sensor.lukas_vindue_contact"],  # Bad ID
        )
    ]
    coordinator = _make_coordinator(rooms=rooms)
    engine = WindowEngine(coordinator)

    # The bad ID is stored as-is — it will never match a real HA state
    assert ".binary_sensor.lukas_vindue_contact" in engine._sensor_to_room
    # The correct ID should NOT be there
    assert "binary_sensor.lukas_vindue_contact" not in engine._sensor_to_room


# ── Bug B2: 30-min warning actually fires ────────────────────────────────────

@pytest.mark.asyncio
async def test_bug_b2_warning_sent_after_30_minutes():
    """
    Regression test for B2.
    Old behaviour: 30-min trigger was defined but had no choose-branch.
    New behaviour: async_tick sends an escalation notification after threshold.
    """
    from homeassistant.util.dt import utcnow
    rooms = [_make_room()]
    coordinator = _make_coordinator(
        rooms=rooms,
        config={
            "notify_service": "notify.test",
            "notify_windows": True,
            "window_warning_min": 30,
        },
    )
    engine = WindowEngine(coordinator)

    # Simulate window has been open for 35 minutes
    from datetime import timezone
    import datetime as dt
    engine._window_opened_at["Kitchen"] = utcnow() - timedelta(minutes=35)
    engine._warning_sent["Kitchen"] = False

    await engine.async_tick()

    # Warning notification should have been sent
    coordinator.hass.services.async_call.assert_awaited_once()
    call_args = coordinator.hass.services.async_call.call_args
    assert "notify" in call_args.args[0]
    assert "35" in call_args.args[2]["message"] or "Kitchen" in call_args.args[2]["message"]
    assert engine._warning_sent["Kitchen"] is True


@pytest.mark.asyncio
async def test_bug_b2_warning_not_sent_twice():
    """B2: Warning must only be sent once per window-open event."""
    from homeassistant.util.dt import utcnow
    rooms = [_make_room()]
    coordinator = _make_coordinator(
        rooms=rooms,
        config={
            "notify_service": "notify.test",
            "notify_windows": True,
            "window_warning_min": 30,
        },
    )
    engine = WindowEngine(coordinator)
    engine._window_opened_at["Kitchen"] = utcnow() - timedelta(minutes=40)
    engine._warning_sent["Kitchen"] = True  # Already sent

    await engine.async_tick()

    # Should NOT send again
    coordinator.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_bug_b2_no_warning_before_threshold():
    """B2: No warning should fire before the 30-min threshold."""
    from homeassistant.util.dt import utcnow
    rooms = [_make_room()]
    coordinator = _make_coordinator(
        rooms=rooms,
        config={
            "notify_service": "notify.test",
            "notify_windows": True,
            "window_warning_min": 30,
        },
    )
    engine = WindowEngine(coordinator)
    engine._window_opened_at["Kitchen"] = utcnow() - timedelta(minutes=10)
    engine._warning_sent["Kitchen"] = False

    await engine.async_tick()

    coordinator.hass.services.async_call.assert_not_awaited()


# ── Bug B3: window close checks presence before restoring ────────────────────

@pytest.mark.asyncio
async def test_bug_b3_window_close_restores_schedule_when_someone_home():
    """
    Regression test for B3.
    Old behaviour: closing a window always restored to 'schedule'.
    New behaviour: restores only if someone is home.
    """
    rooms = [_make_room(sensors=["binary_sensor.kitchen_window"])]
    coordinator = _make_coordinator(rooms=rooms, someone_home=True)

    # Sensor is closed
    coordinator.hass.states.get = MagicMock(
        return_value=_sensor_state(is_open=False)
    )

    engine = WindowEngine(coordinator)
    engine._window_opened_at["Kitchen"] = MagicMock()
    engine._warning_sent["Kitchen"] = False

    await engine._close_after_delay("binary_sensor.kitchen_window", "Kitchen", 0)

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.kitchen", "preset_mode": "schedule"},
        blocking=True,
    )
    coordinator.set_room_state.assert_called_once_with("Kitchen", RoomState.NORMAL)


@pytest.mark.asyncio
async def test_bug_b3_window_close_leaves_away_when_nobody_home():
    """
    B3 FIX: If nobody is home when the window closes, the room must
    stay in AWAY state — not be restored to schedule.
    """
    rooms = [_make_room(sensors=["binary_sensor.kitchen_window"])]
    coordinator = _make_coordinator(rooms=rooms, someone_home=False)

    coordinator.hass.states.get = MagicMock(
        return_value=_sensor_state(is_open=False)
    )

    engine = WindowEngine(coordinator)
    engine._window_opened_at["Kitchen"] = MagicMock()

    await engine._close_after_delay("binary_sensor.kitchen_window", "Kitchen", 0)

    # Climate service must NOT be called
    coordinator.hass.services.async_call.assert_not_awaited()
    # Room state should be set to AWAY, not NORMAL
    coordinator.set_room_state.assert_called_once_with("Kitchen", RoomState.AWAY)


# ── Window open: sets temperature ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_after_delay_sets_away_temperature():
    rooms = [_make_room(away_temp=10.0)]
    coordinator = _make_coordinator(rooms=rooms)

    sensor_state = MagicMock()
    sensor_state.state = "on"
    coordinator.hass.states.get = MagicMock(return_value=sensor_state)

    engine = WindowEngine(coordinator)

    await engine._open_after_delay(
        "binary_sensor.kitchen_window", "Kitchen", 0
    )

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.kitchen", "temperature": 10.0},
        blocking=True,
    )
    coordinator.set_room_state.assert_called_once_with("Kitchen", RoomState.WINDOW_OPEN)


@pytest.mark.asyncio
async def test_open_aborts_if_sensor_already_closed():
    """If the sensor closed during the delay, no action should be taken."""
    rooms = [_make_room()]
    coordinator = _make_coordinator(rooms=rooms)
    coordinator.hass.states.get = MagicMock(
        return_value=_sensor_state(is_open=False)
    )

    engine = WindowEngine(coordinator)
    await engine._open_after_delay("binary_sensor.kitchen_window", "Kitchen", 0)

    coordinator.hass.services.async_call.assert_not_awaited()


# ── get_open_windows ──────────────────────────────────────────────────────────

def test_get_open_windows_returns_only_open_rooms():
    rooms = [
        _make_room("Kitchen", sensors=["binary_sensor.kitchen_window"]),
        _make_room("Lukas", climate="climate.lukas", sensors=["binary_sensor.lukas_window"]),
    ]
    coordinator = _make_coordinator(rooms=rooms)

    def state_for(entity_id):
        if entity_id == "binary_sensor.lukas_window":
            return _sensor_state(is_open=True)
        return _sensor_state(is_open=False)

    coordinator.hass.states.get = MagicMock(side_effect=state_for)

    engine = WindowEngine(coordinator)
    result = engine.get_open_windows()

    assert result == ["Lukas"]
    assert "Kitchen" not in result


# ── Guarded: blocked when OFF ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_after_delay_blocked_when_controller_off():
    rooms = [_make_room()]
    coordinator = _make_coordinator(rooms=rooms)
    coordinator.controller.state = ControllerState.OFF

    sensor_state = MagicMock()
    sensor_state.state = "on"
    coordinator.hass.states.get = MagicMock(return_value=sensor_state)

    engine = WindowEngine(coordinator)
    await engine._open_after_delay("binary_sensor.kitchen_window", "Kitchen", 0)

    coordinator.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_after_delay_blocked_when_controller_paused():
    rooms = [_make_room()]
    coordinator = _make_coordinator(rooms=rooms)
    coordinator.controller.state = ControllerState.PAUSE

    coordinator.hass.states.get = MagicMock(
        return_value=_sensor_state(is_open=False)
    )

    engine = WindowEngine(coordinator)
    await engine._close_after_delay("binary_sensor.kitchen_window", "Kitchen", 0)

    coordinator.hass.services.async_call.assert_not_awaited()
