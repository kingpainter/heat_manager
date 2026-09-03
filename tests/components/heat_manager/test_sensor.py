"""Tests for sensor.py — the global and per-room diagnostic/state sensors.

All tests run completely offline — HA core (coordinator, hass, config entry)
is mocked with MagicMock. Entities are instantiated directly, bypassing
async_setup_entry/async_add_entities, since CoordinatorEntity.__init__ only
stores `coordinator`/`coordinator_context` and touches nothing else.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.heat_manager.const import RoomState
from custom_components.heat_manager.sensor import (
    EfficiencyScoreSensor,
    EnergySavedSensor,
    EnergyWastedSensor,
    PauseRemainingSensor,
    RoomCalibrationOffsetSensor,
    RoomPidPowerSensor,
    RoomStateSensor,
    RoomWindowDurationSensor,
)

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.pause_remaining_minutes = 0
    coord.energy_wasted_today = 0.0
    coord.energy_saved_today = 0.0
    coord.efficiency_score = 100
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.get_room_blocking_sources = MagicMock(return_value=[])
    coord.get_pid = MagicMock(return_value=None)

    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    coord.hass = hass

    coord.global_device_info = MagicMock(return_value={"identifiers": {("x", "y")}})
    coord.room_device_info = MagicMock(return_value={"identifiers": {("x", "z")}})
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


def _room(name: str = "Bathroom", climate: str = "climate.bathroom") -> dict:
    room: dict = {"room_name": name}
    if climate:
        room["climate_entity"] = climate
    return room


def _state(value: str, attrs: dict | None = None) -> MagicMock:
    s = MagicMock()
    s.state = value
    s.attributes = attrs or {}
    return s


# ── global sensors ───────────────────────────────────────────────────────────


def test_pause_remaining_sensor_reads_coordinator_value():
    coord = _make_coordinator()
    coord.pause_remaining_minutes = 12
    sensor = PauseRemainingSensor(coord, _entry())
    assert sensor.native_value == 12
    assert sensor.unique_id == "entry123_pause_remaining"


def test_energy_wasted_sensor_reads_coordinator_value():
    coord = _make_coordinator()
    coord.energy_wasted_today = 1.25
    sensor = EnergyWastedSensor(coord, _entry())
    assert sensor.native_value == 1.25
    assert sensor.unique_id == "entry123_energy_wasted_today"


def test_energy_saved_sensor_reads_coordinator_value():
    coord = _make_coordinator()
    coord.energy_saved_today = 0.75
    sensor = EnergySavedSensor(coord, _entry())
    assert sensor.native_value == 0.75
    assert sensor.unique_id == "entry123_energy_saved_today"


def test_efficiency_score_sensor_reads_coordinator_value():
    coord = _make_coordinator()
    coord.efficiency_score = 87
    sensor = EfficiencyScoreSensor(coord, _entry())
    assert sensor.native_value == 87
    assert sensor.unique_id == "entry123_efficiency_score"


# ── RoomStateSensor: value + attributes ─────────────────────────────────────


def test_room_state_sensor_native_value_from_coordinator():
    coord = _make_coordinator()
    coord.get_room_state = MagicMock(
        side_effect=lambda name: (
            RoomState.WINDOW_OPEN if name == "Bathroom" else RoomState.NORMAL
        )
    )
    sensor = RoomStateSensor(coord, _entry(), _room(name="Bathroom"))
    assert sensor.native_value == RoomState.WINDOW_OPEN.value


def test_room_state_sensor_unique_id_and_name_use_safe_room_name():
    coord = _make_coordinator()
    sensor = RoomStateSensor(coord, _entry(), _room(name="Living Room"))
    assert sensor.unique_id == "entry123_living_room_state"
    assert sensor.name == "Living Room state"


def test_room_state_sensor_extra_state_attributes_includes_blocking_sources():
    coord = _make_coordinator()
    coord.get_room_blocking_sources = MagicMock(
        side_effect=lambda name: (
            ["window", "controller_off"] if name == "Bathroom" else []
        )
    )
    sensor = RoomStateSensor(coord, _entry(), _room(name="Bathroom"))
    attrs = sensor.extra_state_attributes
    assert attrs["room_name"] == "Bathroom"
    assert attrs["blocking_sources"] == ["window", "controller_off"]


# ── RoomStateSensor: availability ───────────────────────────────────────────


def test_room_state_sensor_available_when_climate_state_present_and_ok():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: _state("heat") if eid == "climate.bathroom" else None
    )
    sensor = RoomStateSensor(coord, _entry(), _room())
    assert sensor.available is True


def test_room_state_sensor_unavailable_when_climate_state_missing():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    sensor = RoomStateSensor(coord, _entry(), _room())
    assert sensor.available is False


def test_room_state_sensor_unavailable_when_climate_state_is_unavailable():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: (
            _state("unavailable") if eid == "climate.bathroom" else None
        )
    )
    sensor = RoomStateSensor(coord, _entry(), _room())
    assert sensor.available is False


def test_room_state_sensor_unavailable_when_climate_state_is_unknown():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: _state("unknown") if eid == "climate.bathroom" else None
    )
    sensor = RoomStateSensor(coord, _entry(), _room())
    assert sensor.available is False


def test_room_state_sensor_available_true_when_no_climate_entity_configured():
    """A room with no climate_entity at all (misconfigured / template room)
    should not be forced unavailable — there's nothing to watch."""
    coord = _make_coordinator()
    sensor = RoomStateSensor(coord, _entry(), _room(climate=None))
    assert sensor.available is True


