// Heat Manager Panel
// Version: 0.3.8
//
// Design: Unified visual language with Indeklima — same font (DM Sans/DM Mono),
// same card system, same section-box pattern, same score ring, same chip/badge
// components. Palette shifted to heat semantics: amber/orange for active heating,
// teal for normal/schedule, red for waste/window-open, blue for away/pre-heat.
//
// v0.3.3:
//   • Header logo now served from /api/heat_manager-logo (static HTTP path,
//     registered in panel.py) instead of an inline base64 JPEG. Avoids the
//     shadow DOM data-URI-in-src stripping issue and keeps the file lean.
//   • "Energi i dag" overview section removed — the waste calculator is
//     still active under the hood (it drives the weekly chart on the Rum tab),
//     but the overview card was rarely non-zero in practice and added noise.
//
// Architecture: same blink-free guards as 0.2.x —
//   _loadInFlight, _lastCtrlState diff, setTimeout(0) render debounce,
//   _srAppendHTML for WebKit/iOS, surgical _patchController().
//
// v0.3.4:
//   • Cloud status banner — detects Netatmo cloud outages by inspecting
//     HA climate entity availability and last_updated staleness.
//     Shown across all tabs when cloud is degraded. Configurable via
//     _showCloudBanner flag (can be disabled in config tab).
//
// v0.3.5:
//   • Scroll-position preserved on auto-refresh. _load() now calls
//     _patchAll() instead of _scheduleRender() when the panel is already
//     rendered. Full _render() only runs on initial mount and tab switches.
//   • Surgical patches: _patchRooms(), _patchPersons(), _patchQuickStats(),
//     _patchAutoOff(), _patchTopbarVersion() — all update DOM nodes in-place.
//   • Room cards carry data-room-id attribute; QS cells carry data-qs-* ids;
//     persons/autooff sections carry wrapper IDs for targeted updates.
//
// v0.3.6:
//   A) Controller ring + title + ringColor patched surgically on state change.
//   B) Pause countdown ticks locally every 60 s — no WS poll needed.
//   C) Room cards show valve position badge when available.
//   D) Boost button added to controller row (greyed when unavailable).
//   E) Refresh button shows spinner animation during _load().
//   F) Rooms tab differentiated: valve %, boost status, last-updated per room.
//   G) History tab shows last-fetched timestamp + manual refresh button.
//   H) History loading skeleton shown while WS call is in-flight.
//
// v0.3.7 — Frontend UX fixes:
//   UX1) Controller ring SVG transition fixed: use style.strokeDashoffset
//        (triggers CSS transition) instead of setAttribute (doesn't).
//   UX2) Rooms tab patched by _patchAll() via new _patchRoomsTab().
//   UX3) "Synkroniseret kl. HH:MM" timestamp in header refresh button.
//   UX4) Boost button active state set on initial render from backend data.
//   Backend data: valve_position + boost_active now in room payload.
//
// v0.3.8:
//   • Cloud banner moved into topbar — compact inline chip instead of
//     full-width banner. Dismissing hides chip without re-render.
//   • _patchCloudChip() updates topbar chip surgically.
//   • Manual TRV control in Rum tab — per-room temp slider + Send button.
//     Calls heat_manager/set_room_temp WS. Duration: 30/60/120 min or permanent.
//   • Config tab toggle: "Manuel TRV-kontrol" (session-scoped).

class HeatManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass           = null;
    this._tab            = "overview";
    this._data           = null;
    this._history        = null;
    this._errCount       = 0;
    this._interval       = null;
    this._loadInFlight    = false;
    this._renderPending   = false;
    this._lastCtrlState   = null;
    this._showCloudBanner = true;  // can be toggled off in config tab
    this._pauseTimer      = null;  // local countdown interval
    this._historyLoading  = false; // skeleton guard
    this._historyFetchedAt = null; // timestamp of last history fetch
    this._refreshing      = false; // refresh button spinner guard
    this._lastSyncTime       = null;  // UX3: timestamp of last successful WS fetch
    this._manualControlEnabled = false; // manual TRV control toggle
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
      this._patchControllerHero();
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

  disconnectedCallback() {
    clearInterval(this._interval);
    clearInterval(this._pauseTimer);
  }

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

  async _load(fromRefreshBtn = false) {
    if (!this._hass || this._loadInFlight) return;
    this._loadInFlight = true;
    if (fromRefreshBtn) { this._refreshing = true; this._patchRefreshBtn(); }
    try {
      this._data     = await this._hass.callWS({ type: "heat_manager/get_state" });
      this._errCount = 0;
      this._lastSyncTime = new Date();  // UX3
    } catch (e) {
      this._errCount++;
      this._data = this._entitiesSnapshot();
    } finally {
      this._loadInFlight = false;
      if (fromRefreshBtn) { this._refreshing = false; this._patchRefreshBtn(); }
    }
    if (this._tab === "history" && !this._history) await this._loadHistory();
    this._lastCtrlState = this._data?.controller_state ?? null;
    this._startPauseCountdown();
    // If the panel is already rendered, patch in-place to preserve scroll position.
    // Only fall back to full render on initial load (no .panel-scroll yet).
    if (this.shadowRoot.querySelector(".panel-scroll")) {
      this._patchAll();
    } else {
      this._scheduleRender();
    }
  }

  async _loadHistory() {
    this._historyLoading = true;
    this._patchHistorySkeleton();
    try {
      this._history = await this._hass.callWS({ type: "heat_manager/get_history", days: 7 });
      this._historyFetchedAt = new Date();
    } catch (e) { this._history = { events: [], days: [] }; }
    finally { this._historyLoading = false; }
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

  // ── Orchestrate all surgical patches ─────────────────────────────────────

  _patchAll() {
    this._patchController();
    this._patchControllerHero();
    this._patchTopbarBadge();
    this._patchTopbarVersion();
    this._patchQuickStats();
    this._patchRooms();
    this._patchPersons();
    this._patchAutoOff();
    this._patchCloudChip();   // replaces _patchCloudBanner (now in topbar)
    this._patchHistoryTab();
    this._patchRoomsTab();    // UX2
    this._patchRefreshBtn();  // UX3
  }

  // Update the version/temp/season line in the header without re-rendering topbar.
  _patchTopbarVersion() {
    const root   = this.shadowRoot;
    const verEl  = root.querySelector(".header-text .version");
    if (!verEl) return;
    const d      = this._data;
    const season = ({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[d?.season_mode] ?? "Auto";
    const otemp  = d?.outdoor_temp != null ? `${Math.round(d.outdoor_temp)}°C · ` : "";
    verEl.textContent = `${otemp}${season}`;
  }

  // Update the four quick-stat numbers in the overview Rum section.
  _patchQuickStats() {
    const root  = this.shadowRoot;
    const rooms = this._data?.rooms ?? [];
    const vals  = {
      "qs-active":  { v: rooms.filter(r => r.state === "normal").length,     color: "var(--amber)" },
      "qs-away":    { v: rooms.filter(r => r.state === "away").length,        color: "var(--sub)"   },
      "qs-window":  { v: rooms.filter(r => r.state === "window_open").length, color: null           },
      "qs-preheat": { v: rooms.filter(r => r.state === "pre_heat").length,    color: "var(--teal)"  },
    };
    for (const [id, { v, color }] of Object.entries(vals)) {
      const el = root.querySelector(`[data-qs="${id}"]`);
      if (!el) return; // Not on current tab — skip silently
      el.textContent = String(v);
      if (id === "qs-window") {
        el.style.color = v > 0 ? "var(--red)" : "var(--sub)";
      } else if (color) {
        el.style.color = color;
      }
    }
  }

  // Update room cards in-place. Matches by data-room-id.
  // Falls back to full re-render of the grid container if structure changed.
  _patchRooms() {
    const root  = this.shadowRoot;
    const rooms = this._data?.rooms ?? [];

    // Try surgical update first: update each existing card by room name key
    const grid = root.querySelector(".rooms-grid");
    if (!grid) return;

    const cards = grid.querySelectorAll("[data-room-id]");
    // If room count changed, re-render the whole grid
    if (cards.length !== rooms.length) {
      grid.innerHTML = rooms.length
        ? rooms.map(r => this._roomCardHTML(r)).join("")
        : `<div class="empty">Ingen rum konfigureret</div>`;
      return;
    }

    // Surgical: update each card
    rooms.forEach(room => {
      const card = grid.querySelector(`[data-room-id="${CSS.escape(room.name)}"]`);
      if (!card) return;
      const state   = room.state ?? "normal";
      const color   = this._stateColor(state);
      const grad    = this._stateGradient(state);
      const label   = this._stateLabel(state);
      const temp    = room.climate_entity ? this._climateTemp(room.climate_entity) : null;
      const setpt   = room.climate_entity ? this._climateSetpoint(room.climate_entity) : null;
      const tempStr = temp ?? (room.current_temp != null ? Math.round(room.current_temp * 10) / 10 + "°C" : "–");
      const fillPct = state === "normal" ? "100" : state === "away" ? "20" : state === "window_open" ? "50" : state === "pre_heat" ? "75" : "40";

      // Update card styles
      card.style.background = grad;
      card.style.borderLeftColor = color;
      card.className = `room-card state-${state}`;

      // Update pill
      const pill = card.querySelector(".room-state-pill");
      if (pill) { pill.textContent = label; pill.style.background = `${color}22`; pill.style.color = color; }

      // Update temps
      const vals = card.querySelectorAll(".room-temp-val");
      if (vals[0]) vals[0].textContent = tempStr;
      if (vals[1]) vals[1].textContent = setpt ?? "–";

      // Update state bar fill
      const fill = card.querySelector(".room-state-fill");
      if (fill) { fill.style.width = fillPct + "%"; fill.style.background = color; }

      // Update valve badge
      const valve     = room.valve_position != null ? Math.round(room.valve_position) : null;
      const isHeating = valve != null && valve > 0;
      let vb = card.querySelector(".room-valve-badge");
      if (valve != null) {
        const newCls = "room-valve-badge" + (isHeating ? " room-valve-heating" : "");
        const newTxt = (isHeating ? "🔥" : "❄") + " " + valve + "%";
        if (!vb) {
          const el = document.createElement("div");
          el.className = newCls; el.textContent = newTxt;
          card.appendChild(el);
        } else { vb.className = newCls; vb.textContent = newTxt; }
      } else if (vb) { vb.remove(); }

      // Update boost badge
      const bb = card.querySelector(".room-boost-badge");
      if (room.boost_active && !bb) {
        const el = document.createElement("div");
        el.className = "room-boost-badge"; el.textContent = "⚡ Boost";
        card.querySelector(".room-card-header")?.querySelector("div:last-child")?.prepend(el);
      } else if (!room.boost_active && bb) { bb.remove(); }
    });
  }

  // Update person rows in-place.
  _patchPersons() {
    const root    = this.shadowRoot;
    const wrapper = root.querySelector("#persons-wrapper");
    if (!wrapper) return;
    wrapper.innerHTML = this._personsInnerHTML();
  }

  // Update the auto-off aocard values in-place.
  _patchAutoOff() {
    const root    = this.shadowRoot;
    const wrapper = root.querySelector("#autooff-wrapper");
    if (!wrapper) return;
    wrapper.innerHTML = this._autoOffInnerHTML();
  }

  // Update compact cloud status chip in the topbar (replaces full-width banner).
  _patchCloudChip() {
    const root  = this.shadowRoot;
    const chip  = root.querySelector("#cloud-chip");
    if (!chip) return;
    const { ok, allUnavailable, staleMinutes } = this._cloudStatus();
    if (!ok && this._showCloudBanner) {
      chip.hidden = false;
      chip.title  = allUnavailable
        ? "Netatmo cloud utilgængelig"
        : `Netatmo data ${staleMinutes} min forsinket`;
      chip.querySelector(".cloud-chip-dot").style.background =
        allUnavailable ? "#ef4444" : "#f97316";
      chip.querySelector(".cloud-chip-label").textContent =
        allUnavailable ? "Cloud nede" : `⏱ ${staleMinutes} min`;
    } else {
      chip.hidden = true;
    }
  }

  // ── Additional surgical patches ──────────────────────────────────────────

  // E) Refresh button spinner
  _patchRefreshBtn() {
    const btn = this.shadowRoot.querySelector("[data-action='refresh']");
    if (!btn) return;
    if (this._refreshing) {
      btn.innerHTML = '<span class="refresh-spinner">↻</span> Opdater';
      btn.disabled = true;
    } else {
      // UX3: show last sync time
      if (this._lastSyncTime) {
        const hh = String(this._lastSyncTime.getHours()).padStart(2,"0");
        const mm = String(this._lastSyncTime.getMinutes()).padStart(2,"0");
        btn.textContent = `↻ ${hh}:${mm}`;
      } else {
        btn.textContent = "↻ Opdater";
      }
      btn.style.animation = "";
      btn.disabled = false;
    }
  }

  // A) Controller ring + title + badge patched in-place
  _patchControllerHero() {
    const root  = this.shadowRoot;
    const ctrl  = this._data?.controller_state ?? "unknown";
    const otemp = this._data?.outdoor_temp;
    const season = this._data?.season_mode ?? "auto";
    const r     = 38;
    const circ  = 2 * Math.PI * r;
    const fill  = ctrl === "on" ? circ : ctrl === "pause" ? circ * 0.5 : 0;
    const dashOffset = circ - fill;
    const ringColor  = ctrl === "on" ? "#f97316" : ctrl === "pause" ? "#eab308" : "#475569";

    const ringFill = root.querySelector(".ctrl-ring-fill");
    if (ringFill) {
      // UX1: style.* triggers CSS transitions; setAttribute does not
      ringFill.style.stroke = ringColor;
      ringFill.style.strokeDashoffset = String(dashOffset);
    }
    const ringIcon = root.querySelector(".ctrl-ring-icon");
    if (ringIcon) ringIcon.textContent = this._ctrlIcon(ctrl);

    const ctrlTitle = root.querySelector(".ctrl-title");
    if (ctrlTitle) { ctrlTitle.textContent = this._ctrlTitle(ctrl); ctrlTitle.style.color = ringColor; }

    const ctrlSub = root.querySelector(".ctrl-sub");
    if (ctrlSub) ctrlSub.textContent = `${(this._data?.rooms ?? []).length} rum konfigureret`;

    // Meta chips
    const chips = root.querySelectorAll(".ctrl-meta-chip strong");
    if (chips[0]) chips[0].textContent = otemp != null ? Math.round(otemp) + "°C" : "–";
    if (chips[1]) chips[1].textContent = ({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[season] ?? season;

    // Section badge
    const badge = root.querySelector(".section-box-badge");
    if (badge) {
      badge.textContent = this._ctrlTitle(ctrl);
      badge.style.background = `${ringColor}22`;
      badge.style.color = ringColor;
    }
  }

  // B) Local pause countdown — ticks every 60 s without WS poll
  _startPauseCountdown() {
    clearInterval(this._pauseTimer);
    if (this._data?.controller_state !== "pause") return;
    this._pauseTimer = setInterval(() => {
      if (!this._data || this._data.controller_state !== "pause") {
        clearInterval(this._pauseTimer);
        return;
      }
      if (this._data.pause_remaining > 0) {
        this._data.pause_remaining = Math.max(0, this._data.pause_remaining - 1);
      }
      this._patchController();
      this._patchControllerHero();
      if (this._data.pause_remaining === 0) clearInterval(this._pauseTimer);
    }, 60000);
  }

  // H) History skeleton — show/clear in history tab
  _patchHistorySkeleton() {
    const root = this.shadowRoot;
    if (this._tab !== "history") return;
    const container = root.querySelector(".hist-container");
    if (!container) return;
    if (this._historyLoading) {
      container.innerHTML = `
        <div style="padding:16px;display:flex;flex-direction:column;gap:8px">
          ${Array(6).fill(0).map(() => `
            <div style="display:flex;align-items:center;gap:10px;padding:4px 0">
              <div class="skel" style="width:7px;height:7px;border-radius:50%;flex-shrink:0"></div>
              <div class="skel" style="width:44px;height:13px;border-radius:4px"></div>
              <div class="skel" style="flex:1;height:13px;border-radius:4px"></div>
              <div class="skel" style="width:60px;height:11px;border-radius:4px"></div>
            </div>`).join("")}
        </div>`;
    }
  }

  // UX2: Rooms tab detail rows — patch in-place like overview rooms
  _patchRoomsTab() {
    const root = this.shadowRoot;
    if (this._tab !== "rooms") return;
    // Find the rooms detail section — rebuild its inner content surgically
    const container = root.querySelector(".rooms-detail-container");
    if (!container) return;
    const rooms = this._data?.rooms ?? [];
    const heatingCount = rooms.filter(r => (r.valve_position ?? 0) > 0).length;
    // Update badge
    const badge = root.querySelector(".rooms-detail-badge");
    if (badge) badge.textContent = `${heatingCount} / ${rooms.length} varmer`;
    // Rebuild rows (they're cheap — just text + one bar per room)
    container.innerHTML = rooms.length
      ? rooms.map(r => this._roomDetailRowHTML(r)).join("")
      : `<div class="empty">Ingen rum konfigureret</div>`;
  }

  // G) History tab: patch timestamp label + re-render rows after fresh fetch
  _patchHistoryTab() {
    const root = this.shadowRoot;
    if (this._tab !== "history") return;
    const container = root.querySelector(".hist-container");
    if (!container || this._historyLoading) return;
    container.innerHTML = this._historyRowsHTML();
    const tsEl = root.querySelector("#hist-fetched-at");
    if (tsEl && this._historyFetchedAt) {
      const hh = String(this._historyFetchedAt.getHours()).padStart(2,"0");
      const mm = String(this._historyFetchedAt.getMinutes()).padStart(2,"0");
      tsEl.textContent = `Opdateret kl. ${hh}:${mm}`;
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  async _setController(state) {
    try {
      await this._hass.callService("heat_manager", "set_controller_state", { state });
      if (this._data) this._data.controller_state = state;
      this._lastCtrlState = state;
      this._patchController();
      this._patchControllerHero();
      this._patchTopbarBadge();
      this._startPauseCountdown();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  async _pause(minutes) {
    try {
      await this._hass.callService("heat_manager", "pause", { duration_minutes: minutes });
      if (this._data) { this._data.controller_state = "pause"; this._data.pause_remaining = minutes; }
      this._lastCtrlState = "pause";
      this._patchController();
      this._patchControllerHero();
      this._patchTopbarBadge();
      this._startPauseCountdown();
    } catch (e) { console.error("[HeatManager]", e); }
  }

  async _resume() {
    try {
      await this._hass.callService("heat_manager", "resume", {});
      if (this._data) { this._data.controller_state = "on"; this._data.pause_remaining = 0; }
      this._lastCtrlState = "on";
      clearInterval(this._pauseTimer);
      this._patchController();
      this._patchControllerHero();
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
    if (season === "spring") return reason === "season" ? "Forår — afventer temperatur" : "Forår — varme aktiv (for koldt)";
    if (season === "autumn") return reason === "season" ? "Efterår — afventer temperatur" : "Efterår — varme aktiv (stadig koldt)";
    if (season === "auto")   return "Auto — kalender + temperatur overvåges";
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
        background: url("/api/heat_manager-logo") center / contain no-repeat,
                    linear-gradient(135deg, rgba(249,115,22,0.12) 0%, rgba(234,179,8,0.08) 100%);
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

      /* ── Cloud status banner ── */
      /* Cloud status chip — compact, lives in topbar */
      .cloud-chip {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 8px 3px 6px;
        border-radius: 20px;
        background: rgba(239,68,68,0.15);
        border: 1px solid rgba(239,68,68,0.35);
        cursor: pointer; font-family: 'DM Sans', sans-serif;
        transition: background .15s;
      }
      .cloud-chip:hover { background: rgba(239,68,68,0.25); }
      .cloud-chip-dot {
        width: 6px; height: 6px; border-radius: 50%;
        flex-shrink: 0; animation: chip-pulse 2s ease-in-out infinite;
      }
      @keyframes chip-pulse {
        0%,100% { opacity: 1; } 50% { opacity: 0.4; }
      }
      .cloud-chip-label { font-size: 11px; font-weight: 600; color: #fca5a5; }
      .cloud-chip-x { font-size: 10px; color: rgba(252,165,165,0.5); margin-left:2px; }

      /* Manual TRV control */
      .room-manual {
        padding: 10px 16px 12px;
        background: rgba(99,102,241,0.06);
        border-top: 1px solid rgba(99,102,241,0.15);
      }
      .room-manual-row {
        display: flex; align-items: center; gap: 8px;
      }
      .room-manual-lbl {
        font-size: 11px; color: var(--sub); width: 52px; flex-shrink: 0;
      }
      .room-manual-slider {
        flex: 1; -webkit-appearance: none; appearance: none;
        height: 4px; border-radius: 2px;
        background: linear-gradient(to right, #6366f1 var(--pct,50%), var(--bg3) var(--pct,50%));
        outline: none; cursor: pointer;
      }
      .room-manual-slider::-webkit-slider-thumb {
        -webkit-appearance: none; width: 14px; height: 14px;
        border-radius: 50%; background: #818cf8;
        border: 2px solid var(--bg2); cursor: pointer;
      }
      .room-manual-val {
        font-size: 12px; font-weight: 600; font-family: 'DM Mono', monospace;
        color: #818cf8; width: 38px; text-align: right; flex-shrink: 0;
      }
      .room-manual-dur {
        flex: 1; background: var(--bg3); border: 1px solid var(--div);
        color: var(--fg); border-radius: 7px; padding: 4px 8px;
        font-size: 12px; font-family: 'DM Sans', sans-serif; cursor: pointer;
      }
      .room-manual-send {
        padding: 5px 11px; border-radius: 7px; border: 1px solid rgba(99,102,241,0.4);
        background: rgba(99,102,241,0.12); color: #818cf8;
        font-size: 11px; font-weight: 700; cursor: pointer;
        font-family: 'DM Sans', sans-serif; white-space: nowrap;
        transition: background .15s;
      }
      .room-manual-send:hover { background: rgba(99,102,241,0.25); }
      .room-manual-send.sending { opacity: 0.5; pointer-events: none; }
      .room-manual-reset {
        padding: 5px 10px; border-radius: 7px; border: 1px solid var(--div);
        background: transparent; color: var(--sub);
        font-size: 11px; font-weight: 600; cursor: pointer;
        font-family: 'DM Sans', sans-serif; white-space: nowrap;
        transition: color .15s, border-color .15s;
      }
      .room-manual-reset:hover { color: var(--fg); border-color: var(--fg); }

      /* Toggle button (used for manual control) */
      .toggle-btn {
        padding: 6px 14px; border-radius: 8px;
        border: 1px solid var(--div); background: transparent;
        color: var(--sub); font-size: 12px; font-weight: 600;
        cursor: pointer; font-family: 'DM Sans', sans-serif;
        transition: all .15s;
      }
      .toggle-btn.active {
        border-color: rgba(99,102,241,0.5); color: #818cf8;
        background: rgba(99,102,241,0.12);
      }
      .toggle-btn:hover { color: var(--fg); border-color: var(--fg); }

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
      .ctrl-btn-row { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
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

      /* D) Boost button */
      .ctrl-btn-boost {
        border-color: rgba(168,85,247,0.3) !important;
        color: rgba(168,85,247,0.6) !important;
      }
      .ctrl-btn-boost:hover { border-color: #a855f7 !important; color: #d8b4fe !important; background: rgba(168,85,247,0.12) !important; }
      .ctrl-btn-boost.active {
        background: rgba(168,85,247,0.18) !important;
        border-color: #a855f7 !important; color: #d8b4fe !important;
      }

      /* C) Valve + boost badges on room cards */
      .room-valve-badge {
        font-size: 10px; font-weight: 600;
        color: var(--sub); margin-top: 5px;
        font-family: 'DM Mono', monospace;
      }
      .room-valve-heating { color: #f97316; }
      .room-boost-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 5px;
        background: rgba(168,85,247,0.15); color: #c084fc;
        text-transform: uppercase; letter-spacing: 0.4px;
      }

      /* E) Refresh button spin */
      @keyframes spin-refresh {
        from { display: inline-block; transform: rotate(0deg); }
        to   { display: inline-block; transform: rotate(360deg); }
      }
      .header-refresh { display: inline-flex; align-items: center; gap: 6px; }
      .refresh-spinner { display: inline-block; animation: spin-refresh 0.7s linear infinite; }

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

      /* ── Config edit rows ── */
      .cfg-edit-row {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 16px 14px;
      }
      .cfg-edit-label {
        font-size: 12px; color: var(--sub); white-space: nowrap; flex-shrink: 0;
      }
      .cfg-edit-input {
        flex: 1; min-width: 0;
        background: var(--bg3); border: 1px solid var(--div);
        border-radius: 8px; padding: 6px 10px;
        font-size: 12px; color: var(--text); font-family: 'DM Mono', monospace;
        outline: none;
      }
      .cfg-edit-input:focus { border-color: var(--accent); }
      .cfg-save-btn {
        flex-shrink: 0;
        background: var(--accent); color: #fff;
        border: none; border-radius: 8px;
        padding: 6px 14px; font-size: 12px; font-weight: 600;
        cursor: pointer; transition: opacity 0.15s;
      }
      .cfg-save-btn:hover { opacity: 0.85; }
      .cfg-save-btn:disabled { opacity: 0.45; cursor: default; }
      .cfg-save-ok {
        flex-shrink: 0; font-size: 12px; color: var(--green);
        opacity: 0; transition: opacity 0.3s;
      }
      .cfg-save-ok.visible { opacity: 1; }

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

  // ── Cloud status banner ──────────────────────────────────────────────────

  _cloudStatus() {
    // Detect Netatmo cloud issues from HA entity state — no external fetch needed.
    // Returns: { ok, allUnavailable, staleMinutes } where staleMinutes is the
    // age (in minutes) of the oldest climate entity's last_updated, or 0 if fresh.
    if (!this._hass || !this._data) return { ok: true, allUnavailable: false, staleMinutes: 0 };
    const rooms = this._data?.rooms ?? [];
    if (!rooms.length) return { ok: true, allUnavailable: false, staleMinutes: 0 };

    const climateIds = rooms.map(r => r.climate_entity).filter(Boolean);
    if (!climateIds.length) return { ok: true, allUnavailable: false, staleMinutes: 0 };

    const states = this._hass.states ?? {};
    const now = Date.now();
    let unavailableCount = 0;
    let maxStaleMs = 0;

    for (const id of climateIds) {
      const s = states[id];
      if (!s) { unavailableCount++; continue; }
      if (s.state === "unavailable" || s.state === "unknown") { unavailableCount++; continue; }
      // Check staleness via last_updated
      if (s.last_updated) {
        const staleMs = now - new Date(s.last_updated).getTime();
        if (staleMs > maxStaleMs) maxStaleMs = staleMs;
      }
    }

    const allUnavailable = unavailableCount === climateIds.length;
    const staleMinutes   = Math.floor(maxStaleMs / 60000);
    const isStale        = staleMinutes >= 10;
    return { ok: !allUnavailable && !isStale, allUnavailable, staleMinutes };
  }

  _cloudBannerHTML() {
    if (!this._showCloudBanner) return "";
    const { ok, allUnavailable, staleMinutes } = this._cloudStatus();
    if (ok) return "";

    let icon, title, detail;
    if (allUnavailable) {
      icon   = "☁️";
      title  = "Netatmo cloud utilgængelig";
      detail = "Alle klimaentiteter er unavailable — tjek <a href='https://health.netatmo.com' target='_blank' rel='noopener' style='color:inherit;text-decoration:underline'>health.netatmo.com</a>";
    } else {
      icon   = "⏱️";
      title  = "Netatmo data forsinket";
      detail = `Klimadata er ${staleMinutes} min gammel — mulig cloud-forsinkelse`;
    }

    return `
      <div class="cloud-banner">
        <span class="cloud-banner-icon">${icon}</span>
        <div class="cloud-banner-body">
          <div class="cloud-banner-title">${title}</div>
          <div class="cloud-banner-detail">${detail}</div>
        </div>
        <button class="cloud-banner-dismiss" data-action="dismiss-cloud-banner" title="Skjul">✕</button>
      </div>`;
  }

  _topbarHTML() {
    const d      = this._data;
    const ctrl   = d?.controller_state ?? "unknown";
    const season = ({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[d?.season_mode] ?? "Auto";
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
        <div class="header-icon"></div>
        <div class="header-text">
          <h1>Heat Manager</h1>
          <div class="version">${otemp}${season}</div>
        </div>
        <button id="cloud-chip" class="cloud-chip" hidden
          data-action="dismiss-cloud-banner" title="">
          <span class="cloud-chip-dot"></span>
          <span class="cloud-chip-label"></span>
          <span class="cloud-chip-x">✕</span>
        </button>
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
                <strong>${({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[season] ?? season}</strong>
              </div>
            </div>
          </div>
        </div>

        <div class="ctrl-btns-wrap">
          <div class="ctrl-btn-row">
            <button id="ctrl-btn-on"    class="ctrl-btn" data-action="on">🔥 On</button>
            <button id="ctrl-btn-pause" class="ctrl-btn" data-action="pause">⏸ Pause</button>
            <button id="ctrl-btn-off"   class="ctrl-btn" data-action="off">❄️ Off</button>
            <button id="ctrl-btn-boost" class="ctrl-btn ctrl-btn-boost" data-action="boost"
              title="Boost — varm op hurtigt">⚡ Boost</button>
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

  // Build a single room card HTML string (with data-room-id for surgical patching).
  _roomCardHTML(room) {
    const state    = room.state ?? "normal";
    const color    = this._stateColor(state);
    const grad     = this._stateGradient(state);
    const label    = this._stateLabel(state);
    const temp     = room.climate_entity ? this._climateTemp(room.climate_entity) : null;
    const setpt    = room.climate_entity ? this._climateSetpoint(room.climate_entity) : null;
    const tempStr  = temp ?? (room.current_temp != null ? Math.round(room.current_temp * 10) / 10 + "°C" : "–");
    const fillPct  = state === "normal" ? "100" : state === "away" ? "20" : state === "window_open" ? "50" : state === "pre_heat" ? "75" : "40";
    // C) Valve badge
    const valve    = room.valve_position != null ? Math.round(room.valve_position) : null;
    const isHeating = valve != null && valve > 0;
    const valveBadge = valve != null
      ? `<div class="room-valve-badge${isHeating ? " room-valve-heating" : ""}">${isHeating ? "🔥" : "❄"} ${valve}%</div>`
      : "";
    // Boost badge
    const boostBadge = room.boost_active
      ? `<div class="room-boost-badge">⚡ Boost</div>`
      : "";
    return `
      <div class="room-card state-${state}" data-room-id="${this._esc(room.name)}"
           style="background:${grad};border-left-color:${color}">
        <div class="room-card-header">
          <div class="room-card-name">${this._esc(room.name)}</div>
          <div style="display:flex;align-items:center;gap:5px">
            ${boostBadge}
            <div class="room-state-pill" style="background:${color}22;color:${color}">${label}</div>
          </div>
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
          <div class="room-state-fill" style="width:${fillPct}%;background:${color}"></div>
        </div>
        ${valveBadge}
      </div>`;
  }

  _roomsGridHTML(rooms) {
    if (!rooms?.length) return `<div class="empty">Ingen rum konfigureret</div>`;
    return `<div class="rooms-grid">${rooms.map(r => this._roomCardHTML(r)).join("")}</div>`;
  }

  _personsInnerHTML() {
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

  _personsHTML() {
    return `<div id="persons-wrapper">${this._personsInnerHTML()}</div>`;
  }

  _autoOffInnerHTML() {
    const d      = this._data;
    const isOff  = d?.controller_state === "off";
    const calMap = { winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår" };
    const calLabel = calMap[d?.calendar_season] ?? "–";
    const effLabel = calMap[d?.effective_season] ?? "–";
    const otemp  = d?.outdoor_temp != null ? Math.round(d.outdoor_temp) + "°C" : "–";
    return `
      <div class="section-box-header">
        <div class="section-box-title">Auto-off status</div>
        <div class="section-box-badge" style="background:${isOff?"rgba(239,68,68,0.15)":"rgba(249,115,22,0.15)"};color:${isOff?"#ef4444":"#f97316"}">
          ${isOff ? "Slukket" : "Aktiv"}
        </div>
      </div>
      <div class="autooff-grid">
        <div class="aocard">
          <div class="aocard-lbl">Kalender-sæson</div>
          <div class="aocard-val">${calLabel}</div>
        </div>
        <div class="aocard">
          <div class="aocard-lbl">Effektiv sæson</div>
          <div class="aocard-val">${effLabel}</div>
        </div>
        <div class="aocard">
          <div class="aocard-lbl">Udetemperatur</div>
          <div class="aocard-val">${otemp} / ${d?.auto_off_threshold ?? 18}°C grænse</div>
        </div>
        <div class="aocard">
          <div class="aocard-lbl">Dage over grænse</div>
          <div class="aocard-val">${d?.auto_off_days ?? 0} / ${d?.auto_off_days_required ?? 5}</div>
        </div>
      </div>`;
  }

  _autoOffSectionHTML() {
    return `<div id="autooff-wrapper" class="section-box">${this._autoOffInnerHTML()}</div>`;
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

      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Rum</div>
        </div>
        <div class="qs-grid">
          <div class="qs-card" style="--c:var(--amber)">
            <div class="qs-card" style="position:absolute;inset:0;border-radius:12px;background:linear-gradient(135deg,rgba(249,115,22,0.08) 0%,transparent 100%);pointer-events:none"></div>
            <div class="qs-icon">🔥</div>
            <div class="qs-value" data-qs="qs-active" style="color:var(--amber)">${active}</div>
            <div class="qs-label">Aktiv</div>
          </div>
          <div class="qs-card">
            <div class="qs-icon">🏃</div>
            <div class="qs-value" data-qs="qs-away" style="color:var(--sub)">${away}</div>
            <div class="qs-label">Fraværende</div>
          </div>
          <div class="qs-card">
            <div class="qs-icon">🪟</div>
            <div class="qs-value" data-qs="qs-window" style="color:${winOpen > 0 ? "var(--red)" : "var(--sub)"}">${winOpen}</div>
            <div class="qs-label">Vindue åbent</div>
          </div>
          <div class="qs-card">
            <div class="qs-icon">❄️</div>
            <div class="qs-value" data-qs="qs-preheat" style="color:var(--teal)">${rooms.filter(r => r.state === "pre_heat").length}</div>
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

  _roomDetailRowHTML(room) {
    const state    = room.state ?? "normal";
    const color    = this._stateColor(state);
    const temp     = room.climate_entity ? this._climateTemp(room.climate_entity) : null;
    const setpt    = room.climate_entity ? this._climateSetpoint(room.climate_entity) : null;
    const tempStr  = temp ?? (room.current_temp != null ? Math.round(room.current_temp * 10) / 10 + "°C" : "–");
    const valve    = room.valve_position != null ? Math.round(room.valve_position) : null;
    const isHeat   = valve != null && valve > 0;
    const boostBadge = room.boost_active
      ? `<span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;background:rgba(168,85,247,0.15);color:#c084fc;margin-left:4px">⚡ BOOST</span>`
      : "";
    const valveBar = valve != null
      ? `<div style="margin-top:6px">
           <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
             <span style="font-size:10px;color:var(--sub)">Ventil</span>
             <span style="font-size:10px;font-weight:600;color:${isHeat?'#f97316':'var(--sub)'};font-family:'DM Mono',monospace">${valve}%${isHeat?' 🔥':''}</span>
           </div>
           <div style="height:4px;background:var(--bg3);border-radius:2px;overflow:hidden">
             <div style="height:100%;width:${valve}%;background:${isHeat?"#f97316":"#475569"};border-radius:2px;transition:width .4s"></div>
           </div>
         </div>`
      : "";
    // Manual control section — only rendered when enabled
    const manualHTML = this._manualControlEnabled ? `
      <div class="room-manual" data-room="${this._esc(room.name)}">
        <div class="room-manual-row">
          <span class="room-manual-lbl">Mål °C</span>
          <input class="room-manual-slider" type="range" min="10" max="28" step="0.5"
            value="${setpt ? parseFloat(setpt) : 20}"
            data-room="${this._esc(room.name)}">
          <span class="room-manual-val">${setpt ? parseFloat(setpt) : 20}°C</span>
        </div>
        <div class="room-manual-row" style="margin-top:6px">
          <span class="room-manual-lbl">Varighed</span>
          <select class="room-manual-dur" data-room="${this._esc(room.name)}">
            <option value="30">30 min</option>
            <option value="60" selected>1 time</option>
            <option value="120">2 timer</option>
            <option value="0">Permanent</option>
          </select>
          <button class="room-manual-send" data-room="${this._esc(room.name)}">Send ↗</button>
          <button class="room-manual-reset" data-room="${this._esc(room.name)}">↺ Schedule</button>
        </div>
      </div>` : "";

    return `
      <div class="room-detail-row" style="border-bottom:1px solid var(--div)">
        <div style="padding:12px 16px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
            <div style="display:flex;align-items:center;gap:6px">
              <span style="font-size:14px;font-weight:600">${this._esc(room.name)}</span>
              ${boostBadge}
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-size:12px;font-family:'DM Mono',monospace">${tempStr}</span>
              <span style="font-size:11px;color:var(--sub)">→ ${setpt ?? "–"}</span>
              <span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;background:${color}22;color:${color}">${this._stateLabel(state)}</span>
            </div>
          </div>
          ${valveBar}
        </div>
        ${manualHTML}
      </div>`;
  }

  _roomsTabHTML() {
    const rooms = this._data?.rooms ?? [];
    const heatingCount = rooms.filter(r => (r.valve_position ?? 0) > 0).length;
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Rum — detaljer</div>
          <div class="section-box-badge rooms-detail-badge" style="background:rgba(249,115,22,0.15);color:var(--amber)">
            ${heatingCount} / ${rooms.length} varmer
          </div>
        </div>
        <div class="rooms-detail-container">
          ${rooms.length
            ? rooms.map(r => this._roomDetailRowHTML(r)).join("")
            : `<div class="empty">Ingen rum konfigureret</div>`}
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
    const tsText = this._historyFetchedAt
      ? `Opdateret kl. ${String(this._historyFetchedAt.getHours()).padStart(2,"0")}:${String(this._historyFetchedAt.getMinutes()).padStart(2,"0")}`
      : "";
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Hændelseslog</div>
          <span id="hist-fetched-at" style="font-size:10px;color:var(--sub);margin-left:auto;margin-right:8px">${tsText}</span>
          <button class="section-box-badge" data-action="refresh-history"
            style="background:rgba(14,165,233,0.12);color:var(--teal);border:none;cursor:pointer;padding:2px 7px;border-radius:4px;font-size:9px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase">
            ↻ 7 dage
          </button>
        </div>
        <div class="hist-container">
          ${this._historyLoading
            ? `<div style="padding:16px;display:flex;flex-direction:column;gap:8px">
                ${Array(6).fill(0).map(() => `
                  <div style="display:flex;align-items:center;gap:10px;padding:4px 0">
                    <div class="skel" style="width:7px;height:7px;border-radius:50%;flex-shrink:0"></div>
                    <div class="skel" style="width:44px;height:13px;border-radius:4px"></div>
                    <div class="skel" style="flex:1;height:13px;border-radius:4px"></div>
                    <div class="skel" style="width:60px;height:11px;border-radius:4px"></div>
                  </div>`).join("")}
               </div>`
            : this._historyRowsHTML()}
        </div>
      </div>`;
  }

  _configTabHTML() {
    const d   = this._data?.config ?? {};
    const cfg = [
      ["Weather entity",      d.weather_entity           ?? "–"],
      ["Outdoor temp sensor", d.outdoor_temp_sensor      ?? "–"],
      ["Grace dag",           d.grace_day_min   != null  ? d.grace_day_min   + " min" : "–"],
      ["Grace nat",           d.grace_night_min != null  ? d.grace_night_min + " min" : "–"],
      ["Away temp mildt",     d.away_temp_mild  != null  ? d.away_temp_mild  + "°C"   : "–"],
      ["Away temp koldt",     d.away_temp_cold  != null  ? d.away_temp_cold  + "°C"   : "–"],
      ["Auto-off grænse",     d.auto_off_temp_threshold != null ? d.auto_off_temp_threshold + "°C" : "–"],
      ["Auto-off dage",       d.auto_off_temp_days != null ? d.auto_off_temp_days + " dage" : "–"],
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
          <div class="section-box-title">Alarmtavle</div>
          <div class="section-box-badge" style="background:rgba(249,115,22,0.12);color:var(--amber)">
            ${d.alarm_panel ? 'Konfigureret' : 'Ikke sat'}
          </div>
        </div>
        <div style="padding:10px 16px 4px;font-size:12px;color:var(--sub);line-height:1.5">
          Når alarmen sættes til <strong style="color:var(--text)">armeret (væk)</strong> aktiveres
          fraværsmodus øjeblikkeligt uden grace period. Når den deaktiveres og nogen
          er hjemme, genoptages opvarmningen automatisk.
        </div>
        <div class="cfg-edit-row" style="padding-top:12px">
          <input class="cfg-edit-input" id="cfg-alarm-input"
            placeholder="alarm_control_panel.mit_alarm"
            value="${this._esc(d.alarm_panel ?? '')}">
          <button class="cfg-save-btn" data-action="save-alarm">Gem</button>
          <span class="cfg-save-ok" id="cfg-alarm-ok">✔</span>
        </div>
      </div>

      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Manuel TRV-kontrol</div>
          <div class="section-box-badge" style="background:${this._manualControlEnabled?'rgba(99,102,241,0.15)':'rgba(71,85,105,0.15)'};color:${this._manualControlEnabled?'#818cf8':'var(--sub)'}">
            ${this._manualControlEnabled ? 'Aktiv' : 'Inaktiv'}
          </div>
        </div>
        <div style="padding:14px 16px">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
            <div>
              <div style="font-size:13px;font-weight:600;margin-bottom:4px">Vis manuel temperatur-kontrol i Rum-fanen</div>
              <div style="font-size:12px;color:var(--sub);line-height:1.5">
                Tilføjer en slider og Send-knap per rum — sæt en midlertidig temperatur direkte fra panelet.
              </div>
            </div>
            <button class="toggle-btn${this._manualControlEnabled?' active':''}"
              style="flex-shrink:0" data-action="toggle-manual-control">
              ${this._manualControlEnabled ? 'Slå fra' : 'Slå til'}
            </button>
          </div>
        </div>
      </div>

      <div class="section-box" style="padding:0">
        <div class="section-box-header" style="padding:12px 16px 10px;border-bottom:1px solid var(--div)">
          <div class="section-box-title">Notifikationer</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr${d.house_voice_enabled ? ' 1fr' : ''};gap:0">

          <!-- Venstre: Push-notifikationer -->
          <div style="padding:14px 16px 16px;${d.house_voice_enabled ? 'border-right:1px solid var(--div)' : ''}">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
              <div style="width:30px;height:30px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0">📱</div>
              <div>
                <div style="font-size:13px;font-weight:600;color:var(--text)">Push-notifikationer</div>
                <div style="font-size:11px;color:var(--sub);margin-top:1px">${d.notify_service ? '<span style="color:#10b981">● Konfigureret</span>' : '<span style="color:var(--sub)">● Ikke sat</span>'}</div>
              </div>
            </div>
            <div style="font-size:11px;color:var(--sub);line-height:1.6;margin-bottom:12px">
              Sendes ved: vindue åbnet/lukket, fraværsmodus,
              ankomst, preheat og ventilbeskyttelse.
            </div>
            <div style="display:flex;align-items:center;gap:6px">
              <input class="cfg-edit-input" id="cfg-notify-input" style="flex:1;min-width:0"
                placeholder="notify.mobile_app_min_telefon"
                value="${this._esc(d.notify_service ?? '')}">
              <button class="cfg-save-btn" data-action="save-notify">Gem</button>
              <span class="cfg-save-ok" id="cfg-notify-ok">✔</span>
            </div>
          </div>

          <!-- Højre: House Voice (kun hvis aktiveret) -->
          ${d.house_voice_enabled ? `
          <div style="padding:14px 16px 16px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
              <div style="width:30px;height:30px;background:linear-gradient(135deg,#14b8a6,#34d399);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0">🔊</div>
              <div>
                <div style="font-size:13px;font-weight:600;color:var(--text)">House Voice</div>
                <div style="font-size:11px;margin-top:1px"><span style="color:#14b8a6">● Aktiv</span></div>
              </div>
            </div>
            <div style="font-size:11px;color:var(--sub);line-height:1.6;margin-bottom:12px">
              Talemeddelelser ved: controller pause/sluk
              og sæsonskift sommer/vinter.
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:6px">
              <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(20,184,166,0.1);color:#14b8a6;border:1px solid rgba(20,184,166,0.2)">⏸ Pause</span>
              <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(20,184,166,0.1);color:#14b8a6;border:1px solid rgba(20,184,166,0.2)">⏹ Sluk</span>
              <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(20,184,166,0.1);color:#14b8a6;border:1px solid rgba(20,184,166,0.2)">☀ Sommer</span>
              <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(20,184,166,0.1);color:#14b8a6;border:1px solid rgba(20,184,166,0.2)">❄ Vinter</span>
              <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(20,184,166,0.06);color:rgba(20,184,166,0.45);border:1px solid rgba(20,184,166,0.12)">🔥 Boost til</span>
              <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(20,184,166,0.06);color:rgba(20,184,166,0.45);border:1px solid rgba(20,184,166,0.12)">🔥 Boost slut</span>
            </div>
          </div>` : ''}

        </div>
      </div>

      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Rum &amp; klimaentiteter</div>
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
    this._patchControllerHero();
    this._patchCloudChip();
    this._startPauseCountdown();
    this._attachEvents();
  }

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
      this._tab = btn.dataset.tab;
      if (this._tab === "history" && !this._history) this._loadHistory().then(() => this._scheduleRender());
      else this._scheduleRender();
    }));
    root.querySelector("[data-action='refresh']")?.addEventListener("click", () => this._load(true));
    root.querySelector("[data-action='on']"    )?.addEventListener("click", () => this._setController("on"));
    root.querySelector("[data-action='off']"   )?.addEventListener("click", () => this._setController("off"));
    root.querySelector("[data-action='resume']")?.addEventListener("click", () => this._resume());
    root.querySelector("[data-action='pause']" )?.addEventListener("click", () => {
      const min = parseInt(root.querySelector("#pause-dur")?.value ?? "120", 10);
      this._pause(min);
    });
    // UX4: sync boost button active state from backend data on each render
    const boostBtn = root.querySelector("#ctrl-btn-boost");
    if (boostBtn) {
      const anyBoostActive = (this._data?.rooms ?? []).some(r => r.boost_active);
      boostBtn.classList.toggle("active", anyBoostActive);
    }

    // D) Boost button — toggles boost service if available
    root.querySelector("[data-action='boost']")?.addEventListener("click", async () => {
      const btn = root.querySelector("#ctrl-btn-boost");
      if (!btn) return;
      const isActive = btn.classList.contains("active");
      try {
        await this._hass.callWS({ type: isActive ? "heat_manager/boost_stop" : "heat_manager/boost_start" });
        btn.classList.toggle("active", !isActive);
        // Refresh data so room cards update
        setTimeout(() => this._load(), 300);
      } catch (e) {
        btn.style.opacity = "0.4";
        setTimeout(() => { btn.style.opacity = ""; }, 800);
        console.info("[HeatManager] boost WS failed:", e);
      }
    });
    root.querySelector("[data-action='dismiss-cloud-banner']")?.addEventListener("click", () => {
      this._showCloudBanner = false;
      this._patchCloudChip();
    });

    // Manual TRV control toggle
    root.querySelector("[data-action='toggle-manual-control']")?.addEventListener("click", () => {
      this._manualControlEnabled = !this._manualControlEnabled;
      this._scheduleRender();
    });

    // Slider live update + gradient fill
    root.querySelectorAll(".room-manual-slider").forEach(slider => {
      const updateSlider = () => {
        const min = parseFloat(slider.min), max = parseFloat(slider.max);
        const val = parseFloat(slider.value);
        const pct = ((val - min) / (max - min) * 100).toFixed(1) + "%";
        slider.style.setProperty("--pct", pct);
        const row  = slider.closest(".room-manual-row");
        const valEl = row?.querySelector(".room-manual-val");
        if (valEl) valEl.textContent = val + "°C";
      };
      updateSlider();
      slider.addEventListener("input", updateSlider);
    });

    // Send button — set_room_temp WS
    root.querySelectorAll(".room-manual-send").forEach(btn => {
      btn.addEventListener("click", async () => {
        const roomName = btn.dataset.room;
        const row      = btn.closest(".room-manual");
        const slider   = row?.querySelector(".room-manual-slider");
        const durSel   = row?.querySelector(".room-manual-dur");
        if (!slider || !roomName) return;
        const temp     = parseFloat(slider.value);
        const duration = parseInt(durSel?.value ?? "60", 10);
        btn.classList.add("sending");
        try {
          await this._hass.callWS({
            type: "heat_manager/set_room_temp",
            room_name: roomName,
            temperature: temp,
            duration_min: duration,
          });
          btn.textContent = "✓ Sendt";
          setTimeout(() => { btn.textContent = "Send ↗"; btn.classList.remove("sending"); }, 2000);
        } catch (e) {
          btn.textContent = "Fejl ✗";
          setTimeout(() => { btn.textContent = "Send ↗"; btn.classList.remove("sending"); }, 2000);
          console.error("[HeatManager] set_room_temp failed:", e);
        }
      });
    });

    // Reset button — restore to schedule
    root.querySelectorAll(".room-manual-reset").forEach(btn => {
      btn.addEventListener("click", async () => {
        const roomName = btn.dataset.room;
        if (!roomName) return;
        btn.textContent = "↺ ...";
        try {
          await this._hass.callWS({
            type: "heat_manager/set_room_temp",
            room_name: roomName,
            temperature: null,   // null = restore schedule
            duration_min: 0,
          });
          btn.textContent = "↺ OK";
        } catch (e) {
          btn.textContent = "↺ Fejl";
          console.error("[HeatManager] reset_room_temp failed:", e);
        }
        setTimeout(() => { btn.textContent = "↺ Schedule"; }, 1500);
      });
    });
    // G) History manual refresh
    root.querySelector("[data-action='refresh-history']")?.addEventListener("click", async () => {
      this._history = null;
      this._historyFetchedAt = null;
      await this._loadHistory();
      this._patchHistoryTab();
    });

    // ── Config tab inline save ────────────────────────────────────────────
    root.querySelector("[data-action='save-alarm']")?.addEventListener("click", async () => {
      const input = root.querySelector("#cfg-alarm-input");
      const ok    = root.querySelector("#cfg-alarm-ok");
      const btn   = root.querySelector("[data-action='save-alarm']");
      if (!input) return;
      btn.disabled = true;
      try {
        const res = await this._hass.callWS({
          type: "heat_manager/update_config",
          alarm_panel: input.value.trim(),
        });
        if (res?.updated !== false) {
          if (this._data?.config) this._data.config.alarm_panel = input.value.trim();
          ok.classList.add("visible");
          setTimeout(() => ok.classList.remove("visible"), 2500);
        }
      } catch(e) { console.error("Heat Manager: save alarm failed", e); }
      btn.disabled = false;
    });

    root.querySelector("[data-action='save-notify']")?.addEventListener("click", async () => {
      const input = root.querySelector("#cfg-notify-input");
      const ok    = root.querySelector("#cfg-notify-ok");
      const btn   = root.querySelector("[data-action='save-notify']");
      if (!input) return;
      btn.disabled = true;
      try {
        const res = await this._hass.callWS({
          type: "heat_manager/update_config",
          notify_service: input.value.trim(),
        });
        if (res?.updated !== false) {
          if (this._data?.config) this._data.config.notify_service = input.value.trim();
          ok.classList.add("visible");
          setTimeout(() => ok.classList.remove("visible"), 2500);
        }
      } catch(e) { console.error("Heat Manager: save notify failed", e); }
      btn.disabled = false;
    });
  }
}

if (!customElements.get("heat-manager-panel")) {
  customElements.define("heat-manager-panel", HeatManagerPanel);
}
