"""Tests for websocket._build_active_issues() (v0.32.0 — "status center").

Consolidates what used to be four separately-computed indicators (topbar
cloud-chip / health-chip / ws-error-chip, plus the Oversigt-only
remote-last-action box) into one ordered list of
{"severity": "critical"|"warning"|"info", "icon": str, "message": str}
dicts, sorted critical -> warning -> info. The one indicator that cannot be
computed here — the panel's own WebSocket connection being dead — is
deliberately out of scope for this function; it's injected client-side in
heat-manager-panel.js's _activeIssues() instead, since the server whose
connection is dead cannot report on that itself.

All tests run completely offline — HA core is mocked with MagicMock, same
minimal-coordinator pattern as test_coordinator_mold_risk_notification.py.
_build_active_issues() is a plain module-level function (not a coordinator
method), so no __get__ binding is needed — it's called directly against a
synthetic coordinator and a synthetic already-built `rooms` payload list
(the same shape ws_get_state() assembles per room before calling this).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.util.dt import utcnow

from custom_components.heat_manager import websocket

_build_active_issues = websocket._build_active_issues


def _state(value: str, last_updated=None) -> MagicMock:
    return MagicMock(state=value, last_updated=last_updated)


def _make_coordinator(rooms_cfg: list[dict] | None = None) -> MagicMock:
    """Minimal coordinator mock covering only what _build_active_issues()
    reads: coordinator.rooms (raw config, for the cloud/gateway climate
    resolution) plus get_climate_entity()/get_homekit_climate_entity(),
    boost state, and remote_last_action. hass.states.get() defaults to
    None (nothing configured) so a bare MagicMock never leaks through as a
    "state" object — tests that need a real entity state configure
    hass.states.get explicitly via side_effect."""
    coord = MagicMock()
    coord.rooms = rooms_cfg if rooms_cfg is not None else []
    coord.get_climate_entity = MagicMock(return_value="")
    coord.get_homekit_climate_entity = MagicMock(return_value="")
    coord.boost_remaining_minutes = 0
    coord.boost_active_rooms = {}
    coord.remote_last_action = None

    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    coord.hass = hass
    return coord


def _room_payload(name="Bathroom", **overrides) -> dict:
    """A minimal already-built per-room payload dict, the shape
    ws_get_state() hands to _build_active_issues() as `rooms`."""
    base = {
        "name": name,
        "unavailable_entities": [],
        "mold_risk": False,
        "windows_open": False,
    }
    base.update(overrides)
    return base


# ── no issues ─────────────────────────────────────────────────────────────


def test_no_issues_when_everything_normal():
    coord = _make_coordinator()
    issues = _build_active_issues(coord, [_room_payload()])
    assert issues == []


# ── Netatmo cloud/gateway health ───────────────────────────────────────────


def test_all_rooms_unavailable_is_critical():
    coord = _make_coordinator(rooms_cfg=[{"room_name": "Bathroom"}, {"room_name": "Kitchen"}])
    coord.get_climate_entity = MagicMock(
        side_effect=lambda name: {"Bathroom": "climate.bathroom", "Kitchen": "climate.kitchen"}[name]
    )
    coord.get_homekit_climate_entity = MagicMock(return_value="")
    coord.hass.states.get = MagicMock(return_value=_state("unavailable"))

    issues = _build_active_issues(coord, [_room_payload("Bathroom"), _room_payload("Kitchen")])

    assert len(issues) == 1
    assert issues[0]["severity"] == "critical"
    assert "alle rum" in issues[0]["message"]


def test_some_rooms_unavailable_is_warning_and_names_rooms():
    coord = _make_coordinator(rooms_cfg=[{"room_name": "Bathroom"}, {"room_name": "Kitchen"}])
    coord.get_climate_entity = MagicMock(
        side_effect=lambda name: {"Bathroom": "climate.bathroom", "Kitchen": "climate.kitchen"}[name]
    )
    coord.get_homekit_climate_entity = MagicMock(return_value="")

    def _states(entity_id):
        if entity_id == "climate.bathroom":
            return _state("unavailable")
        return _state("heat")

    coord.hass.states.get = MagicMock(side_effect=_states)

    issues = _build_active_issues(coord, [_room_payload("Bathroom"), _room_payload("Kitchen")])

    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "Bathroom" in issues[0]["message"]
    assert "Kitchen" not in issues[0]["message"]


def test_stale_room_is_warning():
    coord = _make_coordinator(rooms_cfg=[{"room_name": "Bathroom"}])
    coord.get_climate_entity = MagicMock(return_value="climate.bathroom")
    coord.get_homekit_climate_entity = MagicMock(return_value="")
    stale_time = utcnow() - timedelta(minutes=15)
    coord.hass.states.get = MagicMock(return_value=_state("heat", last_updated=stale_time))

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])

    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "opdateret" in issues[0]["message"]


def test_fresh_room_reports_no_cloud_issue():
    coord = _make_coordinator(rooms_cfg=[{"room_name": "Bathroom"}])
    coord.get_climate_entity = MagicMock(return_value="climate.bathroom")
    coord.get_homekit_climate_entity = MagicMock(return_value="")
    fresh_time = utcnow() - timedelta(minutes=2)
    coord.hass.states.get = MagicMock(return_value=_state("heat", last_updated=fresh_time))

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])
    assert issues == []


def test_homekit_twin_excluded_from_cloud_check():
    """A room whose only 'climate entity' is its HomeKit-local twin (no
    separate cloud entity) must never be counted — that entity being
    briefly unavailable is not a cloud/gateway problem."""
    coord = _make_coordinator(rooms_cfg=[{"room_name": "Bathroom"}])
    coord.get_climate_entity = MagicMock(return_value="climate.bathroom_homekit")
    coord.get_homekit_climate_entity = MagicMock(return_value="climate.bathroom_homekit")
    coord.hass.states.get = MagicMock(return_value=_state("unavailable"))

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])
    assert issues == []


# ── other unavailable entities per room ────────────────────────────────────


def test_non_climate_unavailable_entities_reported_as_warning():
    coord = _make_coordinator()
    room = _room_payload("Bathroom", unavailable_entities=["binary_sensor.bathroom_window"])
    issues = _build_active_issues(coord, [room])

    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "Bathroom" in issues[0]["message"]


def test_unavailable_climate_entity_not_double_counted_here():
    """climate.* entries in unavailable_entities are the cloud/gateway
    check's job (above) — this branch only reports non-climate entities so
    the same underlying problem isn't reported twice."""
    coord = _make_coordinator()
    room = _room_payload("Bathroom", unavailable_entities=["climate.bathroom"])
    issues = _build_active_issues(coord, [room])
    assert issues == []


