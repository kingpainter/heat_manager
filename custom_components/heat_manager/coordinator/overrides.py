"""Heat Manager coordinator — overrides layer: manual control and boost.

Putting rooms in manual (override) and back to auto, timed overrides from the
remote and the panel, boost start/stop/expiry, and the house-level status
summary (auto/manual/mixed, boost, paused) shown in the panel and card
(v0.68.6, T3f).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.util.dt import utcnow

from ..const import (
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    CONF_CLIMATE_ENTITY,
    CONF_REMOTE_OVERRIDE_DURATION_MIN,
    CONF_TRV_TYPE,
    CONTROL_MODE_AUTO,
    CONTROL_MODE_MANUAL,
    CONTROL_MODE_MIXED,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMP,
    DEFAULT_REMOTE_OVERRIDE_DURATION_MIN,
    HOUSE_STATUS_AUTO,
    HOUSE_STATUS_BOOST,
    HOUSE_STATUS_MANUAL,
    HOUSE_STATUS_OFF,
    HOUSE_STATUS_PAUSED,
    HOUSE_STATUS_WINDOW_OPEN,
    TRV_TYPE_ZIGBEE,
    ControllerState,
    RoomState,
)
from .netatmo import CoordinatorNetatmo

_LOGGER = logging.getLogger(__name__)


class CoordinatorOverrides(CoordinatorNetatmo):
    """Heat Manager coordinator — overrides layer: manual control and boost."""

    async def async_set_room_override(
        self, room_name: str, enable: bool, source: str = "switch"
    ) -> bool:
        """Toggle a room's manual override (RoomState.OVERRIDE) on/off.

        This is the shared implementation behind RoomOverrideSwitch
        (switch.py) and RemoteButtonEngine (engine/remote_button_engine.py,
        v0.14.0) — factored out so the TRV-command routing exists exactly
        once instead of being duplicated per caller.

        enable=True mirrors the switch's async_turn_on(): forces every
        physical TRV configured for the room to heating — preset_mode=
        schedule for netatmo, hvac_mode=heat for zigbee (zigbee prefers the
        TRV's own write entity, HomeKit if reachable; netatmo always writes
        to its raw climate_entity — same per-TRV routing as force_room_on())
        — and marks the room OVERRIDE, bypassing presence and window logic.
        `source` is purely informational ("switch" or "remote") — recorded
        in room_override_source for the frontend badge, see set_room_state().

        enable=False mirrors async_turn_off(): restores the room's TRVs to
        their schedule/heat mode via async_restore_room_schedule(), then
        marks the room NORMAL. B23 (2026-10-30): this used to only flip the
        state flag — a Netatmo TRV left on a manual setpoint (e.g. by the
        remote's +/- buttons, which write set_temperature) kept that
        setpoint after "back to auto", because nothing ever told it to
        return to its schedule. Same restore path as ws_set_room_temp's
        reset and _async_check_room_override_expiry().

        Returns True if the room's state actually changed the physical
        TRVs (enable=True: at least one TRV command succeeded; enable=False:
        always True), so a caller can decide whether to log/notify.
        """
        if not enable:
            try:
                await self.async_restore_room_schedule(room_name)
            # broad-except-rationale: a failed restore must not leave the room stuck in OVERRIDE
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Override turn_off: schedule restore failed for %s: %s",
                    room_name,
                    err,
                )
            self.set_room_state(room_name, RoomState.NORMAL)
            return True

        trvs = self.get_room_trvs(room_name)
        if not trvs:
            return False
        any_ok = False
        for trv in trvs:
            climate_id = trv.get(CONF_CLIMATE_ENTITY, "")
            if not climate_id:
                continue
            trv_type = trv.get(CONF_TRV_TYPE, "netatmo")
            # 2026-09-16 (deep-dive audit fix): this used to call
            # hass.services.async_call("climate", ...) directly. Shared by
            # RoomOverrideSwitch (one room) AND RemoteButtonEngine's mode-
            # toggle button (every eligible room at once, per its own
            # module docstring) — the latter is the same whole-house burst
            # pattern already fixed for temp up/down in that file.
            try:
                if trv_type == TRV_TYPE_ZIGBEE:
                    write_id = self.get_trv_write_entity(trv) or climate_id
                    await self.async_call_climate_service(
                        "set_hvac_mode",
                        write_id,
                        {"hvac_mode": "heat"},
                        needs_delay=self.trv_needs_cloud_delay(trv),
                    )
                else:
                    await self.async_release_netatmo_room(climate_id)
                any_ok = True
                _LOGGER.info("Override ON: %s \u2192 heating (%s)", room_name, trv_type)
            # broad-except-rationale: one entity failing must not abort the others in this loop
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Override turn_on failed for %s: %s", room_name, err)

        if any_ok:
            self.set_room_state(room_name, RoomState.OVERRIDE)
            self.room_override_source[room_name] = source
        return any_ok

    def set_remote_override_expiry(self, room_name: str) -> None:
        """(Re)start the auto-restore countdown for a room the remote holds
        in OVERRIDE (v0.59.0) — called by RemoteButtonEngine after every
        press that touched the room, so each press extends it.

        Uses the same room_override_expires_at mechanism as the panel's
        duration-limited manual temperature, so expiry, persistence across
        restarts and the frontend's "until HH:MM" all come for free.
        CONF_REMOTE_OVERRIDE_DURATION_MIN == 0 means never expire. The
        room's source becomes "remote" too: a press on a room someone set
        manual from the panel hands it over to the remote's countdown, and
        the badge should say so.
        """
        if self.get_room_state(room_name) != RoomState.OVERRIDE:
            return
        self.room_override_source[room_name] = "remote"
        try:
            duration = int(
                self.config.get(
                    CONF_REMOTE_OVERRIDE_DURATION_MIN,
                    DEFAULT_REMOTE_OVERRIDE_DURATION_MIN,
                )
            )
        except (TypeError, ValueError):
            duration = DEFAULT_REMOTE_OVERRIDE_DURATION_MIN
        if duration > 0:
            self.room_override_expires_at[room_name] = utcnow() + timedelta(
                minutes=duration
            )
        else:
            self.room_override_expires_at.pop(room_name, None)

    def extend_overrides(self, minutes: int) -> list[str]:
        """Push every time-limited manual override's auto-restore time back
        by `minutes` (v0.60.0 — the status line's "+1 time"). An override
        that already expired-but-not-yet-restored counts from now. Rooms
        with a permanent override (no expiry) are left alone."""
        now = utcnow()
        extended: list[str] = []
        for room_name, expires_at in list(self.room_override_expires_at.items()):
            if self.get_room_state(room_name) != RoomState.OVERRIDE:
                continue
            self.room_override_expires_at[room_name] = max(expires_at, now) + timedelta(
                minutes=minutes
            )
            extended.append(room_name)
        if extended:
            self.log_message(
                "override_extended",
                "override",
                "panel",
                minutes=minutes,
                rooms=", ".join(extended),
            )
            self.async_update_listeners()
        return extended

    def get_control_mode(self) -> tuple[str, list[str]]:
        """House-wide control mode (v0.59.0) and the rooms in OVERRIDE.

        AUTO when no room is in OVERRIDE, MANUAL when every room with at
        least one TRV is, MIXED otherwise. Monitoring-only rooms (no TRV)
        are never counted — nothing is being controlled there.
        """
        controllable = [
            room.get("room_name", "")
            for room in self.rooms
            if room.get("room_name") and self.get_all_room_trvs(room["room_name"])
        ]
        manual = [
            name
            for name in controllable
            if self.get_room_state(name) == RoomState.OVERRIDE
        ]
        if not manual:
            return CONTROL_MODE_AUTO, []
        if len(manual) == len(controllable):
            return CONTROL_MODE_MANUAL, manual
        return CONTROL_MODE_MIXED, manual

    def get_house_status(self) -> dict[str, Any]:
        """Headline status of the whole house (v0.60.0) — the Hub "Status"
        sensor's state and attributes. State priority: off > paused >
        window open > boost > manual > auto (HOUSE_STATUSES)."""
        _mode, manual = self.get_control_mode()
        window_rooms = [
            name
            for name, state in self.room_states.items()
            if state == RoomState.WINDOW_OPEN
        ]
        boost_min = self.boost_remaining_minutes or 0
        ctrl = self.controller_state
        if ctrl == ControllerState.OFF:
            status = HOUSE_STATUS_OFF
        elif ctrl == ControllerState.PAUSE:
            status = HOUSE_STATUS_PAUSED
        elif window_rooms:
            status = HOUSE_STATUS_WINDOW_OPEN
        elif boost_min > 0:
            status = HOUSE_STATUS_BOOST
        elif manual:
            status = HOUSE_STATUS_MANUAL
        else:
            status = HOUSE_STATUS_AUTO
        expiries = [self.room_override_expires_at.get(name) for name in manual]
        auto_returns_at = (
            max(e for e in expiries if e is not None)
            if manual and all(e is not None for e in expiries)
            else None
        )
        return {
            "status": status,
            "manual_rooms": manual,
            "window_rooms": window_rooms,
            "auto_returns_at": auto_returns_at,
            "boost_remaining_min": boost_min,
            "pause_remaining_min": self.pause_remaining_minutes
            if ctrl == ControllerState.PAUSE
            else 0,
        }

    async def async_release_all_overrides(self, reason: str = "panel") -> list[str]:
        """Return every room in OVERRIDE to automatic control (v0.59.0) —
        the panel's "Tilbage til auto" button. Same per-room path as the
        override switch and the remote's auto/manual button
        (async_set_room_override(False), which also restores the TRVs'
        schedule — see B23)."""
        released: list[str] = []
        for room_name in list(self.room_states):
            if self.get_room_state(room_name) != RoomState.OVERRIDE:
                continue
            await self.async_set_room_override(room_name, False)
            released.append(room_name)
        if released:
            # `reason` is a "reason" text key ("panel", "remote").
            self.log_message(
                "override_released", "normal", reason, rooms=", ".join(released)
            )
        return released

    def set_remote_last_action(
        self,
        description: str,
        rooms: list[str],
        *,
        action: str | None = None,
        delta: float | None = None,
        skipped: dict[str, str] | None = None,
        text_key: str | None = None,
        text_params: dict[str, Any] | None = None,
    ) -> None:
        """Record the most recent action taken by the global physical
        remote (v0.14.0's temp up/down/mode toggle buttons) — called from
        engine/remote_button_engine.py after a successful action.

        Purely informational: read by sensor.py's RemoteLastActionSensor
        (Hub device). Never gates any control-flow decision.

        v0.60.0: also records a machine-readable `action` ("temp_up",
        "temp_down", "manual", "auto", "boost", "release"), the applied
        `delta` in °C, and `skipped` (room -> RoomState value) for rooms the
        remote left alone — the panel's status line builds its "received,
        sent to 7 rooms, Bad skipped (window open)" acknowledgement from
        these instead of parsing the English description.
        """
        self.remote_last_action = {
            "description": description,
            "rooms": rooms,
            "timestamp": utcnow().isoformat(),
            "action": action,
            "delta": delta,
            "skipped": dict(skipped or {}),
            # v0.72.0: the description's "event" text key + params, so the
            # status line can show it in the viewer's language.
            "key": text_key,
            "params": dict(text_params or {}),
        }
        self.async_update_listeners()

    @property
    def boost_remaining_minutes(self) -> int:
        """Minutes remaining until boost auto-restores. 0 when not boosted."""
        if self.boost_expires_at is None:
            return 0
        remaining = (self.boost_expires_at - utcnow()).total_seconds()
        return max(0, int(remaining / 60))

    async def async_boost_start(
        self,
        temperature: float | None = None,
        duration_minutes: float | None = None,
    ) -> list[str]:
        """Raise every NORMAL/OVERRIDE room to the boost temperature.

        Single source of truth for "boost", called by both the
        heat_manager.boost_start service and the heat_manager/boost_start WS
        command (used by the sidebar panel) — previously the WS handler only
        toggled a flag with no heating effect, and the Lovelace card
        duplicated a separate client-side implementation. Both now delegate
        here so there is exactly one code path that actually moves a TRV.

        Rooms currently AWAY, WINDOW_OPEN or PRE_HEAT are left untouched.
        Sets boost_expires_at so the coordinator tick can auto-restore after
        duration_minutes (default: CONF_BOOST_DEFAULT_MINUTES from options,
        falling back to DEFAULT_BOOST_MINUTES) even if nobody ever
        calls async_boost_stop() — the Lovelace card's own boost only ever
        had a client-side countdown that stopped working the moment the
        dashboard was closed; this gives boost a real backend expiry.

        Also resets every room's offset to 0 (v0.9.0, per-room since B18
        Fase 3) — same "setting a temperature directly clears the offset"
        rule climate_group_helper's Group Offset follows, since boost sets
        an absolute temperature that would otherwise silently stack with a
        leftover offset.
        """
        # 2026-10-30 fix: the configured defaults (panel "Standardtemperatur"/
        # "Standardvarighed", options flow) were read here until v0.31.0
        # dropped them — since then every boost without an explicit
        # temperature/duration (panel button, remote long-press) silently
        # used the hardcoded DEFAULT_BOOST_TEMP/DEFAULT_BOOST_MINUTES.
        temp = (
            float(temperature)
            if temperature is not None
            else float(self.config.get(CONF_BOOST_DEFAULT_TEMP, DEFAULT_BOOST_TEMP))
        )
        self.room_offsets = {}
        self.async_update_listeners()  # refresh every number.<room>_offset immediately

        boosted: list[str] = []
        for room in self.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            if self.get_room_state(room_name) not in (
                RoomState.NORMAL,
                RoomState.OVERRIDE,
            ):
                continue
            # B18: same boost temperature to every TRV configured for this
            # room, not just the primary one.
            # 2026-09-16 (deep-dive audit fix): iterates TRVs directly
            # (rather than the flattened write-entity list) so each write
            # gets its own trv_needs_cloud_delay() decision — this used to
            # call hass.services.async_call("climate", ...) directly for
            # every room's every TRV with no lock/pacing at all. Boost is a
            # one-press, whole-house action (same burst shape as the
            # RemoteButtonEngine fix), making this one of the more
            # user-visible 429-risk gaps this audit found.
            trvs = self.get_room_trvs(room_name)
            if not trvs:
                continue
            room_ok = False
            for trv in trvs:
                write_entity = self.get_trv_write_entity(trv)
                if not write_entity:
                    continue
                try:
                    await self.async_call_climate_service(
                        "set_temperature",
                        write_entity,
                        {"temperature": temp},
                        needs_delay=self.trv_needs_cloud_delay(trv),
                    )
                    room_ok = True
                # broad-except-rationale: one entity failing must not abort the others in this loop
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Boost failed for '%s' (%s): %s", room_name, write_entity, err
                    )
            if room_ok:
                self.boost_active_rooms[room_name] = True
                boosted.append(room_name)

        if boosted:
            minutes = (
                float(duration_minutes)
                if duration_minutes is not None
                else float(
                    self.config.get(CONF_BOOST_DEFAULT_MINUTES, DEFAULT_BOOST_MINUTES)
                )
            )
            self.boost_expires_at = utcnow() + timedelta(minutes=minutes)
        else:
            self.boost_expires_at = None

        if boosted:
            self.log_message(
                "boost_started", "boost", "manual", rooms=", ".join(boosted)
            )
        else:
            self.log_message("boost_started_none", "boost", "manual")
        _LOGGER.info(
            "Boost started — %d room(s) boosted to %.1f°C: %s",
            len(boosted),
            temp,
            ", ".join(boosted) or "none",
        )
        return boosted

    async def async_boost_stop(self) -> list[str]:
        """Restore every currently-boosted room back to its normal schedule.

        Single source of truth for stopping boost — see async_boost_start().
        Restores via presence_engine.force_room_on(), same as the card's own
        boost-stop and the manual force_room_on service.
        """
        boosted_rooms = [
            name for name, active in self.boost_active_rooms.items() if active
        ]
        for room_name in boosted_rooms:
            try:
                await self.presence_engine.force_room_on(room_name)
            # broad-except-rationale: one entity failing must not abort the others in this loop
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Boost-stop restore failed for '%s': %s", room_name, err
                )

        self.boost_active_rooms.clear()
        self.boost_expires_at = None
        self.log_message("boost_stopped", "boost", "manual")
        _LOGGER.info("Boost stopped — restored %d room(s)", len(boosted_rooms))
        return boosted_rooms

    async def _async_check_boost_expiry(self) -> None:
        """Auto-restore boosted rooms once the boost duration has elapsed."""
        if self.boost_expires_at is None:
            return
        if utcnow() >= self.boost_expires_at:
            _LOGGER.info("Boost expired — auto-restoring")
            await self.async_boost_stop()

    async def async_restore_room_schedule(self, room_name: str) -> str | None:
        """Restore a room's TRVs to their schedule/heat mode, releasing any
        manual override. Shared by ws_set_room_temp's temperature=None
        branch and _async_check_room_override_expiry() below so both restore
        identically. Returns the first write entity actually commanded, or
        None if the room has no configured TRVs.
        """
        trvs = self.get_room_trvs(room_name)
        if not trvs:
            return None

        write_entity: str | None = None
        for trv in trvs:
            trv_type = trv.get(CONF_TRV_TYPE, "netatmo")
            if trv_type == "zigbee":
                entity_id = self.get_trv_write_entity(trv) or trv.get(
                    CONF_CLIMATE_ENTITY
                )
                if not entity_id:
                    continue
                await self.async_call_climate_service(
                    "set_hvac_mode",
                    entity_id,
                    {"hvac_mode": "heat"},
                    needs_delay=self.trv_needs_cloud_delay(trv),
                )
            else:
                entity_id = trv.get(CONF_CLIMATE_ENTITY)
                if not entity_id:
                    continue
                await self.async_release_netatmo_room(entity_id)
            if write_entity is None:
                write_entity = entity_id
        return write_entity

    async def _async_check_room_override_expiry(self) -> None:
        """Auto-restore rooms whose duration-limited manual override
        (ws_set_room_temp with duration_min > 0) has elapsed."""
        if not self.room_override_expires_at:
            return
        now = utcnow()
        expired = [
            room_name
            for room_name, expires_at in self.room_override_expires_at.items()
            if now >= expires_at
        ]
        for room_name in expired:
            try:
                await self.async_restore_room_schedule(room_name)
            # broad-except-rationale: one room's restore failing must not block the rest
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Room override expiry restore failed for '%s': %s", room_name, err
                )
            self.set_room_state(room_name, RoomState.NORMAL)
            self.log_message("override_expired", "manual", "auto", room=room_name)
            _LOGGER.info("Room '%s' manual override expired — auto-restored", room_name)
