"""Heat Manager coordinator — Netatmo layer: backend, valve health, relay.

Which Netatmo integration (core netatmo or NET-TRV) owns each valve, the
valves' connectivity/battery/webhook health, the relay's away temperature,
and the per-room release back to the Netatmo schedule. Backend rules are in
engine/netatmo_backend.py; this layer only does the registry lookups
(v0.68.5, T3e).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ..const import (
    CONF_NETATMO_BACKEND,
    CONF_TRV_TYPE,
    DEFAULT_NETATMO_BACKEND,
    NETATMO_API_CALL_DELAY_SEC,
    PRESET_SCHEDULE,
    SERVICE_CLEAR_TEMPERATURE_SETTING,
)
from ..engine.netatmo_backend import (
    HEALTH_BATTERY,
    HEALTH_BATTERY_STATE,
    HEALTH_CONNECTIVITY,
    HEALTH_VALVE_POSITION,
    RELAY_AWAY_TEMP_SUFFIX,
    RELAY_WEBHOOK_SUFFIX,
    NetatmoBackend,
    SiblingEntity,
    available_backends,
    battery_is_low,
    effective_backend,
    pick_health_entities,
    pick_relay_entity,
    resolve_backend,
    summarize_backends,
    trv_pid_writable,
    valve_recently_moved,
)
from .sensors import CoordinatorSensors

_LOGGER = logging.getLogger(__name__)


def _parent_device_id(device: Any) -> str | None:
    """The device this device hangs off: ``parent_device_id`` on HA 2026.11+
    child devices (ChildDeviceEntry), else ``via_device_id``. Reading
    via_device_id on a child device logs a deprecation (breaks in 2027.9),
    so the child attribute is checked first. NET-TRV's room devices are plain
    devices with via_device_id (relay) today."""
    if device is None:
        return None
    parent = getattr(device, "parent_device_id", None)
    if isinstance(parent, str) and parent:
        return parent
    via = getattr(device, "via_device_id", None)
    return via if isinstance(via, str) and via else None


class CoordinatorNetatmo(CoordinatorSensors):
    """Heat Manager coordinator — Netatmo layer: backend, valve health, relay."""

    def get_trv_netatmo_backend(self, trv: dict[str, Any]) -> NetatmoBackend | None:
        """Netatmo integration owning this TRV's climate entity (v0.61.0).

        Read from the entity registry's `platform`, never from the entity_id
        — the 2026-11-11 migration swapped entity names between core netatmo
        and NET-TRV, so names say nothing about the owner. None for a
        non-Netatmo TRV (Zigbee, ...) or an entity missing from the registry.
        """
        return self._entity_netatmo_backend(self.get_trv_climate_entity(trv))

    def get_room_netatmo_backend(self, room_name: str) -> str:
        """Summary of the room's Netatmo backends: "net_trv", "netatmo",
        "mixed" or "none" — see engine/netatmo_backend.summarize_backends."""
        return summarize_backends(
            self.get_trv_netatmo_backend(trv) for trv in self.get_room_trvs(room_name)
        )

    def get_installed_netatmo_backends(self) -> set[NetatmoBackend]:
        """Netatmo integrations with at least one config entry that is not
        disabled. v0.65.1: a disabled entry no longer counts as installed —
        async_entries() returns disabled entries too."""
        return available_backends(
            backend.value
            for backend in NetatmoBackend
            if any(
                entry.disabled_by is None
                for entry in self.hass.config_entries.async_entries(backend.value)
            )
        )

    def is_trv_pid_writable(self, trv: dict[str, Any]) -> bool:
        """v0.61.2: see engine/netatmo_backend.trv_pid_writable()."""
        return trv_pid_writable(
            trv.get(CONF_TRV_TYPE), bool(self.get_trv_homekit_entity(trv))
        )

    def get_trv_health_entities(self, trv: dict[str, Any]) -> dict[str, list[str]]:
        """v0.62.0: connectivity/battery entities on the same device as this
        Netatmo TRV's climate entity — see pick_health_entities(). Empty for
        non-Netatmo TRVs and when the integration exposes none of them."""
        entity_id = self.get_trv_climate_entity(trv)
        if not entity_id:
            return {}
        ent_reg = er.async_get(self.hass)
        entry = ent_reg.async_get(entity_id)
        if (
            entry is None
            or not entry.device_id
            or resolve_backend(entry.platform) is None
        ):
            return {}
        return pick_health_entities(
            SiblingEntity(
                entity_id=e.entity_id,
                domain=e.domain,
                unique_id=e.unique_id or "",
                device_class=e.device_class or e.original_device_class,
            )
            for e in er.async_entries_for_device(ent_reg, entry.device_id)
        )

    def is_trv_reachable(self, trv: dict[str, Any]) -> bool:
        """v0.62.0: False only when the integration says the valve itself is
        offline (connectivity sensor "off"). No sensor / unknown = reachable,
        so integrations without the sensor behave exactly as before."""
        return not any(
            self._state_value(eid) == "off"
            for eid in self.get_trv_health_entities(trv).get(HEALTH_CONNECTIVITY, [])
        )

    def _trv_battery_low(self, trv: dict[str, Any]) -> bool:
        roles = self.get_trv_health_entities(trv)
        for state_id in roles.get(HEALTH_BATTERY_STATE, []):
            if battery_is_low(self._state_value(state_id), None):
                return True
        if roles.get(HEALTH_BATTERY_STATE):
            return False  # battery_state is the truth when it exists
        return any(
            battery_is_low(None, self._state_value(pct_id))
            for pct_id in roles.get(HEALTH_BATTERY, [])
        )

    def trv_valve_recently_moved(self, trv: dict[str, Any], now_ts: float) -> bool:
        """v0.65.0: True when every valve_position sensor of this TRV shows a
        Netatmo motor report within the last week (NET-TRV `netatmo_ts`).
        No sensor, a disabled sensor or no report since NET-TRV started →
        False, so ValveProtectionEngine exercises the valve as before."""
        sensors = self.get_trv_health_entities(trv).get(HEALTH_VALVE_POSITION, [])
        if not sensors:
            return False
        for eid in sensors:
            state = self.hass.states.get(eid)
            ts = state.attributes.get("netatmo_ts") if state is not None else None
            if not valve_recently_moved(ts, now_ts):
                return False
        return True

    def get_netatmo_webhook_entity(self) -> str | None:
        """NET-TRV's webhook binary_sensor on the relay device. None for core
        netatmo."""
        return self._netatmo_relay_entity("binary_sensor", RELAY_WEBHOOK_SUFFIX)

    def get_netatmo_away_temp_entity(self) -> str | None:
        """v0.67.0: NET-TRV's writable home-level away temperature
        (number.<relay>_away_temperature) — the temperature every Netatmo
        valve goes to while Heat Manager has the house in away mode. None for
        core netatmo, which has no such entity."""
        return self._netatmo_relay_entity("number", RELAY_AWAY_TEMP_SUFFIX)

    def _netatmo_relay_entity(self, domain: str, suffix: str) -> str | None:
        """Find a NET-TRV entity on the relay device that the room devices
        hang off (via_device), by unique_id suffix."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        for room in self.rooms:
            for trv in self.get_room_trvs(room.get("room_name", "")):
                entity_id = self.get_trv_climate_entity(trv)
                entry = ent_reg.async_get(entity_id) if entity_id else None
                if entry is None or entry.platform != NetatmoBackend.NET_TRV:
                    continue
                device = dev_reg.async_get(entry.device_id) if entry.device_id else None
                relay_device_id = _parent_device_id(device)
                if relay_device_id is None:
                    continue
                found = pick_relay_entity(
                    (
                        SiblingEntity(
                            entity_id=sib.entity_id,
                            domain=sib.domain,
                            unique_id=sib.unique_id or "",
                            device_class=None,
                        )
                        for sib in er.async_entries_for_device(ent_reg, relay_device_id)
                    ),
                    domain,
                    suffix,
                )
                if found:
                    return found
        return None

    def get_netatmo_health(self) -> dict[str, Any]:
        """v0.62.0: rooms with an offline valve / low battery, and whether
        NET-TRV's realtime webhook is down (state "off")."""
        offline: list[str] = []
        low_battery: list[str] = []
        for room in self.rooms:
            name = room.get("room_name", "")
            if not name:
                continue
            trvs = self.get_room_trvs(name)
            if any(not self.is_trv_reachable(t) for t in trvs):
                offline.append(name)
            if any(self._trv_battery_low(t) for t in trvs):
                low_battery.append(name)
        webhook = self.get_netatmo_webhook_entity()
        return {
            "offline_rooms": offline,
            "low_battery_rooms": low_battery,
            "webhook_down": webhook is not None and self._state_value(webhook) == "off",
        }

    def get_rooms_pid_needs_homekit(self) -> list[str]:
        """Rooms where PID is enabled but no TRV can be PID-driven because
        every Netatmo valve lacks a HomeKit entity (v0.61.2)."""
        if not self.pid_enabled:
            return []
        out: list[str] = []
        for room in self.rooms:
            name = room.get("room_name", "")
            trvs = self.get_room_trvs(name) if name else []
            if trvs and not any(self.is_trv_pid_writable(t) for t in trvs):
                out.append(name)
        return out

    @property
    def netatmo_backend_choice(self) -> str:
        """Global Netatmo backend choice: "auto", "netatmo" or "net_trv"."""
        return str(self.config.get(CONF_NETATMO_BACKEND, DEFAULT_NETATMO_BACKEND))

    def get_effective_netatmo_backend(self) -> NetatmoBackend | None:
        """Backend the choice resolves to with what is installed right now.

        None means an explicit choice whose integration is gone (repair) or
        no Netatmo integration installed at all.
        """
        return effective_backend(
            self.netatmo_backend_choice, self.get_installed_netatmo_backends()
        )

    async def async_call_netatmo_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Call <domain>.<service> (core netatmo / NET-TRV) on entity_id.

        Always a cloud call, so always under the same lock + pacing as
        async_call_climate_service(needs_delay=True).
        """
        async with self._netatmo_call_lock:
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id, **(data or {})},
                blocking=True,
            )
            await asyncio.sleep(NETATMO_API_CALL_DELAY_SEC)

    async def async_release_netatmo_room(self, entity_id: str) -> None:
        """v0.63.0: hand ONE Netatmo room back to its schedule without
        touching the home's mode.

        preset_mode: schedule is a HOME-level command in Netatmo (core and
        NET-TRV), and core maps hvac_mode: auto onto it too — so using
        either to restore one room after an override/window/controller-OFF
        cancelled away or frost guard for the whole house. The owning
        integration's clear_temperature_setting drops only this room's
        manual setpoint. Skipped when the room already follows the schedule
        (NET-TRV's netatmo_setpoint_mode). An entity whose owner is unknown
        keeps the old preset_mode: schedule call.
        """
        backend = self._entity_netatmo_backend(entity_id)
        if backend is None:
            await self.async_call_climate_service(
                "set_preset_mode",
                entity_id,
                {"preset_mode": PRESET_SCHEDULE},
                needs_delay=True,
            )
            return
        state = self.hass.states.get(entity_id)
        if state is not None and state.attributes.get("netatmo_setpoint_mode") in (
            "schedule",
            "home",
        ):
            return
        await self.async_call_netatmo_service(
            backend.value, SERVICE_CLEAR_TEMPERATURE_SETTING, entity_id
        )
