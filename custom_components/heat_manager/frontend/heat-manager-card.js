import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@3.3.3/lit-element.js?module";

class HeatManagerCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _pauseMinutes: { type: Number },
    };
  }

  constructor() {
    super();
    this._pauseMinutes = 120;
  }

  setConfig(config) {
    this.config = config;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        font-family: var(--primary-font-family, sans-serif);
      }
      ha-card {
        overflow: hidden;
      }
      .header {
        padding: 14px 16px 10px;
        border-bottom: 1px solid var(--divider-color);
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .header-title {
        font-size: 15px;
        font-weight: 500;
        color: var(--primary-text-color);
        margin: 0;
      }
      .header-sub {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin: 2px 0 0;
      }
      .season-badge {
        font-size: 11px;
        font-weight: 500;
        padding: 3px 8px;
        border-radius: 20px;
        background: var(--info-color, #039be5);
        color: #fff;
      }
      .section {
        padding: 10px 16px;
        border-bottom: 1px solid var(--divider-color);
      }
      .section-label {
        font-size: 11px;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 8px;
      }
      .btn-row {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 8px;
      }
      .btn {
        padding: 9px 0;
        border-radius: 8px;
        border: 1px solid var(--divider-color);
        background: transparent;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        color: var(--primary-text-color);
        text-align: center;
        transition: background 0.12s, border-color 0.12s, color 0.12s;
      }
      .btn:active { opacity: 0.75; }
      .btn.active-on    { background:#EAF3DE; border-color:#3B6D11; color:#27500A; }
      .btn.active-pause { background:#FAEEDA; border-color:#854F0B; color:#633806; }
      .btn.active-off   { background:var(--secondary-background-color); border-color:var(--secondary-text-color); color:var(--secondary-text-color); }
      .pause-duration {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
      }
      .pause-duration label {
        font-size: 12px;
        color: var(--secondary-text-color);
        white-space: nowrap;
      }
      .pause-duration select {
        flex: 1;
        font-size: 12px;
        padding: 4px 6px;
        border-radius: 6px;
        border: 1px solid var(--divider-color);
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      .pause-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 16px;
        background: #FAEEDA;
        border-top: 1px solid #EF9F27;
      }
      .pause-bar span { font-size: 12px; color: #633806; }
      .pause-cancel {
        font-size: 11px;
        font-weight: 500;
        padding: 3px 8px;
        border-radius: 6px;
        border: 1px solid #854F0B;
        background: transparent;
        color: #633806;
        cursor: pointer;
      }
      .room-row {
        display: flex;
        align-items: center;
        padding: 8px 16px;
        gap: 10px;
        border-bottom: 1px solid var(--divider-color);
      }
      .room-row:last-child { border-bottom: none; }
      .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
      .dot-normal   { background: #639922; }
      .dot-away     { background: #888780; }
      .dot-window   { background: #BA7517; }
      .dot-pre_heat { background: #185FA5; }
      .dot-override { background: #993556; }
      .dot-unknown  { background: #888780; }
      .room-name  { flex: 1; font-size: 13px; color: var(--primary-text-color); }
      .room-state { font-size: 12px; color: var(--secondary-text-color); }
      .room-state.window { color: #BA7517; }
      .room-temp  { font-size: 13px; font-weight: 500; color: var(--primary-text-color); min-width: 36px; text-align: right; }
      .stats { display: grid; grid-template-columns: 1fr 1fr 1fr; border-top: 1px solid var(--divider-color); }
      .stat { padding: 10px 16px; border-right: 1px solid var(--divider-color); }
      .stat:last-child { border-right: none; }
      .stat-label { font-size: 11px; color: var(--secondary-text-color); margin-bottom: 3px; }
      .stat-val   { font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
      .stat-val.warn { color: #BA7517; }
      .no-hass { padding: 24px 16px; text-align: center; color: var(--secondary-text-color); font-size: 13px; }
    `;
  }

  _state(id)    { return this.hass?.states?.[id]; }
  _stateStr(id) { return this._state(id)?.state ?? "unknown"; }
  _attr(id, a)  { return this._state(id)?.attributes?.[a]; }

  _ctrl()      { return this._stateStr("select.heat_manager_controller_state"); }
  _season()    { return this._stateStr("select.heat_manager_season_mode"); }
  _pauseLeft() { return parseInt(this._stateStr("sensor.heat_manager_pause_remaining") ?? "0", 10); }

  async _setCtrl(state) {
    await this.hass.callService("heat_manager", "set_controller_state", { state });
  }
  async _pause() {
    await this.hass.callService("heat_manager", "pause", { duration_minutes: this._pauseMinutes });
  }
  async _resume() {
    await this.hass.callService("heat_manager", "resume", {});
  }

  _rooms() { return this.config?.rooms ?? []; }

  _climateTemp(id) {
    const t = this._attr(id, "current_temperature");
    return t != null ? `${Math.round(t * 10) / 10}°C` : "—";
  }
  _dotClass(s) {
    return ({ normal:"dot-normal", away:"dot-away", window_open:"dot-window", pre_heat:"dot-pre_heat", override:"dot-override" })[s] ?? "dot-unknown";
  }
  _stateLabel(s) {
    return ({ normal:"Schedule", away:"Away", window_open:"Vindue åbent", pre_heat:"Forvarmning", override:"Override" })[s] ?? (s ?? "—");
  }
  _roomState(name) {
    const key = name.toLowerCase().replace(/\s+/g, "_");
    return this._stateStr(`sensor.heat_manager_${key}_state`);
  }
  _sensorVal(id) {
    const s = this._state(id);
    return s && s.state !== "unknown" && s.state !== "unavailable" ? s.state : null;
  }
  _outdoorTemp() {
    const id = this.config?.weather_entity;
    if (!id) return null;
    const t = this._attr(id, "temperature");
    return t != null ? `${Math.round(t)}°C ude` : null;
  }

  render() {
    if (!this.hass) {
      return html`<ha-card><div class="no-hass">Heat Manager indlæser...</div></ha-card>`;
    }

    const ctrl      = this._ctrl();
    const season    = this._season();
    const pauseLeft = this._pauseLeft();
    const rooms     = this._rooms();
    const otemp     = this._outdoorTemp();

    const seasonLabel = ({ winter:"Vinter", summer:"Sommer", auto:"Auto" })[season] ?? season;
    const subParts    = [seasonLabel, otemp].filter(Boolean).join(" · ");

    const savedToday  = this._sensorVal("sensor.heat_manager_energy_saved_today");
    const wastedToday = this._sensorVal("sensor.heat_manager_energy_wasted_today");
    const score       = this._sensorVal("sensor.heat_manager_efficiency_score");

    return html`
      <ha-card>
        <div class="header">
          <div>
            <p class="header-title">Heat Manager</p>
            <p class="header-sub">${subParts}</p>
          </div>
          <span class="season-badge">${seasonLabel}</span>
        </div>

        <div class="section">
          <div class="section-label">Controller</div>
          <div class="btn-row">
            <button class="btn ${ctrl === "on"    ? "active-on"    : ""}" @click=${() => this._setCtrl("on")}>On</button>
            <button class="btn ${ctrl === "pause" ? "active-pause" : ""}" @click=${() => this._pause()}>Pause</button>
            <button class="btn ${ctrl === "off"   ? "active-off"   : ""}" @click=${() => this._setCtrl("off")}>Off</button>
          </div>
          <div class="pause-duration">
            <label>Pause i</label>
            <select @change=${(e) => (this._pauseMinutes = parseInt(e.target.value, 10))}>
              <option value="30">30 min</option>
              <option value="60">1 time</option>
              <option value="120" selected>2 timer</option>
              <option value="240">4 timer</option>
              <option value="480">til i morgen</option>
            </select>
          </div>
        </div>

        ${ctrl === "pause" && pauseLeft > 0 ? html`
          <div class="pause-bar">
            <span>Pause — ${pauseLeft} min tilbage</span>
            <button class="pause-cancel" @click=${() => this._resume()}>Genoptag nu</button>
          </div>
        ` : ""}

        ${rooms.length ? html`
          <div>
            ${rooms.map(room => {
              const state = this._roomState(room.room_name);
              const temp  = this._climateTemp(room.climate_entity);
              return html`
                <div class="room-row">
                  <div class="dot ${this._dotClass(state)}"></div>
                  <span class="room-name">${room.room_name}</span>
                  <span class="room-state ${state === "window_open" ? "window" : ""}">${this._stateLabel(state)}</span>
                  <span class="room-temp">${temp}</span>
                </div>`;
            })}
          </div>
        ` : ""}

        <div class="stats">
          <div class="stat">
            <div class="stat-label">Sparet i dag</div>
            <div class="stat-val">${savedToday ? savedToday + " kWh" : "—"}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Spildt i dag</div>
            <div class="stat-val warn">${wastedToday ? wastedToday + " kWh" : "—"}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Score</div>
            <div class="stat-val">${score ? score + "/100" : "—"}</div>
          </div>
        </div>
      </ha-card>
    `;
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
// Shown when the user clicks the pencil icon on the card in Lovelace.
// Vanilla JS + Shadow DOM — no LitElement dependency needed for the editor.
// Fires "config-changed" events so Lovelace updates the preview live.

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
      input:focus, select:focus {
        outline:none; border-color:var(--primary-color,#03a9f4);
        box-shadow:0 0 0 2px color-mix(in srgb, var(--primary-color,#03a9f4) 20%, transparent);
      }
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
        cursor:pointer; font-weight:500; white-space:nowrap;
      }
      .add-btn:hover { background:color-mix(in srgb, var(--primary-color,#03a9f4) 10%, transparent); }
      .room-block {
        border:1px solid var(--divider-color,#e0e0e0); border-radius:8px;
        padding:10px 12px; margin-bottom:10px;
      }
      .room-hdr {
        display:flex; justify-content:space-between; align-items:center;
        margin-bottom:10px;
      }
      .room-title { font-size:13px; font-weight:500; color:var(--primary-text-color,#212121); }
      .del-btn {
        font-size:11px; padding:3px 9px; border-radius:6px;
        border:1px solid var(--error-color,#db4437);
        background:transparent; color:var(--error-color,#db4437);
        cursor:pointer;
      }
      .del-btn:hover { background:color-mix(in srgb, var(--error-color,#db4437) 10%, transparent); }
      .field { margin-bottom:9px; }
      .field:last-child { margin-bottom:0; }
      .hint { font-size:11px; color:var(--secondary-text-color,#727272); margin-top:3px; line-height:1.4; }
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
              <span class="room-title">Rum ${i + 1}${room.room_name ? ` — ${this._esc(room.room_name)}` : ""}</span>
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
              <div class="hint">Entity ID — find det under Settings → Devices & Services → Entities</div>
            </div>
          </div>`).join("")
      : `<div class="empty-rooms">Ingen rum tilføjet endnu — klik "+ Tilføj rum"</div>`;

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>

      <div class="section-hdr first">Globale indstillinger</div>

      <div class="row">
        <label>Vejr-entitet (entity ID)</label>
        <input id="weather" type="text"
          value="${this._esc(c.weather_entity || "")}"
          placeholder="weather.forecast_home">
        <div class="hint">Bruges til udetemperatur i kortets header</div>
      </div>

      <div class="row">
        <label>Away temperatur — mildt vejr (°C)</label>
        <input id="away_mild" type="number" min="5" max="25" step="0.5"
          value="${c.away_temp_mild ?? 17}">
      </div>

      <div class="row">
        <label>Away temperatur — koldt vejr (°C)</label>
        <input id="away_cold" type="number" min="5" max="25" step="0.5"
          value="${c.away_temp_cold ?? 15}">
      </div>

      <div class="row">
        <label>Nådeperiode — dag (minutter)</label>
        <input id="grace_day" type="number" min="5" max="120" step="5"
          value="${c.grace_day_min ?? 30}">
      </div>

      <div class="row">
        <label>Nådeperiode — nat (minutter)</label>
        <input id="grace_night" type="number" min="5" max="60" step="5"
          value="${c.grace_night_min ?? 15}">
      </div>

      <div class="section-hdr">
        Rum
        <button class="add-btn" id="add-room">+ Tilføj rum</button>
      </div>

      <div id="rooms-container">${roomsHTML}</div>`;

    this._attachEvents();
  }

  _esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  _attachEvents() {
    const root = this.shadowRoot;

    // Scalar fields — fire on blur/change so user can finish typing
    const scalar = {
      "#weather":     v => { this._config.weather_entity  = v.trim(); },
      "#away_mild":   v => { this._config.away_temp_mild  = parseFloat(v); },
      "#away_cold":   v => { this._config.away_temp_cold  = parseFloat(v); },
      "#grace_day":   v => { this._config.grace_day_min   = parseInt(v, 10); },
      "#grace_night": v => { this._config.grace_night_min = parseInt(v, 10); },
    };
    for (const [sel, fn] of Object.entries(scalar)) {
      root.querySelector(sel)?.addEventListener("change", e => { fn(e.target.value); this._fire(); });
    }

    // Add room
    root.querySelector("#add-room")?.addEventListener("click", () => {
      this._rooms.push({ room_name: "", climate_entity: "" });
      this._render();
      this._fire();
    });

    // Per-room name
    root.querySelectorAll(".room-name").forEach(el => {
      el.addEventListener("change", e => {
        this._rooms[+e.target.dataset.idx].room_name = e.target.value.trim();
        this._render();
        this._fire();
      });
    });

    // Per-room climate entity
    root.querySelectorAll(".room-climate").forEach(el => {
      el.addEventListener("change", e => {
        this._rooms[+e.target.dataset.idx].climate_entity = e.target.value.trim();
        this._fire();
      });
    });

    // Delete room
    root.querySelectorAll("[data-del]").forEach(btn => {
      btn.addEventListener("click", e => {
        this._rooms.splice(+e.target.dataset.del, 1);
        this._render();
        this._fire();
      });
    });
  }
}

if (!customElements.get("heat-manager-card-editor")) {
  customElements.define("heat-manager-card-editor", HeatManagerCardEditor);
}
