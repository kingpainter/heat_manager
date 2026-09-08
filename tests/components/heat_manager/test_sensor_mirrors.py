"""Tests for sensor.py's v0.15.0 configured-sensor mirrors.

Covers:
- _NumericMirrorSensor / _TextMirrorSensor: availability, value parsing,
  unit forwarding — the two generic building blocks every mirror is built
  from.
- _room_mirror_sensors() / _hub_mirror_sensors(): only created for fields
  the user actually configured (no silent creation of unconfigured mirrors).
- async_setup_entry(): RemoteLastActionSensor created only when at least
  one of the 3 global remote button entities is configured.
- coordinator.set_remote_last_action() / RemoteLastActionSensor: read-back.

All tests run completely offline — HA core is mocked with MagicMock.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.heat_manager.const import (
    CONF_ALARM_PANEL,
    CONF_BATTERY_SENSOR,
    CONF_BUTTON_TEMP_UP_ENTITY,
    CONF_CO2_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
)
from custom_components.heat_manager.sensor import (
    RemoteLastActionSensor,
    _hub_mirror_sensors,
    _NumericMirrorSensor,
    _room_mirror_sensors,
    _TextMirrorSensor,
    async_setup_entry,
)

# ── shared fixtures ──────────────────────────────────────────────────────────


def _state(value: str, unit: str | None = None) -> MagicMock:
    s = MagicMock()
    s.state = value
    s.attributes = {"unit_of_measurement": unit} if unit is not None else {}
    return s


def _coordinator() -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.rooms = []
    coord.config = {}
    coord.room_device_info = MagicMock(return_value={"identifiers": {("x", "room")}})
    coord.global_device_info = MagicMock(return_value={"identifiers": {("x", "hub")}})
    coord.remote_last_action = None
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


# ── _NumericMirrorSensor ──────────────────────────────────────────────────────


def test_numeric_mirror_parses_float():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("21.5", "°C"))
    sensor = _NumericMirrorSensor(
        coord, "uid", "Room temperature", "sensor.x", {}, device_class=None
    )
    assert sensor.native_value == 21.5
    assert sensor.native_unit_of_measurement == "°C"
    assert sensor.available is True


def test_numeric_mirror_unavailable_when_source_unavailable():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("unavailable"))
    sensor = _NumericMirrorSensor(coord, "uid", "X", "sensor.x", {})
    assert sensor.available is False
    assert sensor.native_value is None


def test_numeric_mirror_unavailable_when_source_missing():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    sensor = _NumericMirrorSensor(coord, "uid", "X", "sensor.x", {})
    assert sensor.available is False
    assert sensor.native_value is None


def test_numeric_mirror_non_numeric_state_returns_none_value_but_available():
    """A garbage/non-numeric state string must not raise — just report no
    value, while still counting as 'available' (it's not unavailable/unknown,
    just unparsable, e.g. a momentary bad reading)."""
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("not-a-number"))
    sensor = _NumericMirrorSensor(coord, "uid", "X", "sensor.x", {})
    assert sensor.available is True
    assert sensor.native_value is None


# ── _TextMirrorSensor ─────────────────────────────────────────────────────────


def test_text_mirror_forwards_raw_state():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("armed_away"))
    sensor = _TextMirrorSensor(coord, "uid", "Alarm panel", "alarm_control_panel.x", {})
    assert sensor.native_value == "armed_away"
    assert sensor.available is True


def test_text_mirror_none_when_unknown():
    coord = _coordinator()
    coord.hass.states.get = MagicMock(return_value=_state("unknown"))
    sensor = _TextMirrorSensor(coord, "uid", "Weather source", "weather.x", {})
    assert sensor.native_value is None


# ── _room_mirror_sensors() ────────────────────────────────────────────────────


def test_room_mirror_sensors_only_created_for_configured_fields():
    coord = _coordinator()
    room = {
        "room_name": "Living room",
        CONF_ROOM_TEMP_SENSOR: "sensor.living_room_temp",
        # humidity/co2/battery left unset
    }
    mirrors = _room_mirror_sensors(coord, _entry(), room)
    assert len(mirrors) == 1
    assert mirrors[0].unique_id == "entry123_living_room_room_temp_mirror"


def test_room_mirror_sensors_none_when_nothing_configured():
    coord = _coordinator()
    room = {"room_name": "Living room"}
    assert _room_mirror_sensors(coord, _entry(), room) == []


def test_room_mirror_sensors_all_four_fields():
    coord = _coordinator()
    room = {
        "room_name": "Living room",
        CONF_ROOM_TEMP_SENSOR: "sensor.a",
        CONF_HUMIDITY_SENSOR: "sensor.b",
        CONF_CO2_SENSOR: "sensor.c",
        CONF_BATTERY_SENSOR: "sensor.d",
    }
    mirrors = _room_mirror_sensors(coord, _entry(), room)
    assert len(mirrors) == 4


# ── _hub_mirror_sensors() ─────────────────────────────────────────────────────


def test_hub_mirror_sensors_only_created_for_configured_fields():
    coord = _coordinator()
    coord.config = {CONF_OUTDOOR_TEMP_SENSOR: "sensor.outdoor_temp"}
    mirrors = _hub_mirror_sensors(coord, _entry())
    assert len(mirrors) == 1
    assert isinstance(mirrors[0], _NumericMirrorSensor)


def test_hub_mirror_sensors_none_when_nothing_configured():
    coord = _coordinator()
    assert _hub_mirror_sensors(coord, _entry()) == []


def test_hub_mirror_sensors_text_fields_use_text_mirror():
    coord = _coordinator()
    coord.config = {
        CONF_WEATHER_ENTITY: "weather.home",
        CONF_ALARM_PANEL: "alarm_control_panel.home",
    }
    mirrors = _hub_mirror_sensors(coord, _entry())
    assert len(mirrors) == 2
    assert all(isinstance(m, _TextMirrorSensor) for m in mirrors)


# ── RemoteLastActionSensor + coordinator.set_remote_last_action() ───────────


def test_remote_last_action_sensor_none_before_any_action():
    coord = _coordinator()
    sensor = RemoteLastActionSensor(coord, _entry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_remote_last_action_sensor_reads_recorded_action():
    coord = _coordinator()
    coord.remote_last_action = {
        "description": "Remote: +0.5°C — Living room → 21.5°C",
        "rooms": ["Living room"],
        "timestamp": "2026-09-06T20:00:00+00:00",
    }
    sensor = RemoteLastActionSensor(coord, _entry())
    assert sensor.native_value is not None
    assert sensor.native_value.year == 2026
    assert sensor.extra_state_attributes == {
        "description": "Remote: +0.5°C — Living room → 21.5°C",
        "rooms": ["Living room"],
    }


def test_set_remote_last_action_records_and_notifies():
    from custom_components.heat_manager.coordinator import HeatManagerCoordinator

    coord = _coordinator()
    coord.set_remote_last_action = (
        HeatManagerCoordinator.set_remote_last_action.__get__(coord, type(coord))
    )
    coord.async_update_listeners = MagicMock()

    coord.set_remote_last_action("Remote: +0.5°C — Bathroom → 20.5°C", ["Bathroom"])

    assert (
        coord.remote_last_action["description"] == "Remote: +0.5°C — Bathroom → 20.5°C"
    )
    assert coord.remote_last_action["rooms"] == ["Bathroom"]
    assert "timestamp" in coord.remote_last_action
    coord.async_update_listeners.assert_called_once()


# ── async_setup_entry(): RemoteLastActionSensor gating ───────────────────────


@pytest.mark.asyncio
async def test_setup_entry_creates_remote_last_action_sensor_when_button_configured():
    coord = _coordinator()
    coord.config = {CONF_BUTTON_TEMP_UP_ENTITY: "event.button_up"}
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    assert any(isinstance(e, RemoteLastActionSensor) for e in added)


@pytest.mark.asyncio
async def test_setup_entry_skips_remote_last_action_sensor_when_no_button_configured():
    coord = _coordinator()
    entry = _entry()
    entry.runtime_data = coord
    added: list = []

    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))

    assert not any(isinstance(e, RemoteLastActionSensor) for e in added)
