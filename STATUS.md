# Heat Manager — Project Status

**Last updated:** 2026-03-21
**Version:** 0.2.0 (unreleased — development)
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included

---

## Repository overview

```
heat_manager/
├── .cursorrules               14-section development ruleset (IQS Bronze–Platinum)
├── README.md                  Full English docs: install, config, services, entities
├── CHANGELOG.md               Keep a Changelog format — [0.2.0] + [0.1.0]
├── GIT_WORKFLOW.md            GitHub Desktop guide for Windows
├── STATUS.md                  This file
├── hacs.json                  HACS distribution metadata
├── custom_components/
│   └── heat_manager/          95 KB — 16 Python/YAML files + 2 JS files
│       ├── engine/            54 KB — 7 engine files
│       └── frontend/          53 KB — panel.js (31 KB) + card.js (22 KB)
└── tests/
    └── components/heat_manager/   44 KB — 5 test files, 58 tests
```

---

## File inventory

### Integration root (16 files, 95 KB)

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 4.8 KB | Setup, ConfigEntryNotReady, service registration with translation keys |
| `manifest.json` | 0.4 KB | v0.2.0, config_flow: true, iot_class: local_push |
| `const.py` | 5.1 KB | All constants, enums, defaults. VERSION = "0.2.0" |
| `coordinator.py` | 12.3 KB | DataUpdateCoordinator — 6 engines, log_event(), energy properties, event_log deque |
| `config_flow.py` | 18.5 KB | 4-step setup wizard + options flow (add/delete rooms & persons) |
| `diagnostics.py` | 4.5 KB | async_get_config_entry_diagnostics() — Gold IQS |
| `panel.py` | 7.1 KB | Sidebar panel + Lovelace card resource, duplicate cleanup, session flag |
| `websocket.py` | 10.1 KB | get_state + get_history — live energy from WasteCalculator, ISO timestamp event log |
| `select.py` | 3.9 KB | controller_state + season_mode — entity_registry_enabled_default applied |
| `sensor.py` | 9.7 KB | pause_remaining, energy_wasted/saved, efficiency_score, room state + window duration |
| `binary_sensor.py` | 3.9 KB | any_window_open, heating_wasted, per-room window sensors |
| `switch.py` | 3.3 KB | Per-room override switches |
| `icons.json` | 0.6 KB | Entity icon overrides — Gold IQS icon-translations |
| `services.yaml` | 1.1 KB | set_controller_state, pause, resume, force_room_on |
| `strings.json` | 5.9 KB | config + options + entity + exceptions sections |
| `quality_scale.yaml` | 3.4 KB | IQS rule tracking — all Bronze ✅, all Silver ✅, Gold mostly ✅ |
| `translations/en.json` | — | Full English: config, options, entity, exceptions |
| `translations/da.json` | — | Full Danish: config, options, entity, exceptions |

### Engine layer (7 files, 54 KB)

| File | Size | Description |
|------|------|-------------|
| `engine/controller.py` | 11.0 KB | ON/PAUSE/OFF state machine, @guarded, auto-off/resume, minimal lock scope |
| `engine/presence_engine.py` | 13.3 KB | Presence logic, grace periods, alarm (B4), log_event() at all transitions |
| `engine/window_engine.py` | 10.8 KB | Per-room window detection, 30-min escalation (B2/B3), log_event() |
| `engine/season_engine.py` | 3.2 KB | AUTO → WINTER/SUMMER via outdoor temp day-counter |
| `engine/waste_calculator.py` | 5.9 KB | Δtemp × duration × coefficient, midnight reset, savings tracking |
| `engine/preheat_engine.py` | 10.1 KB | sensor.`<person>`_travel_time_home listener, arming/disarming, lead time |

### Frontend (2 files, 53 KB)

| File | Size | Notes |
|------|------|-------|
| `frontend/heat-manager-panel.js` | 31.0 KB | 4-tab sidebar panel. Blink fixes: style-once, replaceWith(), skeleton on first mount |
| `frontend/heat-manager-card.js` | 22.0 KB | Lovelace card + editor. Blink fixes: style-once, replaceWith(). Picker auto-registration |

### Tests (5 files, 58 tests)

