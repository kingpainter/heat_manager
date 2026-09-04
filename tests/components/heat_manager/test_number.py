"""Tests for number.py — RoomOffsetNumber (B18 Fase 3).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.

RoomOffsetNumber.__init__ does not call super().__init__(), so the entity
can be instantiated directly without hass/entity-registry machinery.
RestoreEntity.async_added_to_hass() itself is a genuine no-op (an extension
point with no body), so `await super().async_added_to_hass()` inside
RoomOffsetNumber.async_added_to_hass() is safe to call as-is. What DOES
need HA's restore-state cache is async_get_last_number_data() — tests stub
that directly on the instance rather than dragging in the real restore
machinery, the same seam RestoreNumber itself exposes to integrations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import DEFAULT_GROUP_OFFSET
from custom_components.heat_manager.number import RoomOffsetNumber, async_setup_entry

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.room_offsets = {}
    coord.log_event = MagicMock()
    coord.room_device_info = MagicMock(return_value={"identifiers": {("x", "y")}})
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


def _last_number_data(native_value):
    data = MagicMock()
    data.native_value = native_value
    return data


# ── __init__ ─────────────────────────────────────────────────────────────────


def test_init_sets_default_value_and_identity():
    coord = _make_coordinator()
    entity = RoomOffsetNumber(coord, _entry(), "Stue")
    assert entity.native_value == DEFAULT_GROUP_OFFSET
    assert entity.unique_id == "entry123_stue_offset"


# ── async_added_to_hass: restore-on-restart ─────────────────────────────────


@pytest.mark.asyncio
async def test_added_to_hass_restores_previous_value():
    coord = _make_coordinator()
    entity = RoomOffsetNumber(coord, _entry(), "Stue")
    entity.async_get_last_number_data = AsyncMock(return_value=_last_number_data(2.5))

    await entity.async_added_to_hass()

    assert entity.native_value == 2.5
    assert coord.room_offsets["Stue"] == 2.5


@pytest.mark.asyncio
async def test_added_to_hass_no_previous_state_keeps_default():
    coord = _make_coordinator()
    entity = RoomOffsetNumber(coord, _entry(), "Stue")
    entity.async_get_last_number_data = AsyncMock(return_value=None)

    await entity.async_added_to_hass()

    assert entity.native_value == DEFAULT_GROUP_OFFSET
    assert coord.room_offsets["Stue"] == DEFAULT_GROUP_OFFSET


@pytest.mark.asyncio
async def test_added_to_hass_previous_native_value_none_keeps_default():
    """A restored record whose native_value is itself None (e.g. the entity
    had never been set before HA's last shutdown) must not overwrite the
    compiled-in default with None."""
    coord = _make_coordinator()
    entity = RoomOffsetNumber(coord, _entry(), "Stue")
    entity.async_get_last_number_data = AsyncMock(return_value=_last_number_data(None))

    await entity.async_added_to_hass()

    assert entity.native_value == DEFAULT_GROUP_OFFSET
    assert coord.room_offsets["Stue"] == DEFAULT_GROUP_OFFSET


# ── async_set_native_value ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_native_value_updates_coordinator_and_logs():
    coord = _make_coordinator()
    entity = RoomOffsetNumber(coord, _entry(), "Stue")
    entity.async_write_ha_state = MagicMock()  # entity never added to hass

    await entity.async_set_native_value(3.0)

    assert entity.native_value == 3.0
    assert coord.room_offsets["Stue"] == 3.0
    coord.log_event.assert_called_once()
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_set_native_value_keeps_rooms_independent():
    coord = _make_coordinator()
    stue = RoomOffsetNumber(coord, _entry(), "Stue")
    stue.async_write_ha_state = MagicMock()
    kokken = RoomOffsetNumber(coord, _entry(), "Køkken")
    kokken.async_write_ha_state = MagicMock()

    await stue.async_set_native_value(1.5)
    await kokken.async_set_native_value(-2.0)

    assert coord.room_offsets == {"Stue": 1.5, "Køkken": -2.0}


# ── async_setup_entry: only 2+ TRV rooms get an offset entity ───────────────


@pytest.mark.asyncio
async def test_setup_entry_only_creates_entities_for_multi_trv_rooms():
    coord = _make_coordinator()
    coord.rooms = [
        {"room_name": "Stue"},
        {"room_name": "Køkken"},
        {"room_name": ""},  # no name — must be skipped, not crash
    ]

    def _all_trvs(room_name):
        return {
            "Stue": [{"climate_entity": "climate.a"}, {"climate_entity": "climate.b"}],
            "Køkken": [{"climate_entity": "climate.c"}],
        }.get(room_name, [])

    coord.get_all_room_trvs = MagicMock(side_effect=_all_trvs)
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], RoomOffsetNumber)
    assert added[0]._room_name == "Stue"
