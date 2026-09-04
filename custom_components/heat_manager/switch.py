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
    CONF_TRV_TYPE,
    PRESET_SCHEDULE,
    TRV_TYPE_ZIGBEE,
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
    entities: list[SwitchEntity] = [
        RoomOverrideSwitch(coordinator, entry, room) for room in coordinator.rooms
    ]
    for room in coordinator.rooms:
        room_name = room.get("room_name", "")
        if not room_name:
            continue
        if len(coordinator.get_all_room_trvs(room_name)) > 1:
            entities.append(RoomGroupToggleSwitch(coordinator, entry, room_name))
    async_add_entities(entities)


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
        self._room_name = room["room_name"]
        self._climate_id = room.get(CONF_CLIMATE_ENTITY, "")
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_override"
        self._attr_name = f"{self._room_name} override"
        self._attr_device_info = coordinator.room_device_info(self._room_name)

    @property
    def is_on(self) -> bool:
        return self.coordinator.get_room_state(self._room_name) == RoomState.OVERRIDE

    async def async_turn_on(self, **kwargs) -> None:  # type: ignore[override]
        """B18: every physical TRV configured for the room is switched to
        OVERRIDE. Each branch keeps its own pre-existing (and slightly
        inconsistent) entity-selection policy, now scoped per TRV instead
        of the room's primary: zigbee prefers the write entity (HomeKit if
        reachable), netatmo always writes to its own raw climate_entity.
        """
        trvs = self.coordinator.get_room_trvs(self._room_name)
        if not trvs:
            return
        any_ok = False
        for trv in trvs:
            climate_id = trv.get(CONF_CLIMATE_ENTITY, "")
            if not climate_id:
                continue
            trv_type = trv.get(CONF_TRV_TYPE, "netatmo")
            try:
                if trv_type == TRV_TYPE_ZIGBEE:
                    write_id = self.coordinator.get_trv_write_entity(trv) or climate_id
                    await self.coordinator.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": write_id, "hvac_mode": "heat"},
                        blocking=True,
                    )
                else:
                    await self.coordinator.hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": climate_id, "preset_mode": PRESET_SCHEDULE},
                        blocking=True,
                    )
                any_ok = True
                _LOGGER.info(
                    "Override ON: %s → heating (%s)", self._room_name, trv_type
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Override turn_on failed for %s: %s", self._room_name, err
                )

        if any_ok:
            self.coordinator.set_room_state(self._room_name, RoomState.OVERRIDE)
            self.coordinator.log_event(
                f"Override ON — {self._room_name}", "Override", "override"
            )

    async def async_turn_off(self, **kwargs) -> None:  # type: ignore[override]
        self.coordinator.set_room_state(self._room_name, RoomState.NORMAL)
        self.coordinator.log_event(
            f"Override OFF — {self._room_name} returning to normal",
            "Override",
            "normal",
        )
        _LOGGER.info("Override OFF: %s — returning to normal", self._room_name)


class RoomGroupToggleSwitch(CoordinatorEntity, SwitchEntity):
    """B18 Fase 3 — per-room "keep TRVs grouped" toggle.

    Only created for rooms with 2+ physical TRVs (a single-TRV room has
    nothing to group). Default ON: every configured TRV receives the room's
    PID-computed setpoint, as before B18 Fase 3.

    OFF → Heat Manager stops sending commands to every TRV in the room
    except the primary one, across every engine (PID tick, boost, away,
    window, preheat, valve protection, sync, controller off-fallback, the
    override switch, WS manual commands) — they are released for
    independent/manual control until this is switched back on. The
    primary TRV, and the room's offset number, keep applying normally
    regardless of this toggle. See coordinator.get_room_trvs().
    """

    _attr_has_entity_name = True
    _attr_translation_key = "room_group_toggle"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._room_name = room_name
        safe_name = room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_group_toggle"
        self._attr_name = f"{room_name} group"
        self._attr_device_info = coordinator.room_device_info(room_name)

    @property
    def is_on(self) -> bool:
        return self.coordinator.room_group_enabled.get(self._room_name, True)

    async def async_turn_on(self, **kwargs) -> None:  # type: ignore[override]
        self.coordinator.set_room_group_enabled(self._room_name, True)
        self.coordinator.log_event(
            f"Gruppe TIL — {self._room_name} (alle TRV'er styres igen)",
            "Gruppe",
            "normal",
        )
        _LOGGER.info("Group toggle ON: %s — all TRVs grouped again", self._room_name)

    async def async_turn_off(self, **kwargs) -> None:  # type: ignore[override]
        self.coordinator.set_room_group_enabled(self._room_name, False)
        self.coordinator.log_event(
            f"Gruppe FRA — {self._room_name} (ekstra TRV'er frigivet)",
            "Gruppe",
            "warning",
        )
        _LOGGER.info("Group toggle OFF: %s — secondary TRVs released", self._room_name)
