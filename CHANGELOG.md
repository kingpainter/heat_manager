# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Nothing yet._

---

## [0.3.2] — 2026-03-29

### Fixed
- Fixed B-429-RESTORE-RACE — `_restore_all_schedule()` in `presence_engine.py`
  had no re-entrancy guard, so concurrent callers (e.g. a person arriving while
  a window closed within the same 2-second window) each iterated all rooms
  independently, producing `N × rooms` Netatmo API calls in rapid succession and
  reliably triggering HTTP 429 rate-limit errors on `setthermmode`. Fixed by
  adding `_restore_lock` (`asyncio.Lock`): a second caller that finds the lock
  held exits immediately with a `DEBUG` log rather than duplicating the sweep.
- Fixed B-LOG-RESTORE-SPAM — `_restore_all_schedule()` emitted one
  `_LOGGER.warning` per room per failed attempt. With 4 rooms and two
  racing callers this produced 8 identical log lines within 2 minutes, violating
  the Silver IQS "log once" rule. Fixed by adding a per-room NORMAL-state
  idempotency check: rooms already in `RoomState.NORMAL` skip the API call
  entirely, so a second concurrent caller finds nothing to do and logs nothing.
- Fixed stale version strings — `manifest.json` and `const.py` were still
  pinned to `0.2.9` despite `CHANGELOG.md` recording releases through `0.3.1`.
  Both files now correctly reflect `0.3.2`.

---

## [0.3.1] — 2026-03-28

### Fixed
- Fixed B-CARD-IAH — `HeatManagerCard._render()` used invalid optional-chain
  syntax (`?.replaceWith?.()`) on `replaceWith()` that is not supported in all
  JS engines, causing a `Configuration error` crash in the Lovelace card picker
  dialog. Replaced with an explicit `if (existing)` null check.
- Fixed B-CARD-IAH — first-render path now uses `_srAppend()` (WebKit-safe
  helper, same pattern as the panel) instead of a direct shadow root
  `appendChild`, eliminating any residual `insertAdjacentHTML` path on
  `ShadowRoot`.

---

## [0.3.0] — 2026-03-28

### Changed
- `frontend/heat-manager-panel.js` — complete visual redesign. Ports
  Indeklima's design system to Heat Manager so both integrations share the
  same visual family: DM Sans + DM Mono fonts, `section-box` / `section-header`
  / `section-badge` card anatomy, SVG ring component, chip/badge system,
  deep-dark palette with CSS custom properties.
  Palette shifted to heat semantics: amber `#f97316` for active heating / On,
  yellow `#eab308` for Pause, grey for Off, red for window open / waste,
  teal for pre-heat.
  New visual elements: controller ring (SVG arc showing On/Pause/Off state),
  room grid with per-state `border-left` colour + gradient background,
  badge-pulse animation for `window_open` and `pre_heat` rooms, efficiency
  score ring (identical SVG component to Indeklima severity ring), quick-stats
  row with room state counts, `↻ Opdater` refresh button.
  All blink guards from v0.2.x preserved: `_loadInFlight`, `_lastCtrlState`
  diff, `setTimeout(0)` debounce, `_srAppendHTML()` WebKit helper, surgical
  `_patchController()`.
- `frontend/heat-manager-card.js` — complete visual redesign, same design
  system as the panel. Section-box structure, SVG efficiency ring, room cards
  with state colour and badge-pulse, amber controller badge with pulsating dot.
  Editor restyled with dark background, orange focus rings, orange
  "+ Tilføj rum" button.
  `_updateInPlace()` retained — all live state updates happen without
  DOM rebuild.

---

## [0.2.9] — 2026-03-28

### Added
- Added `CONF_CO2_SENSOR` (`co2_sensor`) per-room optional config field.
  When set, `WindowEngine` includes the current CO₂ level and a contextual
  label ("ventilation" vs "heat loss") in all window-related notifications —
  open, close, and the 30-minute escalation warning. Threshold is
  `DEFAULT_CO2_VENTILATION_THRESHOLD = 900 ppm`; above this the window is
  considered purposeful ventilation rather than careless heat loss.
- Added `CONF_ROOM_TEMP_SENSOR` (`room_temp_sensor`) per-room optional config
  field. When set, the PID controller reads `current_temperature` from this
  independent probe instead of from the TRV's own built-in sensor. Particularly
  beneficial for Zigbee TRVs (Z2M) whose sensor sits on the hot radiator body
  and typically reads 1–3 °C above actual room temperature, causing the PID to
  under-heat. Netatmo rooms also benefit if the NRV is poorly positioned.
