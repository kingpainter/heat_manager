# Heat Manager — Project Status

**Last updated:** 2026-03-20 (evening)
**Version:** 0.1.0 (unreleased — development)
**Target:** Home Assistant 2025.1+
**Language:** English (DA translations included)

---

## Repository overview

```
heat_manager/
├── .cursorrules               14-section development ruleset (IQS Bronze–Platinum)
├── README.md                  Full English docs: install, config, services, entities
├── CHANGELOG.md               Keep a Changelog format
├── GIT_WORKFLOW.md            GitHub Desktop guide for Windows
├── STATUS.md                  This file
├── custom_components/
│   └── heat_manager/          82 KB — 14 Python files + 2 JS files
│       ├── engine/            36 KB — 3 engine files + __init__
│       └── frontend/          52 KB — panel.js (29 KB) + card.js (23 KB)
└── tests/
    └── components/heat_manager/   23 KB — 2 test files, 36 tests
```

---

## File inventory

### Integration root (14 files, 82 KB)

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 3.6 KB | Setup, service registration, panel + WS bootstrap |
| `manifest.json` | 0.4 KB | v0.1.0, config_flow: true, iot_class: local_push |
| `const.py` | 5.1 KB | All constants, enums (ControllerState, SeasonMode, RoomState, AutoOffReason), defaults |
| `coordinator.py` | 8.8 KB | DataUpdateCoordinator — owns all engines, shared state, 60s tick |
| `config_flow.py` | 18.5 KB | 4-step setup wizard + options flow (add/delete rooms & persons) |
| `panel.py` | 7.1 KB | Sidebar panel + Lovelace card resource registration, duplicate cleanup |
| `websocket.py` | 10.5 KB | WS API: `heat_manager/get_state`, `heat_manager/get_history` |
| `select.py` | 3.3 KB | `controller_state` (On/Pause/Off), `season_mode` (Auto/Winter/Summer) |
| `sensor.py` | 8.3 KB | pause_remaining, energy_wasted_today, efficiency_score, per-room state + window_duration |
| `binary_sensor.py` | 4.4 KB | any_window_open, heating_wasted, per-room window sensors |
| `switch.py` | 3.1 KB | Per-room manual override switches |
| `services.yaml` | 1.1 KB | set_controller_state, pause, resume, force_room_on |
| `strings.json` | 4.8 KB | Base translation keys |
| `quality_scale.yaml` | 3.0 KB | IQS rule tracking (done/todo/exempt) |
| `translations/en.json` | — | Full English translations incl. options flow |
| `translations/da.json` | — | Full Danish translations incl. options flow |

### Engine layer (4 files, 36 KB)

| File | Size | Description |
|------|------|-------------|
| `engine/controller.py` | 11.0 KB | ON/PAUSE/OFF state machine, @guarded decorator, auto-off/resume |
| `engine/presence_engine.py` | 12.8 KB | Presence logic, grace periods, alarm coordination (B4 fix) |
| `engine/window_engine.py` | 12.0 KB | Per-room window detection, 30-min escalation (B1/B2/B3 fixes) |

### Frontend (2 files, 52 KB)

| File | Size | Description |
|------|------|-------------|
| `frontend/heat-manager-panel.js` | 29.4 KB | Sidebar panel — 4 tabs, blink-free controller, vanilla JS |
| `frontend/heat-manager-card.js` | 22.7 KB | Lovelace card + editor — vanilla JS (no LitElement), auto-registers in card picker |

### Tests (2 files, 36 tests)

| File | Tests | Coverage |
|------|-------|---------|
| `test_controller_engine.py` | 13 | State machine, @guarded, auto-off, auto-resume, season logic |
| `test_presence_engine.py` | 11 | Arrivals, departures, grace periods, B4 regression |
| `test_window_engine.py` | 12 | B1/B2/B3 regressions, open/close delay, presence-aware restore |

---

## Entities created

