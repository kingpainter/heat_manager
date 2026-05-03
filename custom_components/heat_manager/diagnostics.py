"""
Heat Manager — Diagnostics (Gold IQS)

Implements async_get_config_entry_diagnostics() so users can download
a full diagnostics snapshot from Settings → Devices & Services → Heat Manager
→ ⋮ → Download diagnostics.

The snapshot is redacted: entity IDs are preserved (needed for debugging)
but no personal data is included.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_NOTIFY_SERVICE, CONF_PERSONS, CONF_ROOMS, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # ── Config snapshot (redacted) ────────────────────────────────────────────
    cfg = {**entry.data, **entry.options}

    # Redact notify service — may contain personal service names
    cfg_redacted = {
        k: "**REDACTED**" if k == CONF_NOTIFY_SERVICE else v
        for k, v in cfg.items()
    }

    # ── Runtime state ─────────────────────────────────────────────────────────
    rooms_diag = []
    for room in coordinator.rooms:
        room_name  = room.get("room_name", "")
        climate_id = room.get("climate_entity", "")
        room_state = coordinator.get_room_state(room_name)

        climate_attrs: dict[str, Any] = {}
        cs = hass.states.get(climate_id) if climate_id else None
        if cs:
            climate_attrs = {
                "state":               cs.state,
                "current_temperature": cs.attributes.get("current_temperature"),
                "target_temperature":  cs.attributes.get("temperature"),
                "preset_mode":         cs.attributes.get("preset_mode"),
                "hvac_action":         cs.attributes.get("hvac_action"),
            }

        rooms_diag.append({
            "room_name":     room_name,
            "climate_entity": climate_id,
            "room_state":    room_state.value,
            "climate":       climate_attrs,
        })

    persons_diag = []
    for person in coordinator.persons:
        entity_id = person.get("person_entity", "")
        ps        = hass.states.get(entity_id) if entity_id else None
        persons_diag.append({
            "entity":   entity_id,
            "tracking": person.get("person_tracking", True),
            "state":    ps.state if ps else "unavailable",
        })

    # ── Engine state ──────────────────────────────────────────────────────────
    ctrl    = coordinator.controller
    season  = coordinator.season_engine

    engine_state = {
        "controller": {
            "state":               ctrl.state.value,
            "auto_off_reason":     ctrl.auto_off_reason.value,
            "pause_remaining_min": ctrl.pause_remaining_minutes,
            "days_above_high":     ctrl._days_above_high,
            "last_high_date":      ctrl._last_high_date,
        },
        "season": {
            "mode":            coordinator.season_mode.value,
            "effective":       coordinator.effective_season.value,
            "days_above_threshold": season.days_above_threshold,
        },
        "energy": {
            "wasted_today_kwh": coordinator.energy_wasted_today,
            "saved_today_kwh":  coordinator.energy_saved_today,
            "efficiency_score": coordinator.efficiency_score,
        },
        "presence": {
            "someone_home":     coordinator.someone_home(),
            "any_window_open":  coordinator.any_window_open(),
        },
        "preheat": {
            "travel_sensors_found": len(coordinator.preheat_engine._travel_sensors),
            "armed": coordinator.preheat_engine._preheat_armed,
        },
    }

    # ── Recent events ─────────────────────────────────────────────────────────
    recent_events = list(coordinator._event_log)[:20]

    return {
        "config":        cfg_redacted,
        "runtime": {
            "outdoor_temperature": coordinator.outdoor_temperature,
            "rooms":   rooms_diag,
            "persons": persons_diag,
        },
        "engines":       engine_state,
        "recent_events": recent_events,
    }