- Added `CONF_OUTDOOR_TEMP_SENSOR` (`outdoor_temp_sensor`) global optional
  config field (Step 1 / global settings). When set, overrides the temperature
  attribute read from the `weather.*` entity for all outdoor-temperature
  decisions: adaptive away setpoint, SeasonEngine day-counter, and controller
  auto-off. Falls back to the weather entity if the sensor is unavailable.
  Useful when a local weather station (Netatmo outdoor module, Aqara, etc.)
  is available for more accurate microclimate data.
- Added `DEFAULT_CO2_VENTILATION_THRESHOLD = 900` ppm constant to `const.py`.

### Changed
- `coordinator.py` — `_refresh_outdoor_temperature()` now checks
  `CONF_OUTDOOR_TEMP_SENSOR` first and falls back to the weather entity.
  Existing installations without a dedicated sensor are completely unaffected.
- `coordinator.py` — new `get_room_co2(room_name)` helper. Returns current CO₂
  in ppm as `float | None`. Returns `None` when no sensor is configured or the
  sensor is unavailable.
- `coordinator.py` — new `get_room_current_temp(room_name, climate_id)` helper
  with three-tier priority: (1) `CONF_ROOM_TEMP_SENSOR`, (2) HomeKit entity
  `current_temperature` (Netatmo local HAP), (3) cloud entity
  `current_temperature`. `_async_pid_tick()` now calls this helper instead of
  reading the HomeKit entity directly, so Zigbee rooms with an external probe
  benefit from PID accuracy without requiring a HomeKit entity.
- `engine/window_engine.py` — new `_co2_context_label(co2_ppm)` private method.
  Returns `""` (no sensor), `"  (CO₂: N ppm — ventilation)"` (≥ threshold), or
  `"  (CO₂: N ppm — heat loss)"` (< threshold). Appended to open, close, and
  30-min warning notification messages. `_get_current_temp()` now delegates to
  `coordinator.get_room_current_temp()` instead of reading the climate entity
  directly.
- `engine/waste_calculator.py` — new `_co2_waste_weight(room_name)` method.
  Returns `1.0` when no CO₂ sensor is configured or CO₂ is below threshold;
  returns `0.50` when CO₂ ≥ `DEFAULT_CO2_VENTILATION_THRESHOLD`. Applied to
  `waste_kwh` each tick so that ventilation-justified window openings count as
  only 50 % waste in the efficiency score and energy-wasted sensor.
- `config_flow.py` — Step 1 / global schema gains `outdoor_temp_sensor` text
  field. Room schema gains `co2_sensor` and `room_temp_sensor` text fields with
  `data_description` help text on both. All three fields also appear in the
  options flow global and room-add steps.
- `strings.json`, `translations/en.json`, `translations/da.json` — new labels
  and `data_description` entries for all three fields in both languages.
- `manifest.json` — version `0.2.8` → `0.2.9`.
- `const.py` — version string `0.2.8` → `0.2.9`.

---

## [0.2.8] — 2026-03-28

### Fixed
- Fixed B-CONFIG-2 — `homekit_climate_entity` and `pi_demand_entity` config flow fields
  used HA `entity` selectors, which reject empty strings even for optional fields. Both
  fields now use `text` selectors so Zigbee TRV rooms (which have no HomeKit entity)
  can be saved without a validation error. Engines continue to guard with `or None` at
  read time. This unblocked Badeværelse (Zigbee Z2M TRV) room configuration.
- Fixed B-429 — Netatmo API returned HTTP 429 on `setthermmode` when Heat Manager
  called `set_preset_mode` on all four Netatmo rooms nearly simultaneously. Added
  `asyncio.sleep(0.6)` between each room in both `_set_all_away()` and
  `_restore_all_schedule()` in `presence_engine.py`. Staggering the calls 600 ms
  apart brings burst traffic well within Netatmo's tolerance.
