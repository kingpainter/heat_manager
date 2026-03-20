"""
Heat Manager — Select platform

Entities
--------
select.heat_manager_controller_state   On / Pause / Off
select.heat_manager_season_mode        Auto / Winter / Summer
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONTROLLER_STATE_OPTIONS,
    DOMAIN,
    SEASON_MODE_OPTIONS,
    ControllerState,
    SeasonMode,
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
    async_add_entities([
        ControllerStateSelect(coordinator, entry),
        SeasonModeSelect(coordinator, entry),
    ])


class ControllerStateSelect(CoordinatorEntity, SelectEntity):
    """
    ON / PAUSE / OFF selector.
    This is the primary user-facing control for Heat Manager.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "controller_state"
    _attr_options = CONTROLLER_STATE_OPTIONS
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_controller_state"
        self._entry = entry

    @property
    def current_option(self) -> str:
        return self.coordinator.controller.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "auto_off_reason":  self.coordinator.auto_off_reason.value,
            "pause_remaining":  self.coordinator.pause_remaining_minutes,
        }

    async def async_select_option(self, option: str) -> None:
        try:
            new_state = ControllerState(option)
        except ValueError:
            _LOGGER.warning("Invalid controller state selected: %s", option)
            return
        await self.coordinator.controller.set_state(new_state)


class SeasonModeSelect(CoordinatorEntity, SelectEntity):
    """Auto / Winter / Summer selector."""

    _attr_has_entity_name = True
    _attr_translation_key = "season_mode"
    _attr_options = SEASON_MODE_OPTIONS
    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_season_mode"

    @property
    def current_option(self) -> str:
        return self.coordinator.season_mode.value

    async def async_select_option(self, option: str) -> None:
        try:
            new_mode = SeasonMode(option)
        except ValueError:
            _LOGGER.warning("Invalid season mode selected: %s", option)
            return
        self.coordinator.season_mode = new_mode
        self.coordinator.async_update_listeners()
        _LOGGER.info("Season mode set to: %s", new_mode.value)
