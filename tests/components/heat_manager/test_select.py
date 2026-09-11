"""Tests for select.py — ControllerStateSelect, SeasonModeSelect and
NetatmoPresetModeSelect (Fase 2, 2026-09-11).

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
    NetatmoPresetModeSelect,
    SeasonModeSelect,
    async_setup_entry,
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
    coord.room_device_info = MagicMock(
        side_effect=lambda name: {"identifiers": {("x", name)}}
    )

    # Fase 2 (2026-09-11): NetatmoPresetModeSelect fixtures.
    coord.rooms = []
    coord.get_all_room_trvs = MagicMock(return_value=[])
    coord.async_call_climate_service = AsyncMock()
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


# ── NetatmoPresetModeSelect (Fase 2, 2026-09-11) ────────────────────────────


def _netatmo_select(coord=None, room_name="Bathroom", climate_id="climate.bathroom"):
    coord = coord or _make_coordinator()
    return NetatmoPresetModeSelect(coord, _entry(), room_name, climate_id)


def test_netatmo_preset_select_unique_id_and_device_info():
    coord = _make_coordinator()
    select = _netatmo_select(coord, room_name="Living Room")
    assert select.unique_id == "entry123_living_room_netatmo_preset_mode"
    coord.room_device_info.assert_called_with("Living Room")


def test_netatmo_preset_select_available_true_when_state_reporting():
    coord = _make_coordinator()
    state = MagicMock()
    state.state = "heat"
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: state if eid == "climate.bathroom" else None
    )
    select = _netatmo_select(coord)
    assert select.available is True


@pytest.mark.parametrize("bad_state", ["unavailable", "unknown"])
def test_netatmo_preset_select_available_false_when_unavailable_or_missing(bad_state):
    coord = _make_coordinator()
    state = MagicMock()
    state.state = bad_state
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: state if eid == "climate.bathroom" else None
    )
    select = _netatmo_select(coord)
    assert select.available is False


def test_netatmo_preset_select_available_false_when_no_state_at_all():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    select = _netatmo_select(coord)
    assert select.available is False


def test_netatmo_preset_select_options_from_live_entity_attribute():
    coord = _make_coordinator()
    state = MagicMock()
    state.attributes = {"preset_modes": ["schedule", "away", "frost_guard", "boost"]}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: state if eid == "climate.bathroom" else None
    )
    select = _netatmo_select(coord)
    assert select.options == ["schedule", "away", "frost_guard", "boost"]


def test_netatmo_preset_select_options_falls_back_when_no_state():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    select = _netatmo_select(coord)
    assert select.options == ["schedule", "away", "frost_guard", "boost"]


def test_netatmo_preset_select_options_falls_back_when_attribute_missing():
    coord = _make_coordinator()
    state = MagicMock()
    state.attributes = {}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: state if eid == "climate.bathroom" else None
    )
    select = _netatmo_select(coord)
    assert select.options == ["schedule", "away", "frost_guard", "boost"]


def test_netatmo_preset_select_current_option_reads_preset_mode_attribute():
    coord = _make_coordinator()
    state = MagicMock()
    state.attributes = {"preset_mode": "away"}
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: state if eid == "climate.bathroom" else None
    )
    select = _netatmo_select(coord)
    assert select.current_option == "away"


def test_netatmo_preset_select_current_option_none_when_no_state():
    coord = _make_coordinator()
    coord.hass.states.get = MagicMock(return_value=None)
    select = _netatmo_select(coord)
    assert select.current_option is None


@pytest.mark.asyncio
async def test_netatmo_preset_select_option_calls_climate_service_with_delay():
    coord = _make_coordinator()
    select = _netatmo_select(coord, room_name="Bathroom", climate_id="climate.bathroom")

    await select.async_select_option("away")

    coord.async_call_climate_service.assert_awaited_once_with(
        "set_preset_mode",
        "climate.bathroom",
        {"preset_mode": "away"},
        needs_delay=True,
    )
    coord.log_event.assert_called_once()
    coord.async_update_listeners.assert_called_once()


# ── select.py async_setup_entry: NetatmoPresetModeSelect room fan-out ──────


def _mk_entry():
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


def _mk_add_entities():
    added: list = []
    return added, MagicMock(side_effect=lambda entities: added.extend(entities))


@pytest.mark.asyncio
async def test_setup_entry_adds_netatmo_select_for_netatmo_room():
    coord = _make_coordinator()
    coord.rooms = [{"room_name": "Bathroom"}]
    coord.get_all_room_trvs = MagicMock(
        return_value=[{"climate_entity": "climate.bathroom", "trv_type": "netatmo"}]
    )
    entry = _mk_entry()
    entry.runtime_data = coord
    added, add_entities = _mk_add_entities()

    await async_setup_entry(coord.hass, entry, add_entities)

    netatmo_selects = [e for e in added if isinstance(e, NetatmoPresetModeSelect)]
    assert len(netatmo_selects) == 1
    assert netatmo_selects[0]._climate_entity_id == "climate.bathroom"
    assert netatmo_selects[0]._room_name == "Bathroom"


@pytest.mark.asyncio
async def test_setup_entry_skips_netatmo_select_for_zigbee_room():
    coord = _make_coordinator()
    coord.rooms = [{"room_name": "Kitchen"}]
    coord.get_all_room_trvs = MagicMock(
        return_value=[{"climate_entity": "climate.kitchen", "trv_type": "zigbee"}]
    )
    entry = _mk_entry()
    entry.runtime_data = coord
    added, add_entities = _mk_add_entities()

    await async_setup_entry(coord.hass, entry, add_entities)

    assert not any(isinstance(e, NetatmoPresetModeSelect) for e in added)


@pytest.mark.asyncio
async def test_setup_entry_skips_room_without_climate_entity():
    coord = _make_coordinator()
    coord.rooms = [{"room_name": "Attic"}]
    coord.get_all_room_trvs = MagicMock(return_value=[])
    entry = _mk_entry()
    entry.runtime_data = coord
    added, add_entities = _mk_add_entities()

    await async_setup_entry(coord.hass, entry, add_entities)

    assert not any(isinstance(e, NetatmoPresetModeSelect) for e in added)


@pytest.mark.asyncio
async def test_setup_entry_always_adds_controller_and_season_selects():
    coord = _make_coordinator()
    coord.rooms = []
    entry = _mk_entry()
    entry.runtime_data = coord
    added, add_entities = _mk_add_entities()

    await async_setup_entry(coord.hass, entry, add_entities)

    assert any(isinstance(e, ControllerStateSelect) for e in added)
    assert any(isinstance(e, SeasonModeSelect) for e in added)
