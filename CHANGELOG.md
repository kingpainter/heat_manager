# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed
- **trans(en)** `translations/en.json` — resynced to match `strings.json`
  (the canonical English source). It had drifted since ~0.4.x and was
  missing `house_voice_enabled`, `night_setback_*`, `pause_duration_min`,
  `co2_threshold`, `effective_season`, the `cloud_available` binary sensor,
  the entire `issues` block, and now the new `room_edit`/`person_edit`
  options-flow steps. This was one of five files flagged as out-of-sync in
  an earlier session (`presence_engine.py`, `select.py`, `strings.json`,
  `translations/en.json`, `translations/da.json`) — all five are now
  confirmed byte-identical between the GitHub repo and the HA server.
- **B16** `engine/window_engine.py` — rooms with more than one window/door
  sensor could have heating restored while a second sensor in the same room
  was still open. `_close_after_delay()` only checked the state of the
  specific sensor that triggered the close event, not the other sensors
  configured for that room. Added `_all_room_sensors_closed()` and require
  every sensor in the room to report closed before heating is restored.
  Relevant now that Lukas' and Sebastian's rooms each have two window
  sensors.

### Added
- **Options flow** — rooms and persons can now be edited in place via
  `Manage rooms` / `Manage persons`, not just added or deleted. New
  `room_edit` / `person_edit` steps pre-fill the existing values (e.g. window
  sensors, climate entity) so a single field — such as swapping in a newly
  mounted window sensor — can be changed without recreating the whole room.
  Room/person name and entity validation still applies, checked against all
  *other* rooms/persons so the entry being edited doesn't collide with
  itself.
- **Panel v0.3.5** — Scroll-position preserved on auto-refresh. `_load()` calls
  `_patchAll()` instead of `_scheduleRender()` when panel is already rendered.
  Surgical patch methods: `_patchRooms()`, `_patchPersons()`, `_patchAutoOff()`,
  `_patchQuickStats()`, `_patchTopbarVersion()`, `_patchCloudBanner()`. Room
  cards carry `data-room-id`; QS cells carry `data-qs-*`; persons/autooff
  sections carry wrapper IDs.
- **Panel v0.3.6** — UX polish batch: (A) controller ring patches surgically
  on state change via new `_patchControllerHero()`; (B) pause countdown ticks
  locally every 60 s without WS poll; (C) room cards show valve position badge
  (`🔥 42%` / `❄ 0%`) and boost badge when `boost_active` is set; (D) boost
  button added to controller row — calls `heat_manager/boost_start|stop` WS;
  (E) refresh button shows spinner during load; (F) rooms tab differentiated
  with per-room valve bar, boost badge, and `X/Y varmer` count; (G) history
  tab shows last-fetched timestamp + manual refresh button; (H) history loading
  skeleton shown while WS call is in-flight.
- **Panel v0.3.7** — Bug fixes: (UX1) controller ring transition fixed —
  `style.strokeDashoffset` instead of `setAttribute` triggers CSS transition;
  (UX2) rooms tab patches surgically via `_patchRoomsTab()` on each refresh;
  (UX3) refresh button shows `↻ HH:MM` after successful fetch; (UX4) boost
  button `active` class set from backend data on render.
- **B1** `websocket.py` — `valve_position` added to room payload. Zigbee
  `pi_demand_entity` takes priority over Netatmo `heating_power_request`.
- **B2** `websocket.py` / `coordinator.py` — `boost_active` per room added to
  WS payload, read from `coordinator.boost_active_rooms`.
- **B3/B7** `coordinator.py` / `websocket.py` — Energy history persisted to
  `entry.options` as JSON at midnight and on shutdown. Historical bars in the
  history chart now show real data instead of always zero.
- **B4** `engine/season_engine.py` — `coordinator.effective_season` is now
  always a proper `EffectiveSeason` enum (DORMANT/WAKING/ACTIVE). Previously
  `SeasonMode` values were assigned, causing a type mismatch.
- **B5** `const.py` / `engine/controller.py` — `CONF_PAUSE_DURATION_MIN`
  constant added. Controller now reads it via the constant instead of a bare
  string literal that was always falling back to default.
