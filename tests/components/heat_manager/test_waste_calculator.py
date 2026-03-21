"""Tests for WasteCalculator — Phase 3."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from custom_components.heat_manager.engine.waste_calculator import WasteCalculator
from custom_components.heat_manager.const import RoomState


def _make_coordinator(rooms=None, outdoor_temp=5.0) -> MagicMock:
    coord = MagicMock()
    coord.outdoor_temperature = outdoor_temp
    coord.rooms = rooms or []
    coord.room_states = {}

    def get_room_state(name):
        return coord.room_states.get(name, RoomState.NORMAL)
    coord.get_room_state.side_effect = get_room_state

    coord.hass = MagicMock()
    coord.hass.states = MagicMock()
    coord.hass.states.get.return_value = None
    return coord


def _climate_state(setpoint: float, current: float) -> MagicMock:
    s = MagicMock()
    s.attributes = {"temperature": setpoint, "current_temperature": current}
    return s


@pytest.mark.asyncio
async def test_zero_waste_when_no_windows_open():
    """No rooms in WINDOW_OPEN state → wasted stays 0."""
    coord = _make_coordinator(rooms=[{"room_name": "Kitchen", "climate_entity": "climate.kitchen"}])
    coord.room_states["Kitchen"] = RoomState.NORMAL
    engine = WasteCalculator(coord)

    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        from datetime import date
        mock_now.return_value = MagicMock(date=lambda: date(2026, 3, 1), hour=12)
        await engine.async_tick()

    assert engine.energy_wasted_today == 0.0


@pytest.mark.asyncio
async def test_waste_accumulates_when_window_open():
    """Window open with positive Δtemp → waste increases each tick."""
    coord = _make_coordinator(rooms=[{"room_name": "Kitchen", "climate_entity": "climate.kitchen"}])
    coord.room_states["Kitchen"] = RoomState.WINDOW_OPEN
    coord.hass.states.get.return_value = _climate_state(setpoint=21.0, current=15.0)

    engine = WasteCalculator(coord)

    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        from datetime import date
        mock_now.return_value = MagicMock(date=lambda: date(2026, 3, 1), hour=14)
        await engine.async_tick()
        await engine.async_tick()

    # 2 ticks × Δ6°C × (60/3600) h × 0.1 kWh/°C/h = 0.02 kWh
    assert engine.energy_wasted_today > 0.0
    assert engine.energy_wasted_today == pytest.approx(0.02, abs=0.001)


@pytest.mark.asyncio
async def test_no_waste_when_current_above_setpoint():
    """current_temp > setpoint → Δtemp is 0 → no waste."""
    coord = _make_coordinator(rooms=[{"room_name": "Living", "climate_entity": "climate.living"}])
    coord.room_states["Living"] = RoomState.WINDOW_OPEN
    coord.hass.states.get.return_value = _climate_state(setpoint=18.0, current=22.0)

    engine = WasteCalculator(coord)
    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        from datetime import date
        mock_now.return_value = MagicMock(date=lambda: date(2026, 3, 1), hour=10)
        await engine.async_tick()

    assert engine.energy_wasted_today == 0.0


@pytest.mark.asyncio
async def test_savings_accumulate_in_away_during_day():
    """Away rooms during daytime (6–23) should accumulate energy savings."""
    coord = _make_coordinator(rooms=[{"room_name": "Bedroom", "climate_entity": "climate.bedroom"}], outdoor_temp=0.0)
    coord.room_states["Bedroom"] = RoomState.AWAY

    engine = WasteCalculator(coord)
    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        from datetime import date
        mock_now.return_value = MagicMock(date=lambda: date(2026, 3, 1), hour=10)
        await engine.async_tick()

    # baseline_delta = 21 - 0 = 21°C, 1 tick
    expected = 21.0 * (60 / 3600) * 0.1
    assert engine.energy_saved_today == pytest.approx(expected, abs=0.001)


@pytest.mark.asyncio
async def test_no_savings_at_night():
    """Away rooms at night (hour < 6) should not accumulate savings."""
    coord = _make_coordinator(rooms=[{"room_name": "Bedroom", "climate_entity": "climate.bedroom"}], outdoor_temp=5.0)
    coord.room_states["Bedroom"] = RoomState.AWAY

    engine = WasteCalculator(coord)
    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        from datetime import date
        mock_now.return_value = MagicMock(date=lambda: date(2026, 3, 1), hour=3)
        await engine.async_tick()

    assert engine.energy_saved_today == 0.0


@pytest.mark.asyncio
async def test_midnight_reset():
    """Accumulated waste/savings reset when date changes."""
    coord = _make_coordinator(rooms=[{"room_name": "Kitchen", "climate_entity": "climate.kitchen"}])
    coord.room_states["Kitchen"] = RoomState.WINDOW_OPEN
    coord.hass.states.get.return_value = _climate_state(setpoint=21.0, current=15.0)

    engine = WasteCalculator(coord)

    from datetime import date as date_cls
    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        mock_now.return_value = MagicMock(date=lambda: date_cls(2026, 3, 1), hour=12)
        await engine.async_tick()

    assert engine.energy_wasted_today > 0.0
    pre_reset = engine.energy_wasted_today

    # Advance to next day
    with patch("custom_components.heat_manager.engine.waste_calculator.ha_now") as mock_now:
        mock_now.return_value = MagicMock(date=lambda: date_cls(2026, 3, 2), hour=0)
        await engine.async_tick()

    assert engine.energy_wasted_today < pre_reset  # reset then re-accumulated one tick


@pytest.mark.asyncio
async def test_efficiency_score_starts_at_100():
    """No waste → score should be 100."""
    coord = _make_coordinator()
    engine = WasteCalculator(coord)
    assert engine.efficiency_score == 100


@pytest.mark.asyncio
async def test_efficiency_score_decreases_with_waste():
    """Waste > 0 → score decreases."""
    coord = _make_coordinator(rooms=[{"room_name": "Kitchen", "climate_entity": "climate.kitchen"}])
    coord.room_states["Kitchen"] = RoomState.WINDOW_OPEN
    coord.hass.states.get.return_value = _climate_state(setpoint=21.0, current=15.0)

    engine = WasteCalculator(coord)
    engine._wasted_kwh = 0.5  # inject directly

    assert engine.efficiency_score == 50


@pytest.mark.asyncio
async def test_efficiency_score_floor_zero():
    """Very high waste → score floors at 0, never negative."""
    coord = _make_coordinator()
    engine = WasteCalculator(coord)
    engine._wasted_kwh = 5.0
    assert engine.efficiency_score == 0


@pytest.mark.asyncio
async def test_shutdown():
    coord = _make_coordinator()
    engine = WasteCalculator(coord)
    await engine.async_shutdown()
