"""Tests for binary_sensor.py's v0.15.0 RawWindowContactMirror.

All tests run completely offline — HA core is mocked with MagicMock.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.heat_manager.binary_sensor import (
    RawWindowContactMirror,
    RoomWindowSensor,
    async_setup_entry,
)
from custom_components.heat_manager.const import CONF_WINDOW_SENSORS


def _state(value: str) -> MagicMock:
    s = MagicMock()
    s.state = value
    return s


def _coordinator() -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.rooms = []
    coord.room_device_info = MagicMock(return_value={"identifiers": {("x", "room")}})
    coord.global_device_info = MagicMock(return_value={"identifiers": {("x", "hub")}})
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


# ── RawWindowContactMirror ────────────────────────────────────────────────────


def test_mirror_is_on_true():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("on"))
    mirror = RawWindowContactMirror(
        coord, _entry(), {"room_name": "Living room"}, 0, "binary_sensor.window1"
    )
    assert mirror.is_on is True
    assert mirror.available is True
    assert mirror.unique_id == "entry123_living_room_window_mirror_0"
    assert mirror.name == "Window/door sensor 1"


def test_mirror_is_on_false():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("off"))
    mirror = RawWindowContactMirror(
        coord, _entry(), {"room_name": "Living room"}, 0, "binary_sensor.window1"
    )
    assert mirror.is_on is False


def test_mirror_unavailable_when_source_missing():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    mirror = RawWindowContactMirror(
        coord, _entry(), {"room_name": "Living room"}, 0, "binary_sensor.window1"
    )
    assert mirror.available is False
    assert mirror.is_on is None


def test_mirror_index_appears_in_name_and_unique_id():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("off"))
    mirror = RawWindowContactMirror(
        coord, _entry(), {"room_name": "Living room"}, 2, "binary_sensor.window3"
    )
    assert mirror.name == "Window/door sensor 3"
    assert mirror.unique_id == "entry123_living_room_window_mirror_2"


# ── async_setup_entry(): one mirror per configured window sensor ────────────


@pytest.mark.asyncio
async def test_setup_entry_creates_one_mirror_per_window_sensor():
    coord = _coordinator()
    coord.rooms = [
        {
            "room_name": "Living room",
            CONF_WINDOW_SENSORS: ["binary_sensor.a", "binary_sensor.b"],
        }
    ]
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    mirrors = [e for e in added if isinstance(e, RawWindowContactMirror)]
    assert len(mirrors) == 2
    aggregates = [e for e in added if isinstance(e, RoomWindowSensor)]
    assert len(aggregates) == 1


@pytest.mark.asyncio
async def test_setup_entry_skips_empty_window_sensor_slots():
    """A blank entry in the window_sensors list (never fully removed by the
    config flow, or migrated from an older config) must not produce a
    mirror pointed at an empty entity_id."""
    coord = _coordinator()
    coord.rooms = [
        {
            "room_name": "Living room",
            CONF_WINDOW_SENSORS: ["binary_sensor.a", "", None],
        }
    ]
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    mirrors = [e for e in added if isinstance(e, RawWindowContactMirror)]
    assert len(mirrors) == 1


@pytest.mark.asyncio
async def test_setup_entry_no_mirrors_when_room_has_no_window_sensors():
    coord = _coordinator()
    coord.rooms = [{"room_name": "Bathroom"}]
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    assert not any(isinstance(e, RawWindowContactMirror) for e in added)
