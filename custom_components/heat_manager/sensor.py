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

v0.15.0 — configured-sensor mirrors (diagnostic, under the room/Hub device
they belong to, so a failing raw sensor is visible on the Integrations page
without hunting for whichever integration actually owns it):
- Per room: room temperature / humidity / CO2 / battery, when configured.
- Hub: outdoor temperature / humidity, precipitation, wind speed, indoor
  wake sensor, weather source, alarm panel, when configured.
- Hub: "Remote last action" — NOT a mirror, an entity Heat Manager computes
  itself from the global remote's button presses (see coordinator.
  set_remote_last_action()); created only when a button entity is set.

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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import parse_datetime, utcnow

from .const import (
    CONF_ALARM_PANEL,
    CONF_BATTERY_SENSOR,
    CONF_BUTTON_MODE_TOGGLE_ENTITY,
    CONF_BUTTON_TEMP_DOWN_ENTITY,
    CONF_BUTTON_TEMP_UP_ENTITY,
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_CO2_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_INDOOR_WAKE_SENSOR,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PRECIPITATION_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED_SENSOR,
    CONF_WINDOW_SENSORS,
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
        # Hybrid PID engine (v0.8.0) regulates every configured room, not
        # just Netatmo/HomeKit ones (see coordinator._async_pid_tick()) —
        # so the PID power sensor is now created unconditionally instead of
        # only when CONF_HOMEKIT_CLIMATE_ENTITY is set. Local/Zigbee rooms
        # regulate against CONF_COMFORT_TEMP and previously had no way to
        # expose their PID output at all.
        entities.append(RoomPidPowerSensor(coordinator, entry, room))
        if room.get(CONF_CALIBRATION_ENTITY):
            entities.append(RoomCalibrationOffsetSensor(coordinator, entry, room))
        # v0.15.0 — mirror this room's own already-configured raw sensors
        # (temperature/humidity/CO2/battery) under the room's device, so a
        # failing/unavailable one is visible right on the Integrations page
        # instead of hiding among whatever other integration created it.
        entities.extend(_room_mirror_sensors(coordinator, entry, room))

    # v0.15.0 — same idea as above, for Heat Manager's shared/global
    # already-configured sensors, mirrored under the Hub device.
    entities.extend(_hub_mirror_sensors(coordinator, entry))

    if any(
        coordinator.config.get(key)
        for key in (
            CONF_BUTTON_TEMP_UP_ENTITY,
            CONF_BUTTON_TEMP_DOWN_ENTITY,
            CONF_BUTTON_MODE_TOGGLE_ENTITY,
        )
    ):
        entities.append(RemoteLastActionSensor(coordinator, entry))

    async_add_entities(entities)


# ── Configured-sensor mirrors (v0.15.0) ──────────────────────────────────────
#
# Heat Manager doesn't own these entities — they belong to whatever
# integration created them (a Zigbee2MQTT temperature sensor, a weather
# integration, the alarm panel integration, etc.). Mirroring the ones the
# user has actually configured makes them show up under Heat Manager's own
# room/Hub device on the Integrations page too, so a missing/failing sensor
# is visible at a glance without hunting for which device it's really
# registered under. Heat Manager's OWN computed entities (state, PID power,
# calibration offset, ...) are untouched — these mirrors only fill genuine
# gaps for raw configured sensors that otherwise have no presence here.


def _room_mirror_sensors(
    coordinator: HeatManagerCoordinator, entry: ConfigEntry, room: dict
) -> list[SensorEntity]:
    """Diagnostic mirrors of one room's configured raw sensors — only
    created for fields the user actually filled in."""
    room_name = room["room_name"]
    safe = room_name.lower().replace(" ", "_")
    device_info = coordinator.room_device_info(room_name)
    mirrors: list[SensorEntity] = []

    for conf_key, name, device_class, suffix in (
        (
            CONF_ROOM_TEMP_SENSOR,
            "Room temperature",
            SensorDeviceClass.TEMPERATURE,
            "room_temp_mirror",
        ),
        (CONF_HUMIDITY_SENSOR, "Humidity", SensorDeviceClass.HUMIDITY, "humidity_mirror"),
        (CONF_CO2_SENSOR, "CO2", SensorDeviceClass.CO2, "co2_mirror"),
        (CONF_BATTERY_SENSOR, "Battery", SensorDeviceClass.BATTERY, "battery_mirror"),
    ):
        source_id = room.get(conf_key)
        if not source_id:
            continue
        mirrors.append(
            _NumericMirrorSensor(
                coordinator,
                unique_id=f"{entry.entry_id}_{safe}_{suffix}",
                name=name,
                source_entity_id=source_id,
                device_info=device_info,
                device_class=device_class,
            )
        )
    return mirrors


def _hub_mirror_sensors(
    coordinator: HeatManagerCoordinator, entry: ConfigEntry
) -> list[SensorEntity]:
    """Diagnostic mirrors of Heat Manager's shared/global configured raw
    sensors — only created for fields the user actually filled in."""
    device_info = coordinator.global_device_info()
    config = coordinator.config
    mirrors: list[SensorEntity] = []

    numeric_fields = (
        (
            CONF_OUTDOOR_TEMP_SENSOR,
            "Outdoor temperature",
            SensorDeviceClass.TEMPERATURE,
            "outdoor_temp_mirror",
        ),
        (
            CONF_OUTDOOR_HUMIDITY_SENSOR,
            "Outdoor humidity",
            SensorDeviceClass.HUMIDITY,
            "outdoor_humidity_mirror",
        ),
        (CONF_PRECIPITATION_SENSOR, "Precipitation", None, "precipitation_mirror"),
        (CONF_WIND_SPEED_SENSOR, "Wind speed", None, "wind_speed_mirror"),
        (
            CONF_INDOOR_WAKE_SENSOR,
            "Indoor wake sensor",
            SensorDeviceClass.TEMPERATURE,
            "indoor_wake_mirror",
        ),
    )
    for conf_key, name, device_class, suffix in numeric_fields:
        source_id = config.get(conf_key)
        if not source_id:
            continue
        mirrors.append(
            _NumericMirrorSensor(
                coordinator,
                unique_id=f"{entry.entry_id}_{suffix}",
                name=name,
                source_entity_id=source_id,
                device_info=device_info,
                device_class=device_class,
            )
        )

    text_fields = (
        (CONF_WEATHER_ENTITY, "Weather source", "weather_mirror"),
        (CONF_ALARM_PANEL, "Alarm panel", "alarm_panel_mirror"),
    )
    for conf_key, name, suffix in text_fields:
        source_id = config.get(conf_key)
        if not source_id:
            continue
        mirrors.append(
            _TextMirrorSensor(
                coordinator,
                unique_id=f"{entry.entry_id}_{suffix}",
                name=name,
                source_entity_id=source_id,
                device_info=device_info,
            )
        )

    return mirrors


class _MirrorSensorBase(CoordinatorEntity, SensorEntity):
    """Generic read-through mirror of one already-configured source entity.

    Gold IQS — entity-unavailable: mirrors the source entity's own
    availability, so this entity greys out exactly when the real sensor
    does (a missing/removed entity_id counts as unavailable too).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        unique_id: str,
        name: str,
        source_entity_id: str,
        device_info: DeviceInfo,
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._source_id = source_entity_id
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_device_info = device_info
        if device_class is not None:
            self._attr_device_class = device_class

    @property
    def available(self) -> bool:
        s = self.coordinator.hass.states.get(self._source_id)
        return s is not None and s.state not in ("unavailable", "unknown")

    @property
    def native_unit_of_measurement(self) -> str | None:
        s = self.coordinator.hass.states.get(self._source_id)
        if s is None:
            return None
        return s.attributes.get("unit_of_measurement")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source_entity_id": self._source_id}


class _NumericMirrorSensor(_MirrorSensorBase):
    """Mirror of a numeric source (temperature, humidity, CO2, battery,
    precipitation, wind speed, ...)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        s = self.coordinator.hass.states.get(self._source_id)
        if s is None or s.state in ("unavailable", "unknown"):
            return None
        try:
            return float(s.state)
        except (TypeError, ValueError):
            return None


class _TextMirrorSensor(_MirrorSensorBase):
    """Mirror of a non-numeric source (weather condition, alarm state,
    ...) — forwards its raw state string as-is."""

    @property
    def native_value(self) -> str | None:
        s = self.coordinator.hass.states.get(self._source_id)
        if s is None or s.state in ("unavailable", "unknown"):
            return None
        return s.state


# ── Global sensors ────────────────────────────────────────────────────────────


class PauseRemainingSensor(CoordinatorEntity, SensorEntity):
    """Minutes remaining in the current pause. 0 when not paused."""

    _attr_has_entity_name = True
    _attr_translation_key = "pause_remaining"
    _attr_native_unit_of_measurement = "min"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = (
        False  # off by default — only needed for debugging
    )

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_pause_remaining"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def native_value(self) -> int:
        return self.coordinator.pause_remaining_minutes


class EnergyWastedSensor(CoordinatorEntity, SensorEntity):
    """kWh wasted today — windows open while heating runs.

    state_class = TOTAL_INCREASING (not MEASUREMENT — HA rejects that
    combination outright for device_class ENERGY, which only allows None,
    TOTAL or TOTAL_INCREASING). This resets to 0 at midnight; HA's
    statistics engine treats a drop like that as a normal meter reset for
    TOTAL_INCREASING sensors, which is exactly this value's shape, so no
    last_reset bookkeeping (TOTAL's requirement) is needed.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "energy_wasted_today"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy_wasted_today"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def native_value(self) -> float:
        return self.coordinator.energy_wasted_today


class EnergySavedSensor(CoordinatorEntity, SensorEntity):
    """kWh saved today — away mode during expected heating hours.

    state_class = TOTAL_INCREASING — resets at midnight, same reasoning as
    EnergyWastedSensor above.
    """

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
        self._attr_device_info = coordinator.global_device_info()

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
        self._attr_device_info = coordinator.global_device_info()

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
        self._room_name = room["room_name"]
        self._climate_id = room.get(CONF_CLIMATE_ENTITY, "")
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_state"
        self._attr_name = f"{self._room_name} state"
        self._was_unavailable: bool = False
        self._attr_device_info = coordinator.room_device_info(self._room_name)

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
        return {
            "room_name": self._room_name,
            "blocking_sources": self.coordinator.get_room_blocking_sources(
                self._room_name
            ),
            # v0.14.0: which caller ("switch"/"remote") currently holds this
            # room in OVERRIDE, if any — None otherwise. The mobile card
            # reads this off the room's own state sensor entity since it has
            # no websocket connection of its own (see heat-manager-card.js
            # _roomOverrideSource()).
            "override_source": self.coordinator.room_override_source.get(
                self._room_name
            ),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Log once on unavailable, once on recovery — never spam."""
        is_unavailable = not self.available
        if is_unavailable and not self._was_unavailable:
            _LOGGER.warning(
                "Heat Manager: climate entity %s is unavailable — "
                "%s state sensor marked unavailable",
                self._climate_id,
                self._room_name,
            )
        elif not is_unavailable and self._was_unavailable:
            _LOGGER.info(
                "Heat Manager: climate entity %s recovered — "
                "%s state sensor available again",
                self._climate_id,
                self._room_name,
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
        self._attr_device_info = coordinator.room_device_info(self._room_name)

    @property
    def native_value(self) -> int:
        return self._total_minutes

    @callback
    def _handle_coordinator_update(self) -> None:
        is_open = (
            self.coordinator.get_room_state(self._room_name) == RoomState.WINDOW_OPEN
        )
        now = utcnow()

        # S-6 FIX: use date() not day-of-month integer to avoid false resets
        today = now.date()
        if today != self._last_reset_date:
            self._total_minutes = 0
            self._was_open = False
            self._opened_at = None
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
    Created for every room — the hybrid PID engine (v0.8.0) regulates
    Netatmo/HomeKit rooms (against the cloud schedule setpoint) AND
    local/Zigbee rooms (against CONF_COMFORT_TEMP), so every room has a
    live PidController instance and a meaningful power value.
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
        self._attr_device_info = coordinator.room_device_info(self._room_name)

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
            "room_name": self._room_name,
            "pid_kp": getattr(pid, "kp", None),
            "pid_ki": getattr(pid, "ki", None),
            "pid_kd": getattr(pid, "kd", None),
            "integral": round(getattr(pid, "_integral", 0.0), 4),
        }


class RoomCalibrationOffsetSensor(CoordinatorEntity, SensorEntity):
    """Last offset CalibrationEngine wrote to the room's calibration entity.

    Read-only mirror of engine/calibration_engine.py's internal state —
    created only for rooms with CONF_CALIBRATION_ENTITY configured.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 1
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
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_calibration_offset"
        self._attr_name = f"{self._room_name} calibration offset"
        self._attr_device_info = coordinator.room_device_info(self._room_name)

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.calibration_engine._last_written.get(self._room_name)
        return round(value, 1) if value is not None else None


class RemoteLastActionSensor(CoordinatorEntity, SensorEntity):
    """Timestamp of the last action taken by the global physical remote
    (v0.14.0's temp up/down/mode toggle buttons) — only created when at
    least one of the 3 button entities is configured.

    This is NOT a mirror of a configured sensor — it's an entity Heat
    Manager computes itself (see coordinator.set_remote_last_action(),
    called from engine/remote_button_engine.py), created because nothing
    else already shows "what did the remote last do, and when" at a glance.
    Complements room_override_source (which shows *where* the remote is
    currently holding a room in manual mode) with the Hub-level *when/what*.
    """

    _attr_has_entity_name = True
    _attr_name = "Remote last action"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_remote_last_action"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def native_value(self) -> datetime | None:
        action = self.coordinator.remote_last_action
        if not action:
            return None
        return parse_datetime(action["timestamp"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        action = self.coordinator.remote_last_action
        if not action:
            return {}
        return {
            "description": action["description"],
            "rooms": action["rooms"],
        }
