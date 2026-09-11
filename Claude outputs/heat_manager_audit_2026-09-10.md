# Heat Manager — Backend Audit (deep dive)
**Dato:** 2026-09-10 · **Version på tidspunktet for auditten:** 0.17.2

> Fokus: udelukkende backend-Python (`custom_components/heat_manager/*.py` + `engine/*.py`, 26 filer, ~10.200 linjer). Frontend (panel.js/card.js) og tests er kun brugt til at bekræfte/afkræfte fund, ikke gennemgået i dybden. Metode: fuld manuel gennemlæsning af coordinator.py, alle 11 engines, alle platform-filer (`sensor/binary_sensor/switch/number/select/websocket/panel/diagnostics/migrations`), plus mekaniske cross-checks (alle 60 `CONF_*`-felter krydsrefereret mod deres brugssteder, AST-scan for ubrugte funktioner, scan for `except Exception` uden begrundelse, mutable default-argumenter).
>
> Sammenlignet med jeres egen audit fra 2026-09-07 (v0.16.0): **alle punkter derfra er stadig rettet** — jeg har verificeret 1.1/1.2 (døde config-kontakter), 1.5 (service-unregister ved unload), 3.1 (den ubeskyttede `float()` i PID-tick'en), 3.8 (mutable defaults), og `websocket.py`'s "Send temperatur" success-uden-effekt-bug er også stadig lukket. Det er et solidt udgangspunkt — de nye fund nedenfor er alle **nye**, opstået eller opdaget efter den audit.

---

## Hvis du kun retter 5 ting

1. **Rummets `climate_entity`-felt læses direkte 13 steder i kodebasen — inklusive selve PID-tick'en — i stedet for via den hjælpefunktion (`coordinator.get_climate_entity()`) der specifikt blev bygget for at undgå det.** Ethvert rum oprettet eller gemt igennem den nuværende TRV-UI har **ikke** dette felt på rum-niveau (kun inde i `trvs[0]`). Ramt kode inkluderer `coordinator._async_pid_tick()` selv — se punkt A nedenfor. Jeres eksisterende rum er sandsynligvis upåvirkede (migreret én gang ved v1→v2), men **næste nye rum, I opretter, får ingen PID-regulering overhovedet**, helt lydløst.
2. **Den adaptive fraværstemperatur (mild/kold, styret af `away_temp_mild`/`away_temp_cold`/`mild_threshold` i UI'et) gør intet.** `coordinator.get_away_temperature()` — den eneste funktion der bruger de tre indstillinger — kaldes ingen steder. Fraværstilstand sætter reelt bare `preset_mode: away` (Netatmo) / `hvac_mode: off` (Zigbee); de tre skydere i konfigurationsfladen er kosmetiske.
3. **Panelets "Send temperatur"-varighedsvælger (60 min / permanent) gør intet efter loggen er skrevet.** I modsætning til Boost (som fik en rigtig backend-timer i v0.8.0, se CHANGELOG) har `heat_manager/set_room_temp`'s `duration_min` ingen udløbsmekanisme noget sted i coordinator — override'n sidder fast i OVERRIDE, uanset hvad brugeren valgte, indtil den ryddes manuelt.
4. **To engines læser deres entity-konfiguration kun én gang, ved opstart — og bliver ikke opdateret af den nye "smarte reload" fra jeres eget September-fix.** `__init__.py`'s `_async_update_listener` springer nu reload over, medmindre `rooms`/`persons` ændrer sig — men `RemoteButtonEngine` (fjernbetjeningens 3 entiteter) og `PresenceEngine`s alarm-lytter bygges begge kun i deres `__init__`. Ændrer du fjernbetjening- eller alarm-entiteten via Indstillinger, har det ingen effekt før en manuel genindlæsning/genstart.
5. **`const.VERSION` er drevet af sporet igen — "0.17.0" mens `manifest.json` siger "0.17.2".** Samme klasse fejl som blev fundet og rettet 2026-09-07 (der stod dengang "0.9.0" i månedsvis) — den manuelle synkronisering er tydeligvis skrøbelig. Praktisk skade er lille lige nu (cache-busting query-strengen har også en mtime-komponent), men det er et tilbagevendende mønster værd at automatisere væk.

---

## A. Rummets flade `climate_entity`/`calibration_entity`-spejl læses direkte — 13 steder

**Rodårsag:** Siden B18 (TRV-gruppering) gemmer config-flowet kun `room["trvs"]`, aldrig et spejlfelt `room["climate_entity"]` på selve rum-dictet — bekræftet ved at læse `_room_schema()` (intet `climate_entity`-felt) og begge `async_step_room_trvs_menu`-implementeringer (config flow + options flow), som udelukkende sætter `room[CONF_TRVS]`. Den engangsmigrering (`async_migrate_entry`, v1→v2) spejler ganske vist `trvs[0]` tilbage til rum-niveau og **gemmer** det — det er derfor et rum oprettet før B18 stadig fungerer. Men intet gør det samme for et rum oprettet eller gemt igen efter B18.

`coordinator.get_climate_entity()` blev allerede bygget netop til at rette dette (se dens docstring: *"Reading the flat field directly here returned None for any room saved through that UI even once"*), og bruges korrekt af bl.a. `get_homekit_climate_entity()`, `get_write_entity()`, `get_room_trvs()`. Men følgende steder blev ikke konverteret og læser stadig det flade felt direkte:

| # | Sted | Konsekvens |
|---|------|------------|
| A.1 | `coordinator.py:1425` (`_async_pid_tick`) — `primary_id = room.get(CONF_CLIMATE_ENTITY, "")`, derefter `if not room_name or not primary_id: continue` | **PID-reguleringen springer rummet helt over, hver tick, for evigt.** Det mest alvorlige enkeltfund i denne gennemgang — det er selve varmereguleringen. |
| A.2 | `__init__.py:104` (opstarts-reachability-tjek) | Hvis *alle* rum er "moderne", er `reachable`-listen tom → `ConfigEntryNotReady` rejses permanent, integrationen loader aldrig. |
| A.3 | `__init__.py:259` (`_async_check_repair_issues`) | Rejser en vildledende RepairIssue ("climate entity '' not found") for et korrekt konfigureret rum. |
| A.4 | `engine/waste_calculator.py:127` | Rummet tælles slet ikke med i spild/besparelse — `energy_wasted_today`/`energy_saved_today` underrapporterer stille. |
| A.5 | `engine/calibration_engine.py:78,80` — både `CONF_CALIBRATION_ENTITY` og `climate_entity` | CalibrationEngine aktiverer sig aldrig for et moderne rum, selvom kalibrerings-entiteten er korrekt sat i UI'et. |
| A.6 | `binary_sensor.py:104` (`HeatingWastedSensor.is_on`) | Springer rummet over ved spild-i-åbent-vindue-detektion. |
| A.7 | `binary_sensor.py:153,187` (`CloudAvailableSensor`) | Rummet tælles ikke med i cloud-tilgængeligheds-tjekket — en død Netatmo-cloud-forbindelse for netop det rum bliver usynlig. |
| A.8 | `binary_sensor.py:286` (`MoldRiskSensor._climate_id`, fallback-kilde til rumtemperatur) | Mister sin sidste fallback for temperatur, hvis hverken `room_temp_sensor` er sat. |
| A.9 | `switch.py:69` (`RoomOverrideSwitch._climate_id`) | Skadesløs i praksis — feltet gemmes men læses aldrig andre steder i klassen (se også F.1 nedenfor). |
| A.10 | `sensor.py:100,450` — gate for `RoomCalibrationOffsetSensor` + `RoomStateSensor._climate_id` | Kalibrerings-sensoren oprettes aldrig for et moderne rum, selv med `calibration_entity` sat. |
| A.11 | `websocket.py:516` (`calibration_entity` i `ws_get_state`-payload) | Panelets konfigurationsfane viser tom kalibrerings-entity for et moderne rum. |
| A.12 | `diagnostics.py:40` | Den download-bare diagnosticsfil — værktøjet man bruger til netop at fejlsøge "hvorfor varmer rummet ikke" — viser tom `climate_entity` for det ramte rum. Ironisk nok skjuler diagnosticsen selve beviset for denne fejl. |

**Fix-forslag:** Erstat samtlige `room.get(CONF_CLIMATE_ENTITY, ...)` / `room.get("climate_entity", ...)` med `coordinator.get_climate_entity(room_name)` (og tilsvarende for `CONF_CALIBRATION_ENTITY` via en ny `get_trv_calibration_entity()`-lignende helper, eller ved at iterere `get_all_room_trvs()` direkte). Alternativt — og nok mere robust — få config-flowet til selv at skrive det flade spejl ved `room[CONF_TRVS] = ...`-tidspunktet (samme sted `migrate_room_to_trvs()` allerede gør det for læsning), så *alle* de gamle læsesteder automatisk bliver korrekte igen uden at skulle jages enkeltvis.

---

## B. Konfigurerbare indstillinger uden virkning

| # | Indstilling | Fund |
|---|---|---|
| B.1 | `away_temp_mild`, `away_temp_cold`, `mild_threshold` | `coordinator.get_away_temperature()` er den eneste kode der læser disse tre — og den kaldes **ingen steder** i hele kodebasen (bekræftet via grep across backend + frontend + tests). `presence_engine.py`s `_set_all_away()` sætter i stedet blot `preset_mode=away` (Netatmo, som selv styrer sin egen away-temperatur i Netatmo-appen) eller `hvac_mode=off` (Zigbee — lukker ventilen helt, ikke til nogen bestemt temperatur). De tre UI-felter er reelt dekoration. |
| B.2 | 30-minutters vindues-advarsel (tærskelværdi) | `window_engine.py:328`: `self.coordinator.config.get("window_warning_min", DEFAULT_WINDOW_WARNING_MIN)` — der findes **ingen** `CONF_WINDOW_WARNING_MIN`-konstant i `const.py`, og feltet optræder slet ikke i `config_flow.py`'s skemaer. Nøglen kan derfor aldrig sættes af brugeren; koden falder altid tilbage til de hardkodede 30 minutter. Selve strengnøglen er også en "magic string" i stedet for en importeret konstant, i modsætning til stort set alt andet i filen. |
| B.3 | `get_open_windows()` (`engine/window_engine.py:391`) | Implementeret og enhedstestet (`test_window_engine.py:343`), men kaldes ingen steder i produktionskoden (hverken backend, websocket-payload eller frontend). Enten en rest fra en tidligere UI-plan, eller en glemt integration — værd at afklare om den skal bruges eller fjernes. |

---

## C. Live-konfiguration der kræver manuel reload (regression fra jeres eget September-fix)

`__init__.py::_async_update_listener` blev for nylig ændret til kun at genindlæse entry'en når `rooms`/`persons` faktisk ændrer sig — en bevidst, veldokumenteret optimering (undgår at nulstille PID-integratorer/ventil-tracker ved hver lille options-ændring). Men to engines cacher stadig deres entity-konfiguration udelukkende i `__init__`, uden at være dækket af den nye rooms/persons-sammenligning:

- `engine/remote_button_engine.py::_register_listeners()` — læser `CONF_BUTTON_TEMP_UP_ENTITY`/`_DOWN_ENTITY`/`CONF_BUTTON_MODE_TOGGLE_ENTITY` én gang ved konstruktion.
- `engine/presence_engine.py::_register_listeners()` — alarm-lytteren (`self.coordinator.alarm_panel`) sættes op én gang ved konstruktion; `CONF_ALARM_PANEL` er et globalt options-felt, ikke en del af `rooms`/`persons`.

Ændrer man fjernbetjeningens knap-entiteter eller alarm-panelet via Indstillinger → Heat Manager efter opstart, sker der reelt intet, før man manuelt genindlæser integrationen eller genstarter HA — stille, uden fejlmeddelelse.

---

## D. `duration_min` på panelets manuelle temperatur er kosmetisk

`websocket.py::ws_set_room_temp` modtager `duration_min` (default 60, "permanent" ved 0) og bruger den **udelukkende** til logbeskeden ("60 min" vs. "permanent") — der findes ingen tilsvarende `*_expires_at`-mekanisme, sådan som Boost fik i v0.8.0 (`coordinator.boost_expires_at`, tjekket hver tick af `_async_check_boost_expiry()`). En bruger der vælger "override i 60 minutter" fra panelet, får en override der varer for evigt, indtil den ryddes manuelt — nøjagtig det samme problem Boost havde, før det blev rettet, men aldrig rettet her.

---

## E. `const.VERSION` driver igen fra `manifest.json`

`const.py:14`: `VERSION = "0.17.0"` — men `manifest.json` er på `0.17.2`. Kommentaren lige ovenfor (linje 8-13) beskriver eksplicit at dette blev fundet og rettet 2026-09-07 (dengang stod der "0.9.0"), fordi VERSION fodrer panelets/kortets cache-busting query-streng. Skaden er begrænset lige nu (mtime er også en del af query-strengen), men den manuelle synkroniseringsproces er beviseligt skrøbelig — overvej at læse versionen fra `manifest.json` i stedet for at duplikere den.

---

## F. Mindre fund

1. **`switch.py:69`** — `RoomOverrideSwitch._climate_id` sættes i konstruktøren men læses aldrig andre steder i klassen. Dødt attribut (og rammer samme flade-felt-bug som A, blot uden konsekvens fordi det ikke bruges).
2. **`engine/valve_protection_engine.py::async_shutdown()`** — kalder `self._task.cancel()` men afventer ikke tasken. Harmløst i praksis (HA er ved at lukke ned alligevel), men inkonsekvent med resten af kodebasens ellers meget disciplinerede task-håndtering.
3. **`engine/window_engine.py:414`** (`_notify`) — bruger strengen `"notify_service"` i stedet for den importerede `CONF_NOTIFY_SERVICE`-konstant, som filen allerede importerer og bruger andre steder (linje 189, 318, 354). Virker i dag fordi strengværdierne er identiske, men er et brud på mønsteret og en fælde ved en fremtidig omdøbning.
4. **`_async_pid_tick()`s "cloud"-gren** (`coordinator.py:1449-1477`) genbruger `primary_id`/`primary_state` (samme flade felt som A.1) selv i den del af koden der *ikke* har med `get_room_trvs()`-loopet at gøre — dvs. selve target-temperatur-udlæsningen fra Netatmo-skyens skema er også ramt, ikke kun "skip hele rummet"-gaten.

---

## Ikke undersøgt i denne omgang

Frontend (`heat-manager-panel.js`, `heat-manager-card.js`) og testsuiten (`tests/`, 29 filer) er kun brugt punktvis til at be- eller afkræfte specifikke backend-fund — ikke gennemgået selvstændigt. `config_flow.py`s fulde skema-symmetri (ud over det der er nævnt under A/B) og websocket.py's resterende kommandoer er heller ikke gennemgået linje for linje. Sig til hvis en opfølgende runde skal dække disse.
