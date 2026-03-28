// Heat Manager — Custom Lovelace Card
// Version: 0.3.1
//
// Fix B-CARD-IAH: _render() used optional-chaining syntax on replaceWith()
// that is invalid in some JS engines. Replaced with explicit null check.
// Also adds _srAppendHTML() helper (WebKit-safe, same as panel) so the
// first-render path never calls insertAdjacentHTML on a ShadowRoot.
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

function _hmStateLabel(s) {
  return ({ normal:"Normal", away:"Fraværende", window_open:"Vindue åbent", pre_heat:"Forvarmning", override:"Override" })[s] ?? (s || "–");
}

function _hmCtrlColor(s) {
  return ({ on:"#f97316", pause:"#eab308", off:"#64748b" })[s] ?? "#64748b";
}

function _hmCtrlLabel(s) {
  return ({ on:"On", pause:"Pause", off:"Off" })[s] ?? (s || "–");
}

function _hmEffColor(score) {
  if (score == null) return "#64748b";
  if (score >= 80) return "#f97316";
  if (score >= 50) return "#eab308";
  return "#ef4444";
}

function _hmRingHTML(score, size) {
  const s    = size || 80;
  const r    = Math.round(s * 0.38);
  const cx   = Math.round(s / 2);
  const c    = _hmEffColor(score);
  const circ = 2 * Math.PI * r;
  const pct  = score != null ? Math.min(100, score) / 100 : 0;
  const fill = pct * circ;
  const gap  = circ - fill;
  const valSz = s >= 80 ? 18 : 14;
  return `
    <div class="ring-wrap">
      <svg class="ring-svg" viewBox="0 0 ${s} ${s}" style="width:${s}px;height:${s}px;display:block;">
        <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="rgba(148,163,184,0.12)" stroke-width="7"/>
        <circle cx="${cx}" cy="${cx}" r="${r}" fill="none"
          stroke="${c}" stroke-width="7" stroke-linecap="round"
          stroke-dasharray="${fill} ${gap}" stroke-dashoffset="0"
          transform="rotate(-90 ${cx} ${cx})"/>
      </svg>
      <div class="ring-center">
        <div class="ring-val" style="color:${c};font-size:${valSz}px">${score != null ? score : "–"}</div>
        <div class="ring-unit">score</div>
      </div>
    </div>`;
}


// ─────────────────────────────────────────────────────────────────────────────
// heat-manager-card
// ─────────────────────────────────────────────────────────────────────────────

