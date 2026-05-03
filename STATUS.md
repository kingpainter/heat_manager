# Heat Manager — Project Status

**Last updated:** 2026-05-03 · v0.3.6
**Version:** 0.3.6
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included
**Status:** Stable — full stability pass + new features deployed

---

## Repository overview

```
heat_manager/
├── .cursorrules                  14-section development ruleset (IQS Bronze–Platinum)
├── README.md                     Full English docs: install, config, services, entities
├── CHANGELOG.md                  Keep a Changelog format — [0.3.6] through [0.1.0]
├── GIT_WORKFLOW.md               GitHub Desktop guide for Windows
├── STATUS.md                     This file
├── hacs.json                     HACS distribution metadata
├── custom_components/
│   └── heat_manager/             ~145 KB — 16 Python files + 2 JS files
│       ├── engine/               ~85 KB — 9 engine files (valve_protection added)
│       └── frontend/             ~75 KB — panel.js (v0.3.4) + card.js (v0.3.1)
└── tests/
    └── components/heat_manager/  ~60 KB — 7 test files, 60+ tests
```

---

## File inventory

### Integration root

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration. Stores entry_id in hass.data (S-8) |
| `manifest.json` | v0.3.6, config_flow: true, iot_class: local_push |
| `const.py` | All constants and enums. CONF_HUMIDITY_SENSOR, NETATMO_API_CALL_DELAY_SEC added |
| `coordinator.py` | DataUpdateCoordinator — 7 engines + PID tick. calendar_season + days_above_threshold properties (I-2) |
| `config_flow.py` | 4-step setup wizard + options flow. Room schema: co2_sensor, room_temp_sensor, humidity_sensor. Per-person lead time max 90 min |
| `diagnostics.py` | async_get_config_entry_diagnostics() — Gold IQS |
| `panel.py` | Static paths in async_setup (process-level). Sidebar panel in async_setup_entry |
| `websocket.py` | get_state + get_history. _get_entry() uses stored entry_id (S-8). _fmt_time neutral format (S-7) |
| `select.py` | controller_state + season_mode |
| `sensor.py` | pause_remaining, energy_wasted/saved (MEASUREMENT, I-1), efficiency_score, room state, window duration (date fix, S-6) |
| `binary_sensor.py` | any_window_open, heating_wasted, per-room window sensors, per-room mold risk (F6) |
| `switch.py` | Per-room override switches |
| `icons.json` | Entity icon overrides — Gold IQS |
| `services.yaml` | set_controller_state, pause, resume, force_room_on |
| `strings.json` | config + options + entity + exceptions |
| `quality_scale.yaml` | IQS rule tracking |
| `translations/en.json` | Full English |
| `translations/da.json` | Full Danish |

### Engine layer (9 files)

| File | Description |
|------|-------------|
| `engine/controller.py` | ON/PAUSE/OFF state machine. S-1: day-counter replaces timestamp list. S-5: effective_season in _apply_off_fallback |
| `engine/presence_engine.py` | Presence logic, grace periods, alarm integration, NETATMO_API_CALL_DELAY_SEC |
| `engine/window_engine.py` | Per-room window detection, CO₂-aware notifications. S-3: TRV-type routing in close |
| `engine/season_engine.py` | AUTO → WINTER/SUMMER via outdoor temp day-counter |
| `engine/waste_calculator.py` | Phase 4 + CO₂ weighting. S-2: tick_hours from SCAN_INTERVAL_SECONDS |
| `engine/preheat_engine.py` | travel_time listener, per-person lead time. S-4: TRV-type routing in preheat |
| `engine/pid_controller.py` | Discrete-time PI(D) controller, power_to_setpoint(), anti-windup |
| `engine/valve_protection_engine.py` | **NEW (F4)** Weekly valve exercise during 02–03 night window when controller OFF |

### Frontend

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | v0.3.4 — Cloud status banner detects Netatmo outages via entity state/staleness |
| `frontend/heat-manager-card.js` | v0.3.1 — Indeklima design system, section-box, SVG ring, room chips |
| `frontend/heat_manager_logo1.png` | 44 KB. Served at `/api/heat_manager-logo` |

