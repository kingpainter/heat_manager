# Heat Manager — Project Status

**Last updated:** 2026-05-22 · v0.4.6
**Version:** 0.4.6
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included
**Status:** Stable — Gold IQS complete, full stability pass, HomeKit-first routing

---

## Repository overview

```
heat_manager/
├── .cursorrules                  14-section development ruleset (IQS Bronze–Platinum)
├── README.md                     Full English docs: install, config, services, entities
├── CHANGELOG.md                  Keep a Changelog format — [0.4.6] through [0.1.0]
├── GIT_WORKFLOW.md               GitHub Desktop guide for Windows
├── STATUS.md                     This file
├── hacs.json                     HACS distribution metadata
├── custom_components/
│   └── heat_manager/             ~175 KB — 16 Python files + 2 JS files
│       ├── engine/               ~90 KB — 9 engine files
│       └── frontend/             ~80 KB — panel.js (v0.3.9) + card.js (v0.3.1)
└── tests/
    └── components/heat_manager/  ~100 KB — 11 test files, 100+ tests
```

---

## File inventory

### Integration root

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration, repair issues, stale device cleanup |
| `manifest.json` | v0.4.6, config_flow: true, iot_class: local_push |
| `const.py` | All constants. CONF_NIGHT_SETBACK_*, CONF_CO2_THRESHOLD, REPAIR_ISSUE_MISSING_CLIMATE |
| `coordinator.py` | DataUpdateCoordinator — 9 engines + PID tick. Per-engine exception isolation. global_device_info(), room_device_info(), get_room_co2_threshold(), is_night_setback_active(), night_setback_delta() |
| `config_flow.py` | 4-step setup wizard + options flow. Night setback + CO₂ threshold per room |
| `diagnostics.py` | async_get_config_entry_diagnostics() |
| `panel.py` | Static paths (process-level async_setup). Sidebar panel (async_setup_entry) |
| `websocket.py` | get_state, get_history, update_config. _get_entry() uses entry.runtime_data exclusively |
| `select.py` | controller_state + season_mode. Both assigned to global device |
| `sensor.py` | pause_remaining, energy_wasted/saved, efficiency_score, room state, window duration, per-room pid_power. All assigned to devices |
| `binary_sensor.py` | any_window_open, heating_wasted, cloud_available, per-room window, per-room mold_risk. All assigned to devices |
| `switch.py` | Per-room override switches. Assigned to room devices |
| `icons.json` | Entity icon overrides — Gold IQS |
| `services.yaml` | set_controller_state, pause, resume, force_room_on |
| `strings.json` | config + options + entity + issues + exceptions |
| `quality_scale.yaml` | IQS rule tracking — all Gold rules done or exempt |
| `translations/en.json` | Full English |
| `translations/da.json` | Full Danish |

### Engine layer (9 files)

| File | Description |
|------|-------------|
| `engine/controller.py` | ON/PAUSE/OFF. S-1 day-counter. S-5 effective_season. H-5 HomeKit for hvac_mode:off. H-6 conditional delay |
| `engine/presence_engine.py` | Presence, grace periods, alarm. H-6 conditional delay. NETATMO_API_CALL_DELAY_SEC |
| `engine/window_engine.py` | Window detection. H-1 HomeKit write. Weather-aware delay (rain/wind). Per-room CO₂ threshold in _co2_context_label() |
| `engine/season_engine.py` | AUTO → WINTER/SUMMER via outdoor temp day-counter |
| `engine/waste_calculator.py` | heating_power_request × wattage. Per-room CO₂ threshold. Rain overrides CO₂ (full waste) |
| `engine/preheat_engine.py` | travel_time listener, per-person lead time, TRV routing |
| `engine/pid_controller.py` | Discrete-time PI(D), power_to_setpoint(), anti-windup |
| `engine/valve_protection_engine.py` | Weekly valve exercise 02–03, controller OFF only. HomeKit preferred |

### Frontend

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | v0.3.9 — Cloud banner, inline alarm/notify editing, Konfiguration tab |
| `frontend/heat-manager-card.js` | v0.3.1 — Indeklima design system |
| `frontend/heat_manager_logo1.png` | 44 KB. Served at `/api/heat_manager-logo` |

### Tests (9 test files, 100+ tests)

