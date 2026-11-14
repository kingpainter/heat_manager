// Heat Manager — Lovelace card (custom element "heat-manager-card").
//
// Version: follows manifest.json. Change history: CHANGELOG.md.
// Design: unified with Indeklima — DM Sans/DM Mono, section-box system,
// amber/orange heat palette.

// ── i18n (v0.71.0) ───────────────────────────────────────────────────────────
// English is the default; other languages come from
// frontend/translations/<lang>.json via heat_manager/get_translations (the
// backend fills in English for any key a translation lacks). Shared by every
// card instance on the page and the card editor.

var _hmI18n = (window.__heatManagerCardI18n = window.__heatManagerCardI18n || { lang: null, strings: null, loading: null });

function _hmLang(hass) {
  return hass?.locale?.language || hass?.language || "en";
}

// True when the strings for the user's current language still have to be
// fetched (first load, or the user switched language in their profile).
function _hmNeedsTranslations(hass) {
  return !!hass?.callWS && (_hmI18n.lang !== _hmLang(hass) || (!_hmI18n.strings && !_hmI18n.loading));
}

function _hmLoadTranslations(hass) {
  const lang = _hmLang(hass);
  if (_hmI18n.lang === lang && _hmI18n.loading) return _hmI18n.loading;
  _hmI18n.lang = lang;
  _hmI18n.loading = hass.callWS({ type: "heat_manager/get_translations", language: lang })
    .then((res) => { if (_hmI18n.lang === lang) _hmI18n.strings = res?.resources ?? {}; })
    .catch((e) => { console.error("[HeatManager] translations", e); _hmI18n.strings = _hmI18n.strings ?? {}; })
    .finally(() => { _hmI18n.loading = null; });
  return _hmI18n.loading;
}

// Translate `key`, replacing {name} placeholders from `params`. Before the
// strings have arrived it returns "" (the card re-renders once they land).
function _hmT(key, params) {
  if (!_hmI18n.strings) return "";
  let s = _hmI18n.strings[key];
  if (s == null) s = key;
  if (params) s = s.replace(/\{(\w+)\}/g, (m, k) => {
    const v = params[k];
    if (v == null) return m;
    // v0.72.0: a param can reference another text ({key, params}).
    if (typeof v === "object" && v.key) return _hmT(v.key, v.params);
    return String(v);
  });
  return s;
}

// ── Shared helpers ────────────────────────────────────────────────────────────

// v0.71.0: an issue from build_active_issues() in the user's language —
// `key`/`params` when the backend sends them, the English `message` otherwise.
function _hmIssueText(issue) {
  if (issue?.key && _hmI18n.strings) {
    const txt = _hmT(`issue.${issue.key}`, issue.params ?? {});
    if (txt !== `issue.${issue.key}`) return txt;
  }
  return issue?.message ?? "";
}

function _hmEsc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function _hmStateColor(s) {
  return ({ normal:"#f97316", away:"#64748b", window_open:"#ef4444", pre_heat:"#0ea5e9", override:"#a855f7" })[s] ?? "#64748b";
}

// v0.59.0: "Normal" → "Auto" and "Override" → "Manuel" (+ the source's
// icon), so each room tile answers "automatic or manual?" at a glance. The
// full source name and auto-restore time are on the mode row and in the
// room sheet.
function _hmStateLabel(s, source) {
  if (s === "override") {
    const icon = _hmOverrideSourceIcon(source);
    return icon ? _hmT("card.state_manual_icon", { icon }) : _hmT("state.override");
  }
  return ["normal", "away", "window_open", "pre_heat"].includes(s) ? _hmT(`state.${s}`) : (s || "–");
}

function _hmOverrideSourceName(src) {
  return ["remote", "panel", "switch", "trv"].includes(src) ? _hmT(`source.${src}`) : null;
}

function _hmOverrideSourceIcon(src) {
  return ({ remote:"📡", panel:"🖥", switch:"🔘", trv:"🎚" })[src] ?? null;
}

