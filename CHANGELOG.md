# Changelog

All notable changes to Heat Manager are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [0.57.2] — 2026-09-19

**Vigtig proces-rettelse:** `panel.py` registrerer panelets JavaScript-URL
(med cache-busting-parametrene `?v=<version>&m=<filens ændringstidspunkt>`)
én gang pr. HA-proces, ved integrationens opstart — `async_unregister_
panel()` bekræfter selv eksplicit "panel is process-level, skipping
removal". En almindelig "Genindlæs integration" nulstiller IKKE dette, og
ingen mængde browser-hård-genindlæsning kan hente en ny fil, så længe HA
selv fortsat fortæller browseren at hente den GAMLE URL. **Tidligere
beskeder i denne log, der sagde "kun browser-genindlæsning, ingen
HA-genstart nødvendig" for rene frontend-ændringer (v0.55.0, v0.57.0,
v0.57.1), var forkerte for dette specifikke panel** — en fuld HA-genstart
har hele tiden været nødvendig, også for kun-frontend-ændringer. Det
forklarer, hvorfor både v0.57.1's fold-tilstands-rettelse og de
nye sektionsbeskrivelser aldrig nåede frem til browseren.

### Fixed
- **`frontend/heat-manager-panel.js`**: Controller-boksens eget status-badge
  ("Varme aktiv"/"Pause"/"Slukket") delte utilsigtet CSS-klassen
  `.section-box-badge` med Konfiguration-fanens egne sektions-badges
  (Alarmtavle, PID, Vejrkompensation, osv.). `_patchControllerHero()`s
  baggrunds-opdatering — som kører på HVER poll, uanset hvilken fane der
  vises — brugte et uafgrænset `querySelector(".section-box-badge")`, der
  ramte den FØRSTE matchende el i den AKTUELT viste fane. Står man på
  Konfiguration, overskrev det Alarmtavlens "Konfigureret"/"Ikke sat"-badge
  med controller-titlen ("Varme aktiv") i stedet. Rettet med en dedikeret
  `.ctrl-status-badge`-klasse, kun på Controller-boksens eget badge.

Verificeret: `node --check` på den ændrede frontend-fil.

## [0.57.1] — 2026-09-19

Fire relaterede Konfiguration-fane-forbedringer, udløst af rapporten om at
Dør-varmedeling "stadig ikke kunne tændes" — som viste sig at være en
regression fra v0.57.0's sammenfold-som-standard-ændring, ikke en ny
backend-fejl.

### Fixed
- **Kritisk regression: enhver felt-ændring foldede ALLE sektioner sammen
  igen.** v0.57.0 hardkodede `collapsed` ind i selve HTML-skabelonen, så
  enhver `_scheduleRender()` (som hvert `toggle-field`/`Gem`-klik udløser)
  nulstillede samtlige 14 sektioner til lukket — den sektion man lige havde
  åbnet for at trykke "Slå til" i, klappede sig selv sammen i samme
  øjeblik. Det så ud som om klikket ikke virkede (Dør-varmedeling-rapporten),
  fordi hele sektionen — badge, knap, det hele — forsvandt igen med det
  samme. Rettet: fold-tilstand ligger nu i `this._expandedConfigSections`
  (en `Set`, nøglet på et stabilt `data-section-id` pr. sektion) i stedet
  for kun i en DOM-klasse en genopbygning altid overskriver.

