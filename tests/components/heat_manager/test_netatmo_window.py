"""Tests for Netatmo open-window detection as an opt-in window source
(v0.64.0). Fully offline.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.netatmo_backend import window_source_open
from custom_components.heat_manager.engine.window_engine import (
    WindowEngine,
    _open_as_state,
)

# ── window_source_open ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("domain", "state", "attr", "expected"),
    [
        ("binary_sensor", "on", None, True),
        ("binary_sensor", "off", None, False),
        ("binary_sensor", "unavailable", None, None),
        ("climate", "auto", True, True),
        ("climate", "heat", False, False),
        ("climate", "auto", None, None),  # integration without the attribute
        ("climate", "unavailable", True, None),
        ("climate", None, True, None),
    ],
)
def test_window_source_open(domain, state, attr, expected):
    assert window_source_open(domain, state, attr) is expected


def test_open_as_state_maps_climate_attribute():
    st = SimpleNamespace(state="auto", attributes={"open_window": True})
    assert _open_as_state("climate.kitchen", st) == "on"
    st = SimpleNamespace(state="auto", attributes={"open_window": False})
    assert _open_as_state("climate.kitchen", st) == "off"
    assert _open_as_state("climate.kitchen", None) is None


# ── Coordinator: sources per room ─────────────────────────────────────────────


def _coordinator(rooms, trvs, states=None):
    coord = MagicMock()
    coord.rooms = rooms
    coord.get_room_trvs = MagicMock(side_effect=lambda n: trvs.get(n, []))
    coord.get_trv_climate_entity = HeatManagerCoordinator.get_trv_climate_entity
    coord.hass.states.get = MagicMock(side_effect=lambda eid: (states or {}).get(eid))
    for name in (
        "get_room_window_sources",
        "is_window_source_open",
        "any_window_open",
    ):
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )
    return coord


TRVS = {
    "Bath": [{"climate_entity": "climate.toilets", "trv_type": "netatmo"}],
    "Z": [{"climate_entity": "climate.z", "trv_type": "zigbee"}],
}


def test_sources_default_off_contact_sensors_only():
    coord = _coordinator([], TRVS)
    room = {"room_name": "Bath", "window_sensors": ["binary_sensor.bath_window"]}
    assert coord.get_room_window_sources(room) == ["binary_sensor.bath_window"]


def test_sources_opt_in_adds_netatmo_climate_only():
    coord = _coordinator([], TRVS)
    bath = {"room_name": "Bath", "trv_window_detection": True}
    zig = {"room_name": "Z", "trv_window_detection": True}
    assert coord.get_room_window_sources(bath) == ["climate.toilets"]
    assert coord.get_room_window_sources(zig) == []


def test_any_window_open_sees_netatmo_detection():
    rooms = [{"room_name": "Bath", "trv_window_detection": True}]
    states = {
        "climate.toilets": SimpleNamespace(
            state="auto", attributes={"open_window": True}
        )
    }
    assert _coordinator(rooms, TRVS, states).any_window_open() is True
    states["climate.toilets"] = SimpleNamespace(
        state="auto", attributes={"open_window": False}
    )
    assert _coordinator(rooms, TRVS, states).any_window_open() is False


# ── Window engine ─────────────────────────────────────────────────────────────


def _engine(coord) -> WindowEngine:
    engine = WindowEngine.__new__(WindowEngine)
    engine.coordinator = coord
    engine._sensor_to_room = {}
    engine._build_sensor_map()
    return engine


def test_engine_tracks_climate_source_and_opens_without_delay():
    rooms = [{"room_name": "Bath", "trv_window_detection": True}]
    coord = _coordinator(rooms, TRVS)
    engine = _engine(coord)
    assert engine._sensor_to_room == {"climate.toilets": "Bath"}
    assert engine._get_open_delay("climate.toilets") == 0


def _event(old_attr, new_attr):
    return SimpleNamespace(
        data={
            "entity_id": "climate.toilets",
            "old_state": SimpleNamespace(
                state="auto", attributes={"open_window": old_attr}
            ),
            "new_state": SimpleNamespace(
                state="auto", attributes={"open_window": new_attr}
            ),
        }
    )


def test_handler_schedules_open_on_open_window_flip():
    rooms = [{"room_name": "Bath", "trv_window_detection": True}]
    coord = _coordinator(rooms, TRVS)
    engine = _engine(coord)
    engine._schedule_open = MagicMock(name="open")
    engine._schedule_close = MagicMock(name="close")

    engine._handle_sensor_change(_event(False, True))
    engine._schedule_open.assert_called_once_with("climate.toilets")

    engine._handle_sensor_change(_event(True, False))
    engine._schedule_close.assert_called_once_with("climate.toilets")


def test_handler_ignores_other_attribute_changes():
    """Setpoint/temperature updates on the climate entity are not window events."""
    rooms = [{"room_name": "Bath", "trv_window_detection": True}]
    coord = _coordinator(rooms, TRVS)
    engine = _engine(coord)
    engine._schedule_open = MagicMock()
    engine._schedule_close = MagicMock()

    engine._handle_sensor_change(_event(False, False))
    engine._handle_sensor_change(_event(None, False))

    engine._schedule_open.assert_not_called()
    engine._schedule_close.assert_not_called()
