"""
Heat Manager — Schedule Engine (v0.9.0, Fase D)

Optional extra layer on top of a room's normal target temperature (the
Netatmo cloud schedule's own setpoint, or CONF_COMFORT_TEMP on the local/
Zigbee path): a room may point CONF_SCHEDULE_ENTITY at a native HA
`schedule.*` helper or a `calendar.*` entity. While that entity reports an
active block/event, its `temperature` value overrides the room's normal
target for the duration — read fresh every tick, so it never needs baking
into a stored target and automatically releases once the block/event ends.

SeasonEngine and the existing Netatmo cloud schedule are both untouched —
this sits beside them, not in place of them. Group offset and the night/
wake setbacks still apply on top (see coordinator._async_pid_tick()).

Two entity domains, two data sources
-------------------------------------
`schedule.*` — Home Assistant's own Schedule helper natively supports an
                "Additional data" mapping per time block, which HA itself
                copies onto the entity's state attributes while that block
                is active. No parsing needed here: read attributes.get
                ("temperature") straight off the entity's own state.

`calendar.*` — Calendar entities have no such native mechanism. Mirroring
                climate_group_helper's approach, the event's `description`
                attribute is parsed as YAML `key: value` pairs to find a
                `temperature` key. A calendar entity's state is "on" only
                while an event is currently in progress, matching how the
                Schedule helper's "on" state marks an active block.

A room with no CONF_SCHEDULE_ENTITY configured, or whose entity is not
currently "on", simply has no entry in coordinator.schedule_override —
_async_pid_tick() falls through to its normal target unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import yaml

from ..const import (
    CONF_ROOM_NAME,
    CONF_SCHEDULE_ENTITY,
    SCHEDULE_TEMP_MAX,
    SCHEDULE_TEMP_MIN,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class ScheduleEngine:
    """Per-room schedule/calendar target-temperature override."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator

    async def async_tick(self) -> None:
        """Called every SCAN_INTERVAL_SECONDS from the coordinator's main tick."""
        for room in self.coordinator.rooms:
            room_name = room.get(CONF_ROOM_NAME, "")
            entity_id = room.get(CONF_SCHEDULE_ENTITY) or None
            if not room_name:
                continue
            if not entity_id:
                self.coordinator.schedule_override.pop(room_name, None)
                continue
            self._update_room(room_name, entity_id)

    def _update_room(self, room_name: str, entity_id: str) -> None:
        temperature = self._read_active_temperature(entity_id)
        if temperature is None:
            self.coordinator.schedule_override.pop(room_name, None)
            return

        clamped = max(SCHEDULE_TEMP_MIN, min(SCHEDULE_TEMP_MAX, temperature))
        if clamped != temperature:
            _LOGGER.warning(
                "Schedule [%s]: %.1f°C from %s is outside the sane %.0f–%.0f°C"
                " range — clamped to %.1f°C",
                room_name,
                temperature,
                entity_id,
                SCHEDULE_TEMP_MIN,
                SCHEDULE_TEMP_MAX,
                clamped,
            )

        if self.coordinator.schedule_override.get(room_name) != clamped:
            _LOGGER.debug(
                "Schedule [%s]: active block on %s → target %.1f°C",
                room_name,
                entity_id,
                clamped,
            )
        self.coordinator.schedule_override[room_name] = clamped

    def _read_active_temperature(self, entity_id: str) -> float | None:
        state = self.coordinator.hass.states.get(entity_id)
        if state is None or state.state != "on":
            return None

        if entity_id.startswith("calendar."):
            return self._parse_calendar_description(entity_id, state)

        # schedule.* (and anything else): HA already copies the active
        # block's "Additional data" onto the entity's own attributes.
        return self._coerce_float(state.attributes.get("temperature"))

    def _parse_calendar_description(self, entity_id: str, state) -> float | None:
        description = state.attributes.get("description")
        if not description or not isinstance(description, str):
            return None
        try:
            data = yaml.safe_load(description)
        except yaml.YAMLError as err:
            _LOGGER.warning(
                "Schedule [%s]: event description is not valid YAML — skipped (%s)",
                entity_id,
                err,
            )
            return None
        if not isinstance(data, dict):
            return None
        return self._coerce_float(data.get("temperature"))

    @staticmethod
    def _coerce_float(value) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_shutdown(self) -> None:
        """No listeners or timers to release — present for interface consistency
        with the other engines the coordinator shuts down."""
        return None
