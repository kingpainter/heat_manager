"""Tests for the backend's translatable texts (v0.72.0): the event log keeps
English text plus key/params; notifications use the system language."""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

from custom_components.heat_manager import frontend_translations as ft
from custom_components.heat_manager.coordinator import HeatManagerCoordinator

_TEXTS = ft.load_languages(["en", "da"])


def _coord(language: str = "da") -> MagicMock:
    coord = MagicMock(spec=HeatManagerCoordinator)
    coord.hass = MagicMock()
    coord.hass.config.language = language
    coord._texts = _TEXTS
    coord._event_log = deque(maxlen=200)
    for name in ("text", "log_message", "_append_event"):
        setattr(coord, name, getattr(HeatManagerCoordinator, name).__get__(coord))
    type(coord).notify_language = HeatManagerCoordinator.notify_language
    return coord


def test_log_message_stores_english_text_key_and_params():
    coord = _coord()
    coord.log_message(
        "window_open_minutes", "window_open", "window_warning", room="Stue", minutes=35
    )
    event = coord._event_log[0]
    assert event["description"] == "Window open 35 min in Stue"
    assert event["reason"] == "Window warning"
    assert event["type"] == "window_open"
    assert event["key"] == "window_open_minutes"
    assert event["params"] == {"room": "Stue", "minutes": 35}
    assert event["reason_key"] == "window_warning"
    assert event["time"] and event["timestamp"]


def test_log_message_with_nested_reference():
    coord = _coord()
    coord.log_message(
        "season_mode_set", "normal", "manual", season=ft.text_ref("season.winter")
    )
    assert coord._event_log[0]["description"] == "Season mode set to Winter"


def test_text_uses_system_language_with_english_fallback():
    assert (
        _coord("da").text("notify.alarm_armed")
        == "Varmen er slukket — alarmen er slået til."
    )
    # A language without a translation falls back to English.
    assert _coord("fr").text("notify.alarm_armed") == "Heating off — alarm armed."
    assert _coord("da").text("notify.alarm_armed", "en") == "Heating off — alarm armed."


def test_unknown_event_key_is_logged_with_a_warning(caplog):
    coord = _coord()
    coord.log_message("no_such_event")
    assert "Unknown event text key" in caplog.text
    assert coord._event_log[0]["description"] == "event.no_such_event"
