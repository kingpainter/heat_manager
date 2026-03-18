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
        padding: 14px 16px 12px;
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
        border-radius: 6px;
        background: var(--info-color, #039be5);
        color: #fff;
      }
      .section {
        padding: 12px 16px;
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
        transition: background 0.15s, border-color 0.15s;
      }
      .btn:hover {
        background: var(--secondary-background-color);
      }
      .btn.active-on {
        background: #eaf3de;
        border-color: #3b6d11;
        color: #27500a;
      }
      .btn.active-pause {
        background: #faeeda;
        border-color: #854f0b;
        color: #633806;
      }
      .btn.active-off {
        background: var(--secondary-background-color);
        border-color: var(--secondary-text-color);
        color: var(--secondary-text-color);
      }
      .pause-duration {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
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
        padding: 8px 16px;
        background: #faeeda;
        border-bottom: 1px solid #ef9f27;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .pause-bar span {
        font-size: 12px;
        color: #633806;
      }
      .pause-cancel {
        font-size: 11px;
        font-weight: 500;
        padding: 3px 8px;
        border-radius: 6px;
        border: 1px solid #854f0b;
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
      .room-row:last-child {
        border-bottom: none;
      }
      .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
      }
      .dot-normal { background: #639922; }
      .dot-away   { background: #888780; }
      .dot-window { background: #ba7517; }
      .dot-pre_heat { background: #185fa5; }
      .dot-override { background: #993556; }
      .dot-unknown  { background: #888780; }
      .room-name {
        flex: 1;
        font-size: 13px;
        color: var(--primary-text-color);
      }
      .room-state {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .room-state.window { color: #ba7517; }
      .room-temp {
        font-size: 13px;
        font-weight: 500;
        color: var(--primary-text-color);
        min-width: 36px;
        text-align: right;
      }
      .stats {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        border-top: 1px solid var(--divider-color);
      }
      .stat {
        padding: 10px 16px;
        border-right: 1px solid var(--divider-color);
      }
      .stat:last-child { border-right: none; }
      .stat-label {
        font-size: 11px;
        color: var(--secondary-text-color);
        margin-bottom: 3px;
      }
      .stat-val {
        font-size: 16px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .stat-val.warn { color: #ba7517; }
      .config-section {
        border-top: 1px solid var(--divider-color);
        padding: 12px 16px;
      }
      .config-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 4px 0;
        border-bottom: 1px solid var(--divider-color);
      }
      .config-row:last-child { border-bottom: none; }
      .config-key {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .config-val {
        font-size: 12px;
        font-weight: 500;
        color: var(--primary-text-color);
        font-family: monospace;
      }
      .no-hass {
        padding: 24px 16px;
        text-align: center;
        color: var(--secondary-text-color);
        font-size: 13px;
      }
    `;
  }

  _state(entityId) {
    return this.hass?.states?.[entityId];
  }

  _attr(entityId, attr) {
    return this._state(entityId)?.attributes?.[attr];
  }

  _stateStr(entityId) {
    return this._state(entityId)?.state ?? "unknown";
  }

  _controllerState() {
    return this._stateStr("select.heat_manager_controller_state");
  }

  _seasonMode() {
    return this._stateStr("select.heat_manager_season_mode");
  }

  _pauseRemaining() {
    return parseInt(this._stateStr("sensor.heat_manager_pause_remaining") ?? "0", 10);
  }

  async _setControllerState(state) {
    await this.hass.callService("heat_manager", "set_controller_state", { state });
  }

  async _resumeNow() {
    await this.hass.callService("heat_manager", "resume", {});
  }

  async _pauseFor() {
    await this.hass.callService("heat_manager", "pause", {
      duration_minutes: this._pauseMinutes,
    });
  }

  _roomsFromConfig() {
    return this.config?.rooms ?? [];
  }

  _roomState(roomName) {
    const key = roomName.toLowerCase().replace(/\s+/g, "_");
    return this._stateStr(`sensor.heat_manager_${key}_state`);
  }

  _climateTemp(climateEntityId) {
    const t = this._attr(climateEntityId, "current_temperature");
    return t != null ? `${Math.round(t * 10) / 10}°C` : "—";
  }

  _dotClass(state) {
    const map = {
      normal: "dot-normal",
      away: "dot-away",
      window_open: "dot-window",
      pre_heat: "dot-pre_heat",
      override: "dot-override",
    };
    return map[state] ?? "dot-unknown";
  }

  _stateLabel(state) {
    const map = {
      normal: "Schedule",
      away: "Away",
      window_open: "Vindue åbent",
      pre_heat: "Forvarmning",
      override: "Override",
      unknown: "—",
    };
    return map[state] ?? state;
  }

  _outdoorTemp() {
    const weatherId = this.config?.weather_entity;
    if (!weatherId) return null;
    const t = this._attr(weatherId, "temperature");
    return t != null ? `${Math.round(t)}°C ude` : null;
  }

  _configRows() {
    const cfg = this.config ?? {};
    const rows = [];
    if (cfg.weather_entity)
      rows.push({ k: "Weather entity", v: cfg.weather_entity.replace("weather.", "") });
    if (cfg.grace_day_min != null)
      rows.push({ k: "Grace dag", v: `${cfg.grace_day_min} min` });
    if (cfg.grace_night_min != null)
      rows.push({ k: "Grace nat", v: `${cfg.grace_night_min} min` });
    if (cfg.away_temp_mild != null)
      rows.push({ k: "Away temp mildt", v: `${cfg.away_temp_mild}°C` });
    if (cfg.away_temp_cold != null)
      rows.push({ k: "Away temp koldt", v: `${cfg.away_temp_cold}°C` });
    if (cfg.alarm_panel)
      rows.push({ k: "Alarm panel", v: cfg.alarm_panel.replace("alarm_control_panel.", "") });
    const roomCount = (cfg.rooms ?? []).length;
    if (roomCount)
      rows.push({ k: "Rum konfigureret", v: `${roomCount}` });
    const personCount = (cfg.persons ?? []).length;
    if (personCount)
      rows.push({ k: "Personer", v: `${personCount}` });
    return rows;
  }

  render() {
    if (!this.hass) {
      return html`<ha-card><div class="no-hass">Heat Manager indlæser...</div></ha-card>`;
    }

    const ctrl = this._controllerState();
    const season = this._seasonMode();
    const pauseLeft = this._pauseRemaining();
    const rooms = this._roomsFromConfig();
    const outdoorTemp = this._outdoorTemp();

    const subParts = [];
    if (season === "winter") subParts.push("Vinter");
    else if (season === "summer") subParts.push("Sommer");
    else subParts.push("Auto");
    if (outdoorTemp) subParts.push(outdoorTemp);

    const configRows = this._configRows();

    return html`
      <ha-card>
        <div class="header">
          <div>
            <p class="header-title">Heat Manager</p>
            <p class="header-sub">${subParts.join(" · ")}</p>
          </div>
          <span class="season-badge">${season === "winter" ? "Vinter" : season === "summer" ? "Sommer" : "Auto"}</span>
        </div>

        <div class="section">
          <div class="section-label">Controller</div>
          <div class="btn-row">
            <button
              class="btn ${ctrl === "on" ? "active-on" : ""}"
              @click=${() => this._setControllerState("on")}
            >On</button>
            <button
              class="btn ${ctrl === "pause" ? "active-pause" : ""}"
              @click=${() => this._pauseFor()}
            >Pause</button>
            <button
              class="btn ${ctrl === "off" ? "active-off" : ""}"
              @click=${() => this._setControllerState("off")}
            >Off</button>
          </div>
          <div class="pause-duration">
            <label>Pause varighed</label>
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
            <button class="pause-cancel" @click=${() => this._resumeNow()}>Genoptag nu</button>
          </div>
        ` : ""}

        ${rooms.length > 0 ? html`
          <div>
            ${rooms.map((room) => {
              const state = this._roomState(room.room_name);
              const temp = this._climateTemp(room.climate_entity);
              return html`
                <div class="room-row">
                  <div class="dot ${this._dotClass(state)}"></div>
                  <span class="room-name">${room.room_name}</span>
                  <span class="room-state ${state === "window_open" ? "window" : ""}">
                    ${this._stateLabel(state)}
                  </span>
                  <span class="room-temp">${temp}</span>
                </div>
              `;
            })}
          </div>
        ` : ""}

        <div class="stats">
          <div class="stat">
            <div class="stat-label">Sparet i dag</div>
            <div class="stat-val">${this._stateStr("sensor.heat_manager_energy_saved_today") !== "unknown"
              ? this._stateStr("sensor.heat_manager_energy_saved_today") + " kWh"
              : "—"
            }</div>
          </div>
          <div class="stat">
            <div class="stat-label">Spildt i dag</div>
            <div class="stat-val warn">${this._stateStr("sensor.heat_manager_energy_wasted_today") !== "unknown"
              ? this._stateStr("sensor.heat_manager_energy_wasted_today") + " kWh"
              : "—"
            }</div>
          </div>
          <div class="stat">
            <div class="stat-label">Score</div>
            <div class="stat-val">${this._stateStr("sensor.heat_manager_efficiency_score") !== "unknown"
              ? this._stateStr("sensor.heat_manager_efficiency_score") + "/100"
              : "—"
            }</div>
          </div>
        </div>

        ${configRows.length > 0 ? html`
          <div class="config-section">
            <div class="section-label">Konfiguration</div>
            ${configRows.map((row) => html`
              <div class="config-row">
                <span class="config-key">${row.k}</span>
                <span class="config-val">${row.v}</span>
              </div>
            `)}
          </div>
        ` : ""}
      </ha-card>
    `;
  }

  static getConfigElement() {
    return document.createElement("heat-manager-card-editor");
  }

  static getStubConfig() {
    return {
      rooms: [],
      persons: [],
      weather_entity: "",
      grace_day_min: 30,
      grace_night_min: 15,
      away_temp_mild: 17,
      away_temp_cold: 15,
    };
  }
}

customElements.define("heat-manager-card", HeatManagerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "heat-manager-card",
  name: "Heat Manager",
  description: "Intelligent heating control — ON/PAUSE/OFF, room overview, configuration",
  preview: true,
});
