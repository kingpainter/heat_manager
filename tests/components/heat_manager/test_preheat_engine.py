"""Tests for PreheatEngine — Phase 3."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch
import pytest

from custom_components.heat_manager.engine.preheat_engine import PreheatEngine
from custom_components.heat_manager.const import (
    RoomState,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PREHEAT_LEAD_TIME_MIN,
)


def _make_coordinator(
    persons=None,
    rooms=None,
    travel_sensor_state: str | None = None,
    someone_home: bool = False,
) -> MagicMock:
    coord = MagicMock()
    coord.persons = persons or []
    coord.rooms   = rooms   or []
    coord.config  = {"notify_preheat": False, "notify_service": ""}
    coord.room_states = {}
    coord.someone_home.return_value = someone_home
    coord.log_event = MagicMock()
    coord.set_room_state = MagicMock()

    def get_room_state(name):
        return coord.room_states.get(name, RoomState.NORMAL)
    coord.get_room_state.side_effect = get_room_state

    coord.get_climate_entity = MagicMock(return_value="climate.room")
    coord.any_window_open = MagicMock(return_value=False)

    hass = MagicMock()
    hass.async_create_task = MagicMock(return_value=MagicMock())

    travel_s = MagicMock()
    travel_s.state = travel_sensor_state or "unavailable"

    def states_get(entity_id):
        if travel_sensor_state is not None and "travel_time" in entity_id:
            return travel_s
        return None

    hass.states.get.side_effect = states_get
    hass.services.async_call = AsyncMock()
    coord.hass = hass
    return coord


def _person(entity_id: str, tracking: bool = True, lead_min: int = 20) -> dict:
    return {
        CONF_PERSON_ENTITY: entity_id,
        CONF_PERSON_TRACKING: tracking,
        CONF_PREHEAT_LEAD_TIME_MIN: lead_min,
    }


def _room(name: str, climate: str = "climate.room") -> dict:
    return {"room_name": name, "climate_entity": climate}


# ── sensor map tests ──────────────────────────────────────────────────────────

def test_no_travel_sensor_engine_idle():
    """No travel_time sensor → _travel_sensors is empty, engine is idle."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        travel_sensor_state=None,
    )
    engine = PreheatEngine(coord)
    assert len(engine._travel_sensors) == 0


def test_travel_sensor_found_and_mapped():
    """travel_time sensor present → mapped correctly."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        travel_sensor_state="900",
    )
    engine = PreheatEngine(coord)
    assert "person.flemming" in engine._travel_sensors
    assert engine._travel_sensors["person.flemming"] == "sensor.flemming_travel_time_home"


def test_untracked_person_not_mapped():
    """Person with tracking=False must not be added to travel sensor map."""
    coord = _make_coordinator(
        persons=[_person("person.flemming", tracking=False)],
        travel_sensor_state="600",
    )
    engine = PreheatEngine(coord)
    assert len(engine._travel_sensors) == 0


# ── arming logic tests ────────────────────────────────────────────────────────

def test_arms_when_everyone_leaves():
    """person → not_home while house empty → _preheat_armed becomes True."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        travel_sensor_state="1200",
        someone_home=False,
    )
    engine = PreheatEngine(coord)
    engine._travel_sensors = {"person.flemming": "sensor.flemming_travel_time_home"}

    event = MagicMock()
    event.data = {
        "entity_id": "person.flemming",
        "new_state": MagicMock(state="not_home"),
    }
    engine._handle_person_change(event)
    assert engine._preheat_armed is True


