# Heat Manager — Project Status

**Last updated:** 2026-09-02 · v0.7.0
**Version (GitHub):** 0.7.0
**Version (HA server):** 0.6.2 ⚠️ pending deploy
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included
**Status:** Stable — Gold IQS complete, HomeKit-first routing, PID proportional control, boost now functional end-to-end

---

## Repository overview

```
heat_manager/
├── .cursorrules                  14-section development ruleset (IQS Bronze–Platinum)
├── README.md                     Full English docs: install, config, services, entities
├── CHANGELOG.md                  Keep a Changelog format
├── GIT_WORKFLOW.md               GitHub Desktop guide for Windows
├── STATUS.md                     This file
├── hacs.json                     HACS distribution metadata
├── custom_components/
│   └── heat_manager/             ~182 KB — 16 Python files + frontend
│       ├── engine/               ~98 KB — 8 engine files + PID controller
│       └── frontend/             ~187 KB — panel.js + card.js + logo
└── tests/
    └── components/heat_manager/  10 test files
```

---

## File inventory

### Integration root

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration, repair issues, stale device cleanup |
| `manifest.json` | v0.7.0, config_flow: true, iot_class: local_push |
| `const.py` | All constants. CONF_NIGHT_SETBACK_*, CONF_CO2_THRESHOLD, CONF_PID_*, DEFAULT_BOOST_TEMP, REPAIR_ISSUE_MISSING_CLIMATE |
| `coordinator.py` | DataUpdateCoordinator — 7 engines + hybrid PID tick, per-room. Per-engine exception isolation. global_device_info(), room_device_info(), get_room_co2_threshold(), is_night_setback_active(), wake_setback_delta(), async_boost_start()/async_boost_stop() (shared boost implementation), _last_known_rooms/_persons snapshot for reload-skip logic. _async_pid_tick() now regulates Netatmo (HomeKit split-entity) AND local/Zigbee (single-entity, comfort_temp target) rooms, plus outdoor feedforward on both |
| `config_flow.py` | 4-step setup wizard + options flow (incl. room_edit/person_edit, PID + wake settings) |
| `diagnostics.py` | async_get_config_entry_diagnostics() — fixed 2026-09: removed stale ctrl._days_above_high/_last_high_date references left over from the v0.5.0 controller refactor |
| `panel.py` | Static paths (process-level async_setup). Sidebar panel (async_setup_entry) |
| `websocket.py` | get_state, get_history, update_config, boost_start/stop, set_room_temp. boost_start/stop are thin wrappers around coordinator.async_boost_start()/async_boost_stop() — shared with the heat_manager.boost_start/stop services |
| `select.py` | controller_state + season_mode. Both assigned to global device |
| `sensor.py` | pause_remaining, energy_wasted/saved, efficiency_score, room state, window duration, per-room pid_power |
| `binary_sensor.py` | any_window_open, heating_wasted, cloud_available, per-room window, per-room mold_risk |
| `switch.py` | Per-room override switches. Assigned to room devices |
| `icons.json` | Entity icon overrides — Gold IQS |
| `services.yaml` | set_controller_state, pause, resume, force_room_on, boost_start, boost_stop |
| `strings.json` / `translations/{en,da}.json` | Config + options + entity + issues + exceptions |
| `quality_scale.yaml` | IQS rule tracking — all Gold rules done or exempt |

### Engine layer (8 engines + PID)

| File | Description |
|------|-------------|
| `engine/controller.py` | ON/PAUSE/OFF state machine. Auto-off driven solely by SeasonEngine.effective_season == DORMANT (outdoor-temp day-counter logic removed here in v0.5.0, now lives in SeasonEngine) |
| `engine/presence_engine.py` | Presence, grace periods, alarm, arrival/departure, restore-lock against concurrent Netatmo 429s |
| `engine/window_engine.py` | Window detection, weather-aware delay (rain/wind), per-room CO₂ context, multi-sensor-per-room close guard (B16) |
| `engine/season_engine.py` | AUTO → DORMANT/WAKING/ACTIVE via calendar + outdoor-temp day-counter + indoor wake threshold |
| `engine/waste_calculator.py` | heating_power_request × wattage, CO₂/rain-weighted waste attribution |
| `engine/preheat_engine.py` | travel_time listener, per-person lead time, TRV routing |
| `engine/pid_controller.py` | Discrete-time PI(D), power_to_setpoint(), anti-windup — HA-independent, fully unit-testable |
| `engine/valve_protection_engine.py` | Weekly valve exercise 02–03, controller OFF only, HomeKit preferred |

