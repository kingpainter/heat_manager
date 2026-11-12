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


def test_clock_only_engines_are_pure():
    """Architecture rule 3.1: these engines no longer import homeassistant."""
    for name in (
        "clock",
        "calibration_engine",
        "controller",
        "season_engine",
        "valve_protection_engine",
    ):
        assert not _imports_homeassistant(ENGINE_DIR / f"{name}.py"), name