| Entity ID | Type | Notes |
|-----------|------|-------|
| `select.heat_manager_controller_state` | Select | On / Pause / Off — primary control |
| `select.heat_manager_season_mode` | Select | Auto / Winter / Summer (EntityCategory.CONFIG) |
| `sensor.heat_manager_pause_remaining` | Sensor | Minutes left in pause (DIAGNOSTIC) |
| `sensor.heat_manager_energy_wasted_today` | Sensor | kWh wasted today (placeholder accumulator) |
| `sensor.heat_manager_efficiency_score` | Sensor | Daily score 0–100 (DIAGNOSTIC) |
| `sensor.heat_manager_<room>_state` | Sensor | Per-room: normal/away/window_open/pre_heat/override |
| `sensor.heat_manager_<room>_window_duration` | Sensor | Minutes window open today (DIAGNOSTIC) |
| `binary_sensor.heat_manager_any_window_open` | Binary | Any configured window open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | Window open AND climate heating |
| `binary_sensor.heat_manager_<room>_window` | Binary | Per-room window open state |
| `switch.heat_manager_<room>_override` | Switch | Manual override per room (EntityCategory.CONFIG) |

---

## Services

| Service | Parameters | Description |
|---------|-----------|-------------|
| `heat_manager.set_controller_state` | `state: on\|pause\|off` | Change controller state |
| `heat_manager.pause` | `duration_minutes: 1–480` | Pause for specific duration |
| `heat_manager.resume` | — | Resume from pause |
| `heat_manager.force_room_on` | `room_name: str` | Force a specific room to schedule |

---

## Bug fixes from original YAML automations

| ID | Engine | Description |
|----|--------|-------------|
| B1 | `window_engine.py` | Leading-dot typo `.binary_sensor.lukas_vindue_contact` — Lukas' window never detected. Entity IDs now from config flow selector. Regression test: `test_bug_b1_*` |
| B2 | `window_engine.py` | 30-minute open-window escalation was dead code in YAML (trigger defined, handler missing). Now fires in `async_tick()`. Regression test: `test_bug_b2_*` |
| B3 | `window_engine.py` | Window close always restored to `schedule` even when nobody home. Now checks `coordinator.someone_home()` first. Regression test: `test_bug_b3_*` |
| B4 | `presence_engine.py` | Alarm `armed_away → disarmed` had no handler — heating stayed off permanently. Now re-evaluates presence on disarm. Regression test: `test_bug_b4_*` |

---

## Code quality fixes (audit session)

| Issue | File(s) | Fix applied |
|-------|---------|------------|
| Missing `from __future__ import annotations` | `const.py` | Added |
| Deadlock risk: `async_tick` held `_lock` across full await chain | `controller.py` | Lock released before all awaits — only guards minimal critical section |
| `asyncio.ensure_future` deprecated in HA context | `presence_engine.py`, `window_engine.py` | → `hass.async_create_task()` with named tasks throughout |
| `FlowResult` deprecated HA 2024+ | `config_flow.py` | → `ConfigFlowResult` (12 occurrences) |
| Broad `except Exception` without `noqa` | `coordinator.py` | Added `# noqa: BLE001` — correct for `UpdateFailed` wrapping |
| `async_get_logbook_entries` does not exist in HA 2024+ | `websocket.py` | Replaced with internal `coordinator._event_log` store |
| `State.get("state")` — State is not a dict | `websocket.py` | → `state.state` attribute access |
| aiohttp route conflict on config entry reload | `panel.py` | Session-level `_SESSION_KEY` flag prevents double-registration |
| Duplicate Lovelace resources accumulating | `panel.py` | `_register_lovelace_resource()` now removes ALL stale entries before adding canonical URL |
| Card not appearing in Lovelace picker | `heat-manager-card.js` | Removed ES module `import` (LitElement from unpkg) — rewrote as vanilla JS so `window.customCards` registers synchronously |
| `CARDS_FILE` pointed to non-existent filename | `panel.py` | `"heat-manager-cards.js"` → `"heat-manager-card.js"` |
| `getConfigElement()` referenced non-existent editor element | `heat-manager-card.js` | `HeatManagerCardEditor` class written and registered |

---

## IQS Quality Scale

### Bronze — required before release