// "20:42" from an ISO timestamp, in the browser's local time.
function _hmHhmm(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// v0.67.2: Netatmo's own view of a room as one translated phrase — same wording
// as the panel ("Following schedule «Winter» · not heating").
function _hmNetatmoModeText(rd) {
  if (!rd) return "";
  const parts = [];
  const mode  = rd.cloud_setpoint_mode;
  const sched = rd.cloud_selected_schedule;
  const until = _hmHhmm(rd.cloud_setpoint_end_time);
  if (mode === "schedule" || mode === "home") {
    parts.push(sched ? _hmT("rd.follows_schedule_named", { schedule: sched }) : _hmT("rd.follows_schedule"));
  } else if (mode) {
    const label = ["manual", "max", "away", "hg", "off"].includes(mode) ? _hmT(`card.netatmo.${mode}`) : mode;
    parts.push(until && (mode === "manual" || mode === "max") ? _hmT("card.netatmo.until", { mode: label, time: until }) : label);
  } else if (rd.cloud_preset_mode) {
    const preset = _hmT("rd.preset", { preset: rd.cloud_preset_mode });
    parts.push(sched ? `${preset} («${sched}»)` : preset);
  }
  if (rd.cloud_hvac_action) {
    const a = rd.cloud_hvac_action;
    parts.push(["heating", "idle", "off"].includes(a) ? _hmT(`rd.hvac_${a}`) : a);
  }
  return parts.join(" · ");
}

function _hmCtrlColor(s) {
  return ({ on:"#f97316", pause:"#eab308", off:"#64748b" })[s] ?? "#64748b";
}

function _hmCtrlLabel(s) {
  // 2026-09-16: panel.js's _ctrlTitle() shows a friendly title for these
  // same three states; the card uses the same translation keys instead of
  // the raw state.
  return ["on", "pause", "off"].includes(s) ? _hmT(`ctrl.title.${s}`) : (s || "–");
}

// v0.9.0: self-reporting diagnostics — short translated tags for the neutral
// blocking_sources codes coordinator.get_room_blocking_sources() returns.
function _hmBlockingLabel(s) {
  return ["controller_off", "controller_pause", "window", "presence"].includes(s) ? _hmT(`blocking.${s}`) : s;
}

// Card/panel data-parity (2026-09-13) — same labels as panel.js's own
// _syncModeLabel(), so a room configured with sync_mode shows the identical
// translated label on both surfaces.
function _hmSyncModeLabel(mode) {
  return ["disabled", "mirror", "lock"].includes(mode) ? _hmT(`sync_mode.${mode}`) : mode;
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
    this._roomData     = null;
    this._roomByClimate = null;  // v0.69.2 — climate_entity → Heat Manager room name (see _cardRooms())   // Fase 2, del 2 (2026-09-13) — room name → full get_state room dict (door status, trv_count, etc. for the press-and-hold sheet)
    this._openSheetRoom = null;  // room name currently shown in the bottom-sheet, if any
  }

  setConfig(config) {
    this._config = config || {};
    this._updateScale();
    this._render();
  }

  set hass(h) {
    this._hass = h;
    // v0.71.0: fetch the UI strings for the user's language (again, if they
    // switched language) and rebuild once they are in.
    if (_hmNeedsTranslations(h)) _hmLoadTranslations(h).then(() => this._render());
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
    this._checkHouseStatusChange();
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
    // v0.60.0: the compact smart line is rebuilt on every patch — delegate
    // its clicks/keys from the shadow root, bound once.
    if (!this._slcBound) {
      this._slcBound = true;
      this.shadowRoot.addEventListener("click", (e) => {
        if (e.target.closest?.("#smart-compact")) this._onSmartCompactClick(e);
      });
      this.shadowRoot.addEventListener("keydown", (e) => {
        if ((e.key === "Enter" || e.key === " ") && e.target.closest?.("[data-slc='toggle']")
            && !e.target.closest?.("[data-slc-act]")) {
          e.preventDefault();
          this._onSmartCompactClick(e);
        }
      });
    }
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
    // v0.59.0: the boost countdown interval kept ticking after the card
    // was removed from the DOM.
    if (this._boostTimer) { clearInterval(this._boostTimer); this._boostTimer = null; }
    clearTimeout(this._slcRefreshTimer);
    this._slcRefreshTimer = null;
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

  // v0.69.2: this card's rooms resolved against Heat Manager. Every lookup
  // (backend snapshot, entity friendly names, WS commands) keys on the
  // integration's own room name, but the card's YAML has its own copy that
  // can drift ("Soveværelse" vs "Soveværelset"). Match by name first, then
  // by climate_entity; `label` keeps the YAML name for display, and
  // `hm_missing` is true once the snapshot has loaded and neither matched.
  _cardRooms() {
    return (this._config.rooms ?? []).map(r => {
      const own = r?.room_name ?? "";
      let name = own;
      let found = !!this._roomData?.[own];
      if (!found && r?.climate_entity && this._roomByClimate?.[r.climate_entity]) {
        name = this._roomByClimate[r.climate_entity];
        found = true;
      }
      return { ...r, room_name: name, label: own || name, hm_missing: this._roomData != null && !found };
    });
  }

  // YAML label for a resolved Heat Manager room name (sheet title, toasts).
  _roomLabel(roomName) {
    return this._cardRooms().find(r => r.room_name === roomName)?.label ?? roomName;
  }

  // v0.67.2: a room with a valve (climate entity) can be controlled; a room
  // with only sensors cannot. Prefer the backend snapshot, fall back to this
  // card's own room config before the first get_state poll has landed.
  _roomHasValve(room) {
    const rd = this._roomData?.[room?.room_name ?? ""];
    if (rd) return !!rd.climate_entity;
    return !!room?.climate_entity;
  }

  // v0.67.2: the room's own temperature (external room sensor when set) from
  // the backend snapshot; the valve's reading only as a fallback — it sits on
  // the radiator and typically reads 1-3 °C high.
  _roomTempText(room) {
    const t = this._roomData?.[room?.room_name ?? ""]?.current_temp;
    if (t != null) return (Math.round(t * 10) / 10) + "°C";
    return this._climateTemp(room?.climate_entity ?? "");
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
      // v0.69.2: climate_entity → Heat Manager room name, so a card room
      // whose YAML name differs from the integration's (e.g. "Badværelse"
      // vs "Badeværelse") still finds its backend data — see _cardRooms().
      const byClimate = {};
      for (const room of data?.rooms ?? []) {
        if (room?.name != null) {
          roomData[room.name] = room;
          if (room.climate_entity) byClimate[room.climate_entity] = room.name;
          if (room.target_temp != null) map[room.name] = room.target_temp;
        }
      }
      this._targetTemps = map;
      this._roomData = roomData;
      this._roomByClimate = byClimate;
      this._wsData = data; // v0.60.0: active_issues/remote_last_action for the smart line
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
    return this._roomStateAttr(name, "override_source");
  }

  // v0.59.0: any attribute off the room's state sensor (override_source,
  // override_expires_at, override_since, ...).
  _roomStateAttr(name, attr) {
    const states = this._hass?.states ?? {};
    const key = name.toLowerCase().replace(/\s+/g, "_");
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith("_" + key + "_state")) {
        return states[id].attributes?.[attr] ?? null;
      }
    }
    return null;
  }

  // ── v0.60.0: compact smart status line ──────────────────────────────────
  // Mobile version of the panel's smart line: one tile (icon, or a ring
  // counting down to the next automatic change), one plain-language title
  // and at most one action. Tap folds out the context lines and anything
  // else currently going on. Live parts come from the Hub "Status" sensor
  // (instant); warnings/acknowledgements from the 60 s get_state poll,
  // which is re-fetched immediately when that sensor changes.

  _houseStatusState() {
    const states = this._hass?.states ?? {};
    if (!this._houseStatusEntityId && Date.now() >= (this._houseStatusRetryAt ?? 0)) {
      this._houseStatusEntityId = Object.keys(states).find(id =>
        id.startsWith("sensor.") && Array.isArray(states[id]?.attributes?.window_rooms)
          && states[id]?.attributes?.boost_remaining_min !== undefined) ?? null;
      if (!this._houseStatusEntityId && this._hass) this._houseStatusRetryAt = Date.now() + 30000;
    }
    return this._houseStatusEntityId ? states[this._houseStatusEntityId] ?? null : null;
  }

  _durText(ms) {
    const min = Math.max(0, Math.round(ms / 60000));
    if (min < 1) return _hmT("dur.under_1m");
    const h = Math.floor(min / 60), m = min % 60;
    return h ? (m ? _hmT("dur.h_m", { h, m }) : _hmT("dur.h", { h })) : _hmT("dur.m", { m });
  }

  _smartMessages() {
    const hs = this._houseStatusState();
    const a = hs?.attributes ?? {};
    const d = this._wsData ?? {};
    const msgs = [];
    const rla = d.remote_last_action;
    const age = rla?.timestamp ? Date.now() - Date.parse(rla.timestamp) : NaN;
    if (!isNaN(age) && age > -60000 && age < 10000) {
      const n = rla.rooms?.length ?? 0;
      const dlt = rla.delta != null ? `${rla.delta > 0 ? "+" : "−"}${String(Math.abs(rla.delta)).replace(".", _hmT("common.decimal_sep"))}°` : "";
      const title = ({
        temp_up: () => _hmT("card.ack.temp", { delta: dlt, count: n }),
        temp_down: () => _hmT("card.ack.temp", { delta: dlt, count: n }),
        manual: () => _hmT("card.ack.manual", { count: n }),
        auto: () => _hmT("card.ack.auto", { count: n }),
        boost: () => _hmT("card.ack.boost", { count: n }),
        release: () => _hmT("card.ack.release"),
      })[rla.action]?.() ?? _hmT("ack.received");
      const skipped = Object.keys(rla.skipped ?? {});
      msgs.push({ tone: "ack", icon: "✓", title, subs: skipped.length ? [_hmT("ack.skipped", { rooms: skipped.join(", ") })] : [] });
      return msgs;
    }
    for (const i of (d.active_issues ?? []).filter(i => i.severity === "critical")) {
      msgs.push({ tone: "critical", icon: i.icon ?? "!", title: _hmIssueText(i), subs: [] });
    }
    if (hs?.state === "off") msgs.push({ tone: "off", icon: "⏻", title: _hmT("card.sl.off"), subs: [] });
    if (hs?.state === "paused") msgs.push({ tone: "pause", icon: "⏸", title: _hmT("card.sl.pause", { duration: this._durText((a.pause_remaining_min ?? 0) * 60000) }), subs: [] });
    for (const i of (d.active_issues ?? []).filter(i => i.severity === "warning" && !i.snoozed)) {
      msgs.push({ tone: "warning", icon: i.icon ?? "!", title: _hmIssueText(i), subs: [] });
    }
    const manual = a.manual_rooms ?? [];
    if (manual.length) {
      const until = a.auto_returns_at ? Date.parse(a.auto_returns_at) : NaN;
      let ring = null;
      const since = manual.map(n => Date.parse(this._roomData?.[n]?.override_since ?? "")).filter(t => !isNaN(t));
      if (!isNaN(until) && since.length) {
        const start = Math.min(...since);
        if (until > start) ring = Math.min(1, Math.max(0, (until - Date.now()) / (until - start)));
      }
      // Prefer the get_state payload's source: the state-sensor lookup in
      // _roomOverrideSource() matches on a slug that misses æ/ø/å room names.
      const srcs = [...new Set(manual.map(n => this._roomData?.[n]?.override_source ?? this._roomOverrideSource(n)))];
      msgs.push({
        tone: "manual",
        icon: srcs.length === 1 ? (_hmOverrideSourceIcon(srcs[0]) ?? "✋") : "✋",
        title: _hmT("card.sl.manual", {
          count: manual.length,
          expiry: isNaN(until) ? _hmT("sl.no_expiry_short") : _hmT("card.sl.auto_in", { duration: this._durText(until - Date.now()) }),
        }),
        subs: [manual.join(", ")],
        ring,
        action: { act: "release", label: _hmT("sl.auto_now") },
      });
    }
    if ((a.boost_remaining_min ?? 0) > 0) {
      msgs.push({ tone: "ack", icon: "⚡", title: _hmT("card.sl.boost", { duration: this._durText(a.boost_remaining_min * 60000) }), subs: [] });
    }
    if (!msgs.length) msgs.push({ tone: "ok", icon: "✓", title: _hmT("card.sl.ok"), subs: [] });
    return msgs;
  }

  _smartCompactHTML() {
    const msgs = this._smartMessages();
    const m = msgs[0];
    const c = 119.38;
    const ring = m.ring != null
      ? `<svg class="slc-ring" viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="19" fill="none" class="slc-track" stroke-width="3.5"/><circle cx="22" cy="22" r="19" fill="none" class="slc-fill" stroke-width="3.5" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${(c * (1 - m.ring)).toFixed(1)}" transform="rotate(-90 22 22)"/></svg>`
      : "";
    const more = msgs.length > 1 ? `<span class="slc-more">+${msgs.length - 1}</span>` : "";
    const act = m.action ? `<button class="slc-btn" data-slc-act="${m.action.act}">${_hmEsc(m.action.label)}</button>` : "";
    const open = !!this._slcOpen;
    const detail = open
      ? `<div class="slc-detail">${[...(m.subs ?? []).map(t => `<div class="slc-line">${_hmEsc(t)}</div>`),
          ...msgs.slice(1).map(x => `<div class="slc-line">${_hmEsc(x.icon)} ${_hmEsc(x.title)}</div>`)].join("")
          || `<div class="slc-line">${_hmT("card.sl.nothing_else")}</div>`}</div>`
      : "";
    return { tone: m.tone, html: `<div class="slc-main" data-slc="toggle" role="button" tabindex="0" aria-expanded="${open}">
        <div class="slc-tile">${ring}<span class="slc-icon">${_hmEsc(m.icon)}</span></div>
        <div class="slc-title">${_hmEsc(m.title)}</div>${more}${act}
      </div>${detail}` };
  }

  _patchSmartCompact() {
    const el = this.shadowRoot?.querySelector("#smart-compact");
    if (!el) return;
    const { tone, html } = this._smartCompactHTML();
    el.className = `slc tone-${tone}`;
    el.innerHTML = html;
  }

  async _onSmartCompactClick(e) {
    const btn = e.target.closest?.("[data-slc-act]");
    if (btn) {
      e.stopPropagation();
      try {
        const res = await this._hass.callWS({ type: "heat_manager/release_overrides" });
        const n = res?.rooms_released?.length ?? 0;
        this._showToast(n ? _hmT("toast.released", { count: n }) : _hmT("card.toast.already_auto"), "success");
      } catch (err) {
        this._showToast(_hmT("toast.try_again"), "error");
      }
      this._loadTargetTemps();
      return;
    }
    if (e.target.closest?.("[data-slc='toggle']")) {
      this._slcOpen = !this._slcOpen;
      this._patchSmartCompact();
    }
  }

  // Re-fetch get_state right away when the Status sensor changes, so a
  // remote press or a new warning shows without waiting for the 60 s poll.
  _checkHouseStatusChange() {
    const hs = this._houseStatusState();
    if (!hs) return;
    const sig = hs.state + JSON.stringify(hs.attributes ?? {});
    if (this._houseStatusSig === undefined) { this._houseStatusSig = sig; return; }
    if (sig === this._houseStatusSig) return;
    this._houseStatusSig = sig;
    clearTimeout(this._slcRefreshTimer);
    this._slcRefreshTimer = setTimeout(() => { this._slcRefreshTimer = null; this._loadTargetTemps(); }, 500);
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
    this._cardRooms().forEach(room =>
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
    const rooms = this._cardRooms();
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
      return { show: true, color: "#ef4444", text: "☁️ " + _hmT("card.cloud.all_down") };
    }
    if (s.unavailableCount > 0) {
      return { show: true, color: "#f97316", text: "☁️ " + _hmT("card.cloud.some_down", { count: s.unavailableCount, total: s.totalCount }) };
    }
    return { show: true, color: "#f97316", text: "☁️ " + _hmT("card.cloud.stale", { minutes: s.staleMinutes }) };
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
    return ["auto", "winter", "spring", "summer", "autumn"].includes(s) ? _hmT(`season.${s}`) : (s ?? _hmT("season.auto"));
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
      this._showToast(_hmT("toast.controller_failed"));
    }
  }
  async _pause() {
    try {
      await this._hass.callService("heat_manager", "pause", { duration_minutes: this._pauseMinutes });
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast(_hmT("toast.pause_failed"));
    }
  }
  async _resume() {
    try {
      await this._hass.callService("heat_manager", "resume", {});
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast(_hmT("toast.resume_failed"));
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
      this._showToast(_hmT("card.toast.boost_start_failed"));
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
      this._showToast(_hmT("card.toast.boost_stop_failed"));
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
      cntd.textContent   = _hmT("card.boost_left", { time: m + ":" + s });
      btn.textContent    = "⏹ " + _hmT("card.boost_stop");
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
      /* v0.60.0: compact smart status line — one tone per state */
      .slc {
        --sl: #10b981; --sl-rgb: 16,185,129;
        margin: 0 16px calc(8px * var(--hm-scale-h));
        border-radius: 12px; border: 1px solid rgba(var(--sl-rgb),0.45);
        background: linear-gradient(135deg, rgba(var(--sl-rgb),0.16) 0%, rgba(var(--sl-rgb),0.04) 100%);
      }
      .slc.tone-manual   { --sl: #c084fc; --sl-rgb: 168,85,247; }
      .slc.tone-warning  { --sl: #f59e0b; --sl-rgb: 245,158,11; }
      .slc.tone-critical { --sl: #f87171; --sl-rgb: 239,68,68; }
      .slc.tone-ack      { --sl: #38bdf8; --sl-rgb: 14,165,233; }
      .slc.tone-pause    { --sl: #facc15; --sl-rgb: 234,179,8; }
      .slc.tone-off      { --sl: #94a3b8; --sl-rgb: 148,163,184; }
      .slc-main {
        display: flex; align-items: center; gap: 10px; cursor: pointer;
        padding: calc(6px * var(--hm-scale-h)) 10px;
      }
      .slc-tile {
        position: relative; flex: 0 0 34px; width: 34px; height: 34px; border-radius: 10px;
        display: flex; align-items: center; justify-content: center;
        background: rgba(var(--sl-rgb),0.16); color: var(--sl); font-size: 15px;
      }
      .slc-ring { position: absolute; inset: 0; width: 34px; height: 34px; }
      .slc-track { stroke: rgba(var(--sl-rgb),0.25); }
      .slc-fill { stroke: var(--sl); }
      .slc-icon { position: relative; line-height: 1; }
      .slc-title {
        flex: 1 1 auto; min-width: 0; color: var(--sl);
        font-size: calc(12px * var(--hm-scale-h)); font-weight: 600; line-height: 1.3;
      }
      .slc.tone-ok .slc-title { color: var(--text); }
      .slc-more {
        font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 10px;
        background: rgba(var(--sl-rgb),0.2); color: var(--sl);
      }
      .slc-btn {
        font: inherit; font-size: 11px; font-weight: 600; white-space: nowrap; cursor: pointer;
        padding: 5px 10px; border-radius: 16px; color: var(--green);
        background: transparent; border: 1px solid rgba(16,185,129,0.5);
      }
      .slc-detail { padding: 0 10px 8px 54px; }
      .slc-line { font-size: calc(11px * var(--hm-scale-h)); color: var(--sub); line-height: 1.5; }
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
    const sub       = [this._seasonLabel(season), otemp ? _hmT("card.outdoor", { temp: otemp }) : null].filter(Boolean).join(" · ");
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

    const rooms = this._cardRooms();
    const roomsHTML = rooms.length
      ? rooms.map(room => {
          const roomName = room.room_name ?? "";
          const state = this._roomState(roomName);
          const hasValve = this._roomHasValve(room);
          // Sensor-only rooms have no heating state to colour by: neutral slate.
          const color = hasValve ? _hmStateColor(state) : "#64748b";
          // Short pill on the narrow tile; the sheet says "Sensors only".
          const label = room.hm_missing ? _hmT("card.unknown_room")
            : hasValve ? _hmStateLabel(state, this._roomOverrideSource(roomName)) : _hmT("card.sensors");
          const temp  = this._roomTempText(room);
          const setpt = hasValve ? this._roomSetpoint(room) : null;
          // 2026-09-07 audit fix (5.1-5.3 mobile): valve % straight off
          // climate_entity — see the discovery helpers above for why/how.
          const valve     = this._roomValvePosition(room.climate_entity ?? "");
          const moldRisk  = this._roomMoldRisk(roomName);
          const trvDown   = this._roomTrvUnavailable(room);
          const valveBadge = valve != null
            ? `<div class="room-valve-badge${valve > 0 ? " room-valve-heating" : ""}">${valve > 0 ? "🔥" : "❄"} ${Math.round(valve)}%</div>`
            : "";
          const moldBadge = moldRisk
            ? `<div class="room-mold-badge" title="${_hmT("room_card.mold_title")}">⚠️ ${_hmT("card.mold")}</div>`
            : "";
          // 2026-09 audit fix (UI/UX #8) mobile follow-up — own CSS class,
          // not .room-mold-badge: a room can show both badges at once, and
          // _updateInPlace() manages each badge class independently.
          const trvDownBadge = trvDown
            ? `<div class="room-health-badge" title="${_hmT("card.valve_offline_title")}">⚠️ ${_hmT("card.valve_offline")}</div>`
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
              <div class="room-card-name">${_hmEsc(room.label ?? roomName)}</div>
              <div class="room-state-pill" style="${hasValve ? `background:${color}22;color:${color}` : "background:rgba(148,163,184,0.15);color:var(--sub)"}">${label}</div>
              <div class="room-temps">
                <div class="room-temp-current">${temp}</div>
                ${setpt ? `<div class="room-temp-setpoint">→ ${setpt}</div>` : ""}
                ${valveBadge}
                ${moldBadge}
                ${trvDownBadge}
              </div>
            </div>`;
        }).join("")
      : `<div style="color:var(--sub);font-size:12px;padding:4px 0;">${_hmT("card.no_rooms")}</div>`;

    const globalBlocked = this._globalBlockingSources();
    const smart = this._smartCompactHTML(); // v0.60.0
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

      <div id="smart-compact" class="slc tone-${smart.tone}">${smart.html}</div>

      <div id="blocking-row" class="blocking-row" style="display:${globalBlocked.length ? "flex" : "none"}">⛔ ${_hmEsc(globalBlocked.map(s => _hmBlockingLabel(s)).join(", "))}</div>

      <div id="cloud-status-row" class="blocking-row" style="display:${cloudStatus.show ? "flex" : "none"};color:${cloudStatus.color || "#fca5a5"}">${_hmEsc(cloudStatus.text)}</div>

      <div class="section-box">
        <div class="section-header">
          <div class="section-title">${_hmT("ctrl.section")}</div>
          <div class="section-badge" id="ctrl-state-badge"
            style="background:${ctrlColor}20;color:${ctrlColor}">${_hmCtrlLabel(ctrl)}</div>
        </div>
        <div class="section-body">
          <div class="ctrl-btn-row">
            <button id="btn-on"    class="ctrl-btn" style="${btnStyle("on")}">🔥 ${_hmT("ctrl.btn_on")}</button>
            <button id="btn-pause" class="ctrl-btn" style="${btnStyle("pause")}">⏸ ${_hmT("ctrl.btn_pause")}</button>
            <button id="btn-off"   class="ctrl-btn" style="${btnStyle("off")}">❄️ ${_hmT("ctrl.btn_off")}</button>
          </div>
          <div class="ctrl-pause-row">
            <span class="ctrl-pause-label">${_hmT("card.pause_in")}</span>
            <select id="pause-dur" class="ctrl-pause-select">
              <option value="30">${_hmT("ctrl.dur_30m")}</option>
              <option value="60">${_hmT("ctrl.dur_1h")}</option>
              <option value="120" selected>${_hmT("ctrl.dur_2h")}</option>
              <option value="240">${_hmT("ctrl.dur_4h")}</option>
              <option value="480">${_hmT("ctrl.dur_tomorrow")}</option>
            </select>
          </div>
          <div id="pause-bar" class="pause-bar" style="display:${showPause ? "flex" : "none"}">
            <span id="pause-bar-text" class="pause-bar-text">⏸ ${_hmT("ctrl.pause_left", { minutes: pauseLeft })}</span>
            <button class="resume-btn" id="resume-btn">${_hmT("ctrl.resume_now")}</button>
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
            ${_hmT("card.boost_info", { temp: this._config.boost_temp ?? 24, minutes: this._config.boost_minutes ?? 30 })}
          </div>
          <span id="boost-countdown" class="boost-countdown"></span>
        </div>
      </div>

      ${rooms.length ? `
      <div class="section-box rooms-section">
        <div class="section-header">
          <div class="section-title">${_hmT("overview.rooms")}</div>
          <div class="section-badge" style="background:rgba(249,115,22,0.15);color:#f97316">
            ${_hmT("card.rooms_count", { count: rooms.length })}
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
    const sub       = [this._seasonLabel(season), otemp ? _hmT("card.outdoor", { temp: otemp }) : null].filter(Boolean).join(" · ");
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
      if (btxt && showPause) btxt.textContent = "⏸ " + _hmT("ctrl.pause_left", { minutes: pauseLeft });
    }

    // v0.60.0: compact smart status line
    this._patchSmartCompact();

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

    const rooms = this._cardRooms();
    rooms.forEach((room, i) => {
      const cards = root.querySelectorAll(".room-card");
      if (!cards[i]) return;
      const state = this._roomState(room.room_name ?? "");
      const hasValve = this._roomHasValve(room);
      const color = hasValve ? _hmStateColor(state) : "#64748b";
      const label = room.hm_missing ? _hmT("card.unknown_room")
        : hasValve ? _hmStateLabel(state, this._roomOverrideSource(room.room_name ?? "")) : _hmT("card.sensors");
      const temp  = this._roomTempText(room);
      const setpt = hasValve ? this._roomSetpoint(room) : null;
      // v0.69.2: the resolved Heat Manager name can change once the first
      // get_state poll lands — keep press-and-hold pointed at it.
      cards[i].dataset.roomName = room.room_name ?? "";
      if (room.hm_missing) cards[i].title = _hmT("card.unknown_room_title");
      else cards[i].removeAttribute("title");
      cards[i].style.borderLeftColor = color;
      cards[i].style.backgroundImage = `linear-gradient(90deg,${color}0e 0%,transparent 40%)`;
      cards[i].className = "room-card state-" + state;
      const pill = cards[i].querySelector(".room-state-pill");
      if (pill) {
        pill.textContent = label;
        pill.style.background = hasValve ? color + "22" : "rgba(148,163,184,0.15)";
        pill.style.color = hasValve ? color : "var(--sub)";
      }
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
          mb.title = _hmT("room_card.mold_title");
          mb.textContent = "⚠️ " + _hmT("card.mold");
          tempsBox?.appendChild(mb);
        }
      } else if (mb) { mb.remove(); }

      // 2026-09 audit fix (UI/UX #8) mobile follow-up
      let hb = cards[i].querySelector(".room-health-badge");
      if (trvDown) {
        if (!hb) {
          hb = document.createElement("div");
          hb.className = "room-health-badge";
          hb.title = _hmT("card.valve_offline_title");
          hb.textContent = "⚠️ " + _hmT("card.valve_offline");
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
        btn.textContent = btn.dataset.offOrigLabel || "❄️ " + _hmT("ctrl.btn_off");
        this._setCtrl("off");
        return;
      }
      btn.dataset.offOrigLabel = btn.dataset.offOrigLabel || btn.textContent;
      btn.dataset.confirmOff = "1";
      btn.textContent = _hmT("card.press_again");
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
    // v0.67.2: same structure and section names as the panel's room card
    // (v0.66.0) — named sections, one distinct name per value. Rooms without
    // a valve ("Sensors only") show measurements only: no PID, target,
    // Netatmo rows or manual controls.
    const rd    = this._roomData?.[roomName] ?? null;
    const room  = this._cardRooms().find(r => r.room_name === roomName) ?? { room_name: roomName };
    const hasValve = this._roomHasValve(room);
    const state = this._roomState(roomName);
    const color = _hmStateColor(state);
    const label = hasValve
      ? _hmStateLabel(state, rd?.override_source ?? this._roomOverrideSource(roomName))
      : _hmT("rd.sensors_only");
    const pillStyle = hasValve
      ? `background:${color}22;color:${color}`
      : "background:rgba(148,163,184,0.15);color:var(--sub)";
    const fmt = (v, unit = "°C") => v != null ? `${Math.round(v * 10) / 10}${unit}` : null;

    const humidity  = rd?.humidity ?? this._roomHumidity(roomName);
    const co2       = rd?.co2 ?? this._roomCo2(roomName);
    const battery   = rd?.battery_level ?? (hasValve ? this._roomBattery(roomName) : null);
    const pidPower  = hasValve ? (rd?.pid_power ?? this._roomPidPower(roomName)) : null;
    const calib     = hasValve ? (rd?.calibration_offset ?? this._roomCalibrationOffset(roomName)) : null;
    const windowDur = rd?.window_duration_today ?? this._roomWindowDurationToday(roomName);

    const sections = [];
    const add = (title, rows) => {
      const kept = rows.filter(r => r && r[1] != null);
      if (kept.length) sections.push([title, kept]);
    };

    // Temperatur
    const roomTemp = rd?.current_temp ?? null;
    add(_hmT("rd.sec_temperature"), [
      [_hmT("rd.in_room"), fmt(roomTemp) ?? (hasValve ? this._climateTemp(room.climate_entity ?? "") : null)],
      hasValve ? [_hmT("rd.target_now"), fmt(rd?.target_temp ?? this._targetTemps?.[roomName])] : null,
      hasValve && rd?.comfort_temp != null ? [_hmT("rd.comfort"), fmt(rd.comfort_temp)] : null,
      hasValve ? [_hmT("rd.sent_to_valve"), fmt(rd?.trv_setpoint)] : null,
      hasValve ? [_hmT("rd.at_radiator"), this._climateTemp(room.climate_entity ?? rd?.climate_entity ?? "")] : null,
    ]);

    // Ventil
    if (hasValve) {
      const valve = rd?.valve_position ?? this._roomValvePosition(room.climate_entity ?? "");
      const netatmo = [];
      const mode = _hmNetatmoModeText(rd);
      if (mode) netatmo.push(["Netatmo", mode]);
      if (rd?.cloud_temperature != null) {
        netatmo.push([_hmT("rd.netatmo_setpoint"), fmt(rd.cloud_temperature)]);
        const ref = rd.trv_setpoint ?? rd.target_temp;
        if (ref != null && Math.abs(rd.cloud_temperature - ref) >= 0.5) {
          netatmo.push([_hmT("sheet.deviates"), _hmT(rd.trv_setpoint != null ? "sheet.hm_sent" : "sheet.hm_wants", { temp: fmt(ref) })]);
        }
      }
      add(_hmT("rd.sec_valve"), [
        [_hmT("rd.opening"), valve != null ? `${Math.round(valve)}%` : null],
        [_hmT("rd.heat_demand"), pidPower != null ? `${Math.round(pidPower)}%` : null],
        [_hmT("rd.calibration"), calib != null ? `${calib >= 0 ? "+" : ""}${calib.toFixed(1)}°C` : null],
        [_hmT("rd.battery"), battery != null ? `${Math.round(battery)}%` : null],
        rd?.trv_count > 1 ? [_hmT("sheet.valves_in_room"), String(rd.trv_count)] : null,
        ...netatmo,
      ]);
    }

    // Indeklima
    const doors = (this._wsData?.doors ?? []).filter(d => d.room_a === roomName || d.room_b === roomName);
    const doorRows = doors.map(d => {
      const other = d.room_a === roomName ? d.room_b : d.room_a;
      return [_hmT("rd.door_to", { room: other }), _hmT(d.available === false ? "rd.door_unavailable" : (d.is_open ? "rd.open" : "rd.closed"))];
    });
    if (!doors.length && rd?.door_open != null) doorRows.push([_hmT("sheet.door"), _hmT(rd.door_open ? "rd.open" : "rd.closed")]);
    add(_hmT("rd.sec_climate"), [
      [_hmT("rd.humidity"), humidity != null ? `${Math.round(humidity)}%` : null],
      [_hmT("rd.co2"), co2 != null ? `${Math.round(co2)} ppm` : null],
      [_hmT("rd.window_today"), windowDur != null ? `${Math.round(windowDur)} min` : null],
      ...doorRows,
      rd?.has_heated_doors ? [_hmT("rd.outer_door"), _hmT(rd.heated_door_open ? "rd.open" : "rd.closed")] : null,
    ]);

    // Status
    const status = [];
    if (hasValve && state === "override") {
      const src   = rd?.override_source ?? this._roomOverrideSource(roomName);
      const since = _hmHhmm(rd?.override_since ?? this._roomStateAttr(roomName, "override_since"));
      const until = _hmHhmm(rd?.override_expires_at ?? this._roomStateAttr(roomName, "override_expires_at"));
      const parts = [`${_hmOverrideSourceIcon(src) ?? "✋"} ${_hmOverrideSourceName(src) ?? _hmT("state.override")}`];
      if (since) parts.push(_hmT("override_info.since", { time: since }));
      parts.push(until ? _hmT("sheet.auto_again", { time: until }) : _hmT("override_info.no_expiry"));
      status.push([_hmT("sheet.manual_control"), parts.join(" · ")]);
    }
    const extraBlocking = rd?.blocking_sources
      ? rd.blocking_sources.filter(s => !((s === "window" && state === "window_open") || (s === "presence" && state === "away")))
      : this._roomExtraBlocking(roomName, state);
    if (hasValve && extraBlocking.length) {
      status.push([_hmT("sheet.blocked_by"), extraBlocking.map(s => _hmBlockingLabel(s)).join(", ")]);
    }
    if (rd?.health_score != null && rd.health_score < 100) {
      // v0.71.0: health_label is "good"/"ok"/"poor"; older backends sent Danish.
      const hl = ({ god: "good", "dårlig": "poor" })[rd.health_label] ?? rd.health_label;
      const hlText = ["good", "ok", "poor"].includes(hl) ? _hmT(`health.${hl}`) : (hl ?? "–");
      status.push([_hmT("sheet.health"), `${Math.round(rd.health_score)}% (${hlText})`]);
    }
    if (hasValve && rd?.sync_mode && rd.sync_mode !== "disabled") {
      status.push([_hmT("sheet.sync"), _hmSyncModeLabel(rd.sync_mode)]);
    }
    if (rd?.heatup_rate_door_open != null || rd?.heatup_rate_door_closed != null) {
      const parts = [];
      if (rd.heatup_rate_door_open != null)   parts.push(_hmT("sheet.rate_door_open", { rate: rd.heatup_rate_door_open.toFixed(1) }));
      if (rd.heatup_rate_door_closed != null) parts.push(_hmT("sheet.rate_door_closed", { rate: rd.heatup_rate_door_closed.toFixed(1) }));
      status.push([_hmT("sheet.heating"), parts.join(" · ")]);
    }
    add(_hmT("sheet.status"), status);

    const sectionsHTML = sections.length
      ? sections.map(([title, rows]) => `
        <div class="sheet-section">
          <div class="sheet-section-title">${_hmEsc(title)}</div>
          ${rows.map(([k, v]) => `<div class="sheet-row"><span class="sheet-row-k">${_hmEsc(k)}</span><span class="sheet-row-v">${_hmEsc(v)}</span></div>`).join("")}
        </div>`).join("")
      : `<div class="sheet-section"><div class="sheet-empty">${_hmT("sheet.no_data")}</div></div>`;

    const trvCount     = rd?.trv_count ?? 1;
    const groupEnabled = rd?.group_enabled ?? this._roomGroupEnabled(roomName);
    const showGrouping = hasValve && trvCount > 1;
    const currentSetpoint = rd?.target_temp ?? this._targetTemps?.[roomName] ?? null;

    return `
      <div class="room-sheet" data-room-name="${_hmEsc(roomName)}">
        <div class="sheet-handle"></div>
        <div class="sheet-header">
          <div>
            <div class="sheet-title">${_hmEsc(this._roomLabel(roomName))}</div>
            <div class="room-state-pill" style="${pillStyle}">${_hmEsc(label)}</div>
          </div>
          <button class="sheet-close-btn" data-action="close-sheet" aria-label="${_hmT("sheet.close")}">✕</button>
        </div>

        ${sectionsHTML}

        ${hasValve ? `
        <div class="sheet-section">
          <div class="sheet-section-title">${_hmT("rd.sec_temporary")}</div>
          <div class="sheet-manual-row">
            <input type="number" class="sheet-temp-input" id="sheet-temp-input" min="10" max="30" step="0.5"
              aria-label="${_hmT("rd.temperature")}"
              placeholder="${currentSetpoint != null ? currentSetpoint.toFixed(1) : "—"}">
            <select class="sheet-dur-select" id="sheet-dur-select" aria-label="${_hmT("rd.duration")}">
              <option value="60" selected>${_hmT("ctrl.dur_1h")}</option>
              <option value="120">${_hmT("ctrl.dur_2h")}</option>
              <option value="240">${_hmT("ctrl.dur_4h")}</option>
              <option value="0">${_hmT("rd.until_further")}</option>
            </select>
            <button class="sheet-send-btn" data-action="sheet-send-temp">${_hmT("rooms.set")}</button>
          </div>
          <button class="sheet-reset-btn" data-action="sheet-reset-temp">↺ ${_hmT("rooms.back_to_auto")}</button>
        </div>` : ""}

        ${showGrouping ? `
        <div class="sheet-section">
          <div class="sheet-section-title">${_hmT("sheet.valve_group", { count: trvCount })}</div>
          <div class="sheet-manual-row" style="justify-content:space-between">
            <span style="font-size:12px;color:var(--sub)">${_hmT("sheet.extra_valves")}</span>
            <button class="toggle-btn${groupEnabled ? " active" : ""}" data-action="sheet-toggle-group">
              ${_hmT(groupEnabled ? "common.turn_off" : "common.turn_on")}
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
        this._showToast(_hmT("sheet.enter_temp"), "error");
        return;
      }
      try {
        await this._hass.callWS({
          type: "heat_manager/set_room_temp",
          room_name: roomName,
          temperature: temp,
          duration_min: parseInt(dur?.value ?? "60", 10),
        });
        this._showToast(_hmT("sheet.temp_set", { room: this._roomLabel(roomName), temp }), "success");
        setTimeout(() => this._loadTargetTemps(), 300);
      } catch (e) {
        console.error("Heat Manager: sheet send temp failed", e);
        this._showToast(_hmT("sheet.send_failed"), "error");
      }
    });

    overlay.querySelector("[data-action='sheet-reset-temp']")?.addEventListener("click", async () => {
      try {
        await this._hass.callWS({
          type: "heat_manager/set_room_temp",
          room_name: roomName,
          temperature: null,
        });
        this._showToast(_hmT("sheet.back_to_auto", { room: this._roomLabel(roomName) }), "success");
        setTimeout(() => this._loadTargetTemps(), 300);
      } catch (e) {
        console.error("Heat Manager: sheet reset temp failed", e);
        this._showToast(_hmT("sheet.reset_failed"), "error");
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
        btn.textContent = _hmT(currentlyEnabled ? "common.turn_on" : "common.turn_off");
      } catch (e2) {
        console.error("Heat Manager: sheet group toggle failed", e2);
        this._showToast(_hmT("sheet.group_failed"), "error");
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
    description: "ON/PAUSE/OFF controller, room overview and smart status line",
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
    // v0.71.0: same shared strings as the card; re-render once they land.
    if (_hmNeedsTranslations(h)) _hmLoadTranslations(h).then(() => this._render());
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
              <span class="room-title">${_hmT("editor.room_n", { n: i + 1 })}${room.room_name ? " — " + this._esc(room.room_name) : ""}</span>
              <button class="del-btn" data-del="${i}">${_hmT("editor.delete")}</button>
            </div>
            <div class="field">
              <label>${_hmT("editor.room_name")}</label>
              <input class="room-name" data-idx="${i}" type="text"
                value="${this._esc(room.room_name || "")}" placeholder="${this._esc(_hmT("editor.room_name_placeholder"))}">
            </div>
            <div class="field">
              <label>${_hmT("editor.climate")}</label>
              <input class="room-climate" data-idx="${i}" type="text"
                value="${this._esc(room.climate_entity || "")}" placeholder="climate.kitchen">
              <div class="hint">${_hmT("editor.climate_hint")}</div>
            </div>
          </div>`).join("")
      : `<div class="empty-rooms">${this._esc(_hmT("editor.no_rooms"))}</div>`;

    // Editor uses innerHTML — fine here since it's not the card's ShadowRoot
    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="section-title first">${_hmT("editor.global")}</div>
      <div class="field">
        <label>${_hmT("editor.weather")}</label>
        <input id="weather" type="text"
          value="${this._esc(c.weather_entity || "")}" placeholder="weather.forecast_home">
      </div>
      <div class="section-title">${_hmT("editor.boost")}</div>
      <div class="field">
        <label>${_hmT("editor.boost_temp")}</label>
        <input id="boost-temp" type="number" min="18" max="30" step="0.5"
          value="${this._esc(String(c.boost_temp ?? 24))}" placeholder="24">
      </div>
      <div class="field">
        <label>${_hmT("editor.boost_minutes")}</label>
        <input id="boost-minutes" type="number" min="5" max="120" step="5"
          value="${this._esc(String(c.boost_minutes ?? 30))}" placeholder="30">
      </div>
      <div class="section-title">
        ${_hmT("editor.rooms")} <button class="add-btn" id="add-room">${_hmT("editor.add_room")}</button>
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
