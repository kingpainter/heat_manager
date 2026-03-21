// Heat Manager — Custom Lovelace Card
// Version: 0.2.0
//
// Vanilla JS + Shadow DOM — no external imports.
// Runs synchronously so window.customCards is registered before
// HA's card picker scans the page.
//
// Blink fixes v0.2.0:
//   - <style> injected once via querySelector guard — no FOUC on hass updates
//   - _render() replaces .card div via replaceWith() — no shadow root rebuild
//   - _updateInPlace() handles all live state updates without any DOM rebuild

class HeatManagerCard extends HTMLElement {
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

  getCardSize() { return 3; }

  _s(id)       { return this._hass?.states?.[id]; }
  _sv(id)      { return this._s(id)?.state ?? "unknown"; }
  _attr(id, a) { return this._s(id)?.attributes?.[a]; }

  _ctrl()      { return this._sv("select.heat_manager_controller_state"); }
  _season()    { return this._sv("select.heat_manager_season_mode"); }
  _pauseLeft() { return parseInt(this._sv("sensor.heat_manager_pause_remaining") || "0", 10); }

  _sensorVal(id) {
    const s = this._s(id);
    return (s && s.state !== "unknown" && s.state !== "unavailable") ? s.state : null;
  }
  _climateTemp(id) {
    const t = this._attr(id, "current_temperature");
    return t != null ? (Math.round(t * 10) / 10) + "°C" : "—";
  }
  _roomState(name) {
    const key = name.toLowerCase().replace(/\s+/g, "_");
    return this._sv("sensor.heat_manager_" + key + "_state");
  }
  _outdoorTemp() {
    const id = this._config.weather_entity;
    if (!id) return null;
    const t = this._attr(id, "temperature");
    return t != null ? Math.round(t) + "°C ude" : null;
  }

  async _setCtrl(state) {
    await this._hass.callService("heat_manager", "set_controller_state", { state });
  }
  async _pause() {
    await this._hass.callService("heat_manager", "pause", { duration_minutes: this._pauseMinutes });
  }
  async _resume() {
    await this._hass.callService("heat_manager", "resume", {});
  }

  _seasonLabel(s) {
    return { winter:"Vinter", summer:"Sommer", auto:"Auto" }[s] ?? s ?? "Auto";
  }
  _stateLabel(s) {
    return { normal:"Schedule", away:"Away", window_open:"Vindue åbent", pre_heat:"Forvarmning", override:"Override" }[s] ?? (s || "—");
  }
  _dotColor(s) {
    return { normal:"#639922", away:"#888780", window_open:"#BA7517", pre_heat:"#185FA5", override:"#993556" }[s] ?? "#888780";
  }
  _btnStyle(name, ctrl) {
    if (ctrl !== name) return "";
    const m = { on:"#EAF3DE,#3B6D11,#27500A", pause:"#FAEEDA,#854F0B,#633806", off:"var(--secondary-background-color),var(--secondary-text-color),var(--secondary-text-color)" };
    const [bg, border, color] = (m[name] || "").split(",");
    return `background:${bg};border-color:${border};color:${color};`;
  }

