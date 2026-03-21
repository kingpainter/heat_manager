"""
Heat Manager — Binary sensor platform

Gold IQS: entity-disabled-by-default applied to diagnostic sensors.
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
    for room in coordinator.rooms:
        if room.get(CONF_WINDOW_SENSORS):
            entities.append(RoomWindowSensor(coordinator, entry, room))

    async_add_entities(entities)


class AnyWindowOpenSensor(CoordinatorEntity, BinarySensorEntity):
    """True when any configured window/door sensor is currently open."""

    _attr_has_entity_name = True
    _attr_translation_key = "any_window_open"
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_entity_registry_enabled_default = True  # useful for automations

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_any_window_open"

    @property
    def is_on(self) -> bool:
        return self.coordinator.any_window_open()


class HeatingWastedSensor(CoordinatorEntity, BinarySensorEntity):
    """
    True when a window is open AND the climate entity is actively heating.
    Indicates energy waste in real time.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "heating_wasted"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_entity_registry_enabled_default = False  # diagnostic — off by default

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_heating_wasted"

    @property
    def is_on(self) -> bool:
        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not climate_id:
                continue
            if self.coordinator.get_room_state(room_name) != RoomState.WINDOW_OPEN:
                continue
            cs = self.coordinator.hass.states.get(climate_id)
            if cs and cs.attributes.get("hvac_action") == "heating":
                return True
        return False


class RoomWindowSensor(CoordinatorEntity, BinarySensorEntity):
    """Per-room aggregated window open state."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_entity_registry_enabled_default = False  # per-room detail — off by default

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
            (s := self.coordinator.hass.states.get(sid)) is not None and s.state == "on"
            for sid in self._sensors
        )
