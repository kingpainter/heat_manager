"""Tests for switch.py — RoomOverrideSwitch.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import RoomState
from custom_components.heat_manager.switch import RoomOverrideSwitch

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.set_room_state = MagicMock()
    coord.get_write_entity = MagicMock(return_value=None)
    coord.log_event = MagicMock()
    coord.rooms = []

    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    coord.hass = hass

    coord.room_device_info = MagicMock(return_value={"identifiers": {("x", "z")}})
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


def _room(name="Bathroom", climate="climate.bathroom", trv_type="netatmo") -> dict:
    return {"room_name": name, "climate_entity": climate, "trv_type": trv_type}


# ── is_on ─────────────────────────────────────────────────────────────────────


def test_is_on_true_when_room_state_is_override():
    coord = _make_coordinator()
    coord.get_room_state = MagicMock(return_value=RoomState.OVERRIDE)
    switch = RoomOverrideSwitch(coord, _entry(), _room())
    assert switch.is_on is True


def test_is_on_false_when_room_state_is_normal():
    coord = _make_coordinator()
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    switch = RoomOverrideSwitch(coord, _entry(), _room())
    assert switch.is_on is False


def test_unique_id_uses_safe_room_name():
    coord = _make_coordinator()
    switch = RoomOverrideSwitch(coord, _entry(), _room(name="Living Room"))
    assert switch.unique_id == "entry123_living_room_override"


# ── async_turn_on ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_turn_on_no_climate_id_is_noop():
    coord = _make_coordinator()
    switch = RoomOverrideSwitch(coord, _entry(), _room(climate=""))

    await switch.async_turn_on()

    coord.hass.services.async_call.assert_not_called()
    coord.set_room_state.assert_not_called()


@pytest.mark.asyncio
async def test_turn_on_zigbee_sets_hvac_mode_via_write_entity():
    coord = _make_coordinator()
    coord.rooms = [_room(name="Bathroom", trv_type="zigbee")]
    coord.get_write_entity = MagicMock(return_value="climate.bathroom_homekit")
    switch = RoomOverrideSwitch(
        coord, _entry(), _room(name="Bathroom", trv_type="zigbee")
    )

    await switch.async_turn_on()

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.bathroom_homekit", "hvac_mode": "heat"},
        blocking=True,
    )
    coord.set_room_state.assert_called_once_with("Bathroom", RoomState.OVERRIDE)
    coord.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_turn_on_netatmo_sets_preset_mode_via_climate_entity_not_write_entity():
    """Unlike the zigbee branch, netatmo writes to _climate_id directly, not
    the (possibly HomeKit) write entity — regression coverage for that
    asymmetry."""
    coord = _make_coordinator()
    coord.rooms = [_room(name="Bathroom", trv_type="netatmo")]
    coord.get_write_entity = MagicMock(return_value="climate.bathroom_homekit")
    switch = RoomOverrideSwitch(
        coord,
        _entry(),
        _room(name="Bathroom", climate="climate.bathroom", trv_type="netatmo"),
    )

    await switch.async_turn_on()

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.bathroom", "preset_mode": "schedule"},
        blocking=True,
    )
    coord.set_room_state.assert_called_once_with("Bathroom", RoomState.OVERRIDE)


@pytest.mark.asyncio
async def test_turn_on_service_failure_is_caught_and_does_not_set_override_state():
    coord = _make_coordinator()
    coord.rooms = [_room(name="Bathroom")]
    coord.hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    switch = RoomOverrideSwitch(coord, _entry(), _room(name="Bathroom"))

    await switch.async_turn_on()  # must not raise

    coord.set_room_state.assert_not_called()
    coord.log_event.assert_not_called()


@pytest.mark.asyncio
async def test_turn_on_falls_back_to_climate_id_when_no_write_entity():
    coord = _make_coordinator()
    coord.rooms = [_room(name="Bathroom", trv_type="zigbee")]
    coord.get_write_entity = MagicMock(return_value=None)
    switch = RoomOverrideSwitch(
        coord, _entry(), _room(name="Bathroom", trv_type="zigbee")
    )

    await switch.async_turn_on()

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.bathroom", "hvac_mode": "heat"},
        blocking=True,
    )


# ── async_turn_off ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_turn_off_resets_room_state_and_logs():
    coord = _make_coordinator()
    switch = RoomOverrideSwitch(coord, _entry(), _room(name="Bathroom"))

    await switch.async_turn_off()

    coord.set_room_state.assert_called_once_with("Bathroom", RoomState.NORMAL)
    coord.log_event.assert_called_once()
    coord.hass.services.async_call.assert_not_called()
