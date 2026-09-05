"""Tests for switch.py — RoomOverrideSwitch and RoomGroupToggleSwitch (B18
Fase 3).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import CONF_TRVS, RoomState
from custom_components.heat_manager.migrations import migrate_room_to_trvs
from custom_components.heat_manager.switch import (
    RoomGroupToggleSwitch,
    RoomOverrideSwitch,
    async_setup_entry,
)

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.set_room_state = MagicMock()
    # B18: async_turn_on() now resolves the write entity per-TRV via
    # get_trv_write_entity(trv) instead of the room-level get_write_entity().
    coord.get_trv_write_entity = MagicMock(return_value=None)
    coord.log_event = MagicMock()
    coord.rooms = []

    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    coord.hass = hass

    coord.room_device_info = MagicMock(return_value={"identifiers": {("x", "z")}})

    # B18: async_turn_on() now fans out over get_room_trvs() instead of
    # reading the room dict directly. Default to the flat-mirror migration
    # the real coordinator uses at read time, so every existing single-TRV
    # test (built with _room()'s flat fields) keeps sending to exactly the
    # same entity as before.
    def _room_trvs(room_name):
        room = next((r for r in coord.rooms if r.get("room_name") == room_name), None)
        if room is None:
            return []
        return migrate_room_to_trvs(room).get(CONF_TRVS, [])

    coord.get_room_trvs = MagicMock(side_effect=_room_trvs)
    # B18 Fase 3: async_setup_entry() decides whether to create a
    # RoomGroupToggleSwitch from the structural (toggle-ignoring) TRV
    # count, and the switch itself reads/writes room_group_enabled.
    coord.get_all_room_trvs = MagicMock(side_effect=_room_trvs)
    coord.room_group_enabled = {}
    coord.set_room_group_enabled = MagicMock(
        side_effect=lambda room_name, enabled: coord.room_group_enabled.__setitem__(
            room_name, enabled
        )
    )

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
    coord.get_trv_write_entity = MagicMock(return_value="climate.bathroom_homekit")
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
    coord.get_trv_write_entity = MagicMock(return_value="climate.bathroom_homekit")
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
    coord.get_trv_write_entity = MagicMock(return_value=None)
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


# ── B18: multi-TRV grouping — each TRV keeps its own branch's policy ─────────


@pytest.mark.asyncio
async def test_turn_on_multi_trv_room_sends_to_every_trv_with_own_policy():
    """Two TRVs in one room, mixed types — each keeps its own branch's
    existing (asymmetric) entity-selection policy: netatmo → raw
    climate_entity, zigbee → write entity (HomeKit if reachable)."""
    coord = _make_coordinator()
    coord.rooms = [
        {
            "room_name": "Living room",
            "trvs": [
                {
                    "climate_entity": "climate.living_room",
                    "trv_type": "netatmo",
                },
                {
                    "climate_entity": "climate.living_room_trv2",
                    "trv_type": "zigbee",
                },
            ],
        }
    ]
    coord.get_trv_write_entity = MagicMock(
        side_effect=lambda trv: trv.get("climate_entity")
    )
    switch = RoomOverrideSwitch(coord, _entry(), _room(name="Living room"))

    await switch.async_turn_on()

    calls = coord.hass.services.async_call.await_args_list
    assert len(calls) == 2
    by_entity = {c.args[2]["entity_id"]: c for c in calls}
    assert by_entity["climate.living_room"].args[1] == "set_preset_mode"
    assert by_entity["climate.living_room_trv2"].args[1] == "set_hvac_mode"
    coord.set_room_state.assert_called_once_with("Living room", RoomState.OVERRIDE)


# ── RoomGroupToggleSwitch (B18 Fase 3) ────────────────────────────────────────


def test_group_toggle_is_on_true_by_default():
    coord = _make_coordinator()
    switch = RoomGroupToggleSwitch(coord, _entry(), "Living room")
    assert switch.is_on is True


def test_group_toggle_is_on_reflects_coordinator_state():
    coord = _make_coordinator()
    coord.room_group_enabled = {"Living room": False}
    switch = RoomGroupToggleSwitch(coord, _entry(), "Living room")
    assert switch.is_on is False


def test_group_toggle_unique_id_uses_safe_room_name():
    coord = _make_coordinator()
    switch = RoomGroupToggleSwitch(coord, _entry(), "Living Room")
    assert switch.unique_id == "entry123_living_room_group_toggle"


@pytest.mark.asyncio
async def test_group_toggle_turn_off_calls_coordinator_and_logs():
    coord = _make_coordinator()
    switch = RoomGroupToggleSwitch(coord, _entry(), "Living room")

    await switch.async_turn_off()

    coord.set_room_group_enabled.assert_called_once_with("Living room", False)
    coord.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_group_toggle_turn_on_calls_coordinator_and_logs():
    coord = _make_coordinator()
    switch = RoomGroupToggleSwitch(coord, _entry(), "Living room")

    await switch.async_turn_on()

    coord.set_room_group_enabled.assert_called_once_with("Living room", True)
    coord.log_event.assert_called_once()


# ── async_setup_entry: group toggle only for 2+ TRV rooms ────────────────────


@pytest.mark.asyncio
async def test_setup_entry_only_creates_group_toggle_for_multi_trv_rooms():
    coord = _make_coordinator()
    coord.rooms = [
        {
            "room_name": "Living room",
            "trvs": [
                {"climate_entity": "climate.a"},
                {"climate_entity": "climate.b"},
            ],
        },
        {"room_name": "Bathroom", "climate_entity": "climate.bathroom"},
    ]
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    overrides = [e for e in added if isinstance(e, RoomOverrideSwitch)]
    toggles = [e for e in added if isinstance(e, RoomGroupToggleSwitch)]
    assert len(overrides) == 2  # one per room, regardless of TRV count
    assert len(toggles) == 1
    assert toggles[0]._room_name == "Living room"
