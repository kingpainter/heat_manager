# Heat Manager — Project Status

**Last updated:** 2026-04-21 · v0.3.3 deployed
**Version:** 0.3.3
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included
**Status:** Ready for testing — logo served as static HTTP path, "Energi i dag" overview removed from panel

---

## Repository overview

```
heat_manager/
├── .cursorrules               14-section development ruleset (IQS Bronze–Platinum)
├── README.md                  Full English docs: install, config, services, entities
├── CHANGELOG.md               Keep a Changelog format — [0.3.1] through [0.1.0]
├── GIT_WORKFLOW.md            GitHub Desktop guide for Windows
├── STATUS.md                  This file
├── hacs.json                  HACS distribution metadata
├── custom_components/
│   └── heat_manager/          ~130 KB — 16 Python files + 2 JS files
│       ├── engine/            ~75 KB — 8 engine files
│       └── frontend/          ~70 KB — panel.js (35 KB) + card.js (35 KB)
└── tests/
    └── components/heat_manager/   ~60 KB — 7 test files, 60+ tests
```

---

## File inventory

### Integration root (16 files)

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration with translation keys |
| `manifest.json` | v0.3.1, config_flow: true, iot_class: local_push |
| `const.py` | All constants and enums. Includes PID gains, sensor input keys, CO₂ threshold |
| `coordinator.py` | DataUpdateCoordinator — 6 engines + PID tick, unified temp/CO₂ helpers, outdoor sensor priority |
| `config_flow.py` | 4-step setup wizard + options flow. Room schema includes co2_sensor, room_temp_sensor; global schema includes outdoor_temp_sensor |
| `diagnostics.py` | async_get_config_entry_diagnostics() — Gold IQS |
| `panel.py` | Sidebar panel + Lovelace card resource registration, duplicate cleanup |
| `websocket.py` | get_state + get_history — live energy from WasteCalculator, ISO timestamp event log |
| `select.py` | controller_state + season_mode — entity_registry_enabled_default applied |
| `sensor.py` | pause_remaining, energy_wasted/saved, efficiency_score, room state + window duration |
| `binary_sensor.py` | any_window_open, heating_wasted, per-room window sensors |
| `switch.py` | Per-room override switches |
| `icons.json` | Entity icon overrides — Gold IQS icon-translations |
| `services.yaml` | set_controller_state, pause, resume, force_room_on |
| `strings.json` | config + options + entity + exceptions sections |
| `quality_scale.yaml` | IQS rule tracking |
| `translations/en.json` | Full English: config, options, entity, exceptions |
| `translations/da.json` | Full Danish: config, options, entity, exceptions |

### Engine layer (8 files)

| File | Description |
|------|-------------|
| `engine/controller.py` | ON/PAUSE/OFF state machine, @guarded, auto-off/resume |
| `engine/presence_engine.py` | Presence logic, grace periods, alarm integration, log_event() |
| `engine/window_engine.py` | Per-room window detection, CO₂-aware notifications, PID-routed setpoint |
| `engine/season_engine.py` | AUTO → WINTER/SUMMER via outdoor temp day-counter |
| `engine/waste_calculator.py` | Phase 4 + CO₂ weighting: heating_power_request × room_wattage; ventilation reduces waste 50% |
| `engine/preheat_engine.py` | sensor.`<person>`_travel_time_home listener, arming/disarming, lead time |
| `engine/pid_controller.py` | Discrete-time PI(D) controller. power_to_setpoint() mapper. Anti-windup clamp |

### Frontend (2 files, ~70 KB)

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | v0.3.3 — Indeklima design system. Logo served from `/api/heat_manager-logo` static HTTP path (no more inline base64 JPEG). "Energi i dag" overview section removed from Oversigt tab — waste calculator still drives Rooms-tab weekly chart and energy sensors. SVG controller ring, room grid, section-box cards. iOS/WebKit safe. Blink-free. HA restart required for logo registration. |
| `frontend/heat-manager-card.js` | v0.3.1 — Same design system as panel. Section-box, SVG ring, room state chips. Fixed B-CARD-IAH (insertAdjacentHTML crash in card picker). |
| `frontend/heat_manager_logo1.png` | 44 KB. Registered as static HTTP path in `panel.py` at `/api/heat_manager-logo`. Used as panel header icon via CSS `background-image`. |

