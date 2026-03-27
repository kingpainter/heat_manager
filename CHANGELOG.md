# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Nothing yet._

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
- Fixed B6 — ON button (and other controller buttons) blinked on panel load. Root cause:
  `connectedCallback` rendered a full skeleton with unstyled buttons, then `_load()` called
  `_render()` milliseconds later via `replaceWith()`, causing a visible double-paint.
  `connectedCallback` now injects only `<style>` and an empty `.panel` shell with no
  buttons. `_controllerHTML()` no longer bakes active-state colours into inline `style=""`
  attributes — `_patchController()` is the sole colour authority, always called after
  `_render()`. CSS `transition` removed from `.ctrl-btn` to prevent animated flash.
- Fixed B7 — button blink persisted due to three concurrent render triggers: (1) HA's
  `ha-panel-custom` calling `set hass()` 4–8 times in rapid succession at boot, (2) a
  second `_load()` starting while the first WS fetch was still in flight, (3) a redundant
  `_patchController()` DOM write on every `set hass()` even when `controller_state` had
  not changed. Fixed by adding a `_loadInFlight` guard that drops concurrent fetches, a
  `_lastCtrlState` diff in `set hass()` that skips the patch when state is unchanged, and
  a `_scheduleRender()` debounce via `requestAnimationFrame` that coalesces multiple render
  calls within the same JS task into a single DOM swap per frame.

---

## [0.2.0] — 2026-03-21

### Added
- `engine/season_engine.py` — resolves `SeasonMode.AUTO` to effective WINTER or SUMMER
  based on outdoor temperature sustained above threshold for N consecutive days.
- `engine/waste_calculator.py` — per-room energy waste and savings estimation using
  Δtemp × duration × efficiency coefficient. Replaces the tick-accumulator placeholder.
  Resets at midnight.
- `engine/preheat_engine.py` — monitors `sensor.<person>_travel_time_home` sensors and
  starts pre-heating N minutes before a tracked person arrives. Arms when everyone leaves,
  disarms on arrival. No-op if no travel_time sensors are found.
- `diagnostics.py` — `async_get_config_entry_diagnostics()` for Gold IQS. Downloads a
  full snapshot of config, runtime state, engine internals and recent event log from
  Settings → Heat Manager → ⋮ → Download diagnostics.
- `icons.json` — entity icon overrides for all platform entities (Gold IQS icon-translations).
- `sensor.py` — new `EnergySavedSensor` (`sensor.heat_manager_energy_saved_today`).
- `hacs.json` — integration packaged for HACS distribution.
- `coordinator.py` — `log_event()` method populating `_event_log` deque (max 200 entries).
  `effective_season` property. `energy_wasted_today`, `energy_saved_today`, `efficiency_score`
  properties delegating to `WasteCalculator`.
- `strings.json` / `translations/en.json` / `translations/da.json` — `entity` section with
  names and state labels for all platform entities. `exceptions` section for translated
  `ServiceValidationError` and `ConfigEntryNotReady` messages.
- `tests/` — 3 new test files: `test_season_engine.py` (9 tests), `test_waste_calculator.py`
  (10 tests), `test_preheat_engine.py` (14 tests). Total: 58 tests across 5 engine files.

### Changed
- `sensor.py` — `EnergyWastedSensor` and `EfficiencyScoreSensor` now read from
  `coordinator.waste_calculator` instead of accumulating independently.
- `sensor.py`, `binary_sensor.py`, `select.py`, `switch.py` — `entity_registry_enabled_default`
  applied throughout: diagnostic and CONFIG entities are disabled by default.
- `sensor.py` — `RoomStateSensor` marks itself unavailable when the backing climate entity
  is unavailable. Logs WARNING once on unavailable, INFO once on recovery (Silver IQS).
- `websocket.py` — `get_state` returns live energy values and `effective_season` directly
  from coordinator. `get_history` reads from `coordinator._event_log` deque with ISO-timestamp
  filtering. Daily energy chart shows real today values.
- `engine/presence_engine.py` — `log_event()` called at every significant state transition:
  arrival, departure, grace expiry, alarm arm/disarm, force-on.
- `engine/window_engine.py` — `log_event()` called on window open, close, and 30-min warning.
- `coordinator.py` — tick order extended: season → controller → presence → window →
  waste_calculator → preheat.