  _css() {
    return `
      :host { display:block; }
      ha-card, .card {
        background:var(--card-background-color,#fff);
        border-radius:var(--ha-card-border-radius,12px);
        border:1px solid var(--divider-color,rgba(0,0,0,.12));
        overflow:hidden;
        box-shadow:var(--ha-card-box-shadow,none);
      }
      .hdr {
        display:flex; justify-content:space-between; align-items:center;
        padding:14px 16px 10px;
        border-bottom:1px solid var(--divider-color,rgba(0,0,0,.12));
      }
      .hdr-title { font-size:15px; font-weight:500; color:var(--primary-text-color); margin:0; }
      .hdr-sub   { font-size:12px; color:var(--secondary-text-color); margin:2px 0 0; }
      .badge {
        font-size:11px; font-weight:500; padding:3px 9px; border-radius:20px;
        background:var(--info-color,#039be5); color:#fff;
      }
      .section { padding:10px 16px; border-bottom:1px solid var(--divider-color,rgba(0,0,0,.12)); }
      .section-lbl {
        font-size:11px; color:var(--secondary-text-color); text-transform:uppercase;
        letter-spacing:.06em; margin-bottom:8px;
      }
      .btn-row { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
      .btn {
        padding:9px 0; border-radius:8px; border:1px solid var(--divider-color,rgba(0,0,0,.12));
        background:transparent; font-size:13px; font-weight:500; cursor:pointer;
        color:var(--primary-text-color); text-align:center;
        transition:background .12s, border-color .12s, color .12s;
      }
      .btn:active { opacity:.75; }
      .pause-row { display:flex; align-items:center; gap:8px; margin-top:8px; }
      .pause-row label { font-size:12px; color:var(--secondary-text-color); white-space:nowrap; }
      .pause-row select {
        flex:1; font-size:12px; padding:4px 8px; border-radius:6px;
        border:1px solid var(--divider-color,rgba(0,0,0,.12));
        background:var(--card-background-color,#fff); color:var(--primary-text-color);
      }
      .pause-bar {
        display:flex; align-items:center; justify-content:space-between;
        padding:8px 16px; background:#FAEEDA; border-top:1px solid #EF9F27;
      }
      .pause-bar span { font-size:12px; color:#633806; }
      .resume-btn {
        font-size:11px; font-weight:500; padding:3px 9px; border-radius:6px;
        border:1px solid #854F0B; background:transparent; color:#633806; cursor:pointer;
      }
      .room-row {
        display:flex; align-items:center; padding:9px 16px; gap:10px;
        border-bottom:1px solid var(--divider-color,rgba(0,0,0,.12));
      }
      .room-row:last-child { border-bottom:none; }
      .dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
      .room-name  { flex:1; font-size:13px; color:var(--primary-text-color); }
      .room-state { font-size:12px; color:var(--secondary-text-color); }
      .room-temp  { font-size:13px; font-weight:500; color:var(--primary-text-color); min-width:38px; text-align:right; }
      .stats { display:grid; grid-template-columns:1fr 1fr 1fr; }
      .stat { padding:10px 16px; border-right:1px solid var(--divider-color,rgba(0,0,0,.12)); }
      .stat:last-child { border-right:none; }
      .stat-lbl { font-size:11px; color:var(--secondary-text-color); margin-bottom:3px; }
      .stat-val { font-size:16px; font-weight:500; color:var(--primary-text-color); }
      .stat-val.warn { color:#BA7517; }
    `;
  }

