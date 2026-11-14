"""Heat Manager coordinator — base layer: shared state and core lookups.

The coordinator is split into layers, each a subclass of the one below
(v0.68.2, T3b):

    CoordinatorBase          base.py         state, config, rooms, TRVs, climate writes
    CoordinatorPersistence   persistence.py  event log + restart snapshots
    CoordinatorSensors       sensors.py      readings: temperature, weather, doors, windows
    CoordinatorNetatmo       netatmo.py      Netatmo backend, valve health, relay
    CoordinatorOverrides     overrides.py    manual override, boost, house status
    CoordinatorIssues        issues.py       status-line issues, repairs, mold risk
    CoordinatorPid           pid.py          PID tick and target temperature
    HeatManagerCoordinator   core.py         engines, periodic tick, shutdown

A layer may call anything defined in itself or below it, never above it, so
every call is fully typed without protocols or casts. Engines and platforms
only ever see HeatManagerCoordinator.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import utcnow

from ..const import (
    CONF_ALARM_PANEL,
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_DOORS,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_HOUSE_VOICE_ENABLED,
    CONF_MIN_ROOM_TEMP,
    CONF_PERSONS,
    CONF_PID_ENABLED,
    CONF_ROOMS,
    CONF_TRV_MAX_TEMP,
    CONF_TRVS,
    CONF_WEATHER_ENTITY,
    DEFAULT_MIN_ROOM_TEMP,
    DEFAULT_TRV_MAX_TEMP,
    DOMAIN,
    HOUSE_VOICE_DOMAIN,
    HOUSE_VOICE_SERVICE_SAY,
    NETATMO_API_CALL_DELAY_SEC,
    SCAN_INTERVAL_SECONDS,
    AutoOffReason,
    ControllerState,
    EffectiveSeason,
    RoomState,
    SeasonMode,
)
from ..engine import clock as engine_clock
from ..engine.calibration_engine import CalibrationEngine
from ..engine.controller import ControllerEngine
from ..engine.door_engine import DoorEngine
from ..engine.netatmo_backend import (
    NetatmoBackend,
    resolve_backend,
)
from ..engine.pid_controller import PidController
from ..engine.preheat_engine import PreheatEngine
from ..engine.presence_engine import PresenceEngine
from ..engine.remote_button_engine import RemoteButtonEngine
from ..engine.schedule_engine import ScheduleEngine
from ..engine.season_engine import SeasonEngine
from ..engine.sync_engine import SyncEngine
from ..engine.valve_protection_engine import ValveProtectionEngine
from ..engine.window_engine import WindowEngine
from ..frontend_translations import render
from ..migrations import migrate_room_to_trvs

_LOGGER = logging.getLogger(__name__)

# Maximum number of events kept in the in-memory log (FIFO)
_MAX_EVENT_LOG = 200


class CoordinatorBase(DataUpdateCoordinator[dict[str, Any]]):
    """Heat Manager coordinator — base layer: shared state and core lookups."""

    # Engines are created by HeatManagerCoordinator.__init__ (core.py) once
    # all shared state below exists; declared here so every layer can use
    # them with full typing.
    controller: ControllerEngine
    presence_engine: PresenceEngine
    window_engine: WindowEngine
    door_engine: DoorEngine
    season_engine: SeasonEngine
    preheat_engine: PreheatEngine
    valve_protection: ValveProtectionEngine
    calibration_engine: CalibrationEngine
    sync_engine: SyncEngine
    schedule_engine: ScheduleEngine
    remote_button_engine: RemoteButtonEngine

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        texts: dict[str, dict[str, str]] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry
        # v0.72.0: translated texts per language (frontend/translations,
        # loaded off the event loop by async_setup_entry()). "en" renders the
        # stored event log; the system language renders push notifications.
        self._texts: dict[str, dict[str, str]] = texts or {}
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
        # v0.31.0: last known mold-risk state per room, so
        # _async_check_mold_risk() can edge-detect False → True and send
        # exactly one notification per risk episode (re-armed only once the
        # room's risk drops back to False), the same pattern WindowEngine
        # uses for its own open/close notifications.
        self._mold_risk_state: dict[str, bool] = {}

        # 2026-09-13 (architecture review #4) — generic status-center issue
        # tracker backing _report_issue(): key -> UTC time the issue started
        # being continuously active, and the set of keys already escalated to
        # a push notification this episode (so escalation fires once per
        # episode, not once per tick). See _report_issue() (issues.py) for the
        # full mechanism and its three call sites (mold risk, window open,
        # heat-up-rate anomaly).
        self._issue_started_at: dict[str, datetime] = {}
        self._issue_escalated: set[str] = set()
        # 2026-09-14 (implementeringsplan punkt 2) — tracks which issue keys
        # currently have an open HA Repair issue (see REPAIR_WORTHY_ISSUE_
        # PREFIXES / _issue_is_repair_worthy() (issues.py)), so a repair issue is
        # created exactly once per episode instead of every tick, and
        # deleted the moment the category clears.
        self._repair_issue_active: set[str] = set()
        # v0.68.0 (T2): engines read the time through the pure engine.clock
        # module; give it Home Assistant's own functions so they see HA's
        # time and configured time zone.
        engine_clock.use_providers(utcnow=dt_util.utcnow, local_now=dt_util.now)

        # v0.65.4: per-room tracking for the missing-climate repair issue.
        # _climate_missing_since holds when each room's climate entity was
        # first seen missing; _climate_missing_raised holds rooms whose
        # WARNING + repair issue has been raised for the current episode.
        self._climate_missing_since: dict[str, datetime] = {}
        self._climate_missing_raised: set[str] = set()
        # v0.69.3: whether the "chosen Netatmo backend missing" repair is
        # currently raised — see check_netatmo_backend_choice().
        self._netatmo_backend_issue_raised: bool = False

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
        # v0.59.0: UTC time each room entered OVERRIDE, from any code path
        # (see set_room_state()) — lets the panel/card show "manual since
        # 17:42". In-memory only: after a restart a restored override has
        # no known start time and the frontend simply omits it.
        self.room_override_since: dict[str, datetime] = {}
        # v0.60.0: status-line issue id -> UTC time until which it is hidden
        # ("Skjul 1 t"). In-memory only — a restart simply shows it again.
        self._issue_snoozed_until: dict[str, datetime] = {}

        # v0.15.0: last action taken by the global physical remote (any of
        # the 3 configurable button entities — see
        # engine/remote_button_engine.py and CONF_BUTTON_*). Purely
        # informational, written via set_remote_last_action() (overrides.py) and
        # read by sensor.py's RemoteLastActionSensor (Hub device) so a
        # button press's effect is visible at a glance without digging
        # through the History tab. None until the remote has acted at least
        # once since HA started.
        self.remote_last_action: dict[str, Any] | None = None

        self.pid_controllers: dict[str, PidController] = {}
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
        # B27 (v0.60.3): rooms whose PID is currently running on HomeKit
        # alone because the cloud climate entity is unavailable — used only
        # to log one WARNING on entry and one INFO on recovery.
        self._pid_cloud_degraded: set[str] = set()
        # Per-room target-temperature override from an active schedule/
        # calendar block — see engine/schedule_engine.py. Absent (no key)
        # for a room with no CONF_SCHEDULE_ENTITY configured, or whose
        # block/event isn't currently active.
        self.schedule_override: dict[str, float] = {}

    # ── Texts (v0.72.0) ──────────────────────────────────────────────────────

    @property
    def notify_language(self) -> str:
        """Language for push notifications and repair texts: the Home
        Assistant system language (English when it has no translation)."""
        lang = self.hass.config.language or "en"
        return lang if lang in self._texts else "en"

    def text(self, key: str, language: str | None = None, **params: Any) -> str:
        """`key` (e.g. "notify.window_open") rendered in `language` — the
        system language by default — with English for missing strings."""
        strings = self._texts.get(language or self.notify_language) or self._texts.get(
            "en", {}
        )
        return render(strings, key, params)

    @property
    def config(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def rooms(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.config.get(CONF_ROOMS, []))

    @property
    def persons(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.config.get(CONF_PERSONS, []))

    @property
    def doors(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.config.get(CONF_DOORS, []))

    @property
    def alarm_panel(self) -> str | None:
        return self.config.get(CONF_ALARM_PANEL) or None

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
            entry_type=DeviceEntryType.SERVICE,
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
            # 2026-09-15 (punkt 1B, strict typing): mypy (via the
            # `homeassistant-stubs` PyPI package used for local/CI type
            # checking) does not know `via_device_id` as a DeviceInfo key —
            # only the older `via_device: tuple[str, str]` form. This was a
            # deliberate choice (see this method's own docstring above) once
            # `via_device`'s tuple form stopped reliably resolving a parent
            # across config entries; behaviour is unchanged by this ignore,
            # it only silences a stub/runtime version mismatch. Re-verify
            # against whichever HA core version is actually running
            # (`grep via_device_id` in that install's own device_registry.py)
            # if `homeassistant-stubs` is ever upgraded and this still fires.
            via_device_id=self.global_device_id,  # type: ignore[typeddict-unknown-key,unused-ignore]
        )

    @property
    def weather_entity(self) -> str | None:
        return self.config.get(CONF_WEATHER_ENTITY) or None

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
            self.room_override_since.pop(room_name, None)

        old = self.room_states.get(room_name)
        if old == state:
            return
        if state == RoomState.OVERRIDE:
            self.room_override_since[room_name] = utcnow()
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

    @staticmethod
    def get_trv_climate_entity(trv: dict[str, Any]) -> str | None:
        return trv.get(CONF_CLIMATE_ENTITY) or None

    @staticmethod
    def get_trv_homekit_entity(trv: dict[str, Any]) -> str | None:
        return trv.get(CONF_HOMEKIT_CLIMATE_ENTITY) or None

    def _state_value(self, entity_id: str) -> str | None:
        """State string, or None while unknown/unavailable/missing."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return str(state.state)

    def track_state_changes(
        self, entity_ids: list[str], handler: Callable[[Any], None]
    ) -> Callable[[], None]:
        """v0.67.5 (T2b): subscribe an engine handler to state changes.

        Engines stay free of Home Assistant imports (rule 3.1) by asking the
        coordinator to subscribe for them. The handler is wrapped in
        ``@callback`` here so Home Assistant runs it in the event loop — a
        plain sync function would otherwise be sent to an executor thread.
        Returns the unsubscribe function.
        """

        @callback
        def _forward(event: Event[EventStateChangedData]) -> None:
            handler(event)

        return async_track_state_change_event(self.hass, entity_ids, _forward)

    def call_later(
        self, delay_seconds: float, action: Callable[[], None]
    ) -> Callable[[], None]:
        """v0.67.6 (T2c): run an engine action once after ``delay_seconds``.

        Same reason as track_state_changes(): engines stay free of Home
        Assistant imports, and the action runs in the event loop
        (``@callback``). Returns the cancel function.
        """

        @callback
        def _run(_now: Any) -> None:
            action()

        return async_call_later(self.hass, delay_seconds, _run)

    @property
    def min_room_temp(self) -> float:
        """v0.67.0: global lowest room temperature — floors the PID's
        setpoint and the night/wake setback in every room."""
        return float(self.config.get(CONF_MIN_ROOM_TEMP, DEFAULT_MIN_ROOM_TEMP))

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

    def trv_needs_cloud_delay(self, trv: dict[str, Any]) -> bool:
        """Per-TRV equivalent of needs_cloud_delay() — True unless this
        TRV's own HomeKit entity is configured and currently reachable."""
        hk_id = self.get_trv_homekit_entity(trv)
        if hk_id:
            state = self.hass.states.get(hk_id)
            if state and state.state not in ("unavailable", "unknown", "off"):
                return False
        return True

    def _entity_unavailable(self, entity_id: str) -> bool:
        """True if entity_id is missing or not usable as a write target."""
        state = self.hass.states.get(entity_id)
        return state is None or state.state in ("unavailable", "unknown", "off")

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

    def _entity_netatmo_backend(self, entity_id: str | None) -> NetatmoBackend | None:
        """Netatmo integration owning entity_id (registry platform), or None."""
        if not entity_id:
            return None
        entry = er.async_get(self.hass).async_get(entity_id)
        return resolve_backend(entry.platform if entry else None)

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

    @property
    def calendar_season(self) -> SeasonMode:
        """Isolated access to season_engine — avoids direct engine coupling in platforms."""
        return self.season_engine.calendar_season

    @property
    def days_above_threshold(self) -> int:
        """Isolated access to season_engine — avoids direct engine coupling in platforms."""
        return self.season_engine.days_above_threshold

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
