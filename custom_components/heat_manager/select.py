"""
Heat Manager — Select platform

Gold IQS:
- entity-disabled-by-default: season_mode is CONFIG and disabled by default
  (most users never need to override it manually).
- controller_state is the primary control — always enabled.
- netatmo_preset_mode is a per-room passthrough control — always enabled,
  one entity per room with a Netatmo TRV (Fase 2, 2026-09-11).
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
    CONF_CLIMATE_ENTITY,
    CONF_ROOM_NAME,
    CONF_TRV_TYPE,
    CONTROLLER_STATE_OPTIONS,
    NETATMO_PRESET_MODE_FALLBACK_OPTIONS,
    SEASON_MODE_OPTIONS,
    TRV_TYPE_NETATMO,
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
    entities: list[SelectEntity] = [
        ControllerStateSelect(coordinator, entry),
        SeasonModeSelect(coordinator, entry),
    ]

    # Fase 2 (2026-09-11): one NetatmoPresetModeSelect per room that has at
    # least one Netatmo TRV — read/write of Netatmo's own away/frost_guard/
    # boost/schedule preset directly from any HA dashboard, not just the
    # custom panel. Only the room's primary (first) Netatmo TRV gets an
    # entity — the unique_id is per-room, not per-TRV, so a second one would
    # collide.
    for room in coordinator.rooms:
        room_name = room.get(CONF_ROOM_NAME, "")
        if not room_name:
            continue
        for trv in coordinator.get_all_room_trvs(room_name):
            if trv.get(CONF_TRV_TYPE) != TRV_TYPE_NETATMO:
                continue
            climate_entity_id = trv.get(CONF_CLIMATE_ENTITY)
            if not climate_entity_id:
                continue
            entities.append(
                NetatmoPresetModeSelect(coordinator, entry, room_name, climate_entity_id)
            )
            break  # one preset-mode select per room, on its primary Netatmo TRV

    async_add_entities(entities)


class ControllerStateSelect(CoordinatorEntity, SelectEntity):
    """ON / PAUSE / OFF — primary user control. Always enabled."""

    _attr_has_entity_name = True
    _attr_translation_key = "controller_state"
    _attr_options = CONTROLLER_STATE_OPTIONS
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_controller_state"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def current_option(self) -> str:
        return self.coordinator.controller.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "auto_off_reason": self.coordinator.auto_off_reason.value,
            "pause_remaining": self.coordinator.pause_remaining_minutes,
            "effective_season": self.coordinator.effective_season.value,
            "blocking_sources": self.coordinator.global_blocking_sources(),
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
    # Options: auto / winter / spring / summer / autumn

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_season_mode"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def current_option(self) -> str:
        return self.coordinator.season_mode.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "effective_season": self.coordinator.effective_season.value,
            "calendar_season": self.coordinator.season_engine.calendar_season.value,
            "days_above_threshold": self.coordinator.season_engine.days_above_threshold,
        }

    async def async_select_option(self, option: str) -> None:
        try:
            new_mode = SeasonMode(option)
        except ValueError:
            _LOGGER.warning("Invalid season mode selected: %s", option)
            return
        self.coordinator.season_mode = new_mode
        # Persist to options so the selection survives HA restart
        new_options = {**self.coordinator.entry.options, "season_mode": new_mode.value}
        self.coordinator.hass.config_entries.async_update_entry(
            self.coordinator.entry, options=new_options
        )
        self.coordinator.log_event(
            f"Season mode set to {new_mode.value}", "Manual", "normal"
        )
        self.coordinator.async_update_listeners()
        _LOGGER.info("Season mode set to: %s (persisted)", new_mode.value)


class NetatmoPresetModeSelect(CoordinatorEntity, SelectEntity):
    """Read/write a Netatmo room's own cloud preset mode
    (away/frost_guard/boost/schedule) — Fase 2 (2026-09-11).

    This entity owns no state of its own: it's a live passthrough to the
    room's Netatmo climate entity's 'preset_mode' attribute, so any
    dashboard (not just the custom panel) gets a way to read and change a
    Netatmo room's cloud tilstand. Options are read from the live entity's
    own 'preset_modes' attribute when available, and fall back to the
    known Netatmo preset set only when that attribute is missing (e.g. the
    entity is unavailable).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "netatmo_preset_mode"
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room_name: str,
        climate_entity_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._room_name = room_name
        self._climate_entity_id = climate_entity_id
        slug = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{slug}_netatmo_preset_mode"
        self._attr_device_info = coordinator.room_device_info(room_name)

    @property
    def available(self) -> bool:
        state = self.coordinator.hass.states.get(self._climate_entity_id)
        return state is not None and state.state not in ("unavailable", "unknown")

    @property
    def options(self) -> list[str]:
        state = self.coordinator.hass.states.get(self._climate_entity_id)
        if state is not None:
            live_modes = state.attributes.get("preset_modes")
            if live_modes:
                return list(live_modes)
        return NETATMO_PRESET_MODE_FALLBACK_OPTIONS

    @property
    def current_option(self) -> str | None:
        state = self.coordinator.hass.states.get(self._climate_entity_id)
        if state is None:
            return None
        return state.attributes.get("preset_mode")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_call_climate_service(
            "set_preset_mode",
            self._climate_entity_id,
            {"preset_mode": option},
            needs_delay=True,
        )
        self.coordinator.log_event(
            f"Netatmo preset mode for {self._room_name} set to {option}",
            "Manual",
            "normal",
        )
        self.coordinator.async_update_listeners()