### Added
- **Altid-synlig kort beskrivelse i hver sektions-header** (Ønske #3):
  hver af de 14 sektioner har nu en én-linjes beskrivelse under titlen,
  inde i selve headeren — derfor aldrig skjult af sammenfoldning, modsat
  den længere forklarende tekst i sektionens krop.

### Changed
- Med konsekvent header-struktur (titel + kort beskrivelse + evt. badge)
  på alle 14 sektioner har de nu ensartet højde når sammenfoldet, hvilket
  giver den efterspurgte størrelses-harmoni (Ønske #4) i to-kolonne-gridet
  uden at ændre selve rækkefølgen — parringen (Alarmtavle+Manuel TRV,
  PID+Vejrkompensation, Solindfald+Dør-varmedeling, osv.) var allerede
  fornuftig, det var forskellen i UDFOLDET højde der skabte disharmonien.

Verificeret: `node --check` på den ændrede frontend-fil, alle 14
`data-section-id`-værdier bekræftet unikke.

## [0.57.0] — 2026-09-19

Konfiguration-fanen fylder mindre: to-kolonne-layout på bred skærm, og alle
13 sektioner er nu sammenfoldet som standard i stedet for udfoldet.

### Changed
- **`frontend/heat-manager-panel.js`**: `_configTabHTML()`s output er nu
  pakket i et `.config-grid`-wrapper-element (`display:grid;
  grid-template-columns:1fr 1fr`, med `@media (max-width:760px)`-fallback
  til én kolonne på mobil). Kun Konfiguration-fanen — Oversigt/Rum/
  Historik-fanernes egne section-box'e står udenfor dette wrapper-element
  og er uændrede.
- Alle 13 sektioner i Konfiguration (Alarmtavle t/m Rum &amp;
  klimaentiteter) har nu `collapsed`-klassen fra første render, i stedet
  for at starte udfoldet — samme klap-mekanisme fra Trin 5
  (2026-09-14), blot med modsat standardtilstand. Klik på en
  sektions-header for at folde den ud, som før.

Verificeret: `node --check` på den ændrede frontend-fil.

## [0.56.1] — 2026-09-19 (hotfix)

Min egen fejl fra v0.50.0: `door_heat_share_enabled` blev tilføjet til
`_BOOL_CONFIG_FIELD_DEFAULTS`, men aldrig til selve voluptuous-skemaet der
validerer `ws_update_config`-beskeder — de tre numeriske felter
(`door_heat_share_min_neighbor_power` osv.) kom med, men ikke selve
til/fra-kontakten. Konsekvens: forsøg på at gemme "Dør-varmedeling
aktiveret" fra Konfiguration fejlede med "not a valid option" og gemte
aldrig værdien.

### Fixed
- **`websocket.py`**: tilføjet den manglende `vol.Optional(CONF_DOOR_HEAT_
  SHARE_ENABLED): bool` til skemaet. Krydstjekket samtidig ALLE øvrige
  bool- og numeriske config-felter systematisk mod skemaet — dette var det
  eneste hul.

Verificeret: `mypy --strict` rent.

## [0.56.0] — 2026-09-16

To bekræftede løse ender fra en gennemgang af tidligere revisioners
UI/UX-fund (de fleste andre punkter på den gamle liste viste sig allerede
rettet i mellemliggende sessioner — se `_ctrlTitle`/toast-systemet/
batteri-farver/aria-live, som alle allerede var på plads).

### Added
- **panel.js: sæson kan nu ændres direkte fra Oversigt-fanens
  Controller-boks** — "Sæson"-chippen er gået fra ren tekst til en
  `<select>` (Auto/Vinter/Forår/Sommer/Efterår), der kalder HA's indbyggede
  `select.select_option`-service direkte på den eksisterende
  `select.<entry>_season_mode`-entity — ingen backendændring nødvendig,
  samme handling som `select.py`s egen `SeasonModeSelect.async_select_
  option()` allerede udfører. Før krævede en manuel sæson-tvang, at man gik
  uden om det custom panel og ind på HA's egen entity-side.
  `_patchControllerHero()` er samtidig omskrevet fra skør
  positions-indeksering (`querySelectorAll("strong")[n]`) til eksplicitte
  per-chip-klasser, så en fremtidig ny/fjernet chip ikke igen kan forskyde
  alle efterfølgende chips ét indeks.

### Fixed
- **card.js: sprogblanding rettet.** `_hmCtrlLabel()` viste "On/Pause/Off"
  på engelsk for præcis samme tre tilstande som panel.js's `_ctrlTitle()`
  altid har vist korrekt på dansk ("Varme aktiv/Pause/Slukket"). Eneste
  resterende engelsk-rest i mobilkortet.

**Bevidst ikke ændret:** mobilkortets sæson-visning forbliver ren tekst
(samme minimale designfilosofi som resten af kortets header) — den
interaktive kontrol lever i panelet, jeres primære kontrolflade.

Verificeret: `node --check` på begge ændrede frontend-filer.

## [0.55.0] — 2026-09-16

Fundet rodårsagen til Flemmings rapport: "den nye dør-logik virker ikke"
(altandøren stoppede ikke varmen efter at være omregistreret fra vindue til
dør). Selve logikken fra v0.49.0 var korrekt — problemet var, at de to nye
felter (`door_styled_sensors`, `heated_door_sensors`) blev tilføjet til
config-skemaet uden NOGEN oversat label eller beskrivelse i `strings.json`/
`translations/da.json`. I UI'en så de derfor ud som rå, kryptiske
feltnavne uden nogen forklaring på forskellen — nem at forveksle med
hinanden, hvilket er præcis det der skete: en sensor sat i
`heated_door_sensors` (ingen varmeafbrydelse overhovedet, med vilje) i
stedet for `door_styled_sensors` (kosmetisk delmængde af de eksisterende
vinduessensorer, samme fulde adfærd).

### Fixed
- **`strings.json`/`translations/da.json`**: tilføjet manglende labels og
  data_description-tekster for `door_styled_sensors` ("Vis som dør i
  stedet for vindue (kosmetisk)") og `heated_door_sensors` ("Døre til
  opvarmet område (ingen varmeafbrydelse)") på alle tre steder, felterne
  optræder (opsætningsflowets `room`-trin samt options-flowets `room_add`/
  `room_edit`-trin). Beskrivelserne navngiver eksplicit begge lister over
  for hinanden og advarer direkte mod at forveksle dem ("En sensor skal
  OGSÅ vælges i Vindue-/dørsensorer, for at dette har nogen effekt — kun
  at vælge den her gør ingenting" / "Tilføj ikke en sensor her I STEDET
  FOR...").

Ingen kodeændring — selve dør/vindue-logikken fra v0.49.0 er stadig
korrekt og uændret. Ren tekst-/oversættelsesfix.

## [0.54.0] — 2026-09-16

Nyt "Trv setpoint"-felt i Rum-detaljer — svar på "hvad er hvad"-forvirringen
mellem de fire+ temperaturtal i panelet. Der fandtes allerede en (i)-tekst
der ADVAREDE om at Target Temp ikke nødvendigvis er det, der sendes til
TRV'en — men det faktiske tal blev aldrig vist noget sted.

### Added
- **`websocket.py`**: nyt `trv_setpoint`-felt i rum-payloaden —
  `coordinator.last_expected_setpoint[room_name]`, det setpoint PID'en
  rent faktisk beregnede og sendte til TRV'en i sidste aktive cyklus
  (efter effekt→setpoint-mapping OG setpoint-margin-loftet fra
  overshoot-fixet). Gated på `room_state == NORMAL`: `last_expected_
  setpoint` ryddes aldrig efter skrivning (`sync_engine.py` er afhængig af
  det), så uden denne gæring ville et rum i AWAY/WINDOW_OPEN/OVERRIDE vise
  en forældet værdi som om den var live.
- **Panelet (Rum-detaljer)**: nyt femte felt "Trv setpoint" i stat-rækken,
  ved siden af Rum temp/Target Temp/Trv temp/Trv batt, med egen
  (i)-forklaring der præcist beskriver forskellen til Target Temp.

Dermed er alle fire temperaturtal i panelet nu entydigt forklaret og
synlige side om side: **Rum temp** (faktisk temperatur, bedste kilde),
**Target Temp** (Heat Managers mål), **Trv setpoint** (det TRV'en reelt
bliver bedt om lige nu), **Trv temp** (TRV'ens egen, ofte for varme,
måling).

Verificeret: `websocket.py` + hele det tidligere verificerede
punkt-1(B)-sæt (22 filer i alt) består `mypy --strict` rent; panel.js's
JavaScript-syntaks bekræftet med `node --check`.

## [0.53.0] — 2026-09-16

Deep-dive audit, del 3 (sidste): platform-filerne (`switch.py`, `number.py`,
`select.py`, `binary_sensor.py`, `sensor.py`, `websocket.py`, `__init__.py`).
Fandt én yderligere forekomst af samme fejlklasse.

### Fixed
- **`websocket.py` (`ws_set_room_temp`)** — panelets manuelle TRV-kontrol
  (både enkelt-rum-slideren og "Send til alle"-knappen). Begge grene
  (gendan til schedule / sæt temperatur) kaldte
  `hass.services.async_call("climate", ...)` direkte for hver TRV, uden
  lås. Da "Send til alle" kalder denne WS-kommando én gang pr. rum i
  rækkefølge, blev alle TRV'er i det rum stadig ramt uden pacing inden for
  hvert enkelt kald. Rettet til `async_call_climate_service()` med
  pr.-TRV `trv_needs_cloud_delay()`.
- **Tegn-korruption**: ryddet op i tre steder i `websocket.py`, hvor en
  tidligere redigering havde efterladt den litterale tekst `\u2014` i
  stedet for en rigtig tankestreg i kommentarer — kosmetisk, ingen
  funktionel betydning.

**Ingen fund** i `switch.py`, `number.py`, `select.py`, `binary_sensor.py`,
`sensor.py` eller `__init__.py` — alle skrive-handlinger deri var enten
allerede korrekt delegeret til `coordinator`'s (nu rettede) metoder, eller
rene, ikke-Netatmo-relaterede kald (notify/HA-services).

**Samlet status for hele deep-dive-revisionen (runde 1-3):** 9 forekomster
af samme grundlæggende fejlklasse fundet og rettet på tværs af 12
engine-filer, `coordinator.py`, og `websocket.py` — hvert eneste sted i
integrationen, der skriver til en "climate"-entity, går nu igennem den
delte Netatmo-lås/pacing. Plus én separat tidszone-fejl
(`presence_engine.py`).

Verificeret: alle 22 filer i det verificerede sæt består `mypy --strict`
rent.

## [0.52.0] — 2026-09-16

Deep-dive audit, del 2: `coordinator.py` selv (2670+ linjer, den mest
centrale fil). Fandt tre yderligere forekomster af samme fejlklasse som
runde 1's engine-audit — heraf én i selve PID-tick'et, formentlig den
vigtigste enkeltrettelse i hele revisionen, da den kører hvert 60. sekund
for hvert rum, ikke kun ved lejlighedsvise brugerhandlinger.

### Fixed
- **`_async_pid_tick()`'s eget setpoint-skriveloop** — højeste prioritet:
  brugte `hass.services.async_call("climate", ...)` direkte for HVER
  TRV's setpoint-opdatering, hver tick. For et rum hvor den primære TRV har
  en nåelig HomeKit-entity er det harmløst (allerede lokalt) — men i et
  multi-TRV-rum (B18-gruppering), hvor en SEKUNDÆR TRV ikke har sin egen
  HomeKit-entity, eller for et Netatmo-rum konfigureret helt uden HomeKit,
  går skrivningen direkte til Netatmo-cloud'en, uden lås, hver gang
  setpointet ændrer sig — potentielt hvert 60. sekund. Rettet til at bruge
  `async_call_climate_service()` med `trv_needs_cloud_delay()` pr. TRV.
- **`async_boost_start()`** — samme mangel: Boost-knappen (formentlig den
  mest brugte enkeltfunktion i panelet) rammer alle boost-klare rums TRV'er
  i én arbejdsgang uden lås. Omskrevet til at iterere TRV'er direkte (i
  stedet for den flade write-entity-liste) med korrekt pr.-TRV-forsinkelse.
- **`async_set_room_override()`** — delt af override-kontakten (ét rum) OG
  fjernbetjeningens tilstands-knap (alle kvalificerende rum på én gang,
  jf. modulets egen dokumentation) — samme rettelse.

Gennemgået og bekræftet fri for fejl: `get_room_target_temp()`,
`get_all_room_trvs()`/`get_room_trvs()` (TRV-cache/gruppe-toggle-logikken),
`get_room_current_temp()`, `get_room_blocking_sources()`, og
`_async_update_data()`s tick-orkestrering.

Verificeret: `coordinator.py` + hele det tidligere verificerede
punkt-1(B)-sæt (22 filer i alt) består `mypy --strict` rent.

## [0.51.0] — 2026-09-16

Deep-dive audit af alle 12 engine-filer for reelle logikfejl (ikke typing,
det blev dækket af punkt 1). Fandt og rettede fire forekomster af samme
fejlklasse plus én separat tidszone-fejl. Ingen af de øvrige otte
engine-filer (`calibration_engine.py`, `controller.py`, `door_engine.py`,
`pid_controller.py`, `schedule_engine.py`, `season_engine.py`,
`valve_protection_engine.py`, `window_engine.py`) gav anledning til fund.

### Fixed
- **Fire steder omgik `coordinator.async_call_climate_service()`s delte
  Netatmo-lås/pacing** (samme mekanisme der allerede forhindrer 429-fejl i
  `controller.py`, `presence_engine.py` og `window_engine.py`) ved at kalde
  `hass.services.async_call("climate", ...)` direkte:
  - **`remote_button_engine.py`** (`_async_adjust_all_rooms`) — mest
    kritisk: en enkelt fjernbetjenings-tryk rammer *alle* konfigurerede
    rum i én arbejdsgang, uden nogen lås eller forsinkelse mellem kaldene.
    Omskrevet til at iterere rummets TRV'er direkte (i stedet for den
    flade write-entity-liste) så hver skrivning kan få sin egen
    `trv_needs_cloud_delay()`-afgørelse.
  - **`preheat_engine.py`** (`_start_preheat`) — en forvarmnings-sweep
    rører alle AWAY-rum i hurtig rækkefølge, samme byrdemønster som
    låsen er bygget til at forhindre.
  - **`sync_engine.py`** (`_async_lock_revert`) — kun relevant for rum med
    `sync_mode: lock` (opt-in, formentlig sjældent brugt), men samme
    grundlæggende hul.
  Alle tre rettet til at bruge `async_call_climate_service()` med korrekt
  per-TRV `trv_needs_cloud_delay()`-afgørelse, samme mønster som
  `controller.py`s OFF-fallback og `valve_protection_engine.py` allerede
  brugte korrekt.
- **`presence_engine.py`** (`_grace_period_minutes`): brugte
  `utcnow().hour` til at afgøre dag/nat-grace-periode, men
  `CONF_NIGHT_START_HOUR`/`CONF_NIGHT_END_HOUR` er konfigureret som LOKALE
  vægur-timer — samme felter som `coordinator.is_night_setback_active()`
  allerede korrekt sammenligner med `homeassistant.util.dt.now()`. Med
  Danmarks UTC+1/+2-forskydning betød det, at grace-periodens dag/nat-
  skifte reelt skete 1-2 timer forskudt fra det konfigurerede tidspunkt.
  Rettet til samme `now()`-mønster.

Verificeret: alle 4 ændrede filer + hele det tidligere verificerede
punkt-1(B)-sæt (22 filer i alt) består `mypy --strict` rent.

## [0.50.0] — 2026-09-16

Punkt 8 (gruppe C) — dør-varmedeling: en åben indendørs dør til et varmere,
aktivt opvarmende naborum reducerer nu PID-effekten i det koldere rum,
i stedet for at bruge et rum-par-baseret "niveau C"-design der ville have
sænket rummets eget mål midlertidigt. Den oprindelige model rejste et
uåbnet ejerskabsspørgsmål (hvem "ejer" et rums mål når en dør midlertidigt
har ændret det, og hvad sker der når døren lukkes) — den nye model
sidestepper det helt ved aldrig at røre `comfort_temp`/`target_temp`
overhovedet, samme mønster som vejrkompensation (punkt 7's forgænger) og
solindfald (punkt 7) allerede bruger til at justere PID-effekten uden at
ændre selve målet.

### Added
- **`CONF_DOOR_HEAT_SHARE_ENABLED`** (`const.py`, `config_flow.py`,
  `coordinator.py`, `websocket.py`, panel): ny global sektion
  "Dør-varmedeling" i Konfiguration. **Off som standard** — ingen
  adfærdsændring for nogen installation før du selv slår den til. Fire
  justerbare tærskler:
  - `door_heat_share_min_neighbor_power` (standard **50%**, som aftalt) —
    naborummets egen PID-effekt skal være mindst dette, før dets varme
    tæller som reelt leveret lige nu (ikke bare "naboen er varmere fra
    tidligere").
  - `door_heat_share_min_temp_diff` (standard 1,5°C) — en reel
    temperaturgradient skal være til stede, før noget meningsfuldt
    strømmer gennem døråbningen.
  - `door_heat_share_weight` og `door_heat_share_max_reduction` (loft) —
    samme skaleringsmønster som solindfalds tilsvarende felter.
- **`coordinator._door_heat_share_reduction()`**: ren funktion (samme
  "aldrig øge, kun reducere"-form som `_solar_gain_reduction()`), anvendt
  i `_async_pid_tick()` lige efter solindfald. **`comfort_temp` og
  `target_temp` røres aldrig** — kun den effekt PID'en beder TRV'en om
  lige nu, hvilket også betyder ingenting at rydde op i, når døren lukkes
  igen; reduktionen stopper simpelthen ved næste tick.
- **`coordinator.get_door_heat_share_inputs()`**: finder, blandt et rums
  åbne indendørs døre, den nabo der bedst kvalificerer (højest PID-effekt)
  og returnerer dens effekt + temperaturforskel. Et rum med flere åbne
  døre bruger bevidst kun sin bedste nabo, ikke summen af alle, for at
  undgå overdreven reduktion.

### Fixed
- **`config_flow.py`**: ryddet op i en eksisterende dobbelt-import af
  `CONF_DOOR_STYLED_SENSORS`/`CONF_HEATED_DOOR_SENSORS` fra sidste
  sessions "vindue vs. dør"-arbejde (v0.49.0) — harmløst ved runtime
  (Python tillader det), men ryddet op for konsistens.

Verificeret: alle 4 ændrede filer + hele det tidligere verificerede
punkt-1(B)-sæt (22 filer i alt) består `mypy --strict` rent; skemaet
verificeret til rent faktisk at bygge (tomt og udfyldt) i et isoleret
testmiljø — samme test der fangede gårsdagens `NameError`-fejl før
deploy denne gang. panel.js's JavaScript-syntaks bekræftet med
`node --check`.

## [0.49.0] — 2026-09-15/16

"Vindue vs dør": Flemmings fordør blev vist/logget som et "vindue" i systemet
— misvisende, og udløste desuden fulde vindues-advarsler ved almindelig
ind-/udgang. To uafhængige akser adskilt: (1) label/ikon (vindue vs. dør) og
(2) reel adfærd (koldt udenfor vs. varmt/lukket bufferområde). Efter
brugerens eget forslag: akse 1+2 (koldt udenfor) forbliver éN liste
(`CONF_WINDOW_SENSORS`, uændret adfærd) med kun et kosmetisk
label-overlay; "varmt område"-døre (fordør til opvarmet opgang) får sin
egen, separate liste uden nogen grace/sluk/advarsel-logik overhovedet.

### Added
- **`CONF_DOOR_STYLED_SENSORS`** (`const.py`, `config_flow.py`): valgfri
  delmængde af en rums `CONF_WINDOW_SENSORS` der skal vises/logges som
  "Dør" i stedet for "Vindue" — rent kosmetisk, identisk grace/sluk-temp/
  30-min-advarsel-adfærd, matcher f.eks. en altandør (samme reelle
  varmetab som et vindue).
- **`CONF_HEATED_DOOR_SENSORS`** (`const.py`, `config_flow.py`,
  `door_engine.py`, `binary_sensor.py`, `coordinator.py`, `websocket.py`,
  panel): helt separat liste — døre til et opvarmet/lukket bufferområde
  (Flemmings fordør til opgangen). Ingen grace-periode, ingen sluk-temp,
  ingen 30-min-advarsel — kun synlighed + hændelseslog, håndteret af
  `door_engine.py` med samme genstart-sikre mønster som de interne døre.
  Nye `coordinator.get_room_heated_doors()`/`is_room_heated_door_open()`/
  `get_room_door_styled_sensors()`.

### Changed
- **`window_engine.py`**: alle 6 log-/notifikationssteder (åbn/luk/30-min-
  advarsel) viser nu dynamisk "Door"/"Window" ud fra
  `CONF_DOOR_STYLED_SENSORS` — selve reguleringen (grace, sluk-temp,
  `RoomState.WINDOW_OPEN`, event_type til historik-filtrering) er 100%
  uændret, kun den menneskelæselige tekst.
- **`binary_sensor.py`**: `RawWindowContactMirror` viser korrekt
  ikon/navn (Dør/Vindue) pr. sensor; ny `HeatedDoorContactMirror`-klasse
  for de nye "varmt område"-døre.
- **Panelet**: Rum-detaljer viser nu "🚪 Yderdør Åben/Lukket" som en
  separat linje fra den eksisterende interne-dør-status, kun for rum med
  mindst én `CONF_HEATED_DOOR_SENSORS` konfigureret.

Verificeret: alle 7 ændrede backend-filer + hele det tidligere
verificerede punkt-1(B)-sæt (22 filer i alt) består `mypy --strict`
rent; panel.js's JavaScript-syntaks bekræftet med `node --check`.

## [0.48.0] — 2026-09-15

Restart-safety hardening, runde 2 — udløst af opdagelsen af, at punkt 5's
udetemp-regression var 100% in-memory og blev nulstillet ved HVER HA-genstart
(og der har været 15+ genstarter blot under denne uges udviklingsarbejde).
Brugerens eget krav: "ikke kun dette emne men alt vigtig data". Følger det
eksisterende `entry.options`-snapshot-mønster fra 2026-09-13's event-log/
override-hårdføring uændret — ingen ny persisterings-mekanisme introduceret.

### Fixed
- **`engine/calibration_engine.py`**: punkt 5's udetemp-regression
  (`_heatup_mean_x/y/xy/xx`, `_heatup_sample_count`) og
  kalibrerings-offset-writerens `_last_written` overlever nu en HA-genstart.
  Gemmes én gang dagligt (samme kadence som event-loggen) plus ved
  nedlukning — aldrig pr. tick, da regressionen kun flytter sig lidt pr.
  prøve. Bevidst IKKE persisteret: `_heatup_anomaly_streak` og
  `_heatup_baseline_*` — kortlivet bogføring for den aktuelle
  opvarmningscyklus, sikkert at nulstille.
- **`engine/controller.py`**: hele hus-tilstanden (Tænd/Pause/Sluk,
  `pause_until`, `auto_off_reason`) overlever nu en genstart — en manuel
  Pause eller Sluk gik før stille tilbage til Tænd ved næste genstart,
  hvilket kunne genoptage varmen præcis når brugeren bevidst havde slået
  den fra. Gemmes på HVER tilstandsændring (billigt — kun bruger-/
  sæson-udløst, aldrig pr. tick). En gemt Pause hvis udløbstid allerede er
  passeret, mens HA var nede, genoprettes bevidst IKKE — samme "allerede
  udløbet"-regel som `_restore_override_snapshot()` allerede brugte.
- **`engine/season_engine.py`**: den flerdages tæller til auto-off ved
  mildt vejr (`_days_above`) overlevede før ikke en genstart — en
  installation 4 dage inde i en 5-dages mild-vejrs-stræk mistede
  fremskridtet og skulle starte forfra. Samme daglig+nedlukning-kadence som
  kalibreringen ovenfor.
- **`coordinator.py`**: `room_group_enabled` (per-rum "hold TRV'er
  grupperet"-toggle) overlever nu en genstart — et rum hvis sekundære
  TRV'er var bevidst frigivet til manuel kontrol blev før stille grupperet
  igen ved næste genstart. Gemmes med det samme ved hvert toggle.

## [0.47.0] — 2026-09-15

Punkt 1(B) FULDFØRT: sidste bid af strict typing (runde 3) — alle 7
resterende platform-filer (`switch.py`, `sensor.py`, `binary_sensor.py`,
`select.py`, `number.py`, `websocket.py`, `config_flow.py`). Sammen med
runde 1 (`engine/`, v0.44.0) og runde 2 (`coordinator.py`, v0.46.0) er nu
HVER første-parts .py-fil i integrationen, undtaget kun `__init__.py`,
`diagnostics.py`, `migrations.py` og `panel.py` (aldrig i scope — små,
lavrisiko glue-filer), verificeret `mypy --strict`-ren.

### Fixed
- **Strukturel rodfejl fundet og rettet i alle fire entity-platform-filer**:
  hver entity-klasse arvede fra en utype-parameteriseret `CoordinatorEntity`,
  hvilket gjorde `self.coordinator` til `Any` overalt — IKKE løst af blot
  at parameterisere `CoordinatorEntity[HeatManagerCoordinator]`, fordi
  `homeassistant-stubs`' `BaseCoordinatorEntity` selv erklærer
  `coordinator: Incomplete` på klasse-niveau, hvilket overskygger den
  generiske TypeVar-baserede inferens. Løst med en eksplicit re-annotering
  (`self.coordinator: HeatManagerCoordinator = coordinator`) i hver klasses
  `__init__`, umiddelbart efter `super().__init__(coordinator)` — verificeret
  med et minimalt mypy-repro før det blev anvendt bredt. Ren typing-fix,
  ingen adfærdsændring.
- **`websocket.py`/`coordinator.py`-mønster genkendt igen**: genbrug af et
  løkkevariabelnavn (`default`) i to separate `for`-løkker i
  `ws_update_config()` låste mypy's typeinferens forkert fast — omdøbt til
  `numeric_default` i den anden løkke, samme mønster som gårsdagens
  `controller_off_pid`/`dormant_pid`-fix i `coordinator.py`.
- **~50 mekaniske annoteringsfejl rettet** på tværs af de 7 filer: utypede
  `dict`/`list[dict]`/`frozenset` (nu `dict[str, Any]` osv.), `**kwargs`
  uden type i `switch.py`'s `async_turn_on`/`async_turn_off` (plus et
  forkert `# type: ignore[override]`, som reelt skulle have været
  `no-untyped-def`), samt et par `description_placeholders`-dicts der fik
  en `str | None`-værdi hvor HA's egen type kræver `str` (nu `or ""`).

### Added
- **`pyproject.toml`**: `[[tool.mypy.overrides]]` udvidet til at dække alle
  7 platform-filer, med samme `strict = true`. Dokumenterer begge
  strukturelle fælder ovenfor direkte i kommentaren, så de ikke skal
  genopdages næste gang overridet fejler efter en HA-/stub-opdatering.
  Verificeret ved rent faktisk at køre `mypy --config-file pyproject.toml`
  mod alle 21 filer på én gang.

## [0.46.0] — 2026-09-15

Første bid af punkt 1(B) (strict typing, resten af kodebasen): `coordinator.py`
tilføjet til `mypy --strict`-settet fra v0.44.0 (som dækkede `engine/`).
Resterende platform-filer (`sensor.py`, `binary_sensor.py`, `number.py`,
`select.py`, `config_flow.py`, `websocket.py`) er stadig ikke dækket — tages
som senere bidder.

### Fixed
- **13 `mypy --strict`-fejl rettet i `coordinator.py`**:
  - `_weather_compensation_feedforward()`/`_solar_gain_reduction()`: `config`-
    parameteren var en utypet `dict`, og `config.get(...)`-kaldene returnerede
    `Any` ind i funktioner der lover `float` retur — nu `dict[str, Any]` plus
    eksplicitte `float(...)`-casts på hvert opslået tal.
  - `rooms`/`persons`/`doors`-properties og `get_door_other_room()`: samme
    mønster — `self.config.get(...)` returnerer `Any` fra en `dict[str, Any]`,
    tilføjet eksplicitte `cast()`/`str()` på returværdien.
  - `global_device_info()`: `entry_type="service"` (en rå streng med et
    overset `# type: ignore`) erstattet med den rigtige
    `DeviceEntryType.SERVICE`-enum — en reel rettelse, ikke kun en
    typeannotation.
  - `room_device_info()`: `via_device_id`-feltet er ukendt for den lokale
    `homeassistant-stubs`-pakke (formentlig en stub/runtime-versionsforskel,
    ikke en reel fejl) — dokumenteret `# type: ignore[typeddict-unknown-key]`
    med forklaring, adfærd uændret.
  - `_async_pid_tick()`: to tidlige "nulstil alle PID'er"-løkker genbrugte
    løkkevariablen `pid` (samme navn som den senere per-rum `pid: PidController
    | None`), hvilket fik mypy til at låse variablens type forkert fast —
    omdøbt til `controller_off_pid`/`dormant_pid`, ingen adfærdsændring.
- **`pyproject.toml`**: `[[tool.mypy.overrides]]` for
  `custom_components.heat_manager.coordinator` tilføjet med `strict = true`,
  ved siden af `engine.*`-overridet fra v0.44.0. Verificeret ved rent faktisk
  at køre `mypy --config-file pyproject.toml` mod begge — 0 fejl i alle 14
  filer.

## [0.45.0] — 2026-09-15

Overshoot-undersøgelse: rum med 21°C mål holdt sig konsekvent på 22-25°C.
Rodfundet: `PidController.power_to_setpoint()` sender straks `trv_max`
(24°C i brugerens config) ved 100% PID-effekt — og Kp=0,5 mætter effekten
allerede ved ≈ 2°C fejl, længe før rummet reelt er tæt på sit mål. Kombineret
med fjernvarme/TRV-termisk træghed forårsagede det gentaget overskydning.
Alle 7 rum bekræftet allerede at bruge en dedikeret Indeklima
rumtemperatur-sensor (`room_temp_sensor`) — sensorpræcision var IKKE rodfundet.

### Added
- **Ny `CONF_PID_SETPOINT_MARGIN`** (`const.py`, `coordinator.py`,
  `config_flow.py`, `websocket.py`, `heat-manager-panel.js`): caps det
  faktiske TRV-setpoint ved `target_temp + margin` (standard 2,0°C) —
  relativt til HVERT rums eget mål, ikke det globale `trv_max`. Fuld
  PID-effekt driver stadig TRV'en hårdt mens rummet reelt er langt fra målet,
  men rammer nu et kontrolleret, indstilleligt loft i stedet for at hoppe
  direkte til `trv_max`, når effekten mætter tidligt. `trv_max` er stadig
  den absolutte hardware-grænse; margin-loftet lægges oven i, i
  `_async_pid_tick()` lige efter `power_to_setpoint()`. Redigerbart fra
  Konfiguration → PID-regulator, med samme live-gem-mønster som Kp/Ki/Kd.
  Standardværdien (2°C) er bevidst rummelig — sænk den gradvist når
  effekten er bekræftet i praksis.

## [0.44.0] — 2026-09-14/15

Implementerer punkt 1 (gruppe C), niveau "C" af den prioriterede
implementeringsplan: `mypy --strict` på hele `engine/`-laget (de 12
motor-filer — PID, kalibrering, vindue, dør, sync, schedule, sæson,
tilstedeværelse, preheat, controller, fjernbetjening,
ventilbeskyttelse). `coordinator.py` og platform-filerne
(sensor/binary_sensor/number/select/config_flow/websocket) er bevidst
**ikke** dækket endnu — det er niveau "B", som tages senere i mindre bider.

### Added
- **`pyproject.toml`**: ny `[tool.mypy]`-sektion + `[[tool.mypy.overrides]]`
  scoped til `custom_components.heat_manager.engine.*` med `strict = true`.
  Kan køres med `mypy -p custom_components.heat_manager.engine` (eller
  tilføjes CI). `waste_calculator.py` er eksplicit undtaget
  (`ignore_errors = true`) — den er afkoblet død kode siden "Energi i
  dag"-fjernelsen og ikke værd at type-annotere. En separat override for
  `yaml`-modulet gør tjekket uafhængigt af, om `types-PyYAML` er
  installeret lokalt.

### Fixed
- **9 reelle `mypy --strict`-fejl rettet på tværs af 6 filer** — fundet
  ved at køre mypy mod hele `engine/`-pakken og rette hver fejl konkret,
  ikke blot undertrykke dem:
  - **`calibration_engine.py`** (reel latent bug, ikke kun kosmetik):
    `_nearest_select_option()` returnerede en `dict[str, float | str]`
    (label + værdi blandet i ét dict), så mypy aldrig kunne garantere at
    den udlæste værdi rent faktisk var et tal på kaldestedet, hvor den
    indgår i en `abs(a - b)`-sammenligning mod et andet flydende tal.
    Erstattet med en typet `tuple[str, float]`.
  - **`controller.py`**: `guarded`-dekoratorens `Callable` manglede
    typeparametre (`Callable[..., Any]` via en `TypeVar`, så dekoratorens
    returtype forbliver bundet til den dekorerede funktions egen type);
    `getattr(self, "coordinator", None)` blev tildelt en
    ikke-Optional-annoteret variabel.
  - **`schedule_engine.py`**: to hjælpefunktioner manglede
    parametertyper (`state: Any`, `value: Any`).
  - **`sync_engine.py`**: `_make_confirm_callback()` manglede returtype
    (`Callable[[Any], None]`).
  - **`window_engine.py`**: `_cancel_task()`'s `task_dict`-parameter var en
    utypet `dict` — nu `dict[str, asyncio.Task[Any]]`.
  - **`presence_engine.py`**: `_notify()`'s `actions`-parameter var en
    utypet `dict` — nu `list[dict[str, str]] | None`.
  - De øvrige 6 engine-filer (`pid_controller.py`, `door_engine.py`,
    `preheat_engine.py`, `season_engine.py`, `remote_button_engine.py`,
    `valve_protection_engine.py`) bestod allerede `mypy --strict` uden
    ændringer.

## [0.43.0] — 2026-09-14

Implementerer punkt 7 (gruppe C) af den prioriterede implementeringsplan:
solindfald via `sun.sun` + valgfri per-rum lux-sensor.

### Added
- **Punkt 7 — Solindfald** (`const.py`, `coordinator.py`, `config_flow.py`,
  `websocket.py`, `heat-manager-panel.js`): nyt `CONF_LUX_SENSOR` — en
  valgfri lux-sensor pr. rum (i dag: Stuen, Køkken, Gang — tilføjes for
  flere rum når der købes sensorer, uden kodeændringer). Ny
  `coordinator._solar_gain_reduction()`: når `sun.sun`'s elevation er over
  horisonten OG rummets lux overstiger en konfigurerbar grænse, reduceres
  PID'ens beregnede effekt — aldrig øges, kun trækkes fra, anvendt EFTER
  vejrkompensations-feedforward'en så de to kan modvirke hinanden på en
  kold-men-solrig dag. Bevidst målt (lux) frem for beregnet (sol-position +
  husorientering) — en lux-af læsning fanger automatisk skydække, gardiner
  og årstid uden at nogen skal konfigurere en vinkel. Ny global sektion
  "Solindfald" i Konfiguration-fanen (lux-grænse/vægt/maks-reduktion, samme
  mønster som Vejrkompensation) — **off by default**, ingen
  adfærdsændring for nogen installation før både dette slås til OG mindst
  ét rum har en lux-sensor sat. Lux vist som ny chip på rumkort (Oversigt)
  og i Rum-detaljer, side om side med fugt/CO₂.

## [0.42.0] — 2026-09-14

Implementerer punkt 5 og 12 af den prioriterede implementeringsplan
(gruppe B): udetemperatur som covariate i opvarmningsrate-læringen, og
card/panel data-parity for Lovelace-kortets press-and-hold-sheet.

### Changed
- **Punkt 5 — Opvarmningsrate-læring: udetemperatur som covariate**
  (`engine/calibration_engine.py`): den lærte opvarmningsrate pr.
  (rum, dør-tilstand) var én flad EMA, uafhængig af udetemperatur —
  erstattet med en eksponentielt vægtet lineær regression
  (`rate ≈ intercept + slope × udetemp`), samme fysiske intuition som
  PID'ens eksisterende vejrkompensations-feedforward. `get_room_heatup_rate()`
  beregner nu en forudsigelse for den AKTUELLE udetemperatur i stedet for
  ét gennemsnit på tværs af alle tidligere observerede udetemperaturer.
  Falder automatisk tilbage til den gamle flade middelværdi, indtil der er
  observeret nok spredning i udetemperaturen til at fitte en pålidelig
  hældning (eller hvis intet udetemperatur-sensor/vejr-entity er
  konfigureret) — ingen adfærdsændring for en frisk installation før det.
  Anomali-detektionen (`get_room_heatup_anomaly`) sammenligner nu også mod
  den forudsagte rate for dagens udetemperatur i stedet for et fladt
  gennemsnit — et rum der varmer langsommere udelukkende fordi det er
  markant koldere udenfor lige nu, fejlmærkes ikke længere som anomalt.
  Metodesignaturen `get_room_heatup_rate(room, door_open, outdoor_temp=None)`
  er bagudkompatibel — eksisterende kald uden det nye argument får
  automatisk `coordinator.outdoor_temperature` indsat. Explicit forarbejde
  til punkt 6 (EKF-model), som planen selv anbefaler skal vente til denne
  regression har kørt en fuld opvarmningssæson.

### Added
- **Punkt 12 — Card/panel data-parity** (`frontend/heat-manager-card.js`,
  press-and-hold-sheeten): tilføjet de felter, kortet manglede i forhold
  til panelets Rum-detaljer — Mål-temp (`target_temp`) og Away-temp
  (`away_temp_override`) som egne linjer, Netatmo cloud-diagnostik
  (preset mode, schedule, cloud-sætpunkt, hvac-action) for Netatmo-rum,
  og — som bonus, da backend allerede leverer det efter punkt 4 —
  sundhedsscore-badgen. Alle er rene læsninger fra det eksisterende
  `_roomData`-snapshot (opdateret hvert 60. sekund via `get_state`-poll),
  ingen ny backend- eller pollinglogik. "Flyt felter fra bottom-sheet til
  hovedlinje" (samme punkt i planen) er bevidst ikke lavet i denne omgang —
  ren layout-omrokering med lav prioritet, jf. planens egen vurdering af
  punkt 12 som "lav prioritet — poler, ikke funktion".

## [0.41.1] — 2026-09-14 (hotfix)

Critical bugfix for v0.41.0: the entire integration frontend broke after
upgrade — panel showed "Ingen forbindelse til Heat Manager" and "0 rum
konfigureret" on every tab, immediately after a full HA restart.

### Fixed
- **`websocket.py` (`ws_get_state`)**: v0.41.0's new per-room health-score
  computation referenced `unavailable_entities` several dozen lines before
  that variable was actually assigned later in the same loop iteration — a
  plain `NameError` on every single call, which crashed `ws_get_state()`
  entirely before it could return anything. The panel's WS call therefore
  always failed, falling back to its empty client-side snapshot (0 rooms,
  "Ingen forbindelse"). Fixed by moving the health-score block to after
  `unavailable_entities` is populated — no behavioural change to the score
  itself, purely an ordering fix. Caught immediately by the user after
  deploying v0.41.0; not caught beforehand since this repo has no automated
  test coverage for `ws_get_state()` and the bug only manifests at runtime
  (a `python3 -m py_compile` pass, which was run, cannot catch a NameError
  that only fires when the function actually executes).

## [0.41.0] — 2026-09-14

Implementer trin 2–5 af den prioriterede implementeringsplan
(`planning/heat_manager_prioriteret_implementeringsplan_2026-09-13.md`,
gruppe A/B): statuscenter-dedup, per-rum sundhedsscore, en udvidet HA
Repairs-integration, og sammenklappelige sektioner i panelets
Konfiguration-fane.

### Added
- **Punkt 4 — Sundhedsscore pr. rum** (`websocket.py`, `heat-manager-panel.js`):
  nyt `health_score` (0–100) og `health_label` ("god"/"ok"/"dårlig") felt pr.
  rum i `ws_get_state()`-payloaden — en simpel, additiv vægtning af allerede
  eksisterende signaler (lavt batteri, skimmelrisiko, utilgængelige enheder,
  opvarmningsrate-afvigelse). Vist som et nyt 🩺-badge på Oversigt-rumkortene,
  kun når scoren er under 100 (et fuldt sundt rum får intet ekstra badge).
- **Punkt 2 — Udvidet HA Repairs-integration** (`coordinator.py`, `__init__.py`,
  `const.py`, `strings.json`/`translations/da.json`): `_report_issue()`’s
  eksisterende statuscenter-tracker rejser nu også en rigtig HA Repair-issue
  (synlig i Indstillinger → Reparationer og HA-mobilappens badge) for tre
  kategorier, når de har været uafbrudt aktive forbi `issue_escalation_minutes`
  (samme tærskel push-notifikationen allerede bruger): `cloud_down` (hele
  huset — alle Netatmo-rum utilgængelige), `mold_risk:<rum>` (vedvarende
  skimmelrisiko, genbruger den eksisterende kategori), og det nye
  `room_override_stuck:<rum>` (et rum der har stået i manuel override længe —
  ofte bare glemt boost/manuel justering). Én delt oversat streng
  (`persistent_issue`, med `{message}`/`{duration_min}`-placeholders) i stedet
  for en per-kategori oversat streng. Ryddes automatisk når kategorien igen
  bliver inaktiv, og ved entry-unload.
- **Punkt 5 — Sammenklappelige sektioner** (`heat-manager-panel.js`,
  Konfiguration-fanen): hver `.section-box`-header i fanen kan nu klappes
  sammen/ud ved klik — tilstanden ligger udelukkende som en `.collapsed`-klasse
  på selve `.section-box`, uden per-sektion-id eller persisteret state (nulstilles
  ved næste fulde render af fanen, fx faneskift). Reducerer scroll-mængden
  på særligt mobil, hvor Konfiguration-fanen har 12 sektioner.

### Changed
- **Punkt 3 — Dedup/gruppering af statuscenter-issues** (`websocket.py`
  `_build_active_issues()`): kategorierne “utilgængelige entiteter”,
  “skimmelrisiko”, “åbent vindue” og “opvarmningsanomali” viser nu én samlet
  linje (fx “5 rum har utilgængelige sensorer/enheder”) i stedet for én linje
  pr. ramt rum, når mere end ét rum er ramt samtidig — uddrag af sidste sæsons
støjende statuscenter. Et enkelt ramt rum viser stadig den samme,
rum-specifikke besked som før.

## [0.40.1] — 2026-09-14

Bugfix — Netatmo rooms' displayed heating-power/valve % (🔥 in the panel's
room cards) was misleading: it echoed Netatmo's own self-reported
`heating_power_request` cloud attribute, which can lag several minutes
behind Heat Manager's actual commanded setpoint (cloud/valve lag). A room
Heat Manager had already brought back to target could still show 70-100%
"demand" purely from Netatmo's side, looking like a stuck/overheating PID
when the PID itself had already correctly dropped to 0% (confirmed via
anti-windup check in `engine/pid_controller.py` — clamp and math both
correct). Root cause investigated 2026-09-14 after a user report of rooms
holding at 23-25°C against a 19°C target with the panel showing 72-100%
heating power.

### Fixed
- **`websocket.py` (`ws_get_state`)**: a Netatmo/HomeKit-split room's
  `valve_position` (the field the panel displays as 🔥/valve %) is now set
  from Heat Manager's own `pid_power` (the PID controller's last computed
  output) instead of the cloud entity's `heating_power_request` attribute.
  Zigbee rooms with a configured `pi_demand_entity` (an actual physical
  valve-position sensor) are unaffected — that override still applies, since
  those rooms have no HomeKit entity and the new Netatmo-only condition is
  never true for them. The raw `heating_power_request` value is still read
  into a local variable for potential future diagnostics use, just no longer
  echoed to the frontend as the room's valve %.

## [0.40.0] — 2026-09-13

Weather compensation curve — fifth and final of five architecture-review
rounds (see v0.36.0). Turns out this feedforward already existed
(`FF_REFERENCE_OUTDOOR_TEMP`/`FF_WEIGHT`/`FF_MAX_CONTRIBUTION` — "Conservative
defaults, not yet exposed in the UI") as a hardcoded, always-on constant; this
round makes it configurable per-install without changing a single existing
install's behaviour on upgrade.

### Added
- **`coordinator.py`**: new module-level pure helper
  `_weather_compensation_feedforward(config, outdoor_temp)` — same formula as
  before (outdoor temp below a reference contributes proactive PID power, up
  to a cap), now reading its three tuning values from config with the exact
  previous hardcoded constants as fallback defaults, and gated by a new
  enabled toggle that **defaults to on** (the feedforward was always-on
  before this setting existed — defaulting it to off would have silently
  changed heating behaviour for every existing install on upgrade). Extracted
  as a pure function of `(config, outdoor_temp)` specifically so it's
  unit-testable without mocking the coordinator/hass.
- **`const.py`**: `CONF_WEATHER_COMPENSATION_ENABLED` (default `True`) /
  `CONF_FF_REFERENCE_OUTDOOR_TEMP` / `CONF_FF_WEIGHT` / `CONF_FF_MAX_CONTRIBUTION`
  — the `DEFAULT_*`/bare `FF_*` fallback values are unchanged from before.
- **`config_flow.py`**: all four fields added to the existing "Season &
  global settings" step (`_step1_schema()`, right after the PID controller
  fields), in both the initial config-flow and options-flow registrations.
- **`websocket.py`**: wired into the same generic
  `_BOOL_CONFIG_FIELD_DEFAULTS`/`_NUMERIC_CONFIG_FIELDS` live-editing tables
  used by every other Fase 2 field, plus `config_snap` and the update schema.
- **`frontend/heat-manager-panel.js`**: new "Vejrkompensation" section in
  Indstillinger, right after PID-regulator — enable toggle, reference
  outdoor temperature, weight, and max contribution, matching the existing
  section-box/`_cfgToggleRow`/`_cfgNumberRow` pattern. Also fixed a gap from
  v0.39.0: `notify_issue_escalation`/`issue_escalation_minutes` had been
  wired all the way through the backend/config-flow but were never actually
  added to the panel's Notifikationer box — added now, alongside the
  existing per-feature notify toggles.
- **`strings.json` / `translations/en.json` / `translations/da.json`**:
  labels + descriptions for all four weather-compensation fields, in both
  the config-flow and options-flow step registrations.
- **`tests/components/heat_manager/test_weather_compensation_feedforward.py`**:
  10 new tests — critically, that an install with no config for these
  fields computes *identical* feedforward to the old hardcoded formula at
  several outdoor temperatures (including right at the old cap and right at
  the reference point), plus the toggle disabling it outright, a custom
  reference temperature shifting the zero point, a custom weight scaling the
  contribution, a custom max-contribution capping lower than the default,
  a `None` outdoor temperature always being 0 regardless of config, and
  `enabled: True` behaving identically to the unset default.

## [0.39.0] — 2026-09-13

Status escalation + structured HA events — fourth of five architecture-review
rounds (see v0.36.0). A generic layer on top of the status center: any
warning/critical category can now push one escalation notification if it
persists, and every category's start/clear transitions are now visible on
HA's event bus for automations — without requiring each category to build
this itself.

### Added
- **`coordinator.py`**: new generic `_report_issue(key, active, severity,
  message)` — fires `heat_manager_issue_started`/`heat_manager_issue_cleared`
  on HA's event bus on each transition of a stable `key` (payload:
  key/severity/message on start, key/message/duration_seconds on clear), and
  escalates a still-active issue to exactly one push notification per
  continuous episode once it's been active longer than
  `CONF_ISSUE_ESCALATION_MINUTES` (default 60 min), gated by
  `CONF_NOTIFY_ISSUE_ESCALATION` (default on). This is additive to/independent
  of whatever instant notifier a category already has (mold risk, windows);
  heat-up-rate anomaly (v0.38.0) has no notifier of its own at all, so this
  is the only push it will ever get. Wired into three call sites in the
  coordinator's own periodic tick (so it works even with no client watching
  the panel): `_async_check_mold_risk()` (extended, not replaced — its own
  instant False→True notification is unchanged), and two new methods,
  `_async_check_window_issue_events()` (via
  `window_engine.get_open_windows()`) and
  `_async_check_heatup_anomaly_events()` (via
  `calibration_engine.get_room_heatup_anomaly()`).
