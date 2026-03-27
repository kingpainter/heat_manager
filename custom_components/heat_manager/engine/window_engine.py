"""
Heat Manager — Window Engine

Phase 3: log_event() calls added at every significant state transition.
FIX: asyncio.ensure_future → hass.async_create_task throughout.
FIX: task references stored correctly so cancel works reliably.
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
    CONF_WINDOW_DELAY_MIN,
    CONF_WINDOW_SENSORS,
    DEFAULT_WINDOW_CLOSE_DELAY_MIN,
    DEFAULT_WINDOW_DELAY_MIN,
    DEFAULT_WINDOW_WARNING_MIN,
    PRESET_SCHEDULE,
    RoomState,
)
from .controller import guarded
from .pid_controller import PidController

if TYPE_CHECKING:
    from ..coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


class WindowEngine:
    """
    Per-room open window/door detection and heating suppression.

    Bug fixes
    ---------
    B1  Entity IDs come from config flow selector — no leading-dot risk.
    B2  async_tick() sends the 30-min escalation that the old YAML never sent.
    B3  Window-close restore checks presence before restoring schedule.
    """

    def __init__(self, coordinator: HeatManagerCoordinator) -> None:
        self.coordinator = coordinator
        self._window_opened_at: dict[str, datetime] = {}
        self._warning_sent: dict[str, bool] = {}
        self._open_tasks:  dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._close_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._sensor_to_room: dict[str, str] = {}
        self._sensor_to_away_temp: dict[str, float] = {}
        self._unsubs: list[Any] = []
        self._build_sensor_map()
        self._register_listeners()

    def _build_sensor_map(self) -> None:
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            away_temp = float(room.get(CONF_AWAY_TEMP_OVERRIDE, 10.0))
            for sensor in room.get(CONF_WINDOW_SENSORS, []):
                self._sensor_to_room[sensor]      = room_name
                self._sensor_to_away_temp[sensor] = away_temp
        _LOGGER.debug("Window engine tracking %d sensor(s)", len(self._sensor_to_room))

    def _register_listeners(self) -> None:
        sensors = list(self._sensor_to_room.keys())
        if not sensors:
            _LOGGER.debug("No window sensors configured — window engine idle")
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

        if new == "on" and old != "on":
            self.coordinator.hass.async_create_task(
                self._schedule_open(entity_id),
                name=f"heat_manager_window_open_{entity_id}",
            )
        elif new == "off" and old != "off":
            self.coordinator.hass.async_create_task(
                self._schedule_close(entity_id),
                name=f"heat_manager_window_close_{entity_id}",
            )

    async def _schedule_open(self, sensor_id: str) -> None:
        room_name = self._sensor_to_room.get(sensor_id)
        if not room_name:
            return
        self._cancel_task(self._close_tasks, room_name)
        self._cancel_task(self._open_tasks, room_name)
        delay = self._get_open_delay(sensor_id)
        _LOGGER.debug("Window opened in '%s' — waiting %d min", room_name, delay)
        self._open_tasks[room_name] = self.coordinator.hass.async_create_task(
            self._open_after_delay(sensor_id, room_name, delay),
            name=f"heat_manager_open_delay_{room_name}",
        )

    @guarded
    async def _open_after_delay(self, sensor_id: str, room_name: str, delay_min: int) -> None:
        try:
            await asyncio.sleep(delay_min * 60)
        except asyncio.CancelledError:
            return

        state = self.coordinator.hass.states.get(sensor_id)
        if not state or state.state != "on":
            return

        away_temp  = self._sensor_to_away_temp.get(sensor_id, 10.0)
        climate_id = self.coordinator.get_climate_entity(room_name)
        if not climate_id:
            _LOGGER.warning("No climate entity for room '%s'", room_name)
            return

        try:
            target_temp = self._window_open_setpoint(room_name, climate_id, away_temp)
            await self.coordinator.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": climate_id, "temperature": target_temp},
                blocking=True,
            )
            # Reset PID so integral debt doesn't accumulate while window is open
            pid = self.coordinator.get_pid(room_name)
            if pid:
                pid.reset()
            self.coordinator.set_room_state(room_name, RoomState.WINDOW_OPEN)
            self._window_opened_at[room_name] = utcnow()
            self._warning_sent[room_name]     = False
            _LOGGER.info("Window open in '%s' — set %.1f°C", room_name, target_temp)
            self.coordinator.log_event(
                f"Window open in {room_name} — heating to {target_temp:.0f}°C",
                "Window", "window_open",
            )
            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify(f"Window open — {room_name} set to {target_temp:.0f}°C")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to suppress heating in '%s': %s", room_name, err)

    async def _schedule_close(self, sensor_id: str) -> None:
        room_name = self._sensor_to_room.get(sensor_id)
        if not room_name:
            return
        self._cancel_task(self._open_tasks, room_name)
        self._cancel_task(self._close_tasks, room_name)
        self._close_tasks[room_name] = self.coordinator.hass.async_create_task(
            self._close_after_delay(sensor_id, room_name, DEFAULT_WINDOW_CLOSE_DELAY_MIN),
            name=f"heat_manager_close_delay_{room_name}",
        )

    @guarded
    async def _close_after_delay(self, sensor_id: str, room_name: str, delay_min: int) -> None:
        """B3 FIX: Only restore to schedule if someone is home."""
        try:
            await asyncio.sleep(delay_min * 60)
        except asyncio.CancelledError:
            return

        state = self.coordinator.hass.states.get(sensor_id)
        if state and state.state == "on":
            return

        self._window_opened_at.pop(room_name, None)
        self._warning_sent.pop(room_name, None)

        if not self.coordinator.someone_home():
            _LOGGER.info("Window closed in '%s' but nobody home — leaving AWAY", room_name)
            self.coordinator.log_event(
                f"Window closed in {room_name} — nobody home, staying away",
                "Window", "away",
            )
            self.coordinator.set_room_state(room_name, RoomState.AWAY)
            return

        climate_id = self.coordinator.get_climate_entity(room_name)
        if not climate_id:
            return

        try:
            await self.coordinator.hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": climate_id, "preset_mode": PRESET_SCHEDULE},
                blocking=True,
            )
            self.coordinator.set_room_state(room_name, RoomState.NORMAL)
            _LOGGER.info("Window closed in '%s' — restored to schedule", room_name)
            self.coordinator.log_event(
                f"Window closed in {room_name} — heating resumed",
                "Window", "normal",
            )
            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify(f"Window closed — {room_name} heating resumed")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to restore schedule in '%s': %s", room_name, err)

    async def async_tick(self) -> None:
        """B2 FIX: Send 30-min escalation warning."""
        if not self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
            return

        threshold = int(self.coordinator.config.get("window_warning_min", DEFAULT_WINDOW_WARNING_MIN))
        now = utcnow()

        for room_name, opened_at in list(self._window_opened_at.items()):
            if self._warning_sent.get(room_name, False):
                continue
            minutes_open = int((now - opened_at).total_seconds() / 60)
            if minutes_open >= threshold:
                _LOGGER.info("Window in '%s' open %d min — sending warning", room_name, minutes_open)
                self.coordinator.log_event(
                    f"Window open {minutes_open} min in {room_name}",
                    "30-min warning", "window_open",
                )
                await self._notify(
                    f"Window still open in {room_name} ({minutes_open} min) — heating suppressed"
                )
                self._warning_sent[room_name] = True

    def get_open_windows(self) -> list[str]:
        open_rooms: list[str] = []
        for sensor_id, room_name in self._sensor_to_room.items():
            state = self.coordinator.hass.states.get(sensor_id)
            if state and state.state == "on":
                open_rooms.append(room_name)
        return sorted(set(open_rooms))

    async def _notify(self, message: str) -> None:
        service = self.coordinator.config.get("notify_service", "")
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
            _LOGGER.warning("Window notification failed: %s", err)

    def _window_open_setpoint(
        self, room_name: str, climate_id: str, fallback_temp: float
    ) -> float:
        """
        Compute the setpoint to send when a window opens.

        If PID is enabled and a current_temperature reading is available,
        use power_to_setpoint(0) — which returns trv_min — as the floor.
        This is equivalent to the legacy away_temp_override but is now
        routed through the PID mapper so everything uses the same code path.

        If PID is disabled, fall back to the per-room away_temp_override.
        """
        if not self.coordinator.pid_enabled:
            return fallback_temp
        # Power = 0 → TRV minimum temperature (suppress heating without
        # completely cutting off frost protection)
        return PidController.power_to_setpoint(
            power=0.0,
            current_temp=self._get_current_temp(climate_id),
            trv_max=self.coordinator.trv_max_temp,
            trv_min=fallback_temp,   # honour per-room override as the floor
        )

    def _get_current_temp(self, climate_id: str) -> float:
        """Read current_temperature from the climate entity, fallback 20 °C."""
        state = self.coordinator.hass.states.get(climate_id)
        if state:
            try:
                return float(state.attributes.get("current_temperature", 20.0))
            except (TypeError, ValueError):
                pass
        return 20.0

    def _get_open_delay(self, sensor_id: str) -> int:
        room_name = self._sensor_to_room.get(sensor_id)
        for room in self.coordinator.rooms:
            if room.get("room_name") == room_name:
                return int(room.get(CONF_WINDOW_DELAY_MIN, DEFAULT_WINDOW_DELAY_MIN))
        return DEFAULT_WINDOW_DELAY_MIN

    def _cancel_task(self, task_dict: dict, key: str) -> None:
        task = task_dict.pop(key, None)
        if task and not task.done():
            task.cancel()

    async def async_shutdown(self) -> None:
        for task in list(self._open_tasks.values()) + list(self._close_tasks.values()):
            if not task.done():
                task.cancel()
        self._open_tasks.clear()
        self._close_tasks.clear()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("WindowEngine shut down")
