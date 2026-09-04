"""Tests for custom_components.heat_manager.migrations (B18 — TRV
grouping groundwork, Fase 1).

migrate_room_to_trvs()/migrate_rooms_to_trvs() are pure functions (no
homeassistant.* imports) — tested completely offline, same as the engine/
modules. async_migrate_entry() (the HA-facing wrapper in __init__.py) is
covered separately below with a lightweight mocked ConfigEntry/hass, since
it only calls hass.config_entries.async_update_entry() and does not need a
running HA core.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.heat_manager.const import (
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_TRV_TYPE,
    CONF_TRVS,
)
from custom_components.heat_manager.migrations import (
    migrate_room_to_trvs,
    migrate_rooms_to_trvs,
)

# ── migrate_room_to_trvs — fresh (pre-migration) rooms ──────────────────────


def test_migrate_fresh_single_trv_room_builds_trvs_list():
    """A pre-B18 flat room gets a CONF_TRVS list built from its flat
    fields, and the flat fields themselves are left in place (flat
    mirror)."""
    room = {
        CONF_ROOM_NAME: "Bathroom",
        CONF_CLIMATE_ENTITY: "climate.bathroom",
        CONF_TRV_TYPE: "netatmo",
        CONF_CALIBRATION_ENTITY: "number.bathroom_calibration",
    }
    migrated = migrate_room_to_trvs(room)

    assert migrated[CONF_TRVS] == [
        {
            CONF_CLIMATE_ENTITY: "climate.bathroom",
            CONF_TRV_TYPE: "netatmo",
            CONF_CALIBRATION_ENTITY: "number.bathroom_calibration",
        }
    ]
    # Flat fields untouched — every other module keeps working.
    assert migrated[CONF_CLIMATE_ENTITY] == "climate.bathroom"
    assert migrated[CONF_CALIBRATION_ENTITY] == "number.bathroom_calibration"


def test_migrate_fresh_room_omits_blank_optional_trv_fields():
    """Fields that are absent or "" on the flat room must not show up as
    "" inside the built TRV dict (that's the exact B17 shape voluptuous
    entity selectors reject)."""
    room = {
        CONF_ROOM_NAME: "Kitchen",
        CONF_CLIMATE_ENTITY: "climate.kitchen",
        CONF_CALIBRATION_ENTITY: "",
        CONF_HOMEKIT_CLIMATE_ENTITY: "",
    }
    migrated = migrate_room_to_trvs(room)

    trv = migrated[CONF_TRVS][0]
    assert trv == {CONF_CLIMATE_ENTITY: "climate.kitchen"}
    assert CONF_CALIBRATION_ENTITY not in trv
    assert CONF_HOMEKIT_CLIMATE_ENTITY not in trv


def test_migrate_room_with_no_climate_entity_is_left_untouched():
    """A room with no usable climate entity at all (edge case) gets no
    invented TRV — nothing sane to build. Existing entity_not_found /
    ConfigEntryNotReady handling covers this elsewhere."""
    room = {CONF_ROOM_NAME: "Empty Room"}
    migrated = migrate_room_to_trvs(room)

    assert CONF_TRVS not in migrated
    assert migrated == room


def test_migrate_room_does_not_mutate_input():
    """migrate_room_to_trvs() must return a new dict, not mutate the one
    it was given (HA config entry data should be treated as immutable)."""
    room = {CONF_ROOM_NAME: "Kitchen", CONF_CLIMATE_ENTITY: "climate.kitchen"}
    original = dict(room)
    migrate_room_to_trvs(room)
    assert room == original


# ── migrate_room_to_trvs — idempotency / re-migration ───────────────────────


def test_migrate_already_migrated_room_is_idempotent():
    """Calling migrate_room_to_trvs() again on an already-migrated room
    (nothing changed) must return an equivalent room, not double-wrap or
    duplicate anything."""
    room = {
        CONF_ROOM_NAME: "Bathroom",
        CONF_CLIMATE_ENTITY: "climate.bathroom",
        CONF_TRVS: [{CONF_CLIMATE_ENTITY: "climate.bathroom"}],
    }
    once = migrate_room_to_trvs(room)
    twice = migrate_room_to_trvs(once)
    assert once == twice


def test_migrate_resyncs_flat_mirror_after_edit_via_new_ui():
    """After a room is edited through the new per-TRV UI, only CONF_TRVS
    is written (see config_flow.py's room_trvs_menu "done" handling) — the
    flat mirror is stale until migrate_room_to_trvs() re-syncs it from
    trvs[0]."""
    room = {
        CONF_ROOM_NAME: "Bathroom",
        CONF_CLIMATE_ENTITY: "climate.bathroom_old_zigbee",  # stale
        CONF_TRVS: [
            {
                CONF_CLIMATE_ENTITY: "climate.bathroom_new_netatmo",
                CONF_TRV_TYPE: "netatmo",
            }
        ],
    }
    migrated = migrate_room_to_trvs(room)

    assert migrated[CONF_CLIMATE_ENTITY] == "climate.bathroom_new_netatmo"
    assert migrated[CONF_TRV_TYPE] == "netatmo"


def test_migrate_resync_drops_flat_field_no_longer_on_primary_trv():
    """If the primary TRV's edit removed a field (e.g. cleared its
    calibration entity), the stale flat-level copy of that field must be
    dropped too, not left dangling with the old value."""
    room = {
        CONF_ROOM_NAME: "Bathroom",
        CONF_CLIMATE_ENTITY: "climate.bathroom",
        CONF_CALIBRATION_ENTITY: "number.stale_calibration",
        CONF_TRVS: [{CONF_CLIMATE_ENTITY: "climate.bathroom"}],  # calibration cleared
    }
    migrated = migrate_room_to_trvs(room)
    assert CONF_CALIBRATION_ENTITY not in migrated


def test_migrate_room_with_empty_trvs_list_is_left_untouched():
    """A room that already has CONF_TRVS but it's an empty list (edge
    case — shouldn't normally happen since the config/options flow
    requires at least one TRV to finish) is returned unchanged rather than
    crashing on trvs[0]."""
    room = {CONF_ROOM_NAME: "Empty", CONF_TRVS: []}
    migrated = migrate_room_to_trvs(room)
    assert migrated == room


# ── migrate_rooms_to_trvs — list wrapper ────────────────────────────────────


def test_migrate_rooms_to_trvs_applies_to_every_room():
    rooms = [
        {CONF_ROOM_NAME: "Kitchen", CONF_CLIMATE_ENTITY: "climate.kitchen"},
        {CONF_ROOM_NAME: "Bedroom", CONF_CLIMATE_ENTITY: "climate.bedroom"},
    ]
    migrated = migrate_rooms_to_trvs(rooms)

    assert len(migrated) == 2
    assert migrated[0][CONF_TRVS][0][CONF_CLIMATE_ENTITY] == "climate.kitchen"
    assert migrated[1][CONF_TRVS][0][CONF_CLIMATE_ENTITY] == "climate.bedroom"


def test_migrate_rooms_to_trvs_empty_list():
    assert migrate_rooms_to_trvs([]) == []


# ── async_migrate_entry (HA-facing wrapper in __init__.py) ─────────────────


def _make_entry(version: int, rooms: list[dict]) -> MagicMock:
    entry = MagicMock()
    entry.version = version
    entry.data = {CONF_ROOMS: rooms}
    return entry


@pytest.mark.asyncio
async def test_async_migrate_entry_v1_to_v2_updates_rooms_and_version():
    from custom_components.heat_manager import async_migrate_entry

    hass = MagicMock()
    entry = _make_entry(
        version=1,
        rooms=[{CONF_ROOM_NAME: "Kitchen", CONF_CLIMATE_ENTITY: "climate.kitchen"}],
    )

    result = await async_migrate_entry(hass, entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["version"] == 2
    migrated_rooms = kwargs["data"][CONF_ROOMS]
    assert migrated_rooms[0][CONF_TRVS][0][CONF_CLIMATE_ENTITY] == "climate.kitchen"


@pytest.mark.asyncio
async def test_async_migrate_entry_already_current_version_is_a_noop():
    from custom_components.heat_manager import async_migrate_entry

    hass = MagicMock()
    entry = _make_entry(
        version=2,
        rooms=[
            {
                CONF_ROOM_NAME: "Kitchen",
                CONF_CLIMATE_ENTITY: "climate.kitchen",
                CONF_TRVS: [{CONF_CLIMATE_ENTITY: "climate.kitchen"}],
            }
        ],
    )

    result = await async_migrate_entry(hass, entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_async_migrate_entry_preserves_other_entry_data_keys():
    """The migration must only touch CONF_ROOMS — every other top-level
    config entry key must pass through unchanged."""
    from custom_components.heat_manager import async_migrate_entry

    hass = MagicMock()
    entry = _make_entry(version=1, rooms=[])
    entry.data["away_temp_mild"] = 17.0
    entry.data["weather_entity"] = "weather.home"

    await async_migrate_entry(hass, entry)

    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["data"]["away_temp_mild"] == 17.0
    assert kwargs["data"]["weather_entity"] == "weather.home"
