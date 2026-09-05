"""Tests for CalibrationEngine (v0.9.0).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util.dt import utcnow

from custom_components.heat_manager.const import (
    CALIBRATION_OFFSET_MAX,
    CALIBRATION_OFFSET_MIN,
    DEFAULT_CALIBRATION_HEARTBEAT_MIN,
)
from custom_components.heat_manager.engine.calibration_engine import CalibrationEngine


def _make_coordinator(rooms=None) -> MagicMock:
    coord = MagicMock()
    coord.rooms = rooms or []
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    coord.hass = hass
    return coord


def _room(
    name: str = "bathroom",
    climate: str = "climate.bathroom",
    room_temp_sensor: str = "sensor.bathroom_temp",
    calibration_entity: str = "number.bathroom_trv_local_temperature_calibration",
) -> dict:
    room: dict = {"room_name": name, "climate_entity": climate}
    if room_temp_sensor:
        room["room_temp_sensor"] = room_temp_sensor
    if calibration_entity:
        room["calibration_entity"] = calibration_entity
    return room


def _state(value, attrs=None):
    s = MagicMock()
    s.state = value
    s.attributes = attrs or {}
    return s


def _states_get(truth: float, raw: float):
    """Return a hass.states.get side_effect keyed off entity_id substrings."""

    def _get(entity_id: str):
        if "sensor.bathroom_temp" in entity_id:
            return _state(str(truth))
        if entity_id == "climate.bathroom":
            return _state("heat", {"current_temperature": raw})
        return None

    return _get


def _states_get_with_calibration(truth: float, raw: float, calibration: float):
    """Like _states_get, but also simulates the calibration_entity's own
    live state — i.e. the device having echoed back a value Heat Manager
    (or something else) previously wrote to it."""

    def _get(entity_id: str):
        if "sensor.bathroom_temp" in entity_id:
            return _state(str(truth))
        if entity_id == "climate.bathroom":
            return _state("heat", {"current_temperature": raw})
        if entity_id == "number.bathroom_trv_local_temperature_calibration":
            return _state(str(calibration))
        return None

    return _get


# ── opt-in gating ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_room_without_calibration_entity_is_skipped():
    coord = _make_coordinator(rooms=[_room(calibration_entity=None)])
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_room_without_room_temp_sensor_is_skipped():
    coord = _make_coordinator(rooms=[_room(room_temp_sensor=None)])
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_room_without_room_name_is_skipped():
    coord = _make_coordinator(rooms=[{"climate_entity": "climate.x"}])
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


# ── happy path: first write ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_tick_writes_offset():
    """truth=21.0, raw=20.0 → offset=+1.0 written on first tick (no history)."""
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][0] == "number"
    assert call_args[0][1] == "set_value"
    assert (
        call_args[0][2]["entity_id"]
        == "number.bathroom_trv_local_temperature_calibration"
    )
    assert call_args[0][2]["value"] == pytest.approx(1.0)
    assert engine._last_written["bathroom"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_offset_is_clamped_to_max():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=50.0, raw=0.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["value"] == pytest.approx(CALIBRATION_OFFSET_MAX)


@pytest.mark.asyncio
async def test_offset_is_clamped_to_min():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=0.0, raw=50.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["value"] == pytest.approx(CALIBRATION_OFFSET_MIN)


# ── missing / unavailable data ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_room_temp_sensor_state_skips_write():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(return_value=None)
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_unavailable_room_temp_sensor_skips_write():
    def _get(entity_id):
        if "sensor.bathroom_temp" in entity_id:
            return _state("unavailable")
        return _state("heat", {"current_temperature": 20.0})

    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_climate_entity_missing_current_temperature_skips_write():
    def _get(entity_id):
        if "sensor.bathroom_temp" in entity_id:
            return _state("21.0")
        if entity_id == "climate.bathroom":
            return _state("heat", {})
        return None

    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


# ── feedback-loop correctness (regression) ──────────────────────────────────
# The TRV's own current_temperature already reflects whatever calibration is
# currently applied by the device firmware — this is what
# _read_trv_raw_temperature's docstring calls out. These tests simulate that
# real device behaviour (unlike the fixed-`raw` tests above) to prove the
# engine doesn't oscillate the written value every tick.


@pytest.mark.asyncio
async def test_device_echo_of_previous_write_does_not_undo_it():
    """v0.9.1 bug: computing the write as an absolute (truth - raw) each
    tick, once the device's current_temperature already includes the
    correction, would compute a ~0 residual and write 0.0 — undoing the
    correction it just made. The fix reads the calibration entity's own
    current value and adds the residual on top, so a settled room makes no
    further writes."""
    coord = _make_coordinator(rooms=[_room()])
    # Tick 1: uncorrected raw=20.0, truth=21.0 → writes offset=+1.0.
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    assert engine._last_written["bathroom"] == pytest.approx(1.0)
    coord.hass.services.async_call.reset_mock()

    # Tick 2: the device has now applied +1.0°C internally, so its own
    # current_temperature reads 21.0 (matches truth), and the calibration
    # entity itself echoes back the 1.0 that was written.
    coord.hass.states.get = MagicMock(
        side_effect=_states_get_with_calibration(truth=21.0, raw=21.0, calibration=1.0)
    )
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_residual_error_is_added_on_top_of_devices_own_current_value():
    """Room drifts further after a correction was already applied — the new
    write must be current(1.0) + residual(0.5) = 1.5, not just the raw
    residual on its own."""
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(
        side_effect=_states_get_with_calibration(truth=21.5, raw=21.0, calibration=1.0)
    )
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["value"] == pytest.approx(1.5)


# ── de-duplication / heartbeat behaviour ────────────────────────────────────


@pytest.mark.asyncio
async def test_second_tick_no_change_no_heartbeat_due_skips_write():
    """Same offset again, well within the heartbeat window → no re-write."""
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.reset_mock()
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_change_above_threshold_triggers_rewrite():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.reset_mock()

    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=22.0, raw=20.0))
    await engine.async_tick()
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["value"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_change_below_threshold_does_not_trigger_rewrite():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.reset_mock()

    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.05, raw=20.0))
    await engine.async_tick()
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_forces_rewrite_after_timeout_even_without_change():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    engine = CalibrationEngine(coord)
    await engine.async_tick()
    coord.hass.services.async_call.reset_mock()

    # Simulate the heartbeat window having elapsed.
    engine._last_write_time["bathroom"] = utcnow() - timedelta(
        minutes=DEFAULT_CALIBRATION_HEARTBEAT_MIN + 1
    )
    await engine.async_tick()
    coord.hass.services.async_call.assert_called_once()


# ── error handling ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_call_failure_is_caught_and_logged():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(side_effect=_states_get(truth=21.0, raw=20.0))
    coord.hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    engine = CalibrationEngine(coord)
    await engine.async_tick()  # must not raise
    assert "bathroom" not in engine._last_written


# ── shutdown ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shutdown_is_noop():
    coord = _make_coordinator()
    engine = CalibrationEngine(coord)
    await engine.async_shutdown()  # must not raise
