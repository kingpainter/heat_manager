"""Tests for _async_check_repair_issues() and _async_remove_stale_devices().

Covers:
- Issue created when climate entity is missing
- Issue deleted when climate entity is present
- Issue ID includes room name and entry_id prefix
- No issue created when room has no climate entity configured
- Stale device removed when room deleted from config
- Valid room devices not touched
- Global device never removed
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from custom_components.heat_manager.const import (
    DOMAIN,
    REPAIR_ISSUE_MISSING_CLIMATE,
)
from custom_components.heat_manager import (
    _async_check_repair_issues,
    _async_remove_stale_devices,
)


ENTRY_ID = "abcdef1234567890"
ENTRY_ID_SHORT = ENTRY_ID[:8]  # "abcdef12"


def _make_entry(rooms: list[dict], entry_id: str = ENTRY_ID) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"rooms": rooms}
    entry.options = {}
    return entry


def _make_hass(existing_entity_ids: list[str]) -> MagicMock:
    hass = MagicMock()

    def states_get(entity_id: str):
        if entity_id in existing_entity_ids:
            return MagicMock(state="heat")
        return None

    hass.states.get = MagicMock(side_effect=states_get)
    return hass


# ── _async_check_repair_issues ────────────────────────────────────────────────

def test_issue_created_for_missing_climate_entity():
    """Climate entity absent → async_create_issue called."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    hass = _make_hass([])  # entity missing

    with patch(
        "custom_components.heat_manager.async_create_issue"
    ) as mock_create, patch(
        "custom_components.heat_manager.async_delete_issue"
    ) as mock_delete:
        _async_check_repair_issues(hass, entry)

    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs[0][0] is hass
    assert call_kwargs[0][1] == DOMAIN
    assert "stue" in call_kwargs[0][2]  # issue_id contains safe room name
    assert ENTRY_ID_SHORT in call_kwargs[0][2]
    mock_delete.assert_not_called()


def test_issue_deleted_when_entity_present():
    """Climate entity present → async_delete_issue called, not create."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    hass = _make_hass(["climate.stue"])

    with patch(
        "custom_components.heat_manager.async_create_issue"
    ) as mock_create, patch(
        "custom_components.heat_manager.async_delete_issue"
    ) as mock_delete:
        _async_check_repair_issues(hass, entry)

    mock_create.assert_not_called()
    mock_delete.assert_called_once()
    issue_id = mock_delete.call_args[0][2]
    assert "stue" in issue_id
    assert ENTRY_ID_SHORT in issue_id


def test_no_issue_for_room_without_climate_entity():
    """Room with empty climate_entity → skipped entirely."""
    entry = _make_entry([{"room_name": "Bad", "climate_entity": ""}])
    hass = _make_hass([])

    with patch(
        "custom_components.heat_manager.async_create_issue"
    ) as mock_create, patch(
        "custom_components.heat_manager.async_delete_issue"
    ) as mock_delete:
        _async_check_repair_issues(hass, entry)

    mock_create.assert_not_called()
    mock_delete.assert_not_called()


def test_multiple_rooms_independent_issues():
    """Two rooms — one missing, one present → one create, one delete."""
    entry = _make_entry([
        {"room_name": "Stue", "climate_entity": "climate.stue"},
        {"room_name": "Sove", "climate_entity": "climate.sove"},
    ])
    hass = _make_hass(["climate.stue"])  # Stue present, Sove missing

    with patch(
        "custom_components.heat_manager.async_create_issue"
    ) as mock_create, patch(
        "custom_components.heat_manager.async_delete_issue"
    ) as mock_delete:
        _async_check_repair_issues(hass, entry)

    assert mock_create.call_count == 1
    assert mock_delete.call_count == 1
    # Create is for Sove (missing), delete is for Stue (present)
    create_issue_id = mock_create.call_args[0][2]
    assert "sove" in create_issue_id
    delete_issue_id = mock_delete.call_args[0][2]
    assert "stue" in delete_issue_id


def test_issue_id_spaces_replaced_with_underscores():
    """Room name with spaces → issue ID uses underscores."""
    entry = _make_entry([{"room_name": "Flemming Kontor", "climate_entity": "climate.kontor"}])
    hass = _make_hass([])

    with patch("custom_components.heat_manager.async_create_issue") as mock_create, \
         patch("custom_components.heat_manager.async_delete_issue"):
        _async_check_repair_issues(hass, entry)

    issue_id = mock_create.call_args[0][2]
    assert " " not in issue_id
    assert "flemming_kontor" in issue_id


def test_translation_placeholders_include_room_and_entity():
    """Created issue must include room_name and climate_id placeholders."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue_netatmo"}])
    hass = _make_hass([])

    with patch("custom_components.heat_manager.async_create_issue") as mock_create, \
         patch("custom_components.heat_manager.async_delete_issue"):
        _async_check_repair_issues(hass, entry)

    kwargs = mock_create.call_args[1]
    placeholders = kwargs.get("translation_placeholders", {})
    assert placeholders.get("room_name") == "Stue"
    assert placeholders.get("climate_id") == "climate.stue_netatmo"


