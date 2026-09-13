"""Tests for window_engine.py's v0.33.0 global-settings split.

Two behavioural changes, both requested after Flemming pointed out that
away_temp_override was silently doing double duty — flooring the PID's own
idle output/night-setback AND being reused as the window-open write value,
so setting it to a "comfortable away temp" (e.g. 18C) would also raise the
PID's minimum floor everywhere, not just on window-open:

  - _get_open_delay() now reads ONE global CONF_WINDOW_DELAY_DEFAULT_MIN
    setting instead of the old per-room CONF_WINDOW_DELAY_MIN (which lived
    only in the config-flow room step and was never exposed anywhere the
    user actually looks).
  - The window-open write ("heat is off") now uses a dedicated global
    CONF_WINDOW_OFF_TEMP, completely independent of CONF_AWAY_TEMP_OVERRIDE.

All tests run completely offline — HA core is mocked with MagicMock/
AsyncMock, same minimal-coordinator pattern as
test_coordinator_mold_risk_notification.py. WindowEngine methods are called
directly against a bare MagicMock standing in for `self`, rather than
instantiating a real WindowEngine, since __init__ registers real HA
state-change listeners this suite has no need to exercise.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import (
    CONF_AWAY_TEMP_OVERRIDE,
    CONF_NOTIFY_WINDOWS,
    CONF_WINDOW_DELAY_DEFAULT_MIN,
    CONF_WINDOW_OFF_TEMP,
    DEFAULT_WINDOW_DELAY_DEFAULT_MIN,
    DEFAULT_WINDOW_DELAY_WIND_MIN,
    DEFAULT_WINDOW_OFF_TEMP,
    ControllerState,
    RoomState,
)
from custom_components.heat_manager.engine.window_engine import WindowEngine

_get_open_delay = WindowEngine._get_open_delay
# _open_after_delay is @guarded — passing a coordinator whose
# controller.state is ControllerState.ON lets the guard through normally,
# no need to reach through __wrapped__.
_open_after_delay = WindowEngine._open_after_delay


def _fake_engine(config: dict | None = None) -> MagicMock:
    """Bare stand-in for a WindowEngine instance. Only .coordinator is a
    real, configured mock — every other attribute (self._window_opened_at,
    self._warning_sent, self._notify, self._co2_context_label, ...)
    auto-mocks harmlessly via MagicMock, since none of it is asserted on by
    these tests."""
    coord = MagicMock()
    coord.config = config if config is not None else {}
    coord.controller.state = ControllerState.ON
    coord.get_wind_speed = MagicMock(return_value=0.0)
    coord.is_raining = MagicMock(return_value=False)
    coord.hass.states.get = MagicMock(return_value=MagicMock(state="on"))
    coord.hass.services.async_call = AsyncMock()
    coord.get_climate_entity = MagicMock(return_value="climate.test_room")
    coord.get_room_write_entities = MagicMock(return_value=["climate.test_room"])
    coord.get_write_entity = MagicMock(return_value=None)
    coord.get_pid = MagicMock(return_value=None)
    coord.get_room_co2 = MagicMock(return_value=None)
    coord.set_room_state = MagicMock()
    coord.log_event = MagicMock()

    engine = MagicMock()
    engine.coordinator = coord
    return engine


# ── _get_open_delay(): one global setting, no more per-room lookup ─────────


def test_open_delay_reads_global_default_when_configured():
    engine = _fake_engine({CONF_WINDOW_DELAY_DEFAULT_MIN: 12})
    assert _get_open_delay(engine, "binary_sensor.x") == 12


def test_open_delay_falls_back_to_default_when_unset():
    engine = _fake_engine({})
    assert _get_open_delay(engine, "binary_sensor.x") == DEFAULT_WINDOW_DELAY_DEFAULT_MIN


def test_open_delay_ignores_per_room_config_entirely():
    """A room's own (now-vestigial) window_delay_min must have zero effect
    — _get_open_delay() no longer even looks at coordinator.rooms."""
    engine = _fake_engine({CONF_WINDOW_DELAY_DEFAULT_MIN: 7})
    engine.coordinator.rooms = [{"room_name": "Bathroom", "window_delay_min": 99}]
    assert _get_open_delay(engine, "binary_sensor.x") == 7


def test_open_delay_reduced_on_fast_wind():
    engine = _fake_engine({CONF_WINDOW_DELAY_DEFAULT_MIN: 20})
    engine.coordinator.get_wind_speed = MagicMock(return_value=8.0)  # >= WIND_FAST_MS
    assert _get_open_delay(engine, "binary_sensor.x") == DEFAULT_WINDOW_DELAY_WIND_MIN


def test_open_delay_reduced_when_raining():
    engine = _fake_engine({CONF_WINDOW_DELAY_DEFAULT_MIN: 20})
    engine.coordinator.is_raining = MagicMock(return_value=True)
    assert _get_open_delay(engine, "binary_sensor.x") == DEFAULT_WINDOW_DELAY_WIND_MIN


# ── _open_after_delay(): dedicated off-temp, decoupled from away_temp ──────


@pytest.mark.asyncio
async def test_window_open_writes_global_off_temp():
    engine = _fake_engine(
        {CONF_WINDOW_OFF_TEMP: 8.0, CONF_NOTIFY_WINDOWS: False}
    )
    await _open_after_delay(engine, "binary_sensor.x", "Bathroom", 0)

    args, kwargs = engine.coordinator.hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["temperature"] == 8.0
    engine.coordinator.set_room_state.assert_called_once_with(
        "Bathroom", RoomState.WINDOW_OPEN
    )


@pytest.mark.asyncio
async def test_window_open_ignores_away_temp_override():
    """The core bug being fixed: a room's away_temp_override (here 18C,
    deliberately different from window_off_temp) must have NO effect on
    what's written when a window opens."""
    engine = _fake_engine(
        {
            CONF_WINDOW_OFF_TEMP: 8.0,
            CONF_AWAY_TEMP_OVERRIDE: 18.0,  # must be ignored by this path
            CONF_NOTIFY_WINDOWS: False,
        }
    )
    engine.coordinator.rooms = [
        {"room_name": "Bathroom", CONF_AWAY_TEMP_OVERRIDE: 18.0}
    ]
    await _open_after_delay(engine, "binary_sensor.x", "Bathroom", 0)

    call_args, _ = engine.coordinator.hass.services.async_call.call_args
    assert call_args[2]["temperature"] == 8.0
    assert call_args[2]["temperature"] != 18.0


