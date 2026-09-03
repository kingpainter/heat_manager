# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.9.2] — 2026-09-03

Deep-dive review of the full v0.9.0/v0.9.1 feature set, fixing one real
correctness bug found along the way and hardening an edge case.

### Fixed
- `engine/calibration_engine.py` — the written calibration offset was
  computed as an absolute `truth - raw` value every tick. On real
  Zigbee2MQTT TRVs `current_temperature` already reflects whatever
  `local_temperature_calibration` is currently applied (that's the whole
  point of the setting), so this oscillated: tick N writes the correct
  offset, tick N+1 reads the now-corrected temperature, computes a ~0
  residual, and writes 0.0 — undoing tick N's correction — forever. The
  fix reads the calibration entity's own current value and adds the
  residual on top instead of overwriting, so it converges to a stable
  value. Added two regression tests that simulate the device echoing back
  a previously-written calibration value.
- `engine/sync_engine.py` — `_async_act()` (the confirm-delay callback for
  `sync_mode: lock`/`mirror`) now re-checks the room's current write
  entity before acting, matching the guard `_handle_entity_change()`
  already had. Closes a narrow window where a HomeKit↔cloud write-entity
  switch during the `SYNC_CONFIRM_DELAY_SEC` wait could act on a stale
  entity_id.