### Frontend

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | Surgical DOM patching, 4 tabs (Oversigt/Rum/Historik/Konfiguration), toast notifications, cloud-status chip, manual TRV control, boost countdown (v0.3.10, synced every refresh via `_patchControllerHero()`) |
| `frontend/heat-manager-card.js` | Tablet height-scaling (`--hm-scale-h`), 2-col room grid, boost delegates to `heat_manager/boost_start\|stop` WS (v0.4.3, unified with panel/service — no more separate client-side implementation) |
| `frontend/heat_manager_logo1.png` | 44 KB. Served at `/api/heat_manager-logo`. (The stray `heat_manager_logo2.png` on the HA server has been deleted by dev — resolved 2026-09-02.) |

### Tests (10 files)

| File | Coverage |
|------|----------|
| `test_config_flow.py` | Setup wizard + options flow, 16 tests |
| `test_coordinator_co2_threshold.py` | get_room_co2_threshold() — per-room override, fallback |
| `test_coordinator_night_setback.py` | is_night_setback_active(), night_setback_delta() — midnight-spanning windows |
| `test_pid_controller.py` | PI control, anti-windup, power_to_setpoint |
| `test_pid_tick.py` | Coordinator PID tick integration |
| `test_preheat_engine.py` | Travel time, lead time, TRV routing |
| `test_presence_engine.py` | Grace periods, alarm integration, force_room_on |
| `test_repair_issues.py` | _async_check_repair_issues(), _async_remove_stale_devices() |
| `test_season_engine.py` | AUTO→DORMANT/WAKING/ACTIVE, day-counter, reset |
| `test_waste_calculator.py` | Waste/savings accumulation, CO₂ weighting, midnight reset |

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
Note: preset_mode writes (away/schedule) always go to cloud entity.
Note: PID only writes to rooms that HAVE a homekit_climate_entity configured
— rooms without one are never proportionally regulated, only the binary
window-open fallback setpoint applies.
```

### Weather-aware window logic
```
is_raining()           → delay = 1 min, waste_weight = 1.00, label = 🌧️
wind ≥ WIND_FAST_MS    → delay = 1 min, label = 💨
co2 ≥ room_threshold   → waste_weight = 0.50, label = "ventilation"
otherwise              → configured delay, waste_weight = 1.00
```

### Boost (heat_manager/boost_start / boost_stop, WS)
```
boost_start → every NORMAL/OVERRIDE room set to DEFAULT_BOOST_TEMP (24°C,
              or optional "temperature" param) via preferred write entity.
boost_stop  → every room in coordinator.boost_active_rooms restored via
              presence_engine.force_room_on().
Note: heat-manager-card.js still has its OWN separate client-side boost
implementation with a local countdown timer — it does not call these WS
commands, so panel-boost and card-boost remain two independent code paths
that both now heat correctly but don't share live state. No auto-expiry
exists on the panel side (Phase B backlog item).
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

## IQS Quality Scale

