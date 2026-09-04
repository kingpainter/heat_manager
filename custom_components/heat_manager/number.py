"""
Heat Manager — Number platform

Entities
--------
number.<room>_offset   Per-room, non-destructive temperature shift applied
                        on top of that room's PID target every tick
                        (coordinator.room_offsets[room_name], read in
                        coordinator._async_pid_tick()). Persists across HA
                        restarts. Auto-resets to 0 when a boost starts.
                        Only created for rooms with 2+ physical TRVs (B18
                        Fase 3) — a single-TRV room has no group to offset
                        independently of its own target.

Mirrors climate_group_helper's "Group Offset" number entity: a +1.5°C
offset shifts a 20°C morning setpoint to 21.5°C and automatically follows a
schedule/season transition to a different base setpoint later, since it is
applied at read time rather than baked into a stored target.

B18 Fase 3 replaces the single global number.heat_manager_group_offset
(v0.9.0) with one of these per qualifying room, alongside the room's new
RoomGroupToggleSwitch (switch.py) — see coordinator.get_room_trvs().
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_GROUP_OFFSET,
    GROUP_OFFSET_MAX,
    GROUP_OFFSET_MIN,
    GROUP_OFFSET_STEP,
)
from .coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeatManagerCoordinator = entry.runtime_data
    entities: list[RoomOffsetNumber] = []
    for room in coordinator.rooms:
        room_name = room.get("room_name", "")
        if not room_name:
            continue
        if len(coordinator.get_all_room_trvs(room_name)) > 1:
            entities.append(RoomOffsetNumber(coordinator, entry, room_name))
    async_add_entities(entities)


class RoomOffsetNumber(RestoreNumber):
    """Per-room comfort-level shift, layered non-destructively on top of
    that room's current target — see coordinator._async_pid_tick()."""

    _attr_has_entity_name = True
    _attr_translation_key = "room_offset"
    _attr_native_min_value = GROUP_OFFSET_MIN
    _attr_native_max_value = GROUP_OFFSET_MAX
    _attr_native_step = GROUP_OFFSET_STEP
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room_name: str,
    ) -> None:
        self.coordinator = coordinator
        self._room_name = room_name
        safe_name = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_offset"
        # has_entity_name=True + device.name == room_name means HA itself
        # prefixes the device name onto whatever _attr_name is set to
        # (name → f"{device_name} {name}", entity.py's
        # _friendly_name_internal()/suggested_object_id) — a short local
        # name here, NOT "{room_name} offset", is what produces the correct
        # "Living room Offset" friendly_name and living_room_offset entity
        # id. Setting the room name here too would double it up:
        # "Living room Living room Offset". See also RoomGroupToggleSwitch
        # in switch.py, which had exactly this bug before B18 Fase 3's
        # verification pass caught it.
        self._attr_name = "Offset"
        self._attr_device_info = coordinator.room_device_info(room_name)
        self._attr_native_value = DEFAULT_GROUP_OFFSET

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_data = await self.async_get_last_number_data()
        if last_data is not None and last_data.native_value is not None:
            self._attr_native_value = last_data.native_value
        self.coordinator.room_offsets[self._room_name] = float(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.room_offsets[self._room_name] = float(value)
        self.async_write_ha_state()
        self.coordinator.log_event(
            f"Offset ({self._room_name}) sat til {value:+.1f}°C", "manuel", "offset"
        )
        _LOGGER.info("Room offset [%s] set to %.1f°C", self._room_name, value)