- **B6** `coordinator.py` — PID setback log format-string fixed: `−0.1f` was
  invalid Python; corrected to `%.1f`.
- **B8** `websocket.py` — `heat_manager/boost_start` and `boost_stop` WS
  endpoints implemented. Set/clear `coordinator.boost_active_rooms` and log
  event. Frontend boost button wired to these endpoints.
- **B9** `engine/season_engine.py` — WAKING phase now fully functional.
  `_apply_waking_check()` reads `CONF_INDOOR_WAKE_SENSOR` and returns
  `EffectiveSeason.WAKING` when indoor temp ≥ `CONF_INDOOR_WAKE_THRESHOLD`.
  Previously WAKING was defined but never activated.
- **B10** `coordinator.py` — Event log persisted to `entry.options` (last 50
  entries as JSON) at midnight and on shutdown. Restored on startup.
- **Config flow** — `pause_duration_min` field added to global step
  (15–480 min, step 15).
- **Coordinator shutdown** — `_persist_energy_snapshot()` called in
  `async_shutdown()` so today's energy data survives HA restarts.
- **Tests** — `test_season_engine.py` updated for `EffectiveSeason` (B4/B9):
  all assertions use `EffectiveSeason.ACTIVE/DORMANT/WAKING`; four new tests
  cover WAKING activation, ACTIVE fallback, no-sensor fallback, and DORMANT
  immunity to WAKING downgrade.
- **Panel v0.3.9** — UI/UX pass:
  - Oversigt: new "Energi i dag" card (sparet/spildt kWh + efficiency-score
    ring), using `energy_saved_today`/`energy_wasted_today`/`efficiency_score`
    (already in the `get_state` payload — no backend changes needed).
  - Controller hero gains a third meta-chip showing the *effective* season
    (Dvale 😴 / Opvågning 🌅 / Aktiv 🔥). Also fixes a pre-existing bug where the
    "Effektiv sæson" field on the auto-off card always showed "–" (it was
    looked up in the calendar-season label map instead of the
    DORMANT/WAKING/ACTIVE map).
  - Rum tab: TRV-type badge (Netatmo/Zigbee) per room detail row.
  - Historik tab: weekly energy chart (previously only on Rum tab) moved
    above the event log, plus filter chips to show only one event type
    (alle/normal/fravær/vindue/boost/manuel/override).
  - Toast notifications for action failures (boost, manual TRV set/reset,
    config save) — previously these only logged to `console.error` and the
    user saw nothing.
  - a11y: cloud-status dismiss button gets `aria-label`; tab buttons get
    `role="tab"`/`aria-selected`.
- **B15** `websocket.py` — `get_state` room payload now includes `trv_type`
  (netatmo/zigbee), used by the new panel TRV badge.

### Fixed
- `manifest.json` version was stuck at `0.4.6`; synced to `0.5.0`.
- **B11** `engine/presence_engine.py` — Initial presence is now checked at
  startup via `_check_initial_presence()`. Previously
  `async_track_state_change_event` only reacted to future changes, so
  heating could remain on full schedule with nobody home, or stay stuck in
  away mode with someone home, until the next person state change.
  `_restore_all_schedule()` gained a `force` parameter to bypass the
  NORMAL-state idempotency skip for this initial sync.
- **B12** `coordinator.py` — `_refresh_outdoor_temperature()` now falls back
  through `temperature`, `current_temperature` and `temp` weather attribute
  keys in order, since not all weather integrations expose `temperature`.
- **B13** `coordinator.py` — `async_shutdown()` now stores a
  `<date>_partial` snapshot of the in-progress day's energy totals, so data
  accrued since the last midnight tick survives an unexpected restart.
  `_load_energy_history()` strips `_partial` keys on load to avoid stale
  accumulation.
- **B14** `__init__.py` — `async_setup_entry()` now logs a `WARNING` per room
  with a missing climate entity at startup, even when setup fails entirely
  with `ConfigEntryNotReady` (previously only logged once setup succeeded
  far enough to reach `_async_check_repair_issues`).

