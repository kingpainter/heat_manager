"""Tests for the per-room Netatmo restore (v0.63.0): async_release_netatmo_room
uses the owning integration's clear_temperature_setting (room only) instead
of preset_mode: schedule (home-level in Netatmo). Fully offline.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.presence_engine import PresenceEngine

# Module whose code these tests exercise (the coordinator is split into
# layers since v0.68.2 — patch names where they are used).
_COORD_MOD = "custom_components.heat_manager.coordinator.base"


def _coordinator(platform: str | None, setpoint_mode: str | None = "manual"):
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.states.get = MagicMock(
        return_value=SimpleNamespace(
            state="heat", attributes={"netatmo_setpoint_mode": setpoint_mode}
        )
    )
    coord._netatmo_call_lock = asyncio.Lock()
    for name in (
        "_entity_netatmo_backend",
        "async_call_netatmo_service",
        "async_call_climate_service",
        "async_release_netatmo_room",
    ):
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )
    registry = MagicMock()
    registry.async_get = MagicMock(
        return_value=SimpleNamespace(platform=platform) if platform else None
    )
    return coord, registry


async def _release(platform, setpoint_mode="manual"):
    coord, registry = _coordinator(platform, setpoint_mode)
    with (
        patch(
            f"{_COORD_MOD}.er.async_get",
            return_value=registry,
        ),
        patch(f"{_COORD_MOD}.asyncio.sleep", AsyncMock()),
    ):
        await coord.async_release_netatmo_room("climate.toilets")
    return coord.hass.services.async_call


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["net_trv", "netatmo"])
async def test_release_uses_owner_clear_temperature_setting(platform):
    call = await _release(platform)
    call.assert_awaited_once_with(
        platform,
        "clear_temperature_setting",
        {"entity_id": "climate.toilets"},
        blocking=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["schedule", "home"])
async def test_release_skipped_when_room_already_follows_schedule(mode):
    call = await _release("net_trv", mode)
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_unknown_owner_keeps_old_preset_call():
    call = await _release(None)
    call.assert_awaited_once_with(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.toilets", "preset_mode": "schedule"},
        blocking=True,
    )


# ── Home-level schedule once per restore sweep (F6) ──────────────────────────


@pytest.mark.asyncio
async def test_restore_all_schedule_sends_home_preset_once():
    coord = MagicMock()
    coord.rooms = [{"room_name": "Kitchen"}, {"room_name": "Bath"}]
    coord.get_room_state = MagicMock(return_value="away")
    coord.get_room_trvs = MagicMock(
        side_effect=lambda n: [{"climate_entity": f"climate.{n.lower()}"}]
    )
    coord.needs_cloud_delay = MagicMock(return_value=True)
    coord.async_call_climate_service = AsyncMock()
    coord.config = {"notify_presence": False}
    engine = PresenceEngine.__new__(PresenceEngine)
    engine.coordinator = coord
    engine._restore_lock = asyncio.Lock()
    engine._notify = AsyncMock()

    await PresenceEngine._restore_all_schedule.__wrapped__(engine, notify=False)

    coord.async_call_climate_service.assert_awaited_once()
    marked = {c.args[0] for c in coord.set_room_state.call_args_list}
    assert marked == {"Kitchen", "Bath"}
