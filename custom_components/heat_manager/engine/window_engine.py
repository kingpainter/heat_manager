"""
Heat Manager — Window Engine

Phase 3: log_event() calls added at every significant state transition.
FIX: asyncio.ensure_future → hass.async_create_task throughout.
FIX: task references stored correctly so cancel works reliably.

v0.2.9: CO₂-aware notifications.
  When CONF_CO2_SENSOR is configured for a room, window open/close messages
  and the 30-min escalation warning include the current CO₂ level and a
  brief contextual label so the user immediately understands whether the
  open window is doing useful work or just losing heat.

2026-09-11 restart-noise fix: a window/door sensor's platform fires a
  state_changed event the first time its real state becomes known again
  after an HA restart/reload (old_state None/"unknown"/"unavailable"),
  even when nothing physically opened or closed. Before this fix, every
  restart produced a false "Window closed in <room> — heating resumed" log
  line (plus a real, unnecessary climate.set_preset_mode call) for every
  already-closed window. _handle_sensor_change() now only reacts to a
  genuine flip between two KNOWN states; a window already open at startup
  is instead picked up explicitly by the new _check_initial_windows(),
  which reads the live sensor state directly. See presence_engine.py for
  the matching fix on the person/alarm side.
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
    CONF_CLIMATE_ENTITY,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_WINDOW_WARNING_30,
    CONF_NOTIFY_WINDOWS,
    CONF_TRV_TYPE,
    CONF_WINDOW_DELAY_DEFAULT_MIN,
    CONF_WINDOW_OFF_TEMP,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_WARNING_MIN,
    DEFAULT_CO2_VENTILATION_THRESHOLD,
    DEFAULT_WINDOW_CLOSE_DELAY_MIN,
    DEFAULT_WINDOW_DELAY_DEFAULT_MIN,
    DEFAULT_WINDOW_DELAY_WIND_MIN,
    DEFAULT_WINDOW_OFF_TEMP,
    DEFAULT_WINDOW_WARNING_MIN,
    PRESET_SCHEDULE,
    TRV_TYPE_ZIGBEE,
    WIND_FAST_MS,
    RoomState,
)
from .controller import guarded

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
        self._open_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._close_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._sensor_to_room: dict[str, str] = {}
        self._unsubs: list[Any] = []
        self._build_sensor_map()
        self._register_listeners()
        self._check_initial_windows()

    def _build_sensor_map(self) -> None:
        # v0.33.0: the setpoint written on window-open is now one global
        # value (CONF_WINDOW_OFF_TEMP, read fresh at write time in
        # _open_after_delay()) instead of a per-sensor snapshot taken here —
        # see that method's comment for why it's no longer per-room.
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            for sensor in room.get(CONF_WINDOW_SENSORS, []):
                self._sensor_to_room[sensor] = room_name
        _LOGGER.debug("Window engine tracking %d sensor(s)", len(self._sensor_to_room))

    # ── "Vindue vs dør" labeling (2026-09-15) ────────────────────────
    #
    # Purely cosmetic: which log/notification wording a sensor's own
    # open/close events use, sourced from CONF_DOOR_STYLED_SENSORS. Every
    # other behaviour (grace period, off-temp write, 30-min warning,
    # RoomState.WINDOW_OPEN, the "window_open"/"normal"/"away" event_type
    # used for history filtering) is IDENTICAL regardless — only the
    # human-readable label/category string changes. See const.py's
    # CONF_DOOR_STYLED_SENSORS for the full rationale (a balcony door still
    # loses heat exactly like a window; only its name in the log differs).

    def _sensor_label(self, room_name: str, sensor_id: str) -> str:
        """"Door" or "Window" for a specific sensor that just triggered an
        event — the common case, since every open/close handler already
        knows which sensor fired."""
        door_styled = self.coordinator.get_room_door_styled_sensors(room_name)
        return "Door" if sensor_id in door_styled else "Window"

    def _room_label(self, room_name: str) -> str:
        """Room-level fallback for the 30-min warning, which iterates by
        room rather than by sensor: "Door" only if EVERY window sensor
        configured for this room is door-styled, else "Window" (the safer
        default for a room mixing both)."""
        for room in self.coordinator.rooms:
            if room.get("room_name") != room_name:
                continue
            sensors = room.get(CONF_WINDOW_SENSORS, []) or []
            door_styled = set(self.coordinator.get_room_door_styled_sensors(room_name))
            if sensors and all(s in door_styled for s in sensors):
                return "Door"
            break
        return "Window"

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

        # 2026-09-11 restart-noise fix: when this sensor's platform
        # re-establishes itself (HA restart, integration reload, a brief
        # radio dropout), HA fires a state_changed event the first time its
        # real state becomes known again — with old_state None/"unknown"/
        # "unavailable" — even though nothing physically opened or closed.
        # Before this guard, EVERY restart produced a false "Window closed
        # in <room> — heating resumed" log line (and a real climate call!)
        # for every already-closed window, because `old != "off"` is true
        # for "unavailable" too. Only a genuine flip between two KNOWN
        # states counts as a real event now. Windows already open at
        # startup are instead picked up explicitly by
        # _check_initial_windows(), which reads the live sensor state
        # directly rather than relying on this artifact event.
        if old not in ("on", "off") or old == new:
            return

        if new == "on":
            self.coordinator.hass.async_create_task(
                self._schedule_open(entity_id),
                name=f"heat_manager_window_open_{entity_id}",
            )
        else:
            self.coordinator.hass.async_create_task(
                self._schedule_close(entity_id),
                name=f"heat_manager_window_close_{entity_id}",
            )

    def _check_initial_windows(self) -> None:
        """Sync room state with any window already open at startup.

        Mirrors PresenceEngine._check_initial_presence() (B11): the listener
        above only fires on FUTURE changes and — as of the restart-noise fix
        just above — now deliberately ignores the artifact state_changed
        event HA emits when a sensor's real state first becomes known again
        after a restart. Without this check, a window that was already open
        before the restart would silently go unnoticed and heating would
        resume in a room that's supposed to stay suppressed. Goes through
        the normal _schedule_open() path (same open-delay as any other real
        open, same eventual log line) rather than acting immediately, so a
        window that's genuinely still open gets exactly the same treatment
        — and the same visible event — it would have gotten without a
        restart in between.
        """
        for sensor_id, room_name in self._sensor_to_room.items():
            state = self.coordinator.hass.states.get(sensor_id)
            if state and state.state == "on":
                _LOGGER.debug(
                    "WindowEngine: '%s' already open at startup — scheduling suppression",
                    room_name,
                )
                self.coordinator.hass.async_create_task(
                    self._schedule_open(sensor_id),
                    name=f"heat_manager_window_open_startup_{sensor_id}",
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
    async def _open_after_delay(
        self, sensor_id: str, room_name: str, delay_min: int
    ) -> None:
        try:
            await asyncio.sleep(delay_min * 60)
        except asyncio.CancelledError:
            return

        state = self.coordinator.hass.states.get(sensor_id)
        if not state or state.state != "on":
            return

        # v0.33.0: dedicated, global "heat is off" temperature — deliberately
        # NOT away_temp_override (that value now only floors the PID's own
        # idle output and the night/wake setback; see const.py's
        # CONF_WINDOW_OFF_TEMP comment for why they were split apart).
        off_temp = self.coordinator.config.get(
            CONF_WINDOW_OFF_TEMP, DEFAULT_WINDOW_OFF_TEMP
        )
        climate_id = self.coordinator.get_climate_entity(room_name)
        if not climate_id:
            # 2026-09-11 (monitoring-only rooms): a room with no TRV at all
            # (e.g. "Gang", a hallway) can still have a window/exterior-door
            # sensor configured — Flemming's front door to the stairwell is
            # exactly this case: opening it lets outside air into Gang just
            # like a real window, even though there's no TRV there to turn
            # down. Before this branch, hitting `if not climate_id` above
            # returned immediately with only a backend warning — no
            # set_room_state(), no log_event(), no notification — so the
            # door opening was invisible everywhere Flemming actually looks.
            # There's nothing to heat-suppress, so just record the state and
            # make it visible, exactly like a real window open — no
            # climate.set_temperature call, because there's no TRV to call it on.
            self.coordinator.set_room_state(room_name, RoomState.WINDOW_OPEN)
            self._window_opened_at[room_name] = utcnow()
            self._warning_sent[room_name] = False
            label = self._sensor_label(room_name, sensor_id)
            log_msg = f"{label} open in {room_name} (no TRV — monitoring only)"
            _LOGGER.info(log_msg)
            self.coordinator.log_event(log_msg, label, "window_open")
            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify(f"{label} open — {room_name}")
            return

        # H-1: write setpoint via preferred local entity (HomeKit if
        # available) — B18: fan the same setpoint out to every physical TRV
        # configured for this room, not just the primary.
        write_entities = self.coordinator.get_room_write_entities(room_name) or [
            self.coordinator.get_write_entity(room_name) or climate_id
        ]

        try:
            # v0.33.0: was routed through PidController.power_to_setpoint(
            # power=0.0, trv_min=off_temp) — but power<=0.0 always short-
            # circuits to trv_min unconditionally (see pid_controller.py), so
            # that call only ever returned off_temp itself. Simplified to a
            # direct assignment; behaviour is unchanged.
            target_temp = off_temp
            for write_id in write_entities:
                await self.coordinator.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": write_id, "temperature": target_temp},
                    blocking=True,
                )
            pid = self.coordinator.get_pid(room_name)
            if pid:
                pid.reset()
            self.coordinator.set_room_state(room_name, RoomState.WINDOW_OPEN)
            self._window_opened_at[room_name] = utcnow()
            self._warning_sent[room_name] = False

            # ── CO₂-aware open notification ───────────────────────────────
            co2_ppm = self.coordinator.get_room_co2(room_name)
            co2_label = self._co2_context_label(co2_ppm, room_name)
            via = "HomeKit" if any(w != climate_id for w in write_entities) else "cloud"
            label = self._sensor_label(room_name, sensor_id)
            log_msg = (
                f"{label} open in {room_name} — heating to {target_temp:.0f}°C"
                f" (via {via})"
            )
            notif_msg = (
                f"{label} open — {room_name} set to {target_temp:.0f}°C{co2_label}"
            )

            _LOGGER.info(
                "%s%s", log_msg, f"  CO₂: {co2_ppm:.0f} ppm" if co2_ppm else ""
            )
            self.coordinator.log_event(log_msg, label, "window_open")

            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify(notif_msg)
        # broad-except-rationale: one entity failing must not abort the others in this loop
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to suppress heating in '%s': %s", room_name, err)

    async def _schedule_close(self, sensor_id: str) -> None:
        room_name = self._sensor_to_room.get(sensor_id)
        if not room_name:
            return
        # B19 FIX: A room can have more than one window/door sensor. If
        # another sensor in this room is still open, this sensor's close
        # event must not touch the room's pending open-suppression task —
        # cancelling it here left the room with neither a pending open task
        # nor active suppression, so heating was never turned down even
        # though a window remained open (mirror-image bug to B16, which
        # protects the restore side but left this side unguarded).
        if not self._all_room_sensors_closed(room_name):
            _LOGGER.debug(
                "Sensor '%s' closed in '%s' but another sensor is still"
                " open — leaving window-open suppression untouched",
                sensor_id,
                room_name,
            )
            return
        self._cancel_task(self._open_tasks, room_name)
        self._cancel_task(self._close_tasks, room_name)
        self._close_tasks[room_name] = self.coordinator.hass.async_create_task(
            self._close_after_delay(
                sensor_id, room_name, DEFAULT_WINDOW_CLOSE_DELAY_MIN
            ),
            name=f"heat_manager_close_delay_{room_name}",
        )

    @guarded
    async def _close_after_delay(
        self, sensor_id: str, room_name: str, delay_min: int
    ) -> None:
        """B3 FIX: Only restore to schedule if someone is home.

        B16 FIX: A room can have more than one window/door sensor. Only the
        sensor that just triggered this close event was being checked here,
        so if room X has sensor A and B open, and A closes first, heating
        would be restored even though B is still open. Now every sensor
        configured for this room must report closed before we proceed.
        """
        try:
            await asyncio.sleep(delay_min * 60)
        except asyncio.CancelledError:
            return

        if not self._all_room_sensors_closed(room_name):
            return

        self._window_opened_at.pop(room_name, None)
        self._warning_sent.pop(room_name, None)

        if not self.coordinator.someone_home():
            label = self._sensor_label(room_name, sensor_id)
            _LOGGER.info(
                "%s closed in '%s' but nobody home — leaving AWAY", label, room_name
            )
            self.coordinator.log_event(
                f"{label} closed in {room_name} — nobody home, staying away",
                label,
                "away",
            )
            self.coordinator.set_room_state(room_name, RoomState.AWAY)
            return

        # S-3 FIX: route restore by TRV type — Zigbee uses hvac_mode, Netatmo
        # uses preset. B18: every physical TRV in the room is restored, each
        # routed by its own trv_type, using its own raw climate_entity (no
        # HomeKit preference here — matches the pre-existing single-TRV
        # policy of this method exactly).
        trvs = self.coordinator.get_room_trvs(room_name)
        if not trvs:
            # 2026-09-11 (monitoring-only rooms): mirror of the matching
            # branch in _open_after_delay() — a room with no TRV at all has
            # nothing to restore to schedule, but the door/window closing is
            # still a real event that should be visible, not silently
            # dropped. See that method's comment for the full rationale
            # (Flemming's "Gang" front-door case).
            self.coordinator.set_room_state(room_name, RoomState.NORMAL)
            label = self._sensor_label(room_name, sensor_id)
            log_msg = f"{label} closed in {room_name} (no TRV — monitoring only)"
            _LOGGER.info(log_msg)
            self.coordinator.log_event(log_msg, label, "normal")
            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify(f"{label} closed — {room_name}")
            return

        # 2026-09 429 fix: this method runs as its own independent
        # async_create_task() per room (see _schedule_close's caller), so
        # several rooms' windows closing within the same debounce window
        # each fired their Netatmo calls with zero pacing and no
        # cross-task coordination — unlike presence_engine.py's restore
        # path, which at least serialised itself internally. Both gaps are
        # now closed the same way: async_call_climate_service() takes a
        # coordinator-wide lock for any cloud-bound call, so this task's
        # calls queue up behind (and pace against) every other engine's,
        # not just its own.
        room_restored = False
        delay = self.coordinator.needs_cloud_delay(room_name)
        for trv in trvs:
            entity_id = trv.get(CONF_CLIMATE_ENTITY, "")
            if not entity_id:
                continue
            trv_type = trv.get(CONF_TRV_TYPE, "netatmo")
            try:
                if trv_type == TRV_TYPE_ZIGBEE:
                    await self.coordinator.async_call_climate_service(
                        "set_hvac_mode",
                        entity_id,
                        {"hvac_mode": "heat"},
                        needs_delay=delay,
                    )
                else:
                    await self.coordinator.async_call_climate_service(
                        "set_preset_mode",
                        entity_id,
                        {"preset_mode": PRESET_SCHEDULE},
                        needs_delay=delay,
                    )
                room_restored = True
            # broad-except-rationale: one entity failing must not abort the others in this loop
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to restore schedule in '%s': %s", room_name, err
                )

        if room_restored:
            self.coordinator.set_room_state(room_name, RoomState.NORMAL)

            # ── CO₂-aware close notification ──────────────────────────────
            co2_ppm = self.coordinator.get_room_co2(room_name)
            co2_label = self._co2_context_label(co2_ppm, room_name)
            label = self._sensor_label(room_name, sensor_id)
            notif_msg = f"{label} closed — {room_name} heating resumed{co2_label}"

            _LOGGER.info("%s closed in '%s' — restored to schedule", label, room_name)
            self.coordinator.log_event(
                f"{label} closed in {room_name} — heating resumed", label, "normal"
            )
            if self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
                await self._notify(notif_msg)

    async def async_tick(self) -> None:
        """B2 FIX: Send 30-min escalation warning with CO₂ context."""
        if not self.coordinator.config.get(CONF_NOTIFY_WINDOWS, True):
            return

        threshold = int(
            self.coordinator.config.get(
                CONF_WINDOW_WARNING_MIN, DEFAULT_WINDOW_WARNING_MIN
            )
        )
        now = utcnow()

        for room_name, opened_at in list(self._window_opened_at.items()):
            if self._warning_sent.get(room_name, False):
                continue
            minutes_open = int((now - opened_at).total_seconds() / 60)
            if minutes_open >= threshold:
                co2_ppm = self.coordinator.get_room_co2(room_name)
                co2_label = self._co2_context_label(co2_ppm, room_name)

                label = self._room_label(room_name)
                log_msg = f"{label} open {minutes_open} min in {room_name}"
                notif_msg = (
                    f"{label} still open in {room_name} ({minutes_open} min)"
                    f" — heating suppressed{co2_label}"
                )

                _LOGGER.info(
                    "%s in '%s' open %d min%s — sending warning",
                    label,
                    room_name,
                    minutes_open,
                    f"  CO₂: {co2_ppm:.0f} ppm" if co2_ppm else "",
                )
                self.coordinator.log_event(log_msg, "30-min warning", "window_open")
                if self.coordinator.config.get(CONF_NOTIFY_WINDOW_WARNING_30, True):
                    await self._notify(notif_msg)
                self._warning_sent[room_name] = True

    # ── CO₂ context helpers ───────────────────────────────────────────────────

    def _co2_context_label(self, co2_ppm: float | None, room_name: str = "") -> str:
        """Return a short parenthetical string for window notification messages.

        Rain and wind take precedence over CO₂ — both override the context
        to 'heat loss' regardless of CO₂ level.
        Uses per-room CO₂ threshold when room_name is provided.
        """
        # Rain: always heat loss, add rain hint
        if self.coordinator.is_raining():
            precip = self.coordinator.get_precipitation()
            return f"  (🌧️ {precip:.1f} mm — regn: varmetab)"

        # Wind: fast wind means rapid heat loss
        wind = self.coordinator.get_wind_speed()
        if wind is not None and wind >= WIND_FAST_MS:
            return f"  (💨 {wind:.1f} m/s — vind: varmetab)"

        # CO₂ context — use per-room threshold when available
        if co2_ppm is None:
            return ""
        threshold = (
            self.coordinator.get_room_co2_threshold(room_name)
            if room_name
            else DEFAULT_CO2_VENTILATION_THRESHOLD
        )
        if co2_ppm >= threshold:
            return f"  (CO₂: {co2_ppm:.0f} ppm — ventilation)"
        return f"  (CO₂: {co2_ppm:.0f} ppm — varmetab)"

    # ── Remaining helpers (unchanged) ─────────────────────────────────────────

    def get_open_windows(self) -> list[str]:
        open_rooms: list[str] = []
        for sensor_id, room_name in self._sensor_to_room.items():
            state = self.coordinator.hass.states.get(sensor_id)
            if state and state.state == "on":
                open_rooms.append(room_name)
        return sorted(set(open_rooms))

    def _all_room_sensors_closed(self, room_name: str) -> bool:
        """True only when every window/door sensor configured for this room
        is currently closed (B16). A room's heating must stay suppressed as
        long as at least one of its sensors reports open, regardless of
        which specific sensor triggered the close event being processed.
        """
        for sid, r_name in self._sensor_to_room.items():
            if r_name != room_name:
                continue
            state = self.coordinator.hass.states.get(sid)
            if state and state.state == "on":
                return False
        return True

    async def _notify(self, message: str) -> None:
        service = self.coordinator.config.get(CONF_NOTIFY_SERVICE, "")
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
        # broad-except-rationale: one entity failing must not abort the others in this loop
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Window notification failed: %s", err)

    def _get_open_delay(self, sensor_id: str) -> int:
        """Return window open delay in minutes.

        v0.33.0: reads the one global CONF_WINDOW_DELAY_DEFAULT_MIN setting
        (live-editable from the panel's Indstillinger tab) instead of the
        old per-room CONF_WINDOW_DELAY_MIN, which required a trip through
        the config-flow room step and was never exposed anywhere the user
        actually looks. The per-room field is left in const.py/config_flow.py
        untouched (not read here anymore) in case per-room editing returns
        in a future panel pass.

        Wind fast (> WIND_FAST_MS): reduce to DEFAULT_WINDOW_DELAY_WIND_MIN
        so heat loss is suppressed quicker.
        Rain: also reduce — nobody opens a window for ventilation in rain.
        """
        configured = int(
            self.coordinator.config.get(
                CONF_WINDOW_DELAY_DEFAULT_MIN, DEFAULT_WINDOW_DELAY_DEFAULT_MIN
            )
        )

        wind = self.coordinator.get_wind_speed()
        if wind is not None and wind >= WIND_FAST_MS:
            _LOGGER.debug(
                "Window delay reduced to %d min (wind %.1f m/s ≥ %.1f)",
                DEFAULT_WINDOW_DELAY_WIND_MIN,
                wind,
                WIND_FAST_MS,
            )
            return DEFAULT_WINDOW_DELAY_WIND_MIN

        if self.coordinator.is_raining():
            _LOGGER.debug(
                "Window delay reduced to %d min (rain)", DEFAULT_WINDOW_DELAY_WIND_MIN
            )
            return DEFAULT_WINDOW_DELAY_WIND_MIN

        return configured

    def _cancel_task(self, task_dict: dict[str, asyncio.Task[Any]], key: str) -> None:
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