---

## [0.5.0] — 2026-05-23

### Added
- **Three-tier `EffectiveSeason` system** — `SeasonEngine` now resolves `AUTO`
  to one of three phases: `DORMANT` (summer sleep), `WAKING` (transitional),
  or `ACTIVE` (full winter operation). Previously only `WINTER`/`SUMMER` (on/off)
  were used.
- **`WAKING` phase** — during spring/autumn, when outdoor temperature is still
  below the auto-off threshold but the house is already warm (indoor temp
  above `CONF_INDOOR_WAKE_THRESHOLD`, default 21 °C), the system enters WAKING:
  heating is on, but PID setpoints are reduced by `CONF_WAKE_SETBACK_TEMP`
  (default 2 °C) to avoid over-heating a warm house.
- **Indoor wake sensor** (`CONF_INDOOR_WAKE_SENSOR`) — optional global sensor
  used to distinguish WAKING vs ACTIVE. Falls back to ACTIVE when absent
  (fail-safe: never under-heat).
- **`wake_setback_delta()`** helper on coordinator — returns the reduction
  in °C during WAKING, 0.0 otherwise. Applied cumulatively with
  `night_setback_delta()` in the PID tick.
- `const.py` — `EffectiveSeason` enum, `CONF_INDOOR_WAKE_SENSOR`,
  `CONF_INDOOR_WAKE_THRESHOLD` (default 21.0 °C), `CONF_WAKE_SETBACK_TEMP`
  (default 2.0 °C).
- `strings.json` / `translations/da.json` — `effective_season` select entity
  states: `dormant` / `waking` / `active` (DA: Dvale / Vågner / Aktiv).

### Changed
- **`SeasonEngine`** is now the single source of truth for `EffectiveSeason`.
  Manual season overrides (WINTER/SPRING/AUTUMN → ACTIVE, SUMMER → DORMANT)
  are mapped here rather than in coordinator.
- **`ControllerEngine`** simplified — removed the duplicate outdoor-temperature
  day-counter (`_days_above_high`, `_outdoor_temp_sustained_high()`). Auto-off
  and auto-resume now react solely to `coordinator.effective_season`.
- **PID tick** — now active in both ACTIVE and WAKING phases (previously
  only ACTIVE). DORMANT still resets all PIDs.
- `coordinator.py` — `effective_season` type changed from `SeasonMode` to
  `EffectiveSeason`; initial value `ACTIVE` (was `WINTER`).
- Version bumped `0.4.6` → `0.5.0`.

---

## [0.4.6] — 2026-05-22

### Added
- **Repair issues** — `_async_check_repair_issues()` runs after every setup.
  For each room whose `climate_entity` is not found in HA, a `RepairIssue`
  (severity WARNING, `is_fixable=False`) is raised in the HA Repairs panel.
  The issue title and description include the room name and entity ID.
  Issues are cleared automatically on the next reload when the entity
  reappears, and on unload. IQS Gold `repair-issues` now `done`.
- **Stale device cleanup** — `_async_remove_stale_devices()` runs after every
  setup. Compares device registry entries for this config entry against the
  current room list and removes any per-room devices whose room no longer
  exists in config (e.g. after a room is deleted via options flow).
  IQS Gold `stale-devices` now `done`.
- `const.py` — `REPAIR_ISSUE_MISSING_CLIMATE = "missing_climate_entity"`.
- `strings.json` + `translations/da.json` — `issues.missing_climate_entity`
  title and description with `{room_name}` and `{climate_id}` placeholders.

### Changed
- `__init__.py` — added `homeassistant.components.repairs` import and
  `homeassistant.helpers.device_registry` import. `async_unload_entry` now
  deletes all repair issues on unload.
- `quality_scale.yaml` — `repair-issues` and `stale-devices` marked `done`.
  All Gold IQS rules are now either `done` or `exempt`.

---

## [0.4.5] — 2026-05-22

