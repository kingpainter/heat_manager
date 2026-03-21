"""
Heat Manager — Sensor platform

Entities
--------
sensor.heat_manager_pause_remaining          Minutes left in pause
sensor.heat_manager_energy_wasted_today      kWh wasted today (WasteCalculator)
sensor.heat_manager_energy_saved_today       kWh saved today (WasteCalculator)
sensor.heat_manager_efficiency_score         Daily score 0–100 (WasteCalculator)
sensor.heat_manager_<room>_state             Per-room state string
sensor.heat_manager_<room>_window_duration   Minutes window open today (diagnostic)

Gold IQS:
- entity-disabled-by-default: diagnostic sensors off by default
- log-when-unavailable: single WARNING when climate unavailable, INFO on recovery
- entity-unavailable: unavailable climate → unavailable per-room state sensor
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import utcnow

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

    entities: list[SensorEntity] = [
        PauseRemainingSensor(coordinator, entry),
        EnergyWastedSensor(coordinator, entry),
        EnergySavedSensor(coordinator, entry),
        EfficiencyScoreSensor(coordinator, entry),
    ]

    for room in coordinator.rooms:
        entities.append(RoomStateSensor(coordinator, entry, room))
        if room.get(CONF_WINDOW_SENSORS):
            entities.append(RoomWindowDurationSensor(coordinator, entry, room))

    async_add_entities(entities)


# ── Global sensors ────────────────────────────────────────────────────────────

class PauseRemainingSensor(CoordinatorEntity, SensorEntity):
    """Minutes remaining in the current pause. 0 when not paused."""

    _attr_has_entity_name = True
    _attr_translation_key = "pause_remaining"
    _attr_native_unit_of_measurement = "min"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False  # off by default — only needed for debugging

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_pause_remaining"

    @property
    def native_value(self) -> int:
        return self.coordinator.pause_remaining_minutes


class EnergyWastedSensor(CoordinatorEntity, SensorEntity):
    """kWh wasted today — windows open while heating runs."""

    _attr_has_entity_name = True
    _attr_translation_key = "energy_wasted_today"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True  # shown by default — useful for dashboards

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy_wasted_today"

    @property
    def native_value(self) -> float:
        return self.coordinator.energy_wasted_today


class EnergySavedSensor(CoordinatorEntity, SensorEntity):
    """kWh saved today — away mode during expected heating hours."""

    _attr_has_entity_name = True
    _attr_translation_key = "energy_saved_today"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy_saved_today"

    @property
    def native_value(self) -> float:
        return self.coordinator.energy_saved_today


class EfficiencyScoreSensor(CoordinatorEntity, SensorEntity):
    """Daily efficiency score 0–100."""

    _attr_has_entity_name = True
    _attr_translation_key = "efficiency_score"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_efficiency_score"

    @property
    def native_value(self) -> int:
        return self.coordinator.efficiency_score


# ── Per-room sensors ──────────────────────────────────────────────────────────

class RoomStateSensor(CoordinatorEntity, SensorEntity):
    """
    Current state of a single room.

    Gold IQS — entity-unavailable + log-when-unavailable:
    When the room's climate entity is unavailable, this sensor marks itself
    unavailable too. Logs WARNING once on unavailable, INFO once on recovery.
    """

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

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
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_state"
        self._attr_name = f"{self._room_name} state"
        self._was_unavailable: bool = False

    @property
    def available(self) -> bool:
        """Unavailable when the backing climate entity is unavailable."""
        if not self._climate_id:
            return True
        s = self.coordinator.hass.states.get(self._climate_id)
        return s is not None and s.state not in ("unavailable", "unknown")

    @property
    def native_value(self) -> str:
        return self.coordinator.get_room_state(self._room_name).value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"room_name": self._room_name}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Log once on unavailable, once on recovery — never spam."""
        is_unavailable = not self.available
        if is_unavailable and not self._was_unavailable:
            _LOGGER.warning(
                "Heat Manager: climate entity %s is unavailable — "
                "%s state sensor marked unavailable",
                self._climate_id, self._room_name,
            )
        elif not is_unavailable and self._was_unavailable:
            _LOGGER.info(
                "Heat Manager: climate entity %s recovered — "
                "%s state sensor available again",
                self._climate_id, self._room_name,
            )
        self._was_unavailable = is_unavailable
        super()._handle_coordinator_update()


class RoomWindowDurationSensor(CoordinatorEntity, SensorEntity):
    """Total minutes a room's window has been open today."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "min"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False  # diagnostic — off by default

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict,
    ) -> None:
        super().__init__(coordinator)
        self._room_name = room["room_name"]
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_window_duration"
        self._attr_name = f"{self._room_name} window duration"
        self._total_minutes: int = 0
        self._was_open: bool = False
        self._opened_at: datetime | None = None
        self._last_reset_day: int = -1

    @property
    def native_value(self) -> int:
        return self._total_minutes

    @callback
    def _handle_coordinator_update(self) -> None:
        is_open = self.coordinator.get_room_state(self._room_name) == RoomState.WINDOW_OPEN
        now = utcnow()

        if now.day != self._last_reset_day:
            self._total_minutes  = 0
            self._was_open       = False
            self._opened_at      = None
            self._last_reset_day = now.day

        if is_open and not self._was_open:
            self._opened_at = now
        elif not is_open and self._was_open and self._opened_at is not None:
            elapsed = int((now - self._opened_at).total_seconds() / 60)
            self._total_minutes += elapsed
            self._opened_at = None

        self._was_open = is_open
        super()._handle_coordinator_update()
