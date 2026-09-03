// Heat Manager — Custom Lovelace Card
// Version: 0.4.3
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

function _hmStateLabel(s) {
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
  }

  setConfig(config) {
    this._config = config || {};
    this._updateScale();
    this._render();
  }

  set hass(h) {
    this._hass = h;
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
  }

  disconnectedCallback() {
    if (this._resizeHandler) window.removeEventListener("resize", this._resizeHandler);
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

  // v0.9.0: Group offset — number.heat_manager_group_offset (singleton, same
  // discovery pattern as _ctrl()/_season()/_pauseLeft() above).
  _offsetEntityId() {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("number.") && id.endsWith("_group_offset")) return id;
    }
    return null;
  }

  _groupOffset() {
    const id = this._offsetEntityId();
    const v = id ? parseFloat(this._hass?.states?.[id]?.state) : NaN;
    return isNaN(v) ? 0 : v;
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

      /* v0.9.0: Group offset slider */
      .ctrl-offset-row { display: flex; align-items: center; gap: 10px; margin-top: calc(8px * var(--hm-scale-h)); }
      .ctrl-offset-label { font-size: calc(11px * var(--hm-scale-h)); color: var(--sub); white-space: nowrap; }
      .ctrl-offset-slider {
        flex: 1; -webkit-appearance: none; appearance: none;
        height: 4px; border-radius: 2px;
        background: linear-gradient(to right, var(--amber) var(--pct,50%), var(--bg2) var(--pct,50%));
        outline: none; cursor: pointer;
      }
      .ctrl-offset-slider::-webkit-slider-thumb {
        -webkit-appearance: none; width: 14px; height: 14px;
        border-radius: 50%; background: #fb923c;
        border: 2px solid var(--bg); cursor: pointer;
      }
      .ctrl-offset-val {
        font-size: calc(11px * var(--hm-scale-h)); font-weight: 600; font-family: 'DM Mono', monospace;
        color: #fb923c; width: 44px; text-align: right; flex-shrink: 0;
      }

      /* v0.9.0: blocking-sources indicators */
      .blocking-row {
        display: flex; align-items: center; gap: 5px;
        padding: 0 16px calc(8px * var(--hm-scale-h));
        font-size: calc(11px * var(--hm-scale-h)); font-weight: 600; color: #fca5a5;
      }
      .room-blocking-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 1px 5px; border-radius: 5px; margin-top: 2px;
        background: rgba(239,68,68,0.12); color: #fca5a5;
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
          const state = this._roomState(room.room_name ?? "");
          const color = _hmStateColor(state);
          const label = _hmStateLabel(state);
          const temp  = this._climateTemp(room.climate_entity ?? "");
          const setpt = this._climateSetpoint(room.climate_entity ?? "");
          // v0.9.0: blocking-sources badge (controller_off/controller_pause
          // only — window/presence are already shown via the state pill)
          const extraBlocking = this._roomExtraBlocking(room.room_name ?? "", state);
          const blockingBadge = extraBlocking.length
            ? `<div class="room-blocking-badge" title="${_hmEsc(extraBlocking.map(s => _hmBlockingLabel(s)).join(", "))}">⛔ ${_hmEsc(_hmBlockingLabel(extraBlocking[0]))}${extraBlocking.length > 1 ? ` +${extraBlocking.length - 1}` : ""}</div>`
            : "";
          return `
            <div class="room-card state-${state}"
              style="border-left-color:${color};background-image:linear-gradient(90deg,${color}0e 0%,transparent 40%);">
              <div class="room-card-name">${_hmEsc(room.room_name ?? "")}</div>
              <div class="room-state-pill" style="background:${color}22;color:${color}">${label}</div>
              <div class="room-temps">
                <div class="room-temp-current">${temp}</div>
                ${setpt ? `<div class="room-temp-setpoint">→ ${setpt}</div>` : ""}
                ${blockingBadge}
              </div>
            </div>`;
        }).join("")
      : `<div style="color:var(--sub);font-size:12px;padding:4px 0;">Ingen rum konfigureret i kortet</div>`;

    const groupOffset   = this._groupOffset();
    const offsetPct     = Math.max(0, Math.min(100, (groupOffset + 5) / 10 * 100));
    const offsetStr     = (groupOffset >= 0 ? "+" : "") + groupOffset.toFixed(1) + "°C";
    const globalBlocked = this._globalBlockingSources();

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
          <div class="ctrl-offset-row">
            <span class="ctrl-offset-label">Gruppe-offset</span>
            <input type="range" class="ctrl-offset-slider" id="ctrl-offset-slider"
              min="-5" max="5" step="0.5" value="${groupOffset}" style="--pct:${offsetPct}%">
            <span class="ctrl-offset-val" id="ctrl-offset-val">${offsetStr}</span>
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

    // v0.9.0: group offset slider — synced unless the user is actively dragging it
    const groupOffset  = this._groupOffset();
    const offsetSlider = root.querySelector("#ctrl-offset-slider");
    if (offsetSlider && this.shadowRoot.activeElement !== offsetSlider) {
      offsetSlider.value = groupOffset;
      offsetSlider.style.setProperty("--pct", Math.max(0, Math.min(100, (groupOffset + 5) / 10 * 100)) + "%");
    }
    const offsetVal = root.querySelector("#ctrl-offset-val");
    if (offsetVal) offsetVal.textContent = (groupOffset >= 0 ? "+" : "") + groupOffset.toFixed(1) + "°C";

    // v0.9.0: global blocking-sources indicator
    const globalBlocked = this._globalBlockingSources();
    const blockingRow   = root.querySelector("#blocking-row");
    if (blockingRow) {
      blockingRow.style.display = globalBlocked.length ? "flex" : "none";
      blockingRow.textContent = globalBlocked.length
        ? "⛔ " + globalBlocked.map(s => _hmBlockingLabel(s)).join(", ")
        : "";
    }

    this._patchBoost();

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

      // v0.9.0: blocking-sources badge
      const extraBlocking = this._roomExtraBlocking(room.room_name ?? "", state);
      const tempsBox = cards[i].querySelector(".room-temps");
      let blk = cards[i].querySelector(".room-blocking-badge");
      if (extraBlocking.length) {
        const title = extraBlocking.map(s => _hmBlockingLabel(s)).join(", ");
        const txt   = "⛔ " + _hmBlockingLabel(extraBlocking[0]) + (extraBlocking.length > 1 ? ` +${extraBlocking.length - 1}` : "");
        if (!blk) {
          blk = document.createElement("div");
          blk.className = "room-blocking-badge";
          tempsBox?.appendChild(blk);
        }
        blk.title = title;
        blk.textContent = txt;
      } else if (blk) { blk.remove(); }
    });

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
    root.querySelector("#boost-btn")?.addEventListener("click",  () => this._boost());

    // v0.9.0: Group offset slider — live label while dragging,
    // number.set_value on release.
    const offsetSlider = root.querySelector("#ctrl-offset-slider");
    if (offsetSlider) {
      const updateOffsetLabel = () => {
        const val = parseFloat(offsetSlider.value);
        offsetSlider.style.setProperty("--pct", Math.max(0, Math.min(100, (val + 5) / 10 * 100)) + "%");
        const valEl = root.querySelector("#ctrl-offset-val");
        if (valEl) valEl.textContent = (val >= 0 ? "+" : "") + val.toFixed(1) + "°C";
      };
      offsetSlider.addEventListener("input", updateOffsetLabel);
      offsetSlider.addEventListener("change", async () => {
        const entityId = this._offsetEntityId();
        if (!entityId) { console.warn("Heat Manager: group_offset entity not found"); return; }
        const val = parseFloat(offsetSlider.value);
        try {
          await this._hass.callService("number", "set_value", { entity_id: entityId, value: val });
        } catch (e) {
          console.warn("Heat Manager: set group_offset failed:", e);
        }
      });
    }
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
    root.querySelectorAll(".room-homekit").forEach(el => {
      el.addEventListener("change", e => {
        this._rooms[+e.target.dataset.idx].homekit_climate_entity = e.target.value.trim();
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