### Added
- **Device registry** — all entities are now assigned to HA devices (IQS Gold
  `devices` + `dynamic-devices` rules now `done`).
  Two device tiers:
  - **Global device** `Heat Manager` — holds all integration-level entities
    (controller state, season mode, energy sensors, any_window_open,
    heating_wasted, cloud_available).
  - **Per-room devices** (one per configured room) — hold all room-level
    entities (room state, window sensor, mold risk, override switch, PID
    power). Each room device links to the global device via `via_device`.
- `coordinator.py` — `global_device_info()` and `room_device_info(room_name)`
  helpers returning `DeviceInfo`. All platform `__init__` methods set
  `self._attr_device_info` from these helpers.
- `DeviceInfo` import added to `coordinator.py`.

### Changed
- `sensor.py`, `binary_sensor.py`, `select.py`, `switch.py` — all entity
  `__init__` methods set `self._attr_device_info` (one line each).
- `quality_scale.yaml` — `devices` and `dynamic-devices` marked `done`.

---

## [0.4.4] — 2026-05-22

### Added
- **Per-room CO₂ threshold** (`co2_threshold`) — new optional per-room field
  (500–2000 ppm, step 50, default 900 ppm). When set, overrides the global
  `DEFAULT_CO2_VENTILATION_THRESHOLD` for that room in both window notifications
  and waste attribution. Useful when rooms have different ventilation needs
  (e.g. bedrooms tolerate higher CO₂, seldom-used rooms should have a lower
  threshold so any open window is treated as heat loss).
- `coordinator.py` — `get_room_co2_threshold(room_name)` helper. Returns
  per-room override when configured, falls back to global default.
- `engine/window_engine.py` — `_co2_context_label()` signature extended with
  optional `room_name` parameter; all three call sites updated to pass
  `room_name` so per-room threshold is used in window open/close/warning
  notifications.
- `engine/waste_calculator.py` — `_co2_waste_weight()` uses
  `get_room_co2_threshold()` instead of the global constant.
- `const.py` — `CONF_CO2_THRESHOLD` constant added.
- `config_flow.py` — `co2_threshold` number selector added to `_room_schema`
  (appears in setup wizard and options room-add step).
- `strings.json` + `translations/da.json` — labels and descriptions in config
  and options room steps.

### Changed
- `engine/waste_calculator.py` — removed unused
  `DEFAULT_CO2_VENTILATION_THRESHOLD` import (now only read via coordinator
  helper).

---

## [0.4.3] — 2026-05-22

### Added
- **Night setback** — new global option that reduces the PID target temperature
  by a configurable number of degrees during the configured night hours
  (`night_start_hour` – `night_end_hour`, already used by grace periods).
  Three new config fields: `night_setback_enabled` (boolean, default off),
  `night_setback_temp` (0.5–5.0°C, default 2.0°C), plus the existing
  `night_start_hour` / `night_end_hour` are now also shown in the global
  config/options step so users can adjust the window in the UI.
  The setback is applied before the PID tick; the adjusted setpoint will never
  go below the room’s `away_temp_override`. Disabled by default — existing
  installations are unaffected until the option is enabled.
- `coordinator.py` — `is_night_setback_active()` and `night_setback_delta()`
  helpers. `is_night_setback_active()` correctly handles windows that span
  midnight (e.g. 23:00–07:00).
- `const.py` — `CONF_NIGHT_SETBACK_ENABLED`, `CONF_NIGHT_SETBACK_TEMP`,
  `DEFAULT_NIGHT_SETBACK_ENABLED`, `DEFAULT_NIGHT_SETBACK_TEMP`.
- `strings.json` + `translations/da.json` — labels and descriptions for all
  four new/exposed fields in both config and options global step.

---

## [0.4.2] — 2026-05-22

### Changed
- `websocket.py` — `_get_entry()` now uses `entry.runtime_data` exclusively.
  Removed `hass.data[DOMAIN]["entry_id"]` lookup. `entry.runtime_data` is the
  single source of truth per IQS pattern; the `hass.data` workaround (S-8)
  is no longer needed.
- `__init__.py` — removed `hass.data.setdefault(DOMAIN, {})["entry_id"]` write.
  `entry.runtime_data = coordinator` is now the only place coordinator is stored.

