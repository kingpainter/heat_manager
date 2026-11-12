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
- Press types (B22, 2026-10-30): a single press is "multi_press_1" when
  the remote is paired via Matter (the Aqara W100's normal setup) and
  "single"/"single_<button>" via Zigbee2MQTT-style integrations. The
  original version only accepted the literal "single", so a Matter-paired
  W100 never triggered anything at all. A double press ("multi_press_2" /
  "double") on temp up/down applies two steps at once; on the mode toggle
  it is ignored. Long presses are always ignored. See _press_count(). If a
  different device reports other strings, check the raw value with
  {{ state_attr('event.xxx', 'event_type') }} in Developer Tools > Template
  (the States view shows a translated label, not the raw value).
- Restart guard (B25): a state change whose old state is missing or
  "unavailable", or whose state (the event timestamp) didn't change, is not
  a press — it's the entity being restored at startup or an attribute-only
  update.
- Fast presses (B24): presses are serialised with a lock, and each room's
  last setpoint written by the remote is trusted for
  REMOTE_PENDING_SETPOINT_TTL_S instead of re-reading the TRV — Netatmo
  reports a new setpoint back only after several seconds, so two quick
  presses used to start from the same stale value.
- Auto-restore (v0.59.0): every press that puts or keeps a room in manual
  restarts that room's countdown (coordinator.set_remote_override_expiry(),
  CONF_REMOTE_OVERRIDE_DURATION_MIN, default 2 hours) — after it runs out
  the coordinator's existing override-expiry check restores the schedule.