### Tests (7 files)

| File | Tests | Description |
|------|-------|-------------|
| `test_controller_engine.py` | 13 | State machine, @guarded, auto-off, auto-resume |
| `test_presence_engine.py` | 11 | Arrivals, departures, grace periods, B4 regression |
| `test_window_engine.py` | 12 | B1/B2/B3 regression, open/close delay, presence-aware restore |
| `test_season_engine.py` | 9 | AUTO→WINTER/SUMMER, counter reset, same-day guard |
| `test_waste_calculator.py` | 10 | Waste accumulation, savings, midnight reset, efficiency score |
| `test_preheat_engine.py` | 14 | Sensor mapping, arming, trigger thresholds, room filtering |
| `test_pid_controller.py` | 24 | P/I/D terms, anti-windup, power_to_setpoint, reset, B-PID-1/2 regressions |
| `test_pid_tick.py` | 12 | Guard conditions, happy path, B-PID-2 delta threshold |

---

## Frontend design system (v0.3.0+)

Both the panel and card now share Indeklima's visual language, making them
two sides of the same coin — heat management and climate monitoring in the
same home, with the same look and feel.

### Shared components

| Component | Description |
|-----------|-------------|
| DM Sans + DM Mono | Font family — same as Indeklima |
| `section-box` | Card container with header, title, badge, body |
| SVG ring | Animated arc ring — efficiency score / controller state |
| Chip/badge | Pill labels with background tint matching state colour |
| `badge-pulse` | CSS animation on `window_open` and `pre_heat` badges |

### Heat Manager palette (vs Indeklima)

| State | Heat Manager | Indeklima |
|-------|-------------|-----------|
| Good / active | 🟠 Amber `#f97316` | 🟢 Green `#10b981` |
| Warning | 🟡 Yellow `#eab308` | 🟡 Amber `#f59e0b` |
| Bad / critical | 🔴 Red `#ef4444` | 🔴 Red `#ef4444` |
| Accent | 🔵 Teal `#0ea5e9` | 🔵 Teal `#0ea5e9` |
| Away / inactive | ⚫ Grey `#64748b` | ⚫ Grey `#64748b` |

---

## Architecture: sensor input hierarchy (v0.2.9+)

### Outdoor temperature priority

```
1. CONF_OUTDOOR_TEMP_SENSOR   sensor.*  — local station, updates every 5 min
2. weather.* attribute                  — forecast fallback
```

### Room current temperature priority (PID feedback)

```
1. CONF_ROOM_TEMP_SENSOR       sensor.*  — wall probe, best accuracy
2. homekit_climate_entity      climate.* — Netatmo local HAP, <100 ms
3. climate_entity              climate.* — cloud entity, last resort
```

### CO₂ context (window notifications + waste weighting)

```
CONF_CO2_SENSOR  sensor.*  — ppm
  WindowEngine  → "ventilation" (≥900 ppm) or "heat loss" (<900 ppm)
  WasteCalc     → waste_weight: 0.50 (≥900 ppm) or 1.00 (<900 ppm)
  absent        → no change to existing behaviour
```

---

## Bug fix history