- **`const.py`**: `CONF_NOTIFY_ISSUE_ESCALATION` / `CONF_ISSUE_ESCALATION_MINUTES`
  / `DEFAULT_ISSUE_ESCALATION_MINUTES`.
- **`config_flow.py`**: both new fields added to the existing notification
  preferences step (`_notifications_schema()`) — no new step, no schema
  migration needed.
- **`websocket.py`**: both fields wired into the existing generic
  `_BOOL_CONFIG_FIELD_DEFAULTS`/`_NUMERIC_CONFIG_FIELDS` live-editing tables
  (Fase 2 panel "Indstillinger" tab) and into `config_snap`, and the update
  schema — one line per table, no new code path, same pattern every field
  since v0.35.0's Fase 2 refactor has used.
- **`strings.json` / `translations/en.json` / `translations/da.json`**:
  labels for both new fields, in both the initial config-flow step and the
  options-flow step (same schema, two step registrations).
- **`tests/components/heat_manager/test_coordinator_issue_escalation.py`**:
  12 new tests — started/cleared event firing and payloads, no event on an
  unchanged active/inactive state, escalation firing past threshold and not
  before, exactly-once-per-episode dedup, respecting the notify toggle and a
  missing notify_service, a new episode after a clear being escalatable
  again, and both new call sites correctly deriving active/inactive per room
  from `window_engine`/`calibration_engine`.

## [0.38.0] — 2026-09-13

Heat-up-rate anomaly detection — third of five architecture-review rounds
(see v0.36.0). A cheap, room-relative "possible stuck valve" signal built
entirely from data `CalibrationEngine` already learns for its heat-up-rate
EMA — no new sensors, no new config.

### Added
- **`engine/calibration_engine.py`**: new tuning constants
  `_HEATUP_ANOMALY_MIN_SAMPLES` (5), `_HEATUP_ANOMALY_STREAK_THRESHOLD` (3),
  `_HEATUP_ANOMALY_RATIO` (0.4). `_async_update_heatup_learning()` now also
  compares each new heat-up-rate sample against the room's own previously
  learned EMA baseline: a sample below `_HEATUP_ANOMALY_RATIO` of that
  baseline counts toward a per-room streak, reset on any non-underperforming
  sample or as soon as the room stops actively heating (leaves
  `NORMAL`/`PRE_HEAT`). The baseline itself is only trusted once backed by
  `_HEATUP_ANOMALY_MIN_SAMPLES` prior samples, and a streak of
  `_HEATUP_ANOMALY_STREAK_THRESHOLD` consecutive underperforming samples is
  required before flagging — deliberately conservative, to avoid false
  positives from a single noisy reading, an open door, or a draft. New
  `get_room_heatup_anomaly(room_name) -> bool` getter exposes the flag.
  Purely diagnostic — never gates any control decision, same as the
  heat-up rate itself.
- **`websocket.py`**: new "4b" category in `_build_active_issues()` —
  surfaces a `warning`-severity "🐌 &lt;room&gt;: varmer langsommere end
  normalt — muligvis fastsiddende ventil" issue in the status center for
  any room `get_room_heatup_anomaly()` currently flags.
- **`tests/components/heat_manager/test_calibration_engine_heatup_anomaly.py`**:
  5 new tests — no flag before the baseline is trusted (even with a badly
  underperforming run), flag raised after a genuine 3-sample underperforming
  streak, flag clears on a single good-rate sample, streak resets when the
  room leaves active heating (e.g. a window opens) rather than persisting
  across an unrelated state change, and a sanity check on the streak
  threshold constant itself.

## [0.37.0] — 2026-09-13

Calibration select-entity support — second of five architecture-review
rounds (see v0.36.0). better_thermostat-inspired: some integrations (e.g.
HomematicIP) expose TRV calibration as a `select` entity with a fixed set
of discrete offset steps rather than a continuous `number` entity.

### Added
- **`engine/calibration_engine.py`**: `CONF_CALIBRATION_ENTITY` may now
  point at either a `number.*` entity (unchanged — `number.set_value`) or a
  `select.*` entity. For a select entity, the computed offset is snapped to
  the nearest available option (parsed from the option strings via new
  `_parse_offset_option()` — matches the first signed/unsigned decimal in
  each option regardless of unit suffix, e.g. "-1.0", "+0.5K") and written
  via `select.select_option`. The *current* calibration value (needed to
  turn a residual into an absolute offset — see the module's existing
  oscillation-avoidance comment) is now read via new
  `_read_calibration_value()`, which parses the selected option for a
  `select` entity instead of assuming a plain float. Any other entity
  domain is unsupported and silently skipped, same as a missing entity.
- **`tests/components/heat_manager/test_calibration_engine_select_support.py`**:
  11 new tests — option-string parsing across several unit-suffix styles,
  nearest-option snapping, the pre-existing `number` write path confirmed
  unchanged, the new `select` write path (including reading current value
  back from the selected option, not just writing), and silent skip
  behaviour for an unsupported domain or a select entity with no
  parseable numeric options.

## [0.36.0] — 2026-09-13

Restart-safety hardening — first of five rounds implementing findings from
`audit/heat_manager_architecture_review_2026-09-13.md` (better_thermostat
comparison, status system, ML, restart safety). This round: the one genuine
"we lose data" finding from that review.

### Added
- **`coordinator.py`**: `_persist_override_snapshot()`/
  `_restore_override_snapshot()` — same entry.options-snapshot pattern as
  the existing event-log persistence (B10). A room's manual override
  (source + expiry) and an active boost (rooms + expiry) are now persisted
  on shutdown and restored on startup. Previously these lived in pure
  in-memory dicts (`room_override_source`, `room_override_expires_at`,
  `boost_active_rooms`, `boost_expires_at`) — a manual override or an
  active boost was silently forgotten on any HA restart, with the room
  quietly falling back to its normal schedule with no warning at all. Only
  the *bookkeeping* is restored — the physical TRV is never re-commanded,
  since the device already holds whatever setpoint was last written to it;
  restoring the bookkeeping just stops Heat Manager's own next PID tick
  from silently overwriting that still-active manual choice. A saved
  override/boost whose expiry already passed while HA was down is
  deliberately NOT restored — the room just comes back NORMAL, exactly as
  if the expiry had fired normally.
- **`tests/components/heat_manager/test_coordinator_override_boost_persistence.py`**:
  11 new tests covering persist/restore round-trips, permanent (no-expiry)
  overrides, expired-while-down skip behaviour for both overrides and
  boost, and malformed-JSON safety.

### Fixed
- **`__init__.py`**: `_async_update_listener`'s docstring incorrectly
  claimed "WindowEngine has no startup re-sync equivalent to
  PresenceEngine's B11 fix" — that gap was actually closed by the
  2026-09-11 restart-noise fix (`WindowEngine._check_initial_windows()`),
  the docstring was just never updated. Documentation-only fix; window
  restart-safety itself was already correct.

## [0.35.0] — 2026-09-13

Card/panel data parity, scoped to `sync_mode`/`schedule_entity` in the
mobile card's press-and-hold detail sheet.

