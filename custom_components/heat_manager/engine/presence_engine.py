"""
Heat Manager — Presence Engine

Phase 3: log_event() calls added at every significant state transition.
FIX: asyncio.ensure_future → hass.async_create_task throughout.
FIX B-429-RESTORE-RACE: _restore_lock serialises concurrent restore callers.
FIX B-LOG-RESTORE-SPAM: per-room NORMAL idempotency skips redundant API calls
  and prevents repeated WARNING log entries.
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
    CONF_TRV_TYPE,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_GRACE_NIGHT_MIN,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_START_HOUR,
    HVAC_OFF,
    PRESET_AWAY,
    PRESET_SCHEDULE,
    RoomState,
    TRV_TYPE_ZIGBEE,
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
        # Serialises concurrent _restore_all_schedule() callers (e.g. arrival
        # racing with window-close).  Without this, two callers iterate all
        # rooms simultaneously, producing N*rooms Netatmo API calls in quick
        # succession and reliably triggering 429 errors on setthermmode.
        self._restore_lock = asyncio.Lock()
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
        """
        Set all rooms to away / heating-off.

        TRV type routing:
        - netatmo (default): climate.set_preset_mode preset_mode=away
        - zigbee (Z2M):      climate.set_hvac_mode   hvac_mode=off
          Zigbee TRVs via Z2M expose hvac_modes=[auto, heat, off] but have
          no preset_mode concept.  Sending hvac_mode=off fully closes the
          valve, which is the correct away behaviour.
        """
        hass = self.coordinator.hass
        for room in self.coordinator.rooms:
            entity_id = room.get(CONF_CLIMATE_ENTITY, "")
            room_name = room.get("room_name", entity_id)
            if not entity_id:
                continue
            trv_type = room.get(CONF_TRV_TYPE, "netatmo")
            state = hass.states.get(entity_id)
            if trv_type == TRV_TYPE_ZIGBEE:
                # Skip if already off
                if state and state.state == HVAC_OFF:
                    continue
                try:
                    await hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": HVAC_OFF},
                        blocking=True,
                    )
                    self.coordinator.set_room_state(room_name, RoomState.AWAY)
                    self.coordinator.log_event(
                        f"Away mode — {room_name} (hvac_mode: off)", "Presence", "away"
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Failed to set away (Z2M) on %s: %s", entity_id, err)
            else:
                # Netatmo path — preset_mode: away
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
            # Netatmo API rate limit: 200 calls/10 min, burst sensitivity on setthermmode.
            # Small delay between rooms prevents 429 errors when all rooms are updated at once.
            await asyncio.sleep(0.6)

    @guarded
    async def _restore_all_schedule(self) -> None:
        """
        Restore all rooms to schedule / heating-on.

        TRV type routing:
        - netatmo (default): climate.set_preset_mode preset_mode=schedule
        - zigbee (Z2M):      climate.set_hvac_mode   hvac_mode=heat
          Z2M TRVs in hvac_mode=heat self-regulate to their current setpoint.

        Race-condition guard
        --------------------
        _restore_lock ensures only one restore sweep runs at a time.  Without
        it, concurrent callers (e.g. arrival event + window-close event firing
        within the same ~2-second window) each iterate all rooms, multiplying
        Netatmo API calls and triggering 429 rate-limit errors.

        Per-room idempotency
        --------------------
        Rooms already in NORMAL state skip the API call entirely.  This
        eliminates repeated WARNING logs when a second concurrent caller
        would otherwise attempt (and fail with 429) on rooms already restored.
        """
        if self._restore_lock.locked():
            _LOGGER.debug("_restore_all_schedule: skipping — restore already in progress")
            return
        async with self._restore_lock:
            hass = self.coordinator.hass
            any_restored = False
            for room in self.coordinator.rooms:
                entity_id = room.get(CONF_CLIMATE_ENTITY, "")
                room_name = room.get("room_name", entity_id)
                if not entity_id:
                    continue
                if self.coordinator.get_room_state(room_name) == RoomState.WINDOW_OPEN:
                    continue
                # Idempotency: skip rooms already in normal heating state.
                if self.coordinator.get_room_state(room_name) == RoomState.NORMAL:
                    _LOGGER.debug("_restore_all_schedule: %s already NORMAL — skipping", room_name)
                    continue
                trv_type = room.get(CONF_TRV_TYPE, "netatmo")
                try:
                    if trv_type == TRV_TYPE_ZIGBEE:
                        await hass.services.async_call(
                            "climate", "set_hvac_mode",
                            {"entity_id": entity_id, "hvac_mode": "heat"},
                            blocking=True,
                        )
                    else:
                        await hass.services.async_call(
                            "climate", "set_preset_mode",
                            {"entity_id": entity_id, "preset_mode": PRESET_SCHEDULE},
                            blocking=True,
                        )
                    self.coordinator.set_room_state(room_name, RoomState.NORMAL)
                    any_restored = True
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Failed to restore schedule on %s: %s", entity_id, err)
                # Netatmo API rate limit: stagger calls to avoid 429 on setthermmode.
                await asyncio.sleep(0.6)

            if any_restored:
                self.coordinator.log_event("Heating resumed — welcome home", "Presence", "normal")
                if self.coordinator.config.get(CONF_NOTIFY_PRESENCE, True):
                    await self._notify(title="Heat Manager", message="Heating resumed — welcome home.")

    @guarded
    async def force_room_on(self, room_name: str) -> None:
        """
        Force a specific room back to heating, bypassing window/away state.
        Routes service call based on trv_type.
        """
        entity_id = self.coordinator.get_climate_entity(room_name)
        if not entity_id:
            _LOGGER.warning("force_room_on: room '%s' not found", room_name)
            return
        # Find room config for trv_type
        room_cfg = next(
            (r for r in self.coordinator.rooms if r.get("room_name") == room_name), {}
        )
        trv_type = room_cfg.get(CONF_TRV_TYPE, "netatmo")
        try:
            if trv_type == TRV_TYPE_ZIGBEE:
                await self.coordinator.hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "heat"},
                    blocking=True,
                )
            else:
                await self.coordinator.hass.services.async_call(
                    "climate", "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": PRESET_SCHEDULE},
                    blocking=True,
                )
            self.coordinator.set_room_state(room_name, RoomState.NORMAL)
            _LOGGER.info("Force-on: %s → heating (%s)", entity_id, trv_type)
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