See `quality_scale.yaml` for the authoritative, maintained list — all Bronze/Silver rules done,
all Gold rules done or exempt, Platinum `strict-typing` still todo. Not duplicated here anymore
to avoid this file drifting out of sync with the real tracker again (see "Known documentation
debt" below).

---

## Known documentation debt

This file previously (through v0.4.6) drifted significantly out of sync with the actual codebase
— it referenced files, class attributes and a bug-history table that no longer matched reality by
v0.6.x (e.g. `test_controller_engine.py`, `controller.py`'s `_outdoor_temp_history`). Per the
project's own common instructions (§8: "Brug ALDRIG project knowledge files som kode-reference"),
Claude always reads the live code rather than this file — but keep this file honest anyway for
human reference. Prefer `CHANGELOG.md` for a chronological, append-only history; this file is a
snapshot and should be refreshed whenever it's next opened for a real work session, not assumed
current.

---

## Recent fixes (2026-09-02)

| Area | File | Description |
|------|------|-------------|
| Diagnostics crash | `diagnostics.py` | Removed `ctrl._days_above_high` / `ctrl._last_high_date` — attributes no longer exist on `ControllerEngine` since the v0.5.0 refactor. Diagnostics download was crashing unconditionally. |
| Boost no-op | `websocket.py`, `const.py` | `boost_start`/`boost_stop` WS commands only toggled a flag and never touched a TRV — the panel's Boost button had no heating effect. Now performs the same real climate.set_temperature / force_room_on actions as the card's own boost. |
| PID/wake settings hidden | `config_flow.py`, `strings.json`, `translations/{en,da}.json` | PID gains and wake/WAKING settings are now editable from the setup wizard and options flow instead of only via `entry.options`. |
| `heat_manager_logo2.png` resolved | HA server `frontend/` folder | Dev deleted the stray untracked logo file from the server manually (Claude cannot delete/move files). Repo and server frontend folders should now match — confirm with `list_directory_with_sizes` next session. |
| Unnecessary reloads | `__init__.py`, `coordinator.py` | `_async_update_listener` reloaded the whole integration on every `entry.options` write, including 3 purely internal ones (midnight energy snapshot, season_mode select, panel config save). Now only reloads when `rooms`/`persons` actually change; everything else already applies live. Real stability fix — a reload while a window was open could silently drop WindowEngine's suppression. |
| Untracked async task | `engine/season_engine.py` | `_maybe_trigger_voice()` used raw `asyncio.ensure_future()` instead of `hass.async_create_task()`, inconsistent with the rest of the codebase. Fixed for clean shutdown/exception tracking. |
| No boost service | `__init__.py`, `services.yaml`, `const.py`, `coordinator.py` | Added `heat_manager.boost_start`/`boost_stop` HA services, sharing one implementation (`coordinator.async_boost_start`/`async_boost_stop`) with the WS commands — boost can now be triggered from automations. |
| Boost never expired | `coordinator.py` | Boost now sets `boost_expires_at` and auto-restores via a new coordinator tick step once the duration elapses (default 30 min). Previously only the card's client-side timer existed, and it stopped working the moment the dashboard closed. |

---

## Backlog

| Item | Priority |
|------|----------|
| `brands/icon.png` | Medium — required for HACS/official listing |
| `strict-typing` | Low — full mypy pass |
| Deploy 0.7.0 → HA server (currently 0.6.2) | High — pending manual deploy |
| Unify panel-boost and card-boost into one code path (card call the WS commands instead of duplicating logic) | ✅ Done — card now delegates to heat_manager/boost_start\|stop WS, same coordinator methods as panel and service |
| Boost auto-expiry/countdown on the backend (currently only the card has a local, frontend-only timer) | ✅ Done — coordinator now auto-restores after `duration_minutes` |
| Zigbee rooms unregulated by PID | ✅ Done — hybrid PID engine now regulates local/Zigbee rooms too via new `comfort_temp` field, plus outdoor feedforward ("heating curve") on both room types |
| Boost button never re-synced after backend-side stop (auto-expiry, service, another client) | ✅ Done — sync moved from one-time `_attachEvents()` into `_patchControllerHero()`, called every refresh; live countdown added |
| Manual TRV override auto-restore | Low — Phase B |
| Per-room always-on toggle | Low — bypass presence for bathrooms/offices |
| Daily heating summary notification | Low — feedback loop for user |
| EKF thermal model | Future — learned heat loss rate replaces fixed PID gains |
| Solar gain in SeasonEngine | Future |