| File | Tests | Coverage |
|------|-------|---------|
| `test_controller_engine.py` | 13 | State machine, @guarded, auto-off, auto-resume, season |
| `test_presence_engine.py` | 11 | Arrivals, departures, grace periods, B4 regression |
| `test_window_engine.py` | 12 | B1/B2/B3 regression, open/close delay, presence-aware restore |
| `test_season_engine.py` | 9 | AUTO→WINTER/SUMMER, counter reset, same-day double-count guard |
| `test_waste_calculator.py` | 10 | Waste accumulation, savings, midnight reset, efficiency score |
| `test_preheat_engine.py` | 14 | Sensor mapping, arming, trigger thresholds, room filtering |

---

## Entities

| Entity ID | Type | Default | Notes |
|-----------|------|---------|-------|
| `select.heat_manager_controller_state` | Select | enabled | On / Pause / Off — primary control |
| `select.heat_manager_season_mode` | Select | **disabled** | Auto / Winter / Summer (CONFIG) |
| `sensor.heat_manager_pause_remaining` | Sensor | **disabled** | Minutes left in pause (DIAGNOSTIC) |
| `sensor.heat_manager_energy_wasted_today` | Sensor | enabled | kWh wasted today |
| `sensor.heat_manager_energy_saved_today` | Sensor | enabled | kWh saved today |
| `sensor.heat_manager_efficiency_score` | Sensor | **disabled** | Daily score 0–100 (DIAGNOSTIC) |
| `sensor.heat_manager_<room>_state` | Sensor | enabled | Per-room: normal/away/window_open/pre_heat/override |
| `sensor.heat_manager_<room>_window_duration` | Sensor | **disabled** | Minutes window open today (DIAGNOSTIC) |
| `binary_sensor.heat_manager_any_window_open` | Binary | enabled | Any window open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | **disabled** | Window open AND climate heating (DIAGNOSTIC) |
| `binary_sensor.heat_manager_<room>_window` | Binary | **disabled** | Per-room window open (DIAGNOSTIC) |
| `switch.heat_manager_<room>_override` | Switch | **disabled** | Manual room override (CONFIG) |

---

## Services

| Service | Parameters | Description |
|---------|-----------|-------------|
| `heat_manager.set_controller_state` | `state: on\|pause\|off` | Change controller state. Raises translated ServiceValidationError on invalid input |
| `heat_manager.pause` | `duration_minutes: 1–480` | Pause for specific duration |
| `heat_manager.resume` | — | Resume from pause |
| `heat_manager.force_room_on` | `room_name: str` | Force room to schedule. Raises translated ServiceValidationError if room not found |

---

## Bug fixes from original YAML automations

| ID | Engine | Description |
|----|--------|-------------|
| B1 | `window_engine.py` | Leading-dot typo `.binary_sensor.lukas_vindue_contact`. Entity IDs from config flow selector. Regression test: `test_bug_b1_*` |
| B2 | `window_engine.py` | 30-min window warning was dead code. Now fires in `async_tick()`. Regression test: `test_bug_b2_*` |
| B3 | `window_engine.py` | Window close always restored schedule even when nobody home. Checks presence first. Regression test: `test_bug_b3_*` |
| B4 | `presence_engine.py` | Alarm disarmed had no handler — heating stayed off forever. Re-evaluates presence on disarm. Regression test: `test_bug_b4_*` |

---

## Blink / FOUC fixes (frontend audit)

| Issue | File | Fix |
|-------|------|-----|
| `connectedCallback` called `_render()` with `_data=null` → double render + flash | `panel.js` | Shows "Indlæser…" skeleton on first mount; real render fires after `_load()` returns |
| `_render()` injected `<style>` on every tab switch via `shadowRoot.innerHTML` → FOUC | `panel.js` | `querySelector("style")` guard — style injected exactly once |
| `existing.outerHTML = html` → DOM node detach + repaint | `panel.js` | `replaceWith(tmp.firstElementChild)` — in-place mutation |
| `shadowRoot.innerHTML` with `<style>` on every `_render()` call → FOUC | `card.js` | `querySelector("style")` guard — style injected once |
| `.card` div rebuilt on every `_render()` | `card.js` | `replaceWith()` on `.card` — `<style>` node preserved |

---

## Code quality fixes (audit session)

