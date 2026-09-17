"""
Heat Manager — Binary sensor platform

Gold IQS: entity-disabled-by-default applied to diagnostic sensors.
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HUMIDITY_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_WINDOW_SENSORS,
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
        CloudAvailableSensor(coordinator, entry),
    ]
    for room in coordinator.rooms:
        if room.get(CONF_WINDOW_SENSORS):
            entities.append(RoomWindowSensor(coordinator, entry, room))
            # v0.15.0 — mirror each individual raw window/door contact
            # under the room's device too (RoomWindowSensor above only
            # exposes the aggregated "any open" state) — see sensor.py's
            # analogous numeric mirrors for the same visibility rationale.
            entities.extend(
                RawWindowContactMirror(coordinator, entry, room, index, source_id)
                for index, source_id in enumerate(room[CONF_WINDOW_SENSORS])
                if source_id
            )
        if room.get(CONF_HUMIDITY_SENSOR):
            entities.append(MoldRiskSensor(coordinator, entry, room))

    async_add_entities(entities)


class AnyWindowOpenSensor(CoordinatorEntity[HeatManagerCoordinator], BinarySensorEntity):
    """True when any configured window/door sensor is currently open."""

    _attr_has_entity_name = True
    _attr_translation_key = "any_window_open"
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_entity_registry_enabled_default = True  # useful for automations

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        # 2026-09-15 (punkt 1B, strict typing): homeassistant-stubs'
        # BaseCoordinatorEntity declares `coordinator: Incomplete` at
        # the class level, which shadows the generic TypeVar-based
        # inference from CoordinatorEntity[HeatManagerCoordinator] —
        # every self.coordinator.xxx access below would otherwise type
        # as Any regardless of the class's own generic parameter. This
        # explicit re-annotation narrows it back for mypy's benefit;
        # purely a typing fix, coordinator is the same object either way.
        self.coordinator: HeatManagerCoordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_any_window_open"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def is_on(self) -> bool:
        return self.coordinator.any_window_open()


class CloudAvailableSensor(CoordinatorEntity[HeatManagerCoordinator], BinarySensorEntity):
    """True when Netatmo cloud entities are available and fresh.

    Detects two failure modes:
    - All climate entities are unavailable/unknown (cloud down)
    - All climate entities have stale last_updated (> 10 min, cloud degraded)

    Can be used in HA automations e.g. to send a notification when cloud drops.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cloud_available"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_registry_enabled_default = True

    _STALE_MINUTES: int = 10

    def __init__(self, coordinator: HeatManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        # 2026-09-15 (punkt 1B, strict typing): homeassistant-stubs'
        # BaseCoordinatorEntity declares `coordinator: Incomplete` at
        # the class level, which shadows the generic TypeVar-based
        # inference from CoordinatorEntity[HeatManagerCoordinator] —
        # every self.coordinator.xxx access below would otherwise type
        # as Any regardless of the class's own generic parameter. This
        # explicit re-annotation narrows it back for mypy's benefit;
        # purely a typing fix, coordinator is the same object either way.
        self.coordinator: HeatManagerCoordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_cloud_available"
        self._attr_device_info = coordinator.global_device_info()

    @property
    def is_on(self) -> bool:
        """True = cloud OK. False = cloud down or degraded."""
        rooms = self.coordinator.rooms
        if not rooms:
            return True

        from datetime import datetime

        now = datetime.now(UTC)
        stale_threshold = self._STALE_MINUTES * 60
        unavailable_count = 0
        stale_count = 0
        total = 0

        for room in rooms:
            room_name = room.get("room_name", "")
            climate_id = self.coordinator.get_climate_entity(room_name) or ""
            # Skip HomeKit entities — they are local and not a cloud indicator
            hk_id = self.coordinator.get_homekit_climate_entity(room_name) or ""
            if not climate_id or climate_id == hk_id:
                continue
            total += 1
            state = self.coordinator.hass.states.get(climate_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable_count += 1
                continue
            if state.last_updated:
                age = (
                    now - state.last_updated.replace(tzinfo=UTC)
                    if state.last_updated.tzinfo is None
                    else (now - state.last_updated)
                ).total_seconds()
                if age > stale_threshold:
                    stale_count += 1

        if total == 0:
            return True
        if unavailable_count == total:
            return False  # all unavailable
        return stale_count != total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rooms = self.coordinator.rooms
        unavailable = []
        stale = []
        from datetime import datetime

        now = datetime.now(UTC)
        for room in rooms:
            room_name = room.get("room_name", "")
            climate_id = self.coordinator.get_climate_entity(room_name) or ""
            hk_id = self.coordinator.get_homekit_climate_entity(room_name) or ""
            if not climate_id or climate_id == hk_id:
                continue
            state = self.coordinator.hass.states.get(climate_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable.append(room.get("room_name", climate_id))
            elif state.last_updated:
                age = (
                    now - state.last_updated.replace(tzinfo=UTC)
                    if state.last_updated.tzinfo is None
                    else (now - state.last_updated)
                ).total_seconds()
                if age > self._STALE_MINUTES * 60:
                    stale.append(room.get("room_name", climate_id))
        return {
            "unavailable_rooms": unavailable,
            "stale_rooms": stale,
            "stale_threshold_min": self._STALE_MINUTES,
        }


class RoomWindowSensor(CoordinatorEntity[HeatManagerCoordinator], BinarySensorEntity):
    """Per-room aggregated window open state."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_entity_registry_enabled_default = False  # per-room detail — off by default

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        # 2026-09-15 (punkt 1B, strict typing): homeassistant-stubs'
        # BaseCoordinatorEntity declares `coordinator: Incomplete` at
        # the class level, which shadows the generic TypeVar-based
        # inference from CoordinatorEntity[HeatManagerCoordinator] —
        # every self.coordinator.xxx access below would otherwise type
        # as Any regardless of the class's own generic parameter. This
        # explicit re-annotation narrows it back for mypy's benefit;
        # purely a typing fix, coordinator is the same object either way.
        self.coordinator: HeatManagerCoordinator = coordinator
        self._room_name = room["room_name"]
        self._sensors = room.get(CONF_WINDOW_SENSORS, [])
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_window"
        # has_entity_name=True + device.name == room_name means HA itself
        # prefixes the device name onto _attr_name (→ f"{device_name}
        # {name}", entity.py's _friendly_name_internal()) — a short local
        # name, NOT "{room_name} window", is what produces the correct
        # "Living room Window" friendly_name. Found doubled ("Living room
        # Living room Window") during the B18 Fase 1-4 consistency pass.
        self._attr_name = "Window"
        self._attr_device_info = coordinator.room_device_info(self._room_name)

    @property
    def is_on(self) -> bool:
        return any(
            (s := self.coordinator.hass.states.get(sid)) is not None and s.state == "on"
            for sid in self._sensors
        )


class MoldRiskSensor(CoordinatorEntity[HeatManagerCoordinator], BinarySensorEntity):
    """
    True when conditions indicate mold risk in a room.

    Algorithm (DIN 4108-2 simplified)
    ----------------------------------
    Mold risk = RH ≥ 70%  AND  room temperature ≤ dewpoint + 1 °C margin

    Dewpoint approximated via Magnus formula (Lawrence 2005 simplification):
        T_dp = (243.04 × γ) / (17.625 − γ)
        where γ = ln(RH/100) + (17.625 × T) / (243.04 + T)

    Sensor sources (in priority order)
    ------------------------------------
    1. CONF_HUMIDITY_SENSOR   — relative humidity (%) — required
    2. CONF_ROOM_TEMP_SENSOR  — room temperature (°C)  — preferred
    3. Climate entity current_temperature                — fallback

    Rationale: if the room temperature is close to or below the dewpoint
    the partial vapour pressure at wall surfaces (which are typically 1–2 °C
    cooler than room air) exceeds saturation pressure and condensation forms.
    The 1 °C margin accounts for this surface-to-air temperature offset.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_entity_registry_enabled_default = True

    # Mold risk thresholds
    _RH_THRESHOLD: float = 70.0  # % — DIN 4108-2 critical humidity
    _SURFACE_MARGIN: float = 1.0  # °C — wall surface is ~1 °C cooler than air

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        # 2026-09-15 (punkt 1B, strict typing): homeassistant-stubs'
        # BaseCoordinatorEntity declares `coordinator: Incomplete` at
        # the class level, which shadows the generic TypeVar-based
        # inference from CoordinatorEntity[HeatManagerCoordinator] —
        # every self.coordinator.xxx access below would otherwise type
        # as Any regardless of the class's own generic parameter. This
        # explicit re-annotation narrows it back for mypy's benefit;
        # purely a typing fix, coordinator is the same object either way.
        self.coordinator: HeatManagerCoordinator = coordinator
        self._room_name = room["room_name"]
        self._humidity_id = room.get(CONF_HUMIDITY_SENSOR, "")
        self._temp_id = room.get(CONF_ROOM_TEMP_SENSOR, "")
        self._climate_id = coordinator.get_climate_entity(self._room_name) or ""
        safe_name = self._room_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_mold_risk"
        # Short local name — see the identical note on RoomWindowSensor
        # above. Produces friendly_name "Living room Mold risk" (not the
        # doubled "Living room Living room Mold risk").
        self._attr_name = "Mold risk"
        self._attr_device_info = coordinator.room_device_info(self._room_name)

    @staticmethod
    def _dewpoint(temp_c: float, rh_pct: float) -> float:
        """Magnus formula (Lawrence 2005) — valid for 0–60 °C, 1–100% RH."""
        import math

        b, c = 17.625, 243.04
        gamma = math.log(max(rh_pct, 0.01) / 100.0) + (b * temp_c) / (c + temp_c)
        return (c * gamma) / (b - gamma)

    def _get_humidity(self) -> float | None:
        if not self._humidity_id:
            return None
        s = self.coordinator.hass.states.get(self._humidity_id)
        if s is None or s.state in ("unknown", "unavailable"):
            return None
        try:
            return float(s.state)
        except (TypeError, ValueError):
            return None

    def _get_temp(self) -> float | None:
        # 1. Dedicated room temp sensor
        if self._temp_id:
            s = self.coordinator.hass.states.get(self._temp_id)
            if s and s.state not in ("unknown", "unavailable"):
                try:
                    return float(s.state)
                except (TypeError, ValueError):
                    pass
        # 2. Climate entity current_temperature
        if self._climate_id:
            s = self.coordinator.hass.states.get(self._climate_id)
            if s and s.state not in ("unknown", "unavailable"):
                try:
                    v = s.attributes.get("current_temperature")
                    if v is not None:
                        return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    @property
    def available(self) -> bool:
        return self._get_humidity() is not None and self._get_temp() is not None

    @property
    def is_on(self) -> bool:
        rh = self._get_humidity()
        temp = self._get_temp()
        if rh is None or temp is None:
            return False
        if rh < self._RH_THRESHOLD:
            return False
        dewpoint = self._dewpoint(temp, rh)
        # Risk if room air temp is within surface_margin of dewpoint
        return temp <= (dewpoint + self._SURFACE_MARGIN)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rh = self._get_humidity()
        temp = self._get_temp()
        if rh is None or temp is None:
            return {"room_name": self._room_name}
        dewpoint = self._dewpoint(temp, rh)
        outdoor_rh = self.coordinator.get_outdoor_humidity()
        return {
            "room_name": self._room_name,
            "humidity_pct": round(rh, 1),
            "room_temp_c": round(temp, 1),
            "dewpoint_c": round(dewpoint, 1),
            "margin_c": self._SURFACE_MARGIN,
            "outdoor_humidity_pct": round(outdoor_rh, 1)
            if outdoor_rh is not None
            else None,
        }


class RawWindowContactMirror(CoordinatorEntity[HeatManagerCoordinator], BinarySensorEntity):
    """Diagnostic mirror of ONE raw configured window/door contact sensor,
    shown under the room's own device (v0.15.0).

    Heat Manager doesn't own this entity — it belongs to whatever
    integration created it (Zigbee2MQTT, deCONZ, etc.). Mirroring it here
    makes it show up on Heat Manager's own room device on the Integrations
    page too, so a failing/unavailable contact sensor is visible at a
    glance instead of hiding among another integration's entities.
    RoomWindowSensor (above) still owns the aggregated "any open" state
    used by the rest of the codebase — this is purely an additional,
    per-sensor visibility layer.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: HeatManagerCoordinator,
        entry: ConfigEntry,
        room: dict[str, Any],
        index: int,
        source_entity_id: str,
    ) -> None:
        super().__init__(coordinator)
        # 2026-09-15 (punkt 1B, strict typing): homeassistant-stubs'
        # BaseCoordinatorEntity declares `coordinator: Incomplete` at
        # the class level, which shadows the generic TypeVar-based
        # inference from CoordinatorEntity[HeatManagerCoordinator] —
        # every self.coordinator.xxx access below would otherwise type
        # as Any regardless of the class's own generic parameter. This
        # explicit re-annotation narrows it back for mypy's benefit;
        # purely a typing fix, coordinator is the same object either way.
        self.coordinator: HeatManagerCoordinator = coordinator
        room_name = room["room_name"]
        safe_name = room_name.lower().replace(" ", "_")
        self._source_id = source_entity_id
        self._attr_unique_id = f"{entry.entry_id}_{safe_name}_window_mirror_{index}"
        self._attr_name = f"Window/door sensor {index + 1}"
        self._attr_device_info = coordinator.room_device_info(room_name)

    @property
    def available(self) -> bool:
        s = self.coordinator.hass.states.get(self._source_id)
        return s is not None and s.state not in ("unavailable", "unknown")

    @property
    def is_on(self) -> bool | None:
        s = self.coordinator.hass.states.get(self._source_id)
        if s is None or s.state in ("unavailable", "unknown"):
            return None
        return bool(s.state == "on")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source_entity_id": self._source_id}
