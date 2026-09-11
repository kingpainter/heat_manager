# Heat Manager — Fixes anvendt fra audit 2026-09-10

Status: **Alle fund fra `audit/heat_manager_audit_2026-09-10.md` er rettet** og skrevet til GitHub-repoet (`C:\Users\Konge\Documents\github-homeassistant-projekter\heat_manager\`), efter brugerens eksplicitte valg om at springe den kørende HA-server over denne gang.

Version bumpet: `0.17.2` → `0.18.0` (både `const.py` og `manifest.json`, synkroniseret). `CHANGELOG.md` opdateret med fuld `[0.18.0]`-sektion.

## Hvad blev rettet

**A — Flat `climate_entity`/`calibration_entity`-læsninger (13 steder)**
`coordinator.py` (PID-tick — den alvorligste: et rum kunne blive helt sprunget over af PID hver tick), `__init__.py` (×2), `diagnostics.py`, `waste_calculator.py`, `calibration_engine.py`, `binary_sensor.py` (×4), `sensor.py` (×2), `switch.py` — alle læser nu via `coordinator.get_climate_entity()` / den nye `coordinator.get_room_calibration_entity()` i stedet for det flade felt, der aldrig bliver gemt tilbage efter en gemning gennem per-TRV UI'en. `config_flow.py` synkroniserer nu også det flade spejl ved gemning (`migrate_room_to_trvs()`) som et ekstra sikkerhedsnet.

**B.1 — Døde away-temp indstillinger fjernet**
`away_temp_mild` / `away_temp_cold` / `mild_threshold` + `get_away_temperature()` er fjernet helt (bruger valgte "Fjern" frem for at koble dem til). Ingen ændring i faktisk opvarmningsadfærd — Zigbee-rum bruger stadig `hvac_mode: off`, Netatmo-rum `preset_mode: away`.

**B.2 — `CONF_WINDOW_WARNING_MIN` tilføjet**
Ny config-nøgle + felt i config_flow, så `DEFAULT_WINDOW_WARNING_MIN` (30 min) faktisk kan ændres fra UI'en.

**B.3 — `open_windows` eksponeret**
`window_engine.get_open_windows()` var implementeret men aldrig sendt til frontend — nu med i `ws_get_state()`.

**C — Remote-button og alarm-lyttere gensynkroniseres**
Nye `rebuild_listeners()` / `rebuild_alarm_listener()` på hhv. `RemoteButtonEngine` og `PresenceEngine`, kaldt fra `__init__.py`'s `_async_update_listener()` på hver options-gemning der ikke allerede trigger fuld reload.

**D — `duration_min` på manuel rum-override virker nu**
Ny `coordinator.room_override_expires_at` + `_async_check_room_override_expiry()` (samme mønster som boost-expiry), tjekket hver tick. `ws_set_room_temp` sætter nu udløbstidspunktet.

**E — Panel-version læses fra `manifest.json`**
`panel.py` importerede før `const.VERSION`, som allerede var drivet en gang. Læser nu direkte fra `manifest.json` ved runtime — den fejlklasse kan ikke opstå igen.

**F — Diverse**
Død `RoomOverrideSwitch._climate_id` fjernet. `ValveProtectionEngine.async_shutdown()` venter nu faktisk på den annullerede task. `window_engine.py` bruger `CONF_NOTIFY_SERVICE`-konstanten i stedet for magisk streng.

## Tests
`test_presence_engine.py` og `test_config_flow.py` opdateret for B.1-fjernelsen. `test_waste_calculator.py`, `test_calibration_engine.py`, `test_sensor.py` og `test_websocket.py` fik tilføjet mocks for de nye coordinator-helpers (`get_climate_entity`, `get_room_calibration_entity`), så de matcher den nye kaldevej i stedet for det flade felt.

## Verifikation
`python3 -m py_compile` på alle ændrede filer (ren). `ruff check --select=F,E9` (pyflakes + syntaksfejl) på alle ændrede filer — ingen fund. **Kunne ikke køre selve pytest-suiten** (samme miljøbegrænsning som under selve audit'en — `homeassistant`-pakken kan ikke installeres i dette sandbox) — al verifikation er derfor statisk + manuel krydstjek af hvert testsites forventninger mod den nye kode.

## Ikke rettet (bevidst fravalgt)
Frontend (`heat-manager-panel.js`) viser stadig to "Away temp"-felter i config-tabellen, som nu altid vil vise "–" siden de underliggende værdier er fjernet fra backend. Dette var uden for scope for backend-audit'en og blev ikke rettet — kosmetisk, ingen funktionel fejl.
