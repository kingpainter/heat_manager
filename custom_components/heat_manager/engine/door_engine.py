"""
Heat Manager — Door Engine

2026-09-11: new engine for INTERIOR doors (CONF_DOORS), added per Flemming's
feature request (see project doc planning/heat_manager_features_2026-09-11.md,
point 1+2, level A — "visibility"). Unlike WindowEngine, an interior door
carries no heat-suppression meaning of its own — heat isn't lost when it's
open, it just moves between two rooms Heat Manager already controls. This
engine therefore does exactly one thing: log a real, human-readable event
every time a configured interior door opens or closes, so the history tab in
the panel shows real house activity. It does not compute or hold any
"is this room's door open" state itself — that's read live from hass
whenever needed via coordinator.is_room_door_open() (see coordinator.py),
so there is nothing here that can drift out of sync with reality between
listener events.

CalibrationEngine (level B of the same feature) reads coordinator.
is_room_door_open() directly to pick between a room's two learned heat-up
profiles — it does not depend on anything in this file.

Built restart-safe from day one, reusing the known-old-state guard pattern
proven in window_engine.py / presence_engine.py on 2026-09-11: a door
sensor's platform fires a state_changed event the first time its real state
becomes known again after an HA restart/reload (old_state None/"unknown"/
"unavailable"), even though nothing physically opened or closed. Only a
genuine flip between two KNOWN states ("on"/"off") is logged. There is
deliberately no "_check_initial_doors()" startup sync (contrast
WindowEngine/PresenceEngine, which both have one): those exist because a
window/alarm already open/armed at startup must actively re-suppress
heating that hasn't happened yet. A door has no such pending action to
re-arm — it's pure history — so silently doing nothing about a door's
state at startup is correct; the very next real transition logs normally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import CONF_DOOR_ROOM_A, CONF_DOOR_ROOM_B, CONF_DOOR_SENSOR

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class DoorEngine:
    """Logs interior door open/close events. See module docstring."""

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        # sensor entity_id -> (room_a, room_b), in the order configured
        self._sensor_to_rooms: dict[str, tuple[str, str]] = {}
        self._unsubs: list[Any] = []
        self._build_sensor_map()
        self._register_listeners()

    def _build_sensor_map(self) -> None:
        for door in self.coordinator.doors:
            sensor_id = door.get(CONF_DOOR_SENSOR)
            room_a = door.get(CONF_DOOR_ROOM_A, "")
            room_b = door.get(CONF_DOOR_ROOM_B, "")
            if sensor_id and room_a and room_b:
                self._sensor_to_rooms[sensor_id] = (room_a, room_b)
        _LOGGER.debug("Door engine tracking %d door(s)", len(self._sensor_to_rooms))

    def _register_listeners(self) -> None:
        sensors = list(self._sensor_to_rooms.keys())
        if not sensors:
            _LOGGER.debug("No interior doors configured — door engine idle")
            return
        self._unsubs.append(
            async_track_state_change_event(
                self.coordinator.hass, sensors, self._handle_sensor_change
            )
        )

    @callback
    def _handle_sensor_change(self, event: Any) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        new = new_state.state
        old = old_state.state if old_state else None
        entity_id = event.data.get("entity_id", "")

        # Restart-noise guard (2026-09-11) — see module docstring and
        # window_engine.py's _handle_sensor_change() for the full rationale.
        # Only a genuine flip between two KNOWN states is a real event.
        if old not in ("on", "off") or old == new:
            return

        rooms = self._sensor_to_rooms.get(entity_id)
        if not rooms:
            return
        room_a, room_b = rooms

        if new == "on":
            _LOGGER.info("Door opened between '%s' and '%s'", room_a, room_b)
            self.coordinator.log_event(
                f"Dør åbnet mellem {room_a} og {room_b}", "Dør", "door"
            )
        else:
            _LOGGER.info("Door closed between '%s' and '%s'", room_a, room_b)
            self.coordinator.log_event(
                f"Dør lukket mellem {room_a} og {room_b}", "Dør", "door"
            )

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("DoorEngine shut down")