# ── _async_remove_stale_devices ───────────────────────────────────────────────

def _make_device(identifiers: set, name: str, device_id: str) -> MagicMock:
    dev = MagicMock()
    dev.identifiers = identifiers
    dev.name = name
    dev.id = device_id
    return dev


def test_stale_room_device_removed():
    """Device for deleted room → async_remove_device called."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    hass = MagicMock()

    # Registry contains: global + Stue (current) + Sove (stale — room deleted)
    global_device = _make_device(
        {(DOMAIN, ENTRY_ID)}, "Heat Manager", "dev_global"
    )
    stue_device = _make_device(
        {(DOMAIN, f"{ENTRY_ID}_stue")}, "Stue", "dev_stue"
    )
    sove_device = _make_device(
        {(DOMAIN, f"{ENTRY_ID}_sove")}, "Sove", "dev_sove"
    )

    dev_reg = MagicMock()
    dev_reg.async_entries_for_config_entry = MagicMock(
        return_value=[global_device, stue_device, sove_device]
    )

    with patch(
        "custom_components.heat_manager.dr.async_get", return_value=dev_reg
    ), patch(
        "custom_components.heat_manager.dr.async_entries_for_config_entry",
        return_value=[global_device, stue_device, sove_device],
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_called_once_with("dev_sove")


def test_current_room_device_not_removed():
    """Device for existing room → not touched."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    hass = MagicMock()

    global_device = _make_device({(DOMAIN, ENTRY_ID)}, "Heat Manager", "dev_global")
    stue_device = _make_device({(DOMAIN, f"{ENTRY_ID}_stue")}, "Stue", "dev_stue")

    dev_reg = MagicMock()

    with patch(
        "custom_components.heat_manager.dr.async_get", return_value=dev_reg
    ), patch(
        "custom_components.heat_manager.dr.async_entries_for_config_entry",
        return_value=[global_device, stue_device],
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_not_called()


def test_global_device_never_removed():
    """Global device (entry_id only) must never be removed."""
    entry = _make_entry([])  # No rooms at all
    hass = MagicMock()

    global_device = _make_device({(DOMAIN, ENTRY_ID)}, "Heat Manager", "dev_global")
    dev_reg = MagicMock()

    with patch(
        "custom_components.heat_manager.dr.async_get", return_value=dev_reg
    ), patch(
        "custom_components.heat_manager.dr.async_entries_for_config_entry",
        return_value=[global_device],
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_not_called()


def test_no_devices_in_registry():
    """Empty registry → no removal, no crash."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    hass = MagicMock()
    dev_reg = MagicMock()

    with patch(
        "custom_components.heat_manager.dr.async_get", return_value=dev_reg
    ), patch(
        "custom_components.heat_manager.dr.async_entries_for_config_entry",
        return_value=[],
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_not_called()