---

## [0.4.1] — 2026-05-22

### Changed
- `coordinator.py` — `_async_update_data()` rewritten with per-engine isolation.
  Each of the 8 engine ticks (season, controller, presence, window, waste,
  preheat, valve_protection, pid) is now wrapped in its own `try/except`.
  An exception in one engine is logged as `WARNING` and skipped; the remaining
  engines continue normally. Previously, any single engine failure raised
  `UpdateFailed` and marked all Heat Manager entities `unavailable` until the
  next successful tick.

---

## [0.3.9] — 2026-05-03

### Added
- **`heat_manager/update_config` WebSocket command** — New WS endpoint that
  persists `alarm_panel` and `notify_service` to `entry.options` without an
  HA restart. Changes take effect immediately because the coordinator reads
  config dynamically. Logs the change to the event log.
- **Config tab inline editing** — Alarm panel and notify service now have
  inline text inputs with a Gem-button in the Konfiguration tab instead of
  read-only display. Shows a brief ✔ Gemt confirmation on success. Each
  section includes a Danish explanation of what the field does.

---

## [0.3.8] — 2026-05-03

### Fixed
- **BUG** `diagnostics.py` — `ctrl._outdoor_temp_history` reference crashed
  diagnostics download after S-1 fix replaced the list with a counter.
  Replaced with `days_above_high` + `last_high_date`.
- **BUG** `switch.py` — `RoomOverrideSwitch.async_turn_on()` always called
  `set_preset_mode` on the cloud entity, ignoring TRV type and HomeKit.
  Now uses `get_write_entity()` + TRV-type routing consistent with all other
  engines.
- **BUG** `select.py` — `SeasonModeSelect` wrote `season_mode` in-memory only;
  HA restart silently reset it to AUTO. Now persists to `entry.options` via
  `async_update_entry()`. `coordinator.__init__` restores the saved value.
- **BUG** `websocket.py` — `ws_get_state` rooms payload read `current_temperature`
  directly from cloud entity instead of using `get_room_current_temp()`. Rooms
  with `room_temp_sensor` or HomeKit entity were showing TRV radiator-body
  temperature in the panel. Now uses the coordinator helper consistently.
  Also adds `heating_power` (0–100 %) per room to the payload.

### Added
- **Netatmo weather integration** — Three new optional global sensor fields
  in config flow Step 1:
  - `outdoor_humidity_sensor` — outdoor relative humidity (%).
  - `precipitation_sensor` — precipitation (mm or mm/h).
  - `wind_speed_sensor` — wind speed (m/s).
  Four coordinator helpers: `get_outdoor_humidity()`, `get_precipitation()`,
  `get_wind_speed()`, `is_raining()`.
- **Adaptive window delay** — `window_engine._get_open_delay()` now reduces
  delay to `DEFAULT_WINDOW_DELAY_WIND_MIN` (1 min) when wind ≥ `WIND_FAST_MS`
  (6.0 m/s) or precipitation > 0. Fast wind and rain mean rapid heat loss —
  no reason to wait 5 min to confirm the window is open.
- **Weather-aware window notifications** — `_co2_context_label()` now
  prepends rain (🌧️) or wind (💨) context before CO₂ when applicable.
  Rain overrides CO₂ weighting entirely — nobody ventilates in rain.
- **Rain overrides CO₂ waste weighting** — `waste_calculator._co2_waste_weight()`
  returns 1.0 (full waste) when it is raining, regardless of CO₂ level.
- **`binary_sensor.heat_manager_cloud_available`** — New sensor (device class
  `connectivity`, enabled by default). `True` = cloud OK; `False` = all cloud
  climate entities unavailable or all have stale `last_updated` (≥ 10 min).
  Skips HomeKit entities. Exposes `unavailable_rooms` and `stale_rooms`
  attributes. Can drive HA automations (e.g. send notification on cloud loss).