- `__init__.py` — raises `ConfigEntryNotReady` with `translation_key` if first coordinator
  refresh fails or no configured climate entities are reachable at startup.
- `__init__.py` — `ServiceValidationError` raised with `translation_domain` and
  `translation_key` for translated error messages in HA UI (Gold IQS exception-translations).
- `frontend/heat-manager-panel.js` — blink fixes: `<style>` injected once via
  `querySelector` guard; `_render()` uses `replaceWith()` on `.panel` div instead of
  wiping the entire shadow root; `connectedCallback` shows "Indlæser…" skeleton on first
  mount instead of calling `_render()` with null data.
- `frontend/heat-manager-card.js` — blink fixes: `<style>` injected once; `.card` div
  replaced via `replaceWith()` instead of full `shadowRoot.innerHTML` rebuild.

### Fixed
- Fixed `CARDS_FILE` typo in `panel.py` (`heat-manager-cards.js` → `heat-manager-card.js`)
  that silently prevented the Lovelace card from appearing in the card picker.
- Fixed duplicate Lovelace resource entries accumulating across reloads. `panel.py` now
  removes all stale entries matching known URL prefixes before registering the canonical URL.
- Fixed `window.customCards` not registering synchronously. Rewrote `heat-manager-card.js`
  from ES module (LitElement import) to vanilla JS so registration happens at parse time.
- Fixed `HeatManagerCardEditor` missing — `getConfigElement()` previously referenced a
  non-existent custom element, crashing the Lovelace card editor silently.
- Fixed FOUC on tab switch in sidebar panel caused by `<style>` being re-injected via
  `shadowRoot.innerHTML` on every `_render()` call.
- Fixed controller box blink in sidebar panel caused by `connectedCallback` calling
  `_render()` with `_data = null`, resulting in a double render on first mount.

---

## [0.1.0] — 2026-03-20 (foundation)

### Added
- Initial project structure and repository setup.
- `manifest.json` with `config_flow: true`, `iot_class: local_push`.
- `const.py` — single source of truth for all constants and enums (`ControllerState`,
  `SeasonMode`, `RoomState`, `AutoOffReason`).
- `engine/controller.py` — `ControllerEngine` with ON / PAUSE / OFF state machine,
  `@guarded` decorator, pause timer with auto-resume, auto-off via season and outdoor
  temperature, season-aware OFF fallback.
- `engine/presence_engine.py` — presence-based heating logic with configurable day/night
  grace periods, alarm panel coordination, and actionable arrival notifications.
- `engine/window_engine.py` — per-room window detection state machine with configurable
  open delay, 30-minute escalation warning, and presence-aware restore on close.
- `config_flow.py` — 4-step UI setup wizard with repeatable room and person steps.
  `HeatManagerOptionsFlow` for post-setup editing including add/delete rooms and persons.
- `select.py`, `sensor.py`, `binary_sensor.py`, `switch.py` — all platform entities.
- `panel.py` — sidebar panel and Lovelace card resource registration.
- `websocket.py` — `heat_manager/get_state` and `heat_manager/get_history` WS commands.
- `frontend/heat-manager-panel.js` — sidebar panel with 4 tabs (Overview, Rooms, History,
  Configuration). Blink-free controller box via surgical DOM patching.
- `frontend/heat-manager-card.js` — Lovelace card with ON/PAUSE/OFF, room overview,
  energy stats, and `HeatManagerCardEditor` for in-UI configuration.
- `translations/en.json` and `translations/da.json` — complete English and Danish translations.
- `tests/` — 36 tests across `test_controller_engine.py`, `test_presence_engine.py`,
  `test_window_engine.py`.
- `.cursorrules`, `CHANGELOG.md`, `README.md`, `GIT_WORKFLOW.md`, `quality_scale.yaml`,
  `STATUS.md`.

### Fixed
- Fixed B1 — entity ID typo `.binary_sensor.lukas_vindue_contact` (leading dot) prevented
  Lukas' window from ever being detected.
- Fixed B2 — 30-minute open-window warning was dead code in the original YAML automations.
- Fixed B3 — closing a window always restored schedule even when nobody was home.
- Fixed B4 — alarm `armed_away → disarmed` had no handler; heating stayed off permanently
  after disarm.

---

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/kingpainter/heat-manager/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/kingpainter/heat-manager/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kingpainter/heat-manager/releases/tag/v0.1.0
