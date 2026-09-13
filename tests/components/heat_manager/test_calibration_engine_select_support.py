"""Tests for CalibrationEngine's select-entity calibration support
(2026-09-13, better_thermostat-inspired).

CONF_CALIBRATION_ENTITY previously had to be a `number.*` entity, written to
via `number.set_value`. Some integrations (e.g. HomematicIP) instead expose
calibration as a `select.*` entity with a fixed set of discrete offset
steps. These tests cover: the pre-existing `number` write path is unchanged
by the refactor; a `select` entity has its computed offset snapped to the
nearest available option and written via `select.select_option`; the
current calibration value is read back correctly from either domain; and an
unsupported domain, or a select entity with no parseable numeric options,
is silently skipped rather than raising.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.engine.calibration_engine import (
    CalibrationEngine,
    _parse_offset_option,
)


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(return_value=None)
    coord.hass.services.async_call = AsyncMock()
    return coord


def _state(value: str, **attrs) -> MagicMock:
    s = MagicMock()
    s.state = value
    s.attributes = attrs
    return s


# ── _parse_offset_option ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("-1.0", -1.0),
        ("+0.5K", 0.5),
        ("2.0 °C", 2.0),
        ("0", 0.0),
        ("no numbers here", None),
        ("", None),
    ],
)
def test_parse_offset_option(text, expected):
    assert _parse_offset_option(text) == expected


# ── _nearest_select_option ────────────────────────────────────────────────


def test_nearest_select_option_picks_closest():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(
        return_value=_state("0.0", options=["-1.0", "0.0", "0.5", "1.0", "2.0"])
    )
    engine = CalibrationEngine(coord)

    result = engine._nearest_select_option("select.trv_offset", 0.7)

    assert result == {"label": "0.5", "value": 0.5}


def test_nearest_select_option_missing_entity_returns_none():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    engine = CalibrationEngine(coord)

    assert engine._nearest_select_option("select.trv_offset", 1.0) is None


def test_nearest_select_option_no_parseable_options_returns_none():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(
        return_value=_state("auto", options=["auto", "manual"])
    )
    engine = CalibrationEngine(coord)

    assert engine._nearest_select_option("select.trv_offset", 1.0) is None


# ── _async_update_room — number path (unchanged behaviour) ───────────────


@pytest.mark.asyncio
async def test_update_room_number_entity_writes_offset():
    coord = _make_coordinator()

    def _get(entity_id):
        if entity_id == "sensor.bathroom_temp":
            return _state("21.5")
        if entity_id == "climate.bathroom":
            s = _state("heat")
            s.attributes = {"current_temperature": 20.0}
            return s
        if entity_id == "number.bathroom_offset":
            return _state("0.0")
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)

    await engine._async_update_room(
        "Bathroom", "climate.bathroom", "sensor.bathroom_temp", "number.bathroom_offset"
    )

    coord.hass.services.async_call.assert_awaited_once_with(
        "number",
        "set_value",
        {"entity_id": "number.bathroom_offset", "value": 1.5},
        blocking=True,
    )
    assert engine._last_written["Bathroom"] == 1.5


# ── _async_update_room — select path (new) ────────────────────────────────


@pytest.mark.asyncio
async def test_update_room_select_entity_snaps_and_writes_option():
    coord = _make_coordinator()

    def _get(entity_id):
        if entity_id == "sensor.bathroom_temp":
            return _state("21.5")
        if entity_id == "climate.bathroom":
            s = _state("heat")
            s.attributes = {"current_temperature": 20.0}
            return s
        if entity_id == "select.bathroom_offset":
            return _state("0.0", options=["-1.0", "0.0", "1.0", "1.5", "2.0"])
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)

    # Residual is 1.5°C — snaps exactly onto the "1.5" option.
    await engine._async_update_room(
        "Bathroom", "climate.bathroom", "sensor.bathroom_temp", "select.bathroom_offset"
    )

    coord.hass.services.async_call.assert_awaited_once_with(
        "select",
        "select_option",
        {"entity_id": "select.bathroom_offset", "option": "1.5"},
        blocking=True,
    )
    assert engine._last_written["Bathroom"] == 1.5


@pytest.mark.asyncio
async def test_update_room_select_entity_reads_current_value_from_selected_option():
    """current_offset for a select entity comes from parsing its currently
    -selected option string, not from _read_float (which would fail on a
    non-numeric state like "1.5")."""
    coord = _make_coordinator()

    def _get(entity_id):
        if entity_id == "sensor.bathroom_temp":
            return _state("20.0")  # truth == raw → residual 0
        if entity_id == "climate.bathroom":
            s = _state("heat")
            s.attributes = {"current_temperature": 20.0}
            return s
        if entity_id == "select.bathroom_offset":
            # Already sitting on "1.0" — with a zero residual the engine
            # should re-select the SAME option (heartbeat), not drift to 0.
            return _state("1.0", options=["-1.0", "0.0", "1.0", "2.0"])
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)

    await engine._async_update_room(
        "Bathroom", "climate.bathroom", "sensor.bathroom_temp", "select.bathroom_offset"
    )

    coord.hass.services.async_call.assert_awaited_once_with(
        "select",
        "select_option",
        {"entity_id": "select.bathroom_offset", "option": "1.0"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_update_room_select_entity_no_parseable_options_skips_write():
    coord = _make_coordinator()

    def _get(entity_id):
        if entity_id == "sensor.bathroom_temp":
            return _state("21.5")
        if entity_id == "climate.bathroom":
            s = _state("heat")
            s.attributes = {"current_temperature": 20.0}
            return s
        if entity_id == "select.bathroom_offset":
            return _state("auto", options=["auto", "manual"])
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)

    await engine._async_update_room(
        "Bathroom", "climate.bathroom", "sensor.bathroom_temp", "select.bathroom_offset"
    )

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_room_unsupported_domain_skips_write():
    coord = _make_coordinator()

    def _get(entity_id):
        if entity_id == "sensor.bathroom_temp":
            return _state("21.5")
        if entity_id == "climate.bathroom":
            s = _state("heat")
            s.attributes = {"current_temperature": 20.0}
            return s
        return None

    coord.hass.states.get = MagicMock(side_effect=_get)
    engine = CalibrationEngine(coord)

    await engine._async_update_room(
        "Bathroom", "climate.bathroom", "sensor.bathroom_temp", "switch.bathroom_offset"
    )

    coord.hass.services.async_call.assert_not_awaited()
