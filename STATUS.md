# Heat Manager — Project Status

**Last updated:** 2026-03-28
**Version:** 0.2.9
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included

---

## Repository overview

```
heat_manager/
├── .cursorrules               14-section development ruleset (IQS Bronze–Platinum)
├── README.md                  Full English docs: install, config, services, entities
├── CHANGELOG.md               Keep a Changelog format — [0.2.9] through [0.1.0]
├── GIT_WORKFLOW.md            GitHub Desktop guide for Windows
├── STATUS.md                  This file
├── hacs.json                  HACS distribution metadata
├── custom_components/
│   └── heat_manager/          ~125 KB — 16 Python files + 2 JS files
│       ├── engine/            ~75 KB — 8 engine files
│       └── frontend/          ~53 KB — panel.js (31 KB) + card.js (22 KB)
└── tests/
    └── components/heat_manager/   ~60 KB — 7 test files, 60+ tests
```

---

## File inventory

### Integration root (16 files)

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration with translation keys |
| `manifest.json` | v0.2.9, config_flow: true, iot_class: local_push |
| `const.py` | All constants and enums. Includes PID gains, sensor input keys, CO₂ threshold |
| `coordinator.py` | DataUpdateCoordinator — 6 engines + PID tick, unified temp/CO₂ helpers |
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
| `engine/window_engine.py` | Per-room window detection, CO₂-aware notifications, PID-routed setpoint, pid.reset() on open |
| `engine/season_engine.py` | AUTO → WINTER/SUMMER via outdoor temp day-counter |
| `engine/waste_calculator.py` | Phase 4 + CO₂ weighting: heating_power_request × room_wattage; ventilation reduces waste 50%; Δtemp fallback for non-Netatmo |
| `engine/preheat_engine.py` | sensor.`<person>`_travel_time_home listener, arming/disarming, lead time |
| `engine/pid_controller.py` | Discrete-time PI(D) controller. power_to_setpoint() mapper. Anti-windup clamp |

### Frontend (2 files, ~53 KB)

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | 4-tab sidebar panel. iOS/WebKit safe. Blink-free |
| `frontend/heat-manager-card.js` | Lovelace card + editor. Picker auto-registration |

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

## Architecture: sensor input hierarchy (v0.2.9)

### Outdoor temperature priority

```
1. CONF_OUTDOOR_TEMP_SENSOR   sensor.*  — local station, updates every 5 min
   └─ SeasonEngine day-counter
   └─ get_away_temperature()
   └─ ControllerEngine auto-off

2. weather.* attribute         — forecast grid point, fallback when sensor absent/unavailable
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
  WindowEngine  → notification label: "ventilation" (≥900 ppm) or "heat loss" (<900 ppm)
  WasteCalc     → waste_weight: 0.50 (≥900 ppm) or 1.00 (<900 ppm)
  absent        → no label appended, waste_weight = 1.00 (unchanged behaviour)
```

---

## Architecture: Netatmo NRV dual-entity routing

Netatmo TRV rooms are served by two HA entities simultaneously:

```
Netatmo cloud  ──HTTPS──►  climate.kitchen          (cloud entity)
                             └─ preset_mode writes    (presence/window engines)
                             └─ heating_power_request (waste_calculator)
                             └─ schedule target temp  (PID setpoint source)

Netatmo Relay  ◄──HAP/LAN──  climate.netatmo_valve_1  (HomeKit entity)
192.168.40.201:5001            └─ current_temperature  (PID feedback — unless room_temp_sensor set)
                               └─ set_temperature      (PID output, <100 ms)
```

The cloud entity (`climate_entity`) is never written `set_temperature` by
Heat Manager — Netatmo's own MPC and schedule system remain fully in
control. The HomeKit entity (`homekit_climate_entity`) receives proportional
setpoints via local HAP only when PID is active and the room is NORMAL.

---

## PID controller

A discrete-time PI(D) controller runs per room every 60 seconds.

| Parameter | Default | Notes |
|-----------|---------|-------|
| Kp | 0.5 | Proportional gain |
| Ki | 0.02 | Integral gain per tick (~50 min to clear 1 °C offset) |
| Kd | 0.0 | Derivative disabled — TRV thermal lag makes D noisy |
| trv_max | 28.0 °C | Setpoint ceiling when power = 1.0 |
| trv_min | room away_temp_override | Floor when power = 0.0 |
| delta threshold | 0.5 °C | Suppress command if HomeKit setpoint change < 0.5 °C |

Anti-windup clamp: ±5.0 integral units. PID resets automatically on:
AWAY, WINDOW_OPEN, PRE_HEAT, PAUSE, OFF, SUMMER, HomeKit unavailable.

Temperature feedback source: `room_temp_sensor` (if set) → HomeKit entity → cloud entity.

---

## Energy accounting (Phase 4 + CO₂ weighting)

WasteCalculator uses real Netatmo data when available:

```
actual_kWh = (heating_power_request / 100) × room_wattage × tick_hours
```

CO₂ waste weight (v0.2.9):
```
waste_kWh_attributed = actual_kWh × waste_weight

waste_weight:
  no CO₂ sensor  → 1.00  (unchanged)
  CO₂ < 900 ppm  → 1.00  (heat loss — full attribution)
  CO₂ ≥ 900 ppm  → 0.50  (ventilation — half attribution)
```

