"""Tests for SeasonEngine — Phase 3."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
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
    return coord


@pytest.mark.asyncio
async def test_no_op_when_manual_winter():
    """Manual WINTER mode — season engine must not touch effective_season."""
    coord = _make_coordinator(season_mode=SeasonMode.WINTER, outdoor_temp=25.0)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    assert coord.effective_season == SeasonMode.WINTER


@pytest.mark.asyncio
async def test_no_op_when_manual_summer():
    """Manual SUMMER mode — no-op."""
    coord = _make_coordinator(season_mode=SeasonMode.SUMMER, outdoor_temp=5.0)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    # effective_season not written by engine when manual
    assert coord.effective_season == SeasonMode.WINTER  # unchanged from init


@pytest.mark.asyncio
async def test_stays_winter_when_below_threshold():
    """Cold outdoor temp — should remain WINTER."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)
    with patch("custom_components.heat_manager.engine.season_engine.ha_now") as mock_now:
        mock_now.return_value = MagicMock(date=lambda: MagicMock(isoformat=lambda: "2026-01-01"))
        await engine.async_tick()
    assert coord.effective_season == SeasonMode.WINTER
    assert engine.days_above_threshold == 0


@pytest.mark.asyncio
async def test_increments_days_above_threshold():
    """Warm outdoor temp — days_above counter should increment once per calendar day."""
    coord = _make_coordinator(outdoor_temp=20.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)

    dates = ["2026-06-01", "2026-06-02", "2026-06-03"]
    for d in dates:
        with patch("custom_components.heat_manager.engine.season_engine.ha_now") as mock_now:
            mock_now.return_value = MagicMock(date=lambda _d=d: MagicMock(isoformat=lambda: _d))
            await engine.async_tick()

    assert engine.days_above_threshold == 3


@pytest.mark.asyncio
async def test_switches_to_summer_after_n_days():
    """After N consecutive warm days, effective_season becomes SUMMER."""
    coord = _make_coordinator(outdoor_temp=22.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)

    for i in range(3):
        with patch("custom_components.heat_manager.engine.season_engine.ha_now") as mock_now:
            d = f"2026-06-0{i+1}"
            mock_now.return_value = MagicMock(date=lambda _d=d: MagicMock(isoformat=lambda: _d))
            await engine.async_tick()

    assert coord.effective_season == SeasonMode.SUMMER


@pytest.mark.asyncio
async def test_counter_resets_on_cold_day():
    """One cold day after warm days should reset the counter to 0."""
    coord = _make_coordinator(outdoor_temp=20.0, auto_off_threshold=18.0, auto_off_days=5)
    engine = SeasonEngine(coord)

    # 2 warm days
    for i in range(2):
        coord.outdoor_temperature = 22.0
        with patch("custom_components.heat_manager.engine.season_engine.ha_now") as mock_now:
            d = f"2026-06-0{i+1}"
            mock_now.return_value = MagicMock(date=lambda _d=d: MagicMock(isoformat=lambda: _d))
            await engine.async_tick()

    assert engine.days_above_threshold == 2

    # One cold day resets
    coord.outdoor_temperature = 5.0
    with patch("custom_components.heat_manager.engine.season_engine.ha_now") as mock_now:
        mock_now.return_value = MagicMock(date=lambda: MagicMock(isoformat=lambda: "2026-06-03"))
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

    for _ in range(5):  # 5 ticks, same date
        with patch("custom_components.heat_manager.engine.season_engine.ha_now") as mock_now:
            mock_now.return_value = MagicMock(date=lambda: MagicMock(isoformat=lambda: "2026-06-01"))
            await engine.async_tick()

    assert engine.days_above_threshold == 1  # counted only once


@pytest.mark.asyncio
async def test_shutdown():
    """async_shutdown must complete without error."""
    coord = _make_coordinator()
    engine = SeasonEngine(coord)
    await engine.async_shutdown()