- Fixed B-PANEL-ENTITY-ID — after reinstalling the integration the config entry ID
  changes, making entity IDs like `select.heat_manager_controller_state` stale (new
  format: `select.heat_manager_01km1bjqb193y3hf2aec3x66w3_controller_state`). The
  panel's `_syncFromEntities()` and `_entitiesSnapshot()` hardcoded the old IDs and
  therefore always read `"unknown"`. Fixed by `_resolveEntityIds()` which scans
  `hass.states` once on first use and finds the three panel entities by suffix
  (`_controller_state`, `_season_mode`, `_pause_remaining`). Resolves the
  On / Pause / Off buttons never rendering after reinstall.
- Fixed B-PANEL-RAF — `_scheduleRender()` used `requestAnimationFrame` which stalls
  in HA's panel context when the panel is not the active viewport, leaving
  `_renderPending = true` permanently and the panel blank. Switched to `setTimeout(0)`.

### Changed
- `frontend/heat-manager-panel.js` — `_seasonTriggerLabel(season, reason)` method
  added. Replaces the inline ternary `season==='summer' ? 'Sommer — aktiv' : 'Vinter
  — inaktiv'` with context-aware labels: `Vinter — kører normalt`, `Vinter — slået
  fra`, `Sommer — auto-off klar`, `Sommer — slået fra`, `Auto — overvåger ude-temp`.

---

## [0.2.7] — 2026-03-27

### Added
- Added `CONF_TRV_TYPE` (`trv_type`) per-room config field with two options:
  `netatmo` (default, existing behaviour) and `zigbee` (Zigbee2MQTT TRVs without
  preset_mode concept). Added `TRV_TYPE_NETATMO`, `TRV_TYPE_ZIGBEE`,
  `TRV_TYPE_OPTIONS` string constants.
- Added `CONF_PI_DEMAND_ENTITY` (`pi_demand_entity`) per-room config field.
  Optional dedicated sensor entity for Z2M TRVs that expose `pi_heating_demand`
  as a separate `sensor.*` entity (e.g. `sensor.bad_varme_test_trv_pi_heating_demand`).
- Added both fields to `config_flow._room_schema()`: `trv_type` as a select
  widget and `pi_demand_entity` as a sensor entity selector.

### Changed
- `presence_engine._set_all_away()`: branches on `trv_type`.
  Zigbee rooms receive `climate.set_hvac_mode hvac_mode=off`;
  Netatmo rooms receive `climate.set_preset_mode preset_mode=away` (unchanged).
- `presence_engine._restore_all_schedule()`: branches on `trv_type`.
  Zigbee rooms receive `climate.set_hvac_mode hvac_mode=heat`;
  Netatmo rooms receive `climate.set_preset_mode preset_mode=schedule` (unchanged).
- `presence_engine.force_room_on()`: branches on `trv_type` the same way.
- `waste_calculator._get_heating_power_pct()`: now accepts optional `pi_entity`
  parameter. Priority: (1) dedicated Z2M sensor state, (2) `heating_power_request`
  climate attribute (Netatmo), (3) None → Δtemp fallback. Existing Netatmo rooms
  are completely unaffected.

---

## [0.2.6] — 2026-03-27

### Added
- Added `CONF_HOMEKIT_CLIMATE_ENTITY` (`homekit_climate_entity`) per-room config key.
  When set, `_async_pid_tick()` reads `current_temperature` from this entity (Netatmo
  Relay via HomeKit Accessory Protocol on LAN, <100 ms) and writes `set_temperature`
  here instead of the Netatmo cloud entity.
- Added `CONF_ROOM_WATTAGE` / `DEFAULT_ROOM_WATTAGE` (1000 W) per-room config key for
  energy calculations.

