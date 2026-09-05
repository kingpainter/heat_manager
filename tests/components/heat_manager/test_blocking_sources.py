"""Tests for coordinator self-reporting diagnostic helpers (v0.9.0, Fase E).

Covers:
- get_room_blocking_sources(): controller_off / controller_pause / window /
  presence, and the "nothing blocking" empty-list case.
- global_blocking_sources(): union across rooms, sorted, de-duplicated.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.heat_manager.const import ControllerState, RoomState
from custom_components.heat_manager.coordinator import HeatManagerCoordinator


def _make_coordinator(
    controller_state: ControllerState = ControllerState.ON,
    room_states: dict | None = None,
    room_names: list[str] | None = None,
) -> MagicMock:
    coord = MagicMock()
    coord.controller_state = controller_state
    states = room_states or {}
    coord.get_room_state = MagicMock(
        side_effect=lambda name: states.get(name, RoomState.NORMAL)
    )
    coord.rooms = [{"room_name": name} for name in (room_names or [])]
    coord.get_room_blocking_sources = (
        HeatManagerCoordinator.get_room_blocking_sources.__get__(coord, type(coord))
    )
    coord.global_blocking_sources = (
        HeatManagerCoordinator.global_blocking_sources.__get__(coord, type(coord))
    )
    return coord


# ── get_room_blocking_sources ───────────────────────────────────────────────


def test_nothing_blocking_returns_empty_list():
    coord = _make_coordinator()
    assert coord.get_room_blocking_sources("living_room") == []


def test_controller_off_reported():
    coord = _make_coordinator(controller_state=ControllerState.OFF)
    assert coord.get_room_blocking_sources("living_room") == ["controller_off"]


def test_controller_pause_reported():
    coord = _make_coordinator(controller_state=ControllerState.PAUSE)
    assert coord.get_room_blocking_sources("living_room") == ["controller_pause"]


def test_window_open_reported():
    coord = _make_coordinator(room_states={"living_room": RoomState.WINDOW_OPEN})
    assert coord.get_room_blocking_sources("living_room") == ["window"]


def test_presence_away_reported():
    coord = _make_coordinator(room_states={"living_room": RoomState.AWAY})
    assert coord.get_room_blocking_sources("living_room") == ["presence"]


def test_controller_off_and_window_both_reported():
    coord = _make_coordinator(
        controller_state=ControllerState.OFF,
        room_states={"living_room": RoomState.WINDOW_OPEN},
    )
    assert coord.get_room_blocking_sources("living_room") == [
        "controller_off",
        "window",
    ]


def test_override_and_preheat_report_nothing_extra():
    """OVERRIDE/PRE_HEAT aren't 'blocking' states — they're active alternate
    modes, not something stopping heat — so neither is reported."""
    coord = _make_coordinator(room_states={"living_room": RoomState.OVERRIDE})
    assert coord.get_room_blocking_sources("living_room") == []
    coord2 = _make_coordinator(room_states={"living_room": RoomState.PRE_HEAT})
    assert coord2.get_room_blocking_sources("living_room") == []


# ── global_blocking_sources ─────────────────────────────────────────────────


def test_global_empty_when_no_rooms_blocked():
    coord = _make_coordinator(room_names=["living_room", "kitchen"])
    assert coord.global_blocking_sources() == []


def test_global_unions_across_rooms():
    coord = _make_coordinator(
        room_names=["living_room", "kitchen"],
        room_states={"living_room": RoomState.WINDOW_OPEN, "kitchen": RoomState.AWAY},
    )
    assert coord.global_blocking_sources() == ["presence", "window"]


def test_global_dedupes_same_source_across_rooms():
    coord = _make_coordinator(
        room_names=["living_room", "kitchen"],
        room_states={
            "living_room": RoomState.WINDOW_OPEN,
            "kitchen": RoomState.WINDOW_OPEN,
        },
    )
    assert coord.global_blocking_sources() == ["window"]


def test_global_controller_off_applies_to_all_rooms_once():
    coord = _make_coordinator(
        controller_state=ControllerState.OFF,
        room_names=["living_room", "kitchen"],
    )
    assert coord.global_blocking_sources() == ["controller_off"]


def test_global_skips_rooms_without_room_name():
    coord = _make_coordinator(room_names=["living_room"])
    coord.rooms.append({"climate_entity": "climate.no_name"})
    assert coord.global_blocking_sources() == []