class HeatManagerCard extends HTMLElement {
  static getStubConfig() {
    return { rooms: [], weather_entity: "" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass         = null;
    this._config       = {};
    this._pauseMinutes = 120;
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(h) {
    this._hass = h;
    this._updateInPlace();
  }

  getCardSize() { return 4; }

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

  _energySensor(suffix) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith(suffix)) {
        const v = states[id].state;
        return (v && v !== "unknown" && v !== "unavailable") ? v : null;
      }
    }
    return null;
  }

  _climateTemp(id) {
    const t = this._attr(id, "current_temperature");
    return t != null ? (Math.round(t * 10) / 10) + "°C" : "–";
  }

  _climateSetpoint(id) {
    const t = this._attr(id, "temperature");
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }

  _roomState(name) {
    const states = this._hass?.states ?? {};
    const key = name.toLowerCase().replace(/\s+/g, "_");
    for (const id of Object.keys(states)) {
      if (id.startsWith("sensor.") && id.endsWith("_" + key + "_state")) return states[id].state;
    }
    return "normal";
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

  async _setCtrl(state) {
    await this._hass.callService("heat_manager", "set_controller_state", { state });
  }
  async _pause() {
    await this._hass.callService("heat_manager", "pause", { duration_minutes: this._pauseMinutes });
  }
  async _resume() {
    await this._hass.callService("heat_manager", "resume", {});
  }

  // ── CSS ───────────────────────────────────────────────────────────────────

  _css() {
    return `
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

      :host {
        display: block;
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
        overflow: hidden;
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.18));
      }

      /* ── Header ── */
      .card-header {
        display: flex; align-items: center; gap: 12px;
        padding: 14px 16px 10px;
        border-bottom: 1px solid var(--div);
        position: relative; overflow: hidden;
      }
      .card-header::before {
        content: ''; position: absolute; inset: 0;
        background: radial-gradient(ellipse at top left, rgba(249,115,22,0.07) 0%, transparent 60%);
        pointer-events: none;
      }
      .header-icon {
        width: 38px; height: 38px; border-radius: 10px;
        background: linear-gradient(135deg, #f97316 0%, #eab308 100%);
        display: flex; align-items: center; justify-content: center;
        font-size: 20px; flex-shrink: 0;
        box-shadow: 0 0 14px rgba(249,115,22,0.3);
      }
      .header-text { flex: 1; }
      .header-title { font-size: 15px; font-weight: 700; line-height: 1.2; }
      .header-sub   { font-size: 11px; color: var(--sub); margin-top: 2px; font-family: 'DM Mono', monospace; }
      .ctrl-badge {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 4px 10px; border-radius: 20px; border: 1px solid;
        font-size: 11px; font-weight: 700;
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
      .section-box { border-bottom: 1px solid var(--div); }
      .section-box:last-child { border-bottom: none; }
      .section-header {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 14px;
        background: rgba(0,0,0,0.15);
        border-bottom: 1px solid var(--div);
      }
      .section-title {
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 1px; color: var(--sub); flex: 1;
      }
      .section-badge {
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 4px;
        letter-spacing: 0.5px; text-transform: uppercase;
      }
      .section-body { padding: 12px 14px; }

      /* ── Controller buttons ── */
      .ctrl-btn-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 7px; margin-bottom: 8px; }
      .ctrl-btn {
        padding: 10px 0; border-radius: 9px; border: 1px solid rgba(148,163,184,0.2);
        background: transparent; font-size: 12px; font-weight: 700;
        font-family: 'DM Sans', sans-serif; cursor: pointer; text-align: center;
        color: var(--sub); transition: transform .1s;
      }
      .ctrl-btn:active { transform: scale(0.97); }
      .ctrl-pause-row { display: flex; align-items: center; gap: 8px; }
      .ctrl-pause-label { font-size: 11px; color: var(--sub); white-space: nowrap; }
      .ctrl-pause-select {
        flex: 1; font-size: 11px; padding: 5px 8px;
        border-radius: 7px; border: 1px solid var(--div);
        background: var(--bg2); color: var(--text);
        font-family: 'DM Sans', sans-serif;
      }
      .pause-bar {
        margin-top: 8px;
        display: flex; align-items: center; justify-content: space-between;
        padding: 8px 12px;
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

      /* ── Energy ring ── */
      .energy-row { display: flex; align-items: center; gap: 14px; }
      .ring-wrap { position: relative; flex-shrink: 0; }
      .ring-center {
        position: absolute; inset: 0;
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
      }
      .ring-val  { font-weight: 700; line-height: 1; }
      .ring-unit { font-size: 9px; color: var(--sub); margin-top: 1px; }
      .energy-chips { display: flex; flex-direction: column; gap: 6px; flex: 1; }
      .energy-chip {
        display: flex; align-items: center; gap: 7px;
        background: var(--bg2); border-radius: 8px;
        padding: 6px 9px; font-size: 12px;
      }
      .energy-chip span   { color: var(--sub); flex: 1; }
      .energy-chip strong { font-weight: 700; font-family: 'DM Mono', monospace; }

      /* ── Room cards ── */
      .rooms-list { display: flex; flex-direction: column; gap: 6px; }
      .room-card {
        display: flex; align-items: center; gap: 10px;
        background: var(--bg2); border-radius: 11px;
        padding: 9px 11px; border-left: 3px solid transparent;
        position: relative; overflow: hidden;
      }
      .room-card-name { font-size: 13px; font-weight: 600; flex: 1; }
      .room-state-pill {
        font-size: 9px; font-weight: 700;
        padding: 2px 7px; border-radius: 20px;
        text-transform: uppercase; letter-spacing: .4px; flex-shrink: 0;
      }
      .room-card.state-window_open .room-state-pill,
      .room-card.state-pre_heat .room-state-pill {
        animation: badge-pulse 2s infinite;
      }
      @keyframes badge-pulse { 0%,100%{opacity:1}50%{opacity:.55} }
      .room-temps { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; flex-shrink: 0; }
      .room-temp-current  { font-size: 13px; font-weight: 700; font-family: 'DM Mono', monospace; }
      .room-temp-setpoint { font-size: 10px; color: var(--sub); }
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
    const saved     = this._energySensor("_energy_saved_today");
    const wasted    = this._energySensor("_energy_wasted_today");
    const score     = this._energySensor("_efficiency_score");
    const scoreInt  = score != null ? parseInt(score, 10) : null;

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
          const state = this._roomState(room.room_name ?? "");
          const color = _hmStateColor(state);
          const label = _hmStateLabel(state);
          const temp  = this._climateTemp(room.climate_entity ?? "");
          const setpt = this._climateSetpoint(room.climate_entity ?? "");
          return `
            <div class="room-card state-${state}"
              style="border-left-color:${color};background-image:linear-gradient(90deg,${color}0e 0%,transparent 40%);">
              <div class="room-card-name">${_hmEsc(room.room_name ?? "")}</div>
              <div class="room-state-pill" style="background:${color}22;color:${color}">${label}</div>
              <div class="room-temps">
                <div class="room-temp-current">${temp}</div>
                ${setpt ? `<div class="room-temp-setpoint">→ ${setpt}</div>` : ""}
              </div>
            </div>`;
        }).join("")
      : `<div style="color:var(--sub);font-size:12px;padding:4px 0;">Ingen rum konfigureret i kortet</div>`;

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

      <div class="section-box">
        <div class="section-header">
          <div class="section-title">Controller</div>
          <div class="section-badge" id="ctrl-state-badge"
            style="background:${ctrlColor}20;color:${ctrlColor}">${_hmCtrlLabel(ctrl)}</div>
        </div>
        <div class="section-body">
          <div class="ctrl-btn-row">
            <button id="btn-on"    class="ctrl-btn" style="${btnStyle("on")}">🔥 On</button>
            <button id="btn-pause" class="ctrl-btn" style="${btnStyle("pause")}">⏸ Pause</button>
            <button id="btn-off"   class="ctrl-btn" style="${btnStyle("off")}">❄️ Off</button>
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

      ${rooms.length ? `
      <div class="section-box">
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

      <div class="section-box">
        <div class="section-header">
          <div class="section-title">Energi i dag</div>
        </div>
        <div class="section-body">
          <div class="energy-row">
            ${_hmRingHTML(scoreInt, 76)}
            <div class="energy-chips">
              <div class="energy-chip">
                🌿 <span>Sparet</span>
                <strong id="stat-saved" style="color:var(--green)">${saved != null ? saved + " kWh" : "–"}</strong>
              </div>
              <div class="energy-chip">
                🔥 <span>Spildt</span>
                <strong id="stat-wasted" style="color:var(--amber)">${wasted != null ? wasted + " kWh" : "–"}</strong>
              </div>
              <div class="energy-chip">
                📊 <span>Score</span>
                <strong id="stat-score" style="color:${_hmEffColor(scoreInt)}">${scoreInt != null ? scoreInt + "/100" : "–"}</strong>
              </div>
            </div>
          </div>
        </div>
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
    const saved     = this._energySensor("_energy_saved_today");
    const wasted    = this._energySensor("_energy_wasted_today");
    const score     = this._energySensor("_efficiency_score");
    const scoreInt  = score != null ? parseInt(score, 10) : null;
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

    const rooms = this._config.rooms ?? [];
    rooms.forEach((room, i) => {
      const cards = root.querySelectorAll(".room-card");
      if (!cards[i]) return;
      const state = this._roomState(room.room_name ?? "");
      const color = _hmStateColor(state);
      const label = _hmStateLabel(state);
      const temp  = this._climateTemp(room.climate_entity ?? "");
      const setpt = this._climateSetpoint(room.climate_entity ?? "");
      cards[i].style.borderLeftColor = color;
      cards[i].style.backgroundImage = `linear-gradient(90deg,${color}0e 0%,transparent 40%)`;
      cards[i].className = "room-card state-" + state;
      const pill = cards[i].querySelector(".room-state-pill");
      if (pill) { pill.textContent = label; pill.style.background = color + "22"; pill.style.color = color; }
      const tc = cards[i].querySelector(".room-temp-current");
      if (tc) tc.textContent = temp;
      const ts = cards[i].querySelector(".room-temp-setpoint");
      if (ts) ts.textContent = setpt ? "→ " + setpt : "";
    });

    const sv = root.querySelector("#stat-saved");
    const wv = root.querySelector("#stat-wasted");
    const sc = root.querySelector("#stat-score");
    if (sv) sv.textContent = saved  != null ? saved  + " kWh" : "–";
    if (wv) wv.textContent = wasted != null ? wasted + " kWh" : "–";
    if (sc) { sc.textContent = scoreInt != null ? scoreInt + "/100" : "–"; sc.style.color = _hmEffColor(scoreInt); }
  }

  // ── Events ────────────────────────────────────────────────────────────────

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelector("#btn-on")?.addEventListener("click",     () => this._setCtrl("on"));
    root.querySelector("#btn-off")?.addEventListener("click",    () => this._setCtrl("off"));
    root.querySelector("#resume-btn")?.addEventListener("click", () => this._resume());
    root.querySelector("#pause-dur")?.addEventListener("change", e => {
      this._pauseMinutes = parseInt(e.target.value, 10);
    });
    root.querySelector("#btn-pause")?.addEventListener("click",  () => this._pause());
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
