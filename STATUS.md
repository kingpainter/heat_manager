# Heat Manager — Project Status

**Last updated:** 2026-05-03 · v0.3.9
**Version:** 0.3.9
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included
**Status:** Stable — full stability pass, HomeKit-first routing, Netatmo weather integration, inline panel config

---

## Repository overview

```
heat_manager/
├── .cursorrules                  14-section development ruleset (IQS Bronze–Platinum)
├── README.md                     Full English docs: install, config, services, entities
├── CHANGELOG.md                  Keep a Changelog format — [0.3.9] through [0.1.0]
├── GIT_WORKFLOW.md               GitHub Desktop guide for Windows
├── STATUS.md                     This file
├── hacs.json                     HACS distribution metadata
├── custom_components/
│   └── heat_manager/             ~160 KB — 16 Python files + 2 JS files
│       ├── engine/               ~90 KB — 9 engine files
│       └── frontend/             ~80 KB — panel.js (v0.3.9) + card.js (v0.3.1)
└── tests/
    └── components/heat_manager/  ~60 KB — 7 test files, 60+ tests
```

---

## File inventory

### Integration root

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration. Stores entry_id in hass.data |
| `manifest.json` | v0.3.9, config_flow: true, iot_class: local_push |
| `const.py` | All constants. CONF_OUTDOOR_HUMIDITY_SENSOR, CONF_PRECIPITATION_SENSOR, CONF_WIND_SPEED_SENSOR, WIND_FAST_MS, DEFAULT_WINDOW_DELAY_WIND_MIN added |
| `coordinator.py` | DataUpdateCoordinator — 9 engines + PID tick. get_write_entity(), needs_cloud_delay(), get_outdoor_humidity(), get_precipitation(), get_wind_speed(), is_raining() |
| `config_flow.py` | 4-step setup wizard + options flow. Global schema: outdoor_humidity_sensor, precipitation_sensor, wind_speed_sensor |
| `diagnostics.py` | async_get_config_entry_diagnostics(). Fixed crash on _outdoor_temp_history (v0.3.8) |
| `panel.py` | Static paths (process-level async_setup). Sidebar panel (async_setup_entry) |
| `websocket.py` | get_state, get_history, update_config. Rooms payload includes heating_power. _get_entry() uses stored entry_id |
| `select.py` | controller_state + season_mode. Season mode now persists to entry.options |
| `sensor.py` | pause_remaining, energy_wasted/saved, efficiency_score, room state, window duration, per-room pid_power |
| `binary_sensor.py` | any_window_open, heating_wasted, cloud_available, per-room window, per-room mold_risk |
| `switch.py` | Per-room override switches. Uses get_write_entity() + TRV routing |
| `icons.json` | Entity icon overrides — Gold IQS |
| `services.yaml` | set_controller_state, pause, resume, force_room_on |
| `strings.json` | config + options + entity + exceptions |
| `quality_scale.yaml` | IQS rule tracking |
| `translations/en.json` | Full English |
| `translations/da.json` | Full Danish |

### Engine layer (9 files)

| File | Description |
|------|-------------|
| `engine/controller.py` | ON/PAUSE/OFF. S-1 day-counter. S-5 effective_season. H-5 HomeKit for hvac_mode:off. H-6 conditional delay |
| `engine/presence_engine.py` | Presence, grace periods, alarm. H-6 conditional delay. NETATMO_API_CALL_DELAY_SEC |
| `engine/window_engine.py` | Window detection. H-1 HomeKit write. Weather-aware delay (rain/wind). Weather-aware CO₂ label |
| `engine/season_engine.py` | AUTO → WINTER/SUMMER via outdoor temp day-counter |
| `engine/waste_calculator.py` | heating_power_request × wattage. CO₂ weighting. Rain overrides CO₂ (full waste) |
| `engine/preheat_engine.py` | travel_time listener, per-person lead time, TRV routing |
| `engine/pid_controller.py` | Discrete-time PI(D), power_to_setpoint(), anti-windup |
| `engine/valve_protection_engine.py` | Weekly valve exercise 02–03, controller OFF only. HomeKit preferred |

