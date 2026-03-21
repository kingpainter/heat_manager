"""
Heat Manager — Pre-heat Engine (Phase 3)

Starts heating N minutes before a tracked person is expected to arrive home,
based on the HA `sensor.travel_time` or `sensor.proximity` approach.

Detection strategy (in priority order)
---------------------------------------
1. `sensor.<person>_travel_time_home` — if a travel_time sensor exists for
   the person, use its state (seconds) to predict arrival.
2. `device_tracker.<person>` + zone proximity — not implemented (future).
3. Scheduled preheat window — if no travel sensor exists, optionally fire
   preheat at a fixed time each day (not implemented, future).

For now only strategy 1 is implemented. If no travel_time sensor is found
for any person, the engine is a no-op.

Behaviour
---------
- When travel_time ≤ lead_time_min × 60 seconds:
    → Set all rooms currently in AWAY state to PRESET_SCHEDULE
    → Set room state to PRE_HEAT
    → Send optional notification
- Preheat state is cleared automatically when presence engine detects arrival
  (presence engine → _restore_all_schedule → sets state NORMAL).
- Only fires once per departure cycle (guarded by _preheat_armed flag).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_PREHEAT,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PREHEAT_LEAD_TIME_MIN,
    DEFAULT_PREHEAT_LEAD_TIME_MIN,
    PRESET_SCHEDULE,
    RoomState,
)
from .controller import guarded

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class PreheatEngine:
    """
    Monitors travel_time sensors and triggers pre-heating.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        # Maps person entity_id → travel_time sensor entity_id
        self._travel_sensors: dict[str, str] = {}
        # True when everyone is away and preheat hasn't fired yet this cycle
        self._preheat_armed: bool = False
        self._unsubs: list[Any] = []
        self._build_sensor_map()
        self._register_listeners()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _build_sensor_map(self) -> None:
        """
        For each tracked person, check if a travel_time sensor exists.
        Convention: sensor.<person_id>_travel_time_home
        e.g. person.flemming → sensor.flemming_travel_time_home
        """
        hass = self.coordinator.hass
        for person in self.coordinator.persons:
            if not person.get(CONF_PERSON_TRACKING, True):
                continue
            entity_id = person.get(CONF_PERSON_ENTITY, "")
            if not entity_id:
                continue
            person_id = entity_id.split(".")[-1]
            travel_sensor = f"sensor.{person_id}_travel_time_home"
            if hass.states.get(travel_sensor) is not None:
                self._travel_sensors[entity_id] = travel_sensor
                _LOGGER.debug(
                    "PreheatEngine: %s → %s", entity_id, travel_sensor
                )

        if not self._travel_sensors:
            _LOGGER.debug(
                "PreheatEngine: no travel_time sensors found — engine idle. "
                "Create sensor.<person>_travel_time_home to enable pre-heat."
            )

    def _register_listeners(self) -> None:
        if not self._travel_sensors:
            return
        hass = self.coordinator.hass

        # Listen for person state changes to arm/disarm preheat
        person_ids = list(self._travel_sensors.keys())
        self._unsubs.append(
            async_track_state_change_event(
                hass, person_ids, self._handle_person_change
            )
        )

        # Listen for travel_time changes to trigger preheat
        travel_sensor_ids = list(self._travel_sensors.values())
        self._unsubs.append(
            async_track_state_change_event(
                hass, travel_sensor_ids, self._handle_travel_time_change
            )
        )

    # ── Handlers ──────────────────────────────────────────────────────────────

    @callback
    def _handle_person_change(self, event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == "not_home":
            if not self._preheat_armed and not self.coordinator.someone_home():
                self._preheat_armed = True
                _LOGGER.debug("PreheatEngine: armed (everyone away)")
        elif new_state.state == "home":
            # Person arrived — disarm and clear PRE_HEAT states
            self._preheat_armed = False
            self._clear_preheat_states()

    @callback
    def _handle_travel_time_change(self, event: Any) -> None:
        if not self._preheat_armed:
            return
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        entity_id = event.data.get("entity_id", "")

        # Find which person this travel sensor belongs to
        person_id = next(
            (p for p, s in self._travel_sensors.items() if s == entity_id),
            None,
        )
        if not person_id:
            return

        # Get lead time for this person from config
        lead_time_sec = self._lead_time_seconds(person_id)

        try:
            travel_seconds = float(new_state.state)
        except (TypeError, ValueError):
            return

        if travel_seconds <= lead_time_sec:
            _LOGGER.info(
                "PreheatEngine: %s arriving in %.0f s — lead time %d s → starting preheat",
                person_id, travel_seconds, lead_time_sec,
            )
            self.coordinator.hass.async_create_task(
                self._start_preheat(person_id),
                name="heat_manager_preheat",
            )

    # ── Preheat execution ─────────────────────────────────────────────────────

    @guarded
    async def _start_preheat(self, person_id: str) -> None:
        """Set all AWAY rooms to schedule, mark as PRE_HEAT."""
        if not self._preheat_armed:
            return  # Already handled (e.g. person arrived in the meantime)

        hass = self.coordinator.hass
        rooms_preheated: list[str] = []

        for room in self.coordinator.rooms:
            room_name  = room.get("room_name", "")
            climate_id = room.get(CONF_CLIMATE_ENTITY, "")
            if not room_name or not climate_id:
                continue
            if self.coordinator.get_room_state(room_name) != RoomState.AWAY:
                continue  # Only preheat rooms currently in AWAY

            try:
                await hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {"entity_id": climate_id, "preset_mode": PRESET_SCHEDULE},
                    blocking=True,
                )
                self.coordinator.set_room_state(room_name, RoomState.PRE_HEAT)
                rooms_preheated.append(room_name)
                _LOGGER.info("Preheat: %s → schedule (PRE_HEAT)", room_name)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Preheat failed for %s: %s", room_name, err)

        # Disarm so we don't fire again this cycle
        self._preheat_armed = False

        if rooms_preheated and self.coordinator.config.get(CONF_NOTIFY_PREHEAT, True):
            person_name = person_id.split(".")[-1].capitalize()
            rooms_str   = ", ".join(rooms_preheated)
            await self._notify(
                f"Pre-heating started — {person_name} arriving soon. Rooms: {rooms_str}"
            )

    def _clear_preheat_states(self) -> None:
        """Called on arrival — presence engine handles actual schedule restore."""
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            if self.coordinator.get_room_state(room_name) == RoomState.PRE_HEAT:
                # Presence engine will restore to NORMAL — just log
                _LOGGER.debug("PreheatEngine: clearing PRE_HEAT for %s on arrival", room_name)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _lead_time_seconds(self, person_entity_id: str) -> float:
        """Return lead time in seconds for a person from their config."""
        for person in self.coordinator.persons:
            if person.get(CONF_PERSON_ENTITY) == person_entity_id:
                minutes = int(person.get(CONF_PREHEAT_LEAD_TIME_MIN, DEFAULT_PREHEAT_LEAD_TIME_MIN))
                return float(minutes * 60)
        return float(DEFAULT_PREHEAT_LEAD_TIME_MIN * 60)

    async def _notify(self, message: str) -> None:
        service = self.coordinator.config.get(CONF_NOTIFY_SERVICE, "")
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not service_name:
            return
        try:
            await self.coordinator.hass.services.async_call(
                domain, service_name,
                {"message": message, "title": "Heat Manager"},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Preheat notification failed: %s", err)

    async def async_tick(self) -> None:
        """No-op — all preheat logic is event-driven."""

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("PreheatEngine shut down")