Fallback for non-Netatmo rooms: `Δtemp × 0.1 kWh/°C/h`

Away-savings use last known non-zero `heating_power_request` as baseline
(falls back to 50 % of `room_wattage` if no history).

---

## Room configuration fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `room_name` | string | — | Display name |
| `climate_entity` | entity | — | Cloud/primary climate entity (preset_mode + schedule setpoint) |
| `homekit_climate_entity` | entity | — | **Optional.** Local HomeKit entity (HAP). PID writes here |
| `window_sensors` | entity list | [] | Window/door sensors |
| `window_delay_min` | min | 5 | Minutes before heating drops on window open |
| `away_temp_override` | °C | 10.0 | Frost-guard floor (window open / PID trv_min) |
| `room_wattage` | W | 1000 | Rated heating power for energy calculations |
| `trv_type` | string | netatmo | `netatmo` or `zigbee` — routes presence commands correctly |
| `pi_demand_entity` | entity | — | **Optional.** Z2M `pi_heating_demand` sensor for Zigbee TRVs |
| `co2_sensor` | entity | — | **Optional.** CO₂ sensor — enriches window notifications and weights waste |
| `room_temp_sensor` | entity | — | **Optional.** External room probe — improves PID accuracy |

---

## Global configuration fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `weather_entity` | entity | — | Weather entity for outdoor temp and season |
| `outdoor_temp_sensor` | entity | — | **Optional.** Local outdoor sensor — overrides weather entity temp |
| `notify_service` | string | — | HA notify service |
| `away_temp_mild` | °C | 17.0 | Away setpoint — mild weather |
| `away_temp_cold` | °C | 15.0 | Away setpoint — cold weather |
| `mild_threshold` | °C | 8.0 | Mild/cold boundary |
| `grace_day_min` | min | 30 | Grace period — daytime |
| `grace_night_min` | min | 15 | Grace period — night-time |
| `auto_off_temp_threshold` | °C | 18.0 | Sustained outdoor temp for auto-off |
| `auto_off_temp_days` | days | 5 | Days above threshold before auto-off fires |

---

## Entities

| Entity ID | Type | Default | Notes |
|-----------|------|---------|-------|
| `select.heat_manager_controller_state` | Select | enabled | On / Pause / Off |
| `select.heat_manager_season_mode` | Select | **disabled** | Auto / Winter / Summer (CONFIG) |
| `sensor.heat_manager_pause_remaining` | Sensor | **disabled** | Minutes left in pause (DIAGNOSTIC) |
| `sensor.heat_manager_energy_wasted_today` | Sensor | enabled | kWh wasted today (CO₂-weighted) |
| `sensor.heat_manager_energy_saved_today` | Sensor | enabled | kWh saved today |
| `sensor.heat_manager_efficiency_score` | Sensor | **disabled** | Daily score 0–100 (DIAGNOSTIC) |
| `sensor.heat_manager_<room>_state` | Sensor | enabled | normal / away / window_open / pre_heat / override |
| `sensor.heat_manager_<room>_window_duration` | Sensor | **disabled** | Minutes window open today (DIAGNOSTIC) |
| `binary_sensor.heat_manager_any_window_open` | Binary | enabled | Any window open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | **disabled** | Window open + heating running (DIAGNOSTIC) |
| `binary_sensor.heat_manager_<room>_window` | Binary | **disabled** | Per-room window open (DIAGNOSTIC) |
| `switch.heat_manager_<room>_override` | Switch | **disabled** | Manual room override (CONFIG) |

---

## Services

| Service | Parameters | Description |
|---------|-----------|-------------|
| `heat_manager.set_controller_state` | `state: on\|pause\|off` | Change controller state |
| `heat_manager.pause` | `duration_minutes: 1–480` | Pause for specific duration |
| `heat_manager.resume` | — | Resume from pause |
| `heat_manager.force_room_on` | `room_name: str` | Force room to schedule mode |

---

## Bug fix history

| ID | Engine | Description |
|----|--------|-------------|
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

---

## IQS Quality Scale

### Bronze ✅

All Bronze rules complete. `brands/icon.png` marked `deferred`.

### Silver ✅

All Silver rules complete.

### Gold — mostly complete

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
| `brands/icon.png` | Medium | Required for HACS/official listing. Deferred |
| `repair-issues` | Low | RepairIssue when climate entity missing at startup |
| `strict-typing` | Low | Full mypy pass |
| `config-flow-test-coverage` | Low | Test file for config_flow steps not written |
| Persistent energy history | Low | Daily kWh resets on HA restart |
| CO₂ threshold configurable | Low | Currently fixed at 900 ppm — could be a per-room option |
| EKF thermal model | Future | Replace fixed PID gains with per-room learned heat loss rate |
| Mold risk sensor | Future | DIN 4108-2 surface humidity binary_sensor per room |
| Solar gain in SeasonEngine | Future | Sun angle + cloud cover reduces unnecessary heating |
| Valve protection engine | Future | Periodic TRV cycle to prevent calcification |
