"""Tests for the coordinator's generic status-center issue tracker
(2026-09-13, architecture review #4) — _report_issue() and its three call
sites: _async_check_mold_risk() (extended), _async_check_window_issue_events(),
_async_check_heatup_anomaly_events().

_report_issue(key, active, severity, message) is the one place that:
  - fires `heat_manager_issue_started` / `heat_manager_issue_cleared` on HA's
    event bus on each False<->True transition of a stable `key`, so external
    automations can react to any status-center category without polling the
    panel;
  - escalates a still-active issue to exactly one push notification per
    continuous episode once it's been active longer than
    CONF_ISSUE_ESCALATION_MINUTES, gated by CONF_NOTIFY_ISSUE_ESCALATION.

Same minimal-coordinator mock pattern as
test_coordinator_override_boost_persistence.py: only the method(s) under test
are bound to the real implementation via
`HeatManagerCoordinator.<method>.__get__(coord, type(coord))`; everything
else is an explicitly-configured MagicMock/plain attribute.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.heat_manager.coordinator import HeatManagerCoordinator

_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)


def _make_coordinator(config: dict | None = None) -> MagicMock:
    coord = MagicMock()
    coord.config = config or {}
    coord.hass = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord.hass.services.async_call = AsyncMock()

    coord._issue_started_at = {}
    coord._issue_escalated = set()

    coord._report_issue = HeatManagerCoordinator._report_issue.__get__(
        coord, type(coord)
    )
    coord._notify_issue_escalation = (
        HeatManagerCoordinator._notify_issue_escalation.__get__(coord, type(coord))
    )
    coord._async_check_window_issue_events = (
        HeatManagerCoordinator._async_check_window_issue_events.__get__(
            coord, type(coord)
        )
    )
    coord._async_check_heatup_anomaly_events = (
        HeatManagerCoordinator._async_check_heatup_anomaly_events.__get__(
            coord, type(coord)
        )
    )
    return coord


async def _report(coord, key, active, severity="warning", message="msg", *, at=_NOW):
    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=at):
        await coord._report_issue(key, active, severity, message)


# ── started/cleared events ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_active_issue_fires_started_event():
    coord = _make_coordinator()
    await _report(coord, "mold_risk:Stue", True, message="Mold risk — Stue")

    coord.hass.bus.async_fire.assert_called_once_with(
        "heat_manager_issue_started",
        {"key": "mold_risk:Stue", "severity": "warning", "message": "Mold risk — Stue"},
    )
    assert "mold_risk:Stue" in coord._issue_started_at


@pytest.mark.asyncio
async def test_still_active_issue_fires_no_event():
    coord = _make_coordinator()
    await _report(coord, "mold_risk:Stue", True)
    coord.hass.bus.async_fire.reset_mock()

    await _report(coord, "mold_risk:Stue", True, at=_NOW + timedelta(minutes=5))

    coord.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_clearing_active_issue_fires_cleared_event_with_duration():
    coord = _make_coordinator()
    await _report(coord, "window_open:Bad", True, at=_NOW)
    coord.hass.bus.async_fire.reset_mock()

    await _report(
        coord,
        "window_open:Bad",
        False,
        message="Vindue åbent — Bad",
        at=_NOW + timedelta(minutes=10),
    )

    coord.hass.bus.async_fire.assert_called_once_with(
        "heat_manager_issue_cleared",
        {
            "key": "window_open:Bad",
            "message": "Vindue åbent — Bad",
            "duration_seconds": 600.0,
        },
    )
    assert "window_open:Bad" not in coord._issue_started_at


@pytest.mark.asyncio
async def test_already_inactive_issue_fires_no_event():
    coord = _make_coordinator()
    await _report(coord, "window_open:Bad", False)

    coord.hass.bus.async_fire.assert_not_called()


# ── escalation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalation_fires_notification_past_threshold():
    coord = _make_coordinator(
        config={
            "notify_issue_escalation": True,
            "issue_escalation_minutes": 60,
            "notify_service": "notify.mobile_app",
        }
    )
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW)

    await _report(
        coord,
        "heatup_anomaly:Bad",
        True,
        message="varmer langsomt",
        at=_NOW + timedelta(minutes=61),
    )

    coord.hass.services.async_call.assert_awaited_once()
    call = coord.hass.services.async_call.call_args
    assert call.args[0] == "notify"
    assert call.args[1] == "mobile_app"
    assert "varmer langsomt" in call.args[2]["message"]
    assert "heatup_anomaly:Bad" in coord._issue_escalated


@pytest.mark.asyncio
async def test_escalation_does_not_fire_before_threshold():
    coord = _make_coordinator(
        config={
            "notify_issue_escalation": True,
            "issue_escalation_minutes": 60,
            "notify_service": "notify.mobile_app",
        }
    )
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW)

    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=30))

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_fires_only_once_per_episode():
    coord = _make_coordinator(
        config={
            "notify_issue_escalation": True,
            "issue_escalation_minutes": 60,
            "notify_service": "notify.mobile_app",
        }
    )
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW)
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=61))
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=90))

    coord.hass.services.async_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_escalation_respects_notify_toggle_off():
    coord = _make_coordinator(
        config={
            "notify_issue_escalation": False,
            "issue_escalation_minutes": 60,
            "notify_service": "notify.mobile_app",
        }
    )
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW)
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=90))

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_without_notify_service_configured_is_noop():
    coord = _make_coordinator(
        config={"notify_issue_escalation": True, "issue_escalation_minutes": 60}
    )
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW)
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=90))

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_episode_after_clear_can_escalate_again():
    coord = _make_coordinator(
        config={
            "notify_issue_escalation": True,
            "issue_escalation_minutes": 60,
            "notify_service": "notify.mobile_app",
        }
    )
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW)
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=61))
    assert coord.hass.services.async_call.await_count == 1

    # Clears, then a fresh episode starts and also runs long.
    await _report(coord, "heatup_anomaly:Bad", False, at=_NOW + timedelta(minutes=70))
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=80))
    await _report(coord, "heatup_anomaly:Bad", True, at=_NOW + timedelta(minutes=142))

    assert coord.hass.services.async_call.await_count == 2


# ── call sites ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_issue_events_reports_open_rooms_active():
    coord = _make_coordinator()
    coord.rooms = [{"room_name": "Bad"}, {"room_name": "Stue"}]
    coord.window_engine = MagicMock()
    coord.window_engine.get_open_windows = MagicMock(return_value=["Bad"])

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord._async_check_window_issue_events()

    assert "window_open:Bad" in coord._issue_started_at
    assert "window_open:Stue" not in coord._issue_started_at


@pytest.mark.asyncio
async def test_heatup_anomaly_issue_events_reports_flagged_rooms_active():
    coord = _make_coordinator()
    coord.rooms = [{"room_name": "Bad"}, {"room_name": "Stue"}]
    coord.calibration_engine = MagicMock()
    coord.calibration_engine.get_room_heatup_anomaly = MagicMock(
        side_effect=lambda room: room == "Bad"
    )

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        await coord._async_check_heatup_anomaly_events()

    assert "heatup_anomaly:Bad" in coord._issue_started_at
    assert "heatup_anomaly:Stue" not in coord._issue_started_at