  _render() {
    const rootEl = this.shadowRoot;

    // Inject <style> once — re-injecting on every render causes FOUC.
    // _updateInPlace() handles all live updates without touching <style>.
    if (!rootEl.querySelector("style")) {
      const st = document.createElement("style");
      st.textContent = this._css();
      rootEl.appendChild(st);
    }

    const ctrl        = this._ctrl();
    const season      = this._season();
    const pauseLeft   = this._pauseLeft();
    const rooms       = this._config.rooms || [];
    const seasonLabel = this._seasonLabel(season);
    const otemp       = this._outdoorTemp();
    const sub         = [seasonLabel, otemp].filter(Boolean).join(" · ");

    const savedToday  = this._sensorVal("sensor.heat_manager_energy_saved_today");
    const wastedToday = this._sensorVal("sensor.heat_manager_energy_wasted_today");
    const score       = this._sensorVal("sensor.heat_manager_efficiency_score");

    const roomsHTML = rooms.map(room => {
      const state = this._roomState(room.room_name || "");
      const temp  = this._climateTemp(room.climate_entity || "");
      const color = this._dotColor(state);
      const stLbl = this._stateLabel(state);
      const warn  = state === "window_open" ? "color:#BA7517;" : "";
      return `
        <div class="room-row">
          <div class="dot" style="background:${color}"></div>
          <span class="room-name">${this._esc(room.room_name || "")}</span>
          <span class="room-state" style="${warn}">${stLbl}</span>
          <span class="room-temp">${temp}</span>
        </div>`;
    }).join("");

    const pauseBar = (ctrl === "pause" && pauseLeft > 0)
      ? `<div class="pause-bar">
           <span>Pause — ${pauseLeft} min tilbage</span>
           <button class="resume-btn" id="resume-btn">Genoptag nu</button>
         </div>`
      : "";

    const cardHTML = `<div class="card">
        <div class="hdr">
          <div>
            <p class="hdr-title">Heat Manager</p>
            <p class="hdr-sub">${sub}</p>
          </div>
          <span class="badge" id="season-badge">${seasonLabel}</span>
        </div>
        <div class="section">
          <div class="section-lbl">Controller</div>
          <div class="btn-row">
            <button class="btn" id="btn-on"    style="${this._btnStyle("on",    ctrl)}">On</button>
            <button class="btn" id="btn-pause" style="${this._btnStyle("pause", ctrl)}">Pause</button>
            <button class="btn" id="btn-off"   style="${this._btnStyle("off",   ctrl)}">Off</button>
          </div>
          <div class="pause-row">
            <label>Pause i</label>
            <select id="pause-dur">
              <option value="30">30 min</option>
              <option value="60">1 time</option>
              <option value="120" selected>2 timer</option>
              <option value="240">4 timer</option>
              <option value="480">til i morgen</option>
            </select>
          </div>
        </div>
        ${pauseBar}
        ${rooms.length ? `<div id="rooms">${roomsHTML}</div>` : ""}
        <div class="stats">
          <div class="stat">
            <div class="stat-lbl">Sparet i dag</div>
            <div class="stat-val" id="stat-saved">${savedToday ? savedToday + " kWh" : "—"}</div>
          </div>
          <div class="stat">
            <div class="stat-lbl">Spildt i dag</div>
            <div class="stat-val warn" id="stat-wasted">${wastedToday ? wastedToday + " kWh" : "—"}</div>
          </div>
          <div class="stat">
            <div class="stat-lbl">Score</div>
            <div class="stat-val" id="stat-score">${score ? score + "/100" : "—"}</div>
          </div>
        </div>
      </div>`;

    // Replace existing .card in-place — never touch the <style> node
    const existing = rootEl.querySelector(".card");
    if (existing) {
      const tmp = document.createElement("div");
      tmp.innerHTML = cardHTML;
      existing.replaceWith(tmp.firstElementChild);
    } else {
      rootEl.insertAdjacentHTML("beforeend", cardHTML);
    }

    this._attachEvents();
  }

