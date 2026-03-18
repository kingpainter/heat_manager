# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Initial project structure and repository setup.
- `manifest.json` with `config_flow: true`, `iot_class: local_push`.
- `const.py` — single source of truth for all constants, enums (`ControllerState`, `SeasonMode`, `RoomState`, `AutoOffReason`), and defaults.
- `engine/controller.py` — `ControllerEngine` with ON / PAUSE / OFF state machine, `@guarded` decorator, pause timer with auto-resume, auto-off via season and outdoor temperature, season-aware OFF fallback (Winter → `schedule`, Summer → `hvac_mode: off`).
- `config_flow.py` — 4-step UI setup wizard (global settings, rooms, persons, notifications) with repeatable room and person steps. `HeatManagerOptionsFlow` for post-setup editing.
- `__init__.py` — `async_setup_entry`, `async_unload_entry`, service registration (`set_controller_state`, `pause`, `resume`, `force_room_on`), Lovelace frontend resource registration.
- `services.yaml` — service definitions with full HA UI documentation.
- `translations/en.json` and `translations/da.json` — full English and Danish translations for all config flow steps, entity names, and state values.
- `strings.json` — base translation keys.
- `tests/components/heat_manager/test_controller_engine.py` — 13 unit tests covering all state transitions, `@guarded` decorator, auto-off/resume, and season logic.
- `.cursorrules` — Claude/Cursor ruleset derived from HA Integration Quality Scale (Bronze–Platinum).
- `CHANGELOG.md` — this file.
- `README.md` — initial documentation.

---

## Version history

<!-- Releases will be linked here as they are tagged -->
<!-- Example: [0.1.0]: https://github.com/kingpainter/heat-manager/releases/tag/v0.1.0 -->

[Unreleased]: https://github.com/kingpainter/heat-manager/compare/HEAD...HEAD