### Changed
- `coordinator._async_pid_tick()` fully reworked for Netatmo NRV architecture:
  - Reads schedule setpoint from cloud entity (`climate_entity`) — Netatmo's own MPC
    target from the active schedule.
  - Reads `current_temperature` from HomeKit entity (local HAP) — fresher, no cloud.
  - Writes `set_temperature` to HomeKit entity only — never to cloud entity, so
    Netatmo's schedule and preset system is not disturbed.
  - If no `homekit_climate_entity` is configured for a room, PID is silently skipped
    for that room (Netatmo's own MPC remains in full control).
  - Debug log now includes `heating_power_request` from cloud entity for easy tuning.
- `engine/waste_calculator.py` rewritten for Phase 4:
  - Uses `heating_power_request` (0–100%) × `room_wattage` for real kWh calculation
    instead of the fictional 0.1 kWh/°C/h constant.
  - Keeps a rolling `_last_power_pct` history per room to estimate away-mode savings.
  - Falls back to Phase 3 Δtemp formula for non-Netatmo rooms without
    `heating_power_request`.
  - `efficiency_score` recalibrated: 1 point lost per 0.01 kWh wasted (was per 0.1).
- `config_flow.py` room schema extended with two new optional fields: `homekit_climate_entity`
  (entity selector, domain `climate`) and `room_wattage` (number selector, 100–5000 W,
  default 1000 W). Both fields appear in the setup wizard and in the options flow
  room-add step, pre-filled with current values when editing.

---

## [0.2.5] — 2026-03-27

### Added
- Added `_async_pid_tick()` to `HeatManagerCoordinator`, called at position 8 in the
  periodic tick after all other engines have settled state. Drives the PID controller
  for every room in `NORMAL` state each 60-second tick, computing a proportional TRV
  setpoint from `climate.current_temperature` and `climate.temperature`.
- Added `tests/test_pid_tick.py` with 12 offline tests covering all guard conditions
  (pid disabled, controller paused/off, summer season, room AWAY/WINDOW_OPEN/PRE_HEAT,
  climate unavailable, missing temperature attributes) plus happy-path and regression
  B-PID-2 (delta threshold prevents TRV command spam).

### Changed
- `coordinator._async_update_data()` docstring updated to list PID tick as step 8.
- PID resets on every non-NORMAL state so integral debt cannot accumulate while the
  controller is not in authority.
- Setpoint commands are suppressed when the computed TRV setpoint is within 0.5 °C of
  the current `climate.temperature` attribute to prevent flooding TRVs with redundant
  commands every 60 seconds.

---

## [0.2.4] — 2026-03-27

### Added
- Added `engine/pid_controller.py` — a discrete-time PI(D) controller that converts a
  room temperature error into a proportional heating power fraction (0.0–1.0), then maps
  that fraction to a graduated TRV setpoint via `power_to_setpoint()`. Replaces the
  previous binary on/off approach and the hardcoded 10 °C window floor.
- Added `CONF_PID_KP`, `CONF_PID_KI`, `CONF_PID_KD`, `CONF_PID_ENABLED`, and
  `CONF_TRV_MAX_TEMP` constants plus matching defaults in `const.py`.
- Added `pid_controllers` dict, `_init_pid_controllers()`, `get_pid()`, `pid_enabled`,
  and `trv_max_temp` to `HeatManagerCoordinator` — one `PidController` instance per room.
- Added `tests/test_pid_controller.py` with 24 offline tests covering P/I/D terms,
  anti-windup clamping, `power_to_setpoint` edge cases, reset behaviour, and regression
  test B-PID-1 (integral does not wind up during away/window-open periods).

### Changed
- `window_engine.py` now uses `_window_open_setpoint()` instead of writing the hardcoded
  `away_temp_override` directly. When PID is enabled the setpoint is computed via
  `PidController.power_to_setpoint(power=0.0, ...)`, honouring the per-room
  `away_temp_override` as the `trv_min` floor. When PID is disabled the previous
  behaviour is preserved exactly.
- `window_engine.py` calls `pid.reset()` immediately after a window opens, preventing
  integral windup debt from accumulating while the TRV is suppressed.

---

## [0.2.1] — 2026-03-25

### Fixed
- Fixed B5 — `ShadowRoot.insertAdjacentHTML` is not implemented in WebKit (iOS 18 /
  Safari). Both call sites in `heat-manager-panel.js` (`connectedCallback` skeleton path
  and `_render()` first-render fallback) now use a new `_srAppendHTML()` helper that
  parses HTML via a temporary `<div>` and appends child nodes individually.
- Fixed B6 — ON button (and other controller buttons) blinked on panel load.
- Fixed B7 — button blink persisted due to three concurrent render triggers.

---

## [0.2.0] — 2026-03-21

### Added
- `engine/season_engine.py`, `engine/waste_calculator.py`, `engine/preheat_engine.py`.
- `diagnostics.py`, `icons.json`, `hacs.json`.
- Full translations, entity categories, coordinator event log.

---

## [0.1.0] — 2026-03-20 (foundation)

### Added
- Initial project structure, all engines, config flow, platform entities, frontend panel
  and card, full English + Danish translations, 36 tests.

---

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/v0.3.2...HEAD
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
