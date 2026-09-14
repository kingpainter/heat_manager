// Heat Manager — Custom Lovelace Card
// Version: 0.17.2 (comment log below is stale — see manifest.json for the
// actual running version. See CHANGELOG.md for everything since v0.17.2.)
//
// v0.22.0 (2026-09-11 — "Energi i dag" removed):
//   • The Hub-level "Energi i dag" section (added in v0.17.2) is removed
//     entirely, at the user's request — see manifest.json/CHANGELOG.md for
//     the full reasoning (the underlying WasteCalculator model assumes an
//     electric radiator's rated wattage, which doesn't apply to a
//     district-heating/fjernvarme system). Removed _hubEnergyWasted()/
//     _hubEnergySaved()/_hubEfficiency(), _patchEnergy(), the energyHTML
//     block in _cardHTML(), and the related CSS.
//
// v0.21.1 (2026-09-11 mobil-sætpunkt fix):
//   • Fixed the "known still-open item" from v0.21.0 below: room setpoint
//     display now prefers Heat Manager's own resolved target_temp (same
//     value the PID chases, fetched via a new heat_manager/get_state
//     WS poll every 60s — see _loadTargetTemps()/_roomSetpoint()) over the
//     raw Netatmo cloud-entity temperature attribute. Falls back to the old
//     direct read whenever the fetch hasn't completed yet or a room's
//     config name isn't found in the backend's room list. This card always
//     had the same full hass object (and thus callWS()) a panel gets —
//     the earlier "no websocket access" framing in
//     audit/heat_manager_fixes_2026-09-11_fase2.md was a scope choice for
//     that round, not a hard technical limitation.
//
// v0.21.0 (2026-09-11 statustjek):
//   • New #cloud-status-row: this card previously had per-room "TRV
//     offline" badges (_roomTrvUnavailable) but nothing at the card level
//     distinguishing "one room's device has a flat battery" from "the
//     whole house's Netatmo connection is down" — those looked identical,
//     one badge at a time, unless you counted them. New
//     _netatmoCloudStatus()/_netatmoCloudStatusHTML() mirror the panel's
//     _cloudStatus() logic (all rooms down at once → cloud/gateway; some
//     rooms down → single device; stale-but-available → cloud not
//     updating), computed client-side from hass.states like every other
//     mirror helper on this card, since the card has no get_state() access.
//   • Setpoint-source divergence noted here — fixed in v0.21.1 above.
//
// v0.17.2:
//   • Mobile parity pass: room cards now also show PID-power/calibration-
//     offset/window-duration-today chips (same friendly-name discovery as
//     the existing humidity/CO2/battery mirrors) and a "TRV offline" badge
//     when the room's own climate_entity is unavailable/unknown — a
//     lighter version of the panel's health check, scoped to what this
//     card's own per-instance config actually stores (climate_entity only;
//     window_sensors etc. live in the backend config entry, not here).
//     New Hub-level "Energi i dag" section (wasted/saved kWh + efficiency
//     %), discovered the same way against the global "Heat Manager" device.
//
// v0.17.0:
//   • Room cards now show humidity/CO2/battery chips, a valve-% badge and a
//     mold-risk badge — read via the room's own v0.15.0 mirror sensors and
//     climate_entity attributes (friendly_name discovery, same pattern this
//     card already used for the group-toggle switch), no new card config
//     needed. Brings the mobile card closer to Oversigt-fane parity.
//
// v0.16.0:
//   • Version banner corrected — this file had said 0.4.3 since before
//     v0.9.0's frontend surfacing work, several releases out of date.
//   • Removed the dead .room-homekit-lytter listener in the card editor
//     (2.3): the corresponding input field was removed from _render() long
//     ago, so the field was never rendered and the listener never fired.
//
// v0.4.3:
//   • Boost button now delegates to heat_manager/boost_start|stop WS
//     commands (coordinator.async_boost_start/stop) instead of writing
//     climate.set_temperature / calling force_room_on directly. Fixes three
//     things: card and panel/service boosts no longer conflict or double up;
//     the backend's own boost_expires_at auto-restore now applies to
//     card-started boosts too (previously only this card's own JS timer
//     tracked expiry, which stopped the moment the tab closed); and boost
//     now applies to ALL of Heat Manager's configured rooms, not just the
//     subset listed in this particular card instance's config.
//
// UI-CARD: Rooms section now renders as a 2-column grid instead of a
// single stacked column. Grid-auto-flow fills row-wise, so odd room
// counts (e.g. 5 rooms) naturally land as 3-over-2 without any manual
// splitting logic. Falls back to 1 column via a container query when
// the card itself is narrow (sidebar / small mobile width).
//
// Fix B-CARD-IAH: _render() used optional-chaining syntax on replaceWith()
// that is invalid in some JS engines. Replaced with explicit null check.
// Also adds _srAppendHTML() helper (WebKit-safe, same as panel) so the
// first-render path never calls insertAdjacentHTML on a ShadowRoot.
//
// Fix B-CARD-PANEL: card did not fill a `type: panel` view correctly on
// tablet dashboards (e.g. 7" Lenovo, landscape) — :host lacked an explicit
// height, the ha-card/.card wrapper used fixed content flow instead of a
// column flexbox, and the rooms list had no flex-grow/scroll region.
// Aligned with secure_me_alarm_tab_card.js's panel-sizing pattern.
//
// Design: Unified with Indeklima — DM Sans/DM Mono, section-box system,
// SVG efficiency ring, amber/orange heat palette.

// ── Shared helpers ────────────────────────────────────────────────────────────

function _hmEsc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function _hmStateColor(s) {
  return ({ normal:"#f97316", away:"#64748b", window_open:"#ef4444", pre_heat:"#0ea5e9", override:"#a855f7" })[s] ?? "#64748b";
}

// v0.14.0: source param distinguishes who engaged OVERRIDE — "remote"
// (RemoteButtonEngine) gets its own badge, "switch"/undefined keeps the
// plain "Override" label as before.
function _hmStateLabel(s, source) {
  if (s === "override" && source === "remote") return "📡 Fjernbetjening";
  return ({ normal:"Normal", away:"Fraværende", window_open:"Vindue åbent", pre_heat:"Forvarmning", override:"Override" })[s] ?? (s || "–");
}

function _hmCtrlColor(s) {
  return ({ on:"#f97316", pause:"#eab308", off:"#64748b" })[s] ?? "#64748b";
}

function _hmCtrlLabel(s) {
  return ({ on:"On", pause:"Pause", off:"Off" })[s] ?? (s || "–");
}

// v0.9.0: self-reporting diagnostics — short Danish tags for the neutral
// blocking_sources codes coordinator.get_room_blocking_sources() returns.
function _hmBlockingLabel(s) {
  return ({
    controller_off:   "Controller slukket",
    controller_pause: "Controller pause",
    window:           "Vindue åbent",
    presence:         "Fraværende",
  })[s] ?? s;
}

// Card/panel data-parity (2026-09-13) — same labels as panel.js's own
// _syncModeLabel(), so a room configured with sync_mode shows the identical
// Danish label on both surfaces.
function _hmSyncModeLabel(mode) {
  return ({ disabled: "Deaktiveret", mirror: "Spejl", lock: "Lås" })[mode] ?? mode;
}




// ─────────────────────────────────────────────────────────────────────────────
// heat-manager-card
// ─────────────────────────────────────────────────────────────────────────────

class HeatManagerCard extends HTMLElement {
  static getStubConfig() {
    return { rooms: [], weather_entity: "", boost_temp: 24, boost_minutes: 30 };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass         = null;
    this._config       = {};
    this._pauseMinutes = 120;
    this._boostActive  = false;
    this._boostTimer   = null;   // setInterval handle
    this._boostRemain  = 0;      // seconds remaining
    this._targetTemps  = null;   // 2026-09-11 mobil-sætpunkt fix — room name → target_temp
    this._targetTempPollStarted = false;
    this._targetTempInterval    = null;
    this._roomData     = null;   // Fase 2, del 2 (2026-09-13) — room name → full get_state room dict (door status, trv_count, etc. for the press-and-hold sheet)
    this._openSheetRoom = null;  // room name currently shown in the bottom-sheet, if any
  }

  setConfig(config) {
    this._config = config || {};
    this._updateScale();
    this._render();
  }

  set hass(h) {
    this._hass = h;
    // 2026-09-11 mobil-sætpunkt fix: kick off the first target_temp fetch as
    // soon as hass is actually available, so the correct setpoint shows
    // without waiting for the first 60s poll tick — but only once. set
    // hass() fires on every relevant state-bus event (can be many times a
    // second), so anything heavier than a plain object read has to be
    // gated, not run unconditionally here.
    if (h && !this._targetTempPollStarted) {
      this._targetTempPollStarted = true;
      this._loadTargetTemps();
    }
    this._updateInPlace();
  }

  getCardSize() { return 4; }

  // Tablet height-scale (WIP — testing against the new 11" tablet before
  // this gets a version bump). Same pattern as pc-user-statistics-tablet-card
  // and secure_me_alarm_tab_card: computed in JS via window.innerHeight
  // rather than CSS calc(100vh / Npx), which does not reliably resolve in
  // all kiosk WebViews.
  _updateScale() {
    const h = window.innerHeight || 800;
    const scale = Math.min(2.0, Math.max(0.85, h / 800));
    this.style.setProperty("--hm-scale-h", scale.toFixed(4));
    // Defensive: explicit pixel height on the host, in case the % height
    // chain up through the panel-view wrapper doesn't resolve cleanly in
    // this tablet's WebView (belt-and-suspenders alongside :host{height:100%}).
    this.style.height = h + "px";
  }

  connectedCallback() {
    this._updateScale();
    this._resizeHandler = () => this._updateScale();
    window.addEventListener("resize", this._resizeHandler);
    // 2026-09-11 mobil-sætpunkt fix: same 60s cadence as the panel's own
    // get_state poll — see _loadTargetTemps(). Started here (not just from
    // set hass()) so it also resumes if the card is ever removed and
    // re-added to the DOM (tab switch in some dashboards re-mounts cards).
    if (!this._targetTempInterval) {
      this._targetTempInterval = setInterval(() => this._loadTargetTemps(), 60000);
    }
  }

