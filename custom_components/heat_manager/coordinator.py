"""
Heat Manager — DataUpdateCoordinator

Central hub that:
- Owns all engine instances
- Holds all shared runtime state (room_states, season_mode, etc.)
- Runs the periodic tick that drives auto-off, pause expiry, and presence checks
- Exposes helpers used by platform entities to read current state

Phase 3 additions:
- SeasonEngine: resolves AUTO → effective WINTER/SUMMER
- PreheatEngine: travel_time based pre-heat
- log_event(): internal event log for History tab in sidebar panel
- effective_season property: resolved season regardless of manual/auto

v0.2.9 additions:
- CONF_OUTDOOR_TEMP_SENSOR: local sensor overrides weather entity temperature
- CONF_CO2_SENSOR per room: get_room_co2() helper for WindowEngine
- CONF_ROOM_TEMP_SENSOR per room: get_room_current_temp() feeds PID with an
  independent probe instead of the TRV's own (radiator-biased) sensor

v0.4.1 additions:
- _async_update_data: each engine tick is individually isolated — an exception
  in one engine is logged as WARNING and skipped rather than raising UpdateFailed
  and marking all entities unavailable.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import utcnow

from .const import (
    CONF_ALARM_PANEL,
    CONF_BOOST_DEFAULT_MINUTES,
    CONF_BOOST_DEFAULT_TEMP,
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_CO2_SENSOR,
    CONF_COMFORT_TEMP,
    CONF_DOOR_ROOM_A,
    CONF_DOOR_ROOM_B,
    CONF_DOOR_SENSOR,
    CONF_DOORS,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_HOUSE_VOICE_ENABLED,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PERSONS,
    CONF_PID_ENABLED,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_PRECIPITATION_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_ROOMS,
    CONF_TRV_MAX_TEMP,
    CONF_TRV_TYPE,
    CONF_TRVS,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED_SENSOR,
    CONF_WINDOW_SENSORS,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMP,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_PID_KD,
    DEFAULT_PID_KI,
    DEFAULT_PID_KP,
    DEFAULT_TRV_MAX_TEMP,
    DOMAIN,
    FF_MAX_CONTRIBUTION,
    FF_REFERENCE_OUTDOOR_TEMP,
    FF_WEIGHT,
    HOUSE_VOICE_DOMAIN,
    HOUSE_VOICE_SERVICE_SAY,
    NETATMO_API_CALL_DELAY_SEC,
    PRESET_SCHEDULE,
    SCAN_INTERVAL_SECONDS,
    TRV_TYPE_ZIGBEE,
    AutoOffReason,
    ControllerState,
    EffectiveSeason,
    RoomState,
    SeasonMode,
)
from .engine.calibration_engine import CalibrationEngine
from .engine.controller import ControllerEngine
from .engine.door_engine import DoorEngine
from .engine.pid_controller import PidController
from .engine.preheat_engine import PreheatEngine
from .engine.presence_engine import PresenceEngine
from .engine.remote_button_engine import RemoteButtonEngine
from .engine.schedule_engine import ScheduleEngine
from .engine.season_engine import SeasonEngine
from .engine.sync_engine import SyncEngine
from .engine.valve_protection_engine import ValveProtectionEngine
from .engine.window_engine import WindowEngine
from .migrations import migrate_room_to_trvs

_LOGGER = logging.getLogger(__name__)

# Maximum number of events kept in the in-memory log (FIFO)
_MAX_EVENT_LOG = 200

# 3.5 hardening: a room temperature reading outside this range is almost
# certainly a glitching/misbehaving sensor (e.g. reporting -200 or 3000
# instead of going unavailable) rather than a real indoor temperature —
# treated as unavailable so it never reaches the PID/schedule logic.
_ROOM_TEMP_SANITY_MIN = -20.0
_ROOM_TEMP_SANITY_MAX = 50.0


def _sanity_clamp_temp(value: float) -> float | None:
    """Return `value` unchanged if plausible for an indoor temp, else None."""
    if _ROOM_TEMP_SANITY_MIN <= value <= _ROOM_TEMP_SANITY_MAX:
        return value
    return None


class HeatManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Central coordinator for Heat Manager.

    All engines are instantiated here. _async_update_data is the single
    periodic tick driving all time-based logic.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry
        # Registry ID of the global Heat Manager device (set by
        # async_setup_entry() right after this device is created, before
        # platforms are forwarded). Used by room_device_info() as
        # via_device_id — see that method's docstring for why this replaced
        # the old via_device=(DOMAIN, entry_id) tuple form.
        self.global_device_id: str | None = None
        # 2026-09 429/503 fix: every engine that writes to a Netatmo TRV
        # used to pace *its own* sequential calls with
        # asyncio.sleep(NETATMO_API_CALL_DELAY_SEC), which does nothing for
        # concurrent callers — e.g. window_engine spawns one
        # async_create_task() per room, so several rooms closing windows in
        # the same instant each fired a Netatmo call at once regardless of
        # any single engine's own internal pacing. This lock is now shared
        # by every engine via async_call_climate_service() below, so any
        # Netatmo-bound climate call — from any engine, any room, any task —
        # is serialised app-wide instead of racing.
        self._netatmo_call_lock = asyncio.Lock()

        # 2026-09 performance fix: _async_pid_tick() resolves each room's
        # TRV list 3x per room per tick (once via get_room_current_temp()'s
        # internal get_homekit_climate_entity() call, once via its own
        # direct get_homekit_climate_entity() call, once via get_room_trvs()
        # for the write loop) — all 3 route through get_all_room_trvs(),
        # which re-scans self.rooms and re-runs migrate_room_to_trvs() every
        # time. None (disabled) outside a PID tick, so all 29 other call
        # sites across the codebase see get_all_room_trvs() behave exactly
        # as before — only _async_pid_tick() activates it (see that method)
        # for the duration of one tick. Safe even though the tick awaits
        # between rooms (a config change could land there): each room's 3
        # reads all happen back-to-back with no await in between, and no
        # room is ever read a second time later in the same tick — so
        # whichever value was live at the *start* of a room's turn is what
        # every one of that room's 3 reads sees, tick-cache or not.
        self._trv_cache: dict[str, list[dict[str, Any]]] | None = None

        # ── Shared runtime state ──────────────────────────────────────────────
        self.room_states: dict[str, RoomState] = {}
        # Restore persisted season_mode if present (set via select entity)
        _saved_season = self.config.get("season_mode", SeasonMode.AUTO.value)
        try:
            self.season_mode: SeasonMode = SeasonMode(_saved_season)
        except ValueError:
            self.season_mode = SeasonMode.AUTO
        self.effective_season: EffectiveSeason = EffectiveSeason.ACTIVE
        self.outdoor_temperature: float | None = None
        self._event_log: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENT_LOG)
        # Persist the event log once a day (on date change) and on shutdown,
        # so it survives an unclean HA restart. See _persist_event_log_snapshot().
        self._event_log_persist_date: str = ""
        # B18 Fase 3: per-room group toggle (RoomGroupToggleSwitch) — only
        # meaningful for a room with 2+ physical TRVs; default True (grouped).
        # Read by get_room_trvs() below, so it must exist before SyncEngine
        # (and any other engine) is constructed just below.
        self.room_group_enabled: dict[str, bool] = {}
        # v0.14.0: which caller last engaged a room's OVERRIDE state —
        # "switch" (RoomOverrideSwitch) or "remote" (RemoteButtonEngine).
        # Cleared automatically by set_room_state() whenever a room leaves
        # OVERRIDE, from ANY code path (presence/window restore, sync_engine
        # forcing OVERRIDE directly, etc.) — see set_room_state() below.
        # Purely informational: read by websocket.py/sensor.py so the
        # frontend can show which caller is currently holding a room in
        # manual mode. Never gates any control-flow decision.
        self.room_override_source: dict[str, str] = {}

        # 2026-09 fix: ws_set_room_temp's duration_min was accepted and
        # logged but never actually wired to anything — a manual panel
        # temperature stayed in effect forever regardless of the requested
        # duration. Maps room_name → the UTC timestamp at which a
        # duration-limited manual override should auto-restore to schedule.
        # Only holds an entry for rooms with a *timed* override (duration_min
        # > 0); a permanent override (duration_min == 0) has no entry here.
        # Popped automatically by set_room_state() whenever a room leaves
        # OVERRIDE for any reason, exactly like room_override_source.
        self.room_override_expires_at: dict[str, datetime] = {}

        # v0.15.0: last action taken by the global physical remote (any of
        # the 3 configurable button entities — see
        # engine/remote_button_engine.py and CONF_BUTTON_*). Purely
        # informational, written via set_remote_last_action() below and
        # read by sensor.py's RemoteLastActionSensor (Hub device) so a
        # button press's effect is visible at a glance without digging
        # through the History tab. None until the remote has acted at least
        # once since HA started.
        self.remote_last_action: dict[str, Any] | None = None

        # ── Engines ───────────────────────────────────────────────────────────
        self.controller = ControllerEngine(self)
        self.presence_engine = PresenceEngine(self)
        self.window_engine = WindowEngine(self)
        self.door_engine = DoorEngine(self)
        self.season_engine = SeasonEngine(self)
        self.preheat_engine = PreheatEngine(self)
        self.valve_protection = ValveProtectionEngine(self)
        self.calibration_engine = CalibrationEngine(self)
        self.sync_engine = SyncEngine(self)
        self.schedule_engine = ScheduleEngine(self)
        self.remote_button_engine = RemoteButtonEngine(self)

        self.pid_controllers: dict[str, PidController] = {}
        self._init_pid_controllers()
        # B2: boost state per room
        self.boost_active_rooms: dict[str, bool] = {}
        # Boost auto-expiry (Phase B) — None when no boost is active
        self.boost_expires_at: datetime | None = None
        # B18 Fase 3: per-room, non-destructive temperature shift applied on
        # top of that room's PID target — see number.py RoomOffsetNumber
        # (only created for rooms with 2+ physical TRVs). Restored from each
        # RestoreNumber entity on startup, not persisted here directly.
        # Replaces the old single global coordinator.group_offset (v0.9.0).
        self.room_offsets: dict[str, float] = {}
        # Last setpoint the PID tick actually computed/wrote for a room —
        # read-only cache used by SyncEngine to tell an external/manual TRV
        # change apart from Heat Manager's own last write, without having
        # to instrument every write call-site individually.
        self.last_expected_setpoint: dict[str, float] = {}
        # Per-room target-temperature override from an active schedule/
        # calendar block — see engine/schedule_engine.py. Absent (no key)
        # for a room with no CONF_SCHEDULE_ENTITY configured, or whose
        # block/event isn't currently active.
        self.schedule_override: dict[str, float] = {}
        # B10: restore persisted event log on startup
        self._restore_event_log()

        # Snapshot of rooms/persons at last successful setup — used by
        # __init__.py's _async_update_listener to decide whether an
        # entry.options write actually needs a full reload (only true when
        # rooms/persons themselves changed) or can be skipped (internal
        # writes like the midnight energy snapshot, season_mode persistence,
        # or a panel config save — all already applied live via self.config).
        self._last_known_rooms: list[dict[str, Any]] = list(self.rooms)
        self._last_known_persons: list[dict[str, Any]] = list(self.persons)

        _LOGGER.debug(
            "Coordinator initialised — %d room(s), %d person(s)",
            len(self.rooms),
            len(self.persons),
        )

    # ── Config helpers ────────────────────────────────────────────────────────

    @property
    def config(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def rooms(self) -> list[dict[str, Any]]:
        return self.config.get(CONF_ROOMS, [])

    @property
    def persons(self) -> list[dict[str, Any]]:
        return self.config.get(CONF_PERSONS, [])

    @property
    def doors(self) -> list[dict[str, Any]]:
        return self.config.get(CONF_DOORS, [])

    def get_room_doors(self, room_name: str) -> list[dict[str, Any]]:
        """Every configured interior door touching this room, either side."""
        return [
            d
            for d in self.doors
            if d.get(CONF_DOOR_ROOM_A) == room_name
            or d.get(CONF_DOOR_ROOM_B) == room_name
        ]

    def get_door_other_room(self, door: dict[str, Any], room_name: str) -> str:
        """Given a door dict and one of its two rooms, return the other one."""
        if door.get(CONF_DOOR_ROOM_A) == room_name:
            return door.get(CONF_DOOR_ROOM_B, "")
        return door.get(CONF_DOOR_ROOM_A, "")

    def is_room_door_open(self, room_name: str) -> bool:
        """True if ANY interior door connected to this room is currently open.

        Used by CalibrationEngine to pick which of a room's two learned
        heat-up-rate profiles to use — see engine/calibration_engine.py.
        """
        for door in self.get_room_doors(room_name):
            sensor_id = door.get(CONF_DOOR_SENSOR)
            if not sensor_id:
                continue
            state = self.hass.states.get(sensor_id)
            if state and state.state == "on":
                return True
        return False

    @property
    def alarm_panel(self) -> str | None:
        return self.config.get(CONF_ALARM_PANEL) or None

    # ── Device registry helpers ───────────────────────────────────────────────

    def global_device_info(self) -> DeviceInfo:
        """DeviceInfo for the single Heat Manager integration device.

        All global entities (controller state, season mode, energy sensors, etc.)
        belong to this device.
        """
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Heat Manager",
            manufacturer="Heat Manager",
            model="Multi-room heating controller",
            entry_type="service",  # type: ignore[arg-type]
        )

    def room_device_info(self, room_name: str) -> DeviceInfo:
        """DeviceInfo for a per-room virtual device.

        All per-room entities (state, window, mold risk, override, pid power)
        belong to their room device, which is linked to the global device via
        via_device_id (the global device's actual device-registry ID).

        HA 2026.9 deprecated the old via_device=(DOMAIN, identifier) tuple
        form on DeviceInfo/async_get_or_create — identifiers are no longer
        guaranteed unique across config entries, so the registry can't
        reliably resolve a parent from them anymore. async_setup_entry()
        creates the global device explicitly (dr.async_get_or_create) before
        forwarding platform setups and stores the resulting DeviceEntry.id on
        self.global_device_id, so this method never has to look the parent
        up itself — that also sidesteps a race where a room device could
        otherwise be created before the global device exists (platforms are
        forwarded concurrently via async_forward_entry_setups).
        """
        safe = room_name.lower().replace(" ", "_")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{safe}")},
            name=room_name,
            manufacturer="Heat Manager",
            model="Room",
            via_device_id=self.global_device_id,
        )

    @property
    def weather_entity(self) -> str | None:
        return self.config.get(CONF_WEATHER_ENTITY) or None

    # ── State helpers ─────────────────────────────────────────────────────────

    @property
    def controller_state(self) -> ControllerState:
        return self.controller.state

    @property
    def auto_off_reason(self) -> AutoOffReason:
        return self.controller.auto_off_reason

    @property
    def pause_remaining_minutes(self) -> int:
        return self.controller.pause_remaining_minutes

    def get_room_state(self, room_name: str) -> RoomState:
        return self.room_states.get(room_name, RoomState.NORMAL)

    def set_room_state(self, room_name: str, state: RoomState) -> None:
        # v0.14.0: a room leaving OVERRIDE (for ANY reason — this switch,
        # the remote, presence/window restoring the schedule, sync_engine
        # forcing state directly, ...) always drops its recorded override
        # source. Checked unconditionally, ahead of the old==state early
        # return below, so a stale source can never survive.
        if state != RoomState.OVERRIDE:
            self.room_override_source.pop(room_name, None)
            self.room_override_expires_at.pop(room_name, None)

        old = self.room_states.get(room_name)
        if old == state:
            return
        _LOGGER.debug("Room '%s': %s → %s", room_name, old, state.value)
        self.room_states[room_name] = state
        self.async_update_listeners()

    def get_climate_entity(self, room_name: str) -> str | None:
        """Return the room's primary TRV climate entity.

        Resolves via get_all_room_trvs() (CONF_TRVS, migrated on the fly),
        not the room's flat CONF_CLIMATE_ENTITY field directly — that flat
        field is only ever mirrored from trvs[0] in memory by
        migrate_room_to_trvs(); config_flow's per-TRV edit UI writes
        CONF_TRVS only; nothing re-persists the flat mirror to storage
        afterward. Reading the flat field directly here returned None for
        any room saved through that UI even once. See B18 Fase 3 / #room-
        detail-battery for the bug this fixed (Sætpunkt/Trv temp/valve %
        silently blank in the panel, window-open heat reduction silently
        skipped in window_engine.py).
        """
        trvs = self.get_all_room_trvs(room_name)
        return trvs[0].get(CONF_CLIMATE_ENTITY) if trvs else None

    # ── Multi-TRV helpers (B18 Fase 2 — TRV grouping) ───────────────────────
    #
    # A room can now hold more than one physical TRV (CONF_TRVS — see Fase 1
    # / migrations.py). "Grouping" means: one PID loop per room computes a
    # single target/setpoint, which is then sent identically to every TRV
    # configured for that room. These helpers are the read side of that —
    # get_room_trvs() always returns at least a synthesized single-TRV list
    # for a room using only the old flat fields (climate_entity, trv_type,
    # ...), via the same pure migrate_room_to_trvs() used by the one-time
    # config-entry migration. That keeps every caller — and every existing
    # test that builds a plain flat room dict — working unchanged for
    # single-TRV rooms, without needing async_migrate_entry() to have run
    # first.
    #
    # get_climate_entity()/get_homekit_climate_entity() above resolve the
    # room's primary (first) TRV via get_all_room_trvs() (CONF_TRVS),
    # not the room's flat mirror fields — those are only synthesized in
    # memory by migrate_room_to_trvs() and are never re-persisted to the
    # config entry after an edit through the per-TRV UI, which writes
    # CONF_TRVS only. get_write_entity()/needs_cloud_delay() call those two
    # helpers, so they're covered too. This is correct for every read-only
    # use (sensors, the panel/card, other engines not yet converted) that
    # only needs "the" room entity. Only the *command* call sites — the
    # ones that actually write a climate service call — loop the multi-TRV
    # helpers below instead.

    def get_all_room_trvs(self, room_name: str) -> list[dict[str, Any]]:
        """Return every physical TRV *configured* for a room, structurally —
        ignoring the per-room group toggle (B18 Fase 3).

        Always at least a single-element list (synthesized from the room's
        flat fields) for a room with a usable climate entity; empty for a
        room with none configured at all. Use this for entity setup
        (deciding whether a room qualifies for the per-room offset/
        group-toggle entities, which only exist for 2+ TRV rooms) and any
        other structural/configuration read. Command call sites — anything
        that actually writes a climate service call — should use
        get_room_trvs() instead.
        """
        if self._trv_cache is not None and room_name in self._trv_cache:
            return self._trv_cache[room_name]

        trvs: list[dict[str, Any]] = []
        for room in self.rooms:
            if room.get("room_name") == room_name:
                trvs = migrate_room_to_trvs(room).get(CONF_TRVS, [])
                break

        if self._trv_cache is not None:
            self._trv_cache[room_name] = trvs
        return trvs

    def get_room_trvs(self, room_name: str) -> list[dict[str, Any]]:
        """Return every physical TRV Heat Manager should currently *command*
        for a room. Every command call site (PID tick, boost, away/window/
        preheat, valve protection, sync engine, controller off-fallback,
        the override switch, WS manual-temperature commands) loops this —
        never get_all_room_trvs() — to fan a climate service call out.

        Normally identical to get_all_room_trvs(). B18 Fase 3: when a 2+ TRV
        room's group toggle (RoomGroupToggleSwitch) is OFF, this narrows to
        just the primary (first) TRV — every secondary TRV is released for
        independent/manual control until the toggle is switched back on. A
        single-TRV room has no toggle entity and is never affected.
        """
        trvs = self.get_all_room_trvs(room_name)
        if len(trvs) > 1 and not self.room_group_enabled.get(room_name, True):
            return trvs[:1]
        return trvs

    def set_room_group_enabled(self, room_name: str, enabled: bool) -> None:
        """Set a room's group-toggle state (called by RoomGroupToggleSwitch)
        and immediately rebuild SyncEngine's entity→TRV map so a
        just-ungrouped secondary TRV stops being monitored (and a
        just-regrouped one starts being monitored again) without requiring
        an integration reload."""
        self.room_group_enabled[room_name] = enabled
        self.sync_engine.rebuild_entity_map()
        self.async_update_listeners()

    @staticmethod
    def get_trv_climate_entity(trv: dict[str, Any]) -> str | None:
        return trv.get(CONF_CLIMATE_ENTITY) or None

    @staticmethod
    def get_trv_homekit_entity(trv: dict[str, Any]) -> str | None:
        return trv.get(CONF_HOMEKIT_CLIMATE_ENTITY) or None

    def get_trv_write_entity(self, trv: dict[str, Any]) -> str | None:
        """Preferred write entity for one physical TRV — same
        HomeKit-first-if-reachable, else-cloud priority as
        get_write_entity(), just scoped to a single TRV dict instead of a
        room's flat fields. Used by command sites that already followed
        this reachability-fallback policy for the room's primary TRV
        (boost, window-open, valve exercise, the WS manual-temperature
        command) and now fan the same policy out per TRV.
        """
        hk_id = self.get_trv_homekit_entity(trv)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return hk_id
        return self.get_trv_climate_entity(trv)

    def get_room_write_entities(self, room_name: str) -> list[str]:
        """Write entity for every TRV configured in this room (order
        preserved, duplicates dropped) — see get_trv_write_entity()."""
        seen: set[str] = set()
        out: list[str] = []
        for trv in self.get_room_trvs(room_name):
            entity = self.get_trv_write_entity(trv)
            if entity and entity not in seen:
                seen.add(entity)
                out.append(entity)
        return out

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

        enable=False mirrors async_turn_off(): only marks the room NORMAL.
        No TRV commands are sent — the coordinator's normal schedule/PID
        sync resumes control on its next tick.

        Returns True if the room's state actually changed the physical
        TRVs (enable=True: at least one TRV command succeeded; enable=False:
        always True), so a caller can decide whether to log/notify.
        """
        if not enable:
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
            try:
                if trv_type == TRV_TYPE_ZIGBEE:
                    write_id = self.get_trv_write_entity(trv) or climate_id
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": write_id, "hvac_mode": "heat"},
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": climate_id, "preset_mode": PRESET_SCHEDULE},
                        blocking=True,
                    )
                any_ok = True
                _LOGGER.info("Override ON: %s \u2192 heating (%s)", room_name, trv_type)
            # broad-except-rationale: one entity failing must not abort the others in this loop
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Override turn_on failed for %s: %s", room_name, err)

        if any_ok:
            self.set_room_state(room_name, RoomState.OVERRIDE)
            self.room_override_source[room_name] = source
        return any_ok

    def set_remote_last_action(self, description: str, rooms: list[str]) -> None:
        """Record the most recent action taken by the global physical
        remote (v0.14.0's temp up/down/mode toggle buttons) — called from
        engine/remote_button_engine.py after a successful action.

        Purely informational: read by sensor.py's RemoteLastActionSensor
        (Hub device). Never gates any control-flow decision.
        """
        self.remote_last_action = {
            "description": description,
            "rooms": rooms,
            "timestamp": utcnow().isoformat(),
        }
        self.async_update_listeners()

    def trv_needs_cloud_delay(self, trv: dict[str, Any]) -> bool:
        """Per-TRV equivalent of needs_cloud_delay() — True unless this
        TRV's own HomeKit entity is configured and currently reachable."""
        hk_id = self.get_trv_homekit_entity(trv)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return False
        return True

    def _init_pid_controllers(self) -> None:
        kp = float(self.config.get(CONF_PID_KP, DEFAULT_PID_KP))
        ki = float(self.config.get(CONF_PID_KI, DEFAULT_PID_KI))
        kd = float(self.config.get(CONF_PID_KD, DEFAULT_PID_KD))
        for room in self.rooms:
            name = room.get("room_name", "")
            if name:
                self.pid_controllers[name] = PidController(
                    kp=kp, ki=ki, kd=kd, room_name=name
                )

    @property
    def pid_enabled(self) -> bool:
        return bool(self.config.get(CONF_PID_ENABLED, True))

    @property
    def trv_max_temp(self) -> float:
        return float(self.config.get(CONF_TRV_MAX_TEMP, DEFAULT_TRV_MAX_TEMP))

    def get_pid(self, room_name: str) -> PidController | None:
        return self.pid_controllers.get(room_name)

    def get_homekit_climate_entity(self, room_name: str) -> str | None:
        """Return the room's primary TRV HomeKit climate entity, if set.

        See get_climate_entity() — same fix, same reason: resolves via the
        primary TRV's CONF_TRVS entry rather than the stale flat mirror.
        """
        trvs = self.get_all_room_trvs(room_name)
        if not trvs:
            return None
        val = trvs[0].get(CONF_HOMEKIT_CLIMATE_ENTITY)
        return val if val else None

    def get_room_calibration_entity(self, room_name: str) -> str | None:
        """Return the room's primary TRV calibration/offset number entity, if set.

        See get_climate_entity() — same fix, same reason: resolves via the
        primary TRV's CONF_TRVS entry rather than the room's flat
        CONF_CALIBRATION_ENTITY mirror, which is never re-persisted after an
        edit through the per-TRV UI.
        """
        trvs = self.get_all_room_trvs(room_name)
        if not trvs:
            return None
        val = trvs[0].get(CONF_CALIBRATION_ENTITY)
        return val if val else None

    def get_write_entity(self, room_name: str) -> str | None:
        """H-4: Return the preferred write entity for a room.

        Priority:
          1. HomeKit climate entity (local LAN, <100 ms, no rate limits)
          2. Cloud climate entity (fallback)

        Use this for all set_temperature writes. Do NOT use for
        preset_mode writes (away/schedule) — those must still go to the
        cloud entity because preset_mode is not supported via HomeKit HAP.
        """
        hk_id = self.get_homekit_climate_entity(room_name)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return hk_id
        return self.get_climate_entity(room_name)

    def needs_cloud_delay(self, room_name: str) -> bool:
        """H-6: Return True if the write entity for this room is the cloud entity.

        Used to decide whether NETATMO_API_CALL_DELAY_SEC should be applied
        after a service call. HomeKit writes are local and need no stagger.
        """
        hk_id = self.get_homekit_climate_entity(room_name)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return False  # Writing to HomeKit — no delay needed
        return True  # Writing to cloud — stagger to avoid 429

    async def async_call_climate_service(
        self,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        *,
        needs_delay: bool,
    ) -> None:
        """Call climate.<service> on entity_id — the one place any engine
        writes to a climate entity, so Netatmo-bound calls are serialised.

        `needs_delay` should come from needs_cloud_delay(room_name) or
        trv_needs_cloud_delay(trv) — True means this call is NOT reaching a
        currently-reachable HomeKit entity, i.e. it's going to Netatmo's
        cloud. When True, this coroutine takes self._netatmo_call_lock and
        holds it until NETATMO_API_CALL_DELAY_SEC after the call returns,
        so no two Netatmo calls — regardless of which engine, room, or
        asyncio task triggered them — can ever fire concurrently or closer
        together than the pacing interval. See the lock's own comment in
        __init__ for why per-engine-local pacing alone wasn't enough.
        HomeKit calls (needs_delay=False) skip the lock — they're local and
        don't need it.

        Raises whatever hass.services.async_call raises; callers keep their
        own try/except around this to log a per-entity failure and continue
        with the rest of their TRV loop.
        """
        call_data = {"entity_id": entity_id, **(data or {})}
        if not needs_delay:
            await self.hass.services.async_call(
                "climate", service, call_data, blocking=True
            )
            return
        async with self._netatmo_call_lock:
            await self.hass.services.async_call(
                "climate", service, call_data, blocking=True
            )
            await asyncio.sleep(NETATMO_API_CALL_DELAY_SEC)

    def any_window_open(self) -> bool:
        for room in self.rooms:
            for sensor in room.get(CONF_WINDOW_SENSORS, []):
                state = self.hass.states.get(sensor)
                if state and state.state == "on":
                    return True
        return False

    def someone_home(self) -> bool:
        for person in self.persons:
            if not person.get("person_tracking", True):
                continue
            entity_id = person.get("person_entity", "")
            state = self.hass.states.get(entity_id)
            if state and state.state == "home":
                return True
        return False

    # ── Sensor input helpers (v0.2.9) ─────────────────────────────────────────

    def get_room_co2(self, room_name: str) -> float | None:
        """Return current CO₂ level (ppm) for a room, or None."""
        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            entity_id = room.get(CONF_CO2_SENSOR) or None
            if not entity_id:
                return None
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                return None
            try:
                return float(state.state)
            except (TypeError, ValueError):
                return None
        return None

    def get_room_co2_threshold(self, room_name: str) -> int:
        """Return the CO₂ ventilation threshold (ppm) for a room.

        Uses per-room CONF_CO2_THRESHOLD when configured, otherwise falls
        back to the global DEFAULT_CO2_VENTILATION_THRESHOLD.
        """
        from .const import CONF_CO2_THRESHOLD, DEFAULT_CO2_VENTILATION_THRESHOLD

        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            val = room.get(CONF_CO2_THRESHOLD)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
            break
        return DEFAULT_CO2_VENTILATION_THRESHOLD

    def get_outdoor_humidity(self) -> float | None:
        """Return outdoor relative humidity (%) from CONF_OUTDOOR_HUMIDITY_SENSOR."""
        entity_id = self.config.get(CONF_OUTDOOR_HUMIDITY_SENSOR) or None
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def get_precipitation(self) -> float | None:
        """Return current precipitation (mm or mm/h) from CONF_PRECIPITATION_SENSOR."""
        entity_id = self.config.get(CONF_PRECIPITATION_SENSOR) or None
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def get_wind_speed(self) -> float | None:
        """Return current wind speed (m/s) from CONF_WIND_SPEED_SENSOR."""
        entity_id = self.config.get(CONF_WIND_SPEED_SENSOR) or None
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def is_raining(self) -> bool:
        """Return True when precipitation sensor reads > 0."""
        precip = self.get_precipitation()
        return precip is not None and precip > 0.0

    def get_room_current_temp(self, room_name: str, climate_id: str) -> float | None:
        """
        Return the best available current temperature for a room (°C).

        Priority:
        1. CONF_ROOM_TEMP_SENSOR — external probe, independent of the TRV body.
           Zigbee TRVs especially benefit: their built-in sensor sits on the
           hot radiator and reads 1–3 °C higher than actual room temperature.
        2. HomeKit climate entity current_temperature (Netatmo local HAP).
        3. Cloud climate entity current_temperature (fallback).

        Returns None only if all sources are unavailable — a value outside
        _ROOM_TEMP_SANITY_MIN/_MAX (3.5 hardening: a glitching sensor can
        report e.g. -200 or 3000 instead of going unavailable) also counts
        as unavailable rather than being fed into the PID/schedule logic.
        """
        # 1. External room temperature sensor
        for room in self.rooms:
            if room.get("room_name") != room_name:
                continue
            entity_id = room.get(CONF_ROOM_TEMP_SENSOR) or None
            if entity_id:
                state = self.hass.states.get(entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        val = _sanity_clamp_temp(float(state.state))
                        if val is not None:
                            return val
                    except (TypeError, ValueError):
                        pass
            break  # room found, external sensor absent or unavailable

        # 2. HomeKit entity (Netatmo local HAP — fresher than cloud)
        hk_id = self.get_homekit_climate_entity(room_name)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                try:
                    raw = state.attributes.get("current_temperature")
                    if raw is not None:
                        val = _sanity_clamp_temp(float(raw))
                        if val is not None:
                            return val
                except (TypeError, ValueError):
                    pass

        # 3. Cloud / primary climate entity
        if climate_id:
            state = self.hass.states.get(climate_id)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    raw = state.attributes.get("current_temperature")
                    if raw is not None:
                        val = _sanity_clamp_temp(float(raw))
                        if val is not None:
                            return val
                except (TypeError, ValueError):
                    pass

        return None

    # ── Blocking sources (self-reporting diagnostics) ────────────────────────
    # Mirrors climate_group_helper's `blocking_sources` attribute: lets the
    # panel/card explain *why* a room isn't heating without the user having
    # to cross-reference controller_state + room_state manually.

    def get_room_blocking_sources(self, room_name: str) -> list[str]:
        """Return the reasons this room's heating commands are held back.

        Pure function over already-tracked state (controller_state,
        room_state) — introduces no new state. Empty list means nothing is
        blocking the room.
        """
        sources: list[str] = []
        if self.controller_state == ControllerState.OFF:
            sources.append("controller_off")
        elif self.controller_state == ControllerState.PAUSE:
            sources.append("controller_pause")

        state = self.get_room_state(room_name)
        if state == RoomState.WINDOW_OPEN:
            sources.append("window")
        elif state == RoomState.AWAY:
            sources.append("presence")
        return sources

    def global_blocking_sources(self) -> list[str]:
        """Deduplicated blocking reasons currently active across all rooms."""
        sources: set[str] = set()
        for room in self.rooms:
            name = room.get("room_name", "")
            if name:
                sources.update(self.get_room_blocking_sources(name))
        return sorted(sources)

    # ── Season engine helpers (I-2) ──────────────────────────────────────────

    @property
    def calendar_season(self) -> SeasonMode:
        """Isolated access to season_engine — avoids direct engine coupling in platforms."""
        return self.season_engine.calendar_season

    @property
    def days_above_threshold(self) -> int:
        """Isolated access to season_engine — avoids direct engine coupling in platforms."""
        return self.season_engine.days_above_threshold

    # ── Boost (shared by heat_manager.boost_start/stop service and
    # ── heat_manager/boost_start/stop WS command) ─────────────────────

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
            write_entities = self.get_room_write_entities(room_name)
            if not write_entities:
                continue
            room_ok = False
            for write_entity in write_entities:
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": write_entity, "temperature": temp},
                        blocking=True,
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

        detail = (
            f" — {', '.join(boosted)}" if boosted else " — ingen rum klar til boost"
        )
        self.log_event(f"Boost aktiveret{detail}", reason="manuel", event_type="boost")
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
        self.log_event("Boost deaktiveret", reason="manuel", event_type="boost")
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
                await self.async_call_climate_service(
                    "set_preset_mode",
                    entity_id,
                    {"preset_mode": "schedule"},
                    needs_delay=True,
                )
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
            self.log_event(
                f"{room_name}: manuel override udløbet — plan gendannet",
                reason="auto",
                event_type="manual",
            )
            _LOGGER.info("Room '%s' manual override expired — auto-restored", room_name)

    # ── Event log ─────────────────────────────────────────────────────────────

    def log_event(
        self,
        description: str,
        reason: str = "",
        event_type: str = "normal",
    ) -> None:
        from homeassistant.util.dt import now as ha_now

        now = ha_now()
        time_str = now.strftime("%H:%M")
        self._event_log.appendleft(
            {
                "time": time_str,
                "description": description,
                "reason": reason,
                "type": event_type,
                "timestamp": now.isoformat(),
            }
        )
        _LOGGER.debug("Event logged: %s (%s)", description, reason)

    # ── Event log persistence ────────────────────────────────────────────────

    def _persist_event_log_snapshot(self) -> None:
        """Persist the event log snapshot into entry.options (survives HA restarts).

        Called once a day (on date change) and on shutdown, so the log isn't
        lost on an unclean restart.
        """
        import json

        event_snap = list(self._event_log)[:50]
        options = dict(self.entry.options)
        options["_event_log_snap"] = json.dumps(event_snap)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        _LOGGER.debug("Event log persisted (%d entries)", len(event_snap))

    def _restore_event_log(self) -> None:
        """Restore event log from persisted snapshot on startup (B10)."""
        import json

        raw = self.entry.options.get("_event_log_snap", "[]")
        try:
            events = json.loads(raw)
            for e in reversed(events):
                self._event_log.appendleft(e)
            _LOGGER.debug("Event log restored: %d entries", len(events))
        except (ValueError, TypeError):
            pass

    # ── Outdoor temperature ───────────────────────────────────────────────────

    def _refresh_outdoor_temperature(self) -> None:
        """
        Update self.outdoor_temperature from the best available source.

        Priority:
        1. CONF_OUTDOOR_TEMP_SENSOR — local weather station / Netatmo outdoor
           module / Aqara etc.  Updates every 5 min or faster; reflects the
           actual microclimate at the property rather than a forecast grid point.
        2. weather.* entity temperature attribute — existing behaviour, used as
           fallback when the dedicated sensor is absent or unavailable.
           Tries "temperature", "current_temperature" and "temp" attribute
           keys in that order (B12 fix), since not all weather integrations
           expose the same attribute name.
        """
        # 1. Local outdoor temperature sensor (v0.2.9)
        outdoor_sensor = self.config.get(CONF_OUTDOOR_TEMP_SENSOR) or None
        if outdoor_sensor:
            state = self.hass.states.get(outdoor_sensor)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    self.outdoor_temperature = float(state.state)
                    return
                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "Could not parse outdoor temperature from sensor %s",
                        outdoor_sensor,
                    )

        # 2. Fallback: weather entity attribute
        entity_id = self.weather_entity
        if not entity_id:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return
        for temp_key in ("temperature", "current_temperature", "temp"):
            temp = state.attributes.get(temp_key)
            if temp is None:
                continue
            try:
                self.outdoor_temperature = float(temp)
                break
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "Could not parse outdoor temperature '%s' from %s (%s)",
                    temp,
                    entity_id,
                    temp_key,
                )
                continue

    def wake_setback_delta(self) -> float:
        """Return the wake setback delta in °C. 0.0 when not in WAKING phase.

        Applied to PID setpoints during the transitional WAKING phase so the
        system heats gently rather than at full winter capacity.
        """
        from .const import CONF_WAKE_SETBACK_TEMP, DEFAULT_WAKE_SETBACK_TEMP

        if self.effective_season != EffectiveSeason.WAKING:
            return 0.0
        return float(self.config.get(CONF_WAKE_SETBACK_TEMP, DEFAULT_WAKE_SETBACK_TEMP))

    def is_night_setback_active(self) -> bool:
        """Return True when night setback is enabled and the current time is within
        the configured night window (CONF_NIGHT_START_HOUR – CONF_NIGHT_END_HOUR).

        The window may span midnight, e.g. 23:00 – 07:00.
        """
        from .const import (
            CONF_NIGHT_END_HOUR,
            CONF_NIGHT_SETBACK_ENABLED,
            CONF_NIGHT_START_HOUR,
            DEFAULT_NIGHT_END_HOUR,
            DEFAULT_NIGHT_SETBACK_ENABLED,
            DEFAULT_NIGHT_START_HOUR,
        )

        if not self.config.get(
            CONF_NIGHT_SETBACK_ENABLED, DEFAULT_NIGHT_SETBACK_ENABLED
        ):
            return False

        from homeassistant.util.dt import now as ha_now

        hour = ha_now().hour
        start = int(self.config.get(CONF_NIGHT_START_HOUR, DEFAULT_NIGHT_START_HOUR))
        end = int(self.config.get(CONF_NIGHT_END_HOUR, DEFAULT_NIGHT_END_HOUR))

        # Window may span midnight (e.g. 23 – 7)
        if start > end:
            return hour >= start or hour < end
        # Same-day window (unusual, but handle it)
        return start <= hour < end

    def night_setback_delta(self) -> float:
        """Return the setback delta in °C. 0.0 when setback is not active."""
        from .const import CONF_NIGHT_SETBACK_TEMP, DEFAULT_NIGHT_SETBACK_TEMP

        if not self.is_night_setback_active():
            return 0.0
        return float(
            self.config.get(CONF_NIGHT_SETBACK_TEMP, DEFAULT_NIGHT_SETBACK_TEMP)
        )

    # ── Periodic update ───────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Called every SCAN_INTERVAL_SECONDS.

        Tick order:
          1. Refresh outdoor temperature (local sensor preferred, weather fallback)
          2. Season engine (resolve AUTO → WINTER/SUMMER)
          3. Controller (pause expiry, auto-off, auto-resume)
          4. Presence engine (grace period countdowns)
          5. Window engine (open-window escalation warnings)
          6. Waste calculator (energy accounting)
          7. Preheat engine (travel_time polling no-op)
          8. Valve protection (weekly exercise)
          9. Calibration engine (write external sensor delta to TRV calibration)
          10. Schedule engine (resolve active schedule/calendar block overrides)
          11. PID tick (proportional TRV setpoints for NORMAL rooms)
          12. Boost expiry check (auto-restore once boost duration elapses)

        SyncEngine is event-driven (state-change listeners registered in its
        own constructor), not part of this polling tick.

        Each engine is isolated: an exception in one engine is logged and
        skipped rather than taking down the entire tick and marking all
        entities unavailable.
        """
        self._refresh_outdoor_temperature()

        try:
            await self.season_engine.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("season_engine tick failed: %s", err)

        try:
            await self.controller.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("controller tick failed: %s", err)

        try:
            await self.presence_engine.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("presence_engine tick failed: %s", err)

        try:
            await self.window_engine.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("window_engine tick failed: %s", err)

        try:
            await self.preheat_engine.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("preheat_engine tick failed: %s", err)

        try:
            await self.valve_protection.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("valve_protection tick failed: %s", err)

        try:
            await self.calibration_engine.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("calibration_engine tick failed: %s", err)

        try:
            await self.schedule_engine.async_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("schedule_engine tick failed: %s", err)

        try:
            await self._async_pid_tick()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("pid_tick failed: %s", err)

        try:
            await self._async_check_boost_expiry()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("boost expiry check failed: %s", err)

        try:
            await self._async_check_room_override_expiry()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("room override expiry check failed: %s", err)

        # Persist the event log once a day, on date change.
        from homeassistant.util.dt import now as ha_now

        today_str = ha_now().date().isoformat()
        if self._event_log_persist_date and self._event_log_persist_date != today_str:
            self._persist_event_log_snapshot()
        self._event_log_persist_date = today_str

        return {
            "controller_state": self.controller.state,
            "season_mode": self.season_mode,
            "effective_season": self.effective_season.value,
            "outdoor_temperature": self.outdoor_temperature,
            "room_states": dict(self.room_states),
            "pause_remaining_minutes": self.pause_remaining_minutes,
        }

    def get_room_target_temp(self, room: dict[str, Any]) -> float:
        """Resolve a room's PID target temperature (°C), before PID power/
        setpoint mapping.

        Layers, identical for every TRV type since v0.19.0 (B21 — Heat
        Manager is the sole target authority regardless of manufacturer):

            CONF_COMFORT_TEMP → schedule_override → room_offset → setback

        Shared by _async_pid_tick() (drives the PID) and ws_get_state()
        (drives the panel's target-temp display, Fase 2), so the two can
        never drift apart — see
        audit/heat_manager_target_temp_analysis_2026-09-11.md.
        """
        room_name = room.get("room_name", "")
        target_temp = float(room.get(CONF_COMFORT_TEMP, DEFAULT_COMFORT_TEMP))

        # ── Schedule override (v0.9.0, Fase D) ──────────────────────────────
        # An active block on the room's CONF_SCHEDULE_ENTITY replaces the
        # comfort_temp base. Read fresh every tick by
        # schedule_engine.async_tick() earlier in this same coordinator tick
        # — releases automatically once the block/event ends, no state to
        # restore.
        schedule_temp = self.schedule_override.get(room_name)
        if schedule_temp is not None:
            target_temp = schedule_temp

        # ── Room offset (B18 Fase 3) — non-destructive per-room shift ───────
        # Mirrors climate_group_helper's "Group Offset": it automatically
        # follows the next schedule/season transition since it is never
        # baked into a stored target, only ever added at read time. See
        # number.py RoomOffsetNumber.
        room_offset = self.room_offsets.get(room_name, 0.0)
        if room_offset:
            target_temp += room_offset

        # ── Setbacks: night + wake — applied cumulatively ───────────────────
        setback = self.night_setback_delta() + self.wake_setback_delta()
        if setback > 0.0:
            before = target_temp
            target_temp = max(
                target_temp - setback,
                float(room.get("away_temp_override", 10.0)),
            )
            _LOGGER.debug(
                "Setback [%s]: %.1f°C → %.1f°C (night=−%.1f°C wake=−%.1f°C)",
                room_name,
                before,
                target_temp,
                self.night_setback_delta(),
                self.wake_setback_delta(),
            )

        return target_temp

    async def _async_pid_tick(self) -> None:
        """
        Drive the PID controller for every room currently in NORMAL state.

        v0.8.0: generalised to a hybrid PID + outdoor-feedforward engine that
        now regulates BOTH room types, not just Netatmo HomeKit rooms.

        v0.19.0: CONF_COMFORT_TEMP is now the target for BOTH room types —
        Heat Manager is the sole authority for room target temperature,
        regardless of TRV manufacturer:

          - Netatmo rooms (homekit_climate_entity set): target_temp comes
            from CONF_COMFORT_TEMP; PID writes to the local HomeKit entity.
            Before 0.19.0 this read the cloud entity's own 'temperature'
            attribute instead — i.e. whatever Netatmo's own app-side
            schedule dictated — which silently overrode the user's
            configured comfort_temp for every Netatmo room (see
            audit/heat_manager_target_temp_analysis_2026-09-11.md). The
            cloud entity is still read for availability/health and for the
            heating_power_request demand percentage, just no longer for
            the target itself.
          - Local rooms (Zigbee today, Matter/Thread later — no
            homekit_climate_entity): unchanged — CONF_COMFORT_TEMP was
            already the target here. PID writes directly to the room's
            single climate_entity, since Zigbee2MQTT/Matter/Thread are
            local with no cloud rate limit.

        Both paths still layer schedule_override, room_offset and the
        night/wake setbacks on top of this base target identically.

        Both paths now also receive a small proactive "feedforward" power
        contribution based on outdoor temperature (see FF_* constants) on
        top of PID's reactive correction — classic weather-compensation
        "heating curve" behaviour. With a 60 s tick and several minutes of
        TRV thermal lag, pure PID only starts correcting once the room has
        already begun cooling; feedforward starts pushing power up as soon
        as the outdoor temperature drops, reducing undershoot during a
        sudden cold snap.

        current_temperature is read via get_room_current_temp() which
        prefers CONF_ROOM_TEMP_SENSOR over HomeKit entity over cloud entity
        — improves accuracy for Zigbee TRV rooms where the TRV's built-in
        probe sits on the hot radiator body and reads 1–3 °C above actual
        room temp.
        """
        if not self.pid_enabled:
            return
        if self.controller_state != ControllerState.ON:
            for pid in self.pid_controllers.values():
                pid.reset()
            return
        # PID runs in both ACTIVE and WAKING phases.
        # WAKING uses a reduced setpoint via wake_setback_delta().
        if self.effective_season == EffectiveSeason.DORMANT:
            for pid in self.pid_controllers.values():
                pid.reset()
            return

        # 2026-09 performance fix: activate the per-tick TRV cache (see
        # get_all_room_trvs()) for the duration of this loop — always
        # reset in the finally, even if a room's processing raises, so a
        # bug here can never leave every other get_all_room_trvs() call
        # site (all 29 of them) silently reading a stale cache forever.
        self._trv_cache = {}
        try:
            for room in self.rooms:
                room_name = room.get("room_name", "")
                if not room_name:
                    continue
                primary_id = self.get_climate_entity(room_name)
                if not primary_id:
                    continue

                pid = self.pid_controllers.get(room_name)
                if pid is None:
                    continue

                if self.get_room_state(room_name) != RoomState.NORMAL:
                    pid.reset()
                    continue

                # ── Read current temperature via unified helper ────────────────
                # Preference: room_temp_sensor → HomeKit entity → cloud entity
                current_temp = self.get_room_current_temp(room_name, primary_id)
                if current_temp is None:
                    pid.reset()
                    continue

                hk_id = self.get_homekit_climate_entity(room_name)

                if hk_id:
                    # ── Netatmo split-entity path ────────────────────────────
                    # v0.19.0: target comes from get_room_target_temp() (same
                    # CONF_COMFORT_TEMP base as the local path below) — see
                    # docstring above. The cloud entity is still read here for
                    # availability/health and the heating_power_request demand
                    # percentage, not for the target itself.
                    write_id = hk_id
                    primary_state = self.hass.states.get(primary_id)
                    if primary_state is None or primary_state.state in (
                        "unavailable",
                        "unknown",
                    ):
                        pid.reset()
                        continue
                    demand_pct = primary_state.attributes.get(
                        "heating_power_request", "?"
                    )
                else:
                    # ── Local TRV path (Zigbee today, Matter/Thread later) ──
                    # Write directly to the room's own climate_entity:
                    # Z2M/Matter/Thread are local, no rate-limit stagger
                    # needed.
                    write_id = primary_id
                    demand_pct = "n/a (local)"

                # ── Target resolution ────────────────────────────────────────
                # comfort_temp → schedule_override → room_offset → setback,
                # identical for both room types since v0.19.0 (B21). Shared
                # with ws_get_state() via get_room_target_temp() so the
                # panel's displayed target can never drift from what the PID
                # actually chases.
                target_temp = self.get_room_target_temp(room)

                # ── PID tick → power fraction 0..1 ──────────────────────────
                power = pid.update(setpoint=target_temp, current=current_temp)

                # ── Outdoor feedforward (weather compensation) ──────────────
                # Proactive contribution added on top of PID's reactive term.
                # Applies to both room types — independent of write target.
                if self.outdoor_temperature is not None:
                    feedforward = min(
                        FF_MAX_CONTRIBUTION,
                        max(
                            0.0,
                            (FF_REFERENCE_OUTDOOR_TEMP - self.outdoor_temperature)
                            * FF_WEIGHT,
                        ),
                    )
                    if feedforward > 0.0:
                        power = min(1.0, power + feedforward)

                trv_setpoint = PidController.power_to_setpoint(
                    power=power,
                    current_temp=current_temp,
                    trv_max=self.trv_max_temp,
                    trv_min=float(room.get("away_temp_override", 10.0)),
                )

                # Record the setpoint this tick computed as "correct" for this
                # room — regardless of whether the suppress-check below actually
                # sends it. SyncEngine reads this to recognise Heat Manager's
                # own expected value and tell a genuine manual/external TRV
                # change apart from it, without duplicating this whole
                # computation (which would double-advance the PID integrator).
                self.last_expected_setpoint[room_name] = trv_setpoint

                # Reset the PID (not just skip) when the room's primary TRV
                # write entity is unavailable — same policy as before B18. A
                # secondary TRV in a multi-TRV room being briefly unavailable
                # does not reset the room's PID; it's just skipped below.
                write_state = self.hass.states.get(write_id)
                if write_state is None or write_state.state in (
                    "unavailable",
                    "unknown",
                    "off",
                ):
                    pid.reset()
                    continue

                # ── Send the same computed setpoint to every TRV in the room ──
                # B18 "grouping": one PID loop per room, N identical outputs.
                # Each TRV resolves its own write entity the same way the
                # primary one above did (its own homekit_climate_entity if
                # configured, else its own climate_entity — no live-reachability
                # fallback, matching pre-B18 behaviour exactly for the primary
                # TRV: an unreachable configured HomeKit entity is skipped and
                # logged, not silently redirected to the cloud entity), and is
                # suppressed independently — a newly-added or differently-typed
                # TRV can sit at a different current setpoint than the room's
                # primary one.
                for trv in self.get_room_trvs(room_name):
                    trv_write_id = trv.get(CONF_HOMEKIT_CLIMATE_ENTITY) or trv.get(
                        CONF_CLIMATE_ENTITY
                    )
                    if not trv_write_id:
                        continue

                    if trv_write_id == write_id:
                        trv_state = write_state  # already fetched above
                    else:
                        trv_state = self.hass.states.get(trv_write_id)
                        if trv_state is None or trv_state.state in (
                            "unavailable",
                            "unknown",
                            "off",
                        ):
                            continue

                    trv_current_setpoint = trv_state.attributes.get("temperature", 0.0)
                    try:
                        trv_current_setpoint = float(trv_current_setpoint)
                    except (TypeError, ValueError):
                        # 3.1 fix: a malformed/non-numeric setpoint attribute must
                        # not abort the PID tick for every remaining room — skip
                        # just this TRV and let the command below correct it.
                        _LOGGER.debug(
                            "PID tick [%s]: non-numeric current setpoint %r on %s"
                            " — sending setpoint anyway",
                            room_name,
                            trv_current_setpoint,
                            trv_write_id,
                        )
                        trv_current_setpoint = None

                    if (
                        trv_current_setpoint is not None
                        and abs(trv_setpoint - trv_current_setpoint) < 0.5
                    ):
                        continue

                    try:
                        await self.hass.services.async_call(
                            "climate",
                            "set_temperature",
                            {"entity_id": trv_write_id, "temperature": trv_setpoint},
                            blocking=True,
                        )
                        _LOGGER.debug(
                            "PID tick [%s] (%s): target=%.1f cur=%.1f pwr=%.2f → %.1f°C"
                            "  (heating_power_request=%s%%)",
                            room_name,
                            "HomeKit" if hk_id else "local",
                            target_temp,
                            current_temp,
                            power,
                            trv_setpoint,
                            demand_pct,
                        )
                    # broad-except-rationale: one entity failing must not abort the others in this loop
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning(
                            "PID setpoint failed for '%s' via %s: %s",
                            room_name,
                            trv_write_id,
                            err,
                        )
        finally:
            self._trv_cache = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_house_voice_say(self, event_id: str) -> None:
        """Trigger a House Voice event if the integration is enabled and available.

        Requires house_voice integration to be installed and running.
        Fails silently with a debug log if disabled or unavailable.
        """
        if not self.config.get(CONF_HOUSE_VOICE_ENABLED, False):
            return
        if not self.hass.services.has_service(
            HOUSE_VOICE_DOMAIN, HOUSE_VOICE_SERVICE_SAY
        ):
            _LOGGER.debug(
                "House Voice: service '%s.%s' not available — is house_voice installed?",
                HOUSE_VOICE_DOMAIN,
                HOUSE_VOICE_SERVICE_SAY,
            )
            return
        try:
            await self.hass.services.async_call(
                HOUSE_VOICE_DOMAIN,
                HOUSE_VOICE_SERVICE_SAY,
                {"event": event_id},
                blocking=False,
            )
            _LOGGER.debug("House Voice: triggered event '%s'", event_id)
        # broad-except-rationale: House Voice is opt-in; must fail silently, not crash the coordinator
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("House Voice: failed to trigger '%s': %s", event_id, err)

    async def async_shutdown(self) -> None:
        """Persist the event log snapshot and shut down all engines cleanly."""
        # Persist the event log so it survives an unexpected HA restart.
        try:
            self._persist_event_log_snapshot()
        # broad-except-rationale: best-effort; must not block the engine shutdowns that follow
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Event log persist on shutdown failed: %s", err)
        await self.presence_engine.async_shutdown()
        await self.window_engine.async_shutdown()
        await self.door_engine.async_shutdown()
        await self.season_engine.async_shutdown()
        await self.preheat_engine.async_shutdown()
        await self.valve_protection.async_shutdown()
        await self.calibration_engine.async_shutdown()
        await self.sync_engine.async_shutdown()
        await self.schedule_engine.async_shutdown()
        await self.remote_button_engine.async_shutdown()
        _LOGGER.debug("Coordinator shut down cleanly")
