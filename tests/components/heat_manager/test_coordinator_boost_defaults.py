"""Tests for coordinator.async_boost_start()'s default temperature/duration
resolution (2026-09-13).

Covers: falls back to the configured CONF_BOOST_DEFAULT_TEMP/
CONF_BOOST_DEFAULT_MINUTES options when the caller doesn't specify its own,
falls back further to DEFAULT_BOOST_TEMP/DEFAULT_BOOST_MINUTES when those
options aren't set either, and an explicit caller-supplied value always wins
over both.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock,
same minimal-coordinator pattern as test_coordinator_night_setback.py: only
the method under test is bound to a real coordinator function, everything it
touches is an explicitly-configured MagicMock attribute.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.heat_manager.const import (
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    DEFAULT_BOOST_TEMP,
    RoomState,
)

_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


def _make_coordinator(config: dict) -> MagicMock:
    """Minimal coordinator mock: one room, ready to be boosted, with only
    async_boost_start bound to the real implementation."""
    coord = MagicMock()
    coord.config = config
    coord.rooms = [{"room_name": "Bathroom"}]
    coord.room_offsets = {}
    coord.boost_active_rooms = {}
    coord.async_update_listeners = MagicMock()
    coord.log_event = MagicMock()
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.get_room_write_entities = MagicMock(return_value=["climate.bathroom"])
    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()

    from custom_components.heat_manager.coordinator import HeatManagerCoordinator

    coord.async_boost_start = HeatManagerCoordinator.async_boost_start.__get__(
        coord, type(coord)
    )
    return coord


@pytest.mark.asyncio
async def test_boost_uses_configured_default_temp():
    """CONF_BOOST_DEFAULT_TEMP is set — used when the caller gives no
    temperature."""
    coord = _make_coordinator({CONF_BOOST_DEFAULT_TEMP: 22.5})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord.async_boost_start(None, None)

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bathroom", "temperature": 22.5},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_boost_falls_back_to_hardcoded_default_temp_when_unconfigured():
    """No boost_default_temp option stored (fresh install / pre-upgrade
    config entry) — falls back to DEFAULT_BOOST_TEMP, exactly like before
    this option existed."""
    coord = _make_coordinator({})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord.async_boost_start(None, None)

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bathroom", "temperature": DEFAULT_BOOST_TEMP},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_boost_explicit_caller_temp_overrides_configured_default():
    """A caller-supplied temperature (service call or panel button) always
    wins over the configured default, same as before."""
    coord = _make_coordinator({CONF_BOOST_DEFAULT_TEMP: 22.5})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord.async_boost_start(26.0, None)

    coord.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bathroom", "temperature": 26.0},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_boost_expiry_uses_configured_default_minutes():
    """boost_expires_at is set CONF_BOOST_DEFAULT_MINUTES-worth of minutes
    ahead of "now" when the caller gives no duration_minutes."""
    coord = _make_coordinator({CONF_BOOST_DEFAULT_MINUTES: 45})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord.async_boost_start(None, None)

    assert coord.boost_expires_at == _NOW + timedelta(minutes=45)


@pytest.mark.asyncio
async def test_boost_explicit_caller_minutes_overrides_configured_default():
    """A caller-supplied duration_minutes always wins over the configured
    default."""
    coord = _make_coordinator({CONF_BOOST_DEFAULT_MINUTES: 45})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord.async_boost_start(None, 10)

    assert coord.boost_expires_at == _NOW + timedelta(minutes=10)
