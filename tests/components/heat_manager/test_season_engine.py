"""Tests for SeasonEngine — Phase 3."""
from __future__ import annotations

from datetime import date as date_type
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.heat_manager.engine.season_engine import SeasonEngine
from custom_components.heat_manager.const import SeasonMode


def _make_coordinator(
    season_mode: SeasonMode = SeasonMode.AUTO,
    outdoor_temp: float | None = 10.0,
    auto_off_threshold: float = 18.0,
    auto_off_days: int = 5,
) -> MagicMock:
    coord = MagicMock()
    coord.season_mode = season_mode
    coord.outdoor_temperature = outdoor_temp
    coord.effective_season = SeasonMode.WINTER
    coord.config = {
        "auto_off_temp_threshold": auto_off_threshold,
        "auto_off_temp_days": auto_off_days,
    }
    coord.async_house_voice_say = AsyncMock()
    return coord


def _mock_ha_now(date: date_type) -> MagicMock:
    """Return a ha_now mock whose .date() returns a real datetime.date."""
    mock = MagicMock()
    mock.return_value.date.return_value = date
    return mock


PATCH_PATH = "custom_components.heat_manager.engine.season_engine.ha_now"


@pytest.mark.asyncio
async def test_no_op_when_manual_winter():
    """Manual WINTER mode — season engine must not touch effective_season."""
    coord = _make_coordinator(season_mode=SeasonMode.WINTER, outdoor_temp=25.0)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    assert coord.effective_season == SeasonMode.WINTER


@pytest.mark.asyncio
async def test_no_op_when_manual_summer():
    """Manual SUMMER mode — engine sets effective_season to SUMMER and returns."""
    coord = _make_coordinator(season_mode=SeasonMode.SUMMER, outdoor_temp=5.0)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    assert coord.effective_season == SeasonMode.SUMMER


@pytest.mark.asyncio
async def test_stays_winter_when_below_threshold():
    """Cold outdoor temp in spring — should remain WINTER."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)
    with patch(PATCH_PATH, new=_mock_ha_now(date_type(2026, 4, 1)).return_value):  # April = Spring
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = date_type(2026, 4, 1)
            await engine.async_tick()
    assert coord.effective_season == SeasonMode.WINTER
    assert engine.days_above_threshold == 0


@pytest.mark.asyncio
async def test_increments_days_above_threshold():
    """Warm outdoor temp in spring — days_above counter increments once per day."""
    coord = _make_coordinator(outdoor_temp=20.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)
    dates = [date_type(2026, 4, d) for d in range(1, 4)]
    for d in dates:
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = d
            await engine.async_tick()
    assert engine.days_above_threshold == 3


@pytest.mark.asyncio
async def test_switches_to_summer_after_n_days():
    """After N consecutive warm days in spring, effective_season becomes SUMMER."""
    coord = _make_coordinator(outdoor_temp=22.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)
    for i in range(3):
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = date_type(2026, 4, i + 1)
            await engine.async_tick()
    assert coord.effective_season == SeasonMode.SUMMER


@pytest.mark.asyncio
async def test_counter_resets_on_cold_day():
    """One cold day after warm days should reset the counter to 0."""
    coord = _make_coordinator(outdoor_temp=22.0, auto_off_threshold=18.0, auto_off_days=5)
    engine = SeasonEngine(coord)
    # 2 warm days in spring
    for i in range(2):
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = date_type(2026, 4, i + 1)
            await engine.async_tick()
    assert engine.days_above_threshold == 2
    # One cold day resets
    coord.outdoor_temperature = 5.0
    with patch(PATCH_PATH) as mock_now:
        mock_now.return_value.date.return_value = date_type(2026, 4, 3)
        await engine.async_tick()
    assert engine.days_above_threshold == 0
    assert coord.effective_season == SeasonMode.WINTER


@pytest.mark.asyncio
async def test_no_op_without_outdoor_temperature():
    """No weather entity / no outdoor temp — engine should be a no-op."""
    coord = _make_coordinator(outdoor_temp=None)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    assert engine.days_above_threshold == 0


@pytest.mark.asyncio
async def test_same_day_tick_does_not_double_count():
    """Multiple ticks on the same calendar day must not increment counter twice."""
    coord = _make_coordinator(outdoor_temp=22.0, auto_off_threshold=18.0, auto_off_days=5)
    engine = SeasonEngine(coord)
    for _ in range(5):
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = date_type(2026, 4, 1)
            await engine.async_tick()
    assert engine.days_above_threshold == 1


@pytest.mark.asyncio
async def test_shutdown():
    """async_shutdown must complete without error."""
    coord = _make_coordinator()
    engine = SeasonEngine(coord)
    await engine.async_shutdown()
