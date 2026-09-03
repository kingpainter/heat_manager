"""
Heat Manager — Sync Engine (v0.9.0)

Detects when a room's write entity (its Netatmo HomeKit local entity, or
its single Zigbee climate entity) changes for a reason other than Heat
Manager's own PID tick — the Netatmo app, a physical TRV dial, another
automation — and reacts according to the room's configured CONF_SYNC_MODE:

  disabled (default) — ignore. No listener overhead beyond the state-change
                        subscription itself.
  mirror              — accept the change. The room is switched into
                         RoomState.OVERRIDE, the same state the existing
                         per-room override switch already provides, so PID
                         stops fighting the manual setpoint until the user
                         (or a schedule slot / window event) clears it.
  lock                — reject the change. The setpoint the PID tick last
                         computed as correct (coordinator.last_expected_setpoint)
                         is re-sent, cancelling the manual change out.

Telling "Heat Manager just wrote this" apart from a genuine external change
--------------------------------------------------------------------------
Rather than instrumenting every existing call site that writes to a climate
entity (PID tick, boost, override switch, presence/window/preheat engines,
valve protection) with a shared "this write is ours" flag, SyncEngine
compares the entity's reported `temperature` attribute against
coordinator.last_expected_setpoint[room_name] — the value the PID tick
itself computed and either wrote or intentionally suppressed (same value
either way) on its most recent run. A mismatch has to persist for
SYNC_CONFIRM_DELAY_SEC before SyncEngine acts, which absorbs the normal
round-trip window right after Heat Manager's own write where a slow device
(Zigbee, Netatmo cloud) may still briefly report its old value.

Only rooms in RoomState.NORMAL are monitored — PID does not maintain a
meaningful "expected" setpoint for AWAY / WINDOW_OPEN / PRE_HEAT / OVERRIDE
rooms, so a mismatch there is not evidence of anything.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_SYNC_MODE,
    DEFAULT_SYNC_MODE,
    SYNC_CHANGE_THRESHOLD,
    SYNC_CONFIRM_DELAY_SEC,
    SYNC_MODE_DISABLED,
    SYNC_MODE_LOCK,
    SYNC_MODE_MIRROR,
    ControllerState,
    RoomState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class SyncEngine:
    """Per-room reaction to manual/external changes on the write entity."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._entity_to_room: dict[str, str] = {}
        self._unsubs: list[Any] = []
        self._pending_confirm: dict[str, Any] = {}  # room_name -> cancel callback
        self._build_entity_map()
        self._register_listeners()

    def _build_entity_map(self) -> None:
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            if room.get(CONF_SYNC_MODE, DEFAULT_SYNC_MODE) == SYNC_MODE_DISABLED:
                continue
            for key in (CONF_CLIMATE_ENTITY, CONF_HOMEKIT_CLIMATE_ENTITY):
                entity_id = room.get(key) or None
                if entity_id:
                    self._entity_to_room[entity_id] = room_name

    def _register_listeners(self) -> None:
        entities = list(self._entity_to_room.keys())
        if not entities:
            _LOGGER.debug("Sync engine: no rooms have sync_mode enabled — idle")
            return
        self._unsubs.append(
            async_track_state_change_event(
                self.coordinator.hass, entities, self._handle_entity_change
            )
        )

    @callback
    def _handle_entity_change(self, event: Any) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        room_name = self._entity_to_room.get(entity_id)
        if room_name is None or new_state is None:
            return
        if new_state.state in ("unavailable", "unknown", "off"):
            return

        # Only the room's *currently active* write entity is authoritative —
        # ignore the inactive one (e.g. the cloud entity while HomeKit is
        # the live write target) to avoid reacting to stale/duplicate state.
        if self.coordinator.get_write_entity(room_name) != entity_id:
            return

        if self.coordinator.controller_state != ControllerState.ON:
            return
        if self.coordinator.get_room_state(room_name) != RoomState.NORMAL:
            return

        expected = self.coordinator.last_expected_setpoint.get(room_name)
        if expected is None:
            return  # PID hasn't established an expectation yet — nothing to compare

        try:
            observed = float(new_state.attributes.get("temperature"))
        except (TypeError, ValueError):
            return

        if abs(observed - expected) < SYNC_CHANGE_THRESHOLD:
            self._cancel_pending(room_name)
            return

        if room_name in self._pending_confirm:
            return  # already waiting to confirm this mismatch

        self._pending_confirm[room_name] = async_call_later(
            self.coordinator.hass,
            SYNC_CONFIRM_DELAY_SEC,
            self._make_confirm_callback(room_name, entity_id),
        )

    def _make_confirm_callback(self, room_name: str, entity_id: str):
        @callback
        def _confirm(_now: Any) -> None:
            self._pending_confirm.pop(room_name, None)
            self.coordinator.hass.async_create_task(
                self._async_act(room_name, entity_id)
            )

        return _confirm

    def _cancel_pending(self, room_name: str) -> None:
        cancel = self._pending_confirm.pop(room_name, None)
        if cancel is not None:
            cancel()

    async def _async_act(self, room_name: str, entity_id: str) -> None:
        """Re-check and act once the confirm delay has elapsed."""
        if self.coordinator.controller_state != ControllerState.ON:
            return
        if self.coordinator.get_room_state(room_name) != RoomState.NORMAL:
            return
        # The room's active write entity (HomeKit vs cloud) can change
        # during the confirm delay — re-check rather than acting on a
        # now-stale entity_id, mirroring the guard in _handle_entity_change.
        if self.coordinator.get_write_entity(room_name) != entity_id:
            return
        state = self.coordinator.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", "off"):
            return
        expected = self.coordinator.last_expected_setpoint.get(room_name)
        if expected is None:
            return
        try:
            observed = float(state.attributes.get("temperature"))
        except (TypeError, ValueError):
            return
        if abs(observed - expected) < SYNC_CHANGE_THRESHOLD:
            return  # resolved itself (e.g. Heat Manager's own write finally landed)

        room = next(
            (r for r in self.coordinator.rooms if r.get("room_name") == room_name), {}
        )
        sync_mode = room.get(CONF_SYNC_MODE, DEFAULT_SYNC_MODE)

        if sync_mode == SYNC_MODE_MIRROR:
            self.coordinator.set_room_state(room_name, RoomState.OVERRIDE)
            self.coordinator.log_event(
                f"Manuel ændring accepteret — {room_name} ({observed:.1f}°C)",
                "sync_mode: mirror",
                "override",
            )
            _LOGGER.info(
                "Sync [mirror]: %s manually set to %.1f°C — switched to OVERRIDE",
                room_name,
                observed,
            )
        elif sync_mode == SYNC_MODE_LOCK:
            await self._async_lock_revert(room_name, entity_id, expected)

    async def _async_lock_revert(
        self, room_name: str, entity_id: str, expected: float
    ) -> None:
        try:
            await self.coordinator.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": expected},
                blocking=True,
            )
            self.coordinator.log_event(
                f"Manuel ændring afvist — {room_name} tilbage til {expected:.1f}°C",
                "sync_mode: lock",
                "warning",
            )
            _LOGGER.info(
                "Sync [lock]: %s reverted to expected %.1f°C", room_name, expected
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Sync [lock] revert failed for '%s': %s", room_name, err)

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in self._pending_confirm.values():
            cancel()
        self._pending_confirm.clear()
