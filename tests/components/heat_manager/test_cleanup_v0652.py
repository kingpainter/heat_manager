"""Tests for the v0.65.2 cleanup at setup: stale config keys from removed
features are stripped, and this entry's leftover "persistent_*" repair
issues are deleted. Fully offline.
"""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock, patch

from custom_components.heat_manager import (
    _async_clear_stale_persistent_issues,
    _async_strip_stale_config,
)
from custom_components.heat_manager.const import DOMAIN
from custom_components.heat_manager.migrations import strip_stale_config

# ── strip_stale_config ────────────────────────────────────────────────────────


def test_strips_energy_keys_and_room_wattage():
    config = {
        "weather_entity": "weather.hjem",
        "energy_tracking": True,
        "_energy_history": "{}",
        "rooms": [
            {"room_name": "Køkken", "room_wattage": 1000, "comfort_temp": 22.0},
            {"room_name": "Gang"},
        ],
    }
    assert strip_stale_config(config) == {
        "weather_entity": "weather.hjem",
        "rooms": [{"room_name": "Køkken", "comfort_temp": 22.0}, {"room_name": "Gang"}],
    }
    # the input is not mutated
    assert "energy_tracking" in config
    assert "room_wattage" in config["rooms"][0]


def test_clean_config_returns_none():
    assert (
        strip_stale_config({"rooms": [{"room_name": "Gang"}], "pid_enabled": True})
        is None
    )
    assert strip_stale_config({}) is None


# ── Entry update ──────────────────────────────────────────────────────────────


def _entry(data: dict, options: dict) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "01KM1BJQB193Y3HF2AEC3X66W3"
    entry.data = MappingProxyType(data)
    entry.options = MappingProxyType(options)
    return entry


def test_entry_updated_only_where_stale_keys_exist():
    hass = MagicMock()
    entry = _entry({"rooms": []}, {"energy_tracking": True, "pid_enabled": True})
    _async_strip_stale_config(hass, entry)
    hass.config_entries.async_update_entry.assert_called_once()
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["data"] is entry.data  # untouched
    assert kwargs["options"] == {"pid_enabled": True}


def test_clean_entry_is_not_written():
    hass = MagicMock()
    _async_strip_stale_config(hass, _entry({"rooms": []}, {"pid_enabled": True}))
    hass.config_entries.async_update_entry.assert_not_called()


# ── Stale repair issues ───────────────────────────────────────────────────────


def test_only_this_entrys_persistent_issues_are_deleted():
    issues = {
        (DOMAIN, "persistent_cloud_down_01KM1BJQ"): object(),
        (DOMAIN, "persistent_mold_risk_bad_01KM1BJQ"): object(),
        (DOMAIN, "persistent_cloud_down_OTHERENT"): object(),  # other entry
        (DOMAIN, "missing_climate_entity_01KM1BJQ_kitchen"): object(),
        ("netatmo", "persistent_cloud_down_01KM1BJQ"): object(),  # other domain
    }
    registry = MagicMock(issues=issues)
    with (
        patch("custom_components.heat_manager.ir.async_get", return_value=registry),
        patch("custom_components.heat_manager.async_delete_issue") as delete,
    ):
        _async_clear_stale_persistent_issues(MagicMock(), _entry({}, {}))

    deleted = {c.args[2] for c in delete.call_args_list}
    assert deleted == {
        "persistent_cloud_down_01KM1BJQ",
        "persistent_mold_risk_bad_01KM1BJQ",
    }


# ── v0.67.0: per-room away_temp_override → global min_room_temp ─────────────


def test_strips_per_room_away_temp_override():
    config = {
        "rooms": [
            {"room_name": "Soveværelset", "away_temp_override": 18.0},
            {"room_name": "Køkken", "away_temp_override": 10, "comfort_temp": 21.0},
        ],
    }
    assert strip_stale_config(config) == {
        "rooms": [
            {"room_name": "Soveværelset"},
            {"room_name": "Køkken", "comfort_temp": 21.0},
        ],
    }


def test_min_room_temp_default_and_override():
    from custom_components.heat_manager.const import (
        CONF_MIN_ROOM_TEMP,
        DEFAULT_MIN_ROOM_TEMP,
    )
    from custom_components.heat_manager.coordinator import HeatManagerCoordinator

    prop = HeatManagerCoordinator.min_room_temp.fget
    coord = MagicMock()
    coord.config = {}
    assert prop(coord) == DEFAULT_MIN_ROOM_TEMP == 17.0
    coord.config = {CONF_MIN_ROOM_TEMP: 16}
    assert prop(coord) == 16.0
