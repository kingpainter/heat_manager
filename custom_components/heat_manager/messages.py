"""Heat Manager — keys of the translatable backend texts (v0.72.0).

The texts themselves live in frontend/translations/<language>.json (English
is the default). The backend stores the event log in English plus the text
key and params, so the panel can show each event in the viewer's language;
push notifications are rendered in the Home Assistant system language.

EVENT_KEYS lists every "event.<key>" the backend logs via
coordinator.log_message(); tests check it against en.json.
"""

from __future__ import annotations

EVENT_KEYS: frozenset[str] = frozenset(
    {
        "alarm_armed",
        "alarm_disarmed",
        "away_nobody_home",
        "away_room",
        "away_room_off",
        "boost_started",
        "boost_started_none",
        "boost_stopped",
        "config_updated",
        "door_closed",
        "door_closed_away",
        "door_closed_between",
        "door_closed_monitoring",
        "door_closed_resumed",
        "door_open_heating",
        "door_open_minutes",
        "door_open_monitoring",
        "door_opened",
        "door_opened_between",
        "forced_on",
        "forced_on_windows_open",
        "group_off",
        "group_on",
        "mold_risk",
        "netatmo_preset_set",
        "offset_set",
        "override_expired",
        "override_extended",
        "override_off",
        "override_on",
        "override_released",
        "remote_auto",
        "remote_boost",
        "remote_manual",
        "remote_release",
        "remote_temp",
        "room_config_updated",
        "room_schedule_restored",
        "room_temp_set",
        "room_temp_set_for",
        "season_mode_set",
        "sync_accepted",
        "sync_reverted",
        "valve_exercise_done",
        "valve_exercise_skipped",
        "welcome_home",
        "window_closed_away",
        "window_closed_monitoring",
        "window_closed_resumed",
        "window_open_heating",
        "window_open_minutes",
        "window_open_monitoring",
    }
)