### Tests (7 files, 60+ tests)

| File | Tests |
|------|-------|
| `test_controller_engine.py` | 13 |
| `test_presence_engine.py` | 11 |
| `test_window_engine.py` | 12 |
| `test_season_engine.py` | 9 |
| `test_waste_calculator.py` | 10 |
| `test_preheat_engine.py` | 14 |
| `test_pid_controller.py` | 24 |
| `test_pid_tick.py` | 12 |

---

## Architecture: sensor input hierarchy

### Outdoor temperature
```
1. CONF_OUTDOOR_TEMP_SENSOR   sensor.*  — local station
2. weather.* attribute                  — forecast fallback
```

### Room current temperature (PID feedback)
```
1. CONF_ROOM_TEMP_SENSOR       sensor.*  — wall probe
2. homekit_climate_entity      climate.* — Netatmo local HAP <100 ms
3. climate_entity              climate.* — cloud entity
```

### CO₂ context (window notifications + waste weighting)
```
CONF_CO2_SENSOR  sensor.*  — ppm
  ≥ 900 ppm  → "ventilation", waste_weight = 0.50
  < 900 ppm  → "heat loss",   waste_weight = 1.00
  absent     → no change
```

### Mold risk (F6)
```
CONF_HUMIDITY_SENSOR  sensor.*  — % RH (required)
CONF_ROOM_TEMP_SENSOR sensor.*  — °C  (preferred, falls back to climate entity)
  RH ≥ 70% AND T_room ≤ T_dewpoint + 1°C → binary_sensor = True
  Magnus formula (Lawrence 2005), DIN 4108-2 simplified
```

---

## Bug / stability fix history

| ID | Version | File | Description |
|----|---------|------|-------------|
| S-1 | 0.3.5 | `controller.py` | `_outdoor_temp_history` list lost on restart → day-counter |
| S-2 | 0.3.5 | `waste_calculator.py` | `tick_hours` hardcoded 60 s → `SCAN_INTERVAL_SECONDS` |
| S-3 | 0.3.5 | `window_engine.py` | Window close always used Netatmo preset → TRV-type routing |
| S-4 | 0.3.5 | `preheat_engine.py` | Preheat always used Netatmo preset → TRV-type routing |
| S-5 | 0.3.5 | `controller.py` | `_apply_off_fallback` checked `season_mode` not `effective_season` |
| S-6 | 0.3.6 | `sensor.py` | Window duration reset on same day-of-month → `now.date()` |
| S-7 | 0.3.6 | `websocket.py` | `_fmt_time` hardcoded Danish "i går" → neutral format |
| S-8 | 0.3.6 | `websocket.py` + `__init__.py` | `_get_entry()` wrong entry on reinstall → stored entry_id |
| B1 | 0.2.x | `window_engine.py` | Leading-dot typo in entity ID |
| B2 | 0.2.x | `window_engine.py` | 30-min warning was dead code |
| B3 | 0.2.x | `window_engine.py` | Window close restored schedule even nobody home |
| B4 | 0.2.x | `presence_engine.py` | Alarm disarmed had no handler |
| B5–B7 | 0.2.1 | `panel.js` | WebKit ShadowRoot crash + blink issues |
| B-429 | 0.2.8 | `presence_engine.py` | Netatmo 429 on simultaneous setthermmode |
| B-429-RESTORE-RACE | 0.3.2 | `presence_engine.py` | Concurrent restore callers multiplied API calls |

---

## IQS Quality Scale

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

## Backlog

| Item | Priority |
|------|----------|
| `brands/icon.png` | Medium — required for HACS/official listing |
| `repair-issues` | Low — RepairIssue when climate entity missing at startup (F-3) |
| `strict-typing` | Low — full mypy pass |
| `config-flow-test-coverage` | Low |
| CO₂ threshold configurable | Low — currently fixed at 900 ppm (F-2) |
| EKF thermal model | Future — learned heat loss rate replaces fixed PID gains |
| Solar gain in SeasonEngine | Future |
