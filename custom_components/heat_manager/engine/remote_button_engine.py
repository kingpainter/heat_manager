"""
Heat Manager — Remote Button Engine (v0.14.0)

Global (not per-room) physical remote control — e.g. an Aqara Climate
Sensor W100, which exposes 3 separate `event.*` entities (one per physical
button). Configurable in the options flow's "Remote control" step, so any
`event.*` entity can be assigned — not tied to one specific device model.

Behaviour
---------
- Temp up / temp down button: nudges EVERY room's TRV setpoint by
  ±BUTTON_TEMP_STEP (clamped between BUTTON_TEMP_MIN/MAX), skipping rooms
  currently WINDOW_OPEN or AWAY. A room still in NORMAL (auto) is switched
  to OVERRIDE (manual) first via coordinator.async_set_room_override(), so
  the next PID tick doesn't immediately overwrite the button's adjustment.
- Mode toggle button: toggles ALL eligible rooms (same WINDOW_OPEN/AWAY
  exclusion) between OVERRIDE (manual) and NORMAL (auto) together — if any
  eligible room is still NORMAL, every eligible room is switched to
  OVERRIDE; otherwise every eligible room is switched back to NORMAL.
- Only reacts to a "single" press (event_type == "single") — a hold/long
  press is ignored in this first version. Aqara W100 devices exposed via
  Zigbee2MQTT report "single"/"double"/"hold" in the event entity's
  event_type attribute; if your setup (a different integration, or a
  different device) reports a different string, adjust _is_single_press()
  below — check the entity's state attributes in Developer Tools if the
  buttons don't seem to trigger anything.
- No push notification is sent for button presses (the physical result —
  the radiator warming up — is its own feedback); every action is still
  written to the coordinator's event log for the panel's history.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import (
    BUTTON_TEMP_MAX,
    BUTTON_TEMP_MIN,
    BUTTON_TEMP_STEP,
    CONF_BUTTON_MODE_TOGGLE_ENTITY,
    CONF_BUTTON_TEMP_DOWN_ENTITY,
    CONF_BUTTON_TEMP_UP_ENTITY,
    RoomState,
)

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)

# Rooms in these states are never touched by the global remote — heating
# them would fight an open window, or force heat on while everyone's away.
_EXCLUDED_STATES = (RoomState.WINDOW_OPEN, RoomState.AWAY)


class RemoteButtonEngine:
    """Global physical remote — 3 optional `event.*` entities controlling
    every configured room at once. See module docstring above."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._unsubs: list[Any] = []
        self._register_listeners()

    def _register_listeners(self) -> None:
        hass = self.coordinator.hass
        config = self.coordinator.config

        up_id = config.get(CONF_BUTTON_TEMP_UP_ENTITY, "")
        down_id = config.get(CONF_BUTTON_TEMP_DOWN_ENTITY, "")
        mode_id = config.get(CONF_BUTTON_MODE_TOGGLE_ENTITY, "")

        if up_id:
            self._unsubs.append(
                async_track_state_change_event(hass, [up_id], self._handle_temp_up)
            )
        if down_id:
            self._unsubs.append(
                async_track_state_change_event(hass, [down_id], self._handle_temp_down)
            )
        if mode_id:
            self._unsubs.append(
                async_track_state_change_event(hass, [mode_id], self._handle_mode_toggle)
            )

        if not (up_id or down_id or mode_id):
            _LOGGER.debug("RemoteButtonEngine: no button entities configured — idle")

    @staticmethod
    def _is_single_press(new_state: Any) -> bool:
        """True only for a plain single click — see module docstring for
        why this may need adjusting for a different device/integration."""
        if new_state is None:
            return False
        event_type = new_state.attributes.get("event_type")
        return isinstance(event_type, str) and event_type.lower() == "single"

    # ── Temp up / down ──────────────────────────────────────────────────────

    @callback
    def _handle_temp_up(self, event: Any) -> None:
        if not self._is_single_press(event.data.get("new_state")):
            return
        self.coordinator.hass.async_create_task(
            self._async_adjust_all_rooms(BUTTON_TEMP_STEP),
            name="heat_manager_remote_temp_up",
        )

    @callback
    def _handle_temp_down(self, event: Any) -> None:
        if not self._is_single_press(event.data.get("new_state")):
            return
        self.coordinator.hass.async_create_task(
            self._async_adjust_all_rooms(-BUTTON_TEMP_STEP),
            name="heat_manager_remote_temp_down",
        )

    async def _async_adjust_all_rooms(self, delta: float) -> None:
        rooms_adjusted: list[str] = []
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            if self.coordinator.get_room_state(room_name) in _EXCLUDED_STATES:
                continue

            if self.coordinator.get_room_state(room_name) == RoomState.NORMAL:
                await self.coordinator.async_set_room_override(
                    room_name, True, source="remote"
                )

            write_entities = self.coordinator.get_room_write_entities(room_name)
            if not write_entities:
                continue

            current = self._current_setpoint(write_entities)
            if current is None:
                _LOGGER.warning(
                    "RemoteButtonEngine: no readable setpoint for '%s' — skipping",
                    room_name,
                )
                continue

            new_target = max(BUTTON_TEMP_MIN, min(BUTTON_TEMP_MAX, current + delta))
            if new_target == current:
                continue

            for write_id in write_entities:
                try:
                    await self.coordinator.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": write_id, "temperature": new_target},
                        blocking=True,
                    )
                # broad-except-rationale: one entity failing must not abort the others in this loop
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "RemoteButtonEngine: set_temperature failed for %s (%s): %s",
                        room_name,
                        write_id,
                        err,
                    )
            rooms_adjusted.append(f"{room_name} → {new_target:.1f}°C")

        if rooms_adjusted:
            sign = "+" if delta > 0 else ""
            rooms_str = ", ".join(rooms_adjusted)
            description = f"Remote: {sign}{delta:.1f}°C — {rooms_str}"
            self.coordinator.log_event(description, "Remote", "override")
            self.coordinator.set_remote_last_action(
                description,
                [room.split(" → ")[0] for room in rooms_adjusted],
            )
            _LOGGER.info("RemoteButtonEngine: temp %+.1f°C — %s", delta, rooms_str)

    def _current_setpoint(self, write_entities: list[str]) -> float | None:
        """First reachable write entity's own target temperature — the
        room's current setpoint to adjust from. Multi-TRV rooms are
        expected to already carry the same setpoint on every TRV (B18
        keeps them in sync); this just needs any one reachable reading."""
        for entity_id in write_entities:
            state = self.coordinator.hass.states.get(entity_id)
            if not state or state.state in ("unavailable", "unknown"):
                continue
            temp = state.attributes.get("temperature")
            if temp is None:
                continue
            try:
                return float(temp)
            except (TypeError, ValueError):
                continue
        return None

    # ── Mode toggle ───────────────────────────────────────────────────────────

    @callback
    def _handle_mode_toggle(self, event: Any) -> None:
        if not self._is_single_press(event.data.get("new_state")):
            return
        self.coordinator.hass.async_create_task(
            self._async_toggle_all_rooms(),
            name="heat_manager_remote_mode_toggle",
        )

    async def _async_toggle_all_rooms(self) -> None:
        eligible = [
            room.get("room_name", "")
            for room in self.coordinator.rooms
            if room.get("room_name")
            and self.coordinator.get_room_state(room.get("room_name", ""))
            not in _EXCLUDED_STATES
        ]
        if not eligible:
            return

        # If any eligible room is still auto, one press puts everything into
        # manual first — a mixed state always resolves towards manual, never
        # silently towards auto.
        enable = any(
            self.coordinator.get_room_state(room_name) == RoomState.NORMAL
            for room_name in eligible
        )

        rooms_changed: list[str] = []
        for room_name in eligible:
            current = self.coordinator.get_room_state(room_name)
            already_there = (
                current == RoomState.OVERRIDE if enable else current == RoomState.NORMAL
            )
            if already_there:
                continue
            ok = await self.coordinator.async_set_room_override(
                room_name, enable, source="remote"
            )
            if ok:
                rooms_changed.append(room_name)

        if rooms_changed:
            label = "manual" if enable else "auto"
            rooms_str = ", ".join(rooms_changed)
            description = f"Remote: switched to {label} — {rooms_str}"
            self.coordinator.log_event(
                description, "Remote", "override" if enable else "normal"
            )
            self.coordinator.set_remote_last_action(description, rooms_changed)
            _LOGGER.info(
                "RemoteButtonEngine: mode → %s for %s", label, rooms_str
            )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """No-op — all remote-button logic is event-driven."""

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("RemoteButtonEngine shut down")