  _updateInPlace() {
    const root = this.shadowRoot;
    if (!root || !root.querySelector(".card")) { this._render(); return; }

    const ctrl        = this._ctrl();
    const season      = this._season();
    const pauseLeft   = this._pauseLeft();
    const seasonLabel = this._seasonLabel(season);
    const otemp       = this._outdoorTemp();

    const sub = root.querySelector(".hdr-sub");
    if (sub) sub.textContent = [seasonLabel, otemp].filter(Boolean).join(" · ");

    const badge = root.querySelector("#season-badge");
    if (badge) badge.textContent = seasonLabel;

    for (const name of ["on", "pause", "off"]) {
      const btn = root.querySelector("#btn-" + name);
      if (btn) btn.style.cssText = this._btnStyle(name, ctrl);
    }

    const existingBar = root.querySelector(".pause-bar");
    const showBar = ctrl === "pause" && pauseLeft > 0;
    if (existingBar && !showBar) {
      existingBar.remove();
    } else if (!existingBar && showBar) {
      const section = root.querySelector(".section");
      const barEl = document.createElement("div");
      barEl.className = "pause-bar";
      barEl.innerHTML = `<span>Pause — ${pauseLeft} min tilbage</span><button class="resume-btn" id="resume-btn">Genoptag nu</button>`;
      section.after(barEl);
      barEl.querySelector("#resume-btn")?.addEventListener("click", () => this._resume());
    } else if (existingBar && showBar) {
      const txt = existingBar.querySelector("span");
      if (txt) txt.textContent = "Pause — " + pauseLeft + " min tilbage";
    }

    const rooms = this._config.rooms || [];
    rooms.forEach((room, i) => {
      const rows = root.querySelectorAll(".room-row");
      if (!rows[i]) return;
      const state = this._roomState(room.room_name || "");
      const dot   = rows[i].querySelector(".dot");
      const stEl  = rows[i].querySelector(".room-state");
      const tEl   = rows[i].querySelector(".room-temp");
      if (dot)  dot.style.background = this._dotColor(state);
      if (stEl) { stEl.textContent = this._stateLabel(state); stEl.style.color = state === "window_open" ? "#BA7517" : ""; }
      if (tEl)  tEl.textContent = this._climateTemp(room.climate_entity || "");
    });

    const saved  = this._sensorVal("sensor.heat_manager_energy_saved_today");
    const wasted = this._sensorVal("sensor.heat_manager_energy_wasted_today");
    const score  = this._sensorVal("sensor.heat_manager_efficiency_score");
    const sv = root.querySelector("#stat-saved");
    const wv = root.querySelector("#stat-wasted");
    const sc = root.querySelector("#stat-score");
    if (sv) sv.textContent = saved  ? saved  + " kWh" : "—";
    if (wv) wv.textContent = wasted ? wasted + " kWh" : "—";
    if (sc) sc.textContent = score  ? score  + "/100" : "—";
  }

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelector("#btn-on")?.addEventListener("click",    () => this._setCtrl("on"));
    root.querySelector("#btn-off")?.addEventListener("click",   () => this._setCtrl("off"));
    root.querySelector("#resume-btn")?.addEventListener("click",() => this._resume());
    root.querySelector("#pause-dur")?.addEventListener("change", e => {
      this._pauseMinutes = parseInt(e.target.value, 10);
    });
    root.querySelector("#btn-pause")?.addEventListener("click", () => this._pause());
  }

  _esc(s) {
    return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  static getConfigElement() {
    return document.createElement("heat-manager-card-editor");
  }

  static getStubConfig() {
    return {
      rooms: [],
      weather_entity: "",
      grace_day_min: 30,
      grace_night_min: 15,
      away_temp_mild: 17,
      away_temp_cold: 15,
    };
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
    description: "ON/PAUSE/OFF controller, room overview and energy stats",
    preview: true,
    documentationURL: "https://github.com/kingpainter/heat-manager",
  });
}


