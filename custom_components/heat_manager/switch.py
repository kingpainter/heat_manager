"""
Heat Manager — Switch platform

Gold IQS: entity-disabled-by-default — override switches are CONFIG category
and disabled by default (power users only).
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CLIMATE_ENTITY,
    DOMAIN,
    PRESET_SCHEDULE,
    RoomState,
    TRV_TYPE_ZIGBEE,
    CONF_TRV_TYPE,
    HVAC_OFF,
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
        RoomOverrideSwitch(coordinator, entry, room)
        for room in coordinator.rooms
    ])


class RoomOverrideSwitch(CoordinatorEntity, SwitchEntity):
    """
    Manual override for a single room.

    ON  → forces room to schedule, marks OVERRIDE state (bypasses presence + window logic).
    OFF → clears override, coordinator resumes normal logic on next tick.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "room_override"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False  # power-user feature — off by default

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict,
    ) -> None:
        super().__init__(coordinator)
        self._room_name  = room["room_name"]
        self._climate_id = room.get(CONF_CLIMATE_ENTITY, "")
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_override"
        self._attr_name = f"{self._room_name} override"

    @property
    def is_on(self) -> bool:
        return self.coordinator.get_room_state(self._room_name) == RoomState.OVERRIDE

    async def async_turn_on(self, **kwargs) -> None:  # type: ignore[override]
        if not self._climate_id:
            return
        # Use write entity (HomeKit preferred) same as all other engines
        room_cfg  = next(
            (r for r in self.coordinator.rooms if r.get("room_name") == self._room_name), {}
        )
        trv_type  = room_cfg.get(CONF_TRV_TYPE, "netatmo")
        write_id  = self.coordinator.get_write_entity(self._room_name) or self._climate_id
        try:
            if trv_type == TRV_TYPE_ZIGBEE:
                await self.coordinator.hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": write_id, "hvac_mode": "heat"},
                    blocking=True,
                )
            else:
                await self.coordinator.hass.services.async_call(
                    "climate", "set_preset_mode",
                    {"entity_id": self._climate_id, "preset_mode": PRESET_SCHEDULE},
                    blocking=True,
                )
            self.coordinator.set_room_state(self._room_name, RoomState.OVERRIDE)
            self.coordinator.log_event(
                f"Override ON — {self._room_name}", "Override", "override"
            )
            _LOGGER.info("Override ON: %s → heating (%s)", self._room_name, trv_type)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Override turn_on failed for %s: %s", self._room_name, err)

    async def async_turn_off(self, **kwargs) -> None:  # type: ignore[override]
        self.coordinator.set_room_state(self._room_name, RoomState.NORMAL)
        self.coordinator.log_event(
            f"Override OFF — {self._room_name} returning to normal", "Override", "normal"
        )
        _LOGGER.info("Override OFF: %s — returning to normal", self._room_name)
