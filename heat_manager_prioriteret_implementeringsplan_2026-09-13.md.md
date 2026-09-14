# Heat Manager — Prioriteret implementeringsplan for de 13 punkter (2026-09-13)

**Grundlag:** arkitektur-reviewet fra i dag (`audit/heat_manager_architecture_review_2026-09-13.md`), features-oplægget fra 2026-09-11, og selve punktlisten. Instruktionsfilerne på `C:\...\instructions_for_claude\` kunne ikke læses denne gang — den lokale Filesystem MCP-server fejlede med en outputSchema-fejl (ikke en manglende forbindelse). Planen bygger derfor på projektets øvrige dokumentation. Læs instruktionsfilerne ved næste session, som reglerne foreskriver, før noget kodes.

## Metode

Fire grupper efter kombination af sværhedsgrad, forventet vinding og hvor hurtigt punktet kan laves: **A** (hurtige gevinster), **B** (solid middelklasse), **C** (store beslutninger/arkitektur — skal afklares før kodning), **D** (bevidst parkeret denne runde). Derefter en anbefalet rækkefølge og de åbne spørgsmål gruppe C kræver svar på.

---

## Gruppe A — Hurtige gevinster (lav effort, klar værdi, kan startes nu)

### 11. brands/icon.png til HACS-listing
- **Sværhedsgrad:** Meget lav — rent asset-/registreringsarbejde, ingen kodeændring i selve integrationen.
- **Vinding:** Forudsætning for officiel HACS-listing — blokerer distribution, ikke funktionalitet.
- **Kommentar:** Ikonet findes allerede i repoet; opgaven er at få det submitted til `home-assistant/brands` (PR med korrekt mappestruktur/størrelser: `icon.png` 256×256, evt. `logo.png`/dark-variant). Under en times arbejde, bør ikke vente på noget andet.

### 3. Dedup/gruppering af statuscenter-issues
- **Sværhedsgrad:** Lav — isoleret til én funktion (`websocket.py::_build_active_issues`), ingen ny datamodel.
- **Vinding:** Direkte UX-forbedring — reducerer støj mærkbart ("5 rum har utilgængelig sensor" i én linje i stedet for 5).
- **Kommentar:** Gruppér efter issue-type, vis antal + detaljer i undermenu. Selvstændigt og reversibelt.

### 4. Sundhedsscore pr. rum
- **Sværhedsgrad:** Lav-til-moderat — al data findes allerede (batteri, mold_risk, unavailable_entities, afvigelse fra lært opvarmningsrate); opgaven er en vægtningsformel + ét nyt UI-element pr. rum-kort.
- **Vinding:** Høj oplevet værdi — én samlet indikator i stedet for at samle badges selv.
- **Kommentar:** Lav den efter punkt 3 (samme fil/kontekst i websocket.py), men den er ellers uafhængig af punkt 5/6.

---

## Gruppe B — Solid middelklasse (medium effort, velafgrænset, klar værdi)

### 2. Udvid HA Repairs-integrationen
- **Sværhedsgrad:** Moderat — kræver stillingtagen til hvilke issue-typer der skal have egen `repair_issue` (cloud nede, vedvarende skimmelrisiko, rum blokeret i timevis), severity, og oversættelser.
- **Vinding:** Reel — synlighed i Indstillinger → Reparationer og HA-mobilappens badge, ikke kun eget panel.
- **Kommentar:** Naturlig følgesvend til punkt 3 — samme statuscenter-logik som kilde til begge.

### 13. Sammenklappelige menupunkter i panel/config
- **Sværhedsgrad:** Moderat — afhænger af antal sektioner i panel.js/config-fanen; ren frontend, ingen backend-ændring.
- **Vinding:** Håndgribelig i daglig brug — mindre scroll, renere UI, især på mobil.
- **Kommentar:** Kan gøres inkrementelt (én sektion ad gangen). Gem åben/lukket-state i localStorage/session, ikke i `entry.options`, for at holde det lavrisiko.

### 5. Opvarmningsrate-læring: udetemperatur som covariate
- **Sværhedsgrad:** Moderat — simpel lineær regression i stedet for ren EMA; kræver mere validering på tværs af temperaturspænd end en ren EMA-justering.
- **Vinding:** Reel præcisionsgevinst, og eksplicit forarbejde til punkt 6 (EKF).
- **Kommentar:** Byg denne FØR punkt 6 — reviewet anbefaler selv den rækkefølge.

### 12. Fuld card.js/panel.js data-parity
- **Sværhedsgrad:** Moderat — bredt, men lavt niveau (flyt felter fra bottom-sheet til hovedlinje, tilføj Netatmo cloud-diagnostik og target/away-override read-out). Ingen ny arkitektur.
- **Vinding:** Lav prioritet, som du selv har markeret — poler, ikke funktion.
- **Kommentar:** Godt fyldarbejde mellem større opgaver, men bør ikke tage plads fra A/B-punkterne.

---

## Gruppe C — Store beslutninger / arkitektur (afklar før kodning)

### 1. Strict typing
- **Sværhedsgrad:** Ukendt uden afgrænsning — spænder fra "mypy --strict på ny kode" (lav effort) til "retrofit hele codebasen" (stort, flerdages arbejde givet engine/-mappens størrelse).
- **Vinding:** Høj hvis I sigter mod Platinum quality scale (typing indgår i kravene) — fanger reelle bugs, ikke kun kosmetik.
- **Åbent spørgsmål:** (a) strict på ny kode fremadrettet, (b) fuld retrofit af hele `custom_components/heat_manager/`, eller (c) kun `engine/`-laget? Svaret afgør om dette hører til i gruppe A eller er et selvstændigt flerugers spor.

### 8. Interne dørers niveau C (aktiv tværrums-styring)
- **Sværhedsgrad:** Høj — kræver en ny konfigurationsenhed ("Døre" = sensor + rum A + rum B, jf. features-oplægget) OG en afklaret ejerskabsmodel for måltemperatur, før en linje kode skrives.
- **Vinding:** Potentielt den største på hele listen — reel besparelse ved at udnytte "gratis" varme mellem rum.
- **Åbent spørgsmål (fra reviewet):** hvem "ejer" et rums måltemperatur, når en åben dør midlertidigt har sænket den, og hvordan undgås det, at systemet opleves som at gøre noget uforklarligt? Anbefaling: byg niveau A (synlighed) + B (kalibrerings-læring pr. dørstatus) fra features-oplægget først — niveau C er en selvstændig beslutning bagefter.

### 6. EKF-termisk model
- **Sværhedsgrad:** Meget høj — fuld Kalman-filter-model erstatter statiske PID-gains; det tungeste punkt på listen rent modelmæssigt.
- **Vinding:** Potentielt stor præcisionsgevinst, men kun hvis punkt 5 er bygget og har kørt længe nok til at levere brugbare data.
- **Kommentar:** Ikke noget at starte på nu — parkér indtil punkt 5 har kørt en fuld opvarmningssæson.

### 7. Solar gain i SeasonEngine
- **Sværhedsgrad:** Høj — kræver enten en ny datakilde (solindstråling/sol-position) eller en afledt beregning (dag/nat + himmelretning pr. rum), og integration i en model der i dag ikke har nogen af delene.
- **Vinding:** Reel for sydvendte rum, men mindre universel end punkt 5/6.
- **Kommentar:** Reviewet peger på en billigere mellemstation (klassisk vejrkompensationskurve: udetemp → fast offset på PID-setpoint) som endnu ikke er på din liste — værd at overveje som skridt før solar gain.

---

## Gruppe D — Bevidst parkeret denne runde

**9. Vindues-fald via temperaturfald** — fravalgt af dig. Ingen handling nu. Genoptages det senere, bygges det oven på den lærte opvarmningsrate (punkt 5/6-familien): en uventet hurtig temperaturnedgang mod baseline er signalet.

**10. PID auto-tuning** — fravalgt af dig, og markeret "ikke anbefalet endnu" i reviewet. Kræver en relay/step-test-tilgang (Ziegler-Nichols-stil), som intet af det øvrige forudsætter — tungt, bør vente til punkt 1-5 i den oprindelige ML-rækkefølge er afprøvet.

---

## Anbefalet rækkefølge

| Trin | Punkt | Gruppe | Hvorfor her |
|---|---|---|---|
| 1 | 11 — brands/icon.png | A | Nul afhængigheder, blokerer HACS-listing |
| 2 | 3 — Dedup/gruppering | A | Isoleret, hurtig, forudsætning for pæn punkt 2 |
| 3 | 4 — Sundhedsscore | A | Bruger punkt 3's kontekst, ingen ny data |
| 4 | 2 — Repairs-udvidelse | B | Bygger direkte på punkt 3's issue-typer |
| 5 | 13 — Sammenklappelige menuer | B | Uafhængig, god fyldopgave, mærkbar UX-gevinst |
| 6 | 5 — Udetemp-covariate | B | Forarbejde til punkt 6, bør køre en sæson inden 6 |
| 7 | 12 — Card/panel data-parity | B | Lav prioritet, fyld mellem større opgaver |
| — | 1 — Strict typing | C | Afklar omfang først — kan så flyttes til A eller blive et selvstændigt spor |
| — | 8 — Interne døre niveau C | C | Kræver ejerskabsbeslutning — overvej niveau A+B som forstudie først |
| — | 7 — Solar gain | C | Vent til efter punkt 5; overvej vejrkompensationskurve som billigere mellemtrin |
| — | 6 — EKF-model | C | Vent til punkt 5 har kørt en fuld sæson |
| Parkeret | 9, 10 | D | Bevidst fravalgt denne runde |

## Åbne spørgsmål, før gruppe C kan planlægges konkret

1. **Strict typing (punkt 1):** ny kode, hele `engine/`-laget, eller hele integrationen?
2. **Interne døre niveau C (punkt 8):** skal niveau A+B fra features-oplægget (2026-09-11) bygges som forstudie først, eller vil du direkte tage stilling til ejerskabsspørgsmålet?
3. **Solar gain (punkt 7):** vil du have den billigere vejrkompensationskurve som mellemtrin, eller satse direkte på solar gain?