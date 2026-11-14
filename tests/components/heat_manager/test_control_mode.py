"""Tests for v0.59.0's auto/manual visibility backend.

Covers:
- coordinator.set_remote_override_expiry(): the remote's auto-restore
  countdown (CONF_REMOTE_OVERRIDE_DURATION_MIN, 0 = never).
- coordinator.room_override_since: recorded on entering OVERRIDE from any
  code path, cleared on leaving it.
- coordinator.get_control_mode(): auto / manual / mixed, ignoring rooms
  without a TRV.
- coordinator.async_release_all_overrides(): the panel's "back to auto".
- ControlModeSensor (sensor.py): state + attributes.
- ws_release_overrides (websocket.py).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock,
with the real coordinator methods bound onto the mock (same pattern as
test_coordinator_override_source.py).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util.dt import utcnow

from custom_components.heat_manager.const import (
    CONF_REMOTE_OVERRIDE_DURATION_MIN,
    CONTROL_MODE_AUTO,
    CONTROL_MODE_MANUAL,
    CONTROL_MODE_MIXED,
    DEFAULT_REMOTE_OVERRIDE_DURATION_MIN,
    RoomState,
)
from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.sensor import ControlModeSensor
from custom_components.heat_manager.websocket import ws_release_overrides


def _bind(coord: MagicMock, name: str) -> None:
    setattr(
        coord, name, getattr(HeatManagerCoordinator, name).__get__(coord, type(coord))
    )


def _make_coordinator(
    rooms: list[str] | None = None,
    states: dict[str, RoomState] | None = None,
    config: dict | None = None,
    rooms_without_trv: tuple[str, ...] = (),
) -> MagicMock:
    coord = MagicMock()
    for name in (
        "set_room_state",
        "get_room_state",
        "set_remote_override_expiry",
        "get_control_mode",
        "async_release_all_overrides",
        "async_set_room_override",
    ):
        _bind(coord, name)

    names = rooms if rooms is not None else ["Stue", "Køkken"]
    coord.rooms = [{"room_name": n} for n in names]
    coord.room_states = dict(states or {})
    coord.room_override_source = {}
    coord.room_override_expires_at = {}
    coord.room_override_since = {}
    coord.config = config if config is not None else {}
    coord.async_update_listeners = MagicMock()
    coord.log_event = MagicMock()
    coord.async_restore_room_schedule = AsyncMock(return_value="climate.x")
    coord.get_all_room_trvs = MagicMock(
        side_effect=lambda n: [] if n in rooms_without_trv else [{"climate": n}]
    )
    coord.remote_last_action = None
    return coord


# ── set_remote_override_expiry ──────────────────────────────────────────────


def test_remote_expiry_defaults_to_two_hours():
    coord = _make_coordinator(states={"Stue": RoomState.OVERRIDE})
    before = utcnow()

    coord.set_remote_override_expiry("Stue")

    expires = coord.room_override_expires_at["Stue"]
    assert DEFAULT_REMOTE_OVERRIDE_DURATION_MIN == 120
    assert (
        timedelta(minutes=119) < expires - before <= timedelta(minutes=120, seconds=5)
    )
    assert coord.room_override_source["Stue"] == "remote"


def test_remote_expiry_uses_configured_duration():
    coord = _make_coordinator(
        states={"Stue": RoomState.OVERRIDE},
        config={CONF_REMOTE_OVERRIDE_DURATION_MIN: 30},
    )

    coord.set_remote_override_expiry("Stue")

    remaining = coord.room_override_expires_at["Stue"] - utcnow()
    assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)


def test_remote_expiry_zero_means_never():
    coord = _make_coordinator(
        states={"Stue": RoomState.OVERRIDE},
        config={CONF_REMOTE_OVERRIDE_DURATION_MIN: 0},
    )
    coord.room_override_expires_at["Stue"] = utcnow()

    coord.set_remote_override_expiry("Stue")

    assert "Stue" not in coord.room_override_expires_at


def test_remote_expiry_ignores_room_not_in_override():
    coord = _make_coordinator(states={"Stue": RoomState.NORMAL})

    coord.set_remote_override_expiry("Stue")

    assert "Stue" not in coord.room_override_expires_at
    assert "Stue" not in coord.room_override_source


def test_remote_expiry_falls_back_on_bad_config_value():
    coord = _make_coordinator(
        states={"Stue": RoomState.OVERRIDE},
        config={CONF_REMOTE_OVERRIDE_DURATION_MIN: "garbage"},
    )

    coord.set_remote_override_expiry("Stue")

    remaining = coord.room_override_expires_at["Stue"] - utcnow()
    assert remaining > timedelta(minutes=119)


# ── room_override_since ──────────────────────────────────────────────────────


def test_entering_override_records_since():
    coord = _make_coordinator(states={"Stue": RoomState.NORMAL})

    coord.set_room_state("Stue", RoomState.OVERRIDE)

    assert utcnow() - coord.room_override_since["Stue"] < timedelta(seconds=5)


def test_staying_in_override_keeps_original_since():
    coord = _make_coordinator(states={"Stue": RoomState.OVERRIDE})
    original = utcnow() - timedelta(hours=1)
    coord.room_override_since["Stue"] = original

    coord.set_room_state("Stue", RoomState.OVERRIDE)

    assert coord.room_override_since["Stue"] == original


def test_leaving_override_clears_since():
    coord = _make_coordinator(states={"Stue": RoomState.OVERRIDE})
    coord.room_override_since["Stue"] = utcnow()

    coord.set_room_state("Stue", RoomState.NORMAL)

    assert "Stue" not in coord.room_override_since


# ── get_control_mode ─────────────────────────────────────────────────────────


def test_control_mode_auto_when_nothing_is_manual():
    coord = _make_coordinator()
    assert coord.get_control_mode() == (CONTROL_MODE_AUTO, [])


def test_control_mode_mixed():
    coord = _make_coordinator(states={"Stue": RoomState.OVERRIDE})
    assert coord.get_control_mode() == (CONTROL_MODE_MIXED, ["Stue"])


def test_control_mode_manual_when_every_room_is_manual():
    coord = _make_coordinator(
        states={"Stue": RoomState.OVERRIDE, "Køkken": RoomState.OVERRIDE}
    )
    assert coord.get_control_mode() == (CONTROL_MODE_MANUAL, ["Stue", "Køkken"])


def test_control_mode_ignores_rooms_without_trv():
    coord = _make_coordinator(
        rooms=["Stue", "Gang"],
        states={"Stue": RoomState.OVERRIDE},
        rooms_without_trv=("Gang",),
    )
    assert coord.get_control_mode() == (CONTROL_MODE_MANUAL, ["Stue"])


def test_away_room_does_not_make_mode_manual():
    coord = _make_coordinator(
        states={"Stue": RoomState.OVERRIDE, "Køkken": RoomState.AWAY}
    )
    assert coord.get_control_mode()[0] == CONTROL_MODE_MIXED


# ── async_release_all_overrides ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_release_all_overrides_restores_every_manual_room():
    coord = _make_coordinator(
        states={"Stue": RoomState.OVERRIDE, "Køkken": RoomState.NORMAL}
    )
    coord.room_override_source["Stue"] = "remote"

    released = await coord.async_release_all_overrides()

    assert released == ["Stue"]
    coord.async_restore_room_schedule.assert_awaited_once_with("Stue")
    assert coord.room_states["Stue"] == RoomState.NORMAL
    assert "Stue" not in coord.room_override_source
    coord.log_message.assert_called_once()


@pytest.mark.asyncio
async def test_release_all_overrides_noop_when_all_auto():
    coord = _make_coordinator(states={"Stue": RoomState.NORMAL})

    released = await coord.async_release_all_overrides()

    assert released == []
    coord.async_restore_room_schedule.assert_not_called()
    coord.log_message.assert_not_called()


# ── ControlModeSensor ────────────────────────────────────────────────────────


def _sensor(coord: MagicMock) -> ControlModeSensor:
    entry = MagicMock()
    entry.entry_id = "abc"
    return ControlModeSensor(coord, entry)


def test_control_mode_sensor_state_and_attributes():
    coord = _make_coordinator(states={"Stue": RoomState.OVERRIDE})
    expires = utcnow() + timedelta(minutes=90)
    coord.room_override_source["Stue"] = "remote"
    coord.room_override_expires_at["Stue"] = expires
    coord.remote_last_action = {"timestamp": "2026-10-30T18:00:00+00:00"}
    sensor = _sensor(coord)

    assert sensor.native_value == CONTROL_MODE_MIXED
    attrs = sensor.extra_state_attributes
    assert attrs["manual_rooms"] == ["Stue"]
    assert attrs["override_sources"] == {"Stue": "remote"}
    assert attrs["override_expires_at"] == {"Stue": expires.isoformat()}
    assert attrs["remote_last_action_at"] == "2026-10-30T18:00:00+00:00"


def test_control_mode_sensor_auto_has_empty_attributes():
    sensor = _sensor(_make_coordinator())

    assert sensor.native_value == CONTROL_MODE_AUTO
    attrs = sensor.extra_state_attributes
    assert attrs["manual_rooms"] == []
    assert attrs["override_sources"] == {}
    assert attrs["remote_last_action_at"] is None


def test_control_mode_sensor_options_cover_every_mode():
    sensor = _sensor(_make_coordinator())
    assert set(sensor.options) == {
        CONTROL_MODE_AUTO,
        CONTROL_MODE_MANUAL,
        CONTROL_MODE_MIXED,
    }


# ── ws_release_overrides ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_release_overrides(monkeypatch):
    coord = MagicMock()
    coord.async_release_all_overrides = AsyncMock(return_value=["Stue"])
    entry = MagicMock()
    entry.runtime_data = coord
    monkeypatch.setattr(
        "custom_components.heat_manager.websocket._get_entry", lambda hass: entry
    )
    connection = MagicMock()

    # The decorated command wraps the coroutine in a task; call the
    # undecorated function directly, like test_websocket.py does.
    await ws_release_overrides.__wrapped__(
        MagicMock(), connection, {"id": 7, "type": "heat_manager/release_overrides"}
    )

    connection.send_result.assert_called_once_with(
        7, {"success": True, "rooms_released": ["Stue"]}
    )


@pytest.mark.asyncio
async def test_ws_release_overrides_not_loaded(monkeypatch):
    monkeypatch.setattr(
        "custom_components.heat_manager.websocket._get_entry", lambda hass: None
    )
    connection = MagicMock()

    await ws_release_overrides.__wrapped__(
        MagicMock(), connection, {"id": 8, "type": "heat_manager/release_overrides"}
    )

    connection.send_error.assert_called_once()
    connection.send_result.assert_not_called()
