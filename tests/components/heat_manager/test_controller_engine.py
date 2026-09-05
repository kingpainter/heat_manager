"""Tests for engine/controller.py — _apply_off_fallback() behaviour,
including B18 multi-TRV grouping (same fallback command fanned out to
every physical TRV in a room)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import (
    CONF_TRVS,
    EffectiveSeason,
)
from custom_components.heat_manager.engine.controller import ControllerEngine
from custom_components.heat_manager.migrations import migrate_room_to_trvs

# ── Coordinator factory ───────────────────────────────────────────────────────


def _make_coordinator(rooms=None, effective_season=EffectiveSeason.DORMANT):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.hass.services.async_call = AsyncMock()

    coordinator.rooms = rooms or []
    coordinator.effective_season = effective_season
    coordinator.config = {}

    # B18: _apply_off_fallback now fans out over get_room_trvs() /
    # get_trv_write_entity() instead of reading room-level flat fields.
    # Default to the flat-mirror migration the real coordinator uses at
    # read time, with no HomeKit entity (so get_trv_write_entity falls
    # back to the TRV's own climate_entity) — matching pre-existing
    # single-TRV behaviour exactly.
    def _room_trvs(room_name):
        room = next(
            (r for r in coordinator.rooms if r.get("room_name") == room_name), None
        )
        if room is None:
            return []
        return migrate_room_to_trvs(room).get(CONF_TRVS, [])

    def _trv_write_entity(trv):
        return trv.get("homekit_climate_entity") or trv.get("climate_entity")

    coordinator.get_room_trvs = MagicMock(side_effect=_room_trvs)
    coordinator.get_trv_write_entity = MagicMock(side_effect=_trv_write_entity)
    coordinator.needs_cloud_delay = MagicMock(return_value=False)

    return coordinator


def _make_room(name="Kitchen", climate="climate.kitchen"):
    return {"room_name": name, "climate_entity": climate}


def _make_room_with_trvs(name, trvs):
    return {"room_name": name, "trvs": trvs}


# ── DORMANT: hvac_mode off, HomeKit-preferred ─────────────────────────────────


@pytest.mark.asyncio
async def test_dormant_sets_hvac_off_via_write_entity():
    coordinator = _make_coordinator(
        rooms=[_make_room()], effective_season=EffectiveSeason.DORMANT
    )
    engine = ControllerEngine(coordinator)

    await engine._apply_off_fallback()

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.kitchen", "hvac_mode": "off"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_dormant_prefers_homekit_entity_when_available():
    room = _make_room_with_trvs(
        "Kitchen",
        [
            {
                "climate_entity": "climate.kitchen",
                "homekit_climate_entity": "climate.kitchen_homekit",
            }
        ],
    )
    coordinator = _make_coordinator(
        rooms=[room], effective_season=EffectiveSeason.DORMANT
    )
    engine = ControllerEngine(coordinator)

    await engine._apply_off_fallback()

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.kitchen_homekit", "hvac_mode": "off"},
        blocking=True,
    )


# ── ACTIVE/WAKING: preset_mode schedule, always cloud entity ─────────────────


@pytest.mark.asyncio
async def test_active_restores_preset_schedule_on_cloud_entity():
    coordinator = _make_coordinator(
        rooms=[_make_room()], effective_season=EffectiveSeason.ACTIVE
    )
    engine = ControllerEngine(coordinator)

    await engine._apply_off_fallback()

    coordinator.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.kitchen", "preset_mode": "schedule"},
        blocking=True,
    )


# ── B18: multi-TRV rooms get the same fallback fanned out ────────────────────


@pytest.mark.asyncio
async def test_dormant_multi_trv_room_sends_hvac_off_to_every_trv():
    room = _make_room_with_trvs(
        "Living room",
        [
            {"climate_entity": "climate.living_room"},
            {"climate_entity": "climate.living_room_trv2"},
        ],
    )
    coordinator = _make_coordinator(
        rooms=[room], effective_season=EffectiveSeason.DORMANT
    )
    engine = ControllerEngine(coordinator)

    await engine._apply_off_fallback()

    calls = coordinator.hass.services.async_call.await_args_list
    assert len(calls) == 2
    entity_ids = {c.args[2]["entity_id"] for c in calls}
    assert entity_ids == {"climate.living_room", "climate.living_room_trv2"}
    for c in calls:
        assert c.args[1] == "set_hvac_mode"
        assert c.args[2]["hvac_mode"] == "off"


@pytest.mark.asyncio
async def test_active_multi_trv_room_sends_preset_schedule_to_every_trv():
    room = _make_room_with_trvs(
        "Living room",
        [
            {"climate_entity": "climate.living_room"},
            {"climate_entity": "climate.living_room_trv2"},
        ],
    )
    coordinator = _make_coordinator(
        rooms=[room], effective_season=EffectiveSeason.ACTIVE
    )
    engine = ControllerEngine(coordinator)

    await engine._apply_off_fallback()

    calls = coordinator.hass.services.async_call.await_args_list
    assert len(calls) == 2
    entity_ids = {c.args[2]["entity_id"] for c in calls}
    assert entity_ids == {"climate.living_room", "climate.living_room_trv2"}
    for c in calls:
        assert c.args[1] == "set_preset_mode"
        assert c.args[2]["preset_mode"] == "schedule"


@pytest.mark.asyncio
async def test_room_with_no_trvs_is_skipped_without_error():
    coordinator = _make_coordinator(
        rooms=[{"room_name": "Empty"}], effective_season=EffectiveSeason.DORMANT
    )
    engine = ControllerEngine(coordinator)

    await engine._apply_off_fallback()

    coordinator.hass.services.async_call.assert_not_awaited()
