"""
Heat Manager — Number platform (v0.9.0)

Entities
--------
number.heat_manager_group_offset   Global, non-destructive temperature shift
                                    applied on top of every room's PID
                                    target every tick (coordinator.group_offset,
                                    read in coordinator._async_pid_tick()).
                                    Persists across HA restarts. Auto-resets
                                    to 0 when a boost starts.

Mirrors climate_group_helper's "Group Offset" number entity: a +1.5°C
offset shifts a 20°C morning setpoint to 21.5°C and automatically follows a
schedule/season transition to a different base setpoint later, since it is
applied at read time rather than baked into a stored target.
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
    async_add_entities([GroupOffsetNumber(coordinator, entry)])


class GroupOffsetNumber(RestoreNumber):
    """Global comfort-level shift, layered non-destructively on top of every
    room's current target — see coordinator._async_pid_tick()."""

    _attr_has_entity_name = True
    _attr_translation_key = "group_offset"
    _attr_native_min_value = GROUP_OFFSET_MIN
    _attr_native_max_value = GROUP_OFFSET_MAX
    _attr_native_step = GROUP_OFFSET_STEP
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_group_offset"
        self._attr_device_info = coordinator.global_device_info()
        self._attr_native_value = DEFAULT_GROUP_OFFSET

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_data = await self.async_get_last_number_data()
        if last_data is not None and last_data.native_value is not None:
            self._attr_native_value = last_data.native_value
        self.coordinator.group_offset = float(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.group_offset = float(value)
        self.async_write_ha_state()
        self.coordinator.log_event(
            f"Group offset sat til {value:+.1f}°C", "manuel", "offset"
        )
        _LOGGER.info("Group offset set to %.1f°C", value)
