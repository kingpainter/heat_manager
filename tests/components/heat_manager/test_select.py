"""Tests for select.py — ControllerStateSelect and SeasonModeSelect.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import (
    AutoOffReason,
    ControllerState,
    EffectiveSeason,
    SeasonMode,
)
from custom_components.heat_manager.select import (
    ControllerStateSelect,
    SeasonModeSelect,
)

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    coord = MagicMock()

    ctrl = MagicMock()
    ctrl.state = ControllerState.ON
    ctrl.set_state = AsyncMock()
    coord.controller = ctrl

    coord.auto_off_reason = AutoOffReason.NONE
    coord.pause_remaining_minutes = 0
    coord.effective_season = EffectiveSeason.ACTIVE
    coord.global_blocking_sources = MagicMock(return_value=[])

    coord.season_mode = SeasonMode.AUTO
    season_engine = MagicMock()
    season_engine.calendar_season = SeasonMode.WINTER
    season_engine.days_above_threshold = 0
    coord.season_engine = season_engine

    entry = MagicMock()
    entry.options = {}
    coord.entry = entry
    coord.hass = MagicMock()
    coord.hass.config_entries.async_update_entry = MagicMock()
    coord.log_event = MagicMock()
    coord.async_update_listeners = MagicMock()

    coord.global_device_info = MagicMock(return_value={"identifiers": {("x", "y")}})
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


# ── ControllerStateSelect ────────────────────────────────────────────────────


def test_controller_state_current_option_reads_coordinator():
    coord = _make_coordinator()
    coord.controller.state = ControllerState.PAUSE
    select = ControllerStateSelect(coord, _entry())
    assert select.current_option == "pause"
    assert select.unique_id == "entry123_controller_state"


def test_controller_state_extra_state_attributes_shape():
    coord = _make_coordinator()
    coord.auto_off_reason = AutoOffReason.SEASON
    coord.pause_remaining_minutes = 7
    coord.global_blocking_sources = MagicMock(return_value=["window"])
    select = ControllerStateSelect(coord, _entry())

    attrs = select.extra_state_attributes
    assert attrs["auto_off_reason"] == "season"
    assert attrs["pause_remaining"] == 7
    assert attrs["effective_season"] == "active"
    assert attrs["blocking_sources"] == ["window"]


@pytest.mark.asyncio
async def test_controller_state_select_option_valid_delegates_to_controller():
    coord = _make_coordinator()
    select = ControllerStateSelect(coord, _entry())

    await select.async_select_option("off")

    coord.controller.set_state.assert_awaited_once_with(ControllerState.OFF)


@pytest.mark.asyncio
async def test_controller_state_select_option_invalid_is_ignored():
    coord = _make_coordinator()
    select = ControllerStateSelect(coord, _entry())

    await select.async_select_option("not_a_real_state")

    coord.controller.set_state.assert_not_called()


# ── SeasonModeSelect ─────────────────────────────────────────────────────────


def test_season_mode_current_option_reads_coordinator():
    coord = _make_coordinator()
    coord.season_mode = SeasonMode.SUMMER
    select = SeasonModeSelect(coord, _entry())
    assert select.current_option == "summer"
    assert select.unique_id == "entry123_season_mode"


def test_season_mode_extra_state_attributes_shape():
    coord = _make_coordinator()
    coord.effective_season = EffectiveSeason.DORMANT
    coord.season_engine.calendar_season = SeasonMode.SUMMER
    coord.season_engine.days_above_threshold = 4
    select = SeasonModeSelect(coord, _entry())

    attrs = select.extra_state_attributes
    assert attrs["effective_season"] == "dormant"
    assert attrs["calendar_season"] == "summer"
    assert attrs["days_above_threshold"] == 4


@pytest.mark.asyncio
async def test_season_mode_select_option_valid_persists_and_notifies():
    coord = _make_coordinator()
    coord.entry.options = {"alarm_panel": "alarm_control_panel.house"}
    select = SeasonModeSelect(coord, _entry())

    await select.async_select_option("summer")

    assert coord.season_mode == SeasonMode.SUMMER
    coord.hass.config_entries.async_update_entry.assert_called_once_with(
        coord.entry,
        options={
            "alarm_panel": "alarm_control_panel.house",
            "season_mode": "summer",
        },
    )
    coord.log_event.assert_called_once()
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_season_mode_select_option_invalid_is_ignored():
    coord = _make_coordinator()
    coord.season_mode = SeasonMode.AUTO
    select = SeasonModeSelect(coord, _entry())

    await select.async_select_option("not_a_real_season")

    assert coord.season_mode == SeasonMode.AUTO
    coord.hass.config_entries.async_update_entry.assert_not_called()
    coord.log_event.assert_not_called()
    coord.async_update_listeners.assert_not_called()
