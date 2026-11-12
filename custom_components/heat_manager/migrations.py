"""Heat Manager — config entry data migrations.

Pure functions, no `homeassistant.*` imports — testable without a running
HA instance, same as the engine/ modules. Called from
`__init__.async_migrate_entry()`, which HA runs automatically once per
config entry when `HeatManagerConfigFlow.VERSION` is bumped.
"""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_PI_DEMAND_ENTITY,
    CONF_SYNC_MODE,
    CONF_TRV_TYPE,
    CONF_TRVS,
    STALE_CONFIG_KEYS,
    STALE_ROOM_KEYS,
)

# Fields that moved from the room level into each TRV dict when CONF_TRVS
# was introduced (B18 / TRV grouping groundwork). Order doesn't matter.
_TRV_FIELDS = (
    CONF_CLIMATE_ENTITY,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_TRV_TYPE,
    CONF_PI_DEMAND_ENTITY,
    CONF_CALIBRATION_ENTITY,
    CONF_SYNC_MODE,
)


def migrate_room_to_trvs(room: dict[str, Any]) -> dict[str, Any]:
    """Return `room` with a CONF_TRVS list, migrating the old flat
    single-TRV fields into it if needed.

    The flat fields are always left in place too, mirrored from
    ``trvs[0]`` (the room's primary TRV) — every module that still reads
    ``room.get(CONF_CLIMATE_ENTITY)`` directly keeps working unchanged for
    single-TRV rooms. Multi-TRV control (grouping, mirroring the same
    target to every TRV) is a separate, later change to coordinator.py and
    the engines; this migration only makes the *data* multi-TRV-shaped.

    Idempotent: calling it again on an already-migrated room just
    re-syncs the flat mirror from ``trvs[0]`` (relevant after the room was
    edited through the new per-TRV UI, where only CONF_TRVS is written).
    """
    room = dict(room)

    if CONF_TRVS in room:
        trvs = room[CONF_TRVS]
        if not trvs:
            return room
        primary = trvs[0]
        for field in _TRV_FIELDS:
            if field in primary:
                room[field] = primary[field]
            else:
                room.pop(field, None)
        return room

    climate = room.get(CONF_CLIMATE_ENTITY)
    if not climate:
        # No climate entity at all — nothing sane to migrate. Leave the
        # room untouched rather than inventing an empty TRV; the existing
        # "entity_not_found" / ConfigEntryNotReady handling already covers
        # a room with no usable climate entity.
        return room

    trv: dict[str, Any] = {CONF_CLIMATE_ENTITY: climate}
    for field in _TRV_FIELDS[1:]:
        value = room.get(field)
        if value not in (None, ""):
            trv[field] = value

    room[CONF_TRVS] = [trv]
    return room


def migrate_rooms_to_trvs(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply migrate_room_to_trvs() to every room in the list."""
    return [migrate_room_to_trvs(room) for room in rooms]


def strip_stale_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """v0.65.2: return a copy of a stored config dict (entry.data or
    entry.options) without keys left behind by removed features, or None
    when there is nothing to remove — so the caller only writes the entry
    when it actually changes.

    Top-level: STALE_CONFIG_KEYS. Per room in CONF_ROOMS: STALE_ROOM_KEYS.
    """
    changed = False
    out = {k: v for k, v in config.items() if k not in STALE_CONFIG_KEYS}
    if len(out) != len(config):
        changed = True
    rooms = out.get("rooms")
    if isinstance(rooms, list):
        new_rooms = []
        for room in rooms:
            if isinstance(room, dict) and any(k in room for k in STALE_ROOM_KEYS):
                room = {k: v for k, v in room.items() if k not in STALE_ROOM_KEYS}
                changed = True
            new_rooms.append(room)
        out["rooms"] = new_rooms
    return out if changed else None
