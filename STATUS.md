# Heat Manager — Project Status

**Last updated:** 2026-03-20
**Version:** 0.1.0 (unreleased)
**Target:** Home Assistant 2025.1+

---

## Integration at a glance

Heat Manager is a custom HA integration that replaces 4 YAML automations with
a fully managed heating controller. It handles presence-based away mode, per-room
window detection, an ON / PAUSE / OFF controller with automatic seasonal off, and
a custom sidebar panel for monitoring and control.

---

## File inventory

```
custom_components/heat_manager/
├── __init__.py            Setup, service registration, panel + WS bootstrap
├── manifest.json          v0.1.0 — config_flow: true, iot_class: local_push
├── const.py               All constants, enums and defaults
├── coordinator.py         DataUpdateCoordinator — owns all engines and shared state
├── config_flow.py         4-step setup wizard + options flow (add/delete rooms & persons)
├── panel.py               Sidebar panel + Lovelace card resource registration
├── websocket.py           WS API: heat_manager/get_state, heat_manager/get_history
├── select.py              controller_state (On/Pause/Off), season_mode selects
├── sensor.py              pause_remaining, energy_wasted_today, efficiency_score,
│                          per-room state + window duration sensors
├── binary_sensor.py       any_window_open, heating_wasted, per-room window sensors
├── switch.py              per-room manual override switches
├── services.yaml          set_controller_state, pause, resume, force_room_on
├── strings.json           Base translation keys (en)
├── translations/
│   ├── en.json            Full English translations
│   └── da.json            Full Danish translations
├── engine/
│   ├── controller.py      ON/PAUSE/OFF state machine with @guarded decorator
│   ├── presence_engine.py Presence logic, grace periods, alarm coordination
│   └── window_engine.py   Per-room window detection, 30-min escalation
└── frontend/
    ├── heat-manager-panel.js   Sidebar panel (4 tabs, blink-free controller)
    └── heat-manager-card.js    Lovelace card with ON/PAUSE/OFF buttons
```

```
tests/components/heat_manager/
├── test_controller_engine.py   13 tests — state machine, guard, auto-off
├── test_presence_engine.py     11 tests — arrivals, departures, B4 regression
└── test_window_engine.py       12 tests — B1/B2/B3 regression + core behaviour
```

**Total: 36 tests across 3 files**

---

## Entities created by the integration

| Entity | Type | Description |
|--------|------|-------------|
| `select.heat_manager_controller_state` | Select | On / Pause / Off — primary control |
| `select.heat_manager_season_mode` | Select | Auto / Winter / Summer |
| `sensor.heat_manager_pause_remaining` | Sensor | Minutes left in pause |
| `sensor.heat_manager_energy_wasted_today` | Sensor | Estimated kWh wasted today |
| `sensor.heat_manager_efficiency_score` | Sensor | Daily score 0–100 |
| `sensor.heat_manager_<room>_state` | Sensor | Per-room: normal/away/window_open/pre_heat/override |
| `sensor.heat_manager_<room>_window_duration` | Sensor | Minutes window open today |
| `binary_sensor.heat_manager_any_window_open` | Binary | Any window open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | Window open + heating running |
| `binary_sensor.heat_manager_<room>_window` | Binary | Per-room window open state |
| `switch.heat_manager_<room>_override` | Switch | Manual room override |

---

## Bugs fixed from original YAML automations

| ID | File | Description |
|----|------|-------------|
| B1 | `window_engine.py` | Leading-dot typo in `binary_sensor.lukas_vindue_contact` — Lukas' window never appeared in overview. Entity IDs now come from config flow selector, never hardcoded. |
| B2 | `window_engine.py` | 30-minute open-window warning was dead code in YAML (trigger defined, no handler). `async_tick()` now sends the escalation notification. |
| B3 | `window_engine.py` | Window close always restored to `schedule` even when nobody was home. Now checks presence first — leaves room in AWAY if house is empty. |
| B4 | `presence_engine.py` | Alarm `armed_away → disarmed` had no handler. Heating stayed off permanently after disarm. Now re-evaluates presence on disarm and restores heating if someone is home. |

---

## Known technical fixes applied (code review)

| Issue | File | Fix |
|-------|------|-----|
| Missing `from __future__ import annotations` | `const.py` | Added |
| Deadlock risk: `async_tick` held `_lock` across full await chain | `controller.py` | Lock now only guards minimal critical section, released before all awaits |
| `asyncio.ensure_future` (deprecated in HA context) | `presence_engine.py`, `window_engine.py` | Replaced with `hass.async_create_task()` with named tasks |
| `FlowResult` deprecated in HA 2024+ | `config_flow.py` | Replaced with `ConfigFlowResult` (12 occurrences) |
| `except Exception` without `noqa` in `_async_update_data` | `coordinator.py` | Added `# noqa: BLE001` — correct pattern for `UpdateFailed` wrapping |
| `async_get_logbook_entries` does not exist in HA 2024+ | `websocket.py` | Replaced with internal `coordinator._event_log` and zeros for energy chart |
| `State` object has no `.get()` method | `websocket.py` | Changed `(state or {}).get("state")` to `state.state` attribute access |
| `async_register_static_paths` crashes on reload (aiohttp route conflict) | `panel.py` | Session-level flag `_SESSION_KEY` prevents double-registration across reloads |