- **`sensor.<room>_pid_power`** — New per-room DIAGNOSTIC sensor (disabled by
  default). Exposes PID output 0–100 % for rooms with a HomeKit entity.
  Attributes include `pid_kp`, `pid_ki`, `pid_kd`, `integral`. Allows tuning
  PID gains without enabling debug logging.
- **Mold risk outdoor context** — `MoldRiskSensor.extra_state_attributes` now
  includes `outdoor_humidity_pct` from `outdoor_humidity_sensor` when
  configured, giving full context for mold risk assessment.

---

## [0.3.7] — 2026-05-03

### Added
- **H-4** `coordinator.py` — `get_write_entity(room_name)` helper. Returns the
  HomeKit climate entity if configured and available, otherwise falls back to
  the cloud entity. Single authoritative place for "prefer local" routing.
- **H-4** `coordinator.py` — `needs_cloud_delay(room_name)` helper. Returns
  `True` when the write entity resolves to the cloud entity, allowing callers
  to skip `NETATMO_API_CALL_DELAY_SEC` for HomeKit rooms.

### Changed
- **H-1** `engine/window_engine.py` — `_open_after_delay()` now writes the
  frost-guard setpoint via `get_write_entity()` (HomeKit preferred). Window
  suppression no longer touches the Netatmo cloud when HomeKit is available.
  Log message includes `(via HomeKit)` or `(via cloud)` for diagnostics.
- **H-5** `engine/controller.py` — `_apply_off_fallback()` for SUMMER season
  (hvac_mode: off) now uses `get_write_entity()` for a local write. WINTER
  restore (preset_mode: schedule) still uses the cloud entity because
  preset_mode is not exposed via HomeKit HAP.
- **H-6** `engine/controller.py` + `engine/presence_engine.py` — `asyncio.sleep`
  delay between rooms is now conditional on `needs_cloud_delay()`. Rooms with
  an active HomeKit entity skip the 600 ms stagger entirely — reducing the
  total time for a 4-room sweep from 2.4 s to as little as 0 s when all rooms
  have HomeKit configured.
- `engine/presence_engine.py` — imports `NETATMO_API_CALL_DELAY_SEC` from
  const instead of hardcoding `0.6`.
- `coordinator.py` `_async_pid_tick()` — internal `hk_id`/`write_id` variables
  aligned with the new helper pattern for clarity. PID behaviour unchanged:
  still only writes to HomeKit, never to cloud.

---

## [0.3.6] — 2026-05-03

### Fixed
- **S-6** `sensor.py` — `RoomWindowDurationSensor` used `now.day` (1–31) as
  reset key, causing false midnight-resets on the same day-of-month in a
  different month. Changed to `now.date()`.
- **S-7** `websocket.py` — `_fmt_time()` contained hardcoded Danish string
  `"i går "`. Replaced with neutral `"%d/%m %H:%M"` format; panel JS handles
  locale-specific labels.
- **S-8** `websocket.py` + `__init__.py` — `_get_entry()` iterated all config
  entries and returned the first with `runtime_data`, which is wrong if two
  entries exist. Entry ID is now stored in `hass.data[DOMAIN]["entry_id"]` at
  setup; `_get_entry()` looks it up directly and only falls back to iteration.

### Changed
- **I-1** `sensor.py` — `EnergyWastedSensor` and `EnergySavedSensor` changed
  from `TOTAL_INCREASING` to `MEASUREMENT` state class. Both sensors reset at
  midnight; `TOTAL_INCREASING` caused HA Long-Term Statistics to log "dips"
  and raise warnings on every reset.
- **I-2** `coordinator.py` — Added `calendar_season` and `days_above_threshold`
  properties that proxy `season_engine` internals. `websocket.py` and
  `select.py` now use these instead of accessing `coordinator.season_engine.*`
  directly, reducing cross-layer coupling.

---

## [0.3.5] — 2026-05-03

### Added
- **F4** `engine/valve_protection_engine.py` — New `ValveProtectionEngine`.
  Exercises every TRV valve once per ISO calendar week during a 02:00–03:00
  night window, but only when the controller is `OFF` (summer / manual off).
  Sends `set_temperature` to 28 °C (fully open), holds 30 s, then restores the
  original setpoint. Prefers HomeKit entity (local, <100 ms) over cloud entity.
  Staggered with `NETATMO_API_CALL_DELAY_SEC` for Netatmo rooms. Registered in
  coordinator tick and shutdown.