| File | Coverage |
|------|----------|
| `test_controller_engine.py` | ON/PAUSE/OFF state machine, auto-off, auto-resume |
| `test_presence_engine.py` | Grace periods, alarm integration, force_room_on |
| `test_window_engine.py` | Open/close delays, B3 regression, weather-aware delay |
| `test_season_engine.py` | AUTO→SUMMER/WINTER, day-counter, reset |
| `test_waste_calculator.py` | Waste/savings accumulation, CO₂ weighting, midnight reset |
| `test_preheat_engine.py` | Travel time, lead time, TRV routing |
| `test_pid_controller.py` | PI control, anti-windup, power_to_setpoint |
| `test_coordinator_night_setback.py` | is_night_setback_active(), night_setback_delta() — midnight-spanning windows |
| `test_coordinator_co2_threshold.py` | get_room_co2_threshold() — per-room override, fallback, engine integration |
| `test_repair_issues.py` | _async_check_repair_issues(), _async_remove_stale_devices() |

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
co2 ≥ room_threshold   → waste_weight = 0.50, label = "ventilation"
otherwise              → configured delay, waste_weight = 1.00
```

### CO₂ threshold
```
Per-room CONF_CO2_THRESHOLD overrides global DEFAULT_CO2_VENTILATION_THRESHOLD (900 ppm).
Used in both WindowEngine notifications and WasteCalculator waste attribution.
```

### Night setback
```
CONF_NIGHT_SETBACK_ENABLED  — boolean, default False
CONF_NIGHT_SETBACK_TEMP     — °C subtracted from PID target, default 2.0°C
Uses existing CONF_NIGHT_START_HOUR / CONF_NIGHT_END_HOUR (default 23/7).
Setpoint floor: room away_temp_override. Applied before PID tick.
```

### Mold risk
```
CONF_HUMIDITY_SENSOR   sensor.*  — indoor RH % (required)
CONF_ROOM_TEMP_SENSOR  sensor.*  — preferred temp source
  RH ≥ 70% AND T_room ≤ T_dewpoint + 1°C → True
  Magnus formula (Lawrence 2005), DIN 4108-2 simplified
```

---

## Device registry

| Device | Identifier | Entities |
|--------|-----------|---------|
| Heat Manager (global) | `(DOMAIN, entry_id)` | controller_state, season_mode, energy_wasted/saved, efficiency_score, any_window_open, heating_wasted, cloud_available, pause_remaining |
| `<room_name>` (per room) | `(DOMAIN, entry_id_safe_room)` | room_state, window sensor, mold_risk, override switch, pid_power, window_duration |

Per-room devices link to global via `via_device`. Stale devices removed on every reload.

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
| S-8 | 0.3.6 | `websocket.py` + `__init__.py` | `_get_entry()` wrong entry on reinstall — now uses runtime_data |
| H-1 | 0.3.7 | `window_engine.py` | Window open setpoint used cloud → HomeKit preferred |
| H-4 | 0.3.7 | `coordinator.py` | `get_write_entity()` + `needs_cloud_delay()` helpers added |
| H-5 | 0.3.7 | `controller.py` | `_apply_off_fallback` hvac_mode:off → HomeKit preferred |
| H-6 | 0.3.7 | `controller.py` + `presence_engine.py` | Delay skipped for HomeKit rooms |
| BUG | 0.3.8 | `diagnostics.py` | Crash on `_outdoor_temp_history` after S-1 |
| BUG | 0.3.8 | `switch.py` | Override always used cloud + wrong TRV routing |
| BUG | 0.3.8 | `select.py` | Season mode not persisted across restart |
| BUG | 0.3.8 | `websocket.py` | Rooms temp used cloud not `get_room_current_temp()` |
| ENG | 0.4.1 | `coordinator.py` | Per-engine exception isolation — one failure no longer marks all entities unavailable |
| ENG | 0.4.2 | `websocket.py` | `_get_entry()` uses `entry.runtime_data` exclusively — removed `hass.data` workaround |

---

## IQS Quality Scale

| Rule | Status |
|------|--------|
| **Bronze** | |
| action-setup | ✅ |
| appropriate-polling | ✅ |
| brands | ⏸ deferred |
| common-modules | ✅ |
| config-flow | ✅ |
| config-flow-test-coverage | ✅ |
| dependency-transparency | ✅ |
| docs-* | ✅ |
| entity-event-setup | ✅ |
| entity-unique-id | ✅ |
| has-entity-name | ✅ |
| runtime-data | ✅ |
| test-before-configure | ✅ |
| test-before-setup | ✅ |
| unique-config-entry | ✅ |
| **Silver** | |
| action-exceptions | ✅ |
| config-entry-unloading | ✅ |
| docs-configuration-parameters | ✅ |
| entity-unavailable | ✅ |
| integration-owner | ✅ |
| log-when-unavailable | ✅ |
| parallel-updates | ✅ |
| reauthentication-flow | ✅ exempt |
| test-coverage | ✅ |
| **Gold** | |
| devices | ✅ |
| diagnostics | ✅ |
| discovery | ✅ exempt |
| dynamic-devices | ✅ |
| entity-category | ✅ |
| entity-device-class | ✅ |
| entity-disabled-by-default | ✅ |
| entity-translations | ✅ |
| exception-translations | ✅ |
| icon-translations | ✅ |
| reconfiguration-flow | ✅ |
| repair-issues | ✅ |
| stale-devices | ✅ |
| **Platinum** | |
| strict-typing | 🔲 todo |

---

## Backlog

| Item | Priority |
|------|----------|
| `brands/icon.png` | Medium — required for HACS/official listing |
| `strict-typing` | Low — full mypy pass |
| EKF thermal model | Future — learned heat loss rate replaces fixed PID gains |
| Solar gain in SeasonEngine | Future |
| Per-room always-on toggle | Low — bypass presence for bathrooms/offices |
| Daily heating summary notification | Low — feedback loop for user |
