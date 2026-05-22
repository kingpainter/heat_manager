"""Tests for coordinator night setback helpers.

Covers:
- is_night_setback_active(): disabled, enabled + in window, enabled + outside window,
  midnight-spanning windows, same-day window, missing config keys
- night_setback_delta(): returns 0.0 when inactive, returns configured value when active
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from custom_components.heat_manager.const import (
    CONF_NIGHT_SETBACK_ENABLED,
    CONF_NIGHT_SETBACK_TEMP,
    CONF_NIGHT_START_HOUR,
    CONF_NIGHT_END_HOUR,
    DEFAULT_NIGHT_SETBACK_ENABLED,
    DEFAULT_NIGHT_SETBACK_TEMP,
    DEFAULT_NIGHT_START_HOUR,
    DEFAULT_NIGHT_END_HOUR,
)


def _make_coordinator(config: dict) -> MagicMock:
    """Return a minimal coordinator mock with the given config."""
    coord = MagicMock()
    coord.config = config
    coord.rooms = []
    # Bind the real methods to the mock so we can call them
    from custom_components.heat_manager.coordinator import HeatManagerCoordinator
    coord.is_night_setback_active = HeatManagerCoordinator.is_night_setback_active.__get__(
        coord, type(coord)
    )
    coord.night_setback_delta = HeatManagerCoordinator.night_setback_delta.__get__(
        coord, type(coord)
    )
    return coord


# ── is_night_setback_active ───────────────────────────────────────────────────

def test_setback_disabled_by_default():
    """Feature is off by default — should always return False."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: False,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch(
        "custom_components.heat_manager.coordinator.HeatManagerCoordinator"
        ".is_night_setback_active",
        wraps=coord.is_night_setback_active,
    ):
        with patch("homeassistant.util.dt.now") as mock_now:
            mock_now.return_value = MagicMock(hour=1)
            assert coord.is_night_setback_active() is False


def test_setback_active_inside_midnight_spanning_window():
    """23:00–07:00 window, current hour = 02 → active."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=2)
        assert coord.is_night_setback_active() is True


def test_setback_active_at_start_hour():
    """Hour equals start → active (midnight-spanning window)."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=23)
        assert coord.is_night_setback_active() is True


def test_setback_inactive_at_end_hour():
    """Hour equals end → inactive (end is exclusive)."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=7)
        assert coord.is_night_setback_active() is False


def test_setback_inactive_during_day():
    """23:00–07:00 window, current hour = 14 → inactive."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=14)
        assert coord.is_night_setback_active() is False


def test_setback_active_same_day_window():
    """Same-day window e.g. 22–23, hour = 22 → active."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 22,
        CONF_NIGHT_END_HOUR: 23,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=22)
        assert coord.is_night_setback_active() is True


def test_setback_inactive_outside_same_day_window():
    """Same-day window e.g. 22–23, hour = 21 → inactive."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 22,
        CONF_NIGHT_END_HOUR: 23,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=21)
        assert coord.is_night_setback_active() is False


def test_setback_uses_default_hours_when_not_configured():
    """Missing start/end hours → falls back to DEFAULT values (23/7)."""
    coord = _make_coordinator({CONF_NIGHT_SETBACK_ENABLED: True})
    # Default window is 23–07, test hour 0 (should be active)
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=0)
        assert coord.is_night_setback_active() is True


# ── night_setback_delta ───────────────────────────────────────────────────────

def test_delta_zero_when_inactive():
    """Setback disabled → delta = 0.0."""
    coord = _make_coordinator({CONF_NIGHT_SETBACK_ENABLED: False})
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=2)
        assert coord.night_setback_delta() == 0.0


def test_delta_returns_configured_value():
    """Setback enabled + inside window → returns configured temp delta."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_SETBACK_TEMP: 3.0,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=2)
        assert coord.night_setback_delta() == pytest.approx(3.0)


def test_delta_uses_default_temp():
    """Setback enabled but CONF_NIGHT_SETBACK_TEMP absent → DEFAULT (2.0 °C)."""
    coord = _make_coordinator({
        CONF_NIGHT_SETBACK_ENABLED: True,
        CONF_NIGHT_START_HOUR: 23,
        CONF_NIGHT_END_HOUR: 7,
    })
    with patch("homeassistant.util.dt.now") as mock_now:
        mock_now.return_value = MagicMock(hour=3)
        assert coord.night_setback_delta() == pytest.approx(DEFAULT_NIGHT_SETBACK_TEMP)
