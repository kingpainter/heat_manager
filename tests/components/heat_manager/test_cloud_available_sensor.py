"""Tests for CloudAvailableSensor (binary_sensor.py) — v0.69.1 staleness fix.

The sensor reads "cloud degraded" when every Netatmo cloud climate entity
has gone 10+ min without a report. Before v0.69.1 it used last_updated
alone, which HA only moves when the value changes, so a stable room looked
stale even though the integration was reporting it every minute.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from custom_components.heat_manager.binary_sensor import CloudAvailableSensor


def _sensor(state: MagicMock) -> CloudAvailableSensor:
    coord = MagicMock()
    coord.rooms = [{"room_name": "Stuen"}]
    coord.get_climate_entity = MagicMock(return_value="climate.living_room")
    coord.get_homekit_climate_entity = MagicMock(return_value="climate.netatmo_valve_2")
    coord.hass.states.get = MagicMock(return_value=state)
    entry = MagicMock(entry_id="abc")
    return CloudAvailableSensor(coord, entry)


def _now() -> datetime:
    return datetime.now(UTC)


def test_unchanged_but_recently_reported_room_is_available():
    state = MagicMock(
        state="auto",
        last_updated=_now() - timedelta(minutes=19),
        last_reported=_now() - timedelta(minutes=2),
    )
    sensor = _sensor(state)
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["stale_rooms"] == []


def test_room_not_reported_for_10_min_is_degraded():
    state = MagicMock(
        state="auto",
        last_updated=_now() - timedelta(minutes=30),
        last_reported=_now() - timedelta(minutes=11),
    )
    sensor = _sensor(state)
    assert sensor.is_on is False
    assert sensor.extra_state_attributes["stale_rooms"] == ["Stuen"]
