"""Heat Manager coordinator — top layer: engines, periodic tick, shutdown.

HeatManagerCoordinator is the class the rest of the integration uses. It
creates the engines, restores state saved before the last restart, and runs
_async_update_data — the single periodic tick that drives all time-based
logic. Each engine tick is isolated: an exception in one is logged as a
WARNING and skipped instead of marking every entity unavailable.

Everything else lives in the layers below (see base.py for the overview).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
)

from ..engine.calibration_engine import CalibrationEngine
from ..engine.controller import ControllerEngine
from ..engine.door_engine import DoorEngine
from ..engine.preheat_engine import PreheatEngine
from ..engine.presence_engine import PresenceEngine
from ..engine.remote_button_engine import RemoteButtonEngine
from ..engine.schedule_engine import ScheduleEngine
from ..engine.season_engine import SeasonEngine
from ..engine.sync_engine import SyncEngine
from ..engine.valve_protection_engine import ValveProtectionEngine
from ..engine.window_engine import WindowEngine
from .pid import CoordinatorPid

_LOGGER = logging.getLogger(__name__)


class HeatManagerCoordinator(CoordinatorPid):
    """
    Central coordinator for Heat Manager.

    All engines are instantiated here. _async_update_data is the single
    periodic tick driving all time-based logic.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        # All shared state is created by CoordinatorBase.__init__; engines
        # come after it because their constructors read that state.
        super().__init__(hass, entry)

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

        self._init_pid_controllers()
        # B10: restore persisted event log on startup
        self._restore_event_log()
        # 2026-09-13 restart-safety hardening: restore any room override or
        # active boost that was still in effect when HA last shut down — see
        # _restore_override_snapshot()/_persist_override_snapshot() (persistence.py).
        self._restore_override_snapshot()
        # 2026-09-15 (restart-safety hardening, round 2): room_group_enabled
        # (RoomGroupToggleSwitch, B18 Fase 3) used to be pure in-memory too
        # — a room whose secondary TRVs had been deliberately released for
        # manual control silently went back to "grouped" on every HA
        # restart. Same entry.options snapshot pattern as the override
        # snapshot just above. See _persist_group_toggle_snapshot()/
        # _restore_group_toggle_snapshot() (persistence.py).
        self._restore_group_toggle_snapshot()

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
          6. Preheat engine (travel_time polling no-op)
          7. Valve protection (weekly exercise)
          8. Calibration engine (write external sensor delta to TRV calibration)
          9. Schedule engine (resolve active schedule/calendar block overrides)
          10. PID tick (proportional TRV setpoints for NORMAL rooms)
          11. Boost expiry check (auto-restore once boost duration elapses)
          12. Mold risk check (push notification on False → True edge)

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

        try:
            self.check_missing_climate_entities()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("missing climate check failed: %s", err)

        try:
            await self._async_check_mold_risk()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("mold risk check failed: %s", err)

        try:
            await self._async_check_window_issue_events()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("window issue-event check failed: %s", err)

        try:
            await self._async_check_cloud_issue_events()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("cloud issue-event check failed: %s", err)

        try:
            await self._async_check_room_override_stuck_events()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("room override-stuck issue-event check failed: %s", err)

        try:
            await self._async_check_heatup_anomaly_events()
        # broad-except-rationale: isolation boundary, see async_tick docstring above
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("heat-up anomaly issue-event check failed: %s", err)

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

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        """Persist the event log snapshot and shut down all engines cleanly.

        2026-09-15 (restart-safety hardening, round 2): controller.py and
        season_engine.py now persist their own state via THEIR OWN
        async_shutdown()/_persist_snapshot() — controller.py's is already
        called on every transition (not just shutdown), and season_engine's
        async_shutdown() call below already covers its day-counter.
        calibration_engine's async_shutdown() below covers the punkt-5
        regression state the same way.
        """
        # Persist the event log so it survives an unexpected HA restart.
        try:
            self._persist_event_log_snapshot()
        # broad-except-rationale: best-effort; must not block the engine shutdowns that follow
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Event log persist on shutdown failed: %s", err)
        try:
            self._persist_override_snapshot()
        # broad-except-rationale: best-effort; must not block the engine shutdowns that follow
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Override/boost snapshot persist on shutdown failed: %s", err)
        try:
            self._persist_group_toggle_snapshot()
        # broad-except-rationale: best-effort; must not block the engine shutdowns that follow
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Group-toggle snapshot persist on shutdown failed: %s", err)
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
