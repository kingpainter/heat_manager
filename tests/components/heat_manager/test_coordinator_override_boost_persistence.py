"""Tests for coordinator's override/boost restart-safety hardening
(2026-09-13) — _persist_override_snapshot()/_restore_override_snapshot().

Before this, room_override_source/room_override_expires_at/
boost_active_rooms/boost_expires_at were pure in-memory dicts: a manual
override set from the panel, or an active boost, was silently forgotten on
any HA restart, with the room quietly falling back to its normal schedule
with no warning. These tests cover: an active override/boost is captured on
persist and correctly round-trips back through restore; an override/boost
whose expiry has already passed while HA was down is deliberately NOT
restored (mirrors the normal auto-expiry behaviour instead of resurrecting
something that should already be gone); and a room that isn't overridden at
all is never written to the snapshot.

Same minimal-coordinator mock pattern as test_coordinator_boost_defaults.py:
only the method under test is bound to the real implementation via
`HeatManagerCoordinator.<method>.__get__(coord, type(coord))`; everything it
touches is an explicitly-configured MagicMock/plain attribute.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from custom_components.heat_manager.const import RoomState
from custom_components.heat_manager.coordinator import HeatManagerCoordinator

_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)


def _make_coordinator(entry_options: dict | None = None) -> MagicMock:
    coord = MagicMock()
    coord.entry = MagicMock()
    coord.entry.options = dict(entry_options or {})
    coord.hass = MagicMock()
    coord.hass.config_entries.async_update_entry = MagicMock()

    coord.room_states = {}
    coord.room_override_source = {}
    coord.room_override_expires_at = {}
    coord.boost_active_rooms = {}
    coord.boost_expires_at = None

    coord._persist_override_snapshot = (
        HeatManagerCoordinator._persist_override_snapshot.__get__(coord, type(coord))
    )
    coord._restore_override_snapshot = (
        HeatManagerCoordinator._restore_override_snapshot.__get__(coord, type(coord))
    )
    return coord


def _persisted_snapshot(coord: MagicMock) -> dict:
    """Decode the JSON snapshot handed to async_update_entry's options=."""
    options = coord.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    return json.loads(options["_override_snap"])


# ── _persist_override_snapshot ───────────────────────────────────────────────


def test_persist_snapshot_captures_active_override_with_expiry():
    coord = _make_coordinator()
    coord.room_states = {"Bathroom": RoomState.OVERRIDE}
    coord.room_override_source = {"Bathroom": "panel"}
    coord.room_override_expires_at = {"Bathroom": _NOW + timedelta(hours=1)}

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        coord._persist_override_snapshot()

    snap = _persisted_snapshot(coord)
    assert snap["overrides"]["Bathroom"]["source"] == "panel"
    assert snap["overrides"]["Bathroom"]["expires_at"] == (
        _NOW + timedelta(hours=1)
    ).isoformat()


def test_persist_snapshot_permanent_override_has_no_expiry():
    coord = _make_coordinator()
    coord.room_states = {"Bathroom": RoomState.OVERRIDE}
    coord.room_override_source = {"Bathroom": "switch"}
    # No entry in room_override_expires_at at all == permanent override.

    coord._persist_override_snapshot()

    snap = _persisted_snapshot(coord)
    assert snap["overrides"]["Bathroom"]["expires_at"] is None


def test_persist_snapshot_ignores_rooms_not_in_override():
    coord = _make_coordinator()
    coord.room_states = {
        "Bathroom": RoomState.OVERRIDE,
        "Kitchen": RoomState.AWAY,
        "Hallway": RoomState.NORMAL,
    }
    coord.room_override_source = {"Bathroom": "panel"}

    coord._persist_override_snapshot()

    snap = _persisted_snapshot(coord)
    assert list(snap["overrides"].keys()) == ["Bathroom"]


def test_persist_snapshot_captures_active_boost():
    coord = _make_coordinator()
    coord.boost_active_rooms = {"Bathroom": True, "Kitchen": False}
    coord.boost_expires_at = _NOW + timedelta(minutes=30)

    coord._persist_override_snapshot()

    snap = _persisted_snapshot(coord)
    # Only the truthy entry is kept — a room that was boosted and already
    # restored (False) is not something restore should resurrect.
    assert snap["boost_active_rooms"] == {"Bathroom": True}
    assert snap["boost_expires_at"] == (_NOW + timedelta(minutes=30)).isoformat()


