"""Tests for coordinator room-grouping helpers (B18 Fase 3).

Covers:
- get_all_room_trvs(): structural accessor, ignores the group toggle
- get_room_trvs(): toggle-aware — narrows a 2+ TRV room to just the primary
  when its group toggle is off; single-TRV rooms are never affected
- set_room_group_enabled(): updates state, rebuilds SyncEngine's map, and
  refreshes coordinator listeners

All tests run completely offline — HA core is mocked with MagicMock.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.heat_manager.coordinator import HeatManagerCoordinator


def _make_coordinator(rooms: list[dict]) -> MagicMock:
    coord = MagicMock()
    coord.rooms = rooms
    coord.room_group_enabled = {}
    coord.sync_engine = MagicMock()
    coord.get_all_room_trvs = HeatManagerCoordinator.get_all_room_trvs.__get__(
        coord, type(coord)
    )
    coord.get_room_trvs = HeatManagerCoordinator.get_room_trvs.__get__(
        coord, type(coord)
    )
    coord.set_room_group_enabled = (
        HeatManagerCoordinator.set_room_group_enabled.__get__(coord, type(coord))
    )
    return coord


def _single_trv_room(name="Bathroom") -> dict:
    return {
        "room_name": name,
        "climate_entity": "climate.bathroom",
        "trv_type": "netatmo",
    }


def _multi_trv_room(name="Living room") -> dict:
    return {
        "room_name": name,
        "trvs": [
            {"climate_entity": "climate.living_room", "trv_type": "netatmo"},
            {"climate_entity": "climate.living_room_trv2", "trv_type": "zigbee"},
        ],
    }


# ── get_all_room_trvs: structural, ignores the toggle ────────────────────────


def test_get_all_room_trvs_ignores_toggle_off():
    coord = _make_coordinator([_multi_trv_room()])
    coord.room_group_enabled["Living room"] = False
    trvs = coord.get_all_room_trvs("Living room")
    assert len(trvs) == 2


def test_get_all_room_trvs_unknown_room_returns_empty():
    coord = _make_coordinator([_single_trv_room()])
    assert coord.get_all_room_trvs("Nope") == []


# ── get_room_trvs: toggle-aware ───────────────────────────────────────────────


def test_get_room_trvs_multi_trv_room_default_returns_every_trv():
    coord = _make_coordinator([_multi_trv_room()])
    trvs = coord.get_room_trvs("Living room")
    assert len(trvs) == 2


def test_get_room_trvs_multi_trv_room_toggle_off_returns_only_primary():
    coord = _make_coordinator([_multi_trv_room()])
    coord.room_group_enabled["Living room"] = False
    trvs = coord.get_room_trvs("Living room")
    assert len(trvs) == 1
    assert trvs[0]["climate_entity"] == "climate.living_room"


def test_get_room_trvs_multi_trv_room_toggle_explicitly_on_returns_every_trv():
    coord = _make_coordinator([_multi_trv_room()])
    coord.room_group_enabled["Living room"] = True
    trvs = coord.get_room_trvs("Living room")
    assert len(trvs) == 2


def test_get_room_trvs_single_trv_room_unaffected_by_toggle_off():
    """A single-TRV room has no toggle entity — even if room_group_enabled
    somehow held a False for it, it must not lose its only TRV."""
    coord = _make_coordinator([_single_trv_room()])
    coord.room_group_enabled["Bathroom"] = False
    trvs = coord.get_room_trvs("Bathroom")
    assert len(trvs) == 1


def test_get_room_trvs_unknown_room_returns_empty():
    coord = _make_coordinator([_single_trv_room()])
    assert coord.get_room_trvs("Nope") == []


# ── set_room_group_enabled ────────────────────────────────────────────────────


def test_set_room_group_enabled_updates_state():
    coord = _make_coordinator([_multi_trv_room()])
    coord.set_room_group_enabled("Living room", False)
    assert coord.room_group_enabled["Living room"] is False


def test_set_room_group_enabled_rebuilds_sync_engine_map():
    coord = _make_coordinator([_multi_trv_room()])
    coord.set_room_group_enabled("Living room", False)
    coord.sync_engine.rebuild_entity_map.assert_called_once()


def test_set_room_group_enabled_refreshes_listeners():
    coord = _make_coordinator([_multi_trv_room()])
    coord.set_room_group_enabled("Living room", False)
    coord.async_update_listeners.assert_called_once()


def test_set_room_group_enabled_immediately_visible_to_get_room_trvs():
    """The whole point of Fase 3: flipping the toggle must take effect on
    the very next get_room_trvs() call, no coordinator reload needed."""
    coord = _make_coordinator([_multi_trv_room()])
    assert len(coord.get_room_trvs("Living room")) == 2

    coord.set_room_group_enabled("Living room", False)
    assert len(coord.get_room_trvs("Living room")) == 1

    coord.set_room_group_enabled("Living room", True)
    assert len(coord.get_room_trvs("Living room")) == 2


# ── async_boost_start: resets every room's offset (B18 Fase 3) ───────────────


@pytest.mark.asyncio
async def test_boost_start_clears_all_room_offsets():
    """No rooms configured — isolates the offset-reset behaviour from the
    rest of async_boost_start's per-room loop, which is exercised
    separately."""
    coord = _make_coordinator([])
    coord.room_offsets = {"Living room": 1.5, "Bathroom": -1.0}
    coord.async_boost_start = HeatManagerCoordinator.async_boost_start.__get__(
        coord, type(coord)
    )

    await coord.async_boost_start()

    assert coord.room_offsets == {}
    coord.async_update_listeners.assert_called_once()
