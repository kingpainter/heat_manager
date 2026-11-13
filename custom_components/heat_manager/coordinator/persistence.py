"""Heat Manager coordinator — persistence layer: event log and restart snapshots.

The History tab's event log, plus the room overrides, active boost and
per-room group toggles that must survive a Home Assistant restart. Snapshots
are stored in the config entry's options (v0.68.3, T3c).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from homeassistant.util.dt import utcnow

from ..const import (
    RoomState,
)
from .base import CoordinatorBase

_LOGGER = logging.getLogger(__name__)


class CoordinatorPersistence(CoordinatorBase):
    """Heat Manager coordinator — persistence layer: event log and restart snapshots."""

    def set_room_group_enabled(self, room_name: str, enabled: bool) -> None:
        """Set a room's group-toggle state (called by RoomGroupToggleSwitch)
        and immediately rebuild SyncEngine's entity→TRV map so a
        just-ungrouped secondary TRV stops being monitored (and a
        just-regrouped one starts being monitored again) without requiring
        an integration reload."""
        self.room_group_enabled[room_name] = enabled
        self._persist_group_toggle_snapshot()
        self.sync_engine.rebuild_entity_map()
        self.async_update_listeners()

    def _persist_group_toggle_snapshot(self) -> None:
        """Persist room_group_enabled (2026-09-15, restart-safety hardening)
        — called immediately on every toggle (rare, user-triggered only,
        never per tick) rather than waiting for shutdown, so a crash right
        after toggling doesn't lose it."""
        options = dict(self.entry.options)
        options["_group_toggle_snap"] = json.dumps(self.room_group_enabled)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        _LOGGER.debug("Room group-toggle state persisted: %s", self.room_group_enabled)

    def _restore_group_toggle_snapshot(self) -> None:
        """Restore room_group_enabled from a persisted snapshot on startup."""
        raw = self.entry.options.get("_group_toggle_snap")
        if not raw:
            return
        try:
            snap = json.loads(raw)
        except (ValueError, TypeError):
            return
        if isinstance(snap, dict):
            self.room_group_enabled = {k: bool(v) for k, v in snap.items()}
            _LOGGER.info("Restored room group-toggle state for %d room(s)", len(snap))

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

    def _persist_event_log_snapshot(self) -> None:
        """Persist the event log snapshot into entry.options (survives HA restarts).

        Called once a day (on date change) and on shutdown, so the log isn't
        lost on an unclean restart.
        """
        event_snap = list(self._event_log)[:50]
        options = dict(self.entry.options)
        options["_event_log_snap"] = json.dumps(event_snap)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        _LOGGER.debug("Event log persisted (%d entries)", len(event_snap))

    def _restore_event_log(self) -> None:
        """Restore event log from persisted snapshot on startup (B10)."""
        raw = self.entry.options.get("_event_log_snap", "[]")
        try:
            events = json.loads(raw)
            for e in reversed(events):
                self._event_log.appendleft(e)
            _LOGGER.debug("Event log restored: %d entries", len(events))
        except (ValueError, TypeError):
            pass

    # ── Override/boost persistence (2026-09-13 restart-safety hardening) ────
    #
    # Before this, room_override_source/room_override_expires_at/
    # boost_active_rooms/boost_expires_at were pure in-memory dicts — a
    # manual override set from the panel, or an active boost, was silently
    # forgotten on any HA restart (update, power blip, container restart):
    # the room just quietly fell back to its normal schedule with no
    # warning at all. Same snapshot-into-entry.options pattern as the event
    # log above. Only the *bookkeeping* is restored on the other end — the
    # physical TRV is never re-commanded, since the device already holds
    # whatever setpoint was last written to it; restoring the bookkeeping
    # only stops Heat Manager's own next PID tick from silently overwriting
    # that still-active manual choice.

    def _persist_override_snapshot(self) -> None:
        """Persist active room overrides + boost state — called from
        async_shutdown(), same trigger as _persist_event_log_snapshot()."""
        overrides = {
            room_name: {
                "source": self.room_override_source.get(room_name, "switch"),
                "expires_at": self.room_override_expires_at[room_name].isoformat()
                if room_name in self.room_override_expires_at
                else None,
            }
            for room_name, state in self.room_states.items()
            if state == RoomState.OVERRIDE
        }
        snap = {
            "overrides": overrides,
            "boost_active_rooms": {
                k: v for k, v in self.boost_active_rooms.items() if v
            },
            "boost_expires_at": self.boost_expires_at.isoformat()
            if self.boost_expires_at
            else None,
        }
        options = dict(self.entry.options)
        options["_override_snap"] = json.dumps(snap)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        _LOGGER.debug(
            "Override/boost snapshot persisted (%d override(s), boost=%s)",
            len(overrides),
            bool(snap["boost_active_rooms"]),
        )

    def _restore_override_snapshot(self) -> None:
        """Restore room overrides + boost bookkeeping from a persisted
        snapshot on startup. A saved override/boost whose expiry already
        passed while HA was down is deliberately NOT restored — the room
        just starts NORMAL, exactly as if it had expired and auto-restored
        normally instead of HA being down at the time."""
        raw = self.entry.options.get("_override_snap")
        if not raw:
            return
        try:
            snap = json.loads(raw)
        except (ValueError, TypeError):
            return

        now = utcnow()
        restored = 0
        for room_name, info in (snap.get("overrides") or {}).items():
            expires_raw = info.get("expires_at")
            if expires_raw:
                try:
                    expires_at = datetime.fromisoformat(expires_raw)
                except (TypeError, ValueError):
                    continue
                if now >= expires_at:
                    continue  # expired while HA was down — stays NORMAL
                self.room_override_expires_at[room_name] = expires_at
            self.room_states[room_name] = RoomState.OVERRIDE
            self.room_override_source[room_name] = info.get("source", "switch")
            restored += 1

        boost_expires_raw = snap.get("boost_expires_at")
        if boost_expires_raw:
            try:
                boost_expires_at = datetime.fromisoformat(boost_expires_raw)
            except (TypeError, ValueError):
                boost_expires_at = None
            if boost_expires_at and now < boost_expires_at:
                self.boost_expires_at = boost_expires_at
                self.boost_active_rooms = dict(snap.get("boost_active_rooms") or {})

        if restored or self.boost_expires_at:
            _LOGGER.info(
                "Restored %d room override(s)%s from before restart",
                restored,
                " + active boost" if self.boost_expires_at else "",
            )
