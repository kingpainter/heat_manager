"""Tests for _async_check_repair_issues() and _async_remove_stale_devices().

Covers:
- No issue within the grace period after startup (v0.65.4)
- Issue created once the climate entity has been missing for the grace period
- Issue deleted as soon as the climate entity exists, without a reload
- Issue ID includes room name and entry_id prefix
- No issue created when room has no climate entity configured
- Stale device removed when room deleted from config
- Valid room devices not touched
- Global device never removed
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from custom_components.heat_manager import (
    _async_check_repair_issues,
    _async_remove_stale_devices,
)
from custom_components.heat_manager.const import (
    DOMAIN,
    MISSING_CLIMATE_GRACE_SECONDS,
)
from custom_components.heat_manager.coordinator import HeatManagerCoordinator

ENTRY_ID = "abcdef1234567890"
ENTRY_ID_SHORT = ENTRY_ID[:8]  # "abcdef12"


def _make_entry(rooms: list[dict], entry_id: str = ENTRY_ID) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"rooms": rooms}
    entry.options = {}
    # 2026-09 audit fix: the check resolves each room's climate entity via
    # coordinator.get_climate_entity() (TRV-aware) instead of the room's
    # flat field — mirror that from the same flat fields these tests use.
    entry.runtime_data.get_climate_entity = MagicMock(
        side_effect=lambda name: next(
            (r.get("climate_entity") for r in rooms if r.get("room_name") == name),
            None,
        )
    )
    return entry


def _make_hass(existing_entity_ids: list[str]) -> MagicMock:
    hass = MagicMock()

    def states_get(entity_id: str):
        if entity_id in existing_entity_ids:
            return MagicMock(state="heat")
        return None

    hass.states.get = MagicMock(side_effect=states_get)
    return hass


# ── missing-climate repair issue (coordinator.check_missing_climate_entities) ─
#
# v0.65.4: _async_check_repair_issues() delegates to the coordinator, which
# also runs the check every tick. An issue is raised only after the entity
# has been missing for MISSING_CLIMATE_GRACE_SECONDS and is cleared as soon
# as the entity exists — no reload needed.

T0 = datetime(2026, 11, 12, 14, 34, 11, tzinfo=UTC)
COORD = "custom_components.heat_manager.coordinator.issues"


def _make_coordinator(rooms: list[dict], hass: MagicMock) -> MagicMock:
    coord = MagicMock(spec=HeatManagerCoordinator)
    coord.hass = hass
    coord.entry = MagicMock(entry_id=ENTRY_ID)
    coord.rooms = rooms
    coord._climate_missing_since = {}
    coord._climate_missing_raised = set()
    coord.get_climate_entity = MagicMock(
        side_effect=lambda name: next(
            (r.get("climate_entity") for r in rooms if r.get("room_name") == name),
            None,
        )
    )
    for name in ("missing_climate_issue_id", "check_missing_climate_entities"):
        setattr(coord, name, getattr(HeatManagerCoordinator, name).__get__(coord))
    return coord


def _run(coord: MagicMock, at: datetime) -> tuple[MagicMock, MagicMock]:
    with (
        patch(f"{COORD}.utcnow", return_value=at),
        patch(f"{COORD}.async_create_issue") as mock_create,
        patch(f"{COORD}.async_delete_issue") as mock_delete,
    ):
        coord.check_missing_climate_entities()
    return mock_create, mock_delete


def test_setup_check_delegates_to_coordinator():
    """_async_check_repair_issues() runs the coordinator check."""
    entry = MagicMock()
    _async_check_repair_issues(MagicMock(), entry)
    entry.runtime_data.check_missing_climate_entities.assert_called_once_with()


def test_no_issue_while_within_grace_period():
    """Missing at startup → no issue yet (cloud integration may be late)."""
    rooms = [{"room_name": "Stue", "climate_entity": "climate.stue"}]
    coord = _make_coordinator(rooms, _make_hass([]))

    create, delete = _run(coord, T0)
    create.assert_not_called()
    delete.assert_not_called()

    late = T0 + timedelta(seconds=MISSING_CLIMATE_GRACE_SECONDS - 1)
    create, _ = _run(coord, late)
    create.assert_not_called()


def test_issue_created_after_grace_period():
    """Still missing after the grace period → issue raised once."""
    rooms = [{"room_name": "Stue", "climate_entity": "climate.stue_netatmo"}]
    coord = _make_coordinator(rooms, _make_hass([]))
    _run(coord, T0)

    after = T0 + timedelta(seconds=MISSING_CLIMATE_GRACE_SECONDS)
    create, _ = _run(coord, after)
    create.assert_called_once()
    args, kwargs = create.call_args
    assert args[1] == DOMAIN
    assert "stue" in args[2]
    assert ENTRY_ID_SHORT in args[2]
    assert kwargs["translation_placeholders"] == {
        "room_name": "Stue",
        "climate_id": "climate.stue_netatmo",
    }

    # Not raised again on later ticks.
    create, _ = _run(coord, after + timedelta(minutes=10))
    create.assert_not_called()


def test_issue_cleared_when_entity_appears_without_reload():
    """Entity shows up after the issue was raised → issue deleted next tick."""
    rooms = [{"room_name": "Stue", "climate_entity": "climate.stue"}]
    present: list[str] = []
    coord = _make_coordinator(rooms, _make_hass(present))
    _run(coord, T0)
    _run(coord, T0 + timedelta(seconds=MISSING_CLIMATE_GRACE_SECONDS))
    assert "Stue" in coord._climate_missing_raised

    present.append("climate.stue")
    create, delete = _run(coord, T0 + timedelta(minutes=6))
    create.assert_not_called()
    delete.assert_called_once()
    assert "stue" in delete.call_args[0][2]
    assert coord._climate_missing_raised == set()
    assert coord._climate_missing_since == {}


def test_entity_appearing_within_grace_resets_timer():
    """Late entity within the grace period → no issue, timer reset."""
    rooms = [{"room_name": "Stue", "climate_entity": "climate.stue"}]
    present: list[str] = []
    coord = _make_coordinator(rooms, _make_hass(present))
    _run(coord, T0)

    present.append("climate.stue")
    create, _ = _run(coord, T0 + timedelta(seconds=30))
    create.assert_not_called()
    assert coord._climate_missing_since == {}


def test_present_entity_deletes_leftover_issue():
    """Entity present → stale issue from a previous run is deleted."""
    rooms = [{"room_name": "Stue", "climate_entity": "climate.stue"}]
    coord = _make_coordinator(rooms, _make_hass(["climate.stue"]))

    create, delete = _run(coord, T0)
    create.assert_not_called()
    delete.assert_called_once()
    assert ENTRY_ID_SHORT in delete.call_args[0][2]


def test_no_issue_for_room_without_climate_entity():
    """Room with empty climate_entity → skipped entirely."""
    rooms = [{"room_name": "Bad", "climate_entity": ""}]
    coord = _make_coordinator(rooms, _make_hass([]))

    create, delete = _run(coord, T0 + timedelta(hours=1))
    _run(coord, T0 + timedelta(hours=2))
    create.assert_not_called()
    delete.assert_not_called()


def test_multiple_rooms_independent_issues():
    """Two rooms — one missing, one present → one create, deletes for present."""
    rooms = [
        {"room_name": "Stue", "climate_entity": "climate.stue"},
        {"room_name": "Sove", "climate_entity": "climate.sove"},
    ]
    coord = _make_coordinator(rooms, _make_hass(["climate.stue"]))
    _run(coord, T0)

    create, delete = _run(coord, T0 + timedelta(seconds=MISSING_CLIMATE_GRACE_SECONDS))
    assert create.call_count == 1
    assert "sove" in create.call_args[0][2]
    assert delete.call_count == 1
    assert "stue" in delete.call_args[0][2]


def test_issue_id_spaces_replaced_with_underscores():
    """Room name with spaces → issue ID uses underscores."""
    coord = _make_coordinator([], _make_hass([]))
    issue_id = coord.missing_climate_issue_id("Flemming Kontor")
    assert " " not in issue_id
    assert "flemming_kontor" in issue_id
    assert issue_id.endswith(ENTRY_ID_SHORT)


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
    global_device = _make_device({(DOMAIN, ENTRY_ID)}, "Heat Manager", "dev_global")
    stue_device = _make_device({(DOMAIN, f"{ENTRY_ID}_stue")}, "Stue", "dev_stue")
    sove_device = _make_device({(DOMAIN, f"{ENTRY_ID}_sove")}, "Sove", "dev_sove")

    dev_reg = MagicMock()
    dev_reg.async_entries_for_config_entry = MagicMock(
        return_value=[global_device, stue_device, sove_device]
    )

    with (
        patch("custom_components.heat_manager.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.heat_manager.dr.async_entries_for_config_entry",
            return_value=[global_device, stue_device, sove_device],
        ),
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

    with (
        patch("custom_components.heat_manager.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.heat_manager.dr.async_entries_for_config_entry",
            return_value=[global_device, stue_device],
        ),
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_not_called()


def test_global_device_never_removed():
    """Global device (entry_id only) must never be removed."""
    entry = _make_entry([])  # No rooms at all
    hass = MagicMock()

    global_device = _make_device({(DOMAIN, ENTRY_ID)}, "Heat Manager", "dev_global")
    dev_reg = MagicMock()

    with (
        patch("custom_components.heat_manager.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.heat_manager.dr.async_entries_for_config_entry",
            return_value=[global_device],
        ),
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_not_called()


def test_no_devices_in_registry():
    """Empty registry → no removal, no crash."""
    entry = _make_entry([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    hass = MagicMock()
    dev_reg = MagicMock()

    with (
        patch("custom_components.heat_manager.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.heat_manager.dr.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        _async_remove_stale_devices(hass, entry)

    dev_reg.async_remove_device.assert_not_called()
