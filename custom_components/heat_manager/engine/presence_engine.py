"""
Heat Manager — Presence Engine

Phase 3: log_event() calls added at every significant state transition.
FIX: asyncio.ensure_future → hass.async_create_task throughout.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.dt import utcnow

from ..const import (
    ACTION_DISMISS,
    ACTION_FORCE_HEATING_ON,
    ACTION_VIEW_WINDOWS,
    CONF_ALARM_PANEL,
    CONF_CLIMATE_ENTITY,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_NIGHT_END_HOUR,
    CONF_NIGHT_START_HOUR,
    CONF_NOTIFY_PRESENCE,
    CONF_NOTIFY_SERVICE,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_GRACE_NIGHT_MIN,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_START_HOUR,
    PRESET_AWAY,
    PRESET_SCHEDULE,
    RoomState,
)
from .controller import guarded

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class PresenceEngine:
    """
    Monitors person and alarm entities, applies grace periods, and
    controls climate preset modes based on who is home.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._lock = asyncio.Lock()
        self._all_left_at: datetime | None = None
        self._grace_timer_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._unsubs: list[Any] = []
        self._register_listeners()

    # ── Listener registration ─────────────────────────────────────────────────

    def _register_listeners(self) -> None:
        hass = self.coordinator.hass

        person_entity_ids = [
            p[CONF_PERSON_ENTITY]
            for p in self.coordinator.persons
            if p.get(CONF_PERSON_TRACKING, True) and p.get(CONF_PERSON_ENTITY)
        ]

        if person_entity_ids:
            self._unsubs.append(
                async_track_state_change_event(
                    hass, person_entity_ids, self._handle_person_change
                )
            )
            _LOGGER.debug("Tracking persons: %s", person_entity_ids)

        alarm = self.coordinator.alarm_panel
        if alarm:
            self._unsubs.append(
                async_track_state_change_event(
                    hass, [alarm], self._handle_alarm_change
                )
            )
            _LOGGER.debug("Tracking alarm panel: %s", alarm)

    # ── Person state changes ──────────────────────────────────────────────────

    @callback
    def _handle_person_change(self, event: Any) -> None:
        self.coordinator.hass.async_create_task(
            self._async_handle_person_change(event),
            name="heat_manager_person_change",
        )

    @guarded
    async def _async_handle_person_change(self, event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        entity_id = event.data.get("entity_id", "")
        _LOGGER.debug("Person change: %s → %s", entity_id, new_state.state)

        if new_state.state == "home":
            await self._handle_arrival()
        elif new_state.state == "not_home":
            await self._handle_departure()

    async def _handle_arrival(self) -> None:
        async with self._lock:
            self._cancel_grace_timer()
            self._all_left_at = None

        if self.coordinator.any_window_open():
            await self._notify_windows_blocking_heat()
        else:
            await self._restore_all_schedule()

    async def _handle_departure(self) -> None:
        async with self._lock:
            if self.coordinator.someone_home():
                return
            if self._all_left_at is not None:
                return
            self._all_left_at = utcnow()
            grace = self._grace_period_minutes()
            _LOGGER.info("Everyone left — starting %d min grace period", grace)
            self._grace_timer_task = self.coordinator.hass.async_create_task(
                self._grace_period_task(grace),
                name="heat_manager_grace_timer",
            )

    async def _grace_period_task(self, minutes: int) -> None:
        try:
            await asyncio.sleep(minutes * 60)
        except asyncio.CancelledError:
            return
        if not self.coordinator.someone_home():
            await self._set_all_away()
            self.coordinator.log_event(
                f"Away mode — nobody home for {minutes} min",
                "Grace period",
                "away",
            )
            if self.coordinator.config.get(CONF_NOTIFY_PRESENCE, True):
                await self._notify(
                    title="Heat Manager",
                    message=f"Heating off — nobody home for {minutes} min.",
                )

    # ── Alarm changes (fixes B4) ──────────────────────────────────────────────

    @callback
    def _handle_alarm_change(self, event: Any) -> None:
        self.coordinator.hass.async_create_task(
            self._async_handle_alarm_change(event),
            name="heat_manager_alarm_change",
        )

    @guarded
    async def _async_handle_alarm_change(self, event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        alarm_state = new_state.state
        _LOGGER.debug("Alarm state: %s", alarm_state)

        if alarm_state == "armed_away":
            async with self._lock:
                self._cancel_grace_timer()
            await self._set_all_away()
            self.coordinator.log_event("Heating off — alarm armed", "Alarm", "away")
            if self.coordinator.config.get(CONF_NOTIFY_PRESENCE, True):
                await self._notify(
                    title="Heat Manager",
                    message="Heating off — alarm armed.",
                )

        elif alarm_state in ("disarmed", "armed_home"):
            # B4 FIX: re-evaluate presence on alarm disarm
            if self.coordinator.someone_home():
                if self.coordinator.any_window_open():
                    await self._notify_windows_blocking_heat()
                else:
                    self.coordinator.log_event(
                        "Heating resumed — alarm disarmed", "Alarm", "normal"
                    )
                    await self._restore_all_schedule()
                    if self.coordinator.config.get(CONF_NOTIFY_PRESENCE, True):
                        await self._notify(
                            title="Heat Manager",
                            message="Heating resumed — alarm disarmed, someone home.",
                        )

    # ── Climate control ───────────────────────────────────────────────────────

    @guarded
    async def _set_all_away(self) -> None:
        hass = self.coordinator.hass
        for room in self.coordinator.rooms:
            entity_id = room.get(CONF_CLIMATE_ENTITY, "")
            room_name = room.get("room_name", entity_id)
            if not entity_id:
                continue
            state = hass.states.get(entity_id)
            if state and state.attributes.get("preset_mode") == PRESET_AWAY:
                continue
            try:
                await hass.services.async_call(
                    "climate", "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": PRESET_AWAY},
                    blocking=True,
                )
                self.coordinator.set_room_state(room_name, RoomState.AWAY)
                self.coordinator.log_event(
                    f"Away mode — {room_name}", "Presence", "away"
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to set away on %s: %s", entity_id, err)

    @guarded
    async def _restore_all_schedule(self) -> None:
        hass = self.coordinator.hass
        for room in self.coordinator.rooms:
            entity_id = room.get(CONF_CLIMATE_ENTITY, "")
            room_name = room.get("room_name", entity_id)
            if not entity_id:
                continue
            if self.coordinator.get_room_state(room_name) == RoomState.WINDOW_OPEN:
                continue
            try:
                await hass.services.async_call(
                    "climate", "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": PRESET_SCHEDULE},
                    blocking=True,
                )
                self.coordinator.set_room_state(room_name, RoomState.NORMAL)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to restore schedule on %s: %s", entity_id, err)

        self.coordinator.log_event("Heating resumed — welcome home", "Presence", "normal")
        if self.coordinator.config.get(CONF_NOTIFY_PRESENCE, True):
            await self._notify(title="Heat Manager", message="Heating resumed — welcome home.")

    @guarded
    async def force_room_on(self, room_name: str) -> None:
        entity_id = self.coordinator.get_climate_entity(room_name)
        if not entity_id:
            _LOGGER.warning("force_room_on: room '%s' not found", room_name)
            return
        try:
            await self.coordinator.hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": PRESET_SCHEDULE},
                blocking=True,
            )
            self.coordinator.set_room_state(room_name, RoomState.NORMAL)
            _LOGGER.info("Force-on: %s → schedule", entity_id)
            window_warn = " (windows still open — may be costly!)" if self.coordinator.any_window_open() else ""
            self.coordinator.log_event(
                f"Heating forced on for {room_name}{window_warn}", "Override", "override"
            )
            await self._notify(
                title="Heat Manager",
                message=f"Heating forced on for {room_name}{window_warn}",
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("force_room_on failed for %s: %s", room_name, err)

    # ── Notifications ─────────────────────────────────────────────────────────

    async def _notify_windows_blocking_heat(self) -> None:
        if not self.coordinator.config.get(CONF_NOTIFY_PRESENCE, True):
            return
        await self._notify(
            title="Heat Manager",
            message="Heating not resumed — one or more windows are open.",
            actions=[
                {"action": ACTION_FORCE_HEATING_ON, "title": "Heat anyway"},
                {"action": ACTION_VIEW_WINDOWS,      "title": "Show open windows"},
                {"action": ACTION_DISMISS,           "title": "OK"},
            ],
        )

    async def _notify(self, title: str, message: str, actions: list[dict] | None = None) -> None:
        service = self.coordinator.config.get(CONF_NOTIFY_SERVICE, "")
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not service_name:
            _LOGGER.warning("Invalid notify service: %s", service)
            return
        data: dict[str, Any] = {"message": message, "title": title}
        if actions:
            data["data"] = {"actions": actions}
        try:
            await self.coordinator.hass.services.async_call(
                domain, service_name, data, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Notification failed (%s): %s", service, err)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _grace_period_minutes(self) -> int:
        hour = utcnow().hour
        night_start = self.coordinator.config.get(CONF_NIGHT_START_HOUR, DEFAULT_NIGHT_START_HOUR)
        night_end   = self.coordinator.config.get(CONF_NIGHT_END_HOUR,   DEFAULT_NIGHT_END_HOUR)
        is_night    = hour >= night_start or hour < night_end
        key     = CONF_GRACE_NIGHT_MIN if is_night else CONF_GRACE_DAY_MIN
        default = DEFAULT_GRACE_NIGHT_MIN if is_night else DEFAULT_GRACE_DAY_MIN
        return int(self.coordinator.config.get(key, default))

    def _cancel_grace_timer(self) -> None:
        if self._grace_timer_task and not self._grace_timer_task.done():
            self._grace_timer_task.cancel()
            _LOGGER.debug("Grace timer cancelled")
        self._grace_timer_task = None
        self._all_left_at = None

    async def async_tick(self) -> None:
        """No-op — all presence logic is event-driven."""

    async def async_shutdown(self) -> None:
        self._cancel_grace_timer()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("PresenceEngine shut down")
