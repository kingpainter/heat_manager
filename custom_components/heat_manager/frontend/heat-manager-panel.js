// Heat Manager Panel
// Version: 0.3.0
//
// Design: Unified visual language with Indeklima — same font (DM Sans/DM Mono),
// same card system, same section-box pattern, same score ring, same chip/badge
// components. Palette shifted to heat semantics: amber/orange for active heating,
// teal for normal/schedule, red for waste/window-open, blue for away/pre-heat.
//
// Architecture: same blink-free guards as 0.2.x —
//   _loadInFlight, _lastCtrlState diff, setTimeout(0) render debounce,
//   _srAppendHTML for WebKit/iOS, surgical _patchController().

class HeatManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass          = null;
    this._tab           = "overview";
    this._data          = null;
    this._history       = null;
    this._errCount      = 0;
    this._interval      = null;
    this._loadInFlight  = false;
    this._renderPending = false;
    this._lastCtrlState = null;
  }

  set hass(h) {
    const wasNull = !this._hass;
    this._hass = h;
    if (wasNull) { this._load(); return; }
    if (!this._data) return;
    this._syncFromEntities();
    const newCtrl = this._data.controller_state;
    if (newCtrl !== this._lastCtrlState) {
      this._lastCtrlState = newCtrl;
      this._patchController();
      this._patchTopbarBadge();
    }
  }

  connectedCallback() {
    const root = this.shadowRoot;
    if (!root.querySelector("style")) {
      const st = document.createElement("style");
      st.textContent = this._css();
      root.appendChild(st);
    }
    if (!root.querySelector(".panel")) {
      this._srAppendHTML(`<div class="panel"><div class="loading-wrap"><div class="loading-icon">🔥</div><div class="loading-text">Indlæser Heat Manager…</div></div></div>`);
    }
    if (this._data) this._scheduleRender();
    this._interval = setInterval(() => {
      if (this._errCount > 3) { clearInterval(this._interval); return; }
      if (document.visibilityState === "visible") this._load();
    }, 30000);
  }

  disconnectedCallback() { clearInterval(this._interval); }

  _srAppendHTML(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    const root = this.shadowRoot;
    while (tmp.firstChild) root.appendChild(tmp.firstChild);
  }

  _scheduleRender() {
    if (this._renderPending) return;
    this._renderPending = true;
    setTimeout(() => { this._renderPending = false; this._render(); }, 0);
  }

  // ── Data ──────────────────────────────────────────────────────────────────

  async _load() {
    if (!this._hass || this._loadInFlight) return;
    this._loadInFlight = true;
    try {
      this._data     = await this._hass.callWS({ type: "heat_manager/get_state" });
      this._errCount = 0;
    } catch (e) {
      this._errCount++;
      this._data = this._entitiesSnapshot();
    } finally {
      this._loadInFlight = false;
    }
    if (this._tab === "history" && !this._history) await this._loadHistory();
    this._lastCtrlState = this._data?.controller_state ?? null;
    this._scheduleRender();
  }

  async _loadHistory() {
    try {
      this._history = await this._hass.callWS({ type: "heat_manager/get_history", days: 7 });
    } catch (e) { this._history = { events: [], days: [] }; }
  }

  _resolveEntityIds() {
    if (this._ctrlEntityId) return;
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("select.") && id.endsWith("_controller_state")) this._ctrlEntityId   = id;
      if (id.startsWith("select.") && id.endsWith("_season_mode"))      this._seasonEntityId = id;
      if (id.startsWith("sensor.") && id.endsWith("_pause_remaining"))  this._pauseEntityId  = id;
    }
  }

  _entitiesSnapshot() {
    this._resolveEntityIds();
    const v = id => (id ? this._hass.states?.[id]?.state : null) ?? "unknown";
    return {
      controller_state: v(this._ctrlEntityId),
      season_mode:      v(this._seasonEntityId),
      pause_remaining:  parseInt((this._pauseEntityId ? this._hass.states?.[this._pauseEntityId]?.state : null) || "0", 10),
      outdoor_temp: null, rooms: [], persons: [],
      auto_off_reason: "none", auto_off_days: 0,
      auto_off_threshold: 18, auto_off_days_required: 5,
      energy_saved_today: null, energy_wasted_today: null, efficiency_score: null,
    };
  }

  _syncFromEntities() {
    if (!this._data) return;
    this._resolveEntityIds();
    const v = id => (id ? this._hass.states?.[id]?.state : null) ?? "unknown";
    this._data.controller_state = v(this._ctrlEntityId);
    this._data.season_mode      = v(this._seasonEntityId);
    this._data.pause_remaining  = parseInt((this._pauseEntityId ? this._hass.states?.[this._pauseEntityId]?.state : null) || "0", 10);
  }

  // ── Surgical DOM patches ──────────────────────────────────────────────────

  _patchController() {
    const root      = this.shadowRoot;
    const ctrl      = this._data?.controller_state ?? "unknown";
    const pauseLeft = this._data?.pause_remaining ?? 0;

    const styles = {
      on:    { bg:"rgba(251,146,60,0.18)", border:"#f97316", color:"#fed7aa" },
      pause: { bg:"rgba(234,179,8,0.15)",  border:"#ca8a04", color:"#fef08a" },
      off:   { bg:"rgba(148,163,184,0.12)", border:"rgba(148,163,184,0.4)", color:"#94a3b8" },
    };
    const inactive = { bg:"transparent", border:"rgba(148,163,184,0.15)", color:"var(--sub)" };

    ["on","pause","off"].forEach(name => {
      const btn = root.querySelector(`#ctrl-btn-${name}`);
      if (!btn) return;
      const s = ctrl === name ? (styles[name] ?? inactive) : inactive;
      btn.style.background  = s.bg;
      btn.style.borderColor = s.border;
      btn.style.color       = s.color;
    });

    const bar = root.querySelector("#pause-bar");
    const txt = root.querySelector("#pause-bar-text");
    if (bar) {
      const show = ctrl === "pause" && pauseLeft > 0;
      bar.style.display = show ? "flex" : "none";
      if (txt && show) txt.textContent = `Pause — ${pauseLeft} min tilbage`;
    }
  }

  _patchTopbarBadge() {
    const root  = this.shadowRoot;
    const ctrl  = this._data?.controller_state ?? "unknown";
    const badge = root.querySelector("#topbar-badge");
    if (!badge) return;
    const labels = { on:"On", pause:"Pause", off:"Off" };
    const colors = {
      on:    { bg:"rgba(251,146,60,0.2)", color:"#fed7aa", border:"#f97316" },
      pause: { bg:"rgba(234,179,8,0.15)", color:"#fef08a", border:"#ca8a04" },
      off:   { bg:"rgba(148,163,184,0.1)", color:"#94a3b8", border:"rgba(148,163,184,0.3)" },
    };
    const c = colors[ctrl] ?? colors.off;
    badge.textContent       = labels[ctrl] ?? ctrl;
    badge.style.background  = c.bg;
    badge.style.color       = c.color;
    badge.style.borderColor = c.border;
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  async _setController(state) {
    try {
      await this._hass.callService("heat_manager", "set_controller_state", { state });
      if (this._data) this._data.controller_state = state;
      this._lastCtrlState = state;
      this._patchController();
      this._patchTopbarBadge();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  async _pause(minutes) {
    try {
      await this._hass.callService("heat_manager", "pause", { duration_minutes: minutes });
      if (this._data) { this._data.controller_state = "pause"; this._data.pause_remaining = minutes; }
      this._lastCtrlState = "pause";
      this._patchController();
      this._patchTopbarBadge();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  async _resume() {
    try {
      await this._hass.callService("heat_manager", "resume", {});
      if (this._data) { this._data.controller_state = "on"; this._data.pause_remaining = 0; }
      this._lastCtrlState = "on";
      this._patchController();
      this._patchTopbarBadge();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  _esc(s) { return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  _fmt(val, unit, decimals = 0) {
    if (val == null) return "–";
    const n = parseFloat(val);
    return isNaN(n) ? "–" : n.toFixed(decimals) + "\u00a0" + unit;
  }

  // State labels & colours — heat semantics
  _stateLabel(s) {
    return ({ normal:"Normal", away:"Fraværende", window_open:"Vindue åbent", pre_heat:"Forvarmning", override:"Override" })[s] ?? s ?? "–";
  }
  _stateColor(s) {
    return ({ normal:"#f97316", away:"#64748b", window_open:"#ef4444", pre_heat:"#0ea5e9", override:"#a855f7" })[s] ?? "#64748b";
  }
  _stateGradient(s) {
    return ({
      normal:      "linear-gradient(135deg,rgba(249,115,22,0.18) 0%,rgba(249,115,22,0.04) 100%)",
      away:        "linear-gradient(135deg,rgba(100,116,139,0.15) 0%,rgba(100,116,139,0.04) 100%)",
      window_open: "linear-gradient(135deg,rgba(239,68,68,0.18) 0%,rgba(239,68,68,0.04) 100%)",
      pre_heat:    "linear-gradient(135deg,rgba(14,165,233,0.15) 0%,rgba(14,165,233,0.04) 100%)",
      override:    "linear-gradient(135deg,rgba(168,85,247,0.15) 0%,rgba(168,85,247,0.04) 100%)",
    })[s] ?? "linear-gradient(135deg,rgba(100,116,139,0.1) 0%,transparent 100%)";
  }

  _reasonLabel(r) { return ({ season:"Sæson — sommer", temperature:"Ude-temp over grænse", none:"Manuel" })[r] ?? r ?? "–"; }
  _seasonTriggerLabel(season, reason) {
    if (season === "summer") return reason === "season" ? "Sommer — slået fra" : "Sommer — auto-off klar";
    if (season === "auto")   return "Auto — overvåger ude-temp";
    return reason === "season" ? "Vinter — slået fra" : "Vinter — kører normalt";
  }

  _ctrlIcon(s) { return ({ on:"🔥", pause:"⏸", off:"❄️" })[s] ?? "●"; }
  _ctrlTitle(s) { return ({ on:"Varme aktiv", pause:"Pause", off:"Slukket" })[s] ?? s; }

  _climateTemp(id) {
    const t = this._hass?.states?.[id]?.attributes?.current_temperature;
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }
  _climateSetpoint(id) {
    const t = this._hass?.states?.[id]?.attributes?.temperature;
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }

  // Format an ISO timestamp to a short Danish clock string, e.g. "kl. 14:37".
  // Returns null if ts is falsy.
  _fmtEventTime(ts) {
    if (!ts) return null;
    try {
      const d = new Date(ts);
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      return `kl. ${hh}:${mm}`;
    } catch { return null; }
  }

  // Efficiency ring — inverted from severity: 100 = good (full green ring)
  _ringColor(score) {
    if (score == null) return "#64748b";
    if (score >= 80) return "#f97316";
    if (score >= 50) return "#eab308";
    return "#ef4444";
  }

  // ── CSS ───────────────────────────────────────────────────────────────────

  _css() {
    return `
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

      :host {
        display: flex;
        flex-direction: column;
        --bg:          var(--primary-background-color,   #0f1923);
        --bg2:         var(--secondary-background-color, #1a2535);
        --bg3:         #243044;
        --text:        var(--primary-text-color,   #e2e8f0);
        --sub:         var(--secondary-text-color,  #94a3b8);
        --div:         var(--divider-color,         rgba(148,163,184,0.12));
        --amber:       #f97316;
        --amber-soft:  rgba(249,115,22,0.15);
        --amber-glow:  rgba(249,115,22,0.25);
        --yellow:      #eab308;
        --red:         #ef4444;
        --teal:        #0ea5e9;
        --teal-glow:   rgba(14,165,233,0.15);
        --green:       #10b981;
        --card-radius: 18px;
        font-family: 'DM Sans', var(--paper-font-body1_-_font-family, sans-serif);
        background: var(--bg);
        height: 100%;
        overflow: hidden;
        color: var(--text);
      }

      * { box-sizing: border-box; margin: 0; padding: 0; }

      /* ── Layout ── */
      .panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
      .panel-topbar {
        flex-shrink: 0;
        padding: 16px 24px 12px;
        background: var(--bg);
        border-bottom: 1px solid var(--div);
      }
      .panel-scroll {
        flex: 1; min-height: 0;
        overflow-y: auto; overflow-x: hidden;
        padding: 20px 24px 48px;
      }
      .panel-scroll::-webkit-scrollbar { width: 5px; }
      .panel-scroll::-webkit-scrollbar-track { background: transparent; }
      .panel-scroll::-webkit-scrollbar-thumb { background: var(--bg3); border-radius: 3px; }

      /* ── Header ── */
      .header { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
      .header-icon {
        width: 48px; height: 48px; border-radius: 14px;
        background: linear-gradient(135deg, #f97316 0%, #eab308 100%);
        display: flex; align-items: center; justify-content: center;
        font-size: 24px;
        box-shadow: 0 0 20px rgba(249,115,22,0.35);
        flex-shrink: 0;
      }
      .header-text h1 {
        font-size: 21px; font-weight: 700; letter-spacing: -0.3px;
        background: linear-gradient(90deg, #e2e8f0, #94a3b8);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      }
      .header-text .version {
        font-size: 11px; color: var(--sub); letter-spacing: 0.5px;
        font-family: 'DM Mono', monospace; margin-top: 2px;
      }
      .header-refresh {
        margin-left: auto;
        background: var(--bg2); border: 1px solid var(--div);
        color: var(--sub); padding: 7px 13px; border-radius: 10px;
        cursor: pointer; font-size: 13px; font-family: 'DM Sans', sans-serif;
        transition: all .2s;
      }
      .header-refresh:hover { color: var(--amber); border-color: var(--amber); }

      /* ── Topbar badge ── */
      .topbar-badge {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 11px; border-radius: 20px; border: 1px solid;
        font-size: 12px; font-weight: 600;
        font-family: 'DM Sans', sans-serif;
      }
      .badge-dot {
        width: 6px; height: 6px; border-radius: 50%;
        animation: pulse-dot 2s infinite;
      }
      @keyframes pulse-dot {
        0%,100% { opacity: 1; transform: scale(1); }
        50%      { opacity: 0.5; transform: scale(1.4); }
      }

      /* ── Tabs ── */
      .tabs { display: flex; gap: 2px; }
      .tab {
        flex: 1; padding: 9px 10px; border-radius: 10px;
        border: 1px solid transparent; background: transparent;
        color: var(--sub); cursor: pointer; font-size: 13px; font-weight: 500;
        font-family: 'DM Sans', sans-serif; transition: all .2s;
        text-align: center; white-space: nowrap;
      }
      .tab.active {
        background: var(--bg2); border-color: var(--div);
        color: var(--text); box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      }
      .tab:hover:not(.active) { color: var(--text); background: rgba(255,255,255,0.04); }

      /* ── Section boxes (Indeklima system) ── */
      .section-box {
        background: var(--bg2);
        border: 1px solid rgba(148,163,184,0.18);
        border-radius: 14px;
        overflow: hidden;
        margin-bottom: 12px;
      }
      .section-box-header {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 16px;
        border-bottom: 1px solid rgba(148,163,184,0.12);
        background: rgba(0,0,0,0.18);
      }
      .section-box-title {
        font-size: 11px; font-weight: 600;
        text-transform: uppercase; letter-spacing: 1px;
        color: var(--sub); flex: 1;
      }
      .section-box-badge {
        font-size: 9px; font-weight: 700;
        padding: 2px 7px; border-radius: 4px;
        letter-spacing: 0.5px; text-transform: uppercase;
      }
      .section-box-body { padding: 14px 16px; }

      /* ── Controller hero card ── */
      .ctrl-hero {
        display: flex; align-items: center; gap: 18px;
        padding: 20px; margin-bottom: 0;
        position: relative; overflow: hidden;
      }
      .ctrl-hero::before {
        content: ''; position: absolute; inset: 0;
        background: radial-gradient(ellipse at top left, rgba(249,115,22,0.08) 0%, transparent 60%);
        pointer-events: none;
      }
      .ctrl-ring-wrap { position: relative; flex-shrink: 0; }
      .ctrl-ring-svg { width: 100px; height: 100px; transform: rotate(-90deg); }
      .ctrl-ring-bg   { fill: none; stroke: var(--div); stroke-width: 10; }
      .ctrl-ring-fill {
        fill: none; stroke-width: 10; stroke-linecap: round;
        transition: stroke .4s, stroke-dashoffset .6s cubic-bezier(.4,0,.2,1);
      }
      .ctrl-ring-center {
        position: absolute; inset: 0;
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
      }
      .ctrl-ring-icon { font-size: 28px; line-height: 1; }
      .ctrl-info { flex: 1; }
      .ctrl-title { font-size: 19px; font-weight: 700; margin-bottom: 4px; }
      .ctrl-sub   { font-size: 13px; color: var(--sub); }
      .ctrl-meta-row { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
      .ctrl-meta-chip {
        display: flex; align-items: center; gap: 5px;
        background: var(--bg3); border-radius: 8px;
        padding: 5px 9px; font-size: 12px;
      }
      .ctrl-meta-chip span { color: var(--sub); }
      .ctrl-meta-chip strong { font-weight: 600; }

      /* ── Controller buttons ── */
      .ctrl-btns-wrap { padding: 0 16px 16px; }
      .ctrl-btn-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
      .ctrl-btn {
        padding: 11px 0; border-radius: 10px; border: 1px solid rgba(148,163,184,0.2);
        background: transparent; font-size: 13px; font-weight: 600;
        font-family: 'DM Sans', sans-serif; cursor: pointer; text-align: center;
        color: var(--sub); transition: transform .1s;
      }
      .ctrl-btn:active { transform: scale(0.97); }
      .ctrl-pause-row { display: flex; align-items: center; gap: 10px; }
      .ctrl-pause-label { font-size: 12px; color: var(--sub); white-space: nowrap; }
      .ctrl-pause-select {
        flex: 1; font-size: 12px; padding: 6px 10px;
        border-radius: 8px; border: 1px solid var(--div);
        background: var(--bg3); color: var(--text);
        font-family: 'DM Sans', sans-serif;
      }
      .pause-bar {
        margin: 0 16px 14px;
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 14px;
        background: rgba(234,179,8,0.12);
        border: 1px solid rgba(234,179,8,0.3);
        border-radius: 10px;
      }
      .pause-bar-text { font-size: 13px; color: #fef08a; }
      .resume-btn {
        font-size: 11px; font-weight: 600; padding: 5px 11px;
        border-radius: 7px; border: 1px solid rgba(234,179,8,0.4);
        background: transparent; color: #fef08a; cursor: pointer;
        font-family: 'DM Sans', sans-serif;
      }
      .resume-btn:hover { background: rgba(234,179,8,0.1); }

      /* ── Efficiency ring / stats (same pattern as Indeklima score) ── */
      .score-section {
        display: flex; align-items: center; gap: 20px;
        background: none; border: none; padding: 14px 16px 14px; margin-bottom: 0;
        position: relative; overflow: hidden;
      }
      .score-ring-wrap { position: relative; flex-shrink: 0; }
      .score-ring-svg { width: 96px; height: 96px; transform: rotate(-90deg); }
      .score-ring-bg   { fill: none; stroke: var(--div); stroke-width: 9; }
      .score-ring-fill {
        fill: none; stroke-width: 9; stroke-linecap: round;
        transition: stroke-dashoffset .8s cubic-bezier(.4,0,.2,1), stroke .4s;
      }
      .score-ring-center {
        position: absolute; inset: 0;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
      }
      .score-value { font-size: 22px; font-weight: 700; line-height: 1; }
      .score-unit  { font-size: 10px; color: var(--sub); margin-top: 1px; }
      .score-info  { flex: 1; }
      .score-title { font-size: 15px; font-weight: 700; margin-bottom: 2px; }
      .score-sub   { font-size: 12px; color: var(--sub); }
      .score-chips { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
      .score-chip {
        display: flex; align-items: center; gap: 5px;
        background: var(--bg3); border-radius: 7px;
        padding: 5px 9px; font-size: 12px;
      }
      .score-chip span  { color: var(--sub); }
      .score-chip strong { font-weight: 600; }
      .score-hint {
        margin-top: 8px; font-size: 11px;
        color: var(--sub); font-family: var(--mono);
        letter-spacing: 0.01em;
      }

      /* ── Quick stats grid ── */
      .qs-grid {
        display: grid; grid-template-columns: repeat(4,1fr);
        gap: 8px; padding: 0 16px 14px;
      }
      @media (max-width: 500px) { .qs-grid { grid-template-columns: repeat(2,1fr); } }
      .qs-card {
        background: var(--bg3); border-radius: 12px;
        padding: 12px 10px; text-align: center;
        position: relative; overflow: hidden;
        transition: transform .15s;
      }
      .qs-card:hover { transform: translateY(-2px); }
      .qs-card::after {
        content: ''; position: absolute; bottom: 0; left: 0; right: 0;
        height: 2px; border-radius: 0 0 12px 12px;
      }
      .qs-icon  { font-size: 18px; margin-bottom: 5px; }
      .qs-value { font-size: 16px; font-weight: 700; font-family: 'DM Mono', monospace; line-height: 1; }
      .qs-label { font-size: 9px; color: var(--sub); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }

      /* ── Room cards (grid) ── */
      .rooms-grid {
        display: grid; grid-template-columns: repeat(auto-fill, minmax(240px,1fr));
        gap: 10px;
      }
      .room-card {
        border-radius: var(--card-radius); padding: 15px;
        cursor: default; position: relative; overflow: hidden;
        border-left: 4px solid transparent;
        transition: transform .15s, box-shadow .15s;
        border: 1px solid rgba(148,163,184,0.12);
      }
      .room-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.22); }
      .room-card-header {
        display: flex; align-items: center;
        justify-content: space-between; margin-bottom: 10px;
      }
      .room-card-name { font-size: 14px; font-weight: 600; }
      .room-state-pill {
        font-size: 9px; font-weight: 700;
        padding: 3px 8px; border-radius: 20px;
        text-transform: uppercase; letter-spacing: 0.5px;
      }
      .room-temps {
        display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px;
      }
      .room-temp-box {
        background: var(--bg3); border-radius: 9px;
        padding: 7px 8px; text-align: center;
      }
      .room-temp-val { font-size: 16px; font-weight: 700; font-family: 'DM Mono', monospace; line-height: 1.1; }
      .room-temp-lbl { font-size: 9px; color: var(--sub); margin-top: 2px; text-transform: uppercase; }
      .room-state-bar { height: 3px; background: var(--bg3); border-radius: 2px; overflow: hidden; }
      .room-state-fill { height: 100%; border-radius: 2px; }

      /* Pulse for window_open / pre_heat */
      .room-card.state-window_open .room-state-pill,
      .room-card.state-pre_heat .room-state-pill {
        animation: badge-pulse 2s infinite;
      }
      @keyframes badge-pulse {
        0%,100% { opacity: 1; }
        50%      { opacity: 0.55; }
      }

      /* ── History rows ── */
      .hist-row {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 16px; border-bottom: 1px solid var(--div);
      }
      .hist-row:last-child { border-bottom: none; }
      .hist-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
      .hist-time { font-size: 11px; color: var(--sub); min-width: 44px; font-family: 'DM Mono', monospace; }
      .hist-desc { flex: 1; font-size: 13px; }
      .hist-reason { font-size: 11px; color: var(--sub); }

      /* ── Person rows ── */
      .person-row {
        display: flex; align-items: center; gap: 12px;
        padding: 10px 16px; border-bottom: 1px solid var(--div);
      }
      .person-row:last-child { border-bottom: none; }
      .avatar {
        width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
        display: flex; align-items: center; justify-content: center;
        font-size: 13px; font-weight: 600;
      }
      .av-home { background: rgba(249,115,22,0.18); color: #fed7aa; }
      .av-away { background: var(--bg3); color: var(--sub); }
      .av-none { background: var(--bg3); color: var(--sub); border: 1px dashed rgba(148,163,184,0.3); }
      .person-name { font-size: 14px; font-weight: 600; flex: 1; }
      .person-note { font-size: 12px; color: var(--sub); margin-top: 1px; }
      .person-right { text-align: right; }
      .person-state { font-size: 13px; font-weight: 600; }
      .person-since { font-size: 11px; color: var(--sub); margin-top: 1px; }

      /* ── Config rows ── */
      .cfg-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 8px 16px; border-bottom: 1px solid var(--div);
      }
      .cfg-row:last-child { border-bottom: none; }
      .cfg-k { font-size: 13px; color: var(--sub); }
      .cfg-v { font-size: 13px; font-weight: 500; font-family: 'DM Mono', monospace; }

      /* ── Energy chart ── */
      .chart-area  { padding: 12px 16px 6px; }
      .chart-bars  { display: flex; align-items: flex-end; gap: 5px; height: 72px; }
      .bar-group   { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 1px; }
      .bar-saved   { background: var(--green); border-radius: 3px 3px 0 0; width: 100%; min-height: 2px; }
      .bar-wasted  { background: var(--amber); border-radius: 3px 3px 0 0; width: 100%; min-height: 2px; }
      .bar-day     { font-size: 9px; color: var(--sub); margin-top: 3px; }
      .chart-legend { display: flex; gap: 14px; margin-top: 10px; padding: 0 0 8px; }
      .legend-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--sub); }
      .legend-dot  { width: 8px; height: 8px; border-radius: 2px; }

      /* ── Auto-off status chips ── */
      .autooff-grid {
        display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
        padding: 14px 16px;
      }
      .aocard {
        background: var(--bg3); border-radius: 10px; padding: 12px 13px;
      }
      .aocard-lbl { font-size: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px; }
      .aocard-val { font-size: 13px; font-weight: 600; }

      /* ── Loading / error ── */
      .loading-wrap {
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
        min-height: 280px; gap: 14px;
      }
      .loading-icon { font-size: 44px; animation: float 3s ease-in-out infinite; }
      @keyframes float {
        0%,100% { transform: translateY(0); }
        50%      { transform: translateY(-10px); }
      }
      .loading-text { color: var(--sub); font-size: 14px; }

      /* ── Skeleton ── */
      .skel {
        background: linear-gradient(90deg, var(--bg2) 25%, var(--bg3) 50%, var(--bg2) 75%);
        background-size: 200% 100%; animation: skel-shimmer 1.4s infinite; border-radius: 8px;
      }
      @keyframes skel-shimmer {
        0%   { background-position: 200% 0; }
        100% { background-position: -200% 0; }
      }

      .empty {
        padding: 22px 16px; text-align: center;
        color: var(--sub); font-size: 13px;
      }
    `;
  }

  // ── HTML components ───────────────────────────────────────────────────────

  _topbarHTML() {
    const d      = this._data;
    const ctrl   = d?.controller_state ?? "unknown";
    const season = ({ winter:"Vinter", summer:"Sommer", auto:"Auto" })[d?.season_mode] ?? "Auto";
    const otemp  = d?.outdoor_temp != null ? `${Math.round(d.outdoor_temp)}°C · ` : "";
    const labels = { on:"On", pause:"Pause", off:"Off" };
    const bColors = {
      on:    { bg:"rgba(249,115,22,0.2)",  color:"#fed7aa", border:"#f97316" },
      pause: { bg:"rgba(234,179,8,0.15)",  color:"#fef08a", border:"#ca8a04" },
      off:   { bg:"rgba(148,163,184,0.1)", color:"#94a3b8", border:"rgba(148,163,184,0.3)" },
    };
    const bc = bColors[ctrl] ?? bColors.off;

    return `
      <div class="header">
        <div class="header-icon">🔥</div>
        <div class="header-text">
          <h1>Heat Manager</h1>
          <div class="version">${otemp}${season}</div>
        </div>
        <div id="topbar-badge" class="topbar-badge"
          style="background:${bc.bg};color:${bc.color};border-color:${bc.border}">
          <div class="badge-dot" style="background:${bc.color}"></div>
          ${labels[ctrl] ?? ctrl}
        </div>
        <button class="header-refresh" data-action="refresh">↻ Opdater</button>
      </div>
      <div class="tabs">${[
        { id:"overview", label:"Oversigt"  },
        { id:"rooms",    label:"Rum"       },
        { id:"history",  label:"Historik"  },
        { id:"config",   label:"Konfiguration" },
      ].map(t => `<button class="tab${this._tab===t.id?" active":""}" data-tab="${t.id}">${t.label}</button>`).join("")}</div>`;
  }

  _controllerSectionHTML() {
    const ctrl      = this._data?.controller_state ?? "unknown";
    const season    = this._data?.season_mode ?? "auto";
    const otemp     = this._data?.outdoor_temp;
    const pauseLeft = this._data?.pause_remaining ?? 0;
    const showPause = ctrl === "pause" && pauseLeft > 0;

    // Ring: fully lit = ON (amber), half = PAUSE (yellow), empty = OFF (grey)
    const r          = 38;
    const circ       = 2 * Math.PI * r;
    const fill       = ctrl === "on" ? circ : ctrl === "pause" ? circ * 0.5 : 0;
    const dashOffset = circ - fill;
    const ringColor  = ctrl === "on" ? "#f97316" : ctrl === "pause" ? "#eab308" : "#475569";

    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Controller</div>
          <div class="section-box-badge" style="background:${ringColor}22;color:${ringColor}">
            ${this._ctrlTitle(ctrl)}
          </div>
        </div>

        <div class="ctrl-hero">
          <div class="ctrl-ring-wrap">
            <svg class="ctrl-ring-svg" viewBox="0 0 100 100">
              <circle class="ctrl-ring-bg"   cx="50" cy="50" r="${r}" />
              <circle class="ctrl-ring-fill" cx="50" cy="50" r="${r}"
                stroke="${ringColor}"
                stroke-dasharray="${circ}"
                stroke-dashoffset="${dashOffset}" />
            </svg>
            <div class="ctrl-ring-center">
              <div class="ctrl-ring-icon">${this._ctrlIcon(ctrl)}</div>
            </div>
          </div>
          <div class="ctrl-info">
            <div class="ctrl-title" style="color:${ringColor}">${this._ctrlTitle(ctrl)}</div>
            <div class="ctrl-sub">${(this._data?.rooms ?? []).length} rum konfigureret</div>
            <div class="ctrl-meta-row">
              <div class="ctrl-meta-chip">
                🌡️ <span>Ude</span>
                <strong>${otemp != null ? Math.round(otemp) + "°C" : "–"}</strong>
              </div>
              <div class="ctrl-meta-chip">
                🍂 <span>Sæson</span>
                <strong>${({ winter:"Vinter", summer:"Sommer", auto:"Auto" })[season] ?? season}</strong>
              </div>
            </div>
          </div>
        </div>

        <div class="ctrl-btns-wrap">
          <div class="ctrl-btn-row">
            <button id="ctrl-btn-on"    class="ctrl-btn" data-action="on">🔥 On</button>
            <button id="ctrl-btn-pause" class="ctrl-btn" data-action="pause">⏸ Pause</button>
            <button id="ctrl-btn-off"   class="ctrl-btn" data-action="off">❄️ Off</button>
          </div>
          <div class="ctrl-pause-row">
            <span class="ctrl-pause-label">Pause varighed</span>
            <select class="ctrl-pause-select" id="pause-dur">
              <option value="30">30 min</option>
              <option value="60">1 time</option>
              <option value="120" selected>2 timer</option>
              <option value="240">4 timer</option>
              <option value="480">Til i morgen</option>
            </select>
          </div>
        </div>

        <div id="pause-bar" class="pause-bar" style="display:${showPause?"flex":"none"}">
          <span id="pause-bar-text" class="pause-bar-text">⏸ Pause — ${pauseLeft} min tilbage</span>
          <button class="resume-btn" data-action="resume">Genoptag nu</button>
        </div>
      </div>`;
  }

  _energySectionHTML() {
    const d      = this._data;
    const score  = d?.efficiency_score;
    const saved  = d?.energy_saved_today;
    const wasted = d?.energy_wasted_today;
    const color  = this._ringColor(score);

    const r      = 36;
    const circ   = 2 * Math.PI * r;
    const pct    = score != null ? Math.min(score, 100) / 100 : 0;
    const dash   = pct * circ;
    const offset = circ - dash;

    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Energi i dag</div>
        </div>
        <div class="score-section">
          <div class="score-ring-wrap">
            <svg class="score-ring-svg" viewBox="0 0 96 96">
              <circle class="score-ring-bg"   cx="48" cy="48" r="${r}" />
              <circle class="score-ring-fill" cx="48" cy="48" r="${r}"
                stroke="${color}"
                stroke-dasharray="${dash} ${offset}"
                stroke-dashoffset="0" />
            </svg>
            <div class="score-ring-center">
              <div class="score-value" style="color:${color}">${score != null ? score : "–"}</div>
              <div class="score-unit">score</div>
            </div>
          </div>
          <div class="score-info">
            <div class="score-title">Effektivitet</div>
            <div class="score-sub">Daglig score nulstilles ved midnat</div>
            <div class="score-chips">
              <div class="score-chip" title="${this._fmtEventTime(d?.last_saved_time) ? 'Sidst sparet ' + this._fmtEventTime(d.last_saved_time) : 'Ingen besparelse registreret i dag'}">
                🌿 <span>Sparet</span>
                <strong style="color:var(--green)">${saved != null ? saved.toFixed(2) + " kWh" : "–"}</strong>
              </div>
              <div class="score-chip" title="${this._fmtEventTime(d?.last_waste_time) ? 'Sidst spildt ' + this._fmtEventTime(d.last_waste_time) : 'Intet spild registreret i dag'}">
                🔥 <span>Spildt</span>
                <strong style="color:var(--amber)">${wasted != null ? wasted.toFixed(2) + " kWh" : "–"}</strong>
              </div>
            </div>
            <div class="score-hint">${
              (() => {
                const wt = this._fmtEventTime(d?.last_waste_time);
                const st = this._fmtEventTime(d?.last_saved_time);
                if (wt && st) return `Sidst spildt ${wt} · Sidst sparet ${st}`;
                if (wt)      return `Sidst spildt ${wt} · Ingen besparelse i dag`;
                if (st)      return `Ingen spild i dag · Sidst sparet ${st}`;
                return "Ingen aktivitet registreret i dag";
              })()
            }</div>
          </div>
        </div>
      </div>`;
  }

  _roomsGridHTML(rooms) {
    if (!rooms?.length) return `<div class="empty">Ingen rum konfigureret</div>`;
    return `<div class="rooms-grid">${rooms.map(room => {
      const state   = room.state ?? "normal";
      const color   = this._stateColor(state);
      const grad    = this._stateGradient(state);
      const label   = this._stateLabel(state);
      const temp    = room.climate_entity ? this._climateTemp(room.climate_entity) : null;
      const setpt   = room.climate_entity ? this._climateSetpoint(room.climate_entity) : null;
      const tempStr = temp ?? (room.current_temp != null ? Math.round(room.current_temp * 10) / 10 + "°C" : "–");
      return `
        <div class="room-card state-${state}" style="background:${grad};border-left-color:${color}">
          <div class="room-card-header">
            <div class="room-card-name">${this._esc(room.name)}</div>
            <div class="room-state-pill" style="background:${color}22;color:${color}">${label}</div>
          </div>
          <div class="room-temps">
            <div class="room-temp-box">
              <div class="room-temp-val">${tempStr}</div>
              <div class="room-temp-lbl">Aktuelt</div>
            </div>
            <div class="room-temp-box">
              <div class="room-temp-val">${setpt ?? "–"}</div>
              <div class="room-temp-lbl">Sætpunkt</div>
            </div>
          </div>
          <div class="room-state-bar">
            <div class="room-state-fill" style="width:${state === "normal" ? "100" : state === "away" ? "20" : state === "window_open" ? "50" : state === "pre_heat" ? "75" : "40"}%;background:${color}"></div>
          </div>
        </div>`;
    }).join("")}</div>`;
  }

  _personsHTML() {
    const persons = this._data?.persons ?? [];
    if (!persons.length) return `<div class="empty">Ingen personer konfigureret</div>`;
    return persons.map(p => {
      const isHome  = p.state === "home";
      const noTrack = p.tracking === false;
      const initials = (p.name ?? "?").substring(0,2).toUpperCase();
      const avCls    = noTrack ? "av-none" : isHome ? "av-home" : "av-away";
      const stColor  = noTrack ? "var(--sub)" : isHome ? "#fed7aa" : "var(--sub)";
      const stTxt    = noTrack ? "Følger huset" : isHome ? "Hjemme" : "Ikke hjemme";
      return `
        <div class="person-row">
          <div class="avatar ${avCls}">${initials}</div>
          <div>
            <div class="person-name">${this._esc(p.name ?? "")}</div>
            ${noTrack ? `<div class="person-note">Ingen tracking</div>` : ""}
          </div>
          <div class="person-right">
            <div class="person-state" style="color:${stColor}">${stTxt}</div>
            ${p.since ? `<div class="person-since">siden ${this._esc(p.since)}</div>` : ""}
          </div>
        </div>`;
    }).join("");
  }

  _autoOffSectionHTML() {
    const d      = this._data;
    const reason = d?.auto_off_reason ?? "none";
    const isOff  = d?.controller_state === "off";
    const season = d?.season_mode ?? "auto";
    const otemp  = d?.outdoor_temp != null ? Math.round(d.outdoor_temp) + "°C" : "–";
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Auto-off status</div>
          <div class="section-box-badge" style="background:${isOff?"rgba(239,68,68,0.15)":"rgba(249,115,22,0.15)"};color:${isOff?"#ef4444":"#f97316"}">
            ${isOff ? "Slukket" : "Aktiv"}
          </div>
        </div>
        <div class="autooff-grid">
          <div class="aocard">
            <div class="aocard-lbl">Sæson trigger</div>
            <div class="aocard-val">${this._seasonTriggerLabel(season, reason)}</div>
          </div>
          <div class="aocard">
            <div class="aocard-lbl">Udetemperatur</div>
            <div class="aocard-val">${otemp} / ${d?.auto_off_threshold ?? 18}°C grænse</div>
          </div>
          <div class="aocard">
            <div class="aocard-lbl">Dage over grænse</div>
            <div class="aocard-val">${d?.auto_off_days ?? 0} / ${d?.auto_off_days_required ?? 5}</div>
          </div>
          <div class="aocard">
            <div class="aocard-lbl">Årsag til sluk</div>
            <div class="aocard-val">${isOff ? this._reasonLabel(reason) : "–"}</div>
          </div>
        </div>
      </div>`;
  }

  _energyChartHTML() {
    const days = this._history?.days ?? this._fakeDays();
    const max  = Math.max(...days.map(d => (d.saved ?? 0) + (d.wasted ?? 0)), 0.01);
    const bars = days.map(d => {
      const sh = Math.round(((d.saved  ?? 0) / max) * 68);
      const wh = Math.round(((d.wasted ?? 0) / max) * 68);
      return `<div class="bar-group">
        <div class="bar-saved"  style="height:${sh}px"></div>
        <div class="bar-wasted" style="height:${wh}px"></div>
        <div class="bar-day">${this._esc(d.label ?? "")}</div>
      </div>`;
    }).join("");
    return `
      <div class="chart-area">
        <div class="chart-bars">${bars}</div>
        <div class="chart-legend">
          <div class="legend-item"><div class="legend-dot" style="background:var(--green)"></div>Sparet</div>
          <div class="legend-item"><div class="legend-dot" style="background:var(--amber)"></div>Spildt</div>
        </div>
      </div>`;
  }

  _fakeDays() {
    return ["man","tir","ons","tor","fre","lør","søn"].map(l => ({ label:l, saved:0, wasted:0 }));
  }

  _historyRowsHTML() {
    const events = this._history?.events ?? [];
    if (!events.length) return `<div class="empty">Ingen hændelser endnu</div>`;
    return events.slice(0, 25).map(e => `
      <div class="hist-row">
        <div class="hist-dot" style="background:${this._stateColor(e.type ?? "normal")}"></div>
        <div class="hist-time">${this._esc(e.time ?? "")}</div>
        <div class="hist-desc">${this._esc(e.description ?? "")}</div>
        <div class="hist-reason">${this._esc(e.reason ?? "")}</div>
      </div>`).join("");
  }

  // ── Tab builders ──────────────────────────────────────────────────────────

  _overviewHTML() {
    const rooms  = this._data?.rooms ?? [];
    const active = rooms.filter(r => r.state === "normal").length;
    const away   = rooms.filter(r => r.state === "away").length;
    const winOpen = rooms.filter(r => r.state === "window_open").length;
    return `
      ${this._controllerSectionHTML()}
      ${this._energySectionHTML()}

      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Rum</div>
        </div>
        <div class="qs-grid">
          <div class="qs-card" style="--c:var(--amber)">
            <div class="qs-card" style="position:absolute;inset:0;border-radius:12px;background:linear-gradient(135deg,rgba(249,115,22,0.08) 0%,transparent 100%);pointer-events:none"></div>
            <div class="qs-icon">🔥</div>
            <div class="qs-value" style="color:var(--amber)">${active}</div>
            <div class="qs-label">Aktiv</div>
          </div>
          <div class="qs-card">
            <div class="qs-icon">🏃</div>
            <div class="qs-value" style="color:var(--sub)">${away}</div>
            <div class="qs-label">Fraværende</div>
          </div>
          <div class="qs-card">
            <div class="qs-icon">🪟</div>
            <div class="qs-value" style="color:${winOpen > 0 ? "var(--red)" : "var(--sub)"}">${winOpen}</div>
            <div class="qs-label">Vindue åbent</div>
          </div>
          <div class="qs-card">
            <div class="qs-icon">❄️</div>
            <div class="qs-value" style="color:var(--teal)">${rooms.filter(r => r.state === "pre_heat").length}</div>
            <div class="qs-label">Forvarmning</div>
          </div>
        </div>
        <div style="padding: 0 16px 14px;">
          ${this._roomsGridHTML(rooms)}
        </div>
      </div>

      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Tilstedeværelse</div>
        </div>
        ${this._personsHTML()}
      </div>

      ${this._autoOffSectionHTML()}`;
  }

  _roomsTabHTML() {
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Alle rum</div>
          <div class="section-box-badge" style="background:rgba(249,115,22,0.15);color:var(--amber)">
            ${(this._data?.rooms ?? []).length} rum
          </div>
        </div>
        <div style="padding:14px 16px;">
          ${this._roomsGridHTML(this._data?.rooms ?? [])}
        </div>
      </div>
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Energi — denne uge</div>
        </div>
        ${this._energyChartHTML()}
      </div>`;
  }

  _historyTabHTML() {
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Hændelseslog</div>
          <div class="section-box-badge" style="background:rgba(14,165,233,0.12);color:var(--teal)">
            Seneste 7 dage
          </div>
        </div>
        ${this._historyRowsHTML()}
      </div>`;
  }

  _configTabHTML() {
    const d   = this._data?.config ?? {};
    const cfg = [
      ["Weather entity",     d.weather_entity           ?? "–"],
      ["Outdoor temp sensor",d.outdoor_temp_sensor      ?? "–"],
      ["Grace dag",          d.grace_day_min   != null  ? d.grace_day_min   + " min" : "–"],
      ["Grace nat",          d.grace_night_min != null  ? d.grace_night_min + " min" : "–"],
      ["Away temp mildt",    d.away_temp_mild  != null  ? d.away_temp_mild  + "°C"   : "–"],
      ["Away temp koldt",    d.away_temp_cold  != null  ? d.away_temp_cold  + "°C"   : "–"],
      ["Auto-off grænse",    d.auto_off_temp_threshold != null ? d.auto_off_temp_threshold + "°C" : "–"],
      ["Auto-off dage",      d.auto_off_temp_days != null ? d.auto_off_temp_days + " dage" : "–"],
      ["Alarm panel",        d.alarm_panel     ?? "–"],
      ["Notify service",     d.notify_service  ?? "–"],
    ];
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Global konfiguration</div>
        </div>
        ${cfg.map(([k,v]) =>
          `<div class="cfg-row"><span class="cfg-k">${k}</span><span class="cfg-v">${this._esc(v)}</span></div>`
        ).join("")}
      </div>
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Rum & klimaentiteter</div>
        </div>
        ${(this._data?.rooms ?? []).map(r =>
          `<div class="cfg-row">
            <span class="cfg-k">${this._esc(r.name)}</span>
            <span class="cfg-v" style="color:${this._stateColor(r.state ?? "normal")}">${this._esc(r.climate_entity ?? "–")}</span>
          </div>`
        ).join("") || `<div class="empty">Ingen rum</div>`}
      </div>`;
  }

  // ── Main render ───────────────────────────────────────────────────────────

  _render() {
    const content = ({
      overview: () => this._overviewHTML(),
      rooms:    () => this._roomsTabHTML(),
      history:  () => this._historyTabHTML(),
      config:   () => this._configTabHTML(),
    })[this._tab]?.() ?? "";

    const root = this.shadowRoot;
    if (!root.querySelector("style")) {
      const st = document.createElement("style");
      st.textContent = this._css();
      root.appendChild(st);
    }

    const html = `
      <div class="panel">
        <div class="panel-topbar">${this._topbarHTML()}</div>
        <div class="panel-scroll"><div>${content}</div></div>
      </div>`;

    const existing = root.querySelector(".panel");
    if (existing) {
      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      existing.replaceWith(tmp.firstElementChild);
    } else {
      this._srAppendHTML(html);
    }

    this._patchController();
    this._attachEvents();
  }

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
      this._tab = btn.dataset.tab;
      if (this._tab === "history" && !this._history) this._loadHistory().then(() => this._scheduleRender());
      else this._scheduleRender();
    }));
    root.querySelector("[data-action='refresh']")?.addEventListener("click", () => this._load());
    root.querySelector("[data-action='on']"    )?.addEventListener("click", () => this._setController("on"));
    root.querySelector("[data-action='off']"   )?.addEventListener("click", () => this._setController("off"));
    root.querySelector("[data-action='resume']")?.addEventListener("click", () => this._resume());
    root.querySelector("[data-action='pause']" )?.addEventListener("click", () => {
      const min = parseInt(root.querySelector("#pause-dur")?.value ?? "120", 10);
      this._pause(min);
    });
  }
}

if (!customElements.get("heat-manager-panel")) {
  customElements.define("heat-manager-panel", HeatManagerPanel);
}
