"""
Heat Manager — Sensor platform

Entities
--------
sensor.heat_manager_pause_remaining          Minutes left in pause (0 when not paused)
sensor.heat_manager_energy_wasted_today      kWh wasted (window open + heating running)
sensor.heat_manager_efficiency_score         Daily score 0-100
sensor.heat_manager_<room>_state             Per-room state string
sensor.heat_manager_<room>_window_duration   Minutes window open today (diagnostic)
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
    _attr_icon = "mdi:timer-pause"

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_pause_remaining"

    @property
    def native_value(self) -> int:
        return self.coordinator.pause_remaining_minutes


class EnergyWastedSensor(CoordinatorEntity, SensorEntity):
    """
    Estimated kWh wasted today due to windows being open while heating runs.

    Simple accumulator: 0.3 kW × open-window rooms × tick duration.
    Resets at midnight. Placeholder until waste_calculator engine is written.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "energy_wasted_today"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy_wasted_today"
        self._wasted_kwh: float = 0.0
        self._last_reset_day: int = -1

    @property
    def native_value(self) -> float:
        return round(self._wasted_kwh, 3)

    @callback
    def _handle_coordinator_update(self) -> None:
        now = utcnow()
        # Reset at start of new day
        if now.day != self._last_reset_day:
            self._wasted_kwh = 0.0
            self._last_reset_day = now.day

        window_rooms = sum(
            1 for room in self.coordinator.rooms
            if self.coordinator.get_room_state(room.get("room_name", "")) == RoomState.WINDOW_OPEN
        )
        # 0.3 kW per open-window room, tick = 60 seconds
        tick_hours = 60 / 3600
        self._wasted_kwh += window_rooms * 0.3 * tick_hours

        super()._handle_coordinator_update()


class EfficiencyScoreSensor(CoordinatorEntity, SensorEntity):
    """
    Daily efficiency score 0-100.
    Drops 10 points per 0.1 kWh wasted, floor at 0.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "efficiency_score"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_efficiency_score"

    @property
    def native_value(self) -> int:
        wasted_state = self.hass.states.get(
            f"sensor.{DOMAIN}_energy_wasted_today"
        )
        if wasted_state and wasted_state.state not in ("unknown", "unavailable"):
            try:
                wasted = float(wasted_state.state)
                return max(0, min(100, 100 - int(wasted * 100)))
            except (TypeError, ValueError):
                pass
        return 100


# ── Per-room sensors ──────────────────────────────────────────────────────────

class RoomStateSensor(CoordinatorEntity, SensorEntity):
    """Current state of a single room."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:radiator"

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict,
    ) -> None:
        super().__init__(coordinator)
        self._room_name = room["room_name"]
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_state"
        self._attr_name = f"{self._room_name} state"

    @property
    def native_value(self) -> str:
        return self.coordinator.get_room_state(self._room_name).value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"room_name": self._room_name}


class RoomWindowDurationSensor(CoordinatorEntity, SensorEntity):
    """Total minutes a room's window has been open today."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "min"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:window-open-variant"

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

        # Reset at start of new day
        if now.day != self._last_reset_day:
            self._total_minutes = 0
            self._was_open = False
            self._opened_at = None
            self._last_reset_day = now.day

        if is_open and not self._was_open:
            # Window just opened
            self._opened_at = now
        elif not is_open and self._was_open and self._opened_at is not None:
            # Window just closed — add elapsed minutes
            elapsed = int((now - self._opened_at).total_seconds() / 60)
            self._total_minutes += elapsed
            self._opened_at = None

        self._was_open = is_open
        super()._handle_coordinator_update()
