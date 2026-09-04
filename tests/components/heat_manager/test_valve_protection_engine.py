"""Tests for engine/valve_protection_engine.py — weekly valve exercise,
including B18 multi-TRV grouping (every physical TRV in a room is
exercised individually)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import CONF_TRVS, ControllerState
from custom_components.heat_manager.engine.valve_protection_engine import (
    EXERCISE_SETPOINT_C,
    ValveProtectionEngine,
)
from custom_components.heat_manager.migrations import migrate_room_to_trvs


def _make_coordinator(rooms=None):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.hass.services.async_call = AsyncMock()
    coordinator.rooms = rooms or []
    coordinator.config = {"notify_service": ""}
    coordinator.controller = MagicMock()
    coordinator.controller.state = ControllerState.OFF
    coordinator.log_event = MagicMock()

    def _room_trvs(room_name):
        room = next(
            (r for r in coordinator.rooms if r.get("room_name") == room_name), None
        )
        if room is None:
            return []
        return migrate_room_to_trvs(room).get(CONF_TRVS, [])

    coordinator.get_room_trvs = MagicMock(side_effect=_room_trvs)
    return coordinator


def _make_room(name="Kitchen", climate="climate.kitchen"):
    return {"room_name": name, "climate_entity": climate}


def _state(temperature, status="heat"):
    s = MagicMock()
    s.state = status
    s.attributes = {"temperature": temperature}
    return s


@pytest.mark.asyncio
async def test_single_trv_room_exercises_and_restores():
    rooms = [_make_room()]
    coordinator = _make_coordinator(rooms=rooms)
    coordinator.hass.states.get = MagicMock(return_value=_state(19.5))
    engine = ValveProtectionEngine(coordinator)

    import custom_components.heat_manager.engine.valve_protection_engine as vpe

    orig_sleep = vpe.asyncio.sleep
    vpe.asyncio.sleep = AsyncMock()
    try:
        await engine._exercise_all_valves()
    finally:
        vpe.asyncio.sleep = orig_sleep

    calls = coordinator.hass.services.async_call.await_args_list
    assert len(calls) == 2
    assert calls[0].args[2] == {
        "entity_id": "climate.kitchen",
        "temperature": EXERCISE_SETPOINT_C,
    }
    assert calls[1].args[2] == {
        "entity_id": "climate.kitchen",
        "temperature": 19.5,
    }
    coordinator.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_room_with_unavailable_entity_is_skipped():
    rooms = [_make_room()]
    coordinator = _make_coordinator(rooms=rooms)
    unavailable = MagicMock()
    unavailable.state = "unavailable"
    coordinator.hass.states.get = MagicMock(return_value=unavailable)
    engine = ValveProtectionEngine(coordinator)

    await engine._exercise_all_valves()

    coordinator.hass.services.async_call.assert_not_awaited()
    coordinator.log_event.assert_not_called()


@pytest.mark.asyncio
async def test_multi_trv_room_exercises_every_trv_individually():
    """B18: a room with 2+ TRVs gets each physical TRV exercised on its
    own, preferring its own HomeKit entity when configured."""
    room = {
        "room_name": "Living room",
        "trvs": [
            {
                "climate_entity": "climate.living_room",
                "homekit_climate_entity": "climate.living_room_homekit",
                "trv_type": "netatmo",
            },
            {
                "climate_entity": "climate.living_room_trv2",
                "trv_type": "zigbee",
            },
        ],
    }
    coordinator = _make_coordinator(rooms=[room])

    states = {
        "climate.living_room_homekit": _state(20.0),
        "climate.living_room_trv2": _state(21.0),
    }
    coordinator.hass.states.get = MagicMock(side_effect=lambda eid: states.get(eid))
    engine = ValveProtectionEngine(coordinator)

    import custom_components.heat_manager.engine.valve_protection_engine as vpe

    orig_sleep = vpe.asyncio.sleep
    vpe.asyncio.sleep = AsyncMock()
    try:
        await engine._exercise_all_valves()
    finally:
        vpe.asyncio.sleep = orig_sleep

    calls = coordinator.hass.services.async_call.await_args_list
    # 2 calls (open + restore) per TRV = 4 total
    assert len(calls) == 4
    entity_ids = {c.args[2]["entity_id"] for c in calls}
    assert entity_ids == {"climate.living_room_homekit", "climate.living_room_trv2"}
    # Room is only logged once even though 2 TRVs were exercised.
    coordinator.log_event.assert_called_once()
    assert "Living room" in coordinator.log_event.call_args.args[0]


@pytest.mark.asyncio
async def test_multi_trv_room_second_trv_still_exercised_when_first_unavailable():
    room = {
        "room_name": "Living room",
        "trvs": [
            {"climate_entity": "climate.living_room"},
            {"climate_entity": "climate.living_room_trv2"},
        ],
    }
    coordinator = _make_coordinator(rooms=[room])

    def _get(entity_id):
        if entity_id == "climate.living_room":
            return None  # unavailable
        if entity_id == "climate.living_room_trv2":
            return _state(21.0)
        return None

    coordinator.hass.states.get = MagicMock(side_effect=_get)
    engine = ValveProtectionEngine(coordinator)

    import custom_components.heat_manager.engine.valve_protection_engine as vpe

    orig_sleep = vpe.asyncio.sleep
    vpe.asyncio.sleep = AsyncMock()
    try:
        await engine._exercise_all_valves()
    finally:
        vpe.asyncio.sleep = orig_sleep

    calls = coordinator.hass.services.async_call.await_args_list
    assert len(calls) == 2  # only the second TRV
    assert all(c.args[2]["entity_id"] == "climate.living_room_trv2" for c in calls)
    coordinator.log_event.assert_called_once()
