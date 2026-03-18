# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- `coordinator.py` — `HeatManagerCoordinator` owning all engines, shared runtime state (`room_states`, `season_mode`, `outdoor_temperature`), adaptive away temperature based on outdoor conditions, and periodic tick driving all time-based logic.
- `engine/presence_engine.py` — presence-based heating logic with configurable day/night grace periods, alarm panel coordination, and actionable arrival notifications.
- `engine/window_engine.py` — per-room window detection state machine with configurable open delay, 30-minute escalation warning, and presence-aware restore on close.
- `tests/components/heat_manager/test_presence_engine.py` — 11 tests covering arrivals, departures, grace periods, alarm handling, force-room-on, and guard decorator.
- `tests/components/heat_manager/test_window_engine.py` — 12 tests including all 4 bug regression tests (B1, B2, B3, B4).

### Fixed
- Fixed B1 — entity ID typo `.binary_sensor.lukas_vindue_contact` (leading dot) prevented Lukas' window from ever appearing in window state. Entity IDs now come exclusively from the HA entity selector in config flow and are stored without transformation.
- Fixed B2 — 30-minute open-window warning was dead code in the old YAML (trigger defined, no handler). `WindowEngine.async_tick()` now sends an escalation notification after the configured threshold.
- Fixed B3 — closing a window always restored to `schedule` even when nobody was home. `_close_after_delay` now checks presence first; if nobody is home the room stays in `AWAY` state for the presence engine to handle on arrival.
- Fixed B4 — alarm `armed_away → disarmed` transition had no handler in the old YAML, leaving heating off permanently after disarm. `PresenceEngine._async_handle_alarm_change` now re-evaluates presence on disarm and restores heating if someone is home.

---

## [0.1.0] — Unreleased (foundation)

### Added
- Initial project structure and repository setup.
- `manifest.json` with `config_flow: true`, `iot_class: local_push`.
- `const.py` — single source of truth for all constants and enums (`ControllerState`, `SeasonMode`, `RoomState`, `AutoOffReason`).
- `engine/controller.py` — `ControllerEngine` with ON / PAUSE / OFF state machine, `@guarded` decorator, pause timer with auto-resume, auto-off via season and outdoor temperature, season-aware OFF fallback.
- `config_flow.py` — 4-step UI setup wizard with repeatable room and person steps. `HeatManagerOptionsFlow` for post-setup editing.
- `__init__.py` — `async_setup_entry`, `async_unload_entry`, service registration, Lovelace frontend resource registration.
- `services.yaml` — service definitions with full HA UI documentation.
- `translations/en.json` and `translations/da.json` — complete English and Danish translations.
- `strings.json` — base translation keys.
- `tests/components/heat_manager/test_controller_engine.py` — 13 unit tests covering all state transitions, guard decorator, auto-off/resume.
- `.cursorrules` — Claude/Cursor ruleset derived from HA Integration Quality Scale (Bronze–Platinum).
- `CHANGELOG.md`, `README.md`, `GIT_WORKFLOW.md`, `quality_scale.yaml`.

---

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/HEAD...HEAD