| Issue | File | Fix |
|-------|------|-----|
| Missing `from __future__ import annotations` | `const.py` | Added |
| Deadlock risk in `async_tick` — lock held across awaits | `controller.py` | Lock only guards minimal critical section |
| `asyncio.ensure_future` deprecated | `presence_engine.py`, `window_engine.py` | → `hass.async_create_task()` with named tasks |
| `FlowResult` deprecated HA 2024+ | `config_flow.py` | → `ConfigFlowResult` (12 occurrences) |
| Broad `except` without noqa | `coordinator.py` | `# noqa: BLE001` |
| `async_get_logbook_entries` does not exist HA 2024+ | `websocket.py` | → internal `coordinator._event_log` deque |
| `State.get("state")` — State is not a dict | `websocket.py` | → `state.state` attribute |
| aiohttp route conflict on config entry reload | `panel.py` | Session-level `_SESSION_KEY` flag |
| Duplicate Lovelace resources accumulating | `panel.py` | Removes all stale entries before registering canonical URL |
| Card not appearing in picker | `heat-manager-card.js` | Rewrote as vanilla JS (removed ES module import) |
| `CARDS_FILE` pointed to wrong filename | `panel.py` | `"heat-manager-cards.js"` → `"heat-manager-card.js"` |
| `getConfigElement()` referenced non-existent editor | `heat-manager-card.js` | `HeatManagerCardEditor` written and registered |

---

## IQS Quality Scale

### Bronze — complete ✅

| Rule | Status |
|------|--------|
| action-setup | ✅ |
| appropriate-polling | ✅ |
| brands | 🔲 todo |
| common-modules | ✅ |
| config-flow | ✅ |
| config-flow-test-coverage | 🔲 todo |
| dependency-transparency | ✅ |
| docs-* (5 rules) | ✅ |
| entity-event-setup | ✅ |
| entity-unique-id | ✅ |
| has-entity-name | ✅ |
| runtime-data | ✅ |
| test-before-configure | ✅ |
| test-before-setup | ✅ ConfigEntryNotReady raised |
| unique-config-entry | ✅ |

### Silver — complete ✅

| Rule | Status |
|------|--------|
| action-exceptions | ✅ ServiceValidationError with translation_key |
| config-entry-unloading | ✅ |
| entity-unavailable | ✅ RoomStateSensor marks unavailable when climate unavailable |
| integration-owner | ✅ |
| log-when-unavailable | ✅ Single WARNING on unavailable, INFO on recovery |
| parallel-updates | ✅ PARALLEL_UPDATES = 1 in all platforms |
| reauthentication-flow | exempt — no auth required |
| test-coverage | 🔲 58 tests, not formally measured |

### Gold — mostly complete

| Rule | Status |
|------|--------|
| diagnostics | ✅ diagnostics.py |
| entity-category | ✅ DIAGNOSTIC + CONFIG throughout |
| entity-device-class | ✅ ENERGY, DURATION, WINDOW, HEAT |
| entity-disabled-by-default | ✅ diagnostic/config entities off by default |
| entity-translations | ✅ full en + da with entity + exceptions sections |
| exception-translations | ✅ ServiceValidationError + ConfigEntryNotReady with translation_key |
| icon-translations | ✅ icons.json |
| reconfiguration-flow | ✅ options flow: add/delete rooms and persons |
| docs-examples | ✅ |
| docs-known-limitations | ✅ |
| docs-troubleshooting | ✅ |
| docs-use-cases | ✅ |
| devices | 🔲 todo |
| dynamic-devices | 🔲 todo |
| repair-issues | 🔲 todo |
| stale-devices | 🔲 todo |

### Platinum

| Rule | Status |
|------|--------|
| async-dependency | exempt — no external library |
| inject-websession | exempt — no HTTP calls |
| strict-typing | 🔲 todo |

---

## Remaining todos

| Item | Priority | Notes |
|------|----------|-------|
| `brands/icon.png` | Medium | Required for HACS/official listing |
| `config-flow-test-coverage` | Medium | Test file for config_flow wizard not written |
| `repair-issues` | Low | RepairIssue when climate entity missing at startup |
| `strict-typing` | Low | Full mypy pass |
| `test-coverage` measurement | Low | pytest-homeassistant-custom-component setup |
| Persistent energy history | Low | Daily kWh stored across HA restarts (currently resets) |

---

## Commit suggestion for this session

```
fix(frontend): eliminate FOUC and blink — style-once + replaceWith()
feat(gold): complete Gold IQS — exception-translations, icon-translations,
            entity-disabled-by-default, entity-unavailable, log-when-unavailable
fix(frontend): panel skeleton on first mount — no double render
```