- `frontend/heat-manager-panel.js` — the group-offset slider's "don't
  fight the user's drag" guard compared against `document.activeElement`,
  which never equals an element inside an open shadow root (it resolves to
  the panel's own host element instead) — the guard was a no-op, so the
  slider could snap back to the last-polled value mid-drag. Now compares
  against `this.shadowRoot.activeElement`, matching the card's version.

No functional or behavioural change outside the above three fixes.

---

## [0.9.1] — 2026-09-03

Surfaces v0.9.0's backend-only additions in both frontend files — the
group offset slider and self-reporting `blocking_sources` diagnostics were
previously only reachable from Developer Tools or a generic dashboard card.

### Added
- `frontend/heat-manager-panel.js`, `frontend/heat-manager-card.js` —
  `number.heat_manager_group_offset` now has a live slider (Controller
  hero on the panel, its own row on the card), wired to `number.set_value`
  and kept in sync with backend polls (paused while the user is actively
  dragging it).
- `frontend/heat-manager-panel.js`, `frontend/heat-manager-card.js` —
  global and per-room `blocking_sources` are now shown as short Danish
  tags: a global indicator under the controller title, and a per-room
  badge for the sources not already implied by the room's state pill
  (`controller_off` / `controller_pause` — `window`/`presence` are
  suppressed there since `window_open`/`away` already show).
- `custom_components/heat_manager/websocket.py` — `ws_get_state` payload
  now includes top-level `group_offset` and `blocking_sources`, plus
  per-room `blocking_sources`, `calibration_entity`, `sync_mode` and
  `schedule_entity` (raw values only — the panel/card own all display
  labels, per the existing convention).
- `frontend/heat-manager-panel.js` — Konfiguration tab's room list now
  shows a small read-only line when a room has calibration/sync/schedule
  configured. The config-flow (reconfigure) wizard remains the only way
  to actually set these three fields — a dedicated editor UI for them was
  scoped out of this pass.

---

## [0.9.0] — 2026-09-03

Five features inspired by a comparison against
[`climate_group_helper`](https://github.com/bjrnptrsn/climate_group_helper),
implemented as five independent, individually opt-in layers. None of them
touch `SeasonEngine`, the existing Netatmo cloud schedule, or any
already-shipped engine's own behaviour — a room that doesn't configure the
new fields behaves exactly as it did in 0.8.0.

### Added
- **Device calibration** `const.py`, new `engine/calibration_engine.py`,
  `coordinator.py`, `config_flow.py`, `sensor.py` — new optional per-room
  `calibration_entity` field (a `number.*` entity the TRV's own integration
  exposes, e.g. Zigbee2MQTT's `local_temperature_calibration`). When set
  together with the existing `room_temp_sensor` field, `CalibrationEngine`
  writes the delta between the external sensor and the TRV's own raw
  reading to that entity every tick, so the device's internal control loop
  stays accurate even when Heat Manager's own writes are briefly
  unavailable (network hiccup, HA restart). A 30-minute heartbeat re-sends
  the value even when unchanged, guarding against Zigbee entities silently
  reverting. A new diagnostic, disabled-by-default sensor exposes the last
  written offset per room.
- **Sync modes** `const.py`, new `engine/sync_engine.py`, `coordinator.py`,
  `config_flow.py` — new optional per-room `sync_mode` field
  (`disabled` / `mirror` / `lock`). Detects when a room's write entity
  changes for a reason other than Heat Manager's own PID tick (the Netatmo
  app, a physical TRV dial, another automation) by comparing the entity's
  reported setpoint against `coordinator.last_expected_setpoint` — the
  value the PID tick itself last computed — rather than instrumenting every
  write call-site with a "this write is ours" flag. A mismatch must persist
  12 s before acting, absorbing the normal round-trip window right after
  Heat Manager's own write. `mirror` accepts the change (switches the room
  to `OVERRIDE`, same as the existing per-room override switch); `lock`
  reverts it back to the expected setpoint.
- **Group offset** new `number.py` platform (`PLATFORMS` in `const.py`
  extended), `const.py`, `coordinator.py` — new
  `number.heat_manager_group_offset` entity (±5.0 °C slider, `RestoreNumber`
  — persists across HA restarts). Applied fresh every PID tick on top of
  whichever base target is in effect (cloud schedule setpoint, comfort_temp,
  or a schedule/calendar override), so it automatically follows the next
  schedule/season transition instead of being baked into a stored value.
  Auto-resets to 0 °C when a boost starts, mirroring how boost already
  overrides other temporary state.
- **Schedule / calendar integration** `const.py`, new
  `engine/schedule_engine.py`, `coordinator.py`, `config_flow.py` — new
  optional per-room `schedule_entity` field, pointing at a native HA
  `schedule.*` helper or a `calendar.*` entity. While a block/event is
  active, its `temperature` overrides the room's normal target
  (`comfort_temp` on the local path, or the Netatmo cloud schedule setpoint
  on the HomeKit path) for the duration — read fresh every tick, so it
  releases automatically once the block/event ends. `schedule.*` entities
  use HA's own native "Additional data" per time block (copied onto the
  entity's attributes automatically); `calendar.*` entities have the
  event's `description` parsed as YAML `key: value` pairs, mirroring
  `climate_group_helper`'s format. Group offset and the night/wake setbacks
  still apply on top. A parsed temperature is clamped to 5–30 °C as a
  defensive sanity check. Out of scope for this first pass (left for a
  future phase): `hvac_mode`/`turn_off` overrides, a bypass priority layer,
  and the wider CGH meta-key set (`sync_mode`, `window_mode`,
  `presence_mode`, …) driven per slot.
- **Self-reporting diagnostics** `coordinator.py`, `select.py`, `sensor.py`
  — new `get_room_blocking_sources(room_name)` / `global_blocking_sources()`
  coordinator helpers, surfaced as a `blocking_sources` attribute on
  `select.heat_manager_controller_state` (global) and
  `sensor.<room>_room_state` (per room): a plain list of what is currently
  preventing that room (or the whole system) from heating —
  `controller_off`, `controller_pause`, `window`, `presence` — so a
  dashboard or automation can answer "why isn't this room heating right
  now" without cross-referencing multiple entities.

### Tests
- 65 new tests across `test_calibration_engine.py` (15),
  `test_sync_engine.py` (20), `test_schedule_engine.py` (15),
  `test_blocking_sources.py` (12), and 3 new `test_pid_tick.py` cases
  covering the schedule-override hook — full suite: 160 → 225 passed,
  coverage 44.99% → 48.00%.

---

## [0.8.0] — 2026-09-02

### Added
- **Hybrid PID engine** `coordinator.py`, `const.py`, `config_flow.py`,
  `strings.json`, `translations/{en,da}.json` — `_async_pid_tick()`
  generalised from a Netatmo-only engine into a single regulation engine for
  **all** room types:
  - **Netatmo rooms** (with `homekit_climate_entity`): unchanged — target
    comes from the cloud entity's schedule setpoint, PID writes to the local
    HomeKit entity.
  - **Local rooms** (Zigbee today, Matter/Thread later — no
    `homekit_climate_entity`): NEW. Previously these rooms received *no*
    positive temperature regulation from Heat Manager at all — only the
    negative actions (away setback, window-open shutoff) applied, since PID
    unconditionally skipped any room without a HomeKit entity. A new
    per-room `comfort_temp` field (default 20°C) now serves as the PID
    target — playing the same role Netatmo's cloud schedule setpoint plays
    for HomeKit rooms — combined with the same `RoomState` (AWAY/NORMAL) and
    `night_setback_delta()` presence + day/night logic. PID writes directly
    to the room's own `climate_entity`, since Zigbee2MQTT/Matter/Thread are
    local with no cloud rate-limit concern.
  - **Outdoor feedforward** (both room types): a small proactive power
    contribution based on outdoor temperature (`FF_REFERENCE_OUTDOOR_TEMP`,
    `FF_WEIGHT`, `FF_MAX_CONTRIBUTION` in `const.py`) is now added on top of
    PID's reactive correction — classic "heating curve" weather
    compensation. With a 60 s tick and several minutes of TRV thermal lag,
    pure PID only starts correcting once a room has already begun cooling;
    feedforward starts pushing power up as soon as the outdoor temperature
    drops, reducing undershoot during a sudden cold snap. Conservative
    defaults, not yet exposed in the UI.

### Fixed (post-hybrid-engine review)
- **BUG** `sensor.py` — `RoomPidPowerSensor` was only created
  `if room.get(CONF_HOMEKIT_CLIMATE_ENTITY)`. Since the hybrid PID engine
  now regulates local/Zigbee rooms too (against `comfort_temp`), those rooms
  had an actively-computed PID power value with no sensor entity to expose
  it. Now created unconditionally for every room. Removed the now-unused
  `CONF_HOMEKIT_CLIMATE_ENTITY` import.
- **Test bug** `tests/.../test_pid_tick.py` — `make_coordinator()` never set
  `coord.outdoor_temperature`, defaulting to an unconfigured `MagicMock`
  (truthy, not `None`). The new outdoor-feedforward code's
  `max(0.0, (FF_REFERENCE_OUTDOOR_TEMP - self.outdoor_temperature) * FF_WEIGHT)`
  raised `TypeError: '>' not supported between instances of 'MagicMock' and
  'float'` for any test reaching that code path — confirmed by actually
  running the suite (3 tests failed before this fix). Fixed by defaulting
  `outdoor_temperature=None` in the fixture, and by explicitly mocking
  `get_homekit_climate_entity()` instead of relying on MagicMock's
  auto-truthy default (which accidentally exercised only the Netatmo path in
  every existing test, giving zero coverage of the new local/Zigbee path).
  Added 7 new tests: local/Zigbee target-selection, comfort_temp default
  fallback, and 3 feedforward behaviours (additive, zero when mild, capped).
  Full suite re-run afterwards: **160/160 tests pass**, confirmed by actually
  installing Home Assistant core + pytest and executing the suite rather
  than relying on static review alone.
- **BUG** `frontend/heat-manager-panel.js` — the boost button's active/
  inactive visual state was only ever synced from backend data once, inside
  `_attachEvents()`, which runs exactly one time at the panel's very first
  render. Every subsequent 30 s refresh goes through `_patchAll()` instead,
  which never touched the button. A boost stopped from anywhere other than
  that same click (backend auto-expiry, the new `heat_manager.boost_stop`
  service, an automation, another browser tab) left the button looking
  "active" indefinitely until a full page reload. Low-impact before today
  (boost could only be toggled via that one button), but a real, visible bug
  now that boost has other ways to start/stop. Moved the sync into
  `_patchControllerHero()` (already called by `_patchAll()` every refresh).
- **Feature** `frontend/heat-manager-panel.js` — boost button now shows a
  live "⚡ Boost (23 min)" countdown using `boost_remaining_minutes` from the
  `heat_manager/get_state`/`boost_start` WS payload (added earlier but
  previously unused by the frontend). New `_startBoostCountdown()` mirrors
  the existing `_startPauseCountdown()` pattern — ticks the locally-cached
  value down every 60 s between polls; the backend remains authoritative.
- **Unification** `frontend/heat-manager-card.js` — the card's boost button
  duplicated its own boost implementation (direct `climate.set_temperature`
  writes + direct `force_room_on` calls), fully independent of the panel and
  backend. Now delegates to `heat_manager/boost_start`/`boost_stop` WS
  commands — the exact same `coordinator.async_boost_start()`/
  `async_boost_stop()` used by the panel and the `heat_manager.boost_start`
  service. Fixes three concrete problems: (1) a boost started from the
  panel/an automation was invisible to the card and vice versa, so clicking
  boost on one could redundantly re-boost rooms already boosted by the
  other; (2) the backend's own `boost_expires_at` auto-restore never applied
  to card-started boosts, since `boost_active_rooms` was never set
  server-side — only the card's own `setInterval` tracked expiry, which
  stopped the moment the dashboard tab closed; (3) the card only ever
  boosted the subset of rooms listed in *that specific card instance's*
  config, not all of Heat Manager's actual configured rooms — now boosts
  every eligible room regardless of which cards exist. Card bumped to
  v0.4.3 (separate versioning from the integration, as established).

---

## [0.7.0] — 2026-09-02

### Fixed
- **BUG** `__init__.py` — `_async_update_listener` reloaded the *entire*
  integration on every single `entry.options` write, including three purely
  internal writes the coordinator makes itself: the midnight energy-history
  snapshot, a `season_mode` change from the select entity, and an
  alarm_panel/notify_service save from the sidebar panel's config tab. None
  of those values need a reload — the coordinator already reads
  `entry.data`/`entry.options` live every tick. The unconditional reload
  reset every engine's in-memory state (PID integrators,
  `ValveProtectionEngine`'s weekly exercise tracker) and — worst case —
  could silently drop `WindowEngine`'s knowledge that a window was open if
  the reload happened while one was (it has no startup re-sync equivalent to
  `PresenceEngine`'s B11 fix), letting heating resume in that room. The
  listener now compares `rooms`/`persons` against a snapshot taken at the
  coordinator's last successful setup (`coordinator._last_known_rooms` /
  `_last_known_persons`, new in `coordinator.py`) and only reloads when
  those actually changed — the only case that genuinely needs new/removed
  entities. Every other `entry.options` write now applies live with no
  reload, matching the project's own stability goal ("reducer kant-cases
  der får heat_manager til at gå unavailable").
- **BUG** `engine/season_engine.py` — `_maybe_trigger_voice()` used raw
  `asyncio.ensure_future()`, inconsistent with the rest of the codebase
  which explicitly moved away from this exact pattern (see
  `window_engine.py`/`presence_engine.py` docstrings). Replaced with
  `hass.async_create_task(..., name=...)` so the task is tracked and
  cancelled cleanly on shutdown instead of risking an untracked
  "Task exception was never retrieved" warning.
- **BUG** `diagnostics.py` — `async_get_config_entry_diagnostics()` referenced
  `ctrl._days_above_high` and `ctrl._last_high_date`, two attributes removed
  from `ControllerEngine` in the v0.5.0 refactor that moved outdoor-temperature
  auto-off logic into `SeasonEngine`. Downloading diagnostics from
  Settings → Devices & Services → Heat Manager crashed with `AttributeError`
  every time. Removed the two stale keys.
- **BUG** `websocket.py` — `heat_manager/boost_start` and `heat_manager/boost_stop`
  only toggled the `boost_active_rooms` flag and never touched a single TRV, so
  the sidebar panel's Boost button had no heating effect at all — unlike
  `heat-manager-card.js`'s own client-side boost, which does call
  `climate.set_temperature`. The two boost UIs were also fully unsynced (each
  had its own idea of what "boosted" meant). `boost_start` now raises every
  NORMAL/OVERRIDE room to the boost temperature (`DEFAULT_BOOST_TEMP`, 24°C,
  new in `const.py`, or an optional `temperature` param) via the room's
  preferred write entity; `boost_stop` restores every boosted room via the
  existing `force_room_on` engine call, mirroring the card's own restore path.
- **B-CARD-PANEL** `frontend/heat-manager-card.js` — card did not fill a
  `type: panel` view correctly on landscape tablet dashboards (e.g. 7"
  Lenovo), following the same sizing pattern already proven correct in
  `secure_me_alarm_tab_card.js`. `:host` now declares `height: 100%`; the
  `ha-card`/`.card` wrapper is a `width:100%; height:100%; min-height:0;`
  column flexbox instead of plain block flow; the header and the
  Controller/Boost section-boxes get `flex-shrink: 0` so they keep their
  natural size; and the Rooms section (new `.rooms-section` class) grows
  to fill the remaining height with its `.section-body` as the scroll
  region, so the room list scrolls internally instead of overflowing the
  panel. `getCardSize()` is unchanged (irrelevant in a panel view).
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
- **Services** `boost_start` / `boost_stop` (`__init__.py`, `services.yaml`,
  `const.py`) — boost can now be triggered from automations, scripts, or a
  voice assistant, not just the sidebar panel or Lovelace card. Both share
  the exact same implementation as the WS commands via two new coordinator
  methods, `async_boost_start()` / `async_boost_stop()` (`coordinator.py`) —
  the single source of truth for "boost" going forward.
- **Boost auto-expiry** (`coordinator.py`) — boost started via the service or
  the WS command now sets `coordinator.boost_expires_at` (default
  `DEFAULT_BOOST_MINUTES` = 30 min, or an optional `duration_minutes`
  param) and a new coordinator tick step (`_async_check_boost_expiry`)
  auto-restores every boosted room once it elapses. Previously only
  `heat-manager-card.js` had a countdown, and only while its dashboard tab
  stayed open — closing it left the boosted room heated indefinitely.
  `boost_remaining_minutes` is now also included in the `heat_manager/get_state`
  WS payload for future panel/card countdown UI.
- **Config flow** `config_flow.py` + `strings.json` + `translations/{en,da}.json` —
  PID gains (`pid_enabled`, `pid_kp`, `pid_ki`, `pid_kd`, `trv_max_temp`) and
  wake/WAKING settings (`indoor_wake_sensor`, `indoor_wake_threshold`,
  `wake_setback_temp`) are now exposed in the "Season & global settings" step
  of both the initial setup wizard and the options flow. Previously these
  seven fields only existed as `const.py` defaults, reachable only by editing
  `entry.options` directly outside the UI.
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

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/kingpainter/heat-manager/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/kingpainter/heat-manager/compare/v0.6.3...v0.7.0
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