- **F6** `binary_sensor.py` — New `MoldRiskSensor` per room. Active when
  relative humidity ≥ 70 % and room temperature ≤ dewpoint + 1 °C surface
  margin (DIN 4108-2 simplified). Dewpoint calculated via Magnus formula
  (Lawrence 2005). Requires `CONF_HUMIDITY_SENSOR` to be set for a room.
  Exposes `humidity_pct`, `room_temp_c`, `dewpoint_c`, `margin_c` as
  extra state attributes. Device class `moisture`.
- **F5** `config_flow.py` — Per-person `preheat_lead_time_min` was already
  stored and read per-person by `PreheatEngine._lead_time_seconds()`; config
  flow selector max raised from 60 → 90 min to accommodate longer commutes.
- `const.py` — Added `CONF_HUMIDITY_SENSOR` constant with docstring.

### Changed
- `config_flow.py` — Room schema gains `humidity_sensor` text field (sensor.*
  — relative humidity in %). Appears in both setup wizard and options flow
  room-add step.
- `coordinator.py` — `ValveProtectionEngine` instantiated, ticked, and shut
  down alongside existing engines.

---

## [0.3.4] — 2026-05-03

### Added
- `frontend/heat-manager-panel.js` — Cloud status banner. Detects Netatmo
  cloud outages by inspecting HA climate entity `state` (unavailable/unknown)
  and `last_updated` staleness (≥ 10 min). Two modes: "Netatmo cloud
  utilgængelig" (all entities unavailable) and "Netatmo data forsinket" (stale
  data). Includes ✕ dismiss button (session-scoped). No external HTTP calls —
  uses only HA state machine data already available in the panel.
  Links to `health.netatmo.com` when all entities are unavailable.

---

## [0.3.3] — 2026-04-21

### Changed
- `panel.py` — registers `heat_manager_logo1.png` as static HTTP path at
  `/api/heat_manager-logo` with `cache_headers=True`.
- `frontend/heat-manager-panel.js` — `.header-icon` CSS rewritten to use
  `url("/api/heat_manager-logo")` instead of inline base64 JPEG. Fixes shadow
  DOM rendering in Chrome/Safari.

### Removed
- `frontend/heat-manager-panel.js` — "Energi i dag" overview section removed.
  WasteCalculator engine and energy sensors are unchanged; weekly bar chart on
  Rooms tab still works.

### Added
- `frontend/heat_manager_logo1.png` — 44 KB radiator logo.

---

## [0.3.2] — 2026-03-29

### Fixed
- **B-429-RESTORE-RACE** `presence_engine.py` — `_restore_all_schedule()`
  lacked re-entrancy guard; concurrent callers produced N×rooms Netatmo API
  calls and reliable HTTP 429 errors. Fixed with `_restore_lock`.
- **B-LOG-RESTORE-SPAM** `presence_engine.py` — Per-room NORMAL idempotency
  check prevents repeated WARNING logs from concurrent restore callers.
- Stale version strings in `manifest.json` and `const.py` corrected.

---

## [0.3.1] — 2026-03-28

### Fixed
- **B-CARD-IAH** `heat-manager-card.js` — Invalid `?.replaceWith?.()` syntax
  and `insertAdjacentHTML` on ShadowRoot in card picker dialog.

---

## [0.3.0] — 2026-03-28

### Changed
- Complete visual redesign of panel and card. Ports Indeklima design system:
  DM Sans + DM Mono, `section-box` card anatomy, SVG ring component,
  chip/badge system, deep-dark palette with CSS custom properties.
  Heat semantics palette: amber for On, yellow for Pause, red for window/waste,
  teal for pre-heat.

---

## [0.2.9] — 2026-03-28

### Added
- `CONF_CO2_SENSOR` per-room — CO₂-aware window notifications and 50 % waste
  reduction when ventilation is justified.
