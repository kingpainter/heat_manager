"""Tests for engine/clock.py — the engines' pure clock (v0.68.0, T2)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from custom_components.heat_manager.engine import clock

ENGINE_DIR = Path(__file__).parents[3] / "custom_components" / "heat_manager" / "engine"


def test_defaults_are_utc_aware():
    assert clock.utcnow().tzinfo is not None
    assert clock.utcnow().utcoffset().total_seconds() == 0


def test_use_providers_routes_both_functions():
    fixed_utc = datetime(2026, 11, 12, 19, 0, tzinfo=UTC)
    fixed_local = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
    old = (clock._utcnow_provider, clock._local_now_provider)
    try:
        clock.use_providers(utcnow=lambda: fixed_utc, local_now=lambda: fixed_local)
        assert clock.utcnow() is fixed_utc
        assert clock.local_now() is fixed_local
    finally:
        clock._utcnow_provider, clock._local_now_provider = old


def _imports_homeassistant(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "homeassistant"
        ):
            return True
        if isinstance(node, ast.Import) and any(
            a.name.startswith("homeassistant") for a in node.names
        ):
            return True
    return False


def test_pure_engines_do_not_import_homeassistant():
    """Architecture rule 3.1: these engines no longer import homeassistant."""
    for name in (
        "clock",
        "calibration_engine",
        "controller",
        "season_engine",
        "valve_protection_engine",
        # v0.67.5 (T2b): state-change subscriptions via the coordinator
        "door_engine",
        "preheat_engine",
        "presence_engine",
        # v0.67.6 (T2c): the last three — every engine is pure now
        "remote_button_engine",
        "sync_engine",
        "window_engine",
    ):
        assert not _imports_homeassistant(ENGINE_DIR / f"{name}.py"), name


def test_track_state_changes_wraps_handler_as_callback():
    """v0.67.5: the coordinator subscribes for the engines and marks the
    forwarder @callback, so Home Assistant runs it in the event loop."""
    from unittest.mock import MagicMock, patch

    from custom_components.heat_manager.coordinator import HeatManagerCoordinator

    coord = MagicMock()
    coord.hass = MagicMock()
    handler = MagicMock()
    with patch(
        "custom_components.heat_manager.coordinator.async_track_state_change_event",
        return_value="unsub",
    ) as track:
        unsub = HeatManagerCoordinator.track_state_changes(
            coord, ["binary_sensor.door"], handler
        )
    assert unsub == "unsub"
    hass_arg, ids, forward = track.call_args[0]
    assert hass_arg is coord.hass
    assert ids == ["binary_sensor.door"]
    assert getattr(forward, "_hass_callback", False) is True
    forward("event")
    handler.assert_called_once_with("event")


def test_every_engine_module_is_pure():
    """v0.67.6: architecture rule 3.1 holds for the whole engine package —
    a new engine module that imports homeassistant fails here."""
    offenders = [
        p.name for p in sorted(ENGINE_DIR.glob("*.py")) if _imports_homeassistant(p)
    ]
    assert offenders == []


def test_call_later_wraps_action_as_callback():
    from unittest.mock import MagicMock, patch

    from custom_components.heat_manager.coordinator import HeatManagerCoordinator

    coord = MagicMock()
    action = MagicMock()
    with patch(
        "custom_components.heat_manager.coordinator.async_call_later",
        return_value="cancel",
    ) as later:
        cancel = HeatManagerCoordinator.call_later(coord, 30, action)
    assert cancel == "cancel"
    hass_arg, delay, run = later.call_args[0]
    assert hass_arg is coord.hass
    assert delay == 30
    assert getattr(run, "_hass_callback", False) is True
    run("now")
    action.assert_called_once_with()