| ID | File | Description |
|----|------|-------------|
| B1 | `window_engine.py` | Leading-dot typo `.binary_sensor.lukas_vindue_contact` |
| B2 | `window_engine.py` | 30-min window warning was dead code |
| B3 | `window_engine.py` | Window close always restored schedule even when nobody home |
| B4 | `presence_engine.py` | Alarm disarmed had no handler — heating stayed off |
| B5 | `panel.js` | `ShadowRoot.insertAdjacentHTML` crashes WebKit/iOS 18 |
| B6 | `panel.js` | ON-button blink on load (double render from connectedCallback) |
| B7 | `panel.js` | Persistent blink from concurrent `_load()` calls |
| B-PID-1 | `pid_controller.py` | Anti-windup must prevent integral buildup during away |
| B-PID-2 | `coordinator.py` | Delta threshold must suppress TRV command spam |
| B-CONFIG-2 | `config_flow.py` | entity selectors reject empty strings for optional fields |
| B-429 | `presence_engine.py` | Netatmo API 429 on simultaneous setthermmode calls |
| B-PANEL-ENTITY-ID | `panel.js` | Entity IDs stale after reinstall (config entry ID changes) |
| B-PANEL-RAF | `panel.js` | requestAnimationFrame stalls when panel not in active viewport |
| B-CARD-IAH | `card.js` | `?.replaceWith?.()` invalid syntax + `insertAdjacentHTML` on ShadowRoot in card picker |

---

## IQS Quality Scale

### Bronze ✅ · Silver ✅ · Gold — mostly complete

| Rule | Status |
|------|--------|
| diagnostics | ✅ |
| entity-category | ✅ |
| entity-device-class | ✅ |
| entity-disabled-by-default | ✅ |
| entity-translations | ✅ |
| exception-translations | ✅ |
| icon-translations | ✅ |
| reconfiguration-flow | ✅ |
| docs-* | ✅ |
| devices | 🔲 todo |
| dynamic-devices | 🔲 todo |
| repair-issues | 🔲 todo |
| stale-devices | 🔲 todo |

---

## Release notes — v0.3.3 (2026-04-21)

**What changed:**

**Frontend:** Logo now served as static HTTP path `/api/heat_manager-logo` instead of inline base64 JPEG in CSS. This fixes shadow DOM rendering inconsistencies in Chrome and Safari, and reduces `panel.js` file size. "Energi i dag" overview section removed from Oversigt tab — the underlying waste calculator remains active and drives the weekly bar chart on the Rum tab. The energy sensors (`energy_wasted_today`, `energy_saved_today`, `efficiency_score`) are unaffected.

**Backend:** `panel.py` now registers the logo PNG as a static HTTP resource with `cache_headers=True`, matching the pattern already used for `panel.js` and `card.js`.

**Deployment status:**

- ✅ GitHub repo: all 5 changed files + docs updated (const.py, manifest.json, panel.py, heat-manager-panel.js, heat_manager_logo1.png)
- ✅ HA server: heat-manager-panel.js, const.py, manifest.json, panel.py deployed; logo file present
- ⚠️ Minor sync issue: `engine/presence_engine.py` is 1.86 KB newer on GitHub (B-429 fix from 0.3.2 not yet deployed)
- ⚠️ Next: Restart Home Assistant to register logo static path. Browser cache-clear alone is insufficient.

**Testing checklist:**

- [ ] HA restart completes without errors
- [ ] Panel loads at `/heat_manager` with orange radiator logo visible in header (no missing image placeholder)
- [ ] Logo background blends with amber gradient correctly
- [ ] Oversigt tab shows Controller + Rooms + Presence + Auto-off sections (no "Energi i dag" card)
- [ ] Rum tab still shows weekly energy bar chart
- [ ] Card picker can find and load heat-manager-card.js
- [ ] All services (pause, resume, set_controller_state) respond normally

**Known issues:**

- None at this time. Report via GitHub Issues.



| Item | Priority | Notes |
|------|----------|-------|
| `brands/icon.png` | Medium | Required for HACS/official listing. Deferred |
| `repair-issues` | Low | RepairIssue when climate entity missing at startup |
| `strict-typing` | Low | Full mypy pass |
| `config-flow-test-coverage` | Low | Test file for config_flow steps not written |
| Persistent energy history | Low | Daily kWh resets on HA restart |
| CO₂ threshold configurable | Low | Currently fixed at 900 ppm |
| EKF thermal model | Future | Replace fixed PID gains with per-room learned heat loss rate |
| Mold risk sensor | Future | DIN 4108-2 surface humidity binary_sensor per room |
| Solar gain in SeasonEngine | Future | Sun angle + cloud cover reduces unnecessary heating |
| Valve protection engine | Future | Periodic TRV cycle to prevent calcification |