# ── RoomStateSensor: unavailable/recovery logging (once each way) ──────────


def test_room_state_sensor_logs_warning_once_on_unavailable(caplog):
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)  # always unavailable
    sensor = RoomStateSensor(coord, _entry(), _room())

    import logging

    sensor.async_write_ha_state = MagicMock()  # entity never added to hass
    caplog.set_level(logging.WARNING, logger="custom_components.heat_manager.sensor")
    sensor._handle_coordinator_update()
    sensor._handle_coordinator_update()  # still unavailable — must not log again

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_room_state_sensor_logs_info_once_on_recovery(caplog):
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)  # start unavailable
    sensor = RoomStateSensor(coord, _entry(), _room())
    sensor.async_write_ha_state = MagicMock()  # entity never added to hass
    sensor._handle_coordinator_update()  # logs WARNING, sets _was_unavailable=True

    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: _state("heat") if eid == "climate.bathroom" else None
    )

    import logging

    caplog.set_level(logging.INFO, logger="custom_components.heat_manager.sensor")
    caplog.clear()
    sensor._handle_coordinator_update()
    sensor._handle_coordinator_update()  # still available — must not log again

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1


# ── RoomWindowDurationSensor ─────────────────────────────────────────────────


def test_window_duration_sensor_starts_at_zero():
    coord = _make_coordinator()
    sensor = RoomWindowDurationSensor(coord, _entry(), _room())
    assert sensor.native_value == 0


def test_window_duration_sensor_accumulates_minutes_after_close():
    from datetime import timedelta

    from homeassistant.util.dt import utcnow

    coord = _make_coordinator()
    sensor = RoomWindowDurationSensor(coord, _entry(), _room())
    sensor.async_write_ha_state = MagicMock()  # entity never added to hass

    # Window opens.
    coord.get_room_state = MagicMock(return_value=RoomState.WINDOW_OPEN)
    sensor._handle_coordinator_update()
    assert sensor._opened_at is not None

    # Simulate 10 minutes having passed, then window closes.
    sensor._opened_at = utcnow() - timedelta(minutes=10)
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    sensor._handle_coordinator_update()

    assert sensor.native_value == 10
    assert sensor._opened_at is None


def test_window_duration_sensor_resets_on_new_day():
    from datetime import date, timedelta

    coord = _make_coordinator()
    sensor = RoomWindowDurationSensor(coord, _entry(), _room())
    sensor.async_write_ha_state = MagicMock()  # entity never added to hass
    sensor._total_minutes = 42
    sensor._last_reset_date = date.today() - timedelta(days=1)

    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    sensor._handle_coordinator_update()

    assert sensor._total_minutes == 0
    assert sensor._last_reset_date == date.today()


# ── RoomPidPowerSensor ───────────────────────────────────────────────────────


def test_pid_power_sensor_none_when_no_pid():
    coord = _make_coordinator()
    coord.get_pid = MagicMock(return_value=None)
    sensor = RoomPidPowerSensor(coord, _entry(), _room())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"room_name": "Bathroom"}


def test_pid_power_sensor_none_when_pid_has_no_last_output():
    coord = _make_coordinator()
    pid = MagicMock(spec=[])  # no _last_output attribute at all
    coord.get_pid = MagicMock(return_value=pid)
    sensor = RoomPidPowerSensor(coord, _entry(), _room())
    assert sensor.native_value is None


def test_pid_power_sensor_converts_fraction_to_percent():
    coord = _make_coordinator()
    pid = MagicMock()
    pid._last_output = 0.437
    coord.get_pid = MagicMock(return_value=pid)
    sensor = RoomPidPowerSensor(coord, _entry(), _room())
    assert sensor.native_value == 43.7


def test_pid_power_sensor_attributes_expose_gains_and_integral():
    coord = _make_coordinator()
    pid = MagicMock()
    pid._last_output = 0.5
    pid.kp = 1.0
    pid.ki = 0.1
    pid.kd = 0.01
    pid._integral = 3.14159
    coord.get_pid = MagicMock(return_value=pid)
    sensor = RoomPidPowerSensor(coord, _entry(), _room())
    attrs = sensor.extra_state_attributes
    assert attrs["pid_kp"] == 1.0
    assert attrs["pid_ki"] == 0.1
    assert attrs["pid_kd"] == 0.01
    assert attrs["integral"] == 3.1416


# ── RoomCalibrationOffsetSensor ──────────────────────────────────────────────


def test_calibration_offset_sensor_none_when_never_written():
    coord = _make_coordinator()
    coord.calibration_engine = MagicMock()
    coord.calibration_engine._last_written = {}
    sensor = RoomCalibrationOffsetSensor(coord, _entry(), _room())
    assert sensor.native_value is None


def test_calibration_offset_sensor_returns_rounded_last_written_value():
    coord = _make_coordinator()
    coord.calibration_engine = MagicMock()
    coord.calibration_engine._last_written = {"Bathroom": 1.234}
    sensor = RoomCalibrationOffsetSensor(coord, _entry(), _room())
    assert sensor.native_value == 1.2