// ── Heat Manager Card Editor ──────────────────────────────────────────────────
// Editor <style> is intentionally re-injected on each _render() call because
// the editor is only shown in the card picker dialog (low frequency) and
// the full shadowRoot.innerHTML pattern is simpler for a form-heavy component.

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
      detail: { config: { ...this._config, rooms: this._rooms } },
      bubbles: true,
      composed: true,
    }));
  }

  _css() {
    return `
      :host { display:block; padding:4px 0; font-family:var(--primary-font-family,sans-serif); }
      * { box-sizing:border-box; margin:0; padding:0; }
      .row { padding:10px 0; border-bottom:1px solid var(--divider-color,#e0e0e0); }
      .row:last-child { border-bottom:none; }
      label { display:block; font-size:12px; color:var(--secondary-text-color,#727272); margin-bottom:5px; }
      input, select {
        width:100%; padding:8px 10px; font-size:14px;
        border:1px solid var(--divider-color,#ccc); border-radius:6px;
        background:var(--card-background-color,#fff);
        color:var(--primary-text-color,#212121);
      }
      input:focus, select:focus { outline:none; border-color:var(--primary-color,#03a9f4); }
      .section-hdr {
        font-size:13px; font-weight:500; color:var(--primary-text-color,#212121);
        padding:14px 0 6px; border-top:1px solid var(--divider-color,#e0e0e0);
        margin-top:4px; display:flex; justify-content:space-between; align-items:center;
      }
      .section-hdr.first { border-top:none; padding-top:4px; }
      .add-btn {
        font-size:12px; padding:4px 12px; border-radius:6px;
        border:1px solid var(--primary-color,#03a9f4);
        background:transparent; color:var(--primary-color,#03a9f4);
        cursor:pointer; font-weight:500;
      }
      .room-block {
        border:1px solid var(--divider-color,#e0e0e0); border-radius:8px;
        padding:10px 12px; margin-bottom:10px;
      }
      .room-hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
      .room-title { font-size:13px; font-weight:500; color:var(--primary-text-color,#212121); }
      .del-btn {
        font-size:11px; padding:3px 9px; border-radius:6px;
        border:1px solid var(--error-color,#db4437);
        background:transparent; color:var(--error-color,#db4437); cursor:pointer;
      }
      .field { margin-bottom:9px; }
      .field:last-child { margin-bottom:0; }
      .hint { font-size:11px; color:var(--secondary-text-color,#727272); margin-top:3px; }
      .empty-rooms {
        padding:16px; text-align:center; color:var(--secondary-text-color,#727272);
        font-size:13px; border:1px dashed var(--divider-color,#ccc);
        border-radius:8px; margin-bottom:8px;
      }
    `;
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
              <label>Rumnavn</label>
              <input class="room-name" data-idx="${i}" type="text"
                value="${this._esc(room.room_name || "")}" placeholder="f.eks. Køkken">
            </div>
            <div class="field">
              <label>Klimaenhed</label>
              <input class="room-climate" data-idx="${i}" type="text"
                value="${this._esc(room.climate_entity || "")}" placeholder="climate.koekken">
              <div class="hint">Settings → Devices & Services → Entities</div>
            </div>
          </div>`).join("")
      : `<div class="empty-rooms">Ingen rum — klik "+ Tilføj rum"</div>`;

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <div class="section-hdr first">Globale indstillinger</div>
      <div class="row">
        <label>Vejr-entitet</label>
        <input id="weather" type="text"
          value="${this._esc(c.weather_entity || "")}" placeholder="weather.forecast_home">
      </div>
      <div class="row">
        <label>Away temp — mildt vejr (°C)</label>
        <input id="away_mild" type="number" min="5" max="25" step="0.5" value="${c.away_temp_mild ?? 17}">
      </div>
      <div class="row">
        <label>Away temp — koldt vejr (°C)</label>
        <input id="away_cold" type="number" min="5" max="25" step="0.5" value="${c.away_temp_cold ?? 15}">
      </div>
      <div class="row">
        <label>Nådeperiode — dag (min)</label>
        <input id="grace_day" type="number" min="5" max="120" step="5" value="${c.grace_day_min ?? 30}">
      </div>
      <div class="row">
        <label>Nådeperiode — nat (min)</label>
        <input id="grace_night" type="number" min="5" max="60" step="5" value="${c.grace_night_min ?? 15}">
      </div>
      <div class="section-hdr">
        Rum <button class="add-btn" id="add-room">+ Tilføj rum</button>
      </div>
      <div id="rooms-container">${roomsHTML}</div>`;

    this._attachEvents();
  }

  _esc(s) {
    return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  _attachEvents() {
    const root = this.shadowRoot;
    const scalars = {
      "#weather":     v => { this._config.weather_entity  = v.trim(); },
      "#away_mild":   v => { this._config.away_temp_mild  = parseFloat(v); },
      "#away_cold":   v => { this._config.away_temp_cold  = parseFloat(v); },
      "#grace_day":   v => { this._config.grace_day_min   = parseInt(v, 10); },
      "#grace_night": v => { this._config.grace_night_min = parseInt(v, 10); },
    };
    for (const [sel, fn] of Object.entries(scalars)) {
      root.querySelector(sel)?.addEventListener("change", e => { fn(e.target.value); this._fire(); });
    }
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