def test_persist_snapshot_nothing_active_writes_empty_snapshot():
    coord = _make_coordinator()

    coord._persist_override_snapshot()

    snap = _persisted_snapshot(coord)
    assert snap == {
        "overrides": {},
        "boost_active_rooms": {},
        "boost_expires_at": None,
    }


# ── _restore_override_snapshot ───────────────────────────────────────────────


def test_restore_snapshot_no_data_is_noop():
    coord = _make_coordinator(entry_options={})

    coord._restore_override_snapshot()

    assert coord.room_states == {}
    assert coord.boost_expires_at is None


def test_restore_snapshot_restores_override_before_expiry():
    snap = {
        "overrides": {
            "Bathroom": {
                "source": "panel",
                "expires_at": (_NOW + timedelta(minutes=30)).isoformat(),
            }
        },
        "boost_active_rooms": {},
        "boost_expires_at": None,
    }
    coord = _make_coordinator(entry_options={"_override_snap": json.dumps(snap)})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        coord._restore_override_snapshot()

    assert coord.room_states["Bathroom"] == RoomState.OVERRIDE
    assert coord.room_override_source["Bathroom"] == "panel"
    assert coord.room_override_expires_at["Bathroom"] == _NOW + timedelta(minutes=30)


def test_restore_snapshot_restores_permanent_override_with_no_expiry_key():
    snap = {
        "overrides": {"Bathroom": {"source": "switch", "expires_at": None}},
        "boost_active_rooms": {},
        "boost_expires_at": None,
    }
    coord = _make_coordinator(entry_options={"_override_snap": json.dumps(snap)})

    coord._restore_override_snapshot()

    assert coord.room_states["Bathroom"] == RoomState.OVERRIDE
    assert "Bathroom" not in coord.room_override_expires_at


def test_restore_snapshot_skips_override_whose_expiry_already_passed():
    """The room was in a timed override that expired WHILE HA was down —
    must not resurrect it; it should just come back up NORMAL, same as if
    the expiry had fired normally."""
    snap = {
        "overrides": {
            "Bathroom": {
                "source": "panel",
                "expires_at": (_NOW - timedelta(minutes=5)).isoformat(),
            }
        },
        "boost_active_rooms": {},
        "boost_expires_at": None,
    }
    coord = _make_coordinator(entry_options={"_override_snap": json.dumps(snap)})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        coord._restore_override_snapshot()

    assert "Bathroom" not in coord.room_states
    assert "Bathroom" not in coord.room_override_source


def test_restore_snapshot_restores_active_boost_before_expiry():
    snap = {
        "overrides": {},
        "boost_active_rooms": {"Bathroom": True},
        "boost_expires_at": (_NOW + timedelta(minutes=20)).isoformat(),
    }
    coord = _make_coordinator(entry_options={"_override_snap": json.dumps(snap)})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        coord._restore_override_snapshot()

    assert coord.boost_active_rooms == {"Bathroom": True}
    assert coord.boost_expires_at == _NOW + timedelta(minutes=20)


def test_restore_snapshot_skips_boost_whose_expiry_already_passed():
    snap = {
        "overrides": {},
        "boost_active_rooms": {"Bathroom": True},
        "boost_expires_at": (_NOW - timedelta(minutes=1)).isoformat(),
    }
    coord = _make_coordinator(entry_options={"_override_snap": json.dumps(snap)})

    with patch("custom_components.heat_manager.coordinator.utcnow", return_value=_NOW):
        coord._restore_override_snapshot()

    assert coord.boost_active_rooms == {}
    assert coord.boost_expires_at is None


def test_restore_snapshot_malformed_json_is_noop_not_a_crash():
    coord = _make_coordinator(entry_options={"_override_snap": "{not valid json"})

    coord._restore_override_snapshot()  # must not raise

    assert coord.room_states == {}
    assert coord.boost_expires_at is None
