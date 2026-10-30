"""Tests for v0.60.0's smart status line backend.

Covers:
- coordinator.extend_overrides(): "+1 time" on the status line.
- coordinator.snooze_issue()/get_issue_snoozed_until(): "Skjul 1 t".
- coordinator.get_house_status() and HouseStatusSensor: priority order.
- coordinator.set_remote_last_action(): action/delta/skipped fields.
- RemoteButtonEngine long presses: temp up held = boost, auto/manual held =
  every room back to auto; long_release never acts; skipped rooms recorded.
- ws_extend_overrides / ws_snooze_issue.

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock,
with the real coordinator methods bound onto the mock where the logic under
test lives in the coordinator.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util.dt import utcnow

from custom_components.heat_manager.const import (
    CONF_BUTTON_MODE_TOGGLE_ENTITY,
    CONF_BUTTON_TEMP_DOWN_ENTITY,
    CONF_BUTTON_TEMP_UP_ENTITY,
    HOUSE_STATUS_AUTO,
    HOUSE_STATUS_BOOST,
    HOUSE_STATUS_MANUAL,
    HOUSE_STATUS_OFF,
    HOUSE_STATUS_PAUSED,
    HOUSE_STATUS_WINDOW_OPEN,
    HOUSE_STATUSES,
    ControllerState,
    RoomState,
)
from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.remote_button_engine import (
    RemoteButtonEngine,
)
from custom_components.heat_manager.sensor import HouseStatusSensor
from custom_components.heat_manager.websocket import (
    ws_extend_overrides,
    ws_snooze_issue,
)


def _bind(coord: MagicMock, *names: str) -> None:
    for name in names:
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )


def _coordinator(states: dict[str, RoomState] | None = None) -> MagicMock:
    coord = MagicMock()
    _bind(
        coord,
        "get_room_state",
        "set_room_state",
        "extend_overrides",
        "snooze_issue",
        "get_issue_snoozed_until",
        "get_control_mode",
        "get_house_status",
        "set_remote_last_action",
    )
    coord.room_states = dict(states or {})
    coord.rooms = [{"room_name": n} for n in coord.room_states]
    coord.room_override_source = {}
    coord.room_override_expires_at = {}
    coord.room_override_since = {}
    coord._issue_snoozed_until = {}
    coord.get_all_room_trvs = MagicMock(return_value=[{"climate": "x"}])
    coord.async_update_listeners = MagicMock()
    coord.log_event = MagicMock()
    coord.controller_state = ControllerState.ON
    coord.boost_remaining_minutes = 0
    coord.pause_remaining_minutes = 0
    coord.remote_last_action = None
    return coord


# ── extend_overrides ─────────────────────────────────────────────────────────


def test_extend_overrides_pushes_expiry_back():
    coord = _coordinator({"Stue": RoomState.OVERRIDE})
    original = utcnow() + timedelta(minutes=30)
    coord.room_override_expires_at["Stue"] = original

    extended = coord.extend_overrides(60)

    assert extended == ["Stue"]
    assert coord.room_override_expires_at["Stue"] == original + timedelta(minutes=60)
    coord.log_event.assert_called_once()


def test_extend_overrides_counts_from_now_when_already_past():
    coord = _coordinator({"Stue": RoomState.OVERRIDE})
    coord.room_override_expires_at["Stue"] = utcnow() - timedelta(minutes=5)

    coord.extend_overrides(60)

    remaining = coord.room_override_expires_at["Stue"] - utcnow()
    assert timedelta(minutes=59) < remaining <= timedelta(minutes=60)


def test_extend_overrides_leaves_permanent_overrides_alone():
    coord = _coordinator({"Stue": RoomState.OVERRIDE})

    assert coord.extend_overrides(60) == []
    assert "Stue" not in coord.room_override_expires_at
    coord.log_event.assert_not_called()


def test_extend_overrides_ignores_rooms_no_longer_manual():
    coord = _coordinator({"Stue": RoomState.NORMAL})
    coord.room_override_expires_at["Stue"] = utcnow() + timedelta(minutes=5)

    assert coord.extend_overrides(60) == []


# ── snooze ───────────────────────────────────────────────────────────────────


def test_snooze_and_read_back():
    coord = _coordinator()

    until = coord.snooze_issue("window_open:Bad", 60)

    assert coord.get_issue_snoozed_until("window_open:Bad") == until
    assert coord.get_issue_snoozed_until("window_open:Bad,Stue") is None


def test_snooze_zero_unsnoozes():
    coord = _coordinator()
    coord.snooze_issue("mold_risk:Bad", 60)

    assert coord.snooze_issue("mold_risk:Bad", 0) is None
    assert coord.get_issue_snoozed_until("mold_risk:Bad") is None


def test_expired_snooze_is_dropped_on_read():
    coord = _coordinator()
    coord._issue_snoozed_until["x"] = utcnow() - timedelta(seconds=1)

    assert coord.get_issue_snoozed_until("x") is None
    assert "x" not in coord._issue_snoozed_until


# ── house status ─────────────────────────────────────────────────────────────


def test_house_status_auto():
    coord = _coordinator({"Stue": RoomState.NORMAL})
    assert coord.get_house_status()["status"] == HOUSE_STATUS_AUTO


def test_house_status_manual_with_return_time():
    coord = _coordinator({"Stue": RoomState.OVERRIDE, "Bad": RoomState.NORMAL})
    later = utcnow() + timedelta(hours=2)
    coord.room_override_expires_at["Stue"] = later

    info = coord.get_house_status()

    assert info["status"] == HOUSE_STATUS_MANUAL
    assert info["manual_rooms"] == ["Stue"]
    assert info["auto_returns_at"] == later


def test_house_status_no_return_time_when_one_room_is_permanent():
    coord = _coordinator({"Stue": RoomState.OVERRIDE, "Bad": RoomState.OVERRIDE})
    coord.room_override_expires_at["Stue"] = utcnow() + timedelta(hours=1)

    assert coord.get_house_status()["auto_returns_at"] is None


@pytest.mark.parametrize(
    ("ctrl", "states", "boost", "expected"),
    [
        (ControllerState.OFF, {"Bad": RoomState.WINDOW_OPEN}, 30, HOUSE_STATUS_OFF),
        (ControllerState.PAUSE, {"Bad": RoomState.WINDOW_OPEN}, 0, HOUSE_STATUS_PAUSED),
        (
            ControllerState.ON,
            {"Bad": RoomState.WINDOW_OPEN},
            30,
            HOUSE_STATUS_WINDOW_OPEN,
        ),
        (ControllerState.ON, {"Stue": RoomState.OVERRIDE}, 30, HOUSE_STATUS_BOOST),
        (ControllerState.ON, {"Stue": RoomState.OVERRIDE}, 0, HOUSE_STATUS_MANUAL),
    ],
)
def test_house_status_priority(ctrl, states, boost, expected):
    coord = _coordinator(states)
    coord.controller_state = ctrl
    coord.boost_remaining_minutes = boost
    assert coord.get_house_status()["status"] == expected


def test_house_status_sensor():
    coord = _coordinator({"Bad": RoomState.WINDOW_OPEN})
    entry = MagicMock()
    entry.entry_id = "abc"
    sensor = HouseStatusSensor(coord, entry)

    assert sensor.native_value == HOUSE_STATUS_WINDOW_OPEN
    assert set(sensor.options) == set(HOUSE_STATUSES)
    attrs = sensor.extra_state_attributes
    assert attrs["window_rooms"] == ["Bad"]
    assert attrs["auto_returns_at"] is None


# ── set_remote_last_action ───────────────────────────────────────────────────


def test_remote_last_action_records_structured_fields():
    coord = _coordinator()

    coord.set_remote_last_action(
        "Remote: +0.5°C — Stue → 21.5°C",
        ["Stue"],
        action="temp_up",
        delta=0.5,
        skipped={"Bad": "window_open"},
    )

    rla = coord.remote_last_action
    assert rla["action"] == "temp_up"
    assert rla["delta"] == 0.5
    assert rla["skipped"] == {"Bad": "window_open"}
    assert rla["rooms"] == ["Stue"]


# ── RemoteButtonEngine: long presses ─────────────────────────────────────────

UP = "event.w100_button_3"
MODE = "event.w100_button_4"
DOWN = "event.w100_button_5"


def _engine_coordinator(states: dict[str, RoomState]) -> MagicMock:
    coord = MagicMock()
    hass = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro, **kwargs: coro)
    coord.hass = hass
    coord.config = {
        CONF_BUTTON_TEMP_UP_ENTITY: UP,
        CONF_BUTTON_TEMP_DOWN_ENTITY: DOWN,
        CONF_BUTTON_MODE_TOGGLE_ENTITY: MODE,
    }
    coord.rooms = [{"room_name": n} for n in states]
    coord.get_room_state = MagicMock(side_effect=lambda n: states[n])
    coord.async_boost_start = AsyncMock(return_value=["Stue"])
    coord.async_release_all_overrides = AsyncMock(return_value=["Stue"])
    coord.set_remote_last_action = MagicMock()
    coord.log_event = MagicMock()
    return coord


def _event(event_type: str) -> MagicMock:
    new = MagicMock()
    new.entity_id = UP
    new.state = "2026-10-30T19:00:01+00:00"
    new.attributes = {"event_type": event_type}
    old = MagicMock()
    old.state = "2026-10-30T19:00:00+00:00"
    event = MagicMock()
    event.data = {"new_state": new, "old_state": old}
    return event


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("long_press", True),
        ("hold", True),
        ("hold_plus", True),
        ("long_release", False),
        ("release_plus", False),
        ("multi_press_1", False),
        (None, False),
    ],
)
def test_press_type_is_long(event_type, expected):
    assert RemoteButtonEngine._press_type_is_long(event_type) is expected


def test_long_press_on_temp_up_starts_boost_task():
    coord = _engine_coordinator({"Stue": RoomState.NORMAL})
    engine = RemoteButtonEngine(coord)
    engine._async_boost_all = MagicMock(return_value="coro")

    engine._handle_temp_up(_event("long_press"))

    engine._async_boost_all.assert_called_once_with()
    coord.hass.async_create_task.assert_called_once()


def test_long_release_does_nothing():
    coord = _engine_coordinator({"Stue": RoomState.NORMAL})
    engine = RemoteButtonEngine(coord)

    engine._handle_temp_up(_event("long_release"))
    engine._handle_mode_toggle(_event("long_release"))

    coord.hass.async_create_task.assert_not_called()


def test_long_press_on_temp_down_does_nothing():
    coord = _engine_coordinator({"Stue": RoomState.NORMAL})
    engine = RemoteButtonEngine(coord)

    engine._handle_temp_down(_event("long_press"))

    coord.hass.async_create_task.assert_not_called()


def test_long_press_on_mode_starts_release_task():
    coord = _engine_coordinator({"Stue": RoomState.OVERRIDE})
    engine = RemoteButtonEngine(coord)
    engine._async_release_all = MagicMock(return_value="coro")

    engine._handle_mode_toggle(_event("long_press"))

    engine._async_release_all.assert_called_once_with()


@pytest.mark.asyncio
async def test_boost_all_records_skipped_rooms():
    coord = _engine_coordinator(
        {"Stue": RoomState.NORMAL, "Bad": RoomState.WINDOW_OPEN}
    )
    engine = RemoteButtonEngine(coord)

    await engine._async_boost_all()

    coord.async_boost_start.assert_awaited_once_with()
    kwargs = coord.set_remote_last_action.call_args.kwargs
    assert kwargs["action"] == "boost"
    assert kwargs["skipped"] == {"Bad": "window_open"}


@pytest.mark.asyncio
async def test_boost_all_nothing_boosted_records_nothing():
    coord = _engine_coordinator({"Bad": RoomState.WINDOW_OPEN})
    coord.async_boost_start = AsyncMock(return_value=[])
    engine = RemoteButtonEngine(coord)

    await engine._async_boost_all()

    coord.set_remote_last_action.assert_not_called()


@pytest.mark.asyncio
async def test_release_all_clears_pending_and_records_action():
    coord = _engine_coordinator({"Stue": RoomState.OVERRIDE})
    engine = RemoteButtonEngine(coord)
    engine._pending_setpoints["Stue"] = (22.0, 10**12)

    await engine._async_release_all()

    coord.async_release_all_overrides.assert_awaited_once_with(reason="Remote")
    assert "Stue" not in engine._pending_setpoints
    assert coord.set_remote_last_action.call_args.kwargs["action"] == "release"


def test_skipped_rooms_lists_window_and_away():
    coord = _engine_coordinator(
        {
            "Stue": RoomState.NORMAL,
            "Bad": RoomState.WINDOW_OPEN,
            "Kontor": RoomState.AWAY,
        }
    )
    engine = RemoteButtonEngine(coord)

    assert engine._skipped_rooms() == {"Bad": "window_open", "Kontor": "away"}


# ── WebSocket commands ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_extend_overrides(monkeypatch):
    coord = MagicMock()
    coord.extend_overrides = MagicMock(return_value=["Stue"])
    entry = MagicMock()
    entry.runtime_data = coord
    monkeypatch.setattr(
        "custom_components.heat_manager.websocket._get_entry", lambda hass: entry
    )
    connection = MagicMock()

    await ws_extend_overrides.__wrapped__(
        MagicMock(),
        connection,
        {"id": 1, "type": "heat_manager/extend_overrides", "minutes": 60},
    )

    coord.extend_overrides.assert_called_once_with(60)
    connection.send_result.assert_called_once_with(
        1, {"success": True, "rooms_extended": ["Stue"]}
    )


@pytest.mark.asyncio
async def test_ws_snooze_issue(monkeypatch):
    until = utcnow() + timedelta(hours=1)
    coord = MagicMock()
    coord.snooze_issue = MagicMock(return_value=until)
    entry = MagicMock()
    entry.runtime_data = coord
    monkeypatch.setattr(
        "custom_components.heat_manager.websocket._get_entry", lambda hass: entry
    )
    connection = MagicMock()

    await ws_snooze_issue.__wrapped__(
        MagicMock(),
        connection,
        {
            "id": 2,
            "type": "heat_manager/snooze_issue",
            "issue_id": "window_open:Bad",
            "minutes": 60,
        },
    )

    coord.snooze_issue.assert_called_once_with("window_open:Bad", 60)
    connection.send_result.assert_called_once_with(
        2, {"success": True, "snoozed_until": until.isoformat()}
    )


@pytest.mark.asyncio
async def test_ws_commands_not_loaded(monkeypatch):
    monkeypatch.setattr(
        "custom_components.heat_manager.websocket._get_entry", lambda hass: None
    )
    connection = MagicMock()

    await ws_extend_overrides.__wrapped__(
        MagicMock(), connection, {"id": 3, "minutes": 60}
    )
    await ws_snooze_issue.__wrapped__(
        MagicMock(), connection, {"id": 4, "issue_id": "x", "minutes": 60}
    )

    assert connection.send_error.call_count == 2
    connection.send_result.assert_not_called()
