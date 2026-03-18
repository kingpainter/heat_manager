"""
Heat Manager — Window Engine

Handles per-room open window/door detection:
- Monitors configured binary sensors per room
- Drops room heating to the configured away temperature after a delay
- Restores schedule when the window closes (with presence check — fixes B3)
- Escalates to a warning notification after 30 min (fixes B2)
- Aggregates open-window state for the any_window_open binary sensor

Bug fixes implemented here
--------------------------
B2  The 30-minute open-window warning was defined as a trigger in the old
    YAML but had no corresponding choose-branch — it was dead code. It now
    fires a real escalation notification with urgency.

B3  When a window closes, the old YAML always restored to 'schedule' even
    if the house was in away mode because nobody was home. It now checks
    presence first — if nobody is home it leaves the room in AWAY state
    and lets the presence engine handle the restore later.

B1  The leading-dot typo in 'binary_sensor.lukas_vindue_contact' is fixed
    in config (entity IDs come from config flow, not hardcoded). A regression
    test verifies this cannot silently break again.
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
    CONF_AWAY_TEMP_OVERRIDE,
    CONF_CLIMATE_ENTITY,
    CONF_NOTIFY_WINDOWS,
    CONF_ROOMS,
    CONF_WINDOW_DELAY_MIN,
    CONF_WINDOW_SENSORS,
    DEFAULT_WINDOW_CLOSE_DELAY_MIN,
    DEFAULT_WINDOW_DELAY_MIN,
    DEFAULT_WINDOW_WARNING_MIN,
    PRESET_SCHEDULE,
    RoomState,
)
from .controller import guarded

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class WindowEngine:
    """
    Per-room open window detection and heating suppression.

    Each room has its own state tracking:
    - When did the window open?
    - Has the 30-min warning been sent?

    All state-changing methods are decorated with @guarded so they
    silently no-op when the controller is OFF or PAUSED.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator

        # Per-room open tracking: room_name → datetime window opened
        self._window_opened_at: dict[str, datetime] = {}

        # Per-room warning sent flag (reset when window closes)
        self._warning_sent: dict[str, bool] = {}

        # Pending delayed tasks: room_name → asyncio.Task
        self._open_tasks: dict[str, asyncio.Task] = {}
        self._close_tasks: dict[str, asyncio.Task] = {}

        # Sensor → room name mapping built from config
        self._sensor_to_room: dict[str, str] = {}
        self._sensor_to_away_temp: dict[str, float] = {}

        self._unsubs: list[Any] = []
        self._build_sensor_map()
        self._register_listeners()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _build_sensor_map(self) -> None:
        """Build lookups from sensor entity ID → room name and away temp."""
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            away_temp = float(room.get(CONF_AWAY_TEMP_OVERRIDE, 10.0))
            for sensor in room.get(CONF_WINDOW_SENSORS, []):
                self._sensor_to_room[sensor] = room_name
                self._sensor_to_away_temp[sensor] = away_temp

        _LOGGER.debug(
            "Window engine tracking %d sensor(s): %s",
            len(self._sensor_to_room),
            list(self._sensor_to_room.keys()),
        )

    def _register_listeners(self) -> None:
        """Subscribe to all configured window/door sensor state changes."""
        sensors = list(self._sensor_to_room.keys())
        if not sensors:
            _LOGGER.debug("No window sensors configured — window engine idle")
            return

        self._unsubs.append(
            async_track_state_change_event(
                self.coordinator.hass, sensors, self._handle_sensor_change
            )
        )

    # ── State change handler ──────────────────────────────────────────────────

    @callback
    def _handle_sensor_change(self, event: Any) -> None:
        """Dispatches to open or close handler based on new sensor state."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        entity_id = event.data.get("entity_id", "")
        new = new_state.state
        old = old_state.state if old_state else None

        if new == "on" and old != "on":
            asyncio.ensure_future(self._schedule_open(entity_id))
        elif new == "off" and old != "off":
            asyncio.ensure_future(self._schedule_close(entity_id))

    # ── Window opened ─────────────────────────────────────────────────────────

    async def _schedule_open(self, sensor_id: str) -> None:
        """
        Wait for the configured open delay, then suppress heating in the room.
        Any pending close task for this room is cancelled first.
        """
        room_name = self._sensor_to_room.get(sensor_id)
        if not room_name:
            return

        # Cancel any pending close task for this room
        close_task = self._close_tasks.pop(room_name, None)
        if close_task and not close_task.done():
            close_task.cancel()

        # Cancel any existing open task (sensor bounced)
        existing = self._open_tasks.pop(room_name, None)
        if existing and not existing.done():
            existing.cancel()

        delay = self._get_open_delay(sensor_id)
        _LOGGER.debug(
            "Window opened in '%s' — waiting %d min before acting", room_name, delay
        )

        task = asyncio.ensure_future(self._open_after_delay(sensor_id, room_name, delay))
        self._open_tasks[room_name] = task

    @guarded
    async def _open_after_delay(
        self, sensor_id: str, room_name: str, delay_min: int
    ) -> None:
        """Apply heating suppression after the open delay expires."""
        try:
            await asyncio.sleep(delay_min * 60)
        except asyncio.CancelledError:
            return

        # Verify sensor is still open
        state = self.coordinator.hass.states.get(sensor_id)
        if not state or state.state != "on":
            return

        away_temp = self._sensor_to_away_temp.get(sensor_id, 10.0)
        climate_id = self.coordinator.get_climate_entity(room_name)

        if not climate_id:
            _LOGGER.warning("No climate entity for room '%s'", room_name)
            return

        try:
            await self.coordinator.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": climate_id, "temperature": away_temp},
                blocking=True,
            )
            self.coordinator.set_room_state(room_name, RoomState.WINDOW_OPEN)
            self._window_opened_at[room_name] = utcnow()
            self._warning_sent[room_name] = False

            _LOGGER.info(
                "Window open in '%s' — set %.1f°C on %s",
                room_name, away_temp, climate_id,
            )

            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify_open(room_name, away_temp)

        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to suppress heating in '%s': %s", room_name, err
            )

    # ── Window closed ─────────────────────────────────────────────────────────

    async def _schedule_close(self, sensor_id: str) -> None:
        """Wait for the close delay, then decide whether to restore schedule."""
        room_name = self._sensor_to_room.get(sensor_id)
        if not room_name:
            return

        # Cancel any pending open task
        open_task = self._open_tasks.pop(room_name, None)
        if open_task and not open_task.done():
            open_task.cancel()

        existing = self._close_tasks.pop(room_name, None)
        if existing and not existing.done():
            existing.cancel()

        close_delay = DEFAULT_WINDOW_CLOSE_DELAY_MIN
        _LOGGER.debug(
            "Window closed in '%s' — waiting %d min before restoring",
            room_name, close_delay,
        )

        task = asyncio.ensure_future(
            self._close_after_delay(sensor_id, room_name, close_delay)
        )
        self._close_tasks[room_name] = task

    @guarded
    async def _close_after_delay(
        self, sensor_id: str, room_name: str, delay_min: int
    ) -> None:
        """
        Restore heating after the close delay.

        B3 FIX: Only restore to schedule if someone is home.
        If nobody is home, leave the room in AWAY state — the presence
        engine will restore it when someone arrives.
        """
        try:
            await asyncio.sleep(delay_min * 60)
        except asyncio.CancelledError:
            return

        # Verify sensor is still closed
        state = self.coordinator.hass.states.get(sensor_id)
        if state and state.state == "on":
            _LOGGER.debug(
                "Window in '%s' re-opened before close delay elapsed — aborting restore",
                room_name,
            )
            return

        # Clear window tracking for this room
        self._window_opened_at.pop(room_name, None)
        self._warning_sent.pop(room_name, None)

        # B3 FIX: Check presence before restoring
        if not self.coordinator.someone_home():
            _LOGGER.info(
                "Window closed in '%s' but nobody home — leaving in AWAY state",
                room_name,
            )
            self.coordinator.set_room_state(room_name, RoomState.AWAY)
            return

        climate_id = self.coordinator.get_climate_entity(room_name)
        if not climate_id:
            return

        try:
            await self.coordinator.hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": climate_id, "preset_mode": PRESET_SCHEDULE},
                blocking=True,
            )
            self.coordinator.set_room_state(room_name, RoomState.NORMAL)
            _LOGGER.info(
                "Window closed in '%s' — restored to schedule", room_name
            )

            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify_closed(room_name)

        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to restore schedule in '%s': %s", room_name, err
            )

    # ── 30-minute warning (fixes B2) ──────────────────────────────────────────

    async def async_tick(self) -> None:
        """
        Called every SCAN_INTERVAL_SECONDS by the coordinator.
        Checks for rooms where the window has been open 30+ minutes and
        sends an escalation warning if not already sent.

        B2 FIX: The old YAML defined a 30-min trigger but had no handler.
        This tick implements the missing escalation.
        """
        warning_threshold = int(
            self.coordinator.config.get(
                "window_warning_min", DEFAULT_WINDOW_WARNING_MIN
            )
        )

        if not self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
            return

        now = utcnow()
        for room_name, opened_at in list(self._window_opened_at.items()):
            if self._warning_sent.get(room_name, False):
                continue
            minutes_open = (now - opened_at).total_seconds() / 60
            if minutes_open >= warning_threshold:
                _LOGGER.info(
                    "Window in '%s' open for %.0f min — sending warning",
                    room_name, minutes_open,
                )
                await self._notify_warning(room_name, int(minutes_open))
                self._warning_sent[room_name] = True

    # ── Open window list helper ───────────────────────────────────────────────

    def get_open_windows(self) -> list[str]:
        """
        Return a list of room names where a window sensor is currently open.
        Used by the VIEW_WINDOWS notification action handler.
        """
        open_rooms: list[str] = []
        for sensor_id, room_name in self._sensor_to_room.items():
            state = self.coordinator.hass.states.get(sensor_id)
            if state and state.state == "on":
                open_rooms.append(room_name)
        return sorted(set(open_rooms))

    # ── Notifications ─────────────────────────────────────────────────────────

    async def _notify_open(self, room_name: str, temp: float) -> None:
        await self._notify(
            f"Window open — {room_name} set to {temp:.0f}°C"
        )

    async def _notify_closed(self, room_name: str) -> None:
        await self._notify(
            f"Window closed — {room_name} heating resumed"
        )

    async def _notify_warning(self, room_name: str, minutes: int) -> None:
        """B2 FIX: escalation notification after 30 min open window."""
        await self._notify(
            f"Window still open in {room_name} ({minutes} min) — heating suppressed"
        )

    async def _notify(self, message: str) -> None:
        service = self.coordinator.config.get("notify_service", "")
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not service_name:
            return
        try:
            await self.coordinator.hass.services.async_call(
                domain,
                service_name,
                {"message": message, "title": "Heat Manager"},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Window notification failed: %s", err)

    # ── Config helpers ────────────────────────────────────────────────────────

    def _get_open_delay(self, sensor_id: str) -> int:
        """Return the open delay in minutes for a given sensor's room."""
        room_name = self._sensor_to_room.get(sensor_id)
        for room in self.coordinator.rooms:
            if room.get("room_name") == room_name:
                return int(room.get(CONF_WINDOW_DELAY_MIN, DEFAULT_WINDOW_DELAY_MIN))
        return DEFAULT_WINDOW_DELAY_MIN

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        """Cancel all pending tasks and unsubscribe listeners."""
        for task in list(self._open_tasks.values()) + list(self._close_tasks.values()):
            if not task.done():
                task.cancel()
        self._open_tasks.clear()
        self._close_tasks.clear()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("WindowEngine shut down")
