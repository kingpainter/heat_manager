"""Tests for ScheduleEngine (v0.9.0, Fase D).

All tests run completely offline — HA core is mocked with MagicMock.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.heat_manager.const import SCHEDULE_TEMP_MAX, SCHEDULE_TEMP_MIN
from custom_components.heat_manager.engine.schedule_engine import ScheduleEngine


def _make_coordinator(rooms=None) -> MagicMock:
    coord = MagicMock()
    coord.rooms = rooms or []
    coord.schedule_override = {}
    coord.hass = MagicMock()
    return coord


def _room(name="living_room", entity: str | None = "schedule.living_room") -> dict:
    room: dict = {"room_name": name}
    if entity:
        room["schedule_entity"] = entity
    return room


def _state(value: str, attrs: dict | None = None) -> MagicMock:
    s = MagicMock()
    s.state = value
    s.attributes = attrs or {}
    return s


# ── opt-in gating ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_room_without_schedule_entity_untouched():
    coord = _make_coordinator(rooms=[_room(entity=None)])
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override == {}


@pytest.mark.asyncio
async def test_room_without_room_name_is_skipped():
    coord = _make_coordinator(rooms=[{"schedule_entity": "schedule.x"}])
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override == {}


# ── schedule.* entities: attributes already populated by HA ────────────────

@pytest.mark.asyncio
async def test_schedule_entity_active_block_sets_override():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(
        return_value=_state("on", {"temperature": 21.5})
    )
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override["living_room"] == pytest.approx(21.5)


@pytest.mark.asyncio
async def test_schedule_entity_inactive_clears_override():
    coord = _make_coordinator(rooms=[_room()])
    coord.schedule_override["living_room"] = 21.5  # stale from a previous tick
    coord.hass.states.get = MagicMock(return_value=_state("off"))
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert "living_room" not in coord.schedule_override


@pytest.mark.asyncio
async def test_schedule_entity_missing_state_clears_override():
    coord = _make_coordinator(rooms=[_room()])
    coord.schedule_override["living_room"] = 21.5
    coord.hass.states.get = MagicMock(return_value=None)
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert "living_room" not in coord.schedule_override


@pytest.mark.asyncio
async def test_schedule_entity_active_without_temperature_key_no_override():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(return_value=_state("on", {}))
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert "living_room" not in coord.schedule_override


# ── calendar.* entities: YAML description parsing ───────────────────────────

@pytest.mark.asyncio
async def test_calendar_entity_parses_description_yaml():
    coord = _make_coordinator(rooms=[_room(entity="calendar.vacation")])
    coord.hass.states.get = MagicMock(
        return_value=_state("on", {"description": "temperature: 18.5\nhvac_mode: heat"})
    )
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override["living_room"] == pytest.approx(18.5)


@pytest.mark.asyncio
async def test_calendar_entity_no_active_event_no_override():
    coord = _make_coordinator(rooms=[_room(entity="calendar.vacation")])
    coord.hass.states.get = MagicMock(return_value=_state("off"))
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert "living_room" not in coord.schedule_override


@pytest.mark.asyncio
async def test_calendar_entity_missing_description_no_override():
    coord = _make_coordinator(rooms=[_room(entity="calendar.vacation")])
    coord.hass.states.get = MagicMock(return_value=_state("on", {}))
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert "living_room" not in coord.schedule_override


@pytest.mark.asyncio
async def test_calendar_entity_invalid_yaml_is_caught():
    coord = _make_coordinator(rooms=[_room(entity="calendar.vacation")])
    coord.hass.states.get = MagicMock(
        return_value=_state("on", {"description": "not: valid: yaml: at: all:"})
    )
    engine = ScheduleEngine(coord)
    await engine.async_tick()  # must not raise
    assert "living_room" not in coord.schedule_override


@pytest.mark.asyncio
async def test_calendar_entity_plain_text_description_ignored():
    """A description that isn't a YAML mapping (e.g. plain prose) parses to
    a string/None, not a dict — must be treated as 'no data', not crash."""
    coord = _make_coordinator(rooms=[_room(entity="calendar.vacation")])
    coord.hass.states.get = MagicMock(
        return_value=_state("on", {"description": "Just a normal calendar event"})
    )
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert "living_room" not in coord.schedule_override


# ── clamping ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_temperature_above_max_is_clamped():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(return_value=_state("on", {"temperature": 99.0}))
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override["living_room"] == pytest.approx(SCHEDULE_TEMP_MAX)


@pytest.mark.asyncio
async def test_temperature_below_min_is_clamped():
    coord = _make_coordinator(rooms=[_room()])
    coord.hass.states.get = MagicMock(return_value=_state("on", {"temperature": -5.0}))
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override["living_room"] == pytest.approx(SCHEDULE_TEMP_MIN)


# ── multi-room ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_independent_rooms_do_not_interfere():
    coord = _make_coordinator(
        rooms=[
            _room(name="living_room", entity="schedule.living_room"),
            _room(name="bedroom", entity="schedule.bedroom"),
        ]
    )

    def _get(entity_id: str):
        if entity_id == "schedule.living_room":
            return _state("on", {"temperature": 21.0})
        if entity_id == "schedule.bedroom":
            return _state("off")
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = ScheduleEngine(coord)
    await engine.async_tick()
    assert coord.schedule_override == {"living_room": pytest.approx(21.0)}


# ── shutdown ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shutdown_is_noop():
    coord = _make_coordinator()
    engine = ScheduleEngine(coord)
    await engine.async_shutdown()  # must not raise