| Rule | Status | Notes |
|------|--------|-------|
| `config-flow` | ✅ done | 4-step wizard, options flow with add/delete rooms & persons |
| `entity-unique-id` | ✅ done | `f"{entry.entry_id}_{suffix}"` pattern on all entities |
| `has-entity-name` | ✅ done | `_attr_has_entity_name = True` on all entities |
| `runtime-data` | ✅ done | `entry.runtime_data = coordinator` — no `hass.data[DOMAIN]` |
| `action-setup` | ✅ done | All 4 services registered in `async_setup_entry` |
| `test-before-configure` | ✅ done | Entity IDs validated in config flow steps |
| `unique-config-entry` | ✅ done | `_abort_if_unique_id_configured()` |
| `entity-event-setup` | ✅ done | Listeners registered in `_register_listeners()`, unsubbed in `async_shutdown()` |
| `common-modules` | ✅ done | `coordinator.py`, `const.py`, `engine/` |
| `appropriate-polling` | ✅ done | 60s local polling only |
| `dependency-transparency` | ✅ done | `requirements: []` |
| `test-before-setup` | 🔲 todo | `ConfigEntryNotReady` not yet raised on first refresh failure |
| `config-flow-test-coverage` | 🔲 todo | Test file for config_flow not written |
| `brands` | 🔲 todo | `brands/icon.png` not created |

### Silver — current target

| Rule | Status | Notes |
|------|--------|-------|
| `action-exceptions` | ✅ done | `ServiceValidationError` raised, `# noqa: BLE001` on intentional broad catches |
| `config-entry-unloading` | ✅ done | `async_unload_entry` unloads all platforms, shuts down engines, removes panel |
| `parallel-updates` | ✅ done | `PARALLEL_UPDATES = 1` in all 4 platform files |
| `integration-owner` | ✅ done | `codeowners: ["@kingpainter"]` in manifest |
| `entity-unavailable` | 🔲 todo | Unavailable climate entity does not yet propagate to HM sensor |
| `log-when-unavailable` | 🔲 todo | Single WARNING on unavailable, INFO on recovery — not implemented |
| `test-coverage` | 🔲 todo | 36 tests exist, coverage not formally measured |
| `reauthentication-flow` | exempt | No authentication required (local_push) |

### Gold — aspirational

| Rule | Status | Notes |
|------|--------|-------|
| `entity-translations` | ✅ done | All entity names from `strings.json` / translations |
| `entity-device-class` | ✅ done | ENERGY, DURATION, WINDOW, HEAT used appropriately |
| `entity-category` | ✅ done | DIAGNOSTIC and CONFIG applied throughout |
| `reconfiguration-flow` | ✅ done | Options flow: edit global settings, add/delete rooms and persons |
| `docs-troubleshooting` | ✅ done | README troubleshooting section present |
| `docs-examples` | ✅ done | 3 automation examples in README |
| `diagnostics` | 🔲 todo | `diagnostics.py` + `async_get_config_entry_diagnostics()` not written |
| `repair-issues` | 🔲 todo | Missing entity at startup → `RepairIssue` not implemented |

---

## Roadmap — what is not yet built

### Phase 3 (next)

| Feature | File | Description |
|---------|------|-------------|
| Pre-heat engine | `engine/preheat_engine.py` | Start heating before arrival using travel_time sensor |
| Season engine | `engine/season_engine.py` | Auto-detect Winter/Summer from weather entity |
| Waste calculator | `engine/waste_calculator.py` | Proper kWh estimation replacing the tick-accumulator placeholder in sensor.py |
| Event log | `coordinator.py` | `log_event()` method — populates History tab in sidebar panel |
| Energy chart data | `websocket.py` | Real daily kWh from energy sensors once waste_calculator exists |
| Entity unavailable propagation | `sensor.py` | Climate unavailable → HM sensor unavailable |
| ConfigEntryNotReady | `__init__.py` | Raise if first coordinator refresh fails |
| Diagnostics | `diagnostics.py` | `async_get_config_entry_diagnostics()` for Gold IQS |
| Config flow tests | `tests/` | Test file covering setup wizard and options flow |
| HACS packaging | `hacs.json` | Prepare for HACS distribution |

---

## Suggested next commit message

```
fix(panel): deduplicate Lovelace resources, fix CARDS_FILE typo
fix(card): rewrite as vanilla JS — card now appears in Lovelace picker
feat(card): add HeatManagerCardEditor — pencil icon opens editor in Lovelace
chore(status): update STATUS.md
```
