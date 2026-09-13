# Heat Manager — Project Status

**Last updated:** 2026-09-13 · v0.31.0
**Version (GitHub):** 0.31.0 (pending push/commit via GitHub Desktop)
**Version (HA server):** not yet transferred — see CHANGELOG.md before deploying
**Target:** Home Assistant 2025.1+
**Language:** English primary · Danish translations included
**Status:** Stable, actively developed. This file was badly out of date (last
refreshed at v0.16.0, 2026-09-07) while roughly 30 releases (v0.17.0–v0.31.0)
landed — see CHANGELOG.md for the authoritative, chronological detail on all
of them. Headline changes since the previous snapshot: Heat Manager is now
the sole authority for every room's target temperature, Netatmo included
(v0.19.0/v0.20.0, closing a real bug where Netatmo rooms silently ignored
`comfort_temp`); a coordinator-wide lock now paces every Netatmo-bound
`climate.*` call across all engines/rooms/tasks, fixing 429/503 errors
(v0.17.1); interior doors are a first-class feature with their own engine and
heat-up-rate learning (v0.24.0); rooms with no TRV at all ("monitoring-only",
e.g. a hallway) are fully supported (v0.24.1/v0.24.2); several restart-time
false-event bugs in the History tab were fixed (v0.23.0); the standalone
"Energi i dag" (waste/savings/efficiency) feature was removed entirely at the
user's request — district heating, not electric, has no meaningful kWh figure
to show (v0.22.0); and two large "Fase 2" frontend projects shipped: a live-
editable "Indstillinger" tab in the sidebar panel (v0.29.0) and a press-and-
hold diagnostics bottom-sheet on the mobile card (v0.30.0). Most recently,
mold risk — previously a passive, poll-only entity — now pushes a
notification the moment risk turns on (v0.31.0).