### Added
- **`heat-manager-card.js`**: `_roomSheetHTML()` now also shows a "🔄 Sync"
  row (same `_syncModeLabel()` labels as the panel: Deaktiveret/Spejl/Lås,
  omitted when `disabled`) and a "🗓 Schedule" row ("Konfigureret", mirroring
  the panel's own boolean-presence-only badge rather than the raw entity_id)
  — sourced from the existing `heat_manager/get_state` poll (`this._roomData`)
  already used for door status/heat-up rate/TRV-count in this same sheet,
  same "config-only string, no states-based fallback exists" reasoning as
  those fields. New shared `_hmSyncModeLabel()` helper.

### Known limitation
- Deliberately scoped to just these two fields — Target temp/Away temp
  override stay panel-only (edited via v0.34.0's per-room live editing, not
  read-only mirrored here), and Netatmo cloud diagnostics (`cloud_preset_mode`
  etc.) remain panel-only too. Full parity (every config-only field, on the
  card's main row rather than the detail sheet) is still open if wanted.

## [0.34.0] — 2026-09-13

Per-room live editing, straight from the Rum-fane's room cards — Flemming's
previously-parked "punkt 3". Scoped to the two fields he picked (Target temp
/ Away temp override); CO₂ threshold and everything else stays
options-flow-only for now.

### Added
- **`websocket.py`**: new `heat_manager/update_room_config` WS command
  (`ws_update_room_config()`) — takes `room_name` plus `comfort_temp` and/or
  `away_temp_override`, validates each against `_room_schema()`'s own
  selector bounds (comfort_temp 15.0–26.0, away_temp_override 5.0–20.0,
  returning an `invalid_value` error otherwise), and writes the *entire*
  updated `rooms` list back to `entry.options` — same full-list-overwrite
  pattern the options-flow room-edit step already uses. `coordinator.rooms`/
  `coordinator.config` read `entry.options` fresh on every access, so the
  change takes effect immediately, no reload needed. `ws_get_state()`'s
  per-room payload now also includes the raw `comfort_temp`/
  `away_temp_override` config values (previously only the PID's fully
  resolved `target_temp` was sent) so the new edit fields have something to
  prefill with.
- **`heat-manager-panel.js`**: Rum-fane room cards get two new inline
  editable fields — Target temp and Away temp (with an info-icon explaining
  it's the PID/night-setback floor, not the window-off temperature) — same
  input+Gem-button+checkmark visual pattern as the Indstillinger tab's
  `_cfgNumberRow()`, but scoped by `data-room`/`data-field` and the button's
  own closest row instead of a per-field id, since (unlike Indstillinger)
  many of these rows render at once, one set per room.
- **`tests/components/heat_manager/test_websocket.py`**: 12 new tests for
  `ws_update_room_config()` — entry/room lookup misses, no-op when nothing
  sent, both fields persist and log, unchanged-when-same-value and
  unchanged-when-at-default (mirroring `ws_update_config`'s own
  default-aware change detection), out-of-range and non-numeric values
  rejected with `invalid_value`, and a multi-room fixture confirming only
  the targeted room's entry is touched in the persisted list.

### Known limitation
- CO₂ threshold and every other per-room field stay options-flow-only —
  deliberately scoped to just the two fields Flemming picked. Interior
  doors' "niveau C" (a neighbouring room adjusting another room's target)
  remains separately parked — see backlog.

## [0.33.0] — 2026-09-13

Window-off temperature split from `away_temp_override`, a global window-delay
default, and in-panel tooltips — prompted by Flemming pointing out that
setting `away_temp_override` to a "comfortable away temp" (e.g. 18°C) would
silently raise the PID's own idle-output floor and the night/wake-setback
floor everywhere, not just when a window opens.

### Added
- **`const.py`**: `CONF_WINDOW_DELAY_DEFAULT_MIN` (default
  `DEFAULT_WINDOW_DELAY_DEFAULT_MIN` = old `DEFAULT_WINDOW_DELAY_MIN`, 5 min)
  — one global setting every room's window open-delay now actually uses.
  `CONF_WINDOW_OFF_TEMP` (default `DEFAULT_WINDOW_OFF_TEMP` = 10.0°C) — a
  dedicated "heat is off" temperature for the window-open write, completely
  independent of `CONF_AWAY_TEMP_OVERRIDE` (which keeps its existing role:
  flooring the PID's idle output and the night/wake setback — see
  `engine/pid_controller.py`'s `power_to_setpoint()`).
- **`config_flow.py`**: both new fields added to `_step1_schema()` (Vindue
  section) — shared by the first-time wizard and the options-flow's
  `async_step_global`, so both are editable from either place already.
- **`websocket.py`**: both fields added to `config_snap`,
  `_NUMERIC_CONFIG_FIELDS`, and `ws_update_config`'s schema — live-editable
  from the panel, same pattern as `boost_default_temp`/`_minutes`.
- **`heat-manager-panel.js`**: Indstillinger → Vindue now has "Forsinkelse
  før sluk" (`window_delay_default_min`) and "Sluk-temperatur"
  (`window_off_temp`), each with an info-icon tooltip explaining what it
  does. New reusable `_infoIcon(text)` tooltip: hover/focus reveals it on
  desktop via CSS, tap toggles an `.open` class on mobile (reuses the single
  outside-click listener from v0.32.0's status center — no new listener
  added). Also added to Rum-detaljer's "Rum temp" / "Target Temp" / "Trv
  temp" stat labels, clarifying that Target Temp is Heat Manager's resolved
  target (not necessarily the raw value written to the TRV — the PID
  translates it into a control value that can sit above or below it), and
  that Trv temp reads warm because it sits on the radiator body.
- **`tests/components/heat_manager/test_window_engine_global_settings.py`**:
  11 new tests — `_get_open_delay()` reads the global default and ignores
  the (now-vestigial) per-room `window_delay_min` entirely; `_open_after_delay()`
  writes the global `window_off_temp` and ignores `away_temp_override` even
  when a room has one configured, independent of `pid_enabled`.

### Changed
- **`engine/window_engine.py`**: `_get_open_delay()` no longer reads the
  per-room `CONF_WINDOW_DELAY_MIN` — reads `CONF_WINDOW_DELAY_DEFAULT_MIN`
  unconditionally for every room (wind/rain reduction unchanged). The
  window-open write now uses `CONF_WINDOW_OFF_TEMP` directly instead of a
  per-sensor `away_temp_override` snapshot.

### Removed
- **`engine/window_engine.py`**: `_window_open_setpoint()` and
  `_get_current_temp()` (its only caller) — dead code. `power_to_setpoint()`
  always returns `trv_min` unconditionally when `power <= 0.0`, so the old
  PID round-trip on window-open was mathematically always equivalent to
  just using the fallback temperature directly. The now-unused
  `PidController` import was also removed from this file.

### Fixed
- **`strings.json` / `translations/{en,da}.json`**: full rebuild against the
  live `config_flow.py` schema — the "no translation labels yet" limitation
  noted below for `window_delay_default_min`/`window_off_temp` turned out to
  be one small symptom of a much larger, pre-existing drift across all three
  files. Added every missing field across every step (`outdoor_humidity_sensor`,
  `precipitation_sensor`, `wind_speed_sensor`, `pause_duration_min`,
  `humidity_sensor`, the two v0.33.0 window fields, and more); removed stale
  fields long gone from the schema (`away_temp_mild`, `away_temp_cold`,
  `mild_threshold`, `energy_tracking`, the dead `no_rooms` error); added the
  entire missing interior-doors options-flow translation block
  (`doors_menu`/`door_add`/`door_edit`, v0.24.0 — never had any translation
  coverage at all) plus three door-validation error keys that were missing
  entirely (`same_room`, `duplicate_door_pair`, `duplicate_door_sensor` —
  previously shown as raw untranslated keys to a real user hitting them).
  `translations/en.json` specifically had drifted the furthest: it still
  reflected the pre-v0.9.0 room/TRV schema shape, was missing every TRV
  sub-step, and had a factually wrong `comfort_temp` description
  ("ignored for Netatmo rooms") contradicting the already-fixed v0.19.0/
  v0.20.0 "B21" bug. `strings.json` and `translations/en.json` are now kept
  byte-identical going forward to prevent this class of drift recurring.

### Known limitation
- `CONF_WINDOW_DELAY_MIN` (the old per-room field) is left in place in
  `const.py`/`config_flow.py`, unread by `window_engine.py` — kept only in
  case per-room editing returns in a future, larger panel round (Flemming's
  point 3). See v0.34.0 — no longer parked.

## [0.32.0] — 2026-09-13

Status center. Replaces the four scattered header/Oversigt indicators
(cloud-chip, health-chip, ws-error-chip, and the Oversigt-only
remote-last-action pill) with a single consolidated status field, centered
in the header, that shows every currently-active issue — critical, warning,
or info — in one place, on every tab.

### Added
- **`websocket.py`**: new `_build_active_issues(coordinator, rooms)`,
  called from `ws_get_state()` and included in the payload as
  `active_issues`. Computes, in order: (1) Netatmo cloud/gateway health
  (mirrors `binary_sensor.py`'s `CloudAvailableSensor` — all rooms down is
  critical, some rooms down or stale (10+ min) is warning), (2) other
  unavailable entities per room (window/humidity/CO2/battery/secondary
  TRVs), (3) mold risk per room, (4) open windows per room, (5) active
  boost (info), (6) the last remote-control action if under 30 minutes old
  (info — this is what used to be the Oversigt-only remote-last-action
  box, now visible from every tab instead of just one). Each issue is
  `{"severity": "critical"|"warning"|"info", "icon": str, "message": str}`;
  the list is sorted critical → warning → info.
- **`heat-manager-panel.js`**: new `#status-center` header field —
  `flex: 1 1 0%; max-width: 50%` of the header, stretched to ~90% of its
  height, centered between the logo/title and the controller-state badge.
  Shows the single highest-severity issue inline plus a `+N` badge when
  there's more than one; click or tap opens a dropdown listing every active
  issue. Border/background color reflects the worst severity present
  (green when clear, grey for info-only, amber for warning, red for
  critical). `_activeIssues()` merges the server's `active_issues` with one
  thing the server cannot report about itself — its own dead WebSocket
  connection — computed client-side from the existing `_wsError`/
  `_lastSyncTime` fields, exactly as the old `ws-error-chip` did, and
  injected into the same sorted list before render.

### Changed
- Removed `#cloud-chip`, `#health-chip`, `#ws-error-chip` (all three
  topbar chips) and the Oversigt tab's `#remote-last-action-box` — their
  logic now lives in `_build_active_issues()` / `_activeIssues()` /
  `_patchStatusCenter()`. One `_patchStatusCenter()` call replaces the four
  separate patch calls that used to run on every render.
- Removed the now-dead `.cloud-chip*`/`.ws-error-chip*`/
  `.remote-last-action-box` CSS, the `chip-pulse` keyframe, and the
  `[hidden]` override rule those three classes needed (see
  `audit/heat_manager_status_check_2026-09-11.md` for why that rule existed
  in the first place). The new `.status-center*`/`.status-issue-row*`
  classes deliberately avoid the same bug: no element that's also toggled
  via `[hidden]` gets its own unconditional `display` declaration.

### Fixed
- The outside-click handler that closes the status-center dropdown is
  bound once in `connectedCallback()` (guarded by `_outsideClickBound`),
  not inside `_attachEvents()` — the latter reruns on every full render but
  `shadowRoot` itself is never recreated (only the inner `.panel` subtree
  is replaced), so a listener attached directly to `shadowRoot` there would
  have accumulated one duplicate copy per render. Caught during review,
  before ever running on-device.

## [0.31.0] — 2026-09-13

Mold risk as a push notification. `MoldRiskSensor` (`binary_sensor.py`)
already exposed mold risk per room as an entity, but as a passive
`CoordinatorEntity` property it could only ever be polled — nothing pushed
a notification the moment conditions actually turned risky, unlike the
existing window/presence/preheat notifications. The coordinator's periodic
tick now runs its own edge-triggered check, mirroring the sensor's own
RH/dewpoint algorithm, and fires the configured notify service exactly once
per risk episode.

### Added
- **`coordinator.py`**: new `_async_check_mold_risk()` tick step (step 13 of
  `_async_update_data()`), plus `_notify_mold_risk()`. For every room with a
  configured humidity sensor, computes RH ≥ 70% AND room temp ≤ dewpoint +
  1°C (Magnus formula, DIN 4108-2 — duplicated from `MoldRiskSensor` rather
  than imported, same layering rationale as `websocket.py`'s
  `ws_get_state()`) and tracks each room's last-known risk state in the new
  `self._mold_risk_state` dict. Sends exactly one notification on the
  False → True edge — re-armed only once risk drops back to False — logged
  to the History tab and dispatched via `CONF_NOTIFY_SERVICE`, the same
  `notify.*` split-and-call pattern `engine/window_engine.py` already uses.
- **`CONF_NOTIFY_MOLD_RISK`** (`const.py`, default `True`, matching the
  other three notify toggles): new options-flow field in
  `_notifications_schema()` (`config_flow.py`), and a new live-editable
  toggle in the panel's Konfiguration → Notifikationer section
  ("Skimmelrisiko"), wired through the existing generalized
  `_BOOL_CONFIG_FIELD_DEFAULTS`/`config_snap` machinery in `websocket.py`
  from Fase 2 del 1 — no new WS branch needed, just one table entry and one
  `config_snap` key.
- `strings.json` / `translations/{en,da}.json`: new `notify_mold_risk` label
  in both the initial setup wizard's and the options flow's notifications
  step.
- `tests/components/heat_manager/test_coordinator_mold_risk_notification.py`
  (11 tests): risk edge triggers exactly one notification; no duplicate
  notification while risk stays on; re-arms after risk clears and fires
  again; RH below threshold, missing humidity sensor, unavailable humidity
  sensor and missing temperature are all silently skipped; the toggle
  defaults to `True` when unset (same "true unless explicitly turned off"
  contract as the panel's other notify_* toggles, and the same bug class the
  Fase 2 del 1 `_BOOL_CONFIG_FIELD_DEFAULTS` fix was written to prevent);
  `CONF_NOTIFY_MOLD_RISK: False` makes the whole check a no-op;
  `_notify_mold_risk()` is a silent no-op with no `notify_service`
  configured, and correctly splits `"notify.xxx"` into domain/service.

## [0.30.0] — 2026-09-13

Mobile card press-and-hold — Fase 2, del 2 (`planning/heat_manager_fase2_spec_2026-09-11.md`).
Every room card on the mobile Lovelace card (`heat-manager-card.js`) previously
showed up to 6 diagnostic chips (humidity/CO2/battery/PID power/calibration/
window-duration) plus up to 3 status badges (blocking reason, ungrouped,
alongside mold-risk and TRV-offline) simultaneously, all the time — an
"instrument panel" density on the surface most people actually touch daily.
That diagnostic detail moves into a bottom-sheet opened by a 500ms
press-and-hold on a room card; the always-visible card now shows only name,
state, current/target temperature, valve %, and the two genuine warnings
(mold risk, TRV offline).

### Added
- **`heat-manager-card.js`**: press-and-hold (500ms) on any room card opens
  a new bottom-sheet (`_openRoomSheet()`/`_roomSheetHTML()`) showing every
  diagnostic previously rendered as an always-on chip (humidity, CO₂,
  battery, PID power, calibration offset, window-open minutes today),
  blocking-reason and ungrouped status as readable rows, plus two fields no
  card UI has ever shown before: interior-door open/closed status and the
  learned heat-up-rate (door open vs. closed — see v0.24.0) for rooms linked
  to a door. The hold is cancelled on release or on enough pointer movement
  to look like a scroll drag rather than a deliberate press.
- **Manual temperature override from the sheet**: a temperature input +
  duration selector + Send button, delegating to the same
  `heat_manager/set_room_temp` WS command the sidebar panel already uses —
  this card had no manual-override UI at all before. A "Gendan schedule"
  button restores the room to its normal schedule.
- **Grouping toggle from the sheet**: for any room with 2+ TRVs (via the new
  `trv_count` field the sheet reads from the backend), a toggle button calls
  `switch.turn_on`/`turn_off` on that room's `<room> Group` switch entity —
  previously only available from the panel.
- **`_loadTargetTemps()`** now also keeps the full per-room dict from each
  60s `heat_manager/get_state` poll (`this._roomData`), not just
  `target_temp` — the source for the sheet's door/heat-up-rate/trv_count/
  blocking_sources/group_enabled fields, none of which this card could
  discover any other way (its own per-instance config only ever stored
  `climate_entity`).

### Changed
- **Room card** (`_cardHTML()`/`_updateInPlace()`): dropped the always-on
  humidity/CO2/battery/PID/calibration/window-duration chips and the
  blocking-reason/ungrouped badges from the primary view — moved to the new
  sheet above. Mold-risk and TRV-offline badges stay always-visible (rare,
  genuine warnings, not routine diagnostics — matches the spec's own
  recommendation to keep an acute problem visible at a glance).
- **`_attachEvents()`**: removed the now-dead tap-to-toast handler for the
  (now-removed) blocking-reason badge; added the press-and-hold
  pointerdown/up/cancel/leave/move wiring on `#rooms-list` instead.

### Notes
- No automated tests accompany this change — the project's test suite
  (`tests/components/heat_manager/`) is Python/pytest against Home
  Assistant core; there is no JS test harness for either frontend file in
  this repo. Verified via `node --check` (syntax) and manual template/DOM
  review (div-balance check across the edited templates) — the same
  discipline already applied to `heat-manager-panel.js` throughout this
  project, since neither file can be exercised in a live browser from this
  environment.

## [0.29.0] — 2026-09-13

Panel "Indstillinger" — Fase 2, del 1 (`planning/heat_manager_fase2_spec_2026-09-11.md`).
15 operational fields that could previously only be changed by clicking
through the options-flow wizard can now be edited live from the sidebar
panel's Config tab, with the same save-and-confirm pattern already proven by
Alarmtavle/Notifikationer/Manuel TRV-kontrol. The options flow keeps every
one of these fields unchanged, as the fallback for first-time setup.

### Added
- **`websocket.py`**: `ws_update_config()` generalized from two hand-written
  string/bool branches into three declarative per-type tables
  (`_STRING_CONFIG_FIELDS`, `_BOOL_CONFIG_FIELD_DEFAULTS`,
  `_NUMERIC_CONFIG_FIELDS`) so a new live-editable field is a one-line
  addition instead of a new `if`-branch. Numeric fields are cast to their
  declared type (`float`/`int`) with an `invalid_value` WS error on a bad
  value, instead of ever writing a wrong type to `entry.options`.
  Change-detection compares against each field's real `DEFAULT_*` constant —
  not a blanket `0`/`False`/`""` — so a bool field whose true default is
  `True` (PID enabled, window/30-min-warning notify) can still be turned
  off from a fresh install where the key has never been persisted.
- **`ws_get_state()`**: `config_snap` now includes the current value of
  every field the panel can save — `pid_enabled`/`pid_kp`/`pid_ki`/`pid_kd`,
  `boost_default_temp`/`boost_default_minutes`, `window_warning_min`,
  `notify_windows`/`notify_window_warning_30`, `night_setback_enabled`/
  `night_setback_temp`/`night_start_hour`/`night_end_hour`,
  `notify_presence`/`notify_preheat` — so the panel can pre-fill each new
  field with its actual persisted value on load.
- **Panel Config tab** (`heat-manager-panel.js`): six new section-boxes —
  **PID-regulator** (enabled toggle, Kp/Ki/Kd), **Boost — standardværdier**
  (default temperature/duration), **Vindue** (warning-after minutes, window/
  30-min-warning notify toggles), **Nat-sætpunkt** (enabled toggle,
  setback temperature, start/end hour), **Grace-perioder** (day/night
  minutes — previously read-only in this tab), **Auto-off ved mildt vejr**
  (threshold/days — previously read-only). The existing **Notifikationer**
  section gained two more toggles (tilstedeværelse/forvarmning). Two new
  shared row builders (`_cfgNumberRow()`/`_cfgToggleRow()`) and one generic
  `save-field`/`toggle-field` click handler pair drive all of the above,
  instead of copy-pasting a hand-written handler per field the way
  Alarmtavle/Notifikationer's own string-field saves still do.
- **`test_websocket.py`**: seven new tests for the generalized
  `ws_update_config()` — numeric persistence and int/float casting, the
  default-aware change-detection for both a numeric field and a bool field
  defaulting to `True`, turning a `True`-default bool off from a fresh
  install, an invalid numeric value's `invalid_value` error, and multiple
  fields saved in one message.

### Changed
- **Config tab's "Global konfiguration" summary**: dropped Grace dag/nat and
  Auto-off grænse/dage — now shown as live-editable fields in their own
  section-boxes instead of duplicated as a read-only row above them.

## [0.28.0] — 2026-09-13

Boost's default temperature/duration (used whenever `heat_manager.boost_start`
or the panel/card boost button is called without its own values) were
hardcoded `DEFAULT_BOOST_TEMP`/`DEFAULT_BOOST_MINUTES` constants — no way to
change them without editing code. Closes that roadmap item from
`manual/heat_manager_brugermanual_2026-09-11.md` kapitel 9.

### Added

- **Options flow — "Season & global settings"**: two new fields, "Boost
  default temperature" (15–32°C, step 0.5) and "Boost default duration"
  (1–240 min), same bounds `services.yaml` already enforces on the service
  call itself. Available from both the initial setup wizard and the
  options-flow global-settings step (`_step1_schema()` powers both).
- **`const.py`**: new `CONF_BOOST_DEFAULT_TEMP` / `CONF_BOOST_DEFAULT_MINUTES`.
  `DEFAULT_BOOST_TEMP`/`DEFAULT_BOOST_MINUTES` remain as the fallback used
  when a config entry predates this option (fresh installs, upgrades).

### Changed

- **`coordinator.py`**: `async_boost_start()` now resolves its "no
  temperature/duration given" fallback from `self.config` first, falling
  back to the hardcoded constants only when the option itself is absent. An
  explicit caller-supplied value (service call field, panel/card button)
  still always wins, unchanged.
- **`services.yaml`**: `boost_start`'s field descriptions now point at the
  configurable default instead of quoting the old hardcoded numbers as fact.

## [0.27.1] — 2026-09-13

"Manuel TRV-kontrol" (panel Config tab) was session-scoped only — a plain
`panel.js` field, reset to off on every page reload — despite the panel
already presenting it as a persistent setting. Closes that roadmap item
from `manual/heat_manager_brugermanual_2026-09-11.md` kapitel 9.

### Fixed

- **Panel — Config tab**: "Manuel TRV-kontrol" now persists to `entry.options`
  via `heat_manager/update_config` (new `manual_trv_control` field), the same
  live-save pattern already used for `alarm_panel`/`notify_service`. The
  toggle reads its state from the server on every load/poll instead of
  always starting at off, and reverts with a toast if the save fails.
- **`const.py`**: new `CONF_MANUAL_TRV_CONTROL` / `DEFAULT_MANUAL_TRV_CONTROL`.
- **`websocket.py`**: `ws_get_state` includes `manual_trv_control` in the
  config snapshot; `ws_update_config` accepts and persists it (boolean,
  handled separately from the existing string fields).

## [0.27.0] — 2026-09-13

Closes the Fase 2 loose end flagged in `audit/heat_manager_status_check_2026-09-11.md`:
`select.<room>_netatmo_preset_mode` was already documented in the v0.20.0 CHANGELOG entry and
imported by `test_select.py`, but the entity itself was never written to `select.py` because
the file was locked (Windows access denial) on Flemming's machine.

### Added

- **`select.py`**: new `NetatmoPresetModeSelect` entity, one per room with a configured
  Netatmo TRV (`<entry_id>_<room>_netatmo_preset_mode`). Read/write passthrough to the room's
  Netatmo climate entity's own `preset_mode` — options are read live from that entity's
  `preset_modes` attribute, falling back to `NETATMO_PRESET_MODE_FALLBACK_OPTIONS`
  (`schedule`/`away`/`frost_guard`/`boost`) only when that attribute is unavailable.
  `async_select_option()` calls `coordinator.async_call_climate_service("set_preset_mode", ...)`
  with `needs_delay=True` — the same serialised Netatmo-call path every other engine already
  uses, so this can't race another room's cloud call. `async_setup_entry()` fans this out per
  room from `coordinator.get_all_room_trvs()`, adding at most one entity per room (its primary
  Netatmo TRV) so the unique_id (per-room, not per-TRV) can never collide.
- **`const.py`**: new `NETATMO_PRESET_MODE_FALLBACK_OPTIONS` list constant.

Not touched in this pass (see `manual/heat_manager_brugermanual_2026-09-11.md` kapitel 9 for the
rest of the Fase 2 backlog): no dropdown was added inside the custom panel itself — the new
entity is already usable from any standard HA dashboard, which was the original scope decision
from Fase 2 (`audit/heat_manager_fixes_2026-09-11_fase2.md`).

## [0.26.0] — 2026-09-11

Three panel requests from Flemming: show the running integration version somewhere visible,
add a house-wide quick-temperature control alongside the existing per-room one, and consolidate
every "target temperature" label onto one term instead of three ("Sætpunkt", "Mål °C", plus
the Netatmo-specific wording).

### Added

- **Panel — header**: the running integration version (read from `manifest.json` via the same
  `panel.py::_get_version()` helper the cache-busting query string already uses — no second,
  driftable copy of the number) now shows top-right of the header, next to "↻ Opdater".
  `websocket.py::ws_get_state()` reads it off-thread via `hass.async_add_executor_job` (blocking
  file I/O, same discipline as `panel.py`'s own registration-time read) and includes it in the
  payload as `version`.
- **Panel — Oversigt**: a 4th Controller meta-chip, "🛰️ Netatmo", showing the same
  `cloud_preset_mode (cloud_selected_schedule)` info the Rum-detaljer rows already display per
  room (e.g. "manual (Vinter)") — rolled up once for the whole house. Only appears when at
  least one room has Netatmo cloud data; shows "Blandet" with a per-room tooltip on the rare
  case rooms disagree, rather than silently presenting one room's value as the house's.
- **Panel — Rum-fanen**: a global Target Temp control ("Alle rum — Target Temp") above the
  per-room list, visible under the same "Manuel TRV-kontrol" toggle as the existing per-room
  sliders. Sends the chosen temperature + duration to every room that has a TRV, one
  `heat_manager/set_room_temp` WS call per room awaited sequentially (not in parallel) — the
  exact same command the per-room "Send ↗" button already uses, just fanned out, so no backend
  changes were needed and Netatmo's cloud API is never burst-called across every room at once.
  Rooms with no TRV (monitoring-only) are skipped. A matching "↺ Alle til schedule" resets every
  controllable room back to its own schedule.

### Changed

- **Panel — labels**: "Sætpunkt" (Oversigt room cards, Rum-detaljer stat row) and "Mål °C"
  (the per-room manual-override slider) are now both "Target Temp" — one term for the same
  concept everywhere in the panel instead of three different Danish/mixed labels for it.

## [0.25.0] — 2026-09-11

Panel overview tile requested by Flemming: the "Rum" quick-stats row undercounted what it
claimed to show once monitoring-only rooms (v0.24.1) and interior doors (v0.24.0) existed —
"Aktiv" included TRV-less rooms it had no business counting, and door state wasn't surfaced
at the overview level at all (only in Rum detaljer / Historik).

### Added

- **Panel — Oversigt**: two new quick-stats tiles, "Passiv" (🛋️, monitoring-only rooms with no
  TRV — Gang and friends) and "Åbne døre" (🚪, live count of open interior doors from each
  door sensor's `is_open`, same real-time-truth pattern as the existing "Vindue åbent" tile —
  turns red when > 0). Hovering "Åbne døre" lists which room-pairs are open, matching the
  existing "Vindue åbent" tooltip behaviour.

### Changed

- **Panel — Oversigt**: "Aktiv" now only counts rooms with `state === "normal"` AND a
  configured TRV (`climate_entity`) — a monitoring-only room in its default state moves to
  the new "Passiv" tile instead, so the six tiles (Aktiv/Fraværende/Passiv/Vindue åbent/Åbne
  døre/Forvarmning) stay mutually exclusive and sum to the total room count. A monitoring-only
  room that's genuinely away or has an open window still counts under those tiles, not
  "Passiv" — "Passiv" only catches the otherwise-uneventful case.
- **Panel CSS**: `.qs-grid` widened from 4 to 6 columns on desktop, with new breakpoints
  (3 columns ≤700px, 2 columns ≤380px) so the six tiles wrap sensibly on narrower panel widths.

## [0.24.2] — 2026-09-11

Second follow-up to the monitoring-only-room work, from putting "Gang" into real use: its front
door to the stairwell needed to be trackable (cold outside air, exactly like a window), and its
overview card was showing "Sætpunkt –" / "Trv batt –" as if something was broken.

### Added

- **`window_engine.py`**: a monitoring-only room (no TRV) can now have a `CONF_WINDOW_SENSORS`
  entry, for exactly Flemming's case — an exterior door to an unheated stairwell opening off a
  hallway that itself has no heat source. Opening/closing it now sets the room's state
  (`window_open`/`normal`) and logs a real event ("Window open/closed in `<room>` (no TRV —
  monitoring only)"), with a notification if `CONF_NOTIFY_WINDOWS` is on — same visibility as a
  real window, just no `climate.set_temperature`/restore calls since there's no TRV to call them
  on. Previously, `_open_after_delay()`/`_close_after_delay()` both returned immediately on a
  missing climate entity — no state change, no log event, only a `_LOGGER.warning()` nobody would
  ever see — so a monitoring-only room's window/door sensor was silently invisible everywhere
  Flemming actually looks.

### Fixed

- **Panel — Oversigt + Rum detaljer**: a monitoring-only room's card always showed "Sætpunkt –"
  and "Trv batt –" (Rum detaljer also always showed "Trv temp –"), reading as something missing
  or broken rather than the deliberate, expected state of a room with no TRV. Both views now show
  only "Rum temp" for such a room — the one stat that actually applies to it.

## [0.24.1] — 2026-09-11

Follow-up to v0.24.0's door feature, prompted by a real case: Flemming's "Gang" (hallway)
connects every other room, has its own temperature sensor, but no heat source of its own —
so it needs to exist as a room (doors can only connect two entries in `CONF_ROOMS`) without a TRV.

### Added

- **Monitoring-only rooms**: a room can now be saved in the config/options flow with zero TRVs
  — an explicit, labelled choice ("Save room without a TRV (monitoring only)"), not a silent
  gap. Verified every engine already tolerates this gracefully (`get_climate_entity()` returns
  `None`, every `for trv in get_room_trvs(room_name)` loop across the codebase simply no-ops on
  an empty list, `get_room_current_temp()` already reads `CONF_ROOM_TEMP_SENSOR` independently of
  any TRV, `migrate_room_to_trvs()` already had an explicit early-out for an empty TRV list).
  Lets a hallway/entryway/etc. be a real room with its own sensor and, via v0.24.0's interior
  doors, participate fully in the door graph and heat-up-rate learning for its neighbours.

### Fixed

- **`websocket.py`/panel**: a monitoring-only room previously would have shown a misleading
  "Netatmo" TRV badge (the `trv_type` field defaulted to `"netatmo"` even with no TRV at all) and
  a "Sætpunkt" target temperature that nothing actually enforces (`get_room_target_temp()` always
  returns a computed number regardless of TRV presence, but `_async_pid_tick()` never runs for a
  room with no climate entity to write to). Both are now `None`/omitted for a TRV-less room
  instead of showing hardware or a controlled setpoint that doesn't exist.

## [0.24.0] — 2026-09-11

Feature round from Flemming's 5-point request (interior doors, Indeklima sensor coupling,
config/options flow, mobile card). See `planning/heat_manager_features_2026-09-11.md` in the
project for the full decision write-up and the four approved scope choices this release
implements. The panel Settings tab and the mobile-card press-and-hold redesign (points 4 and 5)
are deferred to a separate Fase-2 spec — not part of this release.

### Added

- **Interior doors** — new `CONF_DOORS` config entity (contact sensor + the two rooms it
  connects), managed via a new "Manage interior doors" section in the options flow (mirrors the
  existing Rooms/Persons CRUD pattern: add/edit/delete, with validation for room_a ≠ room_b,
  no duplicate room-pair across doors, and sensor existence — a sensor already used as a window
  sensor elsewhere is allowed but logged as a warning, not blocked).
- **`engine/door_engine.py`** (new) — logs a real "Dør åbnet/lukket mellem X og Y" event
  (`event_type="door"`) every time a configured interior door genuinely opens or closes. Built
  restart-safe from day one using the same known-old-state guard as the 0.23.0 window/presence
  fix — no false door events from an HA restart or reload. Purely observational: an interior
  door has no heat-suppression meaning of its own (unlike an exterior window/door sensor), so
  this engine only logs, it never touches heating.
- **`coordinator.py`**: `doors` property, `get_room_doors()`, `get_door_other_room()`, and
  `is_room_door_open()` — the live (never cached) "is any door connected to this room currently
  open" check other engines and the frontend read.
- **`engine/calibration_engine.py`**: heat-up-rate learning — tracks, per room, two running
  averages (°C/hour) of how fast the room actually warms while heating is genuinely being
  called for, split by whether its interior door was open or closed during that interval
  (`get_room_heatup_rate(room_name, door_open)`). This is deliberately a *different* mechanism
  from the existing sensor-offset writer in the same file (that corrects a TRV's raw thermometer
  reading, a constant independent of door state; this tracks the room's thermal response, which
  genuinely does depend on it). In-memory only, resets on restart. Nothing reads these learned
  rates to change a control decision yet — informational groundwork only, matching the approved
  "visibility + learning" scope (a later, separate, larger decision would be needed before an
  open door in one room is allowed to actively adjust another room's target temperature).
- **Panel**: door status surfaced in "Rum detaljer" (🚪 Åben/Lukket, only for rooms actually
  connected to a configured door) and a new "Dør" filter chip in the Historik tab, separate from
  "Vindue" so interior door traffic doesn't dilute that filter.
- **`websocket.py`**: `get_state` payload gained a top-level `doors` list and, per room,
  `door_open`, `heatup_rate_door_open`, `heatup_rate_door_closed`.

### Changed

- **Config flow UX**: `CONF_OUTDOOR_TEMP_SENSOR`, `CONF_OUTDOOR_HUMIDITY_SENSOR`,
  `CONF_PRECIPITATION_SENSOR`, `CONF_WIND_SPEED_SENSOR`, `CONF_INDOOR_WAKE_SENSOR`,
  `CONF_CO2_SENSOR`, `CONF_ROOM_TEMP_SENSOR`, `CONF_BATTERY_SENSOR`, `CONF_HUMIDITY_SENSOR` were
  raw text boxes (type the entity_id yourself, no autocomplete) — now proper searchable entity
  pickers, using the same `default=... or vol.UNDEFINED` fix already proven on
  `CONF_WEATHER_ENTITY`/`CONF_SCHEDULE_ENTITY` (B17) so an empty optional field still saves
  correctly. Makes it trivial to find e.g. an Indeklima room sensor by typing "indeklima" or the
  room name into the picker's own search — addresses Flemming's point 3 (all external sensors
  come from the Indeklima project) without adding a hard dependency between the two integrations:
  a real, flexible, searchable picker rather than a restrictive integration filter (which HA's
  declarative entity selector schema cannot express as a soft "suggestion only" anyway).
  Verified backward-compatible: every downstream read of these 9 keys already tolerated an
  absent/empty value.

No test files were affected — `tests/components/heat_manager/` only covers `select.py`.

## [0.23.0] — 2026-09-11

Fixes false events in the Historik tab caused by HA restarts. User-reported: the event log
showed window-closed and "welcome home" events that never actually happened, clustered right
after a restart/reload. Root cause: `async_track_state_change_event` fires a state_changed event
the first time an entity's real state becomes known again after its platform re-establishes
itself (HA restart, integration reload, a brief radio dropout) — with `old_state` `None`/
`"unknown"`/`"unavailable"` — even though nothing physically changed. Several listeners treated
that as a genuine transition.

### Fixed

- **`window_engine.py`**: `_handle_sensor_change()` treated ANY state landing on `"off"` as a
  real close whenever the old state wasn't literally `"off"` — which is true for `"unavailable"`/
  `"unknown"` too. Every restart therefore logged a false "Window closed in `<room>` — heating
  resumed" line **for every already-closed window**, and made a real (unnecessary)
  `climate.set_preset_mode`/`set_hvac_mode` call to "restore" a room that was never actually
  suppressed. Now only reacts to a genuine flip between two *known* states (`"on"` ↔ `"off"`).
- **`window_engine.py`**: added `_check_initial_windows()` (mirrors `PresenceEngine`'s existing
  `_check_initial_presence()` / B11) — reads each window sensor's live state directly at startup
  and schedules suppression for any that's genuinely still open, through the normal open-delay
  path. Without this, the fix above would have silently stopped detecting a window that was
  already open across a restart.
- **`presence_engine.py`**: `_restore_all_schedule()`'s "Heating resumed — welcome home" event-log
  line fired unconditionally, even when called with `notify=False` — so `_check_initial_presence()`
  (which runs on every single startup while someone is home, i.e. almost always) logged a "welcome
  home" event that never happened, on every restart. Now gated behind `notify` like the push
  notification already was (B20).
- **`presence_engine.py`**: `_async_handle_alarm_change()` reacted to ANY alarm state with no
  regard for what it transitioned from — so a house that happened to be armed-away (or disarmed)
  across a restart got a false "Heating off — alarm armed" / "Heating resumed — alarm disarmed"
  log entry *and push notification* every time. Added the same known-old-state guard as the window
  sensor fix, plus a new silent `_check_initial_alarm()` (mirrors `_check_initial_presence()`) so
  an already-armed-away house is still correctly synced to away mode at startup — just without
  logging a fake event for it. `_set_all_away()` gained a `log: bool = True` parameter to support
  this silent path.
- **`presence_engine.py`**: `_async_handle_person_change()` gained the same known-old-state guard,
  for consistency (a person entity's own restart-time state artifact could otherwise start/cancel
  an internal grace timer for no reason, even though idempotency elsewhere mostly absorbed the
  visible symptom).

No test files reference any of the changed functions (`tests/components/heat_manager/` contains
only `test_select.py`), so no test updates were needed.

## [0.22.0] — 2026-09-11

Removes the "Energi i dag" (waste/savings/efficiency) feature entirely, at the user's request:
their radiators run on district heating (fjernvarme), not electricity, and there's no way to
meter water/heat flow — so the kWh figures this feature showed were never physically meaningful.
Also fixes a third instance of the `display`-vs-`[hidden]` bug from 0.21.0, this time via an
inline style.

### Removed

- **Backend**: `engine/waste_calculator.py`'s `WasteCalculator` is fully disconnected from the
  coordinator (import, instantiation, the 5 delegating properties `energy_wasted_today` /
  `energy_saved_today` / `efficiency_score` / `last_waste_time` / `last_saved_time`, the
  `async_tick()`/`async_shutdown()` calls). The file itself is left on disk — this tooling can't
  delete files on the live server — but it's now dead code and **safe to delete manually**.
  `tests/` has no `test_waste_calculator.py`, so no test cleanup was needed.
  - `sensor.py`: removed `EnergyWastedSensor`, `EnergySavedSensor`, `EfficiencyScoreSensor`.
  - `binary_sensor.py`: removed `HeatingWastedSensor`.
  - `const.py`: removed `CONF_ENERGY_TRACKING`, `CONF_ROOM_WATTAGE`, `DEFAULT_ROOM_WATTAGE`.
  - `config_flow.py`: removed the per-room "Rated wattage" field and the global "Energy tracking"
    toggle from the options flow.
  - `coordinator.py`: `_persist_energy_snapshot()`/`_energy_history` (the 30-day rolling energy
    history used only by the removed 7-day chart) are gone. The unrelated event-log persistence
    that used to share that function is kept, renamed to `_persist_event_log_snapshot()` — the
    event log (Historik tab) still survives HA restarts exactly as before.
  - `websocket.py`: removed the 5 energy fields from `heat_manager/get_state`, and removed
    `_build_daily_energy()` — `heat_manager/get_history` now returns only `events` (the `days`
    field is gone; nothing reads it anymore).
  - `diagnostics.py`: removed the `energy` block.
  - **Note for the user**: after upgrading, `Settings → Devices & services → Entities` will show
    the 4 removed entities (`sensor.heat_manager_energy_wasted_today`,
    `sensor.heat_manager_energy_saved_today`, `sensor.heat_manager_efficiency_score`,
    `binary_sensor.heat_manager_heating_wasted`) as unavailable/orphaned — safe to delete from
    there manually, HA doesn't do this automatically for custom integrations.
- **Frontend**: `heat-manager-panel.js` — removed the Oversigt tab's "Energi i dag" box and the
  Historik tab's "Energi — sidste 7 dage" bar chart, plus their now-dead CSS.
  `heat-manager-card.js` — removed the mobile card's "Energi i dag" section
  (`_hubEnergyWasted()`/`_hubEnergySaved()`/`_hubEfficiency()`/`_patchEnergy()`) and its CSS.

### Fixed

- The `#remote-last-action-box` ("📡 Fjernbetjening" pill) used an inline
  `style="display:flex"` in its template. Inline styles beat every stylesheet rule — including the
  `[hidden]` override added in 0.21.0 for the topbar chips — so this box was **permanently visible**
  as an empty pill (just the 📡 icon, no text) whenever there was no remote-control action in the
  last 30 minutes. Moved the layout into a `.remote-last-action-box` CSS class, covered by the same
  `[hidden]` override rule, so `box.hidden = true` (already set correctly by
  `_patchRemoteLastAction()`) now actually hides it.

## [0.21.1] — 2026-09-11

Fixes the mobile card's setpoint-source divergence that 0.20.0/0.21.0 both left as a known,
open limitation. Frontend-only (`heat-manager-card.js`).

### Fixed

- `heat-manager-card.js`'s per-room setpoint display read the room's configured `climate_entity`'s
  raw `temperature` attribute directly. Since the 0.19.0 (B21) fix, the PID no longer writes
  `comfort_temp` to that attribute for Netatmo rooms — it targets `get_room_target_temp()` and
  writes to the local HomeKit entity instead — so the card could show a number Heat Manager wasn't
  actually chasing, potentially differing from what the panel showed for the same room at the same
  time.

### Added

- New `_loadTargetTemps()` on the card: polls `heat_manager/get_state` every 60s (mirroring the
  panel's own poll cadence — never on every `set hass()` tick, which fires on every relevant
  state-bus event and would otherwise spam the backend) and builds a room-name → `target_temp` map.
  New `_roomSetpoint(room)` prefers this map, falling back to the old direct cloud-entity read when
  the fetch hasn't completed yet or a room's config name isn't found in the backend's room list.
  The card receives the same full `hass` object (and thus `callWS()`) a panel does — the earlier
  "card has no websocket access" framing (`audit/heat_manager_fixes_2026-09-11_fase2.md`) was a
  scope choice for that round, not a hard technical limitation.

## [0.21.0] — 2026-09-11

Statustjek follow-up on today's Fase 2 (0.20.0), triggered by a live
screenshot of the panel after deployment — see
`audit/heat_manager_status_check_2026-09-11.md`. Frontend-only: no backend
Python changed this round.

### Fixed

- **Confirmed, real bug**: `#cloud-chip`, `#health-chip` and `#ws-error-chip`
  each set `display` unconditionally in their own CSS class
  (`heat-manager-panel.js`). Author-origin CSS always wins over the
  browser's default `[hidden] { display: none }` rule regardless of
  selector specificity, so `chip.hidden = true/false` had **no visual
  effect on any of the three**. `#cloud-chip`/`#health-chip` were
  permanently visible as empty pills (their label is only ever populated
  when there's an actual issue) and `#ws-error-chip`'s "Ingen forbindelse"
  was almost certainly showing all the time — defeating the entire point
  of the 2026-09-07 UI/UX-2 fix it exists for. Added the missing
  `.cloud-chip[hidden], .ws-error-chip[hidden] { display: none; }`.
- `_cloudStatus()` (panel) previously only reported a problem when *every*
  configured room's Netatmo climate entity was unavailable at the same
  time — a partial outage (say 2 of 5 rooms down) silently reported
  `ok: true` and the chip never showed at all. Now surfaces three distinct
  states.
- `_render()` (panel's full first-render path) was missing the
  `_patchWsErrorChip()`/`_patchRemoteLastAction()` calls that `_patchAll()`
  already had — both could sit stuck in their template-default hidden
  state for up to a 60s poll cycle after a fresh page load.

### Added

- Panel's cloud-status chip now distinguishes **all rooms down** (labelled
  "Netatmo cloud/gateway nede" — the closest available proxy to a
  cloud-vs-gateway signal, since HA's own Netatmo integration exposes no
  separate reachable/connectivity attribute for thermostat/valve devices;
  confirmed against `home-assistant/core`'s `netatmo/climate.py` and
  `binary_sensor.py`), **some rooms down** (labelled "Netatmo: X/Y rum
  nede", most likely a single device's battery/RF, not cloud or gateway),
  and **stale-but-available** (cloud responding, not updating).
- `#ws-error-chip` now shows the last-known-good time ("Ingen forbindelse —
  sidst OK kl. HH:MM") instead of a static, undated message.
- **New on the mobile card** (`heat-manager-card.js`): a `#cloud-status-row`
  mirroring the same three-state Netatmo cloud/gateway logic, computed
  client-side from `hass.states` (the card has no `get_state()`/websocket
  access). Previously the card had per-room "TRV offline" badges but
  nothing telling the person whether one room's device had a flat battery
  or the whole house's Netatmo connection was down — those looked
  identical, one badge at a time, unless counted.

### Known limitation (unchanged this round)

- A true third "gateway" layer, distinct from "Netatmo cloud", is not
  observable from HA's own Netatmo integration for thermostat/valve
  devices — only `weather`/`air_care`/`opening` device categories get a
  dedicated connectivity `binary_sensor`; `THERM` (thermostats/valves)
  does not, so a climate entity's own `state` already folds cloud +
  gateway/relay + device into one. The "all rooms down together" vs. "one
  room down" split above is the most specific signal available without
  requiring new configuration from every room.
- Mobile card's setpoint-source divergence (from 0.20.0's Known
  limitation) is still open — not addressed this round.

## [0.20.0] — 2026-09-11

Fase 2 of the target-temp fix (0.19.0): visibility + Netatmo mode control,
per the user's original requests 2 and 3 (`select.mit_hjem`-style
visibility/control, and surfacing `hvac_modes`/`min_temp`/`max_temp`/
`target_temp_step`/`preset_modes`/`current_temperature`/`temperature`/
`hvac_action`/`preset_mode`/`selected_schedule`).

### Added

- **`select.<room>_netatmo_preset_mode`** — new per-room select entity
  (one per room with a Netatmo/cloud TRV; skipped for Zigbee-only rooms)
  that reads and writes the room's cloud climate entity's own
  `preset_mode` (away/frost_guard/boost/schedule) directly via
  `climate.set_preset_mode`, serialised through
  `coordinator.async_call_climate_service(..., needs_delay=True)` like
  every other preset_mode call site in the codebase. This is the
  `select.mit_hjem`-equivalent the user asked for, as a first-class HA
  entity usable from any dashboard — not duplicated Heat Manager state,
  just a thin pass-through to Netatmo's own mode. `CONFIG` category,
  enabled by default.
- `HeatManagerCoordinator.get_room_target_temp(room)` — the single
  resolved-target helper `_async_pid_tick()` and `ws_get_state()` both
  now call, so the panel can never show a different number than what the
  PID is actually chasing.
- `ws_get_state()` room payload gained 10 new fields: `target_temp`
  (Heat Manager's own resolved target) plus 9 read-only `cloud_*`
  diagnostics straight from the room's Netatmo cloud climate entity —
  `cloud_temperature`, `cloud_hvac_action`, `cloud_preset_mode`,
  `cloud_preset_modes`, `cloud_selected_schedule`, `cloud_hvac_modes`,
  `cloud_min_temp`, `cloud_max_temp`, `cloud_target_temp_step`. All
  `None` for Zigbee/local rooms (no separate cloud entity to read).
- Panel (`heat-manager-panel.js`) room-detail view now shows a Netatmo
  diagnostics block (cloud preset mode, selected schedule, hvac action,
  cloud temperature) with an amber warning when the cloud's own
  temperature diverges ≥0.5°C from Heat Manager's `target_temp` — makes
  a future B21-style drift visible immediately instead of silently.

### Fixed

- Panel's room "Sætpunkt" display read the Netatmo cloud entity's
  `temperature` attribute directly — after the 0.19.0 (B21) fix, PID no
  longer writes to that entity for Netatmo rooms, so this would have
  shown a stale/wrong value. Now reads the same resolved
  `get_room_target_temp()` value as the PID via a new `_roomSetpoint()`
  helper, for all three places the panel renders a room's setpoint.

### Known limitation

- `heat-manager-card.js` (the separate mobile card) still reads its
  configured `climate_entity`'s raw `temperature` attribute for its own
  setpoint display and was **not** changed this round — it has no access
  to the coordinator's `get_room_target_temp()` (WS-API only). If that
  card's `climate_entity` points at a room's Netatmo cloud entity, its
  displayed setpoint can now diverge from the panel's. Point the card's
  per-room config at each room's local/HomeKit climate entity instead of
  the cloud one, or expect this divergence until the card is reworked to
  read `target_temp` from `heat_manager/get_state` like the panel does.

## [0.19.0] — 2026-09-11

### Fixed

- **B21 — Netatmo rooms ignored `comfort_temp`, chasing the cloud schedule's
  own setpoint instead.** `_async_pid_tick()`'s HomeKit split-entity path
  read `target_temp` from the Netatmo cloud climate entity's own
  `temperature` attribute — i.e. whatever Netatmo's own app-side schedule
  (e.g. "Vinter") currently dictated — completely bypassing the room's
  configured `comfort_temp`, which was silently ignored for every Netatmo
  room (it only ever applied to local Zigbee/Matter rooms). Reported
  symptom: rooms heating to 24–26°C instead of the configured 21°C target,
  with no way to see the discrepancy since the panel never exposed a
  setpoint field. Heat Manager is now the sole authority for room target
  temperature for every TRV type — `comfort_temp` is authoritative for
  Netatmo rooms too, layered under schedule_override/room_offset/setbacks
  exactly as it already was for local rooms. PID still writes only to the
  local HomeKit entity (unchanged) — no new Netatmo cloud API calls are
  introduced. Full analysis:
  `audit/heat_manager_target_temp_analysis_2026-09-11.md`.
  **Action required:** `comfort_temp` defaults to 20°C per room and was
  previously decorative for Netatmo rooms — verify/set it correctly for
  every Netatmo room in Settings → Heat Manager after upgrading, or those
  rooms will target 20°C instead of your intended value until you do.

## [0.18.2] — 2026-09-10

Hotfix for a regression from 0.18.0's own "Fixed" section (E).

### Fixed

- `panel.py::_get_version()` reads `manifest.json` with a blocking
  `open()`/`json.load()` call. 0.18.0 (E) started calling it directly from
  `async_register_static_paths()` and `async_register_panel()` — both run
  on the event loop — which HA's `homeassistant.util.loop` blocking-call
  detector flagged in production (`Detected blocking call to open... by
  custom integration 'heat_manager' at .../panel.py, line 45`). Both call
  sites now resolve the version via `hass.async_add_executor_job(
  _get_version, hass)` before using it, instead of calling the blocking
  function inline.

## [0.18.1] — 2026-09-10

Frontend/config dead-code sweep — "alt vi har på frontend eller i konfig
skal være i brug og være funktionel eller fjernes". Follow-up to 0.18.0:
that audit covered the backend only; this round covers the panel
(`heat-manager-panel.js`) and the config surface, plus one piece of
self-cleanup left behind by 0.18.0 itself.

### Removed

- The panel's config tab still showed two "Away temp mildt"/"Away temp
  koldt" rows reading `away_temp_mild`/`away_temp_cold` — both settings
  were removed from the backend in 0.18.0 (B.1), so these always rendered
  "–". Removed the rows.
- Two grayed-out "🔥 Boost til"/"🔥 Boost slut" badges in the House Voice
  section had no backend support — `async_house_voice_say()` is never
  called for boost events anywhere in the codebase. Removed; the 4 real
  badges (Pause/Sluk/Sommer/Vinter) are unaffected.
- `const.VERSION` — orphaned by 0.18.0's own fix (E): once `panel.py`
  started reading the version from `manifest.json` at runtime, this
  second, independently-maintained copy had no remaining reader anywhere
  in `custom_components/heat_manager` or `tests/`. Removed rather than
  left to go stale again.
- Per-room `"why"` field (`_why_label()`) — an English one-line reason
  string computed from `room_state` every tick and sent in every payload,
  but never read by either frontend file. Both panels already derive all
  of their state-driven UI (badges, colors, filters, quick-stat counts)
  directly from `room.state` itself, so this was a pure duplicate with no
  functional gap behind it — removed rather than displayed.
- Per-room `"heating_power"` field — always numerically identical to
  `valve_position` for Netatmo rooms (it *is* the source value
  `valve_position` is set from) and stale/superseded once
  `pi_demand_entity` overrides `valve_position` for Zigbee rooms. No
  reader ever used it separately from `valve_position`. The underlying
  `heating_power_request` attribute read is still used internally to
  compute `valve_position` — only the redundant duplicate key was
  dropped from the payload.

### Fixed

- `CONF_OUTDOOR_TEMP_SENSOR` — a real, functional setting (the
  coordinator prefers it over the weather entity for outdoor temperature)
  — was configurable and the panel's config tab has always had a row for
  it, but the value never reached `ws_get_state()`'s payload, so the row
  always showed "–". Wired into `config_snap`.
- `auto_off_reason` was computed by the backend every tick and sent in
  every payload, but nothing displayed it — the "Slukket" badge gave no
  indication of *why* the system had turned itself off. The panel's
  auto-off badge now appends the reason ("sæson"/"temperatur") when set.
- `open_windows` (0.18.0, B.3) was added to the payload but the fix
  stopped there — no frontend ever displayed it, so the underlying gap
  ("implemented but never surfaced") was only half-closed. Completed:
  the overview's "Vindue åbent" card now shows the live sensor-level list
  as a tooltip.
- `energy_saved_today`/`energy_wasted_today`/`efficiency_score`/
  `last_waste_time`/`last_saved_time` were computed and sent in every
  payload (mirrors the real `sensor.heat_manager_energy_*` entities the
  mobile card already reads directly), but the panel's own "Energi i dag"
  display had been removed as dead code back in 0.17.2 — the data kept
  flowing with nothing showing it. Restored as a compact "Energi i dag"
  box in the overview (spildt/sparet, with an efficiency badge and last
  event timestamps).

## [0.18.0] — 2026-09-10

Backend deep-dive audit (2026-09-10) — fixes for every finding, applied
across the board rather than one at a time.

### Fixed

- **Critical**: 13 call sites (coordinator's PID tick, `__init__.py`
  startup reachability check + RepairIssue creation, `diagnostics.py`,
  `waste_calculator.py`, `calibration_engine.py`, 4 sites in
  `binary_sensor.py`, 2 in `sensor.py`, `switch.py`) read a room's
  `climate_entity`/`calibration_entity` via the flat, un-persisted mirror
  field instead of `coordinator.get_climate_entity()` /
  `get_room_calibration_entity()` — for any room saved through the
  per-TRV edit UI (B18), that flat field was never written back to the
  config entry, so these all silently saw an empty/stale value. Worst
  case: **the PID controller silently skipped such a room entirely**,
  every tick. Config flow now also re-syncs the flat mirror at save time
  (`migrate_room_to_trvs()`) as a compatibility safety net for any reader
  that still uses it directly.
- The 3 physical remote-button entities (`RemoteButtonEngine`) and the
  alarm-panel entity (`PresenceEngine`) were only ever subscribed once, in
  `__init__` — re-assigning either in the options flow had no effect until
  something else (a room edit) happened to trigger a full reload. Both
  engines now expose a `rebuild_listeners()`/`rebuild_alarm_listener()`
  method, called unconditionally from `_async_update_listener()` whenever
  an options write doesn't already reload the whole entry.
- `ws_set_room_temp`'s `duration_min` was accepted and logged but never
  actually wired to anything — a manual panel temperature override stayed
  in effect forever regardless of the requested duration. The coordinator
  now tracks a per-room expiry and auto-restores the schedule once it
  elapses, checked every tick alongside boost expiry.
- `panel.py` read its cache-busting version from `const.VERSION`, a
  second, independently-maintained copy of the version that had already
  drifted from `manifest.json` once before. Now reads `manifest.json`
  directly at runtime — that class of drift can't recur.
- `ValveProtectionEngine.async_shutdown()` cancelled its in-flight
  exercise-sweep task but never awaited it, so the cancellation (and
  whatever `except`/`finally` cleanup it triggers) could still run after
  the rest of the integration had already been torn down.
- `window_engine.py` read `"window_warning_min"` and `"notify_service"` as
  magic strings instead of the `CONF_*` constants — `DEFAULT_WINDOW_WARNING_MIN`
  existed with no matching config key, so there was no way to actually set
  it from the UI. Added `CONF_WINDOW_WARNING_MIN` and a config_flow field
  for it.
- `RoomOverrideSwitch` (`switch.py`) stored a `climate_entity` on itself
  that was never read anywhere — removed.
- `window_engine.get_open_windows()` was fully implemented but never
  surfaced anywhere — `ws_get_state()` now includes it as `open_windows`.

### Removed

- `away_temp_mild` / `away_temp_cold` / `mild_threshold` (and
  `coordinator.get_away_temperature()`) — these config fields existed in
  the UI and were read by `ws_get_state()`'s config snapshot, but nothing
  in the actual heating logic ever called `get_away_temperature()`: a
  Zigbee room's AWAY state turns the valve fully off (`hvac_mode: off`)
  and a Netatmo room uses `preset_mode: away` — neither path used a
  computed away temperature. Removing dead configuration rather than
  wiring it up, since the existing off/away behaviour is intentional.
  **No change to actual heating behaviour.**

## [0.17.2] — 2026-09-08

Frontend/websocket polish pass — three streams: broader health-check
coverage, mobile (card.js) parity with the panel, and a couple of small
performance/code-quality fixes found along the way.

### Added

- `ws_get_state()` now reports `pid_power`, `calibration_offset` and
  `window_duration_today` per room, and `unavailable_entities` — every
  entity a room actually depends on (all TRVs, not just the primary;
  window/humidity/CO2/battery sensors) that is currently missing,
  `unavailable` or `unknown`. All 4 were computed by the backend already
  but only ever visible via HA's own entity page.
- Panel: new "Rum detaljer" chips for PID power, calibration offset and
  window-open-minutes-today. New topbar "entity health" chip
  (`_patchHealthChip()`), separate from the existing Netatmo cloud chip —
  it flags a genuinely unavailable *non-Netatmo* entity (a dead
  window-sensor battery, say) that the cloud chip's Netatmo-only check
  never saw.
- Card (mobile): the same 3 diagnostic values as chips on each room card,
  plus a lightweight "TRV offline" badge (checks the one entity this
  card's own per-instance config stores — `climate_entity`; unlike the
  panel it has no websocket connection and never stores `window_sensors`).
  New Hub-level "Energi i dag" section (wasted/saved kWh + efficiency %).

### Fixed

- `RoomWindowDurationSensor`/`RoomPidPowerSensor`/`RoomCalibrationOffsetSensor`
  had a doubled room name baked into their friendly name (e.g. "Bathroom
  Bathroom window duration") — `has_entity_name` already prefixes the
  room device's own name, so the room name in `_attr_name` doubled up.
  Never noticed before because these 3 sensors were
  `entity_registry_enabled_default=False`; flipping that on (see below)
  made it visible, and the mobile card's friendly-name discovery needed
  it fixed to find them at all.
- `EfficiencyScoreSensor`, `RoomWindowDurationSensor`, `RoomPidPowerSensor`
  and `RoomCalibrationOffsetSensor` were `entity_registry_enabled_default
  =False` — invisible to both frontends (and to `hass.states` lookups)
  without the user manually enabling each one first. Same policy already
  applied to the v0.15.0 mirror sensors.

### Changed

- `_async_pid_tick()` resolved each room's TRV list 3 times per room per
  tick (via `get_room_current_temp()`'s internal
  `get_homekit_climate_entity()` call, its own direct call to that method,
  and `get_room_trvs()` for the write loop) — all 3 recomputing
  `migrate_room_to_trvs()` from scratch. `get_all_room_trvs()` now has an
  internal per-tick cache, activated only for the duration of one PID
  tick; every other one of its ~29 call sites elsewhere in the codebase is
  unaffected.
- Removed the dead full-width `_cloudBannerHTML()` in panel.js — superseded
  by the compact topbar chip since v0.16.0 and never actually called.

## [0.17.1] — 2026-09-08

Fixes 429 "Too Many Requests" and follow-on 503 "Service Unavailable"
errors from Netatmo's `setthermmode` API, seen in the log as
`window_engine`/`presence_engine` warnings ("Failed to restore schedule
in/on ...") when several rooms' heating was restored around the same
moment.

### Fixed
- **Netatmo rate-limit race across engines/rooms.** Every engine that
  writes to a Netatmo TRV paced *its own* sequential calls with
  `asyncio.sleep(NETATMO_API_CALL_DELAY_SEC)`, but nothing serialised calls
  *across* engines, rooms, or concurrent asyncio tasks. `window_engine.py`
  additionally had no pacing at all in its window-close restore path, and
  runs each room's restore as an independent `async_create_task()` — so
  several windows closing within the same debounce window fired
  simultaneous, unpaced Netatmo calls and tripped the API's rate limit;
  the resulting 503s ~15-20 min later look like fallout from the same
  throttling window. Added `coordinator.async_call_climate_service()`,
  backed by a single coordinator-wide `asyncio.Lock`, as the one place any
  engine now sends a `climate.*` service call — every Netatmo-bound call,
  regardless of triggering engine/room/task, is serialised and paced
  through it; HomeKit-bound calls skip the lock entirely (local, no rate
  limit). Migrated `presence_engine.py` (`_set_all_away`,
  `_restore_all_schedule`, `force_room_on` — the last of which had no
  pacing at all before this fix either), `window_engine.py`
  (`_schedule_close`), `controller.py` (`_apply_off_fallback`), and
  `valve_protection_engine.py` (weekly valve exercise) to use it.
- **`controller.py` `_apply_off_fallback()`:** the cloud-preset_mode branch
  (`preset_mode: schedule`, which always targets the cloud entity) decided
  whether to pace/lock using the room's *primary*-TRV HomeKit reachability
  instead of "this call always goes to cloud" — a reachable HomeKit entity
  on the primary TRV could wrongly skip pacing for a call that never
  reaches HomeKit. Now always paced.
- **`valve_protection_engine.py` exercise loop:** paced/locked based on the
  configured `trv_type` (`!= zigbee`) rather than whether the resolved
  `write_entity` actually was the cloud entity — a Netatmo TRV with a
  currently-reachable HomeKit entity took the Netatmo lock unnecessarily.
  Now decided by `write_entity == climate_id`.

## [0.17.0] — 2026-09-07

More of the data the backend already computed is now actually shown on the
room cards, on both the Oversigt-fane (PC panel) and the mobile card —
follow-up to the 0.16.0 audit's frontend/backend-parring findings (5.1-5.3,
5.6, 5.9), picked up again the same day at the user's request for "mere
nyttigt info/data" on both surfaces.

### Added
- **Mold-risk badge (5.3).** `binary_sensor.py`'s `MoldRiskSensor` computed
  a dewpoint-based mold-risk signal per room but it was never surfaced
  anywhere. `ws_get_state` now includes a `mold_risk` boolean (recomputed
  from the same humidity/current_temp values already fetched for other
  fields, using the same Magnus-formula thresholds as `MoldRiskSensor`,
  intentionally duplicated to avoid a cross-platform import) — shown as a
  "⚠️ Skimmelrisiko" badge on the panel's Oversigt cards, and independently
  discovered via the room's own `<room> Mold risk` mirror entity on the
  mobile card (which has no `get_state` connection of its own).
- **Humidity + CO2 chips on Oversigt cards (5.2 follow-up).** Already shown
  in the Rum-detaljer tab; now also on the Oversigt grid cards, for rooms
  where the relevant sensor is configured.
- **Humidity + CO2 + battery chips, and a valve-% badge, on the mobile
  card (5.1-5.3 mobile).** The card only stores `room_name`/`climate_entity`
  per room and has no `get_state` connection, so these are read directly
  off `hass.states`: humidity/CO2/battery via the room's v0.15.0 mirror
  sensors (`sensor.<room> Humidity/CO2/Battery`, matched by
  `friendly_name` — the same discovery pattern already used for the
  group-toggle switch), and valve % via the `heating_power_request`
  attribute on the room's own `climate_entity` (Netatmo rooms; Zigbee rooms
  without that attribute simply show no valve badge, same graceful omission
  already used for missing humidity/CO2/battery). No new card configuration
  required.
- **Sync-mode / schedule / TRV-count meta row on Oversigt cards (5.6,
  5.9).** These were already in the `get_state` payload (config-only
  fields, no standalone entity to mirror) but shown only in the
  Rum-detaljer tab. Panel-only — the mobile card's architecture has no way
  to read config-level fields without a `get_state` call, so this one stays
  PC-only for now.

### Deliberately still not done
- Full card.js/panel.js data parity (sync-mode, schedule, TRV-count on
  mobile) would require either giving the card its own websocket
  connection or duplicating more config into the card's own configuration
  — a bigger architectural change than this pass, left for a future
  session if it turns out to matter in practice.

## [0.16.0] — 2026-09-07

Backend/frontend audit fix pass. A deep-dive review (loose ends, dead code,
hardening, load times, frontend/backend parity, UI/UX) produced a report of
~50 findings across 6 categories; this release addresses effectively all of
them. Full report: `audit/heat_manager_audit_2026-09-07.md`.

### Fixed (loose ends)
- `notify_window_warning_30` and `energy_tracking` config options were
  configurable in the options flow but silently did nothing —
  `window_engine.py`'s 30-min escalation notify and `waste_calculator.py`'s
  entire `async_tick()` now actually gate on them (default `True`, so
  existing installs see no behaviour change unless the option is toggled).
- The panel's "Send temperatur" action (`ws_set_room_temp`) never engaged
  `RoomState.OVERRIDE` — a manually-set temperature looked identical to a
  normal schedule-driven one to the rest of the coordinator (presence/window
  logic could silently override it on the next tick) and to the frontend
  (no "Override" badge). It now marks the room OVERRIDE with
  `room_override_source = "panel"`, consistent with the override switch and
  the remote-button engine.
- `heat_manager.force_room_on` existed as a service since `presence_engine.py`'s
  earliest version with no UI element calling it — added a "⚡ Tving til"
  button per room in the panel's Rum tab.
- The domain's 6 services (`set_controller_state`, `pause`, `resume`,
  `force_room_on`, `boost_start`, `boost_stop`) were registered in
  `async_setup_entry` but never unregistered in `async_unload_entry` —
  fixed, guarded so a still-loaded config entry never loses its services
  (services are only removed once no entry remains).
- Frontend version banners were badly stale — `heat-manager-panel.js` said
  "0.3.10" (since before v0.9.1) and `heat-manager-card.js` said "0.4.3"
  (since before v0.9.0). Both now say 0.16.0 and are bumped alongside
  `manifest.json` going forward.
- `const.py`'s `VERSION` constant — used in the panel/card static-asset
  cache-busting query string — had been stuck at `"0.9.0"` since before
  v0.10.0 while `manifest.json` kept advancing normally. Now kept in sync.
- `STATUS.md` refreshed (was last updated 2026-09-04 at v0.13.2).

### Removed (dead code)
- `coordinator.get_window_sensors()` — never called anywhere.
- `heat-manager-panel.js`: `_patchEnergyToday()`, `_reasonLabel()`,
  `_seasonTriggerLabel()`, `_energyTodaySectionHTML()`, and (as a direct
  consequence — their only remaining callers) `_energyTodayInnerHTML()` and
  `_ringColor()` — all leftovers from the "Energi i dag" card removed in
  0.15.0.
- `heat-manager-card.js`: the dead `.room-homekit` change listener in the
  card editor — the corresponding input field was removed from `_render()`
  long ago, so it never fired.

### Fixed (hardening)
- `coordinator.py`'s PID tick: `float(trv_current_setpoint)` ran *outside*
  the per-TRV `try/except`, so one TRV reporting a non-numeric `temperature`
  attribute aborted PID regulation for every room after it in that tick.
  Now guarded independently per TRV.
- `ws_set_room_temp`: an empty `write_entities` list (no reachable write
  entity for the room) fell through to a `success: True` response with no
  TRV actually commanded and a misleading "temperature set" event-log
  entry. Now returns a `not_found` error before attempting anything,
  mirroring the existing check for the schedule-restore branch.
- `engine/valve_protection_engine.py`'s weekly valve exercise `await`ed its
  full per-TRV sweep directly from `async_tick()` — with N TRVs each held
  open for 30 s plus a stagger delay, this blocked the coordinator's entire
  60 s tick cycle (every room's PID/window/presence logic) for several
  minutes, once a week, during the 02:00–03:00 window. Now runs as a
  background task (`hass.async_create_task`), cancelled cleanly on
  `async_shutdown()`.
- Room-temperature readings (`coordinator.get_room_current_temp()`,
  `calibration_engine.py`'s `_read_float()`/`_read_trv_raw_temperature()`)
  had no sanity range — a glitching sensor reporting e.g. -200°C or 3000°C
  instead of going `unavailable` would have been fed straight into the
  PID loop / calibration offset. Now clamped to a -20…50°C plausible range;
  out-of-range readings are treated as unavailable.
- `waste_calculator.py`'s `_get_heating_power_pct()` had no 0–100% clamp on
  either return path (`pi_demand_entity` or `heating_power_request`).
- `panel.py` / `websocket.py`: two `_LOGGER.error(f"...: {err}")` calls
  swapped for `_LOGGER.exception(...)` so the full traceback is logged, not
  just the exception's string.
- `config_flow.py`: 6 schema-builder functions (`_step1_schema`,
  `_trv_schema`, `_room_schema`, `_person_schema`, `_notifications_schema`,
  `_remote_control_schema`) used a mutable `dict = {}` default argument.
  Switched to `dict | None = None` with an explicit `defaults = defaults or {}`.
- `season_engine.py`: the "no outdoor weather data" fallback (spring/autumn,
  safe-default-to-ACTIVE branch) skipped `_maybe_trigger_voice()` and the
  `_prev_effective_season` update that every other branch performs — a
  missing/unavailable weather entity could mean a season-change voice
  announcement never fires and never re-fires. Now matches every other
  branch.

### Changed (load times)
- `heat-manager-panel.js` polled `heat_manager/get_state` every 30 s while
  the backend coordinator only ticks every 60 s (`SCAN_INTERVAL_SECONDS`) —
  half of every poll re-fetched an identical snapshot. Interval raised to
  60 s.
- `panel.py`'s static paths for the panel/card JS were served with
  `cache_headers=False`. Both are always requested with a
  `?v=<VERSION>&m=<mtime>` cache-busting query string, so a long-lived
  browser cache is safe — an update bumps `VERSION` and/or the file's
  mtime, producing a brand-new URL. Switched to `cache_headers=True`.
- `_patchRoomsTab()` rebuilt the entire Rum tab via `innerHTML` on every
  poll, which could reset a slider's DOM node — and whatever value the user
  was mid-drag toward — out from under their finger. Poll-driven rebuilds
  now defer themselves while a slider drag is in progress (tracked via
  `pointerdown`/`pointerup`/`change`) and catch up on the next poll after
  release.

### Fixed (frontend/backend parity)
- `heat_manager/get_state` now includes `remote_last_action`, `wind_speed`
  and `precipitation` — all already computed/tracked backend-side but
  never reaching the panel/card payload at all.
- Panel: wind/rain icons next to the outdoor-temperature header line;
  a "📡 Fjernbetjening" strip on the Oversigt tab showing the global
  remote's most recent action while it's less than 30 minutes old; a
  "🪟 venter" badge on a room card when `windows_open` (the raw sensor
  reading, already computed but never shown) is true while the room's
  state hasn't flipped to `window_open` yet — surfaces the "physically
  open, still inside the close/open delay" window that was previously
  invisible.
- `season_mode`, `heating_power` (largely redundant with `valve_position`
  for Netatmo — `heating_power_request` *is* valve % there; only Zigbee
  rooms with a separate `pi_demand_entity` would show a distinct value),
  `MoldRiskSensor`,
  `RoomPidPowerSensor`/`RoomWindowDurationSensor`/`RoomCalibrationOffsetSensor`,
  a full mobile energy/efficiency overview, an `indoor_wake_sensor` payload
  field, and visually distinguishing editable vs. read-only fields on the
  Konfiguration tab remain as documented gaps in the audit report — out of
  scope for this pass; each already has an HA entity of its own (several as
  of the 0.15.0 mirror layer) even where the panel/card don't surface it.

### Fixed (UI/UX)
- The panel silently stopped polling after 4 consecutive `get_state`
  failures, freezing on stale data with no indication anything was wrong.
  It now retries forever; a persistent "Ingen forbindelse" chip in the
  topbar and a toast (on the 1st failure and every 5th thereafter) make a
  failing connection visible instead.
- Controller actions (On/Pause/Off/Genoptag) in the panel, and every
  action in the card (which had **no error UI at all** — not even a
  reliable `console.error`), now show a toast on failure.
- "Sluk hele huset" (the Off button, panel and card) had no confirmation —
  click-to-arm added (second click within 3s confirms; non-blocking, no
  native `confirm()` dialog).
- Low TRV battery was colour-coded (amber ≤30%, red ≤15%) only in the Rum
  tab — the same value on the Oversigt tab's room cards showed no warning
  colour at all. Now consistent.
- "On"/"Off" (English) next to "Varme aktiv"/"Slukket" (Danish) on the same
  screen, in three separate places across panel.js/card.js — unified to
  "Tænd"/"Sluk" (buttons) and the existing `_ctrlTitle()` Danish mapping
  (topbar badge, both files).
- `title=""` tooltips on the per-room blocking-reason badge never fire on
  touch. Card now also shows the full reason as a toast on tap; panel's
  hover tooltip is unchanged for desktop.
- Toast containers (`role="status" aria-live="polite"`) in both panel and
  card, so screen readers announce action feedback.
- Cloud/health checks covering only Netatmo climate entities (not
  window/battery/humidity/CO₂/Zigbee sensors) remains a documented gap —
  a materially larger feature, out of scope for this pass.

### Added
- New global remote-control config step ("Remote control" in the options
  flow) supporting a physical remote such as the Aqara Climate Sensor
  W100, which exposes 3 separate `event.*` entities. All 3 entities are
  configurable (not hardcoded to one device model): a temp-up and a
  temp-down entity nudge every configured room's setpoint by ±0.5°C at
  once (skipping rooms currently in a WINDOW_OPEN or AWAY state, and
  automatically switching a room still in auto/NORMAL to manual/OVERRIDE
  first), and a mode-toggle entity switches every eligible room between
  auto and manual together. Only a single click triggers an action —
  hold/double-click are ignored in this first version. New
  `engine/remote_button_engine.py`. The TRV-command routing shared with
  the existing per-room override switch was factored into
  `coordinator.async_set_room_override()` so both callers use identical
  logic. Every room now records who last engaged its override
  (`coordinator.room_override_source`, exposed via the websocket API and
  the room's state sensor entity) — the room cards on the Oversigt and Rum
  tabs show a "📡 Fjernbetjening" badge instead of the plain "Override"
  pill when the remote (not the manual switch) is holding a room in manual
  mode. Actions taken via the remote are also logged to the existing
  event log (Historik tab) with reason "Remote" and a description of
  exactly what changed.
- Room detail rows (Rum-fanen) now show a 4-stat row per room: room
  temperature, setpoint, TRV temperature and TRV battery level — room
  temperature and TRV temperature were previously conflated into a single
  "Aktuelt" value that always showed the TRV's own reading, even when a
  `room_temp_sensor` was configured for that room.
- Room overview cards (Oversigt tab) now show room temperature, setpoint
  and TRV battery level (previously temperature and setpoint only, and the
  temperature shown was the TRV's own reading rather than `room_temp_sensor`
  when configured).
- New optional per-room config field `battery_sensor` — a `sensor.*` entity
  reporting TRV battery level (%). When unset, `ws_get_state` falls back to
  a `battery_level` attribute on the room's `climate_entity`, if present.
- Room detail rows show humidity and CO₂ readings when `humidity_sensor` /
  `co2_sensor` are configured for the room (previously collected for mold
  risk / waste weighting only, not surfaced in the UI).
- Heat Manager's own room and Hub devices on the HA Integrations page now
  also carry lightweight diagnostic "mirror" entities for every raw sensor
  the user has actually configured for that room or globally, so a
  missing/failing one is visible at a glance without hunting through
  whichever other integration actually created it. These are read-through
  mirrors, not new duplicate entities Heat Manager owns the data for: per
  room, `room_temp_sensor` / `humidity_sensor` / `co2_sensor` /
  `battery_sensor` and every entry in `window_sensors`; under the Hub,
  `outdoor_temp_sensor` / `outdoor_humidity_sensor` / `precipitation_sensor`
  / `wind_speed_sensor` / `indoor_wake_sensor` / `weather_entity` /
  `alarm_panel`. Each mirror greys out exactly when its source entity does.
  Also new under the Hub: "Remote last action" — not a mirror but a small
  new piece of coordinator state (`coordinator.remote_last_action`, written
  by `engine/remote_button_engine.py`) recording the timestamp, description
  and affected rooms of the global remote's most recent button press, so
  its effect is visible without digging through the History tab.

### Removed
- "Energi i dag" card removed from the Oversigt tab. It modelled estimated
  heat output from valve-open time × a configured room wattage — not a
  measured value, and not electricity consumption (heat comes from
  district heating; the TRVs themselves run on battery) — which made the
  kWh figures look more precise than they were. The underlying
  `waste_calculator` engine and the 7-day energy chart on the Historik tab
  are unchanged.

### Changed
- `STATUS.md` — synced with reality: GitHub/HA-server version (both 0.13.2,
  confirmed deployed and in sync), test suite (24 files, 381 tests, 66.80%
  coverage — was stale at 14/225/48.00%), and the Boost architecture note
  (removed a stale claim that `heat-manager-card.js` still had its own
  separate client-side boost implementation — it was unified with the
  panel/service WS commands back in v0.4.3).
- `quality_scale.yaml` — `test-coverage` comment updated to the current
  381 tests / 24 files / 66.80% (was 303/19/63.00%, v0.9.4).
- `pyproject.toml` — `--cov-fail-under` raised 40 → 60, so CI actually
  protects the coverage level already achieved instead of sitting far
  below it.
- `.github/workflows/ci.yml` — `ruff format`/`ruff check` now also run
  against `tests/`, not just `custom_components/heat_manager`. The ~40
  pre-existing findings this surfaced (unsorted/unformatted imports across
  18 files, one late import, one unused variable, one `dict()` call
  rewritten as a literal) were fixed in the same pass.
- Added a `# broad-except-rationale:` comment above every one of the 36
  `except Exception as err:  # noqa: BLE001` blocks (coordinator.py,
  seven engine files, panel.py, switch.py, websocket.py, `__init__.py`),
  explaining which of three patterns applies: coordinator-tick isolation,
  a per-entity/per-room service-call boundary, or a best-effort
  setup/shutdown/optional-integration step. `instructions_for_claude_heat_manager.md`
  §10 updated to name this as the documented exception to "Catche
  `Exception` bredt", and §4.2's coverage target rewritten to state the
  enforced CI floor (60%) and actual level (66.80%) instead of an
  unmet 95% figure.

### Fixed
- **B19** `engine/window_engine.py` — `_schedule_close()` unconditionally
  cancelled the room's pending open-suppression task whenever any window/door
  sensor in the room reported closed, even if another sensor in the same
  room was still open. In a multi-sensor room this could leave heating
  suppressed only briefly or not at all: opening a second window re-arms the
  delay on the newly-opened sensor (by design), and closing either window
  before that delay elapsed cancelled the pending task without anything
  taking its place — no pending open task, no active suppression, heating
  never turned down even though a window remained open for the rest of the
  airing. This is the mirror-image bug to B16 (which guards the restore
  side); `_schedule_close()` now calls `_all_room_sensors_closed()` up
  front and returns immediately, leaving any pending open task untouched,
  whenever another sensor in the room is still open. Regression tests:
  `test_bug_b19_close_does_not_cancel_pending_open_task_while_second_sensor_still_open`,
  `test_bug_b19_close_proceeds_when_all_sensors_closed`. Relevant to Lukas'
  and Sebastian's rooms (both configured with two window sensors).
- **B20** `engine/presence_engine.py` — every HA restart and every
  integration reload re-instantiates `PresenceEngine`, whose
  `_check_initial_presence()` (B11) re-syncs heating state by calling
  `_restore_all_schedule(force=True)`. That method unconditionally pushed
  "Heating resumed — welcome home" whenever any room was restored — so
  every restart while someone was home spammed the phone, even though
  nothing had actually changed. `_restore_all_schedule()` gained a
  `notify: bool = True` parameter; the startup sync now calls it with
  `notify=False`, so the physical re-sync still happens but stays silent.
  A genuine arrival (`_handle_arrival`) and alarm disarm both still call
  it with the default `notify=True` and keep notifying exactly as before.
  Regression tests: `test_bug_b20_initial_presence_restore_is_scheduled_with_notify_false`,
  `test_bug_b20_restore_all_schedule_notify_false_still_restores_but_does_not_notify`,
  `test_bug_b20_restore_all_schedule_default_notify_true_unchanged`.

---

## [0.13.2] — 2026-09-04

### Changed
- `config_flow.py` — the options flow's room-edit screen (the first screen
  you see when editing a room — window sensors, away temp, etc.) now shows
  which TRVs are already configured for that room, via a new `trv_summary`
  description placeholder (e.g. "TRVs in this room: climate.kitchen,
  climate.kitchen2", or "none yet" for a room with none). Previously the
  TRV list only appeared on the next screen (`room_trvs_menu`), which read
  as "my TRV disappeared" when re-editing a room, even though nothing was
  actually lost — confirmed by `test_options_flow_room_edit_shows_trv_summary`
  that TRVs round-trip correctly through save/reopen.
- `strings.json` / `translations/en.json` / `translations/da.json` —
  `options.step.room_edit.description` updated to include `{trv_summary}`.

### Tests
- `test_options_flow_room_edit_shows_trv_summary` — a room with 2 TRVs
  shows both climate entity IDs, comma-separated.
- `test_options_flow_room_edit_trv_summary_empty_room` — a room with no
  TRVs yet shows `"none yet"` rather than a blank string.

---

## [0.13.1] — 2026-09-04

Bugfix found during a full Fase 1–4 consistency pass over B18 (nothing new
added — just verification), which turned up a pre-existing naming bug that
turned out to affect nine room-scoped entities, not just the three new B18
ones.

### Fixed
- **Doubled room name in every per-room entity's friendly name/entity_id.**
  Nine room-scoped entities all set `_attr_name` to
  `f"{room_name} <suffix>"` (e.g. `"Living room offset"`):
  - B18's new `RoomOffsetNumber` (`number.py`) and `RoomGroupToggleSwitch`
    (`switch.py`), plus the older, pre-existing `RoomOverrideSwitch`
    (`switch.py`).
  - Six entities that predate B18 entirely and have nothing to do with TRV
    grouping: `RoomWindowSensor` and `MoldRiskSensor` (`binary_sensor.py`),
    and `RoomStateSensor`, `RoomWindowDurationSensor`, `RoomPidPowerSensor`,
    `RoomCalibrationOffsetSensor` (`sensor.py`).

  With `has_entity_name = True` and the entity's device already named after
  the room (`coordinator.room_device_info()`), Home Assistant core
  unconditionally computes `friendly_name` (and the `entity_id` assigned at
  first registration) as `f"{device_name} {name}"` — with **no
  startswith/dedup check**. That doubled every one of the nine:
  `"Living room Living room Offset"` / `number.living_room_living_room_offset`,
  `"Living room Living room Window"`, `"Living room Living room State"`, and
  so on. Verified by reading HA core's `entity.py`
  (`_friendly_name_internal()`) and `entity_platform.py`
  (`suggested_object_id` generation) directly — the bug is in the platform,
  there's no dedup anywhere to opt into. Fixed by setting `_attr_name` on
  all nine to a short local name ("Offset" / "Group" / "Override" /
  "Window" / "Mold risk" / "State" / "Window duration" / "PID power" /
  "Calibration offset") and letting HA's own device-name prefixing produce
  the combined name, which is what it was already designed to do. None of
  the nine set `_attr_translation_key`, so this is a pure `_attr_name` fix.
  - This bug meant Fase 4's frontend `_roomOffsetEntityId()` /
    `_roomGroupToggleEntityId()` (panel.js) and `_roomGroupEnabled()`
    (card.js) — which look entities up by `friendly_name` — could never
    find a match, so the new per-room offset slider and group toggle in the
    panel would have silently failed ("kunne ikke finde offset-entity" /
    "kunne ikke finde gruppe-entity"), and the mobile card's "🔓 Ikke
    grupperet" badge would never have shown. Both files updated to match
    the corrected (capitalized, non-doubled) friendly names. The six
    pre-existing sensors were confirmed *not* looked up by friendly_name
    anywhere in the frontend (they're read via `entity_id.endsWith(...)`
    suffix matching or the websocket `ws_get_state()` payload, both
    unaffected by the doubling), so no further frontend changes were
    needed for those.
  - **Registry note:** `RoomOverrideSwitch` and the six pre-existing
    sensors have been running with the doubled name for a long time (well
    before this session). After this fix, HA registers a new entity at the
    corrected `entity_id` on next reload for each of those seven; the old
    doubled-name entity becomes orphaned/unavailable in the entity registry
    and should be removed manually (Settings → Devices & Services →
    Entities) if it lingers. `RoomOffsetNumber` and `RoomGroupToggleSwitch`
    only ever existed with the bug present (introduced this session in
    0.12.0, still unreleased), so there's no orphaned entity for those two
    — this is their first correct registration.

### Tests
- `test_sensor.py::test_room_state_sensor_unique_id_and_name_use_safe_room_name`
  updated: `sensor.name` (the entity's own `_attr_name`, per HA core's
  `_name_internal()` — distinct from the device-prefixed `friendly_name`
  shown in the UI) now asserts `"State"` instead of the previously-doubled
  `"Living Room state"`.

---

## [0.13.0] — 2026-09-04

Fase 4 of TRV grouping (B18, final phase): the frontend catches up with
Fase 3's backend. The old global "Gruppe-offset" slider (`number.
heat_manager_group_offset`) is gone from both `heat-manager-card.js` and
`heat-manager-panel.js` — replaced with per-room controls where each
belongs. `panel.js`'s Rum-fanen (room detail rows) gains a grouping box for
every room with 2+ physical TRVs: a "Grupperet"/"Frigivet" toggle button
(`switch.<room>_group`) and an offset slider (`number.<room>_offset`), same
drag-to-set UX the old global slider had. `card.js` (the compact mobile
card, which has never had per-room interactive controls) instead gets a
small read-only "🔓 Ikke grupperet" badge next to a room's temperature when
its group toggle is off — full editing stays panel-only, matching the
project's mobile-card-is-compact / panel-is-full-detail split.

### Changed
- `frontend/heat-manager-panel.js`:
  - `_resolveEntityIds()` no longer discovers a `_offsetEntityId` — replaced
    by new `_roomOffsetEntityId(roomName)` / `_roomGroupToggleEntityId(roomName)`,
    matched by `attributes.friendly_name` (robust to slugify transliteration
    of accented room names, e.g. "Køkken") rather than entity_id suffix.
  - `_controllerSectionHTML()` / `_patchController()` — the global offset
    slider markup and its "synced unless actively dragging" patch logic are
    removed.
  - `_roomDetailRowHTML()` — new grouping box (only for `room.trv_count >
    1`, using the per-room `offset`/`group_enabled` fields Fase 3 added to
    `ws_get_state()`'s room payload): a `toggle-btn`-styled group toggle and
    an offset slider styled like the removed global one.
  - New `_attachRoomDetailEvents()` — extracted from `_attachEvents()` so it
    can also be called from `_patchRoomsTab()`, which rebuilds
    `.rooms-detail-container`'s innerHTML on every ~30s poll and was
    silently dropping the manual-control slider/send/reset listeners after
    the first refresh; now those and the new grouping controls are
    re-wired on every rebuild. Toggling group state calls
    `switch.turn_on`/`turn_off` and locally patches `room.group_enabled`
    before re-rendering the row; dragging the offset slider calls
    `number.set_value` and locally patches `room.offset`.
- `frontend/heat-manager-card.js`:
  - Removed `_offsetEntityId()`/`_groupOffset()`, the "Gruppe-offset" row in
    the Controller section, its periodic sync in `_updateInPlace()`, and
    its event wiring in `_attachEvents()`.
  - New `_roomGroupEnabled(roomName)` (same friendly_name matching as the
    panel) backs a small "🔓 Ikke grupperet" badge shown next to a room's
    temperature, alongside the existing blocking-sources badge, when that
    room's group toggle is off.

---

## [0.12.0] — 2026-09-04

Fase 3 of TRV grouping (B18): rooms with 2+ physical TRVs now get two new
per-room entities — an offset `number` and a group-toggle `switch` —
replacing the single global `number.heat_manager_group_offset` (v0.9.0).
Turning a room's group toggle OFF releases every TRV in that room except
the primary one for independent/manual control: Heat Manager stops sending
commands to them across every engine (PID tick, boost, away, window,
preheat, valve protection, sync, controller off-fallback, the override
switch, WS manual commands), while the primary TRV and the room's offset
keep applying normally. Frontend updates (panel.js/card.js surfacing the
new per-room controls, removing the old global offset slider) are Fase 4,
not yet done — the existing UI degrades gracefully in the meantime (its
`group_offset` reads default to 0/no-op).

### Added
- `number.py` — `RoomOffsetNumber`, one per room with 2+ physical TRVs,
  writing to the new `coordinator.room_offsets[room_name]` (replaces the
  global `GroupOffsetNumber`/`coordinator.group_offset`). Same bounds/step
  as the entity it replaces (`GROUP_OFFSET_MIN/MAX/STEP`, kept as-is).
- `switch.py` — `RoomGroupToggleSwitch`, one per room with 2+ physical
  TRVs, default ON, backed by `coordinator.room_group_enabled[room_name]`.

### Changed
- `coordinator.py` — `get_room_trvs()` is now toggle-aware: for a 2+ TRV
  room whose group toggle is off, it returns only the primary TRV, so
  every command call site from Fase 2 (PID tick, boost, presence/window/
  preheat, valve protection, sync engine, controller off-fallback, the
  override switch, WS manual commands) automatically stops touching that
  room's secondary TRVs with no further per-engine changes. A new
  `get_all_room_trvs()` is the structural/ignoring-the-toggle accessor,
  used by entity setup and diagnostics. New `set_room_group_enabled()`
  updates the toggle state, rebuilds SyncEngine's entity map, and
  refreshes listeners in one call. `_async_pid_tick()`'s target-temperature
  computation now adds `room_offsets.get(room_name, 0.0)` instead of the
  old global `group_offset`. `async_boost_start()` resets every room's
  offset (`room_offsets = {}`) instead of the single global value.
- `engine/sync_engine.py` — new public `rebuild_entity_map()`: unsubscribes
  the current listener, rebuilds `_entity_to_room`/`_entity_to_trv` from
  `get_room_trvs()`, and re-subscribes. Needed because the toggle can
  change at runtime, which would otherwise leave the map — built once in
  `__init__` — stale (still watching a just-ungrouped secondary TRV, or
  not yet watching one just regrouped).
- `websocket.py` — `ws_get_state()`'s per-room payload gains `trv_count`,
  `offset` and `group_enabled`; the old top-level `group_offset` key is
  removed (the existing frontend already reads it as `?? 0`, so this
  degrades to an inert 0/no-op slider until Fase 4).
- `strings.json` / `translations/da.json` / `translations/en.json` /
  `icons.json` — `number.group_offset` → `number.room_offset`; new
  `switch.room_group_toggle` translation/icon entries.

### Tests
- `test_number.py` rewritten for `RoomOffsetNumber` (was `GroupOffsetNumber`),
  plus `async_setup_entry()` coverage for the 2+ TRV room filter.
- `test_switch.py` — new `RoomGroupToggleSwitch` tests (is_on, unique_id,
  turn_on/off) and `async_setup_entry()` coverage for the 2+ TRV filter.
- `test_sync_engine.py` — new `rebuild_entity_map()` tests: drops a
  just-ungrouped TRV, re-adds a just-regrouped one, unsubscribes the old
  listener, and confirms a stale pending-confirm callback after a rebuild
  is a safe no-op.
- `test_room_grouping.py` — new file: `get_all_room_trvs()` vs. the
  toggle-aware `get_room_trvs()`, `set_room_group_enabled()`, and
  `async_boost_start()`'s per-room offset reset, all against the real
  (unmocked) coordinator methods.
- `test_pid_tick.py` / `test_websocket.py` — updated fixtures
  (`room_offsets`, `room_group_enabled`, `get_all_room_trvs`) plus new
  tests for per-room offset application (and non-leakage across rooms)
  and the new per-room WS payload fields.
- 379 passed.

---

## [0.11.0] — 2026-09-04

Fase 2 of TRV grouping (B18): the coordinator and every engine that writes
a `climate.*` service call now fan the same command out to every physical
TRV configured for a room (via Fase 1's `CONF_TRVS`), instead of only the
room's primary TRV. One PID loop still computes a single target
temperature per room; only the final write step loops. Single-TRV rooms
are unaffected — every existing test passes unchanged. Fase 3 (new
per-room offset/group-toggle entities, removal of the global group-offset
number) and Fase 4 (panel.js/card.js) follow in later releases.

### Changed
- `coordinator.py` — new multi-TRV helpers (`get_room_trvs`,
  `get_trv_write_entity`, `get_room_write_entities`, `trv_needs_cloud_delay`)
  built on Fase 1's flat-mirror migration. `_async_pid_tick()`'s write step
  and `async_boost_start()` now loop every TRV in a room; the PID
  reset-on-unavailable decision and the 0.5 °C suppress threshold stay
  gated on the room's primary TRV only, individual secondary TRVs are
  best-effort.
- `engine/presence_engine.py` — `_set_all_away()`, `_restore_all_schedule()`
  and `force_room_on()` now command every TRV in a room, each still routed
  by its own `trv_type` (netatmo preset_mode vs. Zigbee hvac_mode).
- `engine/window_engine.py` — `_open_after_delay()` sends the same
  window-open setpoint to every TRV's write entity; `_close_after_delay()`
  restores every TRV, each by its own `trv_type`.
- `engine/controller.py` — `_apply_off_fallback()`'s DORMANT and
  ACTIVE/WAKING branches both now loop every TRV in a room, keeping each
  branch's own pre-existing entity-selection policy (the DORMANT branch
  still has no `trv_type` routing — that asymmetry is pre-existing, not
  new).
- `engine/preheat_engine.py` — `_start_preheat()` preheats every TRV in an
  AWAY room, each by its own `trv_type`.
- `engine/valve_protection_engine.py` — `_exercise_all_valves()` exercises
  every physical TRV in a room individually (open → hold → restore per
  TRV), each still preferring its own configured HomeKit entity with no
  reachability check (unchanged single-TRV policy), staggered per TRV by
  its own `trv_type`.
- `engine/sync_engine.py` — `CONF_SYNC_MODE` is read per TRV (it moved to
  the TRV dict in Fase 1). `_build_entity_map()` now maps every enabled
  TRV's entities to its own TRV dict; the "is this the active write
  entity" check and the mirror/lock decision are both scoped to the
  specific TRV that changed, not the room's primary.
- `switch.py` — `RoomOverrideSwitch.async_turn_on()` now switches every
  TRV in the room to OVERRIDE, preserving its own pre-existing (and
  previously room-level) inconsistency between branches: the Zigbee
  branch prefers the write entity, the Netatmo branch always writes to
  the raw `climate_entity` — each now scoped per TRV.
- `websocket.py` — `ws_set_room_temp()` fans a manual temperature or a
  schedule-restore out to every TRV in the room.

### Added
- New test coverage: `test_controller_engine.py` (new — `_apply_off_fallback`
  had no prior test file) and `test_valve_protection_engine.py` (new — no
  prior test file), plus multi-TRV cases added to
  `test_pid_tick.py`, `test_presence_engine.py`, `test_window_engine.py`,
  `test_preheat_engine.py`, `test_sync_engine.py`, `test_switch.py` and
  `test_websocket.py`. All pre-existing single-TRV tests pass unchanged —
  fixtures were extended with a default `get_room_trvs()` (built from
  Fase 1's `migrate_room_to_trvs()`) rather than rewritten. Full suite:
  353 passed.

---

## [0.10.0] — 2026-09-04

Fase 1 of TRV grouping groundwork (B18). Data model and config/options flow
UI only — the coordinator and engines are unchanged, so a multi-TRV room
is not yet actively controlled beyond its primary TRV. Fase 2 (multi-TRV
command loop), Fase 3 (per-room offset/group entities, removal of the
global group-offset number), and Fase 4 (panel.js/card.js) follow in
later releases.

### Added
- `CONF_TRVS` — a room can now hold more than one physical TRV. Each room's
  own config/options flow step (`room` / `room_add` / `room_edit`) is
  followed by a new TRV sub-menu (`room_trvs_menu`) where TRVs are added,
  edited or deleted one at a time (`room_trv_add` / `room_trv_edit`), the
  same repeatable-list pattern already used for rooms and persons. At
  least one TRV is required before a room can be saved — the sub-menu's
  "done" action isn't offered until one exists.
- Per-TRV field granularity: `climate_entity`, `homekit_climate_entity`,
  `trv_type`, `pi_demand_entity`, `calibration_entity` and `sync_mode` all
  now live on each TRV dict inside `CONF_TRVS`, instead of once per room.
  `schedule_entity` and every other room-level field (window sensors,
  away override, CO₂, room/humidity sensors, comfort temp) are unchanged
  and stay on the room.
- `migrations.py` — pure, HA-import-free `migrate_room_to_trvs()` /
  `migrate_rooms_to_trvs()`, run once per config entry via the new
  `async_migrate_entry()` hook in `__init__.py` (config entry version
  1 → 2). A pre-existing single-TRV room's flat fields are copied into a
  one-element `CONF_TRVS` list; the flat fields themselves are *also* left
  in place, mirrored from `trvs[0]` — every other module that still reads
  `room.get(CONF_CLIMATE_ENTITY)` etc. directly (coordinator, sensors,
  switches, all six engines) keeps working unchanged for single-TRV
  rooms, entirely unaware CONF_TRVS exists. The migration is idempotent,
  so editing a room through the new per-TRV UI (which only writes
  CONF_TRVS) correctly re-syncs the flat mirror the next time the entry
  loads.
- 48 new/rewritten tests: `_trv_schema` validation (including the B17
  empty-optional-entity fix, now also verified at the TRV level), the new
  room → room_trvs_menu → room_trv_add/edit flow for both the config and
  options flow, and `tests/components/heat_manager/test_migrations.py`
  (13 tests) covering fresh migration, idempotent re-migration, flat-mirror
  resync after an edit, and `async_migrate_entry`'s version bump. Total
  test count: 303 → 328 (+ existing suites unaffected — zero files outside
  config_flow.py / __init__.py / migrations.py were touched).

---

## [0.9.5] — 2026-09-04

### Fixed
- **B17** — Four optional entity-picker fields (`calibration_entity`,
  `schedule_entity`, `weather_entity`, `alarm_panel`) used
  `vol.Optional(..., default=defaults.get(CONF_X, ""))` together with an
  `"entity"` selector. HA's entity selector rejects `""` as an invalid
  entity ID, so the *schema itself* raised `vol.Invalid` on submit —
  before the step handler's own (correct) `if x and hass.states.get(x)
  is None` guards ever ran. In practice this meant a room could never be
  saved while its TRV calibration entity or schedule/calendar entity was
  left empty, even though strings.json labels both "(optional)". Fixed by
  defaulting to `vol.UNDEFINED` (via `defaults.get(CONF_X) or
  vol.UNDEFINED`) instead of `""`, so an empty selection is omitted from
  the validated data instead of being coerced into an invalid entity ID.
  This also self-heals rooms/entries that already had `""` stored for
  these fields from before the fix. Reported after being unable to clear
  a Zigbee TRV's calibration entity while switching a room to Netatmo.
- Regression tests added in `test_config_flow.py` that apply the actual
  `data_schema` returned by the config/options flow steps (mirroring
  what HA's `FlowManager.async_configure` does), rather than only calling
  the step function directly with a plain dict — the previous tests
  could not have caught this class of bug.

---

## [0.9.4] — 2026-09-03

Closes out the entity-platform test-coverage backlog item from the v0.9.2
deep-dive review — no runtime behaviour changed.

### Added
- `tests/components/heat_manager/test_number.py` — 6 tests for
  `GroupOffsetNumber`, including its restore-on-restart behaviour
  (`async_added_to_hass` restoring a previous value, falling back to the
  default when there's no previous state or its `native_value` is itself
  `None`). `number.py` coverage: 95%.
- `tests/components/heat_manager/test_select.py` — 8 tests for
  `ControllerStateSelect` and `SeasonModeSelect`, including invalid-option
  handling and `SeasonModeSelect`'s config-entry-options persistence.
  `select.py` coverage: 97%.
- `tests/components/heat_manager/test_switch.py` — 8 tests for
  `RoomOverrideSwitch`, including the netatmo-vs-zigbee write-target
  asymmetry (netatmo writes `_climate_id` directly; zigbee prefers the
  write entity) and service-call-failure handling. `switch.py` coverage:
  96%.
- Total test count: 281 → 303. Total project coverage: 58.53% → 63.00%.

### Changed
- `STATUS.md` backlog — the "entity-platform test coverage" item is now
  marked done; `number.py`, `select.py`, `sensor.py`, `switch.py` and
  `websocket.py` all have dedicated tests.

## [0.9.3] — 2026-09-03

Test coverage for the entity-glue code identified as a gap in the v0.9.2
deep-dive review — no runtime behaviour changed.

### Added
- `tests/components/heat_manager/test_websocket.py` — 30 tests covering
  every WS command handler (`ws_get_state`, `ws_boost_start/stop`,
  `ws_set_room_temp`, `ws_update_config`, `ws_get_history`, `_get_entry`),
  including the v0.9.0 payload fields the frontend panel/card depend on
  (`blocking_sources`, `group_offset`, `calibration_entity`/`sync_mode`/
  `schedule_entity`). Tests call each handler's `__wrapped__` coroutine
  directly, bypassing the `@websocket_api.async_response` background-task
  scheduler so results and exceptions can be asserted synchronously.
  `websocket.py` coverage: 16% → 86%.
- `tests/components/heat_manager/test_sensor.py` — 23 tests covering all
  sensor platform entities, with particular attention to
  `RoomStateSensor`'s `available`/unavailable-recovery logging (once each
  way, never spammed) and its `blocking_sources` attribute exposure.
  `sensor.py` coverage: 95%.
- Total test count: 228 → 281. Total project coverage: 48% → 58.53%.

### Changed
- `STATUS.md` backlog — the "entity-platform test coverage" item now
  reflects `websocket.py`/`sensor.py` being covered; `number.py`,
  `select.py`, `switch.py` remain at 0% and are still open.

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