- Long press (v0.60.0): temp up held = start boost (coordinator.
  async_boost_start(), same as the panel's Boost button); auto/manual held
  = every room back to automatic (coordinator.async_release_all_overrides(),
  whatever put it in manual); temp down held = nothing.
- Every action records which rooms were skipped and why (v0.60.0,
  set_remote_last_action(skipped=...)) so the panel can say "Bad skipped
  — window open" instead of silently leaving a room out.
- No push notification is sent for button presses (the physical result —
  the radiator warming up — is its own feedback); every action is still
  written to the coordinator's event log for the panel's history.
"""

from __future__ import annotations

import asyncio
import logging
import time
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
    REMOTE_DOUBLE_PRESS_TYPES,
    REMOTE_LONG_PRESS_TYPES,
    REMOTE_PENDING_SETPOINT_TTL_S,
    REMOTE_SINGLE_PRESS_TYPES,
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
        # B24: one press at a time, and the last setpoint the remote wrote
        # per room (target, time.monotonic() when written).
        self._lock = asyncio.Lock()
        self._pending_setpoints: dict[str, tuple[float, float]] = {}
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
                async_track_state_change_event(
                    hass, [mode_id], self._handle_mode_toggle
                )
            )

        if not (up_id or down_id or mode_id):
            _LOGGER.debug("RemoteButtonEngine: no button entities configured — idle")

    def rebuild_listeners(self) -> None:
        """Unsubscribe and re-register every button listener from the
        current config.

        2026-09 audit fix: the 3 button entity IDs were only ever read once,
        in __init__ — changing CONF_BUTTON_TEMP_UP_ENTITY/_DOWN_ENTITY/
        _MODE_TOGGLE_ENTITY in the options flow had no effect until the next
        full integration reload (which only happens today when rooms/persons
        change — see __init__.py's _async_update_listener). Called from
        there unconditionally so a button re-assignment takes effect
        immediately, matching SyncEngine.rebuild_entity_map()'s pattern.
        """
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._register_listeners()

    @staticmethod
    def _press_type_count(event_type: Any) -> int:
        """1 for a single press, 2 for a double press, 0 for anything else
        (long press/release, hold, unknown strings). See module docstring."""
        if not isinstance(event_type, str):
            return 0
        value = event_type.lower()
        if value in REMOTE_SINGLE_PRESS_TYPES or value.startswith("single_"):
            return 1
        if value in REMOTE_DOUBLE_PRESS_TYPES or value.startswith("double_"):
            return 2
        return 0

    @staticmethod
    def _press_type_is_long(event_type: Any) -> bool:
        """True for the start of a long press (v0.60.0) — Matter
        "long_press", Zigbee2MQTT-style "hold"/"hold_<button>". The matching
        release ("long_release", "release_<button>") is never a press."""
        if not isinstance(event_type, str):
            return False
        value = event_type.lower()
        return value in REMOTE_LONG_PRESS_TYPES or value.startswith("hold_")

    @staticmethod
    def _new_event_type(event: Any) -> str | None:
        """The event_type of a genuinely new button event, else None.

        B25: None for anything that isn't a real new button event — no
        previous state or a previous "unavailable" state (the entity being
        added/restored at startup), an unavailable new state, or an
        unchanged state (attribute-only update; an event entity's state is
        the timestamp of its last event, so a real press always changes it).
        """
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or old_state is None:
            return None
        if old_state.state == "unavailable" or new_state.state in (
            "unavailable",
            "unknown",
        ):
            return None
        if new_state.state == old_state.state:
            return None
        event_type = new_state.attributes.get("event_type")
        return event_type if isinstance(event_type, str) else None

    def _press_count(self, event: Any) -> int:
        """Number of presses a state-change event represents (0, 1 or 2)."""
        event_type = self._new_event_type(event)
        if event_type is None:
            return 0
        count = self._press_type_count(event_type)
        if count == 0 and not self._press_type_is_long(event_type):
            _LOGGER.debug(
                "RemoteButtonEngine: ignoring %s event_type=%r",
                event.data["new_state"].entity_id,
                event_type,
            )
        return count

    def _is_long_press(self, event: Any) -> bool:
        """True when a state-change event is the start of a long press."""
        return self._press_type_is_long(self._new_event_type(event))

    def _skipped_rooms(self) -> dict[str, str]:
        """Rooms the remote never touches right now, with the reason
        (their RoomState value) — see _EXCLUDED_STATES."""
        skipped: dict[str, str] = {}
        for room in self.coordinator.rooms:
            name = room.get("room_name", "")
            if not name:
                continue
            state = self.coordinator.get_room_state(name)
            if state in _EXCLUDED_STATES:
                skipped[name] = state.value
        return skipped

    # ── Temp up / down ──────────────────────────────────────────────────────

    @callback
    def _handle_temp_up(self, event: Any) -> None:
        if self._is_long_press(event):
            self.coordinator.hass.async_create_task(
                self._async_boost_all(), name="heat_manager_remote_boost"
            )
            return
        count = self._press_count(event)
        if not count:
            return
        self.coordinator.hass.async_create_task(
            self._async_adjust_all_rooms(BUTTON_TEMP_STEP * count),
            name="heat_manager_remote_temp_up",
        )

    @callback
    def _handle_temp_down(self, event: Any) -> None:
        count = self._press_count(event)
        if not count:
            return
        self.coordinator.hass.async_create_task(
            self._async_adjust_all_rooms(-BUTTON_TEMP_STEP * count),
            name="heat_manager_remote_temp_down",
        )

    async def _async_adjust_all_rooms(self, delta: float) -> None:
        # B24: serialise presses so a second press always sees the first
        # press's result (see _pending_setpoints).
        async with self._lock:
            await self._async_adjust_all_rooms_locked(delta)

    async def _async_adjust_all_rooms_locked(self, delta: float) -> None:
        rooms_adjusted: list[str] = []
        for room in self.coordinator.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            if self.coordinator.get_room_state(room_name) in _EXCLUDED_STATES:
                continue

            if self.coordinator.get_room_state(room_name) == RoomState.NORMAL:
                # Coming from auto: start from the TRV's own setpoint, not
                # from whatever the remote wrote before the room went back
                # to auto.
                self._pending_setpoints.pop(room_name, None)
                await self.coordinator.async_set_room_override(
                    room_name, True, source="remote"
                )

            write_entities = self.coordinator.get_room_write_entities(room_name)
            if not write_entities:
                continue

            current = self._pending_setpoint(room_name)
            if current is None:
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

            # 2026-09-16 (deep-dive audit fix): this loop used to call
            # hass.services.async_call("climate", ...) directly for every
            # write entity, bypassing coordinator.async_call_climate_service()
            # entirely. A single button press touches EVERY eligible room at
            # once — exactly the burst pattern the shared Netatmo lock/pacing
            # exists to prevent (see that method's own docstring and
            # controller.py's OFF-fallback for the same fix already applied
            # elsewhere) — making this the most likely of the four call sites
            # this audit found to actually trigger a 429. Iterates the room's
            # TRVs directly (not the flattened write_entities list above) so
            # each write's delay is resolved per-TRV via
            # trv_needs_cloud_delay(), the same way preheat_engine.py and
            # controller.py's off-fallback do it.
            any_ok = False
            for trv in self.coordinator.get_room_trvs(room_name):
                write_id = self.coordinator.get_trv_write_entity(trv)
                if not write_id:
                    continue
                try:
                    await self.coordinator.async_call_climate_service(
                        "set_temperature",
                        write_id,
                        {"temperature": new_target},
                        needs_delay=self.coordinator.trv_needs_cloud_delay(trv),
                    )
                    any_ok = True
                # broad-except-rationale: one entity failing must not abort the others in this loop
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "RemoteButtonEngine: set_temperature failed for %s (%s): %s",
                        room_name,
                        write_id,
                        err,
                    )
            if not any_ok:
                # Nothing was actually written — don't report the room as
                # adjusted, and don't let the next press build on a
                # setpoint the TRV never received.
                continue
            self._pending_setpoints[room_name] = (new_target, time.monotonic())
            # v0.59.0: every press on a room restarts its auto-restore
            # countdown (CONF_REMOTE_OVERRIDE_DURATION_MIN).
            self.coordinator.set_remote_override_expiry(room_name)
            rooms_adjusted.append(f"{room_name} → {new_target:.1f}°C")

        if rooms_adjusted:
            sign = "+" if delta > 0 else ""
            rooms_str = ", ".join(rooms_adjusted)
            description = f"Remote: {sign}{delta:.1f}°C — {rooms_str}"
            self.coordinator.log_event(description, "Remote", "override")
            self.coordinator.set_remote_last_action(
                description,
                [room.split(" → ")[0] for room in rooms_adjusted],
                action="temp_up" if delta > 0 else "temp_down",
                delta=delta,
                skipped=self._skipped_rooms(),
            )
            _LOGGER.info("RemoteButtonEngine: temp %+.1f°C — %s", delta, rooms_str)

    def _pending_setpoint(self, room_name: str) -> float | None:
        """The remote's own last-written setpoint for a room, if it is
        recent enough to trust over the TRV's reported value (B24)."""
        pending = self._pending_setpoints.get(room_name)
        if pending is None:
            return None
        target, written_at = pending
        if time.monotonic() - written_at > REMOTE_PENDING_SETPOINT_TTL_S:
            self._pending_setpoints.pop(room_name, None)
            return None
        return target

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
        if self._is_long_press(event):
            self.coordinator.hass.async_create_task(
                self._async_release_all(), name="heat_manager_remote_release"
            )
            return
        # Single press only — a double press on this button is reserved.
        if self._press_count(event) != 1:
            return
        self.coordinator.hass.async_create_task(
            self._async_toggle_all_rooms(),
            name="heat_manager_remote_mode_toggle",
        )

    async def _async_toggle_all_rooms(self) -> None:
        async with self._lock:
            await self._async_toggle_all_rooms_locked()

    async def _async_toggle_all_rooms_locked(self) -> None:
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
                if enable:
                    self.coordinator.set_remote_override_expiry(room_name)
                else:
                    self._pending_setpoints.pop(room_name, None)

        if rooms_changed:
            label = "manual" if enable else "auto"
            rooms_str = ", ".join(rooms_changed)
            description = f"Remote: switched to {label} — {rooms_str}"
            self.coordinator.log_event(
                description, "Remote", "override" if enable else "normal"
            )
            self.coordinator.set_remote_last_action(
                description,
                rooms_changed,
                action=label,
                skipped=self._skipped_rooms(),
            )
            _LOGGER.info("RemoteButtonEngine: mode → %s for %s", label, rooms_str)

    # ── Long presses (v0.60.0) ────────────────────────────────────────────────

    async def _async_boost_all(self) -> None:
        """Temp up held: start boost — the exact same coordinator call as
        the panel's Boost button and the heat_manager.boost_start service."""
        async with self._lock:
            # Boost itself only touches NORMAL/OVERRIDE rooms (see
            # coordinator.async_boost_start()) — record the rest as skipped.
            skipped = {
                name: self.coordinator.get_room_state(name).value
                for name in (r.get("room_name", "") for r in self.coordinator.rooms)
                if name
                and self.coordinator.get_room_state(name)
                not in (RoomState.NORMAL, RoomState.OVERRIDE)
            }
            boosted = await self.coordinator.async_boost_start()
            if not boosted:
                return
            description = f"Remote: boost — {', '.join(boosted)}"
            self.coordinator.log_event(description, "Remote", "boost")
            self.coordinator.set_remote_last_action(
                description, boosted, action="boost", skipped=skipped
            )
            _LOGGER.info("RemoteButtonEngine: boost started for %s", boosted)

    async def _async_release_all(self) -> None:
        """Auto/manual held: every room back to automatic, whatever put it
        in manual (remote, panel, switch or the radiator itself)."""
        async with self._lock:
            released = await self.coordinator.async_release_all_overrides(
                reason="Remote"
            )
            for room_name in released:
                self._pending_setpoints.pop(room_name, None)
            if not released:
                return
            self.coordinator.set_remote_last_action(
                f"Remote: all rooms back to auto — {', '.join(released)}",
                released,
                action="release",
            )
            _LOGGER.info("RemoteButtonEngine: released overrides for %s", released)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_tick(self) -> None:
        """No-op — all remote-button logic is event-driven."""

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.debug("RemoteButtonEngine shut down")
