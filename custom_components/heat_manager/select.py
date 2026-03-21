"""
Heat Manager — Select platform

Gold IQS:
- entity-disabled-by-default: season_mode is CONFIG and disabled by default
  (most users never need to override it manually).
- controller_state is the primary control — always enabled.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    """ON / PAUSE / OFF — primary user control. Always enabled."""

    _attr_has_entity_name = True
    _attr_translation_key = "controller_state"
    _attr_options = CONTROLLER_STATE_OPTIONS
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_controller_state"

    @property
    def current_option(self) -> str:
        return self.coordinator.controller.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "auto_off_reason":  self.coordinator.auto_off_reason.value,
            "pause_remaining":  self.coordinator.pause_remaining_minutes,
            "effective_season": self.coordinator.effective_season.value,
        }

    async def async_select_option(self, option: str) -> None:
        try:
            new_state = ControllerState(option)
        except ValueError:
            _LOGGER.warning("Invalid controller state selected: %s", option)
            return
        await self.coordinator.controller.set_state(new_state)


class SeasonModeSelect(CoordinatorEntity, SelectEntity):
    """
    Auto / Winter / Summer.

    Disabled by default — the SeasonEngine handles AUTO automatically.
    Users only need this to force a manual override.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "season_mode"
    _attr_options = SEASON_MODE_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False  # auto-managed — off by default

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_season_mode"

    @property
    def current_option(self) -> str:
        return self.coordinator.season_mode.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "effective_season":      self.coordinator.effective_season.value,
            "days_above_threshold":  self.coordinator.season_engine.days_above_threshold,
        }

    async def async_select_option(self, option: str) -> None:
        try:
            new_mode = SeasonMode(option)
        except ValueError:
            _LOGGER.warning("Invalid season mode selected: %s", option)
            return
        self.coordinator.season_mode = new_mode
        self.coordinator.log_event(
            f"Season mode set to {new_mode.value}", "Manual", "normal"
        )
        self.coordinator.async_update_listeners()
        _LOGGER.info("Season mode set to: %s", new_mode.value)