- `CONF_ROOM_TEMP_SENSOR` per-room — external probe for PID feedback.
- `CONF_OUTDOOR_TEMP_SENSOR` global — local sensor overrides weather entity.

---

## [0.2.8] — 2026-03-28

### Fixed
- **B-CONFIG-2** Optional entity selectors reject empty strings; switched to
  text selectors for `homekit_climate_entity` and `pi_demand_entity`.
- **B-429** `asyncio.sleep(0.6)` stagger between rooms in `_set_all_away()`
  and `_restore_all_schedule()`.
- **B-PANEL-ENTITY-ID** Panel entity IDs resolved by suffix scan, not hardcoded.
- **B-PANEL-RAF** `requestAnimationFrame` → `setTimeout(0)`.

---

## [0.2.7] — 2026-03-27

### Added
- `CONF_TRV_TYPE` per-room — `netatmo` vs `zigbee` routing in presence,
  window, and preheat engines.
- `CONF_PI_DEMAND_ENTITY` per-room — dedicated Z2M `pi_heating_demand` sensor.

---

## [0.2.6] — 2026-03-27

### Added
- `CONF_HOMEKIT_CLIMATE_ENTITY` per-room — local HomeKit write channel for PID.
- `CONF_ROOM_WATTAGE` per-room — real kWh calculation via `heating_power_request`.

---

## [0.2.5] — 2026-03-27

### Added
- `_async_pid_tick()` in coordinator — PID setpoints written every 60 s.
- `tests/test_pid_tick.py` — 12 tests.

---

## [0.2.4] — 2026-03-27

### Added
- `engine/pid_controller.py` — discrete-time PI(D) with anti-windup and
  `power_to_setpoint()` mapper.
- `tests/test_pid_controller.py` — 24 tests.

---

## [0.2.1] — 2026-03-25

### Fixed
- **B5/B6/B7** `panel.js` — WebKit `ShadowRoot.insertAdjacentHTML` crash,
  ON-button blink, persistent blink from concurrent renders.

---

## [0.2.0] — 2026-03-21

### Added
- `engine/season_engine.py`, `engine/waste_calculator.py`,
  `engine/preheat_engine.py`. Diagnostics, icons, HACS, full translations.

---

## [0.1.0] — 2026-03-20

### Added
- Initial release. All engines, config flow, platform entities, frontend
  panel and card, English + Danish translations, 36 tests.

---

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/v0.4.6...HEAD
[0.4.6]: https://github.com/kingpainter/heat-manager/compare/v0.4.5...v0.4.6
[0.4.5]: https://github.com/kingpainter/heat-manager/compare/v0.4.4...v0.4.5
[0.4.4]: https://github.com/kingpainter/heat-manager/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/kingpainter/heat-manager/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/kingpainter/heat-manager/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/kingpainter/heat-manager/compare/v0.3.9...v0.4.1
[0.3.9]: https://github.com/kingpainter/heat-manager/compare/v0.3.8...v0.3.9
[0.3.8]: https://github.com/kingpainter/heat-manager/compare/v0.3.7...v0.3.8
[0.3.7]: https://github.com/kingpainter/heat-manager/compare/v0.3.6...v0.3.7
[0.3.6]: https://github.com/kingpainter/heat-manager/compare/v0.3.5...v0.3.6
[0.3.5]: https://github.com/kingpainter/heat-manager/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/kingpainter/heat-manager/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/kingpainter/heat-manager/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/kingpainter/heat-manager/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/kingpainter/heat-manager/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/kingpainter/heat-manager/compare/v0.2.9...v0.3.0
[0.2.9]: https://github.com/kingpainter/heat-manager/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/kingpainter/heat-manager/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/kingpainter/heat-manager/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/kingpainter/heat-manager/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/kingpainter/heat-manager/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/kingpainter/heat-manager/compare/v0.2.1...v0.2.4
[0.2.1]: https://github.com/kingpainter/heat-manager/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/kingpainter/heat-manager/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kingpainter/heat-manager/releases/tag/v0.1.0