def test_disarms_on_arrival():
    """person → home while armed → _preheat_armed becomes False."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        travel_sensor_state="300",
        someone_home=True,
    )
    engine = PreheatEngine(coord)
    engine._preheat_armed = True

    event = MagicMock()
    event.data = {
        "entity_id": "person.flemming",
        "new_state": MagicMock(state="home"),
    }
    engine._handle_person_change(event)
    assert engine._preheat_armed is False


# ── preheat trigger tests ─────────────────────────────────────────────────────

def test_preheat_fires_when_travel_time_within_lead():
    """Travel time ≤ lead_time_seconds → async_create_task called."""
    coord = _make_coordinator(
        persons=[_person("person.flemming", lead_min=20)],
        rooms=[_room("Kitchen")],
        travel_sensor_state="1200",
    )
    engine = PreheatEngine(coord)
    engine._preheat_armed = True
    engine._travel_sensors = {"person.flemming": "sensor.flemming_travel_time_home"}

    event = MagicMock()
    event.data = {
        "entity_id": "sensor.flemming_travel_time_home",
        "new_state": MagicMock(state="1100"),  # 18.3 min < 20 min lead
    }
    engine._handle_travel_time_change(event)
    coord.hass.async_create_task.assert_called_once()


def test_preheat_does_not_fire_when_not_armed():
    """Not armed → travel time change is ignored."""
    coord = _make_coordinator(
        persons=[_person("person.flemming", lead_min=20)],
        travel_sensor_state="600",
    )
    engine = PreheatEngine(coord)
    engine._preheat_armed = False
    engine._travel_sensors = {"person.flemming": "sensor.flemming_travel_time_home"}

    event = MagicMock()
    event.data = {
        "entity_id": "sensor.flemming_travel_time_home",
        "new_state": MagicMock(state="300"),
    }
    engine._handle_travel_time_change(event)
    coord.hass.async_create_task.assert_not_called()


def test_preheat_does_not_fire_when_travel_exceeds_lead():
    """Travel time > lead_time → not yet time to preheat."""
    coord = _make_coordinator(
        persons=[_person("person.flemming", lead_min=20)],
        travel_sensor_state="3600",
    )
    engine = PreheatEngine(coord)
    engine._preheat_armed = True
    engine._travel_sensors = {"person.flemming": "sensor.flemming_travel_time_home"}

    event = MagicMock()
    event.data = {
        "entity_id": "sensor.flemming_travel_time_home",
        "new_state": MagicMock(state="3600"),  # 60 min > 20 min lead
    }
    engine._handle_travel_time_change(event)
    coord.hass.async_create_task.assert_not_called()


# ── _start_preheat tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_preheat_sets_rooms_to_schedule():
    """_start_preheat sets AWAY rooms to schedule and marks PRE_HEAT."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        rooms=[_room("Kitchen"), _room("Living")],
    )
    coord.room_states = {"Kitchen": RoomState.AWAY, "Living": RoomState.AWAY}
    coord.get_room_state.side_effect = lambda n: coord.room_states.get(n, RoomState.NORMAL)

    engine = PreheatEngine(coord)
    engine._preheat_armed = True

    await engine._start_preheat("person.flemming")

    assert coord.hass.services.async_call.call_count == 2
    assert engine._preheat_armed is False


@pytest.mark.asyncio
async def test_start_preheat_skips_normal_rooms():
    """_start_preheat only affects AWAY rooms — NORMAL rooms untouched."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        rooms=[_room("Kitchen"), _room("Living")],
    )
    coord.room_states = {"Kitchen": RoomState.NORMAL, "Living": RoomState.AWAY}
    coord.get_room_state.side_effect = lambda n: coord.room_states.get(n, RoomState.NORMAL)

    engine = PreheatEngine(coord)
    engine._preheat_armed = True

    await engine._start_preheat("person.flemming")

    assert coord.hass.services.async_call.call_count == 1  # only Living


@pytest.mark.asyncio
async def test_start_preheat_disarms_after_fire():
    """After preheat fires, _preheat_armed is False to prevent double-fire."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        rooms=[_room("Kitchen")],
    )
    coord.room_states = {"Kitchen": RoomState.AWAY}
    coord.get_room_state.side_effect = lambda n: coord.room_states.get(n, RoomState.NORMAL)

    engine = PreheatEngine(coord)
    engine._preheat_armed = True
    await engine._start_preheat("person.flemming")
    assert engine._preheat_armed is False


@pytest.mark.asyncio
async def test_lead_time_seconds_from_config():
    """Lead time is read from person config."""
    coord = _make_coordinator(
        persons=[_person("person.flemming", lead_min=30)],
    )
    engine = PreheatEngine(coord)
    assert engine._lead_time_seconds("person.flemming") == 1800.0


@pytest.mark.asyncio
async def test_async_tick_noop():
    """async_tick is a no-op for the preheat engine."""
    coord = _make_coordinator()
    engine = PreheatEngine(coord)
    await engine.async_tick()  # must not raise


@pytest.mark.asyncio
async def test_shutdown_unsubscribes():
    """async_shutdown clears all unsub callbacks."""
    coord = _make_coordinator(
        persons=[_person("person.flemming")],
        travel_sensor_state="900",
    )
    engine = PreheatEngine(coord)
    unsub = MagicMock()
    engine._unsubs = [unsub]
    await engine.async_shutdown()
    unsub.assert_called_once()
    assert len(engine._unsubs) == 0
