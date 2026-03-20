"""
Heat Manager — Binary sensor platform

Entities
--------
binary_sensor.heat_manager_any_window_open   True when any configured window is open
binary_sensor.heat_manager_heating_wasted    True when window open AND heating running
binary_sensor.heat_manager_<room>_window     True when that specific room's window is open
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
    RoomState,
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
    entities: list[BinarySensorEntity] = [
        AnyWindowOpenSensor(coordinator, entry),
        HeatingWastedSensor(coordinator, entry),
    ]
    # One per-room window sensor for rooms that have window sensors configured
    for room in coordinator.rooms:
        if room.get(CONF_WINDOW_SENSORS):
            entities.append(RoomWindowSensor(coordinator, entry, room))

    async_add_entities(entities)


class AnyWindowOpenSensor(CoordinatorEntity, BinarySensorEntity):
    """True when any configured window/door sensor is currently open."""

    _attr_has_entity_name = True
    _attr_translation_key = "any_window_open"
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_icon = "mdi:window-open"

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_any_window_open"

    @property
    def is_on(self) -> bool:
        return self.coordinator.any_window_open()


class HeatingWastedSensor(CoordinatorEntity, BinarySensorEntity):
    """
    True when at least one window is open AND the corresponding room
    climate entity is actively heating (not in away/off state).
    This indicates energy waste.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "heating_wasted"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_heating_wasted"

    @property
    def is_on(self) -> bool:
        """
        True if any room is in WINDOW_OPEN state AND the climate entity
        is not already at the suppressed temperature (i.e. is still heating).
        """
        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not climate_id:
                continue
            room_state = self.coordinator.get_room_state(room_name)
            if room_state != RoomState.WINDOW_OPEN:
                continue
            # Check if climate is actually running (hvac_action == "heating")
            cs = self.coordinator.hass.states.get(climate_id)
            if cs:
                hvac_action = cs.attributes.get("hvac_action", "")
                if hvac_action == "heating":
                    return True
        return False


class RoomWindowSensor(CoordinatorEntity, BinarySensorEntity):
    """Per-room aggregated window open state."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict,
    ) -> None:
        super().__init__(coordinator)
        self._room_name = room["room_name"]
        self._sensors   = room.get(CONF_WINDOW_SENSORS, [])
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_window"
        self._attr_name = f"{self._room_name} window"

    @property
    def is_on(self) -> bool:
        return any(
            (self.coordinator.hass.states.get(sid) or object()).state == "on"
            for sid in self._sensors
        )