@pytest.mark.asyncio
async def test_window_open_falls_back_to_default_off_temp_when_unset():
    engine = _fake_engine({CONF_NOTIFY_WINDOWS: False})
    await _open_after_delay(engine, "binary_sensor.x", "Bathroom", 0)

    call_args, _ = engine.coordinator.hass.services.async_call.call_args
    assert call_args[2]["temperature"] == DEFAULT_WINDOW_OFF_TEMP


@pytest.mark.asyncio
async def test_window_open_off_temp_independent_of_pid_state():
    """Before v0.33.0 this path routed through PidController.power_to_setpoint,
    gated on coordinator.pid_enabled — that branch is gone; the write value
    must be identical whether pid_enabled would have been True or False."""
    engine = _fake_engine({CONF_WINDOW_OFF_TEMP: 9.5, CONF_NOTIFY_WINDOWS: False})
    engine.coordinator.pid_enabled = False

    await _open_after_delay(engine, "binary_sensor.x", "Bathroom", 0)

    call_args, _ = engine.coordinator.hass.services.async_call.call_args
    assert call_args[2]["temperature"] == 9.5


@pytest.mark.asyncio
async def test_window_closed_sensor_state_aborts_before_any_write():
    engine = _fake_engine({CONF_WINDOW_OFF_TEMP: 8.0})
    engine.coordinator.hass.states.get = MagicMock(return_value=MagicMock(state="off"))

    await _open_after_delay(engine, "binary_sensor.x", "Bathroom", 0)

    engine.coordinator.hass.services.async_call.assert_not_called()
