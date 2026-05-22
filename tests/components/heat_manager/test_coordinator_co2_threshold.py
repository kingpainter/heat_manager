"""Tests for coordinator.get_room_co2_threshold().

Covers:
- Returns DEFAULT_CO2_VENTILATION_THRESHOLD when no per-room override
- Returns per-room value when CONF_CO2_THRESHOLD is set
- Ignores invalid (non-numeric) override → falls back to default
- Returns default for unknown room name
- WasteCalculator and WindowEngine use per-room threshold via coordinator helper
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from custom_components.heat_manager.const import (
    CONF_CO2_THRESHOLD,
    DEFAULT_CO2_VENTILATION_THRESHOLD,
    RoomState,
)


def _make_coordinator(rooms: list[dict]) -> MagicMock:
    """Return a coordinator mock with real get_room_co2_threshold bound."""
    coord = MagicMock()
    coord.rooms = rooms
    from custom_components.heat_manager.coordinator import HeatManagerCoordinator
    coord.get_room_co2_threshold = HeatManagerCoordinator.get_room_co2_threshold.__get__(
        coord, type(coord)
    )
    return coord


# ── get_room_co2_threshold ────────────────────────────────────────────────────

def test_returns_default_when_no_override():
    """Room with no co2_threshold → global default returned."""
    coord = _make_coordinator([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    assert coord.get_room_co2_threshold("Stue") == DEFAULT_CO2_VENTILATION_THRESHOLD


def test_returns_per_room_override():
    """Room with co2_threshold = 1200 → 1200 returned."""
    coord = _make_coordinator([{
        "room_name": "Soveværelse",
        "climate_entity": "climate.sove",
        CONF_CO2_THRESHOLD: 1200,
    }])
    assert coord.get_room_co2_threshold("Soveværelse") == 1200


def test_invalid_override_falls_back_to_default():
    """Non-numeric co2_threshold → ignored, default returned."""
    coord = _make_coordinator([{
        "room_name": "Kontor",
        "climate_entity": "climate.kontor",
        CONF_CO2_THRESHOLD: "not_a_number",
    }])
    assert coord.get_room_co2_threshold("Kontor") == DEFAULT_CO2_VENTILATION_THRESHOLD


def test_unknown_room_returns_default():
    """Room not in list → default returned without raising."""
    coord = _make_coordinator([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    assert coord.get_room_co2_threshold("UnknownRoom") == DEFAULT_CO2_VENTILATION_THRESHOLD


def test_zero_threshold_accepted():
    """co2_threshold = 0 is a valid (if extreme) override."""
    coord = _make_coordinator([{
        "room_name": "Lager",
        "climate_entity": "climate.lager",
        CONF_CO2_THRESHOLD: 0,
    }])
    assert coord.get_room_co2_threshold("Lager") == 0


def test_float_threshold_converted_to_int():
    """co2_threshold = 1100.5 → returned as int 1100."""
    coord = _make_coordinator([{
        "room_name": "Bad",
        "climate_entity": "climate.bad",
        CONF_CO2_THRESHOLD: 1100.5,
    }])
    assert coord.get_room_co2_threshold("Bad") == 1100


# ── WasteCalculator uses per-room threshold ───────────────────────────────────

@pytest.mark.asyncio
async def test_waste_calculator_uses_per_room_threshold():
    """WasteCalculator._co2_waste_weight() must use get_room_co2_threshold()."""
    from custom_components.heat_manager.engine.waste_calculator import WasteCalculator

    coord = MagicMock()
    coord.rooms = [{
        "room_name": "Stue",
        "climate_entity": "climate.stue",
        CONF_CO2_THRESHOLD: 1500,  # high threshold — CO₂ at 1000 should NOT reduce waste
    }]
    coord.get_room_co2_threshold = MagicMock(return_value=1500)
    coord.get_room_co2 = MagicMock(return_value=1000.0)   # below 1500
    coord.is_raining = MagicMock(return_value=False)

    engine = WasteCalculator(coord)
    weight = engine._co2_waste_weight("Stue")

    # CO₂ 1000 < threshold 1500 → full waste (1.0)
    coord.get_room_co2_threshold.assert_called_once_with("Stue")
    assert weight == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_waste_calculator_reduces_waste_above_per_room_threshold():
    """CO₂ above per-room threshold → waste weight 0.50."""
    from custom_components.heat_manager.engine.waste_calculator import WasteCalculator

    coord = MagicMock()
    coord.rooms = [{"room_name": "Stue", "climate_entity": "climate.stue", CONF_CO2_THRESHOLD: 800}]
    coord.get_room_co2_threshold = MagicMock(return_value=800)
    coord.get_room_co2 = MagicMock(return_value=1000.0)   # above 800
    coord.is_raining = MagicMock(return_value=False)

    engine = WasteCalculator(coord)
    weight = engine._co2_waste_weight("Stue")

    assert weight == pytest.approx(0.50)


# ── WindowEngine uses per-room threshold ─────────────────────────────────────

def test_window_engine_co2_label_uses_per_room_threshold():
    """_co2_context_label() with room_name must call get_room_co2_threshold()."""
    from custom_components.heat_manager.engine.window_engine import WindowEngine

    coord = MagicMock()
    coord.rooms = []
    coord.config = {}
    coord.is_raining = MagicMock(return_value=False)
    coord.get_wind_speed = MagicMock(return_value=None)
    coord.get_room_co2_threshold = MagicMock(return_value=1000)

    engine = WindowEngine.__new__(WindowEngine)
    engine.coordinator = coord
    engine._sensor_to_room = {}
    engine._sensor_to_away_temp = {}
    engine._window_opened_at = {}
    engine._warning_sent = {}
    engine._open_tasks = {}
    engine._close_tasks = {}
    engine._unsubs = []

    label = engine._co2_context_label(co2_ppm=1200.0, room_name="Stue")

    coord.get_room_co2_threshold.assert_called_once_with("Stue")
    assert "ventilation" in label


def test_window_engine_co2_label_no_room_uses_global_default():
    """_co2_context_label() without room_name falls back to global constant."""
    from custom_components.heat_manager.engine.window_engine import WindowEngine

    coord = MagicMock()
    coord.rooms = []
    coord.config = {}
    coord.is_raining = MagicMock(return_value=False)
    coord.get_wind_speed = MagicMock(return_value=None)
    coord.get_room_co2_threshold = MagicMock()

    engine = WindowEngine.__new__(WindowEngine)
    engine.coordinator = coord
    engine._sensor_to_room = {}
    engine._sensor_to_away_temp = {}
    engine._window_opened_at = {}
    engine._warning_sent = {}
    engine._open_tasks = {}
    engine._close_tasks = {}
    engine._unsubs = []

    # Call without room_name — get_room_co2_threshold must NOT be called
    engine._co2_context_label(co2_ppm=500.0)
    coord.get_room_co2_threshold.assert_not_called()
