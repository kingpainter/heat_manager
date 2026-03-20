// Heat Manager Panel
// Version: 0.2.0
// Fix: controller box blink removed — _patchController() uses surgical
//      style/textContent updates instead of outerHTML replacement.
//      set hass(h) never touches the DOM directly.

class HeatManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass     = null;
    this._tab      = "overview";
    this._data     = null;
    this._history  = null;
    this._errCount = 0;
    this._interval = null;
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) this._load();
    else {
      // Update data model from live entities — no DOM work here
      this._syncFromEntities();
      // Patch only the specific nodes that can change on every HA tick
      this._patchController();
      this._patchTopbarBadge();
    }
  }

  connectedCallback() {
    this._render();
    this._interval = setInterval(() => {
      if (this._errCount > 3) { clearInterval(this._interval); return; }
      if (document.visibilityState === "visible") this._load();
    }, 30000);
  }

  disconnectedCallback() { clearInterval(this._interval); }

  // ── Data ──────────────────────────────────────────────────────────────────

  async _load() {
    if (!this._hass) return;
    try {
      this._data     = await this._hass.callWS({ type: "heat_manager/get_state" });
      this._errCount = 0;
    } catch (e) {
      this._errCount++;
      this._data = this._entitiesSnapshot();
    }
    if (this._tab === "history" && !this._history) await this._loadHistory();
    this._render();
  }

  async _loadHistory() {
    try {
      this._history = await this._hass.callWS({ type: "heat_manager/get_history", days: 7 });
    } catch (e) { this._history = { events: [], days: [] }; }
  }

  _entitiesSnapshot() {
    const v = id => this._hass.states?.[id]?.state ?? "unknown";
    return {
      controller_state: v("select.heat_manager_controller_state"),
      season_mode:      v("select.heat_manager_season_mode"),
      pause_remaining:  parseInt(v("sensor.heat_manager_pause_remaining") || "0", 10),
      outdoor_temp:     null,
      rooms: [], persons: [],
      auto_off_reason: "none", auto_off_days: 0,
      auto_off_threshold: 18, auto_off_days_required: 5,
    };
  }

  // Update model only — called on every hass update, zero DOM work
  _syncFromEntities() {
    if (!this._data) return;
    const v = id => this._hass.states?.[id]?.state ?? "unknown";
    this._data.controller_state = v("select.heat_manager_controller_state");
    this._data.season_mode      = v("select.heat_manager_season_mode");
    this._data.pause_remaining  = parseInt(v("sensor.heat_manager_pause_remaining") || "0", 10);
  }

  // ── Surgical DOM patches — no innerHTML, no outerHTML ─────────────────────

  _patchController() {
    const root = this.shadowRoot;
    const ctrl = this._data?.controller_state ?? "unknown";
    const pauseLeft = this._data?.pause_remaining ?? 0;

    const styles = {
      on:    { bg:"#EAF3DE", border:"#3B6D11",                  color:"#27500A" },
      pause: { bg:"#FAEEDA", border:"#854F0B",                  color:"#633806" },
      off:   { bg:"var(--secondary-background-color)",
               border:"var(--secondary-text-color)",
               color:"var(--secondary-text-color)" },
    };
    const inactive = { bg:"transparent", border:"var(--divider-color)", color:"var(--primary-text-color)" };

    ["on","pause","off"].forEach(name => {
      const btn = root.querySelector(`#ctrl-btn-${name}`);
      if (!btn) return;
      const s = ctrl === name ? (styles[name] ?? inactive) : inactive;
      btn.style.background   = s.bg;
      btn.style.borderColor  = s.border;
      btn.style.color        = s.color;
    });

    // Pause bar — show/hide + update text without DOM creation
    const bar  = root.querySelector("#pause-bar");
    const txt  = root.querySelector("#pause-bar-text");
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
    badge.textContent   = labels[ctrl] ?? ctrl;
    badge.style.background  = this._ctrlBg(ctrl);
    badge.style.color        = this._ctrlColor(ctrl);
    badge.style.borderColor  = this._ctrlBorder(ctrl);
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  async _setController(state) {
    try {
      await this._hass.callService("heat_manager", "set_controller_state", { state });
      if (this._data) this._data.controller_state = state;
      this._patchController();
      this._patchTopbarBadge();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  async _pause(minutes) {
    try {
      await this._hass.callService("heat_manager", "pause", { duration_minutes: minutes });
      if (this._data) { this._data.controller_state = "pause"; this._data.pause_remaining = minutes; }
      this._patchController();
      this._patchTopbarBadge();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  async _resume() {
    try {
      await this._hass.callService("heat_manager", "resume", {});
      if (this._data) { this._data.controller_state = "on"; this._data.pause_remaining = 0; }
      this._patchController();
      this._patchTopbarBadge();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  _esc(s) { return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  _stateLabel(s) { return ({normal:"Schedule",away:"Away",window_open:"Vindue åbent",pre_heat:"Forvarmning",override:"Override"})[s] ?? s ?? "—"; }
  _dotColor(s)   { return ({normal:"#639922",away:"#888780",window_open:"#BA7517",pre_heat:"#185FA5",override:"#993556"})[s] ?? "#888780"; }
  _ctrlColor(s)  { return ({on:"#27500A",pause:"#633806",off:"var(--secondary-text-color)"})[s] ?? "var(--secondary-text-color)"; }
  _ctrlBg(s)     { return ({on:"#EAF3DE",pause:"#FAEEDA",off:"var(--secondary-background-color)"})[s] ?? "var(--secondary-background-color)"; }
  _ctrlBorder(s) { return ({on:"#3B6D11",pause:"#854F0B",off:"var(--secondary-text-color)"})[s] ?? "var(--divider-color)"; }
  _reasonLabel(r){ return ({season:"Sæson — sommer",temperature:"Udetemperatur over grænse",none:"Manuel"})[r] ?? r ?? "—"; }
  _fmtTemp(t)    { return t != null ? (Math.round(t * 10) / 10) + "°C" : "—"; }

  _climateTemp(id) {
    const t = this._hass?.states?.[id]?.attributes?.current_temperature;
    return t != null ? (Math.round(t * 10) / 10) + "°C" : "—";
  }
  _climateSetpoint(id) {
    const t = this._hass?.states?.[id]?.attributes?.temperature;
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }

  // ── CSS ───────────────────────────────────────────────────────────────────

  _css() { return `
    :host { display:block; height:100%; overflow-y:auto; background:var(--primary-background-color); }
    * { box-sizing:border-box; margin:0; padding:0; }
    .panel { display:flex; flex-direction:column; min-height:100%; }
    .topbar {
      display:flex; align-items:center; justify-content:space-between;
      padding:14px 20px 12px; border-bottom:1px solid var(--divider-color);
      background:var(--card-background-color); position:sticky; top:0; z-index:10;
    }
    .topbar-left { display:flex; align-items:center; gap:12px; }
    .topbar-title { font-size:17px; font-weight:500; color:var(--primary-text-color); }
    .topbar-sub { font-size:12px; color:var(--secondary-text-color); margin-top:2px; }
    .ctrl-badge { font-size:12px; font-weight:500; padding:4px 10px; border-radius:20px; border:1px solid; }
    .refresh-btn { background:transparent; border:none; cursor:pointer; padding:6px; color:var(--secondary-text-color); border-radius:8px; }
    .refresh-btn svg { width:18px; height:18px; fill:currentColor; display:block; }
    .refresh-btn:hover { background:var(--secondary-background-color); }
    .tabs {
      display:flex; border-bottom:1px solid var(--divider-color);
      background:var(--card-background-color); overflow-x:auto;
      position:sticky; top:57px; z-index:9;
    }
    .tab {
      flex:1; padding:11px 8px; background:transparent; border:none;
      border-bottom:2px solid transparent; cursor:pointer; font-size:13px;
      color:var(--secondary-text-color); white-space:nowrap; transition:color .15s;
    }
    .tab.active { color:var(--primary-color,#039be5); border-bottom-color:var(--primary-color,#039be5); }
    .tab:hover:not(.active) { color:var(--primary-text-color); background:var(--secondary-background-color); }
    .content { padding:16px; display:flex; flex-direction:column; gap:12px; flex:1; }
    .card { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:12px; overflow:hidden; }
    .card-hdr { display:flex; justify-content:space-between; align-items:center; padding:12px 16px; border-bottom:1px solid var(--divider-color); }
    .card-title { font-size:14px; font-weight:500; color:var(--primary-text-color); }
    .card-sub { font-size:12px; color:var(--secondary-text-color); }
    .section-label { font-size:11px; font-weight:500; text-transform:uppercase; letter-spacing:.06em; color:var(--secondary-text-color); padding:10px 16px 6px; }
    .btn-row { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; padding:12px 16px; }
    .ctrl-btn {
      padding:10px 0; border-radius:8px; border:1px solid var(--divider-color);
      background:transparent; font-size:13px; font-weight:500;
      cursor:pointer; text-align:center; color:var(--primary-text-color);
      transition:background .12s, border-color .12s, color .12s;
    }
    .ctrl-btn:active { opacity:.75; }
    .pause-row { display:flex; align-items:center; gap:8px; padding:0 16px 12px; }
    .pause-label { font-size:12px; color:var(--secondary-text-color); white-space:nowrap; }
    .pause-select { flex:1; font-size:12px; padding:5px 8px; border-radius:7px; border:1px solid var(--divider-color); background:var(--primary-background-color); color:var(--primary-text-color); }
    .pause-bar { align-items:center; justify-content:space-between; padding:9px 16px; background:#FAEEDA; border-top:1px solid #EF9F27; }
    .pause-bar-text { font-size:12px; color:#633806; }
    .resume-btn { font-size:11px; font-weight:500; padding:4px 10px; border-radius:6px; border:1px solid #854F0B; background:transparent; color:#633806; cursor:pointer; }
    .room-row { display:flex; align-items:flex-start; padding:10px 16px; gap:12px; border-bottom:1px solid var(--divider-color); }
    .room-row:last-child { border-bottom:none; }
    .dot { width:9px; height:9px; border-radius:50%; flex-shrink:0; margin-top:4px; }
    .room-main { flex:1; }
    .room-name { font-size:14px; color:var(--primary-text-color); font-weight:500; }
    .room-why { font-size:12px; color:var(--secondary-text-color); margin-top:2px; }
    .room-right { text-align:right; }
    .room-state { font-size:12px; color:var(--secondary-text-color); }
    .room-temp { font-size:14px; font-weight:500; color:var(--primary-text-color); }
    .room-setpoint { font-size:11px; color:var(--secondary-text-color); }
    .stats-grid { display:grid; grid-template-columns:repeat(4,1fr); }
    .stat { padding:10px 16px; border-right:1px solid var(--divider-color); }
    .stat:last-child { border-right:none; }
    .stat-label { font-size:11px; color:var(--secondary-text-color); margin-bottom:4px; }
    .stat-val { font-size:17px; font-weight:500; color:var(--primary-text-color); }
    .stat-val.warn { color:#BA7517; }
    .metric-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:12px 16px; }
    .metric-box { background:var(--secondary-background-color); border-radius:8px; padding:10px 12px; }
    .metric-lbl { font-size:11px; color:var(--secondary-text-color); margin-bottom:4px; }
    .metric-val { font-size:14px; font-weight:500; color:var(--primary-text-color); }
    .chart-area { padding:12px 16px; }
    .chart-bars { display:flex; align-items:flex-end; gap:5px; height:80px; }
    .bar-group { flex:1; display:flex; flex-direction:column; align-items:center; gap:2px; }
    .bar-saved { background:#97C459; border-radius:3px 3px 0 0; width:100%; min-height:2px; }
    .bar-wasted { background:#EF9F27; border-radius:3px 3px 0 0; width:100%; min-height:2px; }
    .bar-day { font-size:10px; color:var(--secondary-text-color); margin-top:4px; }
    .chart-legend { display:flex; gap:14px; margin-top:10px; }
    .legend-item { display:flex; align-items:center; gap:5px; font-size:11px; color:var(--secondary-text-color); }
    .legend-dot { width:8px; height:8px; border-radius:2px; }
    .hist-row { display:flex; align-items:center; gap:12px; padding:8px 16px; border-bottom:1px solid var(--divider-color); }
    .hist-row:last-child { border-bottom:none; }
    .hist-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; }
    .hist-time { font-size:11px; color:var(--secondary-text-color); min-width:52px; }
    .hist-desc { flex:1; font-size:13px; color:var(--primary-text-color); }
    .hist-reason { font-size:11px; color:var(--secondary-text-color); }
    .person-row { display:flex; align-items:center; padding:10px 16px; gap:12px; border-bottom:1px solid var(--divider-color); }
    .person-row:last-child { border-bottom:none; }
    .avatar { width:32px; height:32px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:500; }
    .av-home { background:#EAF3DE; color:#27500A; }
    .av-away { background:var(--secondary-background-color); color:var(--secondary-text-color); }
    .av-none { background:var(--secondary-background-color); color:var(--secondary-text-color); border:1px dashed var(--divider-color); }
    .person-name { flex:1; font-size:14px; color:var(--primary-text-color); font-weight:500; }
    .person-note { font-size:12px; color:var(--secondary-text-color); margin-top:1px; }
    .person-right { text-align:right; }
    .person-state { font-size:13px; font-weight:500; }
    .person-since { font-size:11px; color:var(--secondary-text-color); }
    .cfg-row { display:flex; justify-content:space-between; align-items:center; padding:7px 16px; border-bottom:1px solid var(--divider-color); }
    .cfg-row:last-child { border-bottom:none; }
    .cfg-k { font-size:13px; color:var(--secondary-text-color); }
    .cfg-v { font-size:13px; font-weight:500; color:var(--primary-text-color); font-family:monospace; }
    .empty { padding:24px 16px; text-align:center; color:var(--secondary-text-color); font-size:13px; }
  `; }

  // ── HTML builders ─────────────────────────────────────────────────────────

  _topbarHTML() {
    const d      = this._data;
    const ctrl   = d?.controller_state ?? "unknown";
    const season = { winter:"Vinter", summer:"Sommer", auto:"Auto" }[d?.season_mode] ?? "Auto";
    const otemp  = d?.outdoor_temp != null ? `${Math.round(d.outdoor_temp)}°C ude · ` : "";
    const labels = { on:"On", pause:"Pause", off:"Off" };
    return `
      <div class="topbar">
        <div class="topbar-left">
          <div>
            <div class="topbar-title">Heat Manager</div>
            <div class="topbar-sub">${otemp}${season}</div>
          </div>
          <div id="topbar-badge" class="ctrl-badge"
            style="background:${this._ctrlBg(ctrl)};color:${this._ctrlColor(ctrl)};border-color:${this._ctrlBorder(ctrl)}">
            ${labels[ctrl] ?? ctrl}
          </div>
        </div>
        <button class="refresh-btn" data-action="refresh" title="Genindlæs">
          <svg viewBox="0 0 24 24"><path d="M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z"/></svg>
        </button>
      </div>`;
  }

  _tabsHTML() {
    return `<div class="tabs">${[
      {id:"overview", label:"Oversigt"},
      {id:"rooms",    label:"Rum"},
      {id:"history",  label:"Historik"},
      {id:"config",   label:"Konfiguration"},
    ].map(t => `<button class="tab${this._tab===t.id?" active":""}" data-tab="${t.id}">${t.label}</button>`).join("")}</div>`;
  }

  // Controller card — stable IDs on every element that _patchController() targets
  _controllerHTML() {
    const ctrl     = this._data?.controller_state ?? "unknown";
    const pauseLeft = this._data?.pause_remaining ?? 0;
    const showPause = ctrl === "pause" && pauseLeft > 0;

    const btnStyle = (name) => {
      const active = ctrl === name;
      const s = { on:["#EAF3DE","#3B6D11","#27500A"], pause:["#FAEEDA","#854F0B","#633806"], off:["var(--secondary-background-color)","var(--secondary-text-color)","var(--secondary-text-color)"] }[name];
      return active && s ? `background:${s[0]};border-color:${s[1]};color:${s[2]}` : "";
    };

    return `
      <div class="card" id="ctrl-card">
        <div class="section-label">Controller</div>
        <div class="btn-row">
          <button id="ctrl-btn-on"    class="ctrl-btn" data-action="on"    style="${btnStyle("on")}">On</button>
          <button id="ctrl-btn-pause" class="ctrl-btn" data-action="pause" style="${btnStyle("pause")}">Pause</button>
          <button id="ctrl-btn-off"   class="ctrl-btn" data-action="off"   style="${btnStyle("off")}">Off</button>
        </div>
        <div class="pause-row">
          <span class="pause-label">Pause varighed</span>
          <select class="pause-select" id="pause-dur">
            <option value="30">30 min</option>
            <option value="60">1 time</option>
            <option value="120" selected>2 timer</option>
            <option value="240">4 timer</option>
            <option value="480">til i morgen</option>
          </select>
        </div>
        <div id="pause-bar" class="pause-bar" style="display:${showPause?"flex":"none"}">
          <span id="pause-bar-text" class="pause-bar-text">Pause — ${pauseLeft} min tilbage</span>
          <button class="resume-btn" data-action="resume">Genoptag nu</button>
        </div>
      </div>`;
  }

  _roomsListHTML(rooms, detailed) {
    if (!rooms?.length) return `<div class="empty">Ingen rum konfigureret</div>`;
    return rooms.map(room => {
      const color  = this._dotColor(room.state);
      const temp   = room.climate_entity ? this._climateTemp(room.climate_entity) : this._fmtTemp(room.current_temp);
      const setpt  = room.climate_entity ? this._climateSetpoint(room.climate_entity) : null;
      return `
        <div class="room-row">
          <div class="dot" style="background:${color}"></div>
          <div class="room-main">
            <div class="room-name">${this._esc(room.name)}</div>
            ${detailed && room.why ? `<div class="room-why">${this._esc(room.why)}</div>` : ""}
          </div>
          <div class="room-right">
            <div class="room-state" style="${room.state==="window_open"?"color:#BA7517":""}">${this._stateLabel(room.state)}</div>
            <div class="room-temp">${temp}</div>
            ${setpt ? `<div class="room-setpoint">sætpunkt ${setpt}</div>` : ""}
          </div>
        </div>`;
    }).join("");
  }

  _energyChartHTML() {
    const days = this._history?.days ?? this._fakeDays();
    const max  = Math.max(...days.map(d => (d.saved ?? 0) + (d.wasted ?? 0)), 0.1);
    const bars = days.map(d => {
      const sh = Math.round(((d.saved  ?? 0) / max) * 76);
      const wh = Math.round(((d.wasted ?? 0) / max) * 76);
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
          <div class="legend-item"><div class="legend-dot" style="background:#97C459"></div>Sparet</div>
          <div class="legend-item"><div class="legend-dot" style="background:#EF9F27"></div>Spildt</div>
        </div>
      </div>`;
  }

  _fakeDays() {
    return ["man","tir","ons","tor","fre","lør","søn"].map(l =>
      ({ label:l, saved:Math.random()*0.5, wasted:Math.random()*0.2 }));
  }

  _historyHTML() {
    const events = this._history?.events ?? [];
    if (!events.length) return `<div class="empty">Ingen historik endnu</div>`;
    return events.slice(0,20).map(e => `
      <div class="hist-row">
        <div class="hist-dot" style="background:${this._dotColor(e.type ?? "normal")}"></div>
        <div class="hist-time">${this._esc(e.time ?? "")}</div>
        <div class="hist-desc">${this._esc(e.description ?? "")}</div>
        <div class="hist-reason">${this._esc(e.reason ?? "")}</div>
      </div>`).join("");
  }

  _personsHTML() {
    const persons = this._data?.persons ?? [];
    if (!persons.length) return `<div class="empty">Ingen personer konfigureret</div>`;
    return persons.map(p => {
      const isHome   = p.state === "home";
      const noTrack  = p.tracking === false;
      const initials = (p.name ?? "?").substring(0,2).toUpperCase();
      const avCls    = noTrack ? "av-none" : isHome ? "av-home" : "av-away";
      const stTxt    = noTrack ? "Følger huset" : isHome ? "Hjemme" : "Ikke hjemme";
      const stColor  = noTrack ? "var(--secondary-text-color)" : isHome ? "#27500A" : "var(--secondary-text-color)";
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

  _autoOffHTML() {
    const d       = this._data;
    const reason  = d?.auto_off_reason ?? "none";
    const isOff   = d?.controller_state === "off";
    const otemp   = d?.outdoor_temp != null ? Math.round(d.outdoor_temp) + "°C" : "—";
    const season  = d?.season_mode ?? "auto";
    return `
      <div class="card">
        <div class="card-hdr">
          <span class="card-title">Auto-off status</span>
          <span style="font-size:12px;font-weight:500;color:${isOff?"#BA7517":"#27500A"}">${isOff?"Slukket":"Aktiv"}</span>
        </div>
        <div class="metric-grid">
          <div class="metric-box"><div class="metric-lbl">Sæson trigger</div><div class="metric-val">${season==="summer"?"Sommer — aktiv":"Vinter — inaktiv"}</div></div>
          <div class="metric-box"><div class="metric-lbl">Udetemperatur</div><div class="metric-val">${otemp} / ${d?.auto_off_threshold ?? 18}°C grænse</div></div>
          <div class="metric-box"><div class="metric-lbl">Dage over grænse</div><div class="metric-val">${d?.auto_off_days ?? 0} / ${d?.auto_off_days_required ?? 5} dage</div></div>
          <div class="metric-box"><div class="metric-lbl">Årsag til sluk</div><div class="metric-val">${isOff ? this._reasonLabel(reason) : "—"}</div></div>
        </div>
      </div>`;
  }

  // ── Tab content ───────────────────────────────────────────────────────────

  _overviewHTML() {
    const d     = this._data;
    const rooms = d?.rooms ?? [];
    const sv    = id => { const s = this._hass?.states?.[id]; return s && s.state !== "unknown" && s.state !== "unavailable" ? s.state : null; };
    const savedT  = sv("sensor.heat_manager_energy_saved_today");
    const wastT   = sv("sensor.heat_manager_energy_wasted_today");
    const scoreT  = sv("sensor.heat_manager_efficiency_score");
    const pauseL  = d?.pause_remaining ?? 0;
    return `
      ${this._controllerHTML()}
      <div class="card">
        <div class="card-hdr"><span class="card-title">Rum</span><span class="card-sub">${rooms.length} konfigureret</span></div>
        ${this._roomsListHTML(rooms, true)}
        <div class="stats-grid">
          <div class="stat"><div class="stat-label">Sparet i dag</div><div class="stat-val">${savedT ? savedT + " kWh" : "—"}</div></div>
          <div class="stat"><div class="stat-label">Spildt i dag</div><div class="stat-val warn">${wastT ? wastT + " kWh" : "—"}</div></div>
          <div class="stat"><div class="stat-label">Score</div><div class="stat-val">${scoreT ? scoreT + "/100" : "—"}</div></div>
          <div class="stat"><div class="stat-label">Pause tilbage</div><div class="stat-val">${pauseL > 0 ? pauseL + " min" : "—"}</div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-hdr"><span class="card-title">Tilstedeværelse</span></div>
        ${this._personsHTML()}
      </div>
      ${this._autoOffHTML()}`;
  }

  _roomsTabHTML() {
    return `
      <div class="card">
        <div class="card-hdr"><span class="card-title">Alle rum</span><span class="card-sub">${this._data?.rooms?.length ?? 0} rum</span></div>
        ${this._roomsListHTML(this._data?.rooms ?? [], true)}
      </div>
      <div class="card">
        <div class="card-hdr"><span class="card-title">Energi denne uge</span></div>
        ${this._energyChartHTML()}
      </div>`;
  }

  _historyTabHTML() {
    return `
      <div class="card">
        <div class="card-hdr"><span class="card-title">Hændelseslog</span><span class="card-sub">Seneste 7 dage</span></div>
        ${this._historyHTML()}
      </div>`;
  }

  _configTabHTML() {
    const d = this._data?.config ?? {};
    const rows = [
      ["Weather entity",  d.weather_entity ?? "—"],
      ["Grace dag",       d.grace_day_min  != null ? d.grace_day_min  + " min" : "—"],
      ["Grace nat",       d.grace_night_min!= null ? d.grace_night_min+ " min" : "—"],
      ["Away temp mildt", d.away_temp_mild != null ? d.away_temp_mild + "°C"  : "—"],
      ["Away temp koldt", d.away_temp_cold != null ? d.away_temp_cold + "°C"  : "—"],
      ["Auto-off grænse", d.auto_off_temp_threshold != null ? d.auto_off_temp_threshold + "°C" : "—"],
      ["Auto-off dage",   d.auto_off_temp_days != null ? d.auto_off_temp_days + " dage" : "—"],
      ["Alarm panel",     d.alarm_panel    ?? "—"],
      ["Notify service",  d.notify_service ?? "—"],
    ];
    return `
      <div class="card">
        <div class="card-hdr"><span class="card-title">Aktiv konfiguration</span></div>
        ${rows.map(([k,v]) => `<div class="cfg-row"><span class="cfg-k">${k}</span><span class="cfg-v">${this._esc(v)}</span></div>`).join("")}
      </div>
      <div class="card">
        <div class="card-hdr"><span class="card-title">Rum & sensorer</span></div>
        ${(this._data?.rooms ?? []).map(r =>
          `<div class="cfg-row"><span class="cfg-k">${this._esc(r.name)}</span><span class="cfg-v">${this._esc(r.climate_entity ?? "—")}</span></div>`
        ).join("") || `<div class="empty">Ingen rum</div>`}
      </div>`;
  }

  // ── Main render ───────────────────────────────────────────────────────────

  _render() {
    const content = {
      overview: () => this._overviewHTML(),
      rooms:    () => this._roomsTabHTML(),
      history:  () => this._historyTabHTML(),
      config:   () => this._configTabHTML(),
    }[this._tab]?.() ?? "";

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="panel">
        ${this._topbarHTML()}
        ${this._tabsHTML()}
        <div class="content">${content}</div>
      </div>`;

    this._attachEvents();
  }

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
      this._tab = btn.dataset.tab;
      if (this._tab === "history" && !this._history) this._loadHistory().then(() => this._render());
      else this._render();
    }));
    root.querySelector("[data-action='refresh']")?.addEventListener("click", () => this._load());
    root.querySelector("[data-action='on']")?.addEventListener("click",     () => this._setController("on"));
    root.querySelector("[data-action='off']")?.addEventListener("click",    () => this._setController("off"));
    root.querySelector("[data-action='resume']")?.addEventListener("click", () => this._resume());
    root.querySelector("[data-action='pause']")?.addEventListener("click",  () => {
      const min = parseInt(root.querySelector("#pause-dur")?.value ?? "120", 10);
      this._pause(min);
    });
  }
}

if (!customElements.get("heat-manager-panel")) {
  customElements.define("heat-manager-panel", HeatManagerPanel);
}
