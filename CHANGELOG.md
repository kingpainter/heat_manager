# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Nothing yet._

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

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/v0.3.9...HEAD
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