  disconnectedCallback() {
    if (this._resizeHandler) window.removeEventListener("resize", this._resizeHandler);
    if (this._targetTempInterval) { clearInterval(this._targetTempInterval); this._targetTempInterval = null; }
  }

  // WebKit-safe helper — ShadowRoot does not support insertAdjacentHTML
  _srAppend(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    while (tmp.firstChild) this.shadowRoot.appendChild(tmp.firstChild);
  }

  // ── State helpers ─────────────────────────────────────────────────────────

  _attr(id, a) { return this._hass?.states?.[id]?.attributes?.[a]; }

  _ctrl() {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("select.") && id.endsWith("_controller_state")) return states[id].state;
    }
    return "unknown";
  }

  _season() {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("select.") && id.endsWith("_season_mode")) return states[id].state;
    }
    return "auto";
  }

  _pauseLeft() {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith("_pause_remaining")) {
        return parseInt(states[id].state || "0", 10);
      }
    }
    return 0;
  }

  _climateTemp(id) {
    const t = this._attr(id, "current_temperature");
    return t != null ? (Math.round(t * 10) / 10) + "°C" : "–";
  }

  _climateSetpoint(id) {
    const t = this._attr(id, "temperature");
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }

  // 2026-09-11 mobil-sætpunkt fix. Since the 0.19.0 (B21) fix, the PID no
  // longer writes comfort_temp to the Netatmo cloud entity's own
  // `temperature` attribute for Netatmo rooms — it targets
  // get_room_target_temp() and writes to the local HomeKit entity instead.
  // _climateSetpoint() above still reads exactly that now-stale cloud
  // attribute directly, so it can show a number Heat Manager isn't
  // actually chasing (see audit/heat_manager_fixes_2026-09-11_fase2.md's
  // "Known limitation" and audit/heat_manager_connection_health_fix_
  // 2026-09-11.md). The panel fixed this with a WS fetch of target_temp
  // (_roomSetpoint() there); this card had no websocket call anywhere
  // before now, only ever reading this._hass.states directly — but the
  // hass object a Lovelace card receives is the same full frontend object
  // a panel gets, so callWS() has always been available here too. That was
  // a scope choice in Fase 2, not a hard technical limitation.
  //
  // Polled every 60s from connectedCallback() (see _loadTargetTemps()) —
  // NOT on every set hass() tick, which fires on every relevant state-bus
  // event and would otherwise spam the backend. Falls back to the raw
  // cloud-entity read below whenever the map hasn't loaded yet, or this
  // room's name isn't found in it (e.g. a name mismatch between this
  // card's own per-instance room_name config and the integration's actual
  // configured rooms) — same graceful-degradation convention every other
  // mirror helper on this card already follows.
  _roomSetpoint(room) {
    const name = room?.room_name ?? "";
    const t = name ? this._targetTemps?.[name] : null;
    if (t != null) return (Math.round(t * 10) / 10) + "°C";
    return this._climateSetpoint(room?.climate_entity ?? "");
  }

  async _loadTargetTemps() {
    if (!this._hass?.callWS) return;
    try {
      const data = await this._hass.callWS({ type: "heat_manager/get_state" });
      const map = {};
      // Fase 2, del 2 (2026-09-13): also keep the full per-room dict, keyed
      // the same way — the press-and-hold sheet (_roomSheetHTML()) uses it
      // for fields this card has no other way to discover at all (door
      // status/heat-up rate, trv_count, blocking_sources, group_enabled).
      const roomData = {};
      for (const room of data?.rooms ?? []) {
        if (room?.name != null) {
          roomData[room.name] = room;
          if (room.target_temp != null) map[room.name] = room.target_temp;
        }
      }
      this._targetTemps = map;
      this._roomData = roomData;
    } catch (e) {
      // Backend not up yet / WS hiccup — keep whatever we last had (or
      // null) rather than throwing; _roomSetpoint() falls back gracefully.
    }
    this._updateInPlace();
  }

  _roomState(name) {
    const states = this._hass?.states ?? {};
    const key = name.toLowerCase().replace(/\s+/g, "_");
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith("_" + key + "_state")) return states[id].state;
    }
    return "normal";
  }

  // v0.9.0: per-room blocking sources — read from the room's own state
  // sensor's blocking_sources attribute (sensor.py RoomStateSensor), the
  // same entity _roomState() already reads .state from.
  _roomBlockingSources(name) {
    const states = this._hass?.states ?? {};
    const key = name.toLowerCase().replace(/\s+/g, "_");
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith("_" + key + "_state")) {
        return states[id].attributes?.blocking_sources ?? [];
      }
    }
    return [];
  }

  // v0.14.0: which caller ("switch"/"remote") currently holds this room in
  // OVERRIDE, if any — read off the same per-room state sensor entity as
  // _roomBlockingSources() above (this card has no websocket connection of
  // its own, unlike the panel, which gets it straight from ws_get_state).
  _roomOverrideSource(name) {
    const states = this._hass?.states ?? {};
    const key = name.toLowerCase().replace(/\s+/g, "_");
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith("_" + key + "_state")) {
        return states[id].attributes?.override_source ?? null;
      }
    }
    return null;
  }

  // Per-room blocking sources minus whatever the room's own state pill
  // already communicates (window_open/away) — mirrors the panel's filter.
  _roomExtraBlocking(name, state) {
    return this._roomBlockingSources(name).filter(s => {
      if (s === "window" && state === "window_open") return false;
      if (s === "presence" && state === "away") return false;
      return true;
    });
  }

  // Deduplicated blocking reasons across every room configured in this card.
  _globalBlockingSources() {
    const set = new Set();
    (this._config.rooms ?? []).forEach(room =>
      this._roomBlockingSources(room.room_name ?? "").forEach(s => set.add(s))
    );
    return Array.from(set).sort();
  }

  // B18 Fase 3: the old global group_offset number is gone — offset/group
  // controls are per-room now and live in the panel (bigger-screen UI). The
  // compact mobile card just surfaces a read-only "ungrouped" badge per
  // room, via the room's own switch.<room> group-toggle entity (same
  // friendly-name discovery pattern the panel uses) — no per-room slider
  // here, that stays panel-only.
  //
  // Matches what HA itself computes: has_entity_name=True + device.name ==
  // roomName + the entity's own _attr_name ("Group") combine to
  // f"{device_name} {name}" = "<room> Group" (entity.py's
  // _friendly_name_internal()) — capitalization matters here.
  _roomGroupEnabled(roomName) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("switch.") && states[id]?.attributes?.friendly_name === `${roomName} Group`) {
        return states[id].state !== "off";
      }
    }
    return true; // no toggle entity for this room (single-TRV room) — always "grouped"
  }

  // 2026-09-07 audit fix (5.1-5.3 mobile follow-up): humidity/CO2/battery
  // are only exposed to this card through the v0.15.0 per-room "mirror"
  // diagnostic sensors (sensor.py's _room_mirror_sensors) — has_entity_name
  // devices whose friendly_name is exactly "<room> <label>", same
  // discovery pattern _roomGroupEnabled() above already uses for the group
  // switch. This only ever finds a value when the room actually has that
  // raw sensor configured (mirrors are only created for configured
  // fields) — same "omit when not configured" behaviour the panel has.
  _roomMirrorNumeric(roomName, label) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && states[id]?.attributes?.friendly_name === `${roomName} ${label}`) {
        const v = parseFloat(states[id].state);
        return Number.isNaN(v) ? null : v;
      }
    }
    return null;
  }

  _roomHumidity(roomName) { return this._roomMirrorNumeric(roomName, "Humidity"); }
  _roomCo2(roomName)      { return this._roomMirrorNumeric(roomName, "CO2"); }
  _roomBattery(roomName)  { return this._roomMirrorNumeric(roomName, "Battery"); }

  // 2026-09 frontend-parity fix: same discovery pattern, the 3 diagnostic
  // sensors this session flipped to enabled_default=True (and fixed the
  // doubled-room-name friendly_name bug on — see sensor.py).
  _roomPidPower(roomName)           { return this._roomMirrorNumeric(roomName, "PID power"); }
  _roomWindowDurationToday(roomName){ return this._roomMirrorNumeric(roomName, "Window duration"); }
  _roomCalibrationOffset(roomName)  { return this._roomMirrorNumeric(roomName, "Calibration offset"); }

  // Hub-level equivalent of _roomMirrorNumeric() — same friendly-name
  // discovery, against the global "Heat Manager" device instead of a
  // per-room one (coordinator.global_device_info()'s name is hardcoded
  // "Heat Manager", so this string is safe to match literally).
  _hubMirrorNumeric(label) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && states[id]?.attributes?.friendly_name === `Heat Manager ${label}`) {
        const v = parseFloat(states[id].state);
        return Number.isNaN(v) ? null : v;
      }
    }
    return null;
  }
  // 2026-09 audit fix (UI/UX #8) mobile follow-up: minimal per-room health
  // check using only what this card's own config actually stores per room
  // — climate_entity. Unlike the panel (which gets a full
  // unavailable_entities list per room straight from ws_get_state(),
  // covering secondary TRVs and window/humidity/CO2/battery sensors too),
  // this card has no websocket connection and its per-instance config
  // never stores window_sensors — those live in the backend's config
  // entry, not here — so this can only ever check the one entity the card
  // config actually has.
  _roomTrvUnavailable(room) {
    const id = room.climate_entity;
    if (!id) return false;
    const s = this._hass?.states?.[id];
    return !s || s.state === "unavailable" || s.state === "unknown";
  }

  // 2026-09-11 statustjek: card-level equivalent of the panel's
  // _cloudStatus() — this card has no get_state()/websocket access, so it
  // reads this._config.rooms' climate_entity list straight off hass.states,
  // same pattern as every other mirror helper on this card. Was previously
  // ENTIRELY missing at the card level: per-room "TRV offline" badges
  // existed (_roomTrvUnavailable above), but nothing told the person
  // looking at the mobile card whether one room's device had a flat battery
  // or the whole house's Netatmo connection was down — those look
  // identical, one badge at a time, unless you count them.
  //
  // Distinguishes the same three states as the panel, for the same reason
  // (see heat-manager-panel.js's _cloudStatus() docstring): HA's own
  // Netatmo integration exposes no separate reachable/connectivity signal
  // for thermostat/valve devices, so "every room down at once" is the best
  // available proxy for "cloud or gateway", vs. "one room down" (battery/RF
  // on that device) vs. "stale" (cloud responding, not updating).
  _netatmoCloudStatus() {
    const rooms = this._config.rooms ?? [];
    const climateIds = rooms.map(r => r.climate_entity).filter(Boolean);
    const empty = { ok: true, allUnavailable: false, unavailableCount: 0, totalCount: 0, staleMinutes: 0 };
    if (!climateIds.length) return empty;

    const states = this._hass?.states ?? {};
    const now = Date.now();
    let unavailableCount = 0;
    let maxStaleMs = 0;
    for (const id of climateIds) {
      const s = states[id];
      if (!s) { unavailableCount++; continue; }
      if (s.state === "unavailable" || s.state === "unknown") { unavailableCount++; continue; }
      if (s.last_updated) {
        const staleMs = now - new Date(s.last_updated).getTime();
        if (staleMs > maxStaleMs) maxStaleMs = staleMs;
      }
    }
    const totalCount     = climateIds.length;
    const allUnavailable = unavailableCount === totalCount;
    const staleMinutes   = Math.floor(maxStaleMs / 60000);
    const isStale        = staleMinutes >= 10;
    return {
      ok: unavailableCount === 0 && !isStale,
      allUnavailable, unavailableCount, totalCount, staleMinutes,
    };
  }

  // Text + color for the cloud-status row — shared between _cardHTML()
  // (first render) and _updateInPlace() (every poll) so the two can never
  // drift apart, same reasoning as get_room_target_temp() on the backend.
  _netatmoCloudStatusHTML() {
    const s = this._netatmoCloudStatus();
    if (s.ok) return { show: false, text: "", color: "" };
    if (s.allUnavailable) {
      return { show: true, color: "#ef4444", text: "☁️ Netatmo cloud/gateway nede — alle rum utilgængelige" };
    }
    if (s.unavailableCount > 0) {
      return { show: true, color: "#f97316", text: `☁️ Netatmo: ${s.unavailableCount}/${s.totalCount} rum utilgængelige` };
    }
    return { show: true, color: "#f97316", text: `☁️ Netatmo-data ${s.staleMinutes} min forsinket` };
  }

  // Mold-risk binary_sensor — same friendly_name discovery, different domain.
  _roomMoldRisk(roomName) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("binary_sensor.") && states[id]?.attributes?.friendly_name === `${roomName} Mold risk`) {
        return states[id].state === "on";
      }
    }
    return false;
  }

  // Valve/heating % — read straight off the room's own configured
  // climate_entity attribute, exactly like websocket.py's ws_get_state does
  // for the Netatmo case (heating_power_request). The Zigbee pi_demand_entity
  // override websocket.py also applies isn't available here since this
  // card's config only stores climate_entity — Netatmo rooms (the common
  // case) still get a correct reading; Zigbee rooms without that attribute
  // simply show no valve badge, same graceful-omission behaviour as
  // humidity/CO2 above.
  _roomValvePosition(climateEntityId) {
    if (!climateEntityId) return null;
    const raw = this._attr(climateEntityId, "heating_power_request");
    if (raw == null) return null;
    const v = parseFloat(raw);
    return Number.isNaN(v) ? null : v;
  }

  _outdoorTemp() {
    const id = this._config.weather_entity;
    if (!id) return null;
    const t = this._attr(id, "temperature");
    return t != null ? Math.round(t) + "°C" : null;
  }

  _seasonLabel(s) {
    return ({ winter:"Vinter", summer:"Sommer", auto:"Auto" })[s] ?? s ?? "Auto";
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  // 2026-09-07 audit fix: this card had NO error UI at all — a failed
  // service call was invisible (not even a console.error in some cases).
  // Minimal toast, mirroring heat-manager-panel.js's _showToast().
  _showToast(message, kind = "error") {
    const container = this.shadowRoot?.querySelector("#hm-toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `hm-toast hm-toast-${kind}`;
    const icon = kind === "error" ? "⚠️ " : kind === "success" ? "✅ " : "⛔ ";
    toast.textContent = icon + message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  async _setCtrl(state) {
    try {
      await this._hass.callService("heat_manager", "set_controller_state", { state });
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast("Kunne ikke ændre varme-tilstand");
    }
  }
  async _pause() {
    try {
      await this._hass.callService("heat_manager", "pause", { duration_minutes: this._pauseMinutes });
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast("Kunne ikke sætte pause");
    }
  }
  async _resume() {
    try {
      await this._hass.callService("heat_manager", "resume", {});
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast("Kunne ikke genoptage varmestyring");
    }
  }

  async _boost() {
    if (this._boostActive) { this._boostStop(); return; }

    const boostTemp    = parseFloat(this._config.boost_temp    ?? 24);
    const boostMinutes = parseInt(this._config.boost_minutes   ?? 30, 10);

    // Delegates to coordinator.async_boost_start() — the same shared
    // implementation the sidebar panel and the heat_manager.boost_start
    // service use. Previously this card wrote climate.set_temperature
    // directly to every eligible room itself, fully independent of the
    // panel/backend. That meant: (1) boosting from the panel or an
    // automation was invisible to the card and vice versa, so a second
    // click here could re-boost an already-boosted room; (2) the backend's
    // own boost_expires_at auto-restore never applied to card-started
    // boosts, since boost_active_rooms was never set server-side — only
    // this card's own setInterval tracked expiry, which stopped the moment
    // the dashboard tab closed; and (3) this card only ever boosted the
    // subset of rooms listed in ITS OWN config, not all of Heat Manager's
    // actual configured rooms. All three are fixed by delegating here.
    let result;
    try {
      result = await this._hass.callWS({
        type: "heat_manager/boost_start",
        temperature: boostTemp,
        duration_minutes: boostMinutes,
      });
    } catch (e) {
      console.warn("Heat Manager boost_start failed:", e);
      this._showToast("Kunne ikke starte boost");
      return;
    }

    this._boostActive = true;
    this._boostRemain = (result?.boost_remaining_minutes ?? boostMinutes) * 60;
    this._render();

    // Local countdown tick every second — display only. The backend's own
    // boost_expires_at is authoritative; this just ticks the on-screen
    // timer down smoothly between hass state updates.
    this._boostTimer = setInterval(() => {
      this._boostRemain -= 1;
      this._patchBoost();
      if (this._boostRemain <= 0) this._boostStop();
    }, 1000);
  }

  async _boostStop() {
    if (this._boostTimer) { clearInterval(this._boostTimer); this._boostTimer = null; }
    this._boostActive = false;
    this._boostRemain = 0;

    // Delegates to coordinator.async_boost_stop() — see _boost() above.
    try {
      await this._hass.callWS({ type: "heat_manager/boost_stop" });
    } catch (e) {
      console.warn("Heat Manager boost_stop failed:", e);
      this._showToast("Kunne ikke stoppe boost");
    }
    this._render();
  }

  _patchBoost() {
    const root = this.shadowRoot;
    const btn  = root?.querySelector("#boost-btn");
    const cntd = root?.querySelector("#boost-countdown");
    if (!btn || !cntd) return;
    if (this._boostActive) {
      const m = Math.floor(this._boostRemain / 60);
      const s = String(this._boostRemain % 60).padStart(2, "0");
      cntd.style.display = "inline";
      cntd.textContent   = m + ":" + s + " tilbage";
      btn.textContent    = "⏹ Stop boost";
      btn.style.cssText  = "background:rgba(239,68,68,0.18);border-color:#ef4444;color:#fca5a5;";
    } else {
      cntd.style.display = "none";
      btn.textContent    = "🔥 Boost";
      btn.style.cssText  = "";
    }
  }

  // ── CSS ───────────────────────────────────────────────────────────────────

  _css() {
    return `
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

      :host {
        display: block;
        height: 100%;
        /* Fallback only — real value set at runtime via
           this.style.setProperty() in _updateScale() (JS). */
        --hm-scale-h: 1;
        --bg:    var(--card-background-color, #1a2535);
        --bg2:   var(--secondary-background-color, #243044);
        --bg3:   #2d3c52;
        --text:  var(--primary-text-color, #e2e8f0);
        --sub:   var(--secondary-text-color, #94a3b8);
        --div:   var(--divider-color, rgba(148,163,184,0.12));
        --amber: #f97316;
        --teal:  #0ea5e9;
        --green: #10b981;
        --red:   #ef4444;
        font-family: 'DM Sans', var(--paper-font-body1_-_font-family, sans-serif);
      }

      * { box-sizing: border-box; margin: 0; padding: 0; }

      ha-card, .card {
        background: var(--bg);
        border-radius: var(--ha-card-border-radius, 16px);
        color: var(--text);
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.18));
        width: 100%;
        height: 100%;
        min-height: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        position: relative; /* anchors .hm-toast-container */
      }

      /* ── Header ── */
      .card-header {
        display: flex; align-items: center; gap: 12px;
        padding: calc(14px * var(--hm-scale-h)) 16px calc(10px * var(--hm-scale-h));
        border-bottom: 1px solid var(--div);
        position: relative; overflow: hidden;
        flex-shrink: 0;
      }
      .card-header::before {
        content: ''; position: absolute; inset: 0;
        background: radial-gradient(ellipse at top left, rgba(249,115,22,0.07) 0%, transparent 60%);
        pointer-events: none;
      }
      .header-icon {
        width: calc(38px * var(--hm-scale-h)); height: calc(38px * var(--hm-scale-h)); border-radius: 10px;
        background: linear-gradient(135deg, #f97316 0%, #eab308 100%);
        display: flex; align-items: center; justify-content: center;
        font-size: calc(20px * var(--hm-scale-h)); flex-shrink: 0;
        box-shadow: 0 0 14px rgba(249,115,22,0.3);
      }
      .header-text { flex: 1; }
      .header-title { font-size: calc(15px * var(--hm-scale-h)); font-weight: 700; line-height: 1.2; }
      .header-sub   { font-size: calc(11px * var(--hm-scale-h)); color: var(--sub); margin-top: 2px; font-family: 'DM Mono', monospace; }
      .ctrl-badge {
        display: inline-flex; align-items: center; gap: 5px;
        padding: calc(4px * var(--hm-scale-h)) 10px; border-radius: 20px; border: 1px solid;
        font-size: calc(11px * var(--hm-scale-h)); font-weight: 700;
      }
      .badge-dot {
        width: 6px; height: 6px; border-radius: 50%;
        animation: pulse-dot 2s infinite;
      }
      @keyframes pulse-dot {
        0%,100% { opacity:1; transform:scale(1); }
        50%      { opacity:.5; transform:scale(1.4); }
      }

      /* ── Section box ── */
      .section-box { border-bottom: 1px solid var(--div); flex-shrink: 0; }
      .section-box:last-child { border-bottom: none; }
      /* Rooms section grows to fill remaining panel height on tablet views;
         its own body becomes the scroll region so header/controller/boost
         stay fixed. See B-CARD-PANEL. */
      .section-box.rooms-section {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
      }
      .section-box.rooms-section .section-body {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
        container-type: inline-size;
        display: flex;
        flex-direction: column;
      }
      .section-header {
        display: flex; align-items: center; gap: 8px;
        padding: calc(8px * var(--hm-scale-h)) 14px;
        background: rgba(0,0,0,0.15);
        border-bottom: 1px solid var(--div);
      }
      .section-title {
        font-size: calc(10px * var(--hm-scale-h)); font-weight: 600; text-transform: uppercase;
        letter-spacing: 1px; color: var(--sub); flex: 1;
      }
      .section-badge {
        font-size: calc(9px * var(--hm-scale-h)); font-weight: 700;
        padding: 2px 6px; border-radius: 4px;
        letter-spacing: 0.5px; text-transform: uppercase;
      }
      .section-body { padding: calc(12px * var(--hm-scale-h)) 14px; }

      /* ── Controller buttons ── */
      .ctrl-btn-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 7px; margin-bottom: calc(8px * var(--hm-scale-h)); }
      .ctrl-btn {
        padding: calc(10px * var(--hm-scale-h)) 0; border-radius: 9px; border: 1px solid rgba(148,163,184,0.2);
        background: transparent; font-size: calc(12px * var(--hm-scale-h)); font-weight: 700;
        font-family: 'DM Sans', sans-serif; cursor: pointer; text-align: center;
        color: var(--sub); transition: transform .1s;
      }
      .ctrl-btn:active { transform: scale(0.97); }
      .ctrl-pause-row { display: flex; align-items: center; gap: 8px; }
      .ctrl-pause-label { font-size: calc(11px * var(--hm-scale-h)); color: var(--sub); white-space: nowrap; }
      .ctrl-pause-select {
        flex: 1; font-size: calc(11px * var(--hm-scale-h)); padding: calc(5px * var(--hm-scale-h)) 8px;
        border-radius: 7px; border: 1px solid var(--div);
        background: var(--bg2); color: var(--text);
        font-family: 'DM Sans', sans-serif;
      }
      .pause-bar {
        margin-top: 8px;
        display: flex; align-items: center; justify-content: space-between;
        padding: calc(8px * var(--hm-scale-h)) 12px;
        background: rgba(234,179,8,0.1);
        border: 1px solid rgba(234,179,8,0.25);
        border-radius: 9px;
      }
      .pause-bar-text { font-size: 12px; color: #fef08a; }
      .resume-btn {
        font-size: 11px; font-weight: 600; padding: 4px 9px;
        border-radius: 6px; border: 1px solid rgba(234,179,8,0.35);
        background: transparent; color: #fef08a; cursor: pointer;
        font-family: 'DM Sans', sans-serif;
      }

      /* v0.9.0: blocking-sources indicators */
      .blocking-row {
        display: flex; align-items: center; gap: 5px;
        padding: 0 16px calc(8px * var(--hm-scale-h));
        font-size: calc(11px * var(--hm-scale-h)); font-weight: 600; color: #fca5a5;
      }
      /* room-blocking-badge/room-ungrouped-badge/room-extra-chips (humidity/
         CO2/battery/PID/calibration/window-duration chips) used to render
         directly on the always-visible room card here — moved into the
         press-and-hold detail sheet in Fase 2, del 2 (2026-09-13; see
         .room-sheet-overlay below and planning/heat_manager_fase2_spec_
         2026-09-11.md) along with their CSS, to declutter the primary
         card view down to name/state/temp/setpoint/valve/mold/TRV-offline. */
      .room-valve-badge {
        font-size: 9px; font-weight: 600;
        color: var(--sub); margin-top: 2px;
        font-family: 'DM Mono', monospace;
        align-self: flex-end;
      }
      .room-valve-heating { color: #f97316; }
      .room-mold-badge, .room-health-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 1px 5px; border-radius: 5px; margin-top: 2px;
        background: rgba(217,119,6,0.14); color: #fbbf24;
        text-transform: uppercase; letter-spacing: 0.4px;
        align-self: flex-end;
      }


      /* ── Boost ── */
      .boost-row {
        display: flex; align-items: center; gap: 10px;
        padding: calc(12px * var(--hm-scale-h)) 16px calc(14px * var(--hm-scale-h));
      }
      .boost-btn {
        flex-shrink: 0;
        background: rgba(249,115,22,0.12); border: 1px solid var(--amber);
        color: var(--amber); border-radius: 10px; padding: calc(8px * var(--hm-scale-h)) 16px;
        font-size: calc(13px * var(--hm-scale-h)); font-weight: 700; font-family: 'DM Sans', sans-serif;
        cursor: pointer; transition: all .15s;
      }
      .boost-btn:hover { background: rgba(249,115,22,0.22); }
      .boost-info {
        flex: 1; font-size: calc(12px * var(--hm-scale-h)); color: var(--sub); line-height: 1.4;
      }
      .boost-countdown {
        font-size: calc(12px * var(--hm-scale-h)); font-weight: 600; color: var(--red);
        font-family: 'DM Mono', monospace; display: none;
      }

      /* ── Room cards ──
         2-column grid — grid-auto-flow is row-wise, so 5 rooms naturally
         land as 3 (row 1+2 left+right, row 2 left) / 2 (row 3 would-be),
         i.e. reading order 1,2 / 3,4 / 5,— giving a 3-over-2 layout when
         the room count is odd. Falls back to a single column on very
         narrow cards (e.g. sidebar/mobile width). */
      .rooms-list {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: calc(7px * var(--hm-scale-h)) 8px;
        flex: 1;
        min-height: 0;
        align-content: space-evenly;
      }
      @container (max-width: 340px) {
        .rooms-list { grid-template-columns: 1fr; }
      }
      .room-card {
        display: flex; align-items: center; gap: 8px;
        background: var(--bg2); border-radius: 11px;
        padding: calc(9px * var(--hm-scale-h)) 10px; border-left: 3px solid transparent;
        position: relative; overflow: hidden;
        min-width: 0;
      }
      .room-card-name {
        font-size: calc(13px * var(--hm-scale-h)); font-weight: 600; flex: 1;
        min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }
      .room-state-pill {
        font-size: calc(9px * var(--hm-scale-h)); font-weight: 700;
        padding: 2px 6px; border-radius: 20px;
        text-transform: uppercase; letter-spacing: .3px; flex-shrink: 0;
      }
      .room-card.state-window_open .room-state-pill,
      .room-card.state-pre_heat .room-state-pill {
        animation: badge-pulse 2s infinite;
      }
      @keyframes badge-pulse { 0%,100%{opacity:1}50%{opacity:.55} }
      .room-temps { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; flex-shrink: 0; }
      .room-temp-current  { font-size: calc(13px * var(--hm-scale-h)); font-weight: 700; font-family: 'DM Mono', monospace; }
      .room-temp-setpoint { font-size: calc(10px * var(--hm-scale-h)); color: var(--sub); }

      /* 2026-09-07 audit fix: minimal toast for action failures — this card
         previously had no error UI at all. */
      .hm-toast-container {
        position: absolute; left: 8px; right: 8px; bottom: 8px;
        display: flex; flex-direction: column; gap: 4px;
        pointer-events: none; z-index: 5;
      }
      .hm-toast {
        font-size: 11px; font-weight: 500; padding: 6px 10px;
        border-radius: 8px; color: #fff; text-align: center;
        font-family: 'DM Sans', sans-serif;
      }
      .hm-toast-error   { background: rgba(239,68,68,0.92); }
      .hm-toast-success { background: rgba(34,197,94,0.92); }
      .hm-toast-info    { background: rgba(51,65,85,0.92); }

      /* ── Room detail bottom-sheet (Fase 2, del 2 — 2026-09-13) ──
         Opened by a 500ms press-and-hold on a room card — see
         _openRoomSheet()/_roomSheetHTML(). position:fixed here is relative
         to the viewport (nothing on :host establishes a containing block
         for it), which is what a bottom sheet needs regardless of where
         this card sits in the dashboard's scroll layout. */
      .room-sheet-overlay {
        position: fixed; inset: 0; z-index: 20;
        background: rgba(0,0,0,0.5);
        display: flex; align-items: flex-end; justify-content: center;
        opacity: 0; transition: opacity .2s ease-out;
      }
      .room-sheet-overlay.open { opacity: 1; }
      .room-sheet {
        width: 100%; max-width: 480px; max-height: 80vh;
        background: var(--bg2); border-radius: 16px 16px 0 0;
        padding: 8px 16px 16px; overflow-y: auto;
        transform: translateY(100%); transition: transform .25s ease-out;
        font-family: 'DM Sans', sans-serif;
      }
      .room-sheet-overlay.open .room-sheet { transform: translateY(0); }
      .sheet-handle {
        width: 36px; height: 4px; border-radius: 2px;
        background: var(--div); margin: 6px auto 10px;
      }
      .sheet-header {
        display: flex; align-items: flex-start; justify-content: space-between;
        gap: 10px; margin-bottom: 12px;
      }
      .sheet-title { font-size: 16px; font-weight: 700; margin-bottom: 6px; }
      .sheet-close-btn {
        flex-shrink: 0; background: transparent; border: none;
        color: var(--sub); font-size: 16px; cursor: pointer; padding: 4px 8px;
      }
      .sheet-section {
        border-top: 1px solid var(--div); padding: 12px 0;
      }
      .sheet-section:first-of-type { border-top: none; padding-top: 0; }
      .sheet-section-title {
        font-size: 11px; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.5px; color: var(--sub); margin-bottom: 8px;
      }
      .sheet-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 5px 0; font-size: 13px;
      }
      .sheet-row-k { color: var(--sub); }
      .sheet-row-v { font-weight: 600; font-family: 'DM Mono', monospace; }
      .sheet-empty { font-size: 12px; color: var(--sub); padding: 4px 0; }
      .sheet-manual-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
      .sheet-temp-input, .sheet-dur-select {
        background: var(--bg); border: 1px solid var(--div); border-radius: 8px;
        color: var(--text); font-family: 'DM Mono', monospace; font-size: 13px;
        padding: 7px 9px;
      }
      .sheet-temp-input { flex: 1; min-width: 0; }
      .sheet-send-btn {
        flex-shrink: 0; background: var(--amber); color: #1a1206;
        border: none; border-radius: 8px; padding: 7px 14px;
        font-size: 12px; font-weight: 700; cursor: pointer;
      }
      .sheet-reset-btn {
        width: 100%; background: transparent; border: 1px solid var(--div);
        color: var(--sub); border-radius: 8px; padding: 7px 0;
        font-size: 12px; font-weight: 600; cursor: pointer; font-family: 'DM Sans', sans-serif;
      }
      .toggle-btn {
        padding: 6px 14px; border-radius: 8px;
        border: 1px solid var(--div); background: transparent;
        color: var(--sub); font-size: 12px; font-weight: 600;
        cursor: pointer; font-family: 'DM Sans', sans-serif;
      }
      .toggle-btn.active {
        border-color: var(--amber); color: var(--amber);
        background: rgba(249,115,22,0.12);
      }
    `;
  }

  // ── Render ────────────────────────────────────────────────────────────────

  _render() {
    const root = this.shadowRoot;

    // Inject <style> once
    if (!root.querySelector("style")) {
      const st = document.createElement("style");
      st.textContent = this._css();
      root.appendChild(st);
    }

    const html = `<ha-card><div class="card">${this._cardHTML()}</div></ha-card>`;

    const existing = root.querySelector("ha-card");
    if (existing) {
      // Replace existing ha-card safely via DOM, no insertAdjacentHTML
      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      existing.replaceWith(tmp.firstElementChild);
    } else {
      // First render — use WebKit-safe helper (no insertAdjacentHTML on ShadowRoot)
      this._srAppend(html);
    }

    this._attachEvents();
  }

  _cardHTML() {
    const ctrl      = this._ctrl();
    const season    = this._season();
    const pauseLeft = this._pauseLeft();
    const otemp     = this._outdoorTemp();

    const ctrlColor = _hmCtrlColor(ctrl);
    const sub       = [this._seasonLabel(season), otemp ? otemp + " ude" : null].filter(Boolean).join(" · ");
    const showPause = ctrl === "pause" && pauseLeft > 0;

    const btnStyle = (name) => {
      if (ctrl !== name) return "";
      const styles = {
        on:    "background:rgba(249,115,22,0.18);border-color:#f97316;color:#fed7aa;",
        pause: "background:rgba(234,179,8,0.15);border-color:#ca8a04;color:#fef08a;",
        off:   "background:rgba(148,163,184,0.12);border-color:rgba(148,163,184,0.4);color:#94a3b8;",
      };
      return styles[name] ?? "";
    };

    const rooms = this._config.rooms ?? [];
    const roomsHTML = rooms.length
      ? rooms.map(room => {
          const roomName = room.room_name ?? "";
          const state = this._roomState(roomName);
          const color = _hmStateColor(state);
          const label = _hmStateLabel(state, this._roomOverrideSource(roomName));
          const temp  = this._climateTemp(room.climate_entity ?? "");
          const setpt = this._roomSetpoint(room);
          // 2026-09-07 audit fix (5.1-5.3 mobile): valve % straight off
          // climate_entity — see the discovery helpers above for why/how.
          const valve     = this._roomValvePosition(room.climate_entity ?? "");
          const moldRisk  = this._roomMoldRisk(roomName);
          const trvDown   = this._roomTrvUnavailable(room);
          const valveBadge = valve != null
            ? `<div class="room-valve-badge${valve > 0 ? " room-valve-heating" : ""}">${valve > 0 ? "🔥" : "❄"} ${Math.round(valve)}%</div>`
            : "";
          const moldBadge = moldRisk
            ? `<div class="room-mold-badge" title="Høj fugt tæt på dugpunktet — risiko for skimmelvækst">⚠️ Skimmel</div>`
            : "";
          // 2026-09 audit fix (UI/UX #8) mobile follow-up — own CSS class,
          // not .room-mold-badge: a room can show both badges at once, and
          // _updateInPlace() manages each badge class independently.
          const trvDownBadge = trvDown
            ? `<div class="room-health-badge" title="Rummets klima-/TRV-entitet er unavailable/unknown">⚠️ TRV offline</div>`
            : "";
          // Fase 2, del 2 (2026-09-13) — humidity/CO2/battery/PID/calibration/
          // window-duration chips and the blocking-sources/ungrouped badges
          // moved off the always-visible card into the press-and-hold
          // bottom-sheet (_roomSheetHTML()) — mold risk and TRV-offline stay
          // visible here since they're rare, genuine warnings (see
          // planning/heat_manager_fase2_spec_2026-09-11.md, "Del 2"). Only
          // mold/valve/trvDown remain always visible; moldRisk/trvDown are
          // still real-time (states-based), unlike the sheet's diagnostics
          // (60s-cached from the get_state poll — see _roomSheetHTML()).
          return `
            <div class="room-card state-${state}" data-room-name="${_hmEsc(roomName)}"
              style="border-left-color:${color};background-image:linear-gradient(90deg,${color}0e 0%,transparent 40%);">
              <div class="room-card-name">${_hmEsc(roomName)}</div>
              <div class="room-state-pill" style="background:${color}22;color:${color}">${label}</div>
              <div class="room-temps">
                <div class="room-temp-current">${temp}</div>
                ${setpt ? `<div class="room-temp-setpoint">→ ${setpt}</div>` : ""}
                ${valveBadge}
                ${moldBadge}
                ${trvDownBadge}
              </div>
            </div>`;
        }).join("")
      : `<div style="color:var(--sub);font-size:12px;padding:4px 0;">Ingen rum konfigureret i kortet</div>`;

    const globalBlocked = this._globalBlockingSources();
    // 2026-09-11 statustjek: see _netatmoCloudStatusHTML() — was completely
    // missing at the card level before this.
    const cloudStatus = this._netatmoCloudStatusHTML();

    return `
      <div class="card-header">
        <div class="header-icon">🔥</div>
        <div class="header-text">
          <div class="header-title">Heat Manager</div>
          <div class="header-sub" id="hdr-sub">${_hmEsc(sub)}</div>
        </div>
        <div id="ctrl-badge" class="ctrl-badge"
          style="background:${ctrlColor}20;color:${ctrlColor};border-color:${ctrlColor}">
          <div class="badge-dot" style="background:${ctrlColor}"></div>
          ${_hmCtrlLabel(ctrl)}
        </div>
      </div>

      <div id="blocking-row" class="blocking-row" style="display:${globalBlocked.length ? "flex" : "none"}">⛔ ${_hmEsc(globalBlocked.map(s => _hmBlockingLabel(s)).join(", "))}</div>

      <div id="cloud-status-row" class="blocking-row" style="display:${cloudStatus.show ? "flex" : "none"};color:${cloudStatus.color || "#fca5a5"}">${_hmEsc(cloudStatus.text)}</div>

      <div class="section-box">
        <div class="section-header">
          <div class="section-title">Controller</div>
          <div class="section-badge" id="ctrl-state-badge"
            style="background:${ctrlColor}20;color:${ctrlColor}">${_hmCtrlLabel(ctrl)}</div>
        </div>
        <div class="section-body">
          <div class="ctrl-btn-row">
            <button id="btn-on"    class="ctrl-btn" style="${btnStyle("on")}">🔥 Tænd</button>
            <button id="btn-pause" class="ctrl-btn" style="${btnStyle("pause")}">⏸ Pause</button>
            <button id="btn-off"   class="ctrl-btn" style="${btnStyle("off")}">❄️ Sluk</button>
          </div>
          <div class="ctrl-pause-row">
            <span class="ctrl-pause-label">Pause i</span>
            <select id="pause-dur" class="ctrl-pause-select">
              <option value="30">30 min</option>
              <option value="60">1 time</option>
              <option value="120" selected>2 timer</option>
              <option value="240">4 timer</option>
              <option value="480">Til i morgen</option>
            </select>
          </div>
          <div id="pause-bar" class="pause-bar" style="display:${showPause ? "flex" : "none"}">
            <span id="pause-bar-text" class="pause-bar-text">⏸ Pause — ${pauseLeft} min tilbage</span>
            <button class="resume-btn" id="resume-btn">Genoptag nu</button>
          </div>
        </div>
      </div>

      <div class="section-box">
        <div class="section-header">
          <div class="section-title">Boost</div>
          <div class="section-badge" style="background:rgba(249,115,22,0.12);color:var(--amber)">
            ${this._config.boost_temp ?? 24}°C · ${this._config.boost_minutes ?? 30} min
          </div>
        </div>
        <div class="boost-row">
          <button id="boost-btn" class="boost-btn">🔥 Boost</button>
          <div class="boost-info">
            Øger varmen til ${this._config.boost_temp ?? 24}°C i alle aktive rum i
            ${this._config.boost_minutes ?? 30} min, derefter restore.
          </div>
          <span id="boost-countdown" class="boost-countdown"></span>
        </div>
      </div>

      ${rooms.length ? `
      <div class="section-box rooms-section">
        <div class="section-header">
          <div class="section-title">Rum</div>
          <div class="section-badge" style="background:rgba(249,115,22,0.15);color:#f97316">
            ${rooms.length} rum
          </div>
        </div>
        <div class="section-body">
          <div class="rooms-list" id="rooms-list">${roomsHTML}</div>
        </div>
      </div>` : ""}

      <div id="hm-toast-container" class="hm-toast-container" role="status" aria-live="polite"></div>
      </div>`;
  }

  // ── In-place live update ──────────────────────────────────────────────────

  _updateInPlace() {
    const root = this.shadowRoot;
    if (!root || !root.querySelector(".card")) { this._render(); return; }

    const ctrl      = this._ctrl();
    const season    = this._season();
    const pauseLeft = this._pauseLeft();
    const otemp     = this._outdoorTemp();
    const ctrlColor = _hmCtrlColor(ctrl);
    const sub       = [this._seasonLabel(season), otemp ? otemp + " ude" : null].filter(Boolean).join(" · ");
    const showPause = ctrl === "pause" && pauseLeft > 0;

    const subEl = root.querySelector("#hdr-sub");
    if (subEl) subEl.textContent = sub;

    for (const id of ["ctrl-badge", "ctrl-state-badge"]) {
      const el = root.querySelector("#" + id);
      if (!el) continue;
      el.textContent = _hmCtrlLabel(ctrl);
      el.style.background  = ctrlColor + "20";
      el.style.color       = ctrlColor;
      el.style.borderColor = ctrlColor;
    }

    const btnStyles = {
      on:    "background:rgba(249,115,22,0.18);border-color:#f97316;color:#fed7aa;",
      pause: "background:rgba(234,179,8,0.15);border-color:#ca8a04;color:#fef08a;",
      off:   "background:rgba(148,163,184,0.12);border-color:rgba(148,163,184,0.4);color:#94a3b8;",
    };
    const inactive = "background:transparent;border-color:rgba(148,163,184,0.2);color:var(--sub);";
    for (const name of ["on", "pause", "off"]) {
      const btn = root.querySelector("#btn-" + name);
      if (btn) btn.style.cssText = ctrl === name ? (btnStyles[name] ?? inactive) : inactive;
    }

    const bar  = root.querySelector("#pause-bar");
    const btxt = root.querySelector("#pause-bar-text");
    if (bar) {
      bar.style.display = showPause ? "flex" : "none";
      if (btxt && showPause) btxt.textContent = "⏸ Pause — " + pauseLeft + " min tilbage";
    }

    // v0.9.0: global blocking-sources indicator
    const globalBlocked = this._globalBlockingSources();
    const blockingRow   = root.querySelector("#blocking-row");
    if (blockingRow) {
      blockingRow.style.display = globalBlocked.length ? "flex" : "none";
      blockingRow.textContent = globalBlocked.length
        ? "⛔ " + globalBlocked.map(s => _hmBlockingLabel(s)).join(", ")
        : "";
    }

    // 2026-09-11 statustjek: Netatmo cloud/gateway status row.
    const cloudStatus  = this._netatmoCloudStatusHTML();
    const cloudRow     = root.querySelector("#cloud-status-row");
    if (cloudRow) {
      cloudRow.style.display = cloudStatus.show ? "flex" : "none";
      cloudRow.style.color   = cloudStatus.color || "#fca5a5";
      cloudRow.textContent   = cloudStatus.text;
    }

    this._patchBoost();

    const rooms = this._config.rooms ?? [];
    rooms.forEach((room, i) => {
      const cards = root.querySelectorAll(".room-card");
      if (!cards[i]) return;
      const state = this._roomState(room.room_name ?? "");
      const color = _hmStateColor(state);
      const label = _hmStateLabel(state, this._roomOverrideSource(room.room_name ?? ""));
      const temp  = this._climateTemp(room.climate_entity ?? "");
      const setpt = this._roomSetpoint(room);
      cards[i].style.borderLeftColor = color;
      cards[i].style.backgroundImage = `linear-gradient(90deg,${color}0e 0%,transparent 40%)`;
      cards[i].className = "room-card state-" + state;
      const pill = cards[i].querySelector(".room-state-pill");
      if (pill) { pill.textContent = label; pill.style.background = color + "22"; pill.style.color = color; }
      const tc = cards[i].querySelector(".room-temp-current");
      if (tc) tc.textContent = temp;
      const ts = cards[i].querySelector(".room-temp-setpoint");
      if (ts) ts.textContent = setpt ? "→ " + setpt : "";

      const tempsBox = cards[i].querySelector(".room-temps");

      // 2026-09-07 audit fix (5.1-5.3 mobile): valve/mold-risk — kept always
      // visible (see the room-card template in _cardHTML() for why). The
      // humidity/CO2/battery/PID/calibration/window-duration chips that used
      // to also patch here moved into the press-and-hold sheet in Fase 2,
      // del 2 (2026-09-13) — that sheet is a separate overlay element this
      // per-card patch loop never touches, so it needs no patch logic here.
      const roomName = room.room_name ?? "";
      const valve    = this._roomValvePosition(room.climate_entity ?? "");
      const moldRisk = this._roomMoldRisk(roomName);
      const trvDown  = this._roomTrvUnavailable(room);

      let vb = cards[i].querySelector(".room-valve-badge");
      if (valve != null) {
        const newCls = "room-valve-badge" + (valve > 0 ? " room-valve-heating" : "");
        const newTxt = (valve > 0 ? "🔥" : "❄") + " " + Math.round(valve) + "%";
        if (!vb) {
          vb = document.createElement("div");
          vb.className = newCls;
          tempsBox?.appendChild(vb);
        }
        vb.className = newCls;
        vb.textContent = newTxt;
      } else if (vb) { vb.remove(); }

      let mb = cards[i].querySelector(".room-mold-badge");
      if (moldRisk) {
        if (!mb) {
          mb = document.createElement("div");
          mb.className = "room-mold-badge";
          mb.title = "Høj fugt tæt på dugpunktet — risiko for skimmelvækst";
          mb.textContent = "⚠️ Skimmel";
          tempsBox?.appendChild(mb);
        }
      } else if (mb) { mb.remove(); }

      // 2026-09 audit fix (UI/UX #8) mobile follow-up
      let hb = cards[i].querySelector(".room-health-badge");
      if (trvDown) {
        if (!hb) {
          hb = document.createElement("div");
          hb.className = "room-health-badge";
          hb.title = "Rummets klima-/TRV-entitet er unavailable/unknown";
          hb.textContent = "⚠️ TRV offline";
          tempsBox?.appendChild(hb);
        }
      } else if (hb) { hb.remove(); }
    });

    // Fase 2, del 2 (2026-09-13) — if a room's press-and-hold sheet is
    // currently open, its diagnostic rows are a snapshot from the last
    // heat_manager/get_state poll (_roomData), not live-patched here on
    // every hass tick like the primary card above — reopening (or waiting
    // for the next 60s poll) refreshes it. Keeps this hot path (runs on
    // every relevant state-bus event) cheap.
  }

  // ── Events ────────────────────────────────────────────────────────────────

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelector("#btn-on")?.addEventListener("click",     () => this._setCtrl("on"));
    // 2026-09-07 audit fix (UI/UX-5): click-to-arm confirmation before
    // turning off heating for every room — previously a single tap did it
    // immediately, with no confirmation at all.
    root.querySelector("#btn-off")?.addEventListener("click", (e) => {
      const btn = e.currentTarget;
      if (btn.dataset.confirmOff === "1") {
        clearTimeout(this._offConfirmTimer);
        delete btn.dataset.confirmOff;
        btn.textContent = btn.dataset.offOrigLabel || "❄️ Sluk";
        this._setCtrl("off");
        return;
      }
      btn.dataset.offOrigLabel = btn.dataset.offOrigLabel || btn.textContent;
      btn.dataset.confirmOff = "1";
      btn.textContent = "Tryk igen";
      this._offConfirmTimer = setTimeout(() => {
        delete btn.dataset.confirmOff;
        btn.textContent = btn.dataset.offOrigLabel;
      }, 3000);
    });
    root.querySelector("#resume-btn")?.addEventListener("click", () => this._resume());
    root.querySelector("#pause-dur")?.addEventListener("change", e => {
      this._pauseMinutes = parseInt(e.target.value, 10);
    });
    root.querySelector("#btn-pause")?.addEventListener("click",  () => this._pause());
    root.querySelector("#boost-btn")?.addEventListener("click",  () => this._boost());

    // Fase 2, del 2 (2026-09-13) — press-and-hold a room card to open its
    // detail bottom-sheet (humidity/CO2/battery/PID/calibration/window-
    // duration/door status, blocking reasons, ungrouped state, manual
    // temperature override, grouping toggle — everything that used to be
    // always-visible chips/badges on the card itself). 500ms hold,
    // cancelled on release or on enough pointer movement to look like a
    // scroll drag rather than a deliberate press — see
    // planning/heat_manager_fase2_spec_2026-09-11.md, "Del 2".
    let holdTimer  = null;
    let holdStartX = 0;
    let holdStartY = 0;
    const roomsList = root.querySelector("#rooms-list");
    roomsList?.addEventListener("pointerdown", (e) => {
      const card = e.target.closest(".room-card");
      if (!card) return;
      holdStartX = e.clientX;
      holdStartY = e.clientY;
      const roomName = card.dataset.roomName;
      holdTimer = setTimeout(() => {
        holdTimer = null;
        this._openRoomSheet(roomName);
      }, 500);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((evt) => {
      roomsList?.addEventListener(evt, () => {
        if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
      });
    });
    roomsList?.addEventListener("pointermove", (e) => {
      if (!holdTimer) return;
      if (Math.abs(e.clientX - holdStartX) > 10 || Math.abs(e.clientY - holdStartY) > 10) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
    });
  }

  // ── Room detail bottom-sheet (Fase 2, del 2 — 2026-09-13) ─────────────────
  // Opened by a 500ms press-and-hold on a room card (see the pointerdown
  // wiring in _attachEvents() above). Content is built from two sources: the
  // card's own states-based mirror helpers (same ones the primary card view
  // already used before this feature — still real-time), and, where richer
  // data is available, the full per-room snapshot from the last
  // heat_manager/get_state poll (this._roomData, refreshed every 60s by
  // _loadTargetTemps() — see that method) for fields this card has no other
  // way to discover at all (door status/heat-up rate, trv_count).

  _openRoomSheet(roomName) {
    if (!roomName) return;
    this._closeRoomSheet(); // only one sheet at a time
    this._openSheetRoom = roomName;
    const root = this.shadowRoot;
    const overlay = document.createElement("div");
    overlay.className = "room-sheet-overlay";
    overlay.id = "room-sheet-overlay";
    overlay.innerHTML = this._roomSheetHTML(roomName);
    root.appendChild(overlay);
    this._attachRoomSheetEvents(overlay, roomName);
    // Trigger the slide-up transition on the next frame rather than at
    // insertion time, so the browser has a "before" state (opacity/transform
    // at their initial values) to actually transition from.
    requestAnimationFrame(() => overlay.classList.add("open"));
  }

  _closeRoomSheet() {
    const root = this.shadowRoot;
    const existing = root?.querySelector("#room-sheet-overlay");
    if (existing) existing.remove();
    this._openSheetRoom = null;
  }

  _roomGroupSwitchId(roomName) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("switch.") && states[id]?.attributes?.friendly_name === `${roomName} Group`) return id;
    }
    return null;
  }

  _roomSheetHTML(roomName) {
    const rd    = this._roomData?.[roomName] ?? null;
    const state = this._roomState(roomName);
    const color = _hmStateColor(state);
    const label = _hmStateLabel(state, rd?.override_source ?? this._roomOverrideSource(roomName));

    const humidity  = rd?.humidity ?? this._roomHumidity(roomName);
    const co2       = rd?.co2 ?? this._roomCo2(roomName);
    const battery   = rd?.battery_level ?? this._roomBattery(roomName);
    const pidPower  = rd?.pid_power ?? this._roomPidPower(roomName);
    const calib     = rd?.calibration_offset ?? this._roomCalibrationOffset(roomName);
    const windowDur = rd?.window_duration_today ?? this._roomWindowDurationToday(roomName);

    const rows = [];
    if (humidity != null)   rows.push(["💧 Fugt", Math.round(humidity) + "%"]);
    if (co2 != null)        rows.push(["🫧 CO₂", Math.round(co2) + " ppm"]);
    if (battery != null)    rows.push(["🔋 Batteri", Math.round(battery) + "%"]);
    if (pidPower != null)   rows.push(["⚙️ PID-effekt", Math.round(pidPower) + "%"]);
    if (calib != null)      rows.push(["🎯 Kalibrering", (calib >= 0 ? "+" : "") + calib.toFixed(1) + "°C"]);
    if (windowDur != null)  rows.push(["🪟 Vindue åbent i dag", Math.round(windowDur) + " min"]);

    // Interior doors (2026-09-11) — only ever available via the backend
    // get_state snapshot (rd); this card has no states-based way to
    // discover door linkage or the learned heat-up-rate at all.
    if (rd?.door_open != null) {
      rows.push(["🚪 Dør", rd.door_open ? "Åben" : "Lukket"]);
    }
    if (rd?.heatup_rate_door_open != null || rd?.heatup_rate_door_closed != null) {
      const parts = [];
      if (rd.heatup_rate_door_open != null)   parts.push(`åben: ${rd.heatup_rate_door_open.toFixed(1)}°C/t`);
      if (rd.heatup_rate_door_closed != null) parts.push(`lukket: ${rd.heatup_rate_door_closed.toFixed(1)}°C/t`);
      rows.push(["📈 Opvarmningshastighed", parts.join(" · ")]);
    }

    // Card/panel data-parity (2026-09-13) — sync_mode and schedule_entity
    // are config-only strings this card's own instance config never stores
    // (they live in the backend config entry), so — same as door_open/
    // heatup_rate/trv_count above — the get_state snapshot (rd) is the only
    // way to show them at all. Mirrors panel.js's Rum-detaljer meta-badge
    // row (same _syncModeLabel() labels, same "schedule configured" wording
    // rather than the raw entity_id, which the panel doesn't show either).
    if (rd?.sync_mode && rd.sync_mode !== "disabled") {
      rows.push(["🔄 Sync", _hmSyncModeLabel(rd.sync_mode)]);
    }
    if (rd?.schedule_entity) {
      rows.push(["🗓 Schedule", "Konfigureret"]);
    }

    // Punkt 12 (2026-09-14, card/panel data-parity) — target_temp/away_temp
    // read-out, mirroring the panel's Rum-fane inline room-cfg rows
    // (target_temp is already used as the manual-temp input's placeholder
    // below, but wasn't shown as its own labelled row anywhere on this
    // card until now — same gap for away_temp_override, which the card
    // never surfaced at all). Both are plain rd reads, only present once
    // the 60s get_state poll has completed.
    if (rd?.target_temp != null) {
      rows.push(["🎯 Mål-temp", rd.target_temp.toFixed(1) + "°C"]);
    }
    if (rd?.away_temp_override != null) {
      rows.push(["🚀 Away-temp", rd.away_temp_override.toFixed(1) + "°C"]);
    }

    // Punkt 12 — Netatmo cloud-diagnostik, mirroring the panel's
    // Rum-detaljer "🛰️ Netatmo:" row (_roomDetailRowHTML's netatmoHTML) — only
    // present for rooms with a Netatmo cloud climate entity (None for
    // Zigbee/local rooms, same as the panel). Shows what Netatmo's OWN
    // cloud entity currently reports, separate from Heat Manager's
    // resolved Mål-temp above — the exact distinction the B21 target-temp
    // bug (2026-09-11) made worth surfacing on both surfaces, not just the
    // panel.
    if (rd?.cloud_preset_mode || rd?.cloud_selected_schedule || rd?.cloud_temperature != null) {
      const parts = [];
      if (rd.cloud_preset_mode) parts.push(rd.cloud_preset_mode);
      if (rd.cloud_selected_schedule) parts.push(`(${rd.cloud_selected_schedule})`);
      if (parts.length) rows.push(["🛰️ Netatmo", parts.join(" ")]);
      if (rd.cloud_temperature != null) {
        rows.push(["🛰️ Netatmo sætpunkt", (Math.round(rd.cloud_temperature * 10) / 10) + "°C"]);
      }
      if (rd.cloud_hvac_action) {
        rows.push(["🛰️ Netatmo hvac", rd.cloud_hvac_action]);
      }
    }

    // Punkt 4/12 — combined per-room health score, same weighting as the
    // panel's 🩺 badge (websocket.py's health_score/health_label) — only
    // shown when below 100, same threshold the panel badge uses.
    if (rd?.health_score != null && rd.health_score < 100) {
      rows.push(["🩺 Sundhed", `${Math.round(rd.health_score)}% (${rd.health_label ?? "–"})`]);
    }

    const extraBlocking = rd?.blocking_sources
      ? rd.blocking_sources.filter(s => !((s === "window" && state === "window_open") || (s === "presence" && state === "away")))
      : this._roomExtraBlocking(roomName, state);
    if (extraBlocking.length) {
      rows.push(["⛔ Blokeret af", extraBlocking.map(s => _hmBlockingLabel(s)).join(", ")]);
    }

    const trvCount     = rd?.trv_count ?? 1;
    const groupEnabled = rd?.group_enabled ?? this._roomGroupEnabled(roomName);
    const showGrouping = trvCount > 1;

    const rowsHTML = rows.length
      ? rows.map(([k, v]) => `<div class="sheet-row"><span class="sheet-row-k">${_hmEsc(k)}</span><span class="sheet-row-v">${_hmEsc(v)}</span></div>`).join("")
      : `<div class="sheet-empty">Ingen yderligere data for dette rum</div>`;

    const currentSetpoint = rd?.target_temp ?? this._targetTemps?.[roomName] ?? null;

    return `
      <div class="room-sheet" data-room-name="${_hmEsc(roomName)}">
        <div class="sheet-handle"></div>
        <div class="sheet-header">
          <div>
            <div class="sheet-title">${_hmEsc(roomName)}</div>
            <div class="room-state-pill" style="background:${color}22;color:${color}">${_hmEsc(label)}</div>
          </div>
          <button class="sheet-close-btn" data-action="close-sheet">✕</button>
        </div>

        <div class="sheet-section">${rowsHTML}</div>

        <div class="sheet-section">
          <div class="sheet-section-title">Manuel temperatur</div>
          <div class="sheet-manual-row">
            <input type="number" class="sheet-temp-input" id="sheet-temp-input" min="10" max="30" step="0.5"
              placeholder="${currentSetpoint != null ? currentSetpoint.toFixed(1) : "—"}">
            <select class="sheet-dur-select" id="sheet-dur-select">
              <option value="60" selected>1 time</option>
              <option value="120">2 timer</option>
              <option value="240">4 timer</option>
              <option value="0">Permanent</option>
            </select>
            <button class="sheet-send-btn" data-action="sheet-send-temp">Send</button>
          </div>
          <button class="sheet-reset-btn" data-action="sheet-reset-temp">↺ Gendan schedule</button>
        </div>

        ${showGrouping ? `
        <div class="sheet-section">
          <div class="sheet-section-title">Gruppering (${trvCount} TRV'er)</div>
          <div class="sheet-manual-row" style="justify-content:space-between">
            <span style="font-size:12px;color:var(--sub)">Ekstra TRV'er følger gruppen</span>
            <button class="toggle-btn${groupEnabled ? " active" : ""}" data-action="sheet-toggle-group">
              ${groupEnabled ? "Slå fra" : "Slå til"}
            </button>
          </div>
        </div>` : ""}
      </div>`;
  }

  _attachRoomSheetEvents(overlay, roomName) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) this._closeRoomSheet();
    });
    overlay.querySelector("[data-action='close-sheet']")?.addEventListener("click", () => this._closeRoomSheet());

    overlay.querySelector("[data-action='sheet-send-temp']")?.addEventListener("click", async () => {
      const input = overlay.querySelector("#sheet-temp-input");
      const dur   = overlay.querySelector("#sheet-dur-select");
      const temp  = parseFloat(input?.value);
      if (Number.isNaN(temp)) {
        this._showToast("Angiv en temperatur", "error");
        return;
      }
      try {
        await this._hass.callWS({
          type: "heat_manager/set_room_temp",
          room_name: roomName,
          temperature: temp,
          duration_min: parseInt(dur?.value ?? "60", 10),
        });
        this._showToast(`${roomName}: ${temp}°C sendt`, "success");
        setTimeout(() => this._loadTargetTemps(), 300);
      } catch (e) {
        console.error("Heat Manager: sheet send temp failed", e);
        this._showToast("Kunne ikke sende temperatur", "error");
      }
    });

    overlay.querySelector("[data-action='sheet-reset-temp']")?.addEventListener("click", async () => {
      try {
        await this._hass.callWS({
          type: "heat_manager/set_room_temp",
          room_name: roomName,
          temperature: null,
        });
        this._showToast(`${roomName}: schedule gendannet`, "success");
        setTimeout(() => this._loadTargetTemps(), 300);
      } catch (e) {
        console.error("Heat Manager: sheet reset temp failed", e);
        this._showToast("Kunne ikke gendanne schedule", "error");
      }
    });

    overlay.querySelector("[data-action='sheet-toggle-group']")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const entityId = this._roomGroupSwitchId(roomName);
      if (!entityId) return;
      const currentlyEnabled = this._roomGroupEnabled(roomName);
      try {
        await this._hass.callService("switch", currentlyEnabled ? "turn_off" : "turn_on", { entity_id: entityId });
        btn.classList.toggle("active");
        btn.textContent = currentlyEnabled ? "Slå til" : "Slå fra";
      } catch (e2) {
        console.error("Heat Manager: sheet group toggle failed", e2);
        this._showToast("Kunne ikke ændre gruppering", "error");
      }
    });
  }

  static getConfigElement() {
    return document.createElement("heat-manager-card-editor");
  }
}

