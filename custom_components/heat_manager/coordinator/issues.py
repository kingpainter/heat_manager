"""Heat Manager coordinator — issues layer: status line, repairs, mold risk.

Tracks how long each problem has been active, escalates long-running ones to
a push notification, raises and clears Home Assistant repair issues, and
feeds the panel's status line (window open, cloud down, stuck override,
slow heat-up, mold risk, missing climate entity) (v0.68.7, T3g).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.util.dt import utcnow

from ..const import (
    CONF_HUMIDITY_SENSOR,
    CONF_ISSUE_ESCALATION_MINUTES,
    CONF_NOTIFY_ISSUE_ESCALATION,
    CONF_NOTIFY_MOLD_RISK,
    CONF_NOTIFY_SERVICE,
    DEFAULT_ISSUE_ESCALATION_MINUTES,
    DOMAIN,
    MISSING_CLIMATE_GRACE_SECONDS,
    NETATMO_BACKEND_AUTO,
    REPAIR_ISSUE_ID_PREFIX,
    REPAIR_ISSUE_MISSING_CLIMATE,
    REPAIR_ISSUE_NETATMO_BACKEND_MISSING,
    REPAIR_ISSUE_PERSISTENT,
    RoomState,
)
from ..engine.mold import is_mold_risk
from .overrides import CoordinatorOverrides

_LOGGER = logging.getLogger(__name__)


# 2026-09-14 (implementeringsplan punkt 2, gruppe B) — which status-center
# issue keys (see HeatManagerCoordinator._report_issue()) are worth raising
# as a real HA Repair issue once persistent, versus categories that stay
# panel-only (e.g. a single open window, a single unavailable sensor — too
# routine/frequent to belong in Settings -> Repairs). Matched by exact key
# or by prefix for the per-room categories.
def _issue_is_repair_worthy(key: str) -> bool:
    return (
        key == "cloud_down"
        or key.startswith("mold_risk:")
        or key.startswith("room_override_stuck:")
    )


class CoordinatorIssues(CoordinatorOverrides):
    """Heat Manager coordinator — issues layer: status line, repairs, mold risk."""

    def snooze_issue(self, issue_id: str, minutes: int) -> datetime | None:
        """Hide one status-line issue for `minutes` (v0.60.0); 0 un-hides
        it. Returns the new hidden-until time, or None when un-hidden."""
        if minutes <= 0:
            self._issue_snoozed_until.pop(issue_id, None)
            self.async_update_listeners()
            return None
        until = utcnow() + timedelta(minutes=minutes)
        self._issue_snoozed_until[issue_id] = until
        self.async_update_listeners()
        return until

    def get_issue_snoozed_until(self, issue_id: str) -> datetime | None:
        """Hidden-until time for an issue id, or None when it isn't hidden
        (expired snoozes are dropped on read)."""
        until = self._issue_snoozed_until.get(issue_id)
        if until is None:
            return None
        if utcnow() >= until:
            self._issue_snoozed_until.pop(issue_id, None)
            return None
        return until

    async def _async_check_mold_risk(self) -> None:
        """Push a notification the moment a room's mold risk turns on.

        MoldRiskSensor (binary_sensor.py) exposes the same condition as an
        entity for dashboards/automations, but as a passive CoordinatorEntity
        property it has no way to *push* anything on its own — it's only
        ever polled. This mirrors that sensor's exact algorithm (see the
        shared engine/mold.py) and adds the one thing the entity
        can't do: fire CONF_NOTIFY_SERVICE on the False → True edge, once per
        episode, exactly like WindowEngine's open/close notifications.
        """
        if not self.config.get(CONF_NOTIFY_MOLD_RISK, True):
            return
        for room in self.rooms:
            room_name = room.get("room_name", "")
            humidity_id = room.get(CONF_HUMIDITY_SENSOR)
            if not humidity_id:
                continue
            state = self.hass.states.get(humidity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                continue
            try:
                rh = float(state.state)
            except (TypeError, ValueError):
                continue

            climate_id = self.get_climate_entity(room_name) or ""
            temp = self.get_room_current_temp(room_name, climate_id)
            if temp is None:
                continue

            at_risk = is_mold_risk(temp, rh)
            was_at_risk = self._mold_risk_state.get(room_name, False)
            self._mold_risk_state[room_name] = at_risk

            msg = f"Mold risk — {room_name} ({rh:.0f}% RH, {temp:.1f}°C)"
            # 2026-09-13 (architecture review #4): feed the generic
            # status-center issue tracker regardless of the transition —
            # _report_issue() itself figures out started/cleared/escalate.
            await self._report_issue(f"mold_risk:{room_name}", at_risk, "warning", msg)

            if not at_risk or was_at_risk:
                continue

            _LOGGER.info(
                "Mold risk detected in '%s' (RH %.0f%%, temp %.1f°C)",
                room_name,
                rh,
                temp,
            )
            self.log_event(msg, "Mold risk", "mold_risk")
            await self._notify_mold_risk(msg)

    async def _notify_mold_risk(self, message: str) -> None:
        service = self.config.get(CONF_NOTIFY_SERVICE, "")
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not service_name:
            return
        try:
            await self.hass.services.async_call(
                domain,
                service_name,
                {"message": message, "title": "Heat Manager"},
                blocking=True,
            )
        # broad-except-rationale: one failing notification must not break the tick
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Mold risk notification failed: %s", err)

    # ── Generic issue escalation + structured events (2026-09-13) ───────────
    # Architecture review #4: a status-center issue category (mold risk,
    # window open, heat-up-rate anomaly — see the three call sites below)
    # feeds its per-tick active/inactive boolean through this one tracker,
    # under a stable `key` (e.g. "mold_risk:Stue"). It gives every category
    # two things none of them had to build for itself: a
    # `heat_manager_issue_started`/`heat_manager_issue_cleared` HA bus event
    # on each transition (for automations — see also diagnostics.py/the
    # architecture review doc), and — for a category still active past
    # CONF_ISSUE_ESCALATION_MINUTES — exactly one push notification per
    # continuous episode via CONF_NOTIFY_SERVICE, gated by
    # CONF_NOTIFY_ISSUE_ESCALATION. This is on top of / independent of
    # whatever instant notifier a category already has of its own (mold
    # risk, windows); some categories (heat-up anomaly) have no notifier of
    # their own at all, so this is the only push they will ever get.

    async def _report_issue(
        self, key: str, active: bool, severity: str, message: str
    ) -> None:
        was_active = key in self._issue_started_at
        if active and not was_active:
            self._issue_started_at[key] = utcnow()
            self.hass.bus.async_fire(
                f"{DOMAIN}_issue_started",
                {"key": key, "severity": severity, "message": message},
            )
            return

        if not active:
            if was_active:
                started_at = self._issue_started_at.pop(key, None)
                self._issue_escalated.discard(key)
                duration_s = (
                    (utcnow() - started_at).total_seconds() if started_at else None
                )
                self.hass.bus.async_fire(
                    f"{DOMAIN}_issue_cleared",
                    {"key": key, "message": message, "duration_seconds": duration_s},
                )
                # 2026-09-14 (punkt 2): clear any repair issue this category
                # had open — same edge (active -> inactive) that already
                # clears the escalation notification gate above.
                if key in self._repair_issue_active:
                    self._repair_issue_active.discard(key)
                    async_delete_issue(self.hass, DOMAIN, self._repair_issue_id(key))
            return

        # Still active from a previous tick.
        started_at = self._issue_started_at.get(key)
        threshold_min = self.config.get(
            CONF_ISSUE_ESCALATION_MINUTES, DEFAULT_ISSUE_ESCALATION_MINUTES
        )
        persistent = (
            started_at is not None
            and (utcnow() - started_at).total_seconds() >= threshold_min * 60
        )

        # 2026-09-14 (punkt 2, gruppe B — "Udvid HA Repairs-integrationen"):
        # once a repair-worthy category has been continuously active past
        # the same escalation threshold the push notification uses, also
        # raise a real HA Repair issue — visible in Settings -> Repairs and
        # the HA mobile app's badge, not only in Heat Manager's own panel.
        # Independent of CONF_NOTIFY_ISSUE_ESCALATION (that gate is only for
        # the push notification) and created at most once per episode via
        # _repair_issue_active.
        if (
            persistent
            and _issue_is_repair_worthy(key)
            and key not in self._repair_issue_active
        ):
            self._repair_issue_active.add(key)
            async_create_issue(
                self.hass,
                DOMAIN,
                self._repair_issue_id(key),
                is_fixable=False,
                severity=(
                    IssueSeverity.CRITICAL
                    if severity == "critical"
                    else IssueSeverity.WARNING
                ),
                translation_key=REPAIR_ISSUE_PERSISTENT,
                translation_placeholders={
                    "message": message,
                    "duration_min": str(int(threshold_min)),
                },
            )

        # Escalation-notification path (unchanged) — only escalation work
        # remains once the repair-issue check above has run.
        if key in self._issue_escalated:
            return
        if not self.config.get(CONF_NOTIFY_ISSUE_ESCALATION, True):
            return
        if started_at is None or not persistent:
            return
        self._issue_escalated.add(key)
        await self._notify_issue_escalation(message, threshold_min)

    def missing_climate_issue_id(self, room_name: str) -> str:
        """Repair issue_id for a room whose climate entity is missing."""
        safe = room_name.lower().replace(" ", "_")
        return f"{REPAIR_ISSUE_MISSING_CLIMATE}_{safe}_{self.entry.entry_id[:8]}"

    def check_netatmo_backend_choice(self) -> None:
        """v0.61.1 / v0.69.3: RepairIssue when the explicitly chosen Netatmo
        backend (core netatmo or NET-TRV) has no active config entry — e.g.
        core disabled or removed after the user picked "Core". Cleared as
        soon as the choice resolves again (integration re-enabled, or the
        user switches back to Auto).

        v0.69.3: runs every tick, not only at setup and on an options save.
        Disabling or deleting the chosen integration does not touch Heat
        Manager's options, so before this the issue only appeared after the
        next Home Assistant restart. WARNING logged once per episode.
        """
        choice = self.netatmo_backend_choice
        issue_id = f"{REPAIR_ISSUE_NETATMO_BACKEND_MISSING}_{self.entry.entry_id[:8]}"
        missing = (
            choice != NETATMO_BACKEND_AUTO
            and self.get_effective_netatmo_backend() is None
        )
        if missing:
            if not self._netatmo_backend_issue_raised:
                _LOGGER.warning(
                    "Heat Manager: chosen Netatmo backend '%s' is not installed —"
                    " raised RepairIssue '%s'",
                    choice,
                    issue_id,
                )
            async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key=REPAIR_ISSUE_NETATMO_BACKEND_MISSING,
                translation_placeholders={"backend": choice},
            )
        else:
            async_delete_issue(self.hass, DOMAIN, issue_id)
        self._netatmo_backend_issue_raised = missing

    def check_missing_climate_entities(self) -> None:
        """Raise or clear the missing-climate repair issue for each room.

        Called once at setup and on every coordinator tick. A room whose
        climate entity is missing only gets a WARNING and a repair issue
        after MISSING_CLIMATE_GRACE_SECONDS, so a cloud integration that
        creates its entities shortly after Heat Manager starts does not
        produce noise. Once the entity exists the issue is deleted right
        away, without needing a reload.
        """
        now = utcnow()
        for room in self.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            climate_id = self.get_climate_entity(room_name) or ""
            if not climate_id:
                continue
            issue_id = self.missing_climate_issue_id(room_name)

            if self.hass.states.get(climate_id) is not None:
                self._climate_missing_since.pop(room_name, None)
                if room_name in self._climate_missing_raised:
                    self._climate_missing_raised.discard(room_name)
                    _LOGGER.info(
                        "Heat Manager: climate entity '%s' (room '%s') is"
                        " available again — cleared RepairIssue '%s'",
                        climate_id,
                        room_name,
                        issue_id,
                    )
                # Also clears an issue left over from a previous run.
                async_delete_issue(self.hass, DOMAIN, issue_id)
                continue

            since = self._climate_missing_since.setdefault(room_name, now)
            if room_name in self._climate_missing_raised:
                continue
            if (now - since).total_seconds() < MISSING_CLIMATE_GRACE_SECONDS:
                continue

            self._climate_missing_raised.add(room_name)
            _LOGGER.warning(
                "Heat Manager: climate entity '%s' (room '%s') has been missing"
                " for %d min — raised RepairIssue '%s'",
                climate_id,
                room_name,
                MISSING_CLIMATE_GRACE_SECONDS // 60,
                issue_id,
            )
            async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key=REPAIR_ISSUE_MISSING_CLIMATE,
                translation_placeholders={
                    "room_name": room_name,
                    "climate_id": climate_id,
                },
            )

    def _repair_issue_id(self, key: str) -> str:
        """Stable, registry-safe issue_id for a status-center key, scoped to
        this config entry so two Heat Manager entries never collide."""
        safe_key = key.lower().replace(":", "_").replace(" ", "_")
        return f"{REPAIR_ISSUE_ID_PREFIX}{safe_key}_{self.entry.entry_id[:8]}"

    async def _notify_issue_escalation(
        self, message: str, threshold_min: float
    ) -> None:
        service = self.config.get(CONF_NOTIFY_SERVICE, "")
        if not service:
            return
        domain, _, service_name = service.partition(".")
        if not service_name:
            return
        full_message = f"{message} (aktiv i {int(threshold_min)}+ min)"
        try:
            await self.hass.services.async_call(
                domain,
                service_name,
                {"message": full_message, "title": "Heat Manager"},
                blocking=True,
            )
        # broad-except-rationale: one failing notification must not break the tick
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Issue escalation notification failed: %s", err)

    async def _async_check_window_issue_events(self) -> None:
        """Feed each room's window-open state into the generic issue
        tracker. WindowEngine already has its own instant open/close
        notification and its own 30-min warning (CONF_NOTIFY_WINDOW_WARNING_30)
        — this is the separate, category-agnostic "still open after N
        minutes" safety net that every category gets via _report_issue(),
        independent of and in addition to that existing warning.
        """
        open_rooms = set(self.window_engine.get_open_windows())
        for room in self.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            is_open = room_name in open_rooms
            await self._report_issue(
                f"window_open:{room_name}",
                is_open,
                "warning",
                f"Vindue åbent — {room_name}",
            )

    async def _async_check_cloud_issue_events(self) -> None:
        """Feed whole-house Netatmo cloud/gateway availability into the
        generic issue tracker (2026-09-14, implementeringsplan punkt 2).
        Mirrors websocket_payload.py's build_active_issues() cloud check (kept
        independent rather than imported, same cross-module rationale used
        elsewhere in this file) — only the "every Netatmo room unreachable"
        case counts as the whole-house cloud_down category; a single room
        being unavailable stays panel-only via the existing per-room
        unavailable_entities status line, not a repair-worthy outage.
        """
        total = 0
        unavailable = 0
        for room in self.rooms:
            room_name = room.get("room_name", "")
            climate_id = self.get_climate_entity(room_name) or ""
            hk_id = self.get_homekit_climate_entity(room_name) or ""
            if not climate_id or climate_id == hk_id:
                continue
            total += 1
            state = self.hass.states.get(climate_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable += 1
        active = total > 0 and unavailable == total
        await self._report_issue(
            "cloud_down",
            active,
            "critical",
            "Netatmo cloud/gateway nede — alle rum utilgængelige",
        )

    async def _async_check_room_override_stuck_events(self) -> None:
        """Feed each room's manual-override state into the generic issue
        tracker (2026-09-14, implementeringsplan punkt 2). A room left in
        OVERRIDE for a long time is often simply forgotten — boosted or
        manually adjusted once and never switched back — rather than a
        deliberate long-term choice, so it becomes a real Repair issue once
        persistent, the same threshold every other repair-worthy category
        uses (CONF_ISSUE_ESCALATION_MINUTES).
        """
        for room in self.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            is_override = self.get_room_state(room_name) == RoomState.OVERRIDE
            await self._report_issue(
                f"room_override_stuck:{room_name}",
                is_override,
                "warning",
                f"{room_name}: har stået i manuel override i lang tid",
            )

    async def _async_check_heatup_anomaly_events(self) -> None:
        """Feed each room's heat-up-rate anomaly flag (v0.38.0) into the
        generic issue tracker. This category has no dedicated notifier of
        its own — the escalation path in _report_issue() is the only push
        notification it will ever get.
        """
        for room in self.rooms:
            room_name = room.get("room_name", "")
            if not room_name:
                continue
            anomaly = self.calibration_engine.get_room_heatup_anomaly(room_name)
            await self._report_issue(
                f"heatup_anomaly:{room_name}",
                anomaly,
                "warning",
                f"{room_name}: varmer langsommere end normalt — muligvis"
                " fastsiddende ventil",
            )
