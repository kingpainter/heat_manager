# Heat Manager — Runde 2: Frontend/config dødkode-sweep (2026-09-10)

Opfølgning på `audit/heat_manager_fixes_2026-09-10.md` (0.18.0), efter brugerens
spørgsmål: *"er der mere død kode eller funktioner der bare er til pynt? alt vi
har på frontend eller i konfig skal være i brug og være funktionel eller
fjernes."* Runde 1 dækkede kun backend-Python; denne runde dækker panelet
(`heat-manager-panel.js`), config-fladen, og et stykke selv-oprydning efter
runde 1.

Version bumpet: `0.18.0` → `0.18.1` (patch — primært oprydning, ét genskabt
felt). `CHANGELOG.md` opdateret med fuld `[0.18.1]`-sektion. Skrevet til
GitHub-repoet (`C:\Users\Konge\Documents\github-homeassistant-projekter\heat_manager\`),
samme deploy-afgrænsning som runde 1.

## Metode

1. Alle 58 `CONF_*`-konstanter i `const.py` krydstjekket: sættes de i
   `config_flow.py`, og læses de i mindst én produktionsfil? — ingen fund.
2. Alle funktionsdefinitioner i backend og frontend talt op mod kaldesteder
   (regex, manuelt verificeret mod false positives fra dekoratorer/framework-hooks).
3. Alle `heat_manager/*`-websocket-kommandoer krydstjekket mellem frontend og
   backend-registrering — ingen forældreløse i nogen retning.
4. Alle `this._data?.X`/`room.X`-feltlæsninger i panelet krydstjekket mod de
   faktiske nøgler `ws_get_state()` bygger — både top-niveau og per-rum.
5. Samme øvelse for `heat-manager-card.js` (mobilkortet, som ikke bruger
   websocket men læser rigtige entity-states direkte) — ingen døde metoder
   fundet.

## Fjernet (bekræftet død/dekorativ)

- **"Away temp mildt"/"Away temp koldt"-rækker** i panelets config-tab —
  viste altid "–" siden backend-felterne blev fjernet i 0.18.0 (B.1).
- **To nedtonede "🔥 Boost til"/"🔥 Boost slut"-badges** i House Voice-sektionen
  — ingen backend-understøttelse (`async_house_voice_say()` kaldes aldrig for
  boost-events). De 4 rigtige badges er upåvirket.
- **`const.VERSION`** — blev forældreløs af min egen 0.18.0-fix (panel.py
  læser nu version fra `manifest.json` direkte). Ingen resterende læser i
  hverken `custom_components/heat_manager/` eller `tests/`.
- **Per-rum `"why"`-felt** (`_why_label()`) — en engelsk statustekst beregnet
  hver tick og sendt i hver payload, men aldrig læst af noget frontend. Begge
  frontends afleder allerede al deres tilstands-UI (badges, farver, filtre,
  optællinger) direkte fra `room.state` — ren duplikering uden funktionelt
  hul bagved.
- **Per-rum `"heating_power"`-felt** — altid talmæssigt identisk med
  `valve_position` for Netatmo-rum (det *er* kildeværdien `valve_position`
  sættes fra), og forældet/overskrevet når `pi_demand_entity` overstyrer
  `valve_position` for Zigbee-rum. Ingen læser brugte det separat. Selve
  aflæsningen af `heating_power_request` bruges stadig internt til at beregne
  `valve_position` — kun den overflødige duplikat-nøgle er fjernet fra
  payload'en.

## Rettet (reelt hul, ikke bevidst fravalg)

- **`CONF_OUTDOOR_TEMP_SENSOR`** — en rigtig, funktionel indstilling
  (coordinator foretrækker den frem for weather-entiteten til
  udetemperatur), konfigurerbar og med sin egen række i panelets config-tab,
  men værdien nåede aldrig `ws_get_state()`'s payload → rækken viste altid
  "–". Koblet ind i `config_snap`.
- **`auto_off_reason`** blev beregnet af backend hver tick og sendt i hver
  payload, men intet viste den — "Slukket"-badgen gav ingen antydning af
  *hvorfor*. Badgen tilføjer nu årsagen ("sæson"/"temperatur") når sat.
- **`open_windows`** (fra 0.18.0, B.3) blev tilføjet til payload'en, men
  fixet stoppede der — intet frontend viste den, så det oprindelige hul
  ("implementeret men aldrig eksponeret") var kun halvt lukket. Færdiggjort:
  oversigtens "Vindue åbent"-kort viser nu den reelle sensor-liste som
  tooltip.
- **`energy_saved_today`/`energy_wasted_today`/`efficiency_score`/
  `last_waste_time`/`last_saved_time`** blev beregnet og sendt i hver
  payload (samme kilde som de rigtige `sensor.heat_manager_energy_*`-
  entiteter mobilkortet allerede læser direkte), men panelets egen "Energi i
  dag"-visning var fjernet som død kode i 0.17.2 — data blev ved med at
  flyde uden noget der viste det. **Brugerens valg**: genskab en kompakt
  boks (i stedet for at fjerne felterne) → tilføjet `_energySectionHTML()`
  i oversigten (spildt/sparet, effektivitets-badge, seneste tidspunkter).

## Ikke fjernet — falske positiver undersøgt og afvist

- Service-svar-felter (`success`, `changed`, `rooms_boosted`,
  `rooms_restored`, `duration_min`, `write_entity`, `date` i historik-arrayet)
  er kvitteringer for websocket-kommandoer, ikke visningsfelter — normalt
  mønster, ikke død kode.
- `entity_id`/`hvac_mode`/`preset_mode` i `websocket.py` er data der sendes
  *til* HA's climate-services, ikke felter sendt til frontend.
- `getCardSize` i `heat-manager-card.js` er en Lovelace-framework-hook kaldt
  af HA selv, ikke fra filen — ingen dead code.

## Tests

`test_websocket.py`: opdateret assertion for det fjernede `heating_power`-
felt (`assert "heating_power" not in room` i stedet for at tjekke værdien).
Ingen andre tests refererede `"why"` eller `heating_power` eksplicit.

## Verifikation

`python3 -m py_compile` på alle ændrede Python-filer (ren). `ruff check
--select=F,E9` på samme (ingen fund). `node --check` på
`heat-manager-panel.js` (ren). `manifest.json` valideret som gyldig JSON.
Samme miljøbegrænsning som tidligere: **kunne ikke køre selve
pytest-suiten** (`homeassistant`-pakken kan ikke installeres i dette
sandbox) — verifikation er derfor statisk + manuelt krydstjek af hvert
ændret testsites forventninger.

## Ændrede filer

`custom_components/heat_manager/websocket.py`, `const.py`,
`frontend/heat-manager-panel.js`, `manifest.json`, `CHANGELOG.md`,
`tests/components/heat_manager/test_websocket.py`.