if (!customElements.get("heat-manager-card")) {
  customElements.define("heat-manager-card", HeatManagerCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === "heat-manager-card")) {
  window.customCards.push({
    type: "heat-manager-card",
    name: "Heat Manager",
    description: "ON/PAUSE/OFF controller, rum-oversigt og energistatistik",
    preview: true,
    documentationURL: "https://github.com/kingpainter/heat-manager",
  });
}


// ─────────────────────────────────────────────────────────────────────────────
// heat-manager-card-editor
// ─────────────────────────────────────────────────────────────────────────────

class HeatManagerCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config   = {};
    this._hass     = null;
    this._rooms    = [];
    this._rendered = false;
  }

  set hass(h) {
    this._hass = h;
    if (!this._rendered) this._render();
  }

  setConfig(config) {
    this._config   = { ...config };
    this._rooms    = JSON.parse(JSON.stringify(config.rooms || []));
    this._rendered = false;
    this._render();
  }

  _fire() {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail:   { config: { ...this._config, rooms: this._rooms } },
      bubbles:  true,
      composed: true,
    }));
  }

  _css() {
    return `
      :host {
        display: block; padding: 4px 0;
        font-family: var(--primary-font-family, sans-serif);
        --bg:   var(--card-background-color, #1a2535);
        --bg2:  var(--secondary-background-color, #243044);
        --text: var(--primary-text-color, #e2e8f0);
        --sub:  var(--secondary-text-color, #94a3b8);
        --div:  var(--divider-color, rgba(148,163,184,0.12));
      }
      * { box-sizing: border-box; margin: 0; padding: 0; }
      .section-title {
        font-size: 11px; font-weight: 700; text-transform: uppercase;
        letter-spacing: 1px; color: var(--sub);
        padding: 14px 0 8px; border-top: 1px solid var(--div);
        margin-top: 4px; display: flex;
        justify-content: space-between; align-items: center;
      }
      .section-title.first { border-top: none; padding-top: 4px; }
      .field { margin-bottom: 10px; }
      label  { display: block; font-size: 12px; color: var(--sub); margin-bottom: 5px; }
      input, select {
        width: 100%; padding: 8px 10px; font-size: 13px;
        border: 1px solid var(--div); border-radius: 8px;
        background: var(--bg2); color: var(--text); font-family: inherit;
      }
      input:focus, select:focus {
        outline: none; border-color: #f97316;
        box-shadow: 0 0 0 2px rgba(249,115,22,0.15);
      }
      .add-btn {
        font-size: 11px; padding: 4px 11px; border-radius: 6px;
        border: 1px solid #f97316; background: rgba(249,115,22,0.1);
        color: #f97316; cursor: pointer; font-weight: 600;
      }
      .room-block {
        border: 1px solid var(--div); border-radius: 10px;
        padding: 10px 12px; margin-bottom: 8px; background: var(--bg2);
      }
      .room-hdr {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 9px;
      }
      .room-title { font-size: 12px; font-weight: 600; color: var(--text); }
      .del-btn {
        font-size: 10px; padding: 3px 8px; border-radius: 6px;
        border: 1px solid rgba(239,68,68,0.4); background: transparent;
        color: #ef4444; cursor: pointer;
      }
      .hint { font-size: 10px; color: var(--sub); margin-top: 3px; }
      .empty-rooms {
        padding: 14px; text-align: center; color: var(--sub);
        font-size: 12px; border: 1px dashed var(--div);
        border-radius: 8px; margin-bottom: 8px;
      }
    `;
  }

  _esc(s) {
    return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  _render() {
    this._rendered = true;
    const c = this._config;
    const r = this._rooms;

    const roomsHTML = r.length
      ? r.map((room, i) => `
          <div class="room-block">
            <div class="room-hdr">
              <span class="room-title">Rum ${i + 1}${room.room_name ? " — " + this._esc(room.room_name) : ""}</span>
              <button class="del-btn" data-del="${i}">Slet</button>
            </div>
            <div class="field">
              <label>Rumnavn (matcher Heat Manager config)</label>
              <input class="room-name" data-idx="${i}" type="text"
                value="${this._esc(room.room_name || "")}" placeholder="f.eks. Køkken">
            </div>
            <div class="field">
              <label>Klimaenhed</label>
              <input class="room-climate" data-idx="${i}" type="text"
                value="${this._esc(room.climate_entity || "")}" placeholder="climate.koekken">
              <div class="hint">Bruges til at vise aktuel temperatur</div>
            </div>
          </div>`).join("")
      : `<div class="empty-rooms">Ingen rum endnu — klik "+ Tilføj rum"</div>`;

    // Editor uses innerHTML — fine here since it's not the card's ShadowRoot
    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="section-title first">Globale indstillinger</div>
      <div class="field">
        <label>Vejr-entitet (til ude-temperatur i header)</label>
        <input id="weather" type="text"
          value="${this._esc(c.weather_entity || "")}" placeholder="weather.forecast_home">
      </div>
      <div class="section-title">Boost-indstillinger</div>
      <div class="field">
        <label>Boost-temperatur (°C)</label>
        <input id="boost-temp" type="number" min="18" max="30" step="0.5"
          value="${this._esc(String(c.boost_temp ?? 24))}" placeholder="24">
      </div>
      <div class="field">
        <label>Boost-varighed (min)</label>
        <input id="boost-minutes" type="number" min="5" max="120" step="5"
          value="${this._esc(String(c.boost_minutes ?? 30))}" placeholder="30">
      </div>
      <div class="section-title">
        Rum <button class="add-btn" id="add-room">+ Tilføj rum</button>
      </div>
      <div id="rooms-container">${roomsHTML}</div>`;

    this._attachEditorEvents();
  }

  _attachEditorEvents() {
    const root = this.shadowRoot;
    root.querySelector("#weather")?.addEventListener("change", e => {
      this._config.weather_entity = e.target.value.trim(); this._fire();
    });
    root.querySelector("#boost-temp")?.addEventListener("change", e => {
      const v = parseFloat(e.target.value);
      if (!isNaN(v)) { this._config.boost_temp = v; this._fire(); }
    });
    root.querySelector("#boost-minutes")?.addEventListener("change", e => {
      const v = parseInt(e.target.value, 10);
      if (!isNaN(v)) { this._config.boost_minutes = v; this._fire(); }
    });
    root.querySelector("#add-room")?.addEventListener("click", () => {
      this._rooms.push({ room_name: "", climate_entity: "" });
      this._render(); this._fire();
    });
    root.querySelectorAll(".room-name").forEach(el => {
      el.addEventListener("change", e => {
        this._rooms[+e.target.dataset.idx].room_name = e.target.value.trim();
        this._render(); this._fire();
      });
    });
    root.querySelectorAll(".room-climate").forEach(el => {
      el.addEventListener("change", e => {
        this._rooms[+e.target.dataset.idx].climate_entity = e.target.value.trim();
        this._fire();
      });
    });
    root.querySelectorAll("[data-del]").forEach(btn => {
      btn.addEventListener("click", e => {
        this._rooms.splice(+e.target.dataset.del, 1);
        this._render(); this._fire();
      });
    });
  }
}

if (!customElements.get("heat-manager-card-editor")) {
  customElements.define("heat-manager-card-editor", HeatManagerCardEditor);
}