---

## IQS Quality Scale status

### Bronze (required before release)

| Rule | Status | Notes |
|------|--------|-------|
| `config-flow` | ✅ done | 4-step UI wizard |
| `entity-unique-id` | ✅ done | `f"{entry.entry_id}_{suffix}"` pattern |
| `has-entity-name` | ✅ done | All entities use `_attr_has_entity_name = True` |
| `runtime-data` | ✅ done | `entry.runtime_data = coordinator` |
| `action-setup` | ✅ done | Services registered in `async_setup_entry` |
| `test-before-configure` | ✅ done | Config flow validates entity IDs |
| `unique-config-entry` | ✅ done | `_abort_if_unique_id_configured()` |
| `config-flow-test-coverage` | 🔲 todo | Test file for config flow not written yet |
| `test-before-setup` | 🔲 todo | `ConfigEntryNotReady` not yet raised |
| `entity-event-setup` | ✅ done | Listeners in `_register_listeners()`, removed in `async_shutdown()` |
| `common-modules` | ✅ done | `coordinator.py`, `const.py`, `engine/` |
| `appropriate-polling` | ✅ done | 60s interval, local state only |
| `dependency-transparency` | ✅ done | `requirements = []` |
| `brands` | 🔲 todo | `brands/icon.png` not created |
| `docs-*` | ✅ done | README covers all required sections |

### Silver (current target)

| Rule | Status | Notes |
|------|--------|-------|
| `action-exceptions` | ✅ done | `ServiceValidationError` raised on failure |
| `config-entry-unloading` | ✅ done | `async_unload_entry` unloads platforms + shuts down engines |
| `entity-unavailable` | 🔲 todo | Unavailable climate → unavailable HM sensor not yet implemented |
| `integration-owner` | ✅ done | `codeowners: ["@kingpainter"]` |
| `log-when-unavailable` | 🔲 todo | Not yet implemented |
| `parallel-updates` | ✅ done | `PARALLEL_UPDATES = 1` in all platform files |
| `test-coverage` | 🔲 todo | 36 tests, coverage not yet measured |
| `reauthentication-flow` | exempt | No authentication required |

### Gold (aspirational)

| Rule | Status | Notes |
|------|--------|-------|
| `entity-translations` | ✅ done | All names from `strings.json` |
| `entity-device-class` | ✅ done | `ENERGY`, `DURATION`, `WINDOW`, `HEAT` used |
| `entity-category` | ✅ done | `DIAGNOSTIC` and `CONFIG` applied |
| `diagnostics` | 🔲 todo | `diagnostics.py` not written |
| `reconfiguration-flow` | ✅ done | Options flow: edit global, add/delete rooms and persons |
| `repair-issues` | 🔲 todo | Missing entity → RepairIssue not implemented |
| `docs-troubleshooting` | ✅ done | README troubleshooting section present |
| `docs-examples` | ✅ done | 3 automation examples in README |

---

## What is not yet built (roadmap)

### Fase 3 — Advanced (planned)

| Feature | File | Description |
|---------|------|-------------|
| Pre-heat engine | `engine/preheat_engine.py` | Start heating before arrival using HA Companion travel_time |
| Season engine | `engine/season_engine.py` | Auto-detect Winter/Summer from weather entity |
| Waste calculator | `engine/waste_calculator.py` | Proper kWh estimation replacing the tick-accumulator placeholder |
| Diagnostics | `diagnostics.py` | `async_get_config_entry_diagnostics()` |
| Config entry not ready | `__init__.py` | Raise `ConfigEntryNotReady` if first coordinator refresh fails |
| Energy chart data | `websocket.py` | Real kWh data from recorder once waste_calculator exists |
| Event log | `coordinator.py` | `log_event()` method so History tab shows real events |
| HACS | `hacs.json` | Package for HACS distribution |

---

## Commit suggestion for current state

```
feat(platforms): add sensor, binary_sensor, select, switch — enable all platforms
fix(websocket): State.get() → State.state attribute, remove broken logbook API
fix(panel): prevent aiohttp route conflict on config entry reload
fix(engines): ensure_future → async_create_task, deadlock in controller.py
fix(config_flow): FlowResult → ConfigFlowResult (HA 2024+)
fix(const): add from __future__ import annotations
```
