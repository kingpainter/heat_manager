"""Tests for engine/netatmo_backend.py and the coordinator lookups built on it
(v0.61.0). Fully offline — the entity registry and config entries are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.netatmo_backend import (
    BACKEND_SUMMARY_MIXED,
    BACKEND_SUMMARY_NONE,
    NetatmoBackend,
    available_backends,
    effective_backend,
    resolve_backend,
    summarize_backends,
    trv_pid_writable,
)

CORE = NetatmoBackend.CORE
NET_TRV = NetatmoBackend.NET_TRV

# ── resolve_backend ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("netatmo", CORE),
        ("net_trv", NET_TRV),
        ("homekit_controller", None),
        ("mqtt", None),
        ("", None),
        (None, None),
    ],
)
def test_resolve_backend(platform, expected):
    assert resolve_backend(platform) is expected


# ── available_backends ────────────────────────────────────────────────────────


def test_available_backends_filters_non_netatmo_domains():
    assert available_backends(["mqtt", "net_trv", "netatmo", "zha"]) == {
        CORE,
        NET_TRV,
    }


def test_available_backends_empty():
    assert available_backends([]) == set()


# ── effective_backend ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("choice", ["auto", None, ""])
def test_auto_prefers_net_trv_when_both_installed(choice):
    assert effective_backend(choice, {CORE, NET_TRV}) is NET_TRV


def test_auto_falls_back_to_core():
    assert effective_backend("auto", {CORE}) is CORE


def test_auto_with_nothing_installed_is_none():
    assert effective_backend("auto", set()) is None


def test_explicit_choice_used_when_installed():
    assert effective_backend("netatmo", {CORE, NET_TRV}) is CORE


def test_explicit_choice_missing_is_none():
    """e.g. core removed after the user picked "Core" → caller raises a repair."""
    assert effective_backend("netatmo", {NET_TRV}) is None


# ── summarize_backends ────────────────────────────────────────────────────────


def test_summary_single_backend():
    assert summarize_backends([NET_TRV, NET_TRV, None]) == "net_trv"


def test_summary_mixed():
    assert summarize_backends([NET_TRV, CORE]) == BACKEND_SUMMARY_MIXED


def test_summary_no_netatmo_valves():
    assert summarize_backends([None, None]) == BACKEND_SUMMARY_NONE
    assert summarize_backends([]) == BACKEND_SUMMARY_NONE


# ── Coordinator lookups ───────────────────────────────────────────────────────


def _coordinator(platforms: dict[str, str], installed: set[str]) -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.hass.config_entries.async_entries = MagicMock(
        side_effect=lambda domain: [MagicMock()] if domain in installed else []
    )
    for name in (
        "get_trv_netatmo_backend",
        "get_room_netatmo_backend",
        "get_installed_netatmo_backends",
    ):
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )
    coord.get_trv_climate_entity = HeatManagerCoordinator.get_trv_climate_entity

    registry = MagicMock()
    registry.async_get = MagicMock(
        side_effect=lambda eid: (
            SimpleNamespace(platform=platforms[eid]) if eid in platforms else None
        )
    )
    coord._registry = registry
    return coord


def _patch_registry(coord):
    return patch(
        "custom_components.heat_manager.coordinator.er.async_get",
        return_value=coord._registry,
    )


def test_trv_backend_from_registry_platform_not_entity_name():
    """climate.kitchen_core is owned by NET-TRV here on purpose: the name must
    not matter, only the registry platform."""
    coord = _coordinator({"climate.kitchen_core": "net_trv"}, set())
    with _patch_registry(coord):
        backend = coord.get_trv_netatmo_backend(
            {"climate_entity": "climate.kitchen_core"}
        )
    assert backend is NET_TRV


def test_trv_backend_none_for_zigbee_and_missing_entity():
    coord = _coordinator({"climate.trv_z2m": "mqtt"}, set())
    with _patch_registry(coord):
        assert (
            coord.get_trv_netatmo_backend({"climate_entity": "climate.trv_z2m"}) is None
        )
        assert coord.get_trv_netatmo_backend({"climate_entity": "climate.gone"}) is None
        assert coord.get_trv_netatmo_backend({}) is None


def test_room_backend_summary_mixed():
    coord = _coordinator(
        {"climate.a": "net_trv", "climate.b": "netatmo"}, {"netatmo", "net_trv"}
    )
    coord.get_room_trvs = MagicMock(
        return_value=[{"climate_entity": "climate.a"}, {"climate_entity": "climate.b"}]
    )
    with _patch_registry(coord):
        assert coord.get_room_netatmo_backend("Stue") == BACKEND_SUMMARY_MIXED


def test_installed_backends_from_config_entries():
    coord = _coordinator({}, {"net_trv"})
    assert coord.get_installed_netatmo_backends() == {NET_TRV}


# ── trv_pid_writable (v0.61.2) ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("trv_type", "has_homekit", "expected"),
    [
        ("netatmo", True, True),
        ("netatmo", False, False),
        (None, False, False),
        ("zigbee", False, True),
        ("zigbee", True, True),
    ],
)
def test_trv_pid_writable(trv_type, has_homekit, expected):
    assert trv_pid_writable(trv_type, has_homekit) is expected


def test_rooms_pid_needs_homekit():
    coord = MagicMock()
    coord.pid_enabled = True
    coord.rooms = [{"room_name": "Kitchen"}, {"room_name": "Hall"}, {"room_name": "Z"}]
    trvs = {
        "Kitchen": [{"climate_entity": "climate.kitchen", "trv_type": "netatmo"}],
        "Hall": [],
        "Z": [{"climate_entity": "climate.z", "trv_type": "zigbee"}],
    }
    coord.get_room_trvs = MagicMock(side_effect=lambda n: trvs[n])
    coord.get_trv_homekit_entity = HeatManagerCoordinator.get_trv_homekit_entity
    for name in ("is_trv_pid_writable", "get_rooms_pid_needs_homekit"):
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )
    assert coord.get_rooms_pid_needs_homekit() == ["Kitchen"]
    coord.pid_enabled = False
    assert coord.get_rooms_pid_needs_homekit() == []