# ── mold risk / open windows ───────────────────────────────────────────────


def test_mold_risk_reported_as_warning():
    coord = _make_coordinator()
    issues = _build_active_issues(coord, [_room_payload("Kælder", mold_risk=True)])
    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "Kælder" in issues[0]["message"]


def test_open_window_reported_as_warning():
    coord = _make_coordinator()
    issues = _build_active_issues(coord, [_room_payload("Stue", windows_open=True)])
    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "Stue" in issues[0]["message"]


# ── boost active (info) ─────────────────────────────────────────────────────


def test_active_boost_reported_as_info_with_room_names():
    coord = _make_coordinator()
    coord.boost_remaining_minutes = 12
    coord.boost_active_rooms = {"Bathroom": True, "Kitchen": False}

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])

    assert len(issues) == 1
    assert issues[0]["severity"] == "info"
    assert "Bathroom" in issues[0]["message"]
    assert "Kitchen" not in issues[0]["message"]
    assert "12" in issues[0]["message"]


def test_zero_boost_remaining_reports_nothing():
    coord = _make_coordinator()
    coord.boost_remaining_minutes = 0
    coord.boost_active_rooms = {"Bathroom": True}

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])
    assert issues == []


# ── remote last action (info, <30 min) ──────────────────────────────────────


def test_recent_remote_action_reported_as_info():
    coord = _make_coordinator()
    coord.remote_last_action = {
        "timestamp": (utcnow() - timedelta(minutes=5)).isoformat(),
        "description": "Alarm armed away",
        "rooms": ["Bathroom", "Kitchen"],
    }

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])

    assert len(issues) == 1
    assert issues[0]["severity"] == "info"
    assert "Alarm armed away" in issues[0]["message"]
    assert "Bathroom" in issues[0]["message"]


def test_stale_remote_action_over_30min_not_reported():
    coord = _make_coordinator()
    coord.remote_last_action = {
        "timestamp": (utcnow() - timedelta(minutes=45)).isoformat(),
        "description": "Alarm armed away",
        "rooms": [],
    }

    issues = _build_active_issues(coord, [_room_payload("Bathroom")])
    assert issues == []


def test_no_remote_action_configured_reports_nothing():
    coord = _make_coordinator()
    coord.remote_last_action = None
    issues = _build_active_issues(coord, [_room_payload("Bathroom")])
    assert issues == []


# ── ordering ─────────────────────────────────────────────────────────────


def test_issues_sorted_critical_before_warning_before_info():
    coord = _make_coordinator(rooms_cfg=[{"room_name": "Bathroom"}])
    coord.get_climate_entity = MagicMock(return_value="climate.bathroom")
    coord.get_homekit_climate_entity = MagicMock(return_value="")
    coord.hass.states.get = MagicMock(return_value=_state("unavailable"))
    coord.boost_remaining_minutes = 10
    coord.boost_active_rooms = {"Bathroom": True}

    room = _room_payload("Bathroom", mold_risk=True)
    issues = _build_active_issues(coord, [room])

    severities = [i["severity"] for i in issues]
    assert severities == sorted(severities, key={"critical": 0, "warning": 1, "info": 2}.get)
    assert severities[0] == "critical"
    assert severities[-1] == "info"
