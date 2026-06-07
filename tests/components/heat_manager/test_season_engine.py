"""Tests for SeasonEngine — B4/B9 update: uses EffectiveSeason, not SeasonMode."""
from __future__ import annotations

from datetime import date as date_type
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.heat_manager.engine.season_engine import SeasonEngine
from custom_components.heat_manager.const import (
    SeasonMode,
    EffectiveSeason,
    CONF_INDOOR_WAKE_SENSOR,
    CONF_INDOOR_WAKE_THRESHOLD,
)


def _make_coordinator(
    season_mode: SeasonMode = SeasonMode.AUTO,
    outdoor_temp: float | None = 10.0,
    auto_off_threshold: float = 18.0,
    auto_off_days: int = 5,
) -> MagicMock:
    coord = MagicMock()
    coord.season_mode = season_mode
    coord.outdoor_temperature = outdoor_temp
    coord.effective_season = EffectiveSeason.ACTIVE  # B4: now EffectiveSeason, not SeasonMode
    coord.config = {
        "auto_off_temp_threshold": auto_off_threshold,
        "auto_off_temp_days": auto_off_days,
    }
    coord.async_house_voice_say = AsyncMock()
    coord.hass = MagicMock()
    coord.hass.states.get.return_value = None  # no indoor_wake_sensor by default
    return coord


def _mock_ha_now(date: date_type) -> MagicMock:
    """Return a ha_now mock whose .date() returns a real datetime.date."""
    mock = MagicMock()
    mock.return_value.date.return_value = date
    return mock


PATCH_PATH = "custom_components.heat_manager.engine.season_engine.ha_now"


@pytest.mark.asyncio
async def test_no_op_when_manual_winter():
    """Manual WINTER mode — engine maps WINTER → EffectiveSeason.ACTIVE."""
    coord = _make_coordinator(season_mode=SeasonMode.WINTER, outdoor_temp=25.0)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.ACTIVE


@pytest.mark.asyncio
async def test_no_op_when_manual_summer():
    """Manual SUMMER mode — engine maps SUMMER → EffectiveSeason.DORMANT."""
    coord = _make_coordinator(season_mode=SeasonMode.SUMMER, outdoor_temp=5.0)
    engine = SeasonEngine(coord)
    await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.DORMANT


@pytest.mark.asyncio
async def test_stays_winter_when_below_threshold():
    """Cold outdoor temp in spring — should remain ACTIVE (was WINTER)."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)
    with patch(PATCH_PATH) as mock_now:
        mock_now.return_value.date.return_value = date_type(2026, 4, 1)  # April = Spring
        await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.ACTIVE
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
async def test_switches_to_dormant_after_n_days():
    """After N consecutive warm days in spring, effective_season becomes DORMANT."""
    coord = _make_coordinator(outdoor_temp=22.0, auto_off_threshold=18.0, auto_off_days=3)
    engine = SeasonEngine(coord)
    for i in range(3):
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = date_type(2026, 4, i + 1)
            await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.DORMANT


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
    assert coord.effective_season == EffectiveSeason.ACTIVE


@pytest.mark.asyncio
async def test_no_op_without_outdoor_temperature():
    """No weather entity / no outdoor temp — engine falls back to ACTIVE."""
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
async def test_waking_phase_when_indoor_warm():
    """B9: WAKING phase activates when indoor sensor exceeds wake threshold."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=5)
    coord.config = {
        "auto_off_temp_threshold": 18.0,
        "auto_off_temp_days": 5,
        CONF_INDOOR_WAKE_SENSOR: "sensor.living_room_temp",
        CONF_INDOOR_WAKE_THRESHOLD: 21.0,
    }
    indoor_state = MagicMock()
    indoor_state.state = "22.5"  # above 21.0 threshold
    coord.hass.states.get.return_value = indoor_state
    engine = SeasonEngine(coord)
    with patch(PATCH_PATH) as mock_now:
        mock_now.return_value.date.return_value = date_type(2026, 4, 1)  # Spring
        await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.WAKING


@pytest.mark.asyncio
async def test_active_phase_when_indoor_cold():
    """B9: ACTIVE phase when indoor sensor is below wake threshold."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=5)
    coord.config = {
        "auto_off_temp_threshold": 18.0,
        "auto_off_temp_days": 5,
        CONF_INDOOR_WAKE_SENSOR: "sensor.living_room_temp",
        CONF_INDOOR_WAKE_THRESHOLD: 21.0,
    }
    indoor_state = MagicMock()
    indoor_state.state = "19.0"  # below 21.0 threshold
    coord.hass.states.get.return_value = indoor_state
    engine = SeasonEngine(coord)
    with patch(PATCH_PATH) as mock_now:
        mock_now.return_value.date.return_value = date_type(2026, 4, 1)
        await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.ACTIVE


@pytest.mark.asyncio
async def test_waking_falls_back_to_active_without_sensor():
    """B9: Without indoor_wake_sensor configured, engine always returns ACTIVE."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=5)
    # No CONF_INDOOR_WAKE_SENSOR in config
    coord.hass.states.get.return_value = None
    engine = SeasonEngine(coord)
    with patch(PATCH_PATH) as mock_now:
        mock_now.return_value.date.return_value = date_type(2026, 4, 1)
        await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.ACTIVE


@pytest.mark.asyncio
async def test_dormant_not_overridden_by_waking_check():
    """B9: DORMANT (summer) is never downgraded to WAKING regardless of indoor temp."""
    coord = _make_coordinator(outdoor_temp=10.0, auto_off_threshold=18.0, auto_off_days=3)
    coord.config = {
        "auto_off_temp_threshold": 18.0,
        "auto_off_temp_days": 3,
        CONF_INDOOR_WAKE_SENSOR: "sensor.living_room_temp",
        CONF_INDOOR_WAKE_THRESHOLD: 21.0,
    }
    indoor_state = MagicMock()
    indoor_state.state = "25.0"  # very warm — would trigger WAKING if not DORMANT
    coord.hass.states.get.return_value = indoor_state
    engine = SeasonEngine(coord)
    # 3 warm outdoor days → DORMANT
    coord.outdoor_temperature = 22.0
    for i in range(3):
        with patch(PATCH_PATH) as mock_now:
            mock_now.return_value.date.return_value = date_type(2026, 4, i + 1)
            await engine.async_tick()
    assert coord.effective_season == EffectiveSeason.DORMANT  # not WAKING


@pytest.mark.asyncio
async def test_shutdown():
    """async_shutdown must complete without error."""
    coord = _make_coordinator()
    engine = SeasonEngine(coord)
    await engine.async_shutdown()