### Frontend

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | v0.3.9 — Cloud banner, inline alarm/notify editing, Konfiguration tab with forklaringstekst |
| `frontend/heat-manager-card.js` | v0.3.1 — Indeklima design system |
| `frontend/heat_manager_logo1.png` | 44 KB. Served at `/api/heat_manager-logo` |

### Tests (7 test files, 60+ tests)

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
1. outdoor_temp_sensor         sensor.*  — local station (Netatmo outdoor module etc.)
2. weather.* attribute                   — forecast fallback
```

### Room temperature (PID feedback)
```
1. room_temp_sensor            sensor.*  — wall probe, best accuracy
2. homekit_climate_entity      climate.* — Netatmo local HAP, <100 ms
3. climate_entity              climate.* — cloud entity, last resort
```

### Write channel (set_temperature)
```
1. homekit_climate_entity  — local LAN, no rate limits, no 429 risk  ← preferred
2. climate_entity          — Netatmo cloud                            ← fallback
Note: preset_mode writes (away/schedule) always go to cloud entity
```

### Weather-aware window logic
```
is_raining()           → delay = 1 min, waste_weight = 1.00, label = 🌧️
wind ≥ WIND_FAST_MS    → delay = 1 min, label = 💨
co2 ≥ 900 ppm          → waste_weight = 0.50, label = "ventilation"
otherwise              → configured delay, waste_weight = 1.00
```

### Mold risk
```
CONF_HUMIDITY_SENSOR   sensor.*  — indoor RH % (required)
CONF_ROOM_TEMP_SENSOR  sensor.*  — preferred temp source
  RH ≥ 70% AND T_room ≤ T_dewpoint + 1°C → True
  Magnus formula (Lawrence 2005), DIN 4108-2 simplified
  outdoor_humidity_pct exposed as extra_state_attribute
```

---

## Bug / stability fix history

| ID | Version | File | Description |
|----|---------|------|-------------|
| S-1 | 0.3.5 | `controller.py` | `_outdoor_temp_history` lost on restart → day-counter |
| S-2 | 0.3.5 | `waste_calculator.py` | `tick_hours` hardcoded → `SCAN_INTERVAL_SECONDS` |
| S-3 | 0.3.5 | `window_engine.py` | Window close ignored TRV type → routing added |
| S-4 | 0.3.5 | `preheat_engine.py` | Preheat ignored TRV type → routing added |
| S-5 | 0.3.5 | `controller.py` | `_apply_off_fallback` used `season_mode` not `effective_season` |
| S-6 | 0.3.6 | `sensor.py` | Window duration reset on day-of-month not date |
| S-7 | 0.3.6 | `websocket.py` | `_fmt_time` hardcoded Danish |
| S-8 | 0.3.6 | `websocket.py` + `__init__.py` | `_get_entry()` wrong entry on reinstall |
| H-1 | 0.3.7 | `window_engine.py` | Window open setpoint used cloud → HomeKit preferred |
| H-4 | 0.3.7 | `coordinator.py` | `get_write_entity()` + `needs_cloud_delay()` helpers added |
| H-5 | 0.3.7 | `controller.py` | `_apply_off_fallback` hvac_mode:off → HomeKit preferred |
| H-6 | 0.3.7 | `controller.py` + `presence_engine.py` | Delay skipped for HomeKit rooms |
| BUG | 0.3.8 | `diagnostics.py` | Crash on `_outdoor_temp_history` after S-1 |
| BUG | 0.3.8 | `switch.py` | Override always used cloud + wrong TRV routing |
| BUG | 0.3.8 | `select.py` | Season mode not persisted across restart |
| BUG | 0.3.8 | `websocket.py` | Rooms temp used cloud not `get_room_current_temp()` |

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
| `repair-issues` (F-3) | Low — RepairIssue when climate entity missing at startup |
| `strict-typing` | Low — full mypy pass |
| `config-flow-test-coverage` | Low |
| CO₂ threshold configurable (F-2) | Low — currently fixed at 900 ppm |
| Night setback mode | Medium — reduce setpoints N°C during configured night hours |
| EKF thermal model | Future — learned heat loss rate replaces fixed PID gains |
| Solar gain in SeasonEngine | Future |
