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
    CONF_HOMEKIT_CLIMATE_ENTITY,
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
        if room.get(CONF_HOMEKIT_CLIMATE_ENTITY):
            entities.append(RoomPidPowerSensor(coordinator, entry, room))

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
    """kWh wasted today — windows open while heating runs.

    I-1 FIX: state_class = MEASUREMENT not TOTAL_INCREASING.
    These sensors reset at midnight so HA LTS would log 'dips' with
    TOTAL_INCREASING and possibly raise warnings. MEASUREMENT is correct
    for values that represent today's running total and reset daily.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "energy_wasted_today"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy_wasted_today"

    @property
    def native_value(self) -> float:
        return self.coordinator.energy_wasted_today


class EnergySavedSensor(CoordinatorEntity, SensorEntity):
    """kWh saved today — away mode during expected heating hours.

    I-1 FIX: state_class = MEASUREMENT (resets at midnight, same as wasted).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "energy_saved_today"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
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
        self._last_reset_date: Any = None  # S-6 FIX: date() not day integer

    @property
    def native_value(self) -> int:
        return self._total_minutes

    @callback
    def _handle_coordinator_update(self) -> None:
        is_open = self.coordinator.get_room_state(self._room_name) == RoomState.WINDOW_OPEN
        now = utcnow()

        # S-6 FIX: use date() not day-of-month integer to avoid false resets
        today = now.date()
        if today != self._last_reset_date:
            self._total_minutes   = 0
            self._was_open        = False
            self._opened_at       = None
            self._last_reset_date = today

        if is_open and not self._was_open:
            self._opened_at = now
        elif not is_open and self._was_open and self._opened_at is not None:
            elapsed = int((now - self._opened_at).total_seconds() / 60)
            self._total_minutes += elapsed
            self._opened_at = None

        self._was_open = is_open
        super()._handle_coordinator_update()


class RoomPidPowerSensor(CoordinatorEntity, SensorEntity):
    """Current PID output power for a room (0–100 %).

    Exposes the last computed PID power fraction as a sensor so users
    can monitor and tune PID gains without enabling debug logging.
    Only created for rooms that have a HomeKit entity configured
    (i.e. rooms where PID actually writes setpoints).
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0
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
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_pid_power"
        self._attr_name = f"{self._room_name} PID power"

    @property
    def native_value(self) -> float | None:
        pid = self.coordinator.get_pid(self._room_name)
        if pid is None:
            return None
        # PID stores last output as _last_output (0.0–1.0)
        raw = getattr(pid, "_last_output", None)
        if raw is None:
            return None
        return round(raw * 100.0, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pid = self.coordinator.get_pid(self._room_name)
        if pid is None:
            return {"room_name": self._room_name}
        return {
            "room_name":    self._room_name,
            "pid_kp":       getattr(pid, "kp", None),
            "pid_ki":       getattr(pid, "ki", None),
            "pid_kd":       getattr(pid, "kd", None),
            "integral":     round(getattr(pid, "_integral", 0.0), 4),
        }