**Known deferred items (still open):** a full card.js/panel.js data-parity
pass (surfacing every config-only field, e.g. sync-mode/schedule, on the
mobile card the same way the panel shows them) remains deferred — the card's
architecture has no live websocket connection, so this would need either
adding one or duplicating more config into the card's own per-room setup
(see CHANGELOG [0.17.0]'s "Deliberately still not done"). "Interne dørs
niveau C" (letting an open interior door actively influence a *neighbouring*
room's target temperature, rather than only being visible/logged/learned) is
explicitly parked pending a design decision from the user about
room-target-temperature "ownership" — see
`manual/heat_manager_brugermanual_2026-09-11.md` kapitel 9.

---

## Repository overview

```
heat_manager/
├── .cursorrules                  14-section development ruleset (IQS Bronze–Platinum)
├── README.md                     Full English docs: install, config, services, entities
├── CHANGELOG.md                  Keep a Changelog format — authoritative, chronological history
├── GIT_WORKFLOW.md               GitHub Desktop guide for Windows
├── STATUS.md                     This file — a periodically-refreshed snapshot, not the source of truth
├── hacs.json                     HACS distribution metadata
├── custom_components/
│   └── heat_manager/
│       ├── engine/                13 engine files + PID controller
│       └── frontend/               panel.js (sidebar, PC/tablet) + card.js (mobile Lovelace card) + logo
└── tests/
    └── components/heat_manager/   pytest suite (Python/HA-core only — no JS test harness exists)
```

---

## File inventory

### Integration root

| File | Description |
|------|-------------|
| `__init__.py` | Setup, ConfigEntryNotReady, service registration, repair issues, stale device cleanup |
| `manifest.json` | v0.31.0, config_flow: true, iot_class: local_push |
| `const.py` | All constants. Notable recent additions: `CONF_DOORS`/`CONF_DOOR_SENSOR`/`CONF_DOOR_ROOM_A/B` (interior doors), `CONF_MANUAL_TRV_CONTROL`, `CONF_BOOST_DEFAULT_TEMP`/`CONF_BOOST_DEFAULT_MINUTES`, `CONF_NOTIFY_MOLD_RISK`. `CONF_ENERGY_TRACKING`/`CONF_ROOM_WATTAGE` were removed in v0.22.0 |
| `coordinator.py` | `DataUpdateCoordinator` — 13-step tick (season → controller → presence → window → preheat → valve-protection → calibration → schedule → PID → boost-expiry → room-override-expiry → **mold-risk check** ). Per-engine exception isolation, so one engine's exception never marks every entity unavailable. `get_room_target_temp()` is the single resolved-target helper both the PID tick and the panel/card read (v0.20.0) — Netatmo and Zigbee/local rooms are regulated identically. `async_call_climate_service()` is the one place any engine sends a `climate.*` service call, serialised behind a single coordinator-wide `asyncio.Lock` so Netatmo's rate limit is respected app-wide, not per-engine (v0.17.1). `_async_check_mold_risk()`/`_notify_mold_risk()` (v0.31.0) edge-detect a room's mold risk turning on and push a notification, mirroring `MoldRiskSensor`'s own algorithm |
| `config_flow.py` | Multi-step setup wizard + options flow (rooms/persons/doors CRUD, PID + wake settings, boost defaults, notifications incl. mold risk) |
| `diagnostics.py` | `async_get_config_entry_diagnostics()` — no longer includes an `energy` block (removed with the energy feature, v0.22.0) |
| `panel.py` | Static paths (process-level `async_setup`). Sidebar panel (`async_setup_entry`). Reads the running version from `manifest.json` off-thread (`hass.async_add_executor_job`) — no more separate `const.VERSION` copy to drift (v0.18.0/v0.18.1/v0.18.2) |
| `websocket.py` | `get_state`, `get_history`, `update_config`, `boost_start`/`boost_stop`, `set_room_temp`. `ws_update_config()` (v0.29.0) is table-driven — `_STRING_CONFIG_FIELDS`/`_BOOL_CONFIG_FIELD_DEFAULTS`/`_NUMERIC_CONFIG_FIELDS` — so a new panel-editable field is a one-line table addition, not a new branch; change-detection always compares against the field's real `DEFAULT_*` value, never a blanket `0`/`False`/`""`. No more energy fields in `get_state`/`get_history` (v0.22.0) |
| `select.py` | `controller_state`, `season_mode` (global), plus per-room `NetatmoPresetModeSelect` (`select.<room>_netatmo_preset_mode`, one per room with a Netatmo/cloud TRV — v0.20.0/v0.27.0) |
| `number.py` | `group_offset` — RestoreNumber, ±5 °C, global |
| `sensor.py` | `pause_remaining`, per-room state/window-duration/pid_power/calibration-offset sensors. The energy sensors (`energy_wasted`/`energy_saved`/`efficiency_score`) were removed in v0.22.0 |
| `binary_sensor.py` | `any_window_open`, `cloud_available`, per-room `window`, per-room `mold_risk` (now also drives a push notification via the coordinator — see above), raw window/door contact mirrors. `heating_wasted` was removed in v0.22.0 |
| `switch.py` | Per-room override switches + per-room group-enable switches. Assigned to room devices |
| `icons.json` | Entity icon overrides — Gold IQS |
| `services.yaml` | `set_controller_state`, `pause`, `resume`, `force_room_on`, `boost_start`, `boost_stop` |
| `strings.json` / `translations/{en,da}.json` | Config + options + entity + issues + exceptions. Notifications step now has 5 toggles (presence/windows/30-min-warning/preheat/mold-risk) |
| `quality_scale.yaml` | IQS rule tracking — all Gold rules done or exempt, Platinum `strict-typing` still todo |

### Engine layer (13 engines + PID)

| File | Description |
|------|-------------|
| `engine/controller.py` | ON/PAUSE/OFF state machine. Auto-off driven solely by `SeasonEngine.effective_season == DORMANT` |
| `engine/presence_engine.py` | Presence, grace periods, alarm, arrival/departure, restore-lock against concurrent Netatmo 429s. v0.23.0: known-old-state guards on alarm/person state changes so an HA restart no longer logs/notifies a false "away"/"welcome home" event; a silent `_check_initial_alarm()` still correctly syncs an already-armed-away house at startup |
| `engine/window_engine.py` | Window/door detection, weather-aware delay (rain/wind), per-room CO₂ context, multi-sensor-per-room close guard. v0.23.0: known-old-state guard + `_check_initial_windows()` for the same restart-false-event fix as presence_engine. v0.24.2: a monitoring-only room (no TRV) can now have a window/door sensor too — state/log/notify only, no `climate.set_temperature` |
| `engine/door_engine.py` | (v0.24.0, new) Purely observational — logs a real "Dør åbnet/lukket mellem X og Y" event whenever a configured interior door genuinely opens or closes. Restart-safe from day one (same known-old-state guard). Never touches heating directly |
| `engine/season_engine.py` | AUTO → DORMANT/WAKING/ACTIVE via calendar + outdoor-temp day-counter + indoor wake threshold |
| `engine/preheat_engine.py` | `travel_time` listener, per-person lead time, TRV routing |
| `engine/pid_controller.py` | Discrete-time PI(D), `power_to_setpoint()`, anti-windup — HA-independent, fully unit-testable |
| `engine/valve_protection_engine.py` | Weekly valve exercise 02–03, controller OFF only, routed through the shared Netatmo call lock (v0.17.1) |
| `engine/calibration_engine.py` | Writes `room_temp_sensor − TRV raw` delta to a room's `calibration_entity` + 30 min heartbeat. v0.24.0: also learns per-room heat-up rate (°C/hour), split by whether the room's interior door was open or closed while heating was called for (`get_room_heatup_rate()`) — informational only, in-memory, resets on restart; nothing acts on it yet |
| `engine/sync_engine.py` | Per-room `sync_mode` (disabled/mirror/lock) — reacts to manual/external changes on the write entity |
| `engine/schedule_engine.py` | Per-room `schedule_entity` (`schedule.*`/`calendar.*`) — active block/event `temperature` overrides the room's normal target |
| `engine/remote_button_engine.py` | Global physical remote (e.g. Aqara W100) — 3 configurable `event.*` entities act on every eligible room via `coordinator.async_set_room_override()` |
| `engine/waste_calculator.py` | **Disconnected from the coordinator since v0.22.0** (energy feature removed at the user's request — no meaningful kWh figure on district heating). File is still on disk (this tooling can't delete files on the live server) but is dead code, safe to delete manually |

### Frontend

| File | Notes |
|------|-------|
| `frontend/heat-manager-panel.js` | Surgical DOM patching, 4 tabs (Oversigt/Rum/Historik/Konfiguration). Konfiguration gained a full "Indstillinger" section in v0.29.0 (Fase 2 del 1): PID-regulator, Boost-standardværdier, Vindue, Nat-sætpunkt, Grace-perioder, Auto-off ved mildt vejr, plus 2 more Notifikationer toggles — all live-editable via a generic `save-field`/`toggle-field` handler pair, same save-and-confirm pattern as the older Alarmtavle/Notifikationer/Manuel TRV-kontrol fields (which itself became properly persistent in v0.27.1, no longer session-scoped). Oversigt gained a version chip, a house-wide Netatmo mode summary, 2 more quick-stat tiles (Passiv, Åbne døre — v0.25.0), and a global "Alle rum — Target Temp" control (v0.26.0). "Sætpunkt"/"Mål °C" were unified into one "Target Temp" label everywhere (v0.26.0). The Energi i dag box and Historik energy chart were removed (v0.22.0). Polls every 60s |
| `frontend/heat-manager-card.js` | Mobile Lovelace card. v0.30.0 (Fase 2 del 2): a 500ms press-and-hold on any room card opens a bottom-sheet with every diagnostic previously shown as an always-on chip (humidity/CO2/battery/PID power/calibration/window-duration, blocking-reason, ungrouped), plus door status + learned heat-up-rate, a manual temperature override, and a grouping toggle — all new to this card. The always-visible card view is now decluttered to name/state/temp/setpoint/valve/mold-risk/TRV-offline. `_loadTargetTemps()` (v0.21.1, extended v0.30.0) polls `heat_manager/get_state` every 60s so the card's setpoint/room-detail data can never diverge from the panel's, unlike the raw-entity reads used before. The Energi i dag section was removed (v0.22.0) |
| `frontend/heat_manager_logo1.png` | Served at `/api/heat_manager-logo` |

### Tests

`tests/components/heat_manager/` — Python/pytest against Home Assistant core
(there is no JS test harness in this repo for either frontend file; frontend
changes are verified via `node --check` plus manual template/DOM review — see
each frontend-touching CHANGELOG entry for what was actually checked).
Coverage/test-count figures here go stale fast; CHANGELOG.md's per-version
entries list exactly which test files were added or changed for that release
— prefer those over any specific number quoted in an older snapshot of this
file.

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

### Room target temperature (single source of truth since v0.20.0)
```
coordinator.get_room_target_temp(room_name)
  — layers schedule_override / room_offset / night-setback / wake-setback
    on top of the room's configured comfort_temp, for EVERY TRV type
    (Netatmo included since the v0.19.0 "B21" fix — previously Netatmo
    rooms silently chased the cloud schedule's own setpoint instead).
  — Read by both _async_pid_tick() and the panel/card, so neither can ever
    show a different "target" than what the PID is actually chasing.
```

### Write channel (set_temperature)
```
1. homekit_climate_entity  — local LAN, no rate limits, no 429 risk  ← preferred
2. climate_entity          — Netatmo cloud                            ← fallback
Every Netatmo-bound climate.* call (any engine, any room, any task) is
serialised behind coordinator.async_call_climate_service()'s single
asyncio.Lock (v0.17.1) — fixed a 429/503 storm caused by several rooms'
windows closing (or other engines writing) within the same instant with no
cross-engine pacing.
```

### Weather-aware window logic
```
is_raining()           → delay = 1 min, label = 🌧️
wind ≥ WIND_FAST_MS    → delay = 1 min, label = 💨
co2 ≥ room_threshold   → label = "ventilation"
otherwise              → configured delay
A monitoring-only room (no TRV) can still have a window/door sensor — state/
log/notification only, no climate.set_temperature (v0.24.2).
```

### Interior doors (v0.24.0)
```
CONF_DOORS: [{sensor, room_a, room_b}, ...]  — managed via options flow CRUD
engine/door_engine.py   — logs open/close events only, restart-safe, no
                           control-flow effect of its own
calibration_engine.py   — learns heat-up-rate (°C/hour) per room, split by
                           door open/closed — informational only for now;
                           see "Interne dørs niveau C" under Known deferred
                           items above for what a future active-control pass
                           would need to decide first
```

### Boost (heat_manager/boost_start / boost_stop, WS + service)
```
boost_start → every NORMAL/OVERRIDE room set to the configured
              CONF_BOOST_DEFAULT_TEMP (falls back to DEFAULT_BOOST_TEMP,
              24°C, if unset — v0.28.0), or an explicit caller-supplied
              "temperature" param, via preferred write entity.
boost_stop  → every room in coordinator.boost_active_rooms restored via
              presence_engine.force_room_on().
Panel, card and the heat_manager.boost_start/stop service all delegate to
the same coordinator methods — one implementation, three callers.
Duration likewise falls back to CONF_BOOST_DEFAULT_MINUTES/DEFAULT_BOOST_MINUTES.
boost_expires_at is authoritative; the coordinator auto-restores once
duration elapses (checked every tick) — the frontend timer is cosmetic only.
```

### CO₂ threshold
```
Per-room CONF_CO2_THRESHOLD overrides global DEFAULT_CO2_VENTILATION_THRESHOLD (900 ppm).
Used by WindowEngine's notification context labels.
```

### Night setback
```
CONF_NIGHT_SETBACK_ENABLED  — boolean, default False
CONF_NIGHT_SETBACK_TEMP     — °C subtracted from PID target, default 2.0°C
Uses CONF_NIGHT_START_HOUR / CONF_NIGHT_END_HOUR (default 23/7).
Setpoint floor: room away_temp_override. Applied before PID tick.
Live-editable from the panel's Konfiguration tab since v0.29.0.
```

### Mold risk (now also a push notification — v0.31.0)
```
CONF_HUMIDITY_SENSOR   sensor.*  — indoor RH % (required)
CONF_ROOM_TEMP_SENSOR  sensor.*  — preferred temp source (falls back to the
                                    room's current_temperature like the PID
                                    feedback hierarchy above)
  RH ≥ 70% AND T_room ≤ T_dewpoint + 1°C → risk on
  Magnus formula (Lawrence 2005), DIN 4108-2 simplified
MoldRiskSensor (binary_sensor.py) exposes this per room as a poll-only
entity, as before. coordinator._async_check_mold_risk() (new, v0.31.0)
duplicates the same algorithm and edge-detects the False → True transition
per room every tick, firing CONF_NOTIFY_SERVICE exactly once per episode
(re-armed only once risk drops back to False) — the same edge-triggered
notification pattern WindowEngine already uses for open/close. Gated by
CONF_NOTIFY_MOLD_RISK (default True), live-editable from the panel's
Notifikationer section.
```

### Energy tracking — removed (v0.22.0)
```
The user's radiators run on district heating (fjernvarme), not electricity
— there is no way to meter water/heat flow, so the previous kWh figures
were never physically meaningful. engine/waste_calculator.py is fully
disconnected; every entity/UI/payload field it fed was removed. The file
itself is still on disk (left for the user to delete manually) but is dead
code — see CHANGELOG [0.22.0] for the full removal list if resurrecting any
part of this is ever reconsidered.
```

---

## Device registry

| Device | Identifier | Entities |
|--------|-----------|---------|
| Heat Manager (global) | `(DOMAIN, entry_id)` | controller_state, season_mode, any_window_open, cloud_available, pause_remaining |
| `<room_name>` (per room) | `(DOMAIN, entry_id_safe_room)` | room_state, window sensor, mold_risk, override switch, group-enable switch, pid_power, window_duration, calibration_offset, netatmo_preset_mode (Netatmo/cloud rooms) |

Per-room devices link to global via `via_device`. Stale devices removed on every reload.

---

## IQS Quality Scale

See `quality_scale.yaml` for the authoritative, maintained list — all Bronze/Silver rules done,
all Gold rules done or exempt, Platinum `strict-typing` still todo.

---

## Known documentation debt

This file previously (through v0.4.6, and again through v0.16.0) drifted
significantly out of sync with the actual codebase. Per the project's own
common instructions (§8: "Brug ALDRIG project knowledge files som
kode-reference"), Claude always reads the live code rather than this file —
but keep this file honest anyway for human reference. **Prefer
`CHANGELOG.md`** for a chronological, append-only, per-release history; this
file is a periodically-refreshed snapshot and should be treated as
potentially stale, not assumed current, the next time it matters.

---

## Backlog

| Item | Priority | Status |
|------|----------|--------|
| `brands/icon.png` | Medium — required for HACS/official listing | Open |
| Boost's default temp/duration hardcoded | — | ✅ Done (v0.28.0) — now configurable, falls back to the old hardcoded constants only when unset |
| Panel "Indstillinger" tab (PID/boost/window/night-setback/grace/auto-off/notify fields moved from options-flow-only to live panel editing) | — | ✅ Done (v0.29.0) |
| Mobile card press-and-hold diagnostics sheet | — | ✅ Done (v0.30.0) |
| Mold risk as a push notification (previously poll-only) | — | ✅ Done (v0.31.0) |
| Manual TRV control persistence (was session-scoped only) | — | ✅ Done (v0.27.1) |
| Netatmo rooms ignoring `comfort_temp` ("B21") | — | ✅ Done (v0.19.0/v0.20.0) |
| Netatmo 429/503 rate-limit races across engines | — | ✅ Done (v0.17.1) — single coordinator-wide lock |
| False restart-time events in Historik (window/presence/alarm) | — | ✅ Done (v0.23.0) |
| Interior doors (visibility + heat-up-rate learning) | — | ✅ Done (v0.24.0) |
| Rooms with no TRV ("monitoring-only") | — | ✅ Done (v0.24.1/v0.24.2) |
| Energy tracking (waste/saved/efficiency) — not meaningful on district heating | — | ✅ Removed (v0.22.0), at the user's request |
| "Interne dørs niveau C" — an open door actively adjusting a *neighbouring* room's target temp | Medium | Parked — needs a user decision on room-target-temperature "ownership" first |
| Full card.js/panel.js data parity (sync-mode/schedule/TRV-count etc. on the mobile card) | Low | Open — needs either a card-side websocket connection or more duplicated per-room card config |
| `strict-typing` | Low | Open — full mypy pass |
| Per-room always-on toggle (bypass presence for bathrooms/offices) | Low | Open |
| EKF thermal model | Future | Open — learned heat loss rate replaces fixed PID gains (the v0.24.0 heat-up-rate learning is informational groundwork toward this) |
| Solar gain in SeasonEngine | Future | Open |
