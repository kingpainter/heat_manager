"""Tests for coordinator.room_override_source (v0.14.0).

Covers:
- async_set_room_override() records who engaged OVERRIDE ("switch" by
  default, or an explicit source= such as "remote" from RemoteButtonEngine).
- set_room_state() clears a room's recorded source the moment it leaves
  OVERRIDE, from ANY code path — not just async_set_room_override(False) —
  since presence/window restore and sync_engine can also move a room out of
  (or, for sync_engine, directly into) OVERRIDE without going through it.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock,
with the real coordinator methods bound onto the mock (same pattern as
test_coordinator_night_setback.py) so the actual logic is exercised.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import CONF_CLIMATE_ENTITY, RoomState
from custom_components.heat_manager.coordinator import HeatManagerCoordinator


def _make_coordinator(trvs: list[dict] | None = None) -> MagicMock:
    """Minimal coordinator mock with the real async_set_room_override() /
    set_room_state() bound on, so these tests exercise the actual
    room_override_source bookkeeping rather than a mocked no-op."""
    coord = MagicMock()
    coord.async_set_room_override = (
        HeatManagerCoordinator.async_set_room_override.__get__(coord, type(coord))
    )
    coord.set_room_state = HeatManagerCoordinator.set_room_state.__get__(
        coord, type(coord)
    )

    coord.room_states: dict[str, RoomState] = {}
    coord.room_override_source: dict[str, str] = {}
    coord.async_update_listeners = MagicMock()

    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.get_trv_write_entity = MagicMock(return_value=None)
    coord.get_room_trvs = MagicMock(
        return_value=trvs if trvs is not None else [{CONF_CLIMATE_ENTITY: "climate.x"}]
    )
    # 2026-10-30: TRV writes go through async_call_climate_service()
    # (2026-09-16 audit fix) — without these the mock silently fails every
    # write and no source is ever recorded.
    coord.async_call_climate_service = AsyncMock()

    # v0.63.0: per-room Netatmo restore goes through
    # async_release_netatmo_room() (clear_temperature_setting on the owning
    # integration) instead of the home-level preset_mode: schedule.
    async def _release(entity_id):
        return await coord.hass.services.async_call(
            "net_trv",
            "clear_temperature_setting",
            {"entity_id": entity_id},
            blocking=True,
        )

    coord.async_release_netatmo_room = AsyncMock(side_effect=_release)
    coord.trv_needs_cloud_delay = MagicMock(return_value=False)
    coord.async_restore_room_schedule = AsyncMock(return_value="climate.x")

    return coord


# ── async_set_room_override: recording the source ────────────────────────────


@pytest.mark.asyncio
async def test_default_source_is_switch():
    coord = _make_coordinator()

    await coord.async_set_room_override("Living room", True)

    assert coord.room_override_source["Living room"] == "switch"


@pytest.mark.asyncio
async def test_explicit_remote_source_is_recorded():
    coord = _make_coordinator()

    await coord.async_set_room_override("Living room", True, source="remote")

    assert coord.room_override_source["Living room"] == "remote"


@pytest.mark.asyncio
async def test_no_trvs_records_no_source():
    """enable=True with nothing to actually turn on must not fake a source."""
    coord = _make_coordinator(trvs=[])

    ok = await coord.async_set_room_override("Living room", True, source="remote")

    assert ok is False
    assert "Living room" not in coord.room_override_source


@pytest.mark.asyncio
async def test_disable_does_not_itself_write_a_source():
    """enable=False never sets a source — it goes through set_room_state(),
    which is what actually clears any existing one (see tests below)."""
    coord = _make_coordinator()

    await coord.async_set_room_override("Living room", False)

    assert "Living room" not in coord.room_override_source


# ── set_room_state: clearing a stale source ──────────────────────────────────


def test_leaving_override_clears_its_source():
    coord = _make_coordinator()
    coord.room_override_source["Living room"] = "remote"

    coord.set_room_state("Living room", RoomState.NORMAL)

    assert "Living room" not in coord.room_override_source


def test_leaving_override_for_any_state_clears_source():
    """Not just NORMAL — WINDOW_OPEN/AWAY/PRE_HEAT taking over from OVERRIDE
    (e.g. presence/window engines restoring control) must clear it too."""
    coord = _make_coordinator()
    coord.room_override_source["Living room"] = "switch"

    coord.set_room_state("Living room", RoomState.WINDOW_OPEN)

    assert "Living room" not in coord.room_override_source


def test_re_entering_override_keeps_its_source():
    """A no-op re-set (already OVERRIDE, called again) must not wipe the
    source that was just recorded — set_room_state()'s early return for an
    unchanged state must not have already cleared it first."""
    coord = _make_coordinator()
    coord.room_override_source["Living room"] = "remote"

    coord.set_room_state("Living room", RoomState.OVERRIDE)

    assert coord.room_override_source["Living room"] == "remote"


def test_clearing_one_rooms_source_does_not_touch_another():
    coord = _make_coordinator()
    coord.room_override_source["Living room"] = "remote"
    coord.room_override_source["Bathroom"] = "switch"

    coord.set_room_state("Living room", RoomState.NORMAL)

    assert "Living room" not in coord.room_override_source
    assert coord.room_override_source["Bathroom"] == "switch"


def test_no_stale_source_is_a_no_op():
    """A room with no recorded source leaving OVERRIDE must not raise."""
    coord = _make_coordinator()

    coord.set_room_state("Living room", RoomState.NORMAL)  # must not raise

    assert "Living room" not in coord.room_override_source


# ── B23: "back to auto" restores the schedule ────────────────────────────────


@pytest.mark.asyncio
async def test_bug_b23_disable_restores_room_schedule():
    """Regression: enable=False used to only flip the state flag, so a
    Netatmo TRV left on a manual setpoint by the remote's +/- buttons kept
    that setpoint after "back to auto"."""
    coord = _make_coordinator()
    coord.room_states["Living room"] = RoomState.OVERRIDE

    ok = await coord.async_set_room_override("Living room", False)

    assert ok is True
    coord.async_restore_room_schedule.assert_awaited_once_with("Living room")
    assert coord.room_states["Living room"] == RoomState.NORMAL


@pytest.mark.asyncio
async def test_disable_still_returns_to_normal_when_restore_fails():
    coord = _make_coordinator()
    coord.room_states["Living room"] = RoomState.OVERRIDE
    coord.async_restore_room_schedule = AsyncMock(side_effect=RuntimeError("429"))

    ok = await coord.async_set_room_override("Living room", False)

    assert ok is True
    assert coord.room_states["Living room"] == RoomState.NORMAL
