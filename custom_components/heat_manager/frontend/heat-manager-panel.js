// Heat Manager — sidebar panel (custom element "heat-manager-panel").
//
// Version: follows manifest.json (panel.py serves this file with the
// integration's version as cache-buster). Change history: CHANGELOG.md.
// Design: Indeklima Designer reference (DM Sans/DM Mono, section-box system,
// amber/orange heat palette).

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
    // v0.32.0: whether the header status center's detail dropdown is
    // expanded — replaces the old per-chip _showCloudBanner/_showHealthBanner
    // dismiss flags now that all three chips are one consolidated field.
    this._statusCenterOpen = false;
    this._pauseTimer      = null;  // local countdown interval
    this._boostTimer      = null;  // local boost countdown interval
    this._historyLoading  = false; // skeleton guard
    this._historyFetchedAt = null; // timestamp of last history fetch
    this._refreshing      = false; // refresh button spinner guard
    this._lastSyncTime       = null;  // UX3: timestamp of last successful WS fetch
    this._manualControlEnabled = false; // manual TRV control toggle
    // v0.67.1: room cards in the Rum tab are collapsed by default; the names
    // of the expanded ones survive the 60 s rebuild and a page reload in the
    // same browser tab (sessionStorage — a light per-viewer convenience).
    this._expandedRooms = this._loadExpandedRooms();
    this._historyFilter   = "all"; // v0.3.9: event-type filter on Historik tab
    this._toastTimer      = null;  // v0.3.9: auto-dismiss timer for toast
    // 2026-09-19 (bugfix): sections in Konfiguration default collapsed
    // (v0.57.0), but every field save previously triggered a full
    // _configTabHTML() rebuild that hardcoded every section back to
    // collapsed — clicking a toggle inside an open section made that
    // section snap shut immediately, looking like the click had done
    // nothing. Tracked by stable data-section-id (not DOM state, which a
    // rebuild always discards) and consulted when building the class list.
    this._expandedConfigSections = new Set();
  }

  set hass(h) {
    const wasNull = !this._hass;
    this._hass = h;
    if (wasNull) { this._load(); return; }
    if (!this._data) return;
    this._syncFromEntities();
    this._checkControlModeChange();
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
    // Root-level listeners (smart status line since v0.60.0; the v0.32
    // status center before it). Bound once here (not in _attachEvents(), which re-runs on every
    // full render) — shadowRoot persists across renders, so a listener
    // added there would accumulate one extra copy per render instead of
    // being replaced with the old DOM.
    // v0.33.0: the same listener also drives the info-icon tooltips (point
    // 4 — hover on PC via CSS :hover/:focus, tap on mobile via this click
    // toggle) — one shared listener instead of a second one accumulating
    // alongside it.
    if (!this._outsideClickBound) {
      this._outsideClickBound = true;
      // v0.60.0: keyboard access to the smart line's toggle and "why" rows,
      // and pausing its rotation while the pointer is over it.
      root.addEventListener("keydown", (e) => {
        if ((e.key === "Enter" || e.key === " ") && e.target.closest?.("[data-sl='toggle'], [data-sl-why]")
            && !e.target.closest?.("[data-sl-act], [data-sl-dot]")) {
          e.preventDefault();
          this._onSmartLineClick(e);
        }
      });
      root.addEventListener("mouseover", (e) => { this._slHover = !!e.target.closest?.("#smart-line"); });
      this.addEventListener("mouseleave", () => { this._slHover = false; });
      root.addEventListener("click", (e) => {
        // v0.60.0: smart status line — its innerHTML is rebuilt on every
        // patch, so all of its clicks are delegated from here (bound once).
        if (e.target.closest?.("#smart-line")) this._onSmartLineClick(e);
        const tappedIcon = e.target.closest?.(".info-icon");
        root.querySelectorAll(".info-icon.open").forEach((icon) => {
          if (icon !== tappedIcon) icon.classList.remove("open");
        });
        if (tappedIcon) {
          e.stopPropagation();
          tappedIcon.classList.toggle("open");
        }
      });
    }
    if (!root.querySelector(".panel")) {
      this._srAppendHTML(`<div class="panel"><div class="loading-wrap"><div class="loading-icon">🔥</div><div class="loading-text">Indlæser Heat Manager…</div></div></div>`);
    }
    if (this._data) this._scheduleRender();
    // 2026-09-07 audit fix (4.1, UI/UX-1): poll at the same cadence as the
    // backend's own SCAN_INTERVAL_SECONDS (60 s) — polling twice as often
    // as the coordinator ticks only ever re-fetched the same snapshot.
    // Also: never silently give up after repeated failures — that used to
    // freeze the panel on stale data with zero indication anything was
    // wrong. Polling keeps retrying forever; _patchWsErrorChip() (see
    // _load()) is what tells the user a fetch is failing.
    this._interval = setInterval(() => {
      if (document.visibilityState === "visible") this._load();
    }, 60000);
  }

  disconnectedCallback() {
    clearInterval(this._interval);
    clearInterval(this._pauseTimer);
    clearInterval(this._boostTimer);
    clearTimeout(this._pulseTimer);
    this._pulseTimer = null;
    clearTimeout(this._modeRefreshTimer);
    this._modeRefreshTimer = null;
    clearInterval(this._slTimer);
    this._slTimer = null;
    clearTimeout(this._slAckTimer);
    this._slAckTimer = null;
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

  // v0.3.9: lightweight toast for action failures/successes (boost, manual
  // TRV, config save). Previously these only logged to console.error and the
  // user saw nothing. Auto-dismisses after 4s or on click of the close button.
  _showToast(message, kind = "error") {
    const container = this.shadowRoot.querySelector("#toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${kind}`;
    toast.innerHTML = `
      <span class="toast-icon">${kind === "error" ? "⚠️" : "✅"}</span>
      <span class="toast-msg">${this._esc(message)}</span>
      <button class="toast-close" aria-label="Luk besked">✕</button>`;
    const remove = () => {
      toast.classList.add("toast-out");
      setTimeout(() => toast.remove(), 220);
    };
    toast.querySelector(".toast-close").addEventListener("click", remove);
    setTimeout(remove, 4000);
    container.appendChild(toast);
  }

  // ── Data ──────────────────────────────────────────────────────────────────

  async _load(fromRefreshBtn = false) {
    if (!this._hass || this._loadInFlight) return;
    this._loadInFlight = true;
    if (fromRefreshBtn) { this._refreshing = true; this._patchRefreshBtn(); }
    try {
      this._data     = await this._hass.callWS({ type: "heat_manager/get_state" });
      this._errCount = 0;
      this._wsError  = false;
      this._lastSyncTime = new Date();  // UX3
      // 2026-09-13: "Manuel TRV-kontrol" used to be session-scoped only (this
      // field, never read from the server) — now persisted server-side, so
      // sync it from the authoritative config snapshot on every load instead
      // of always starting at false after a page reload.
      this._manualControlEnabled = !!this._data?.config?.manual_trv_control;
    } catch (e) {
      this._errCount++;
      this._wsError = true;
      this._data = this._entitiesSnapshot();
      // Surface it — previously only console.error, indistinguishable from
      // a quiet, working panel to anyone not watching devtools.
      if (this._errCount === 1 || this._errCount % 5 === 0) {
        this._showToast(
          "Kunne ikke hente status fra Heat Manager — viser sidst kendte data",
          "error"
        );
      }
    } finally {
      this._loadInFlight = false;
      if (fromRefreshBtn) { this._refreshing = false; this._patchRefreshBtn(); }
    }
    if (this._tab === "history" && !this._history) await this._loadHistory();
    this._lastCtrlState = this._data?.controller_state ?? null;
    this._startPauseCountdown();
    this._startBoostCountdown();
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

  // B18 Fase 3: per-room offset/group-toggle entities — friendly_name
  // match (not entity_id suffix matching) since it's robust to slugify
  // transliteration of accented room names (æ/ø/å). Matches what HA
  // itself computes: has_entity_name=True + device.name == roomName +
  // entity's own _attr_name ("Offset"/"Group") combine to
  // f"{device_name} {name}" = "<room> Offset" / "<room> Group" — see
  // entity.py's _friendly_name_internal(). Capitalization matters here.
  _roomOffsetEntityId(roomName) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("number.") && states[id]?.attributes?.friendly_name === `${roomName} Offset`) return id;
    }
    return null;
  }

  _roomGroupToggleEntityId(roomName) {
    const states = this._hass?.states ?? {};
    for (const id of Object.keys(states)) {
      if (id.startsWith("switch.") && states[id]?.attributes?.friendly_name === `${roomName} Group`) return id;
    }
    return null;
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
    // 2026-09-07 audit fix (UI/UX-7): was "On/Pause/Off" here but "Varme
    // aktiv/Pause/Slukket" everywhere else on the same screen (ctrl ring,
    // controller title) — now shares _ctrlTitle()'s single Danish mapping.
    const colors = {
      on:    { bg:"rgba(251,146,60,0.2)", color:"#fed7aa", border:"#f97316" },
      pause: { bg:"rgba(234,179,8,0.15)", color:"#fef08a", border:"#ca8a04" },
      off:   { bg:"rgba(148,163,184,0.1)", color:"#94a3b8", border:"rgba(148,163,184,0.3)" },
    };
    const c = colors[ctrl] ?? colors.off;
    badge.textContent       = this._ctrlTitle(ctrl);
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
    this._patchStatusCenter(); // v0.32.0 — replaces cloud/health/ws-error chips + remote-last-action box
    this._patchHistoryTab();
    this._patchRoomsTab();    // UX2
    this._patchRefreshBtn();  // UX3
  }

  // ── Status center (v0.32.0) ──────────────────────────────────────────────
  //
  // Replaces #cloud-chip/#health-chip/#ws-error-chip (each independently
  // dismissible, each re-deriving its own "is something wrong" heuristic
  // from raw hass.states — see the 2026-09-11 statustjek history that used
  // to live here) plus the Oversigt-only #remote-last-action-box, with one
  // header field that renders the server-computed `active_issues` list
  // (websocket_payload.py's build_active_issues()) directly. The one thing that
  // still can't come from the server: a dead websocket connection can't be
  // reported *by* the server whose connection is dead, so _activeIssues()
  // injects a synthetic "Ingen forbindelse" entry client-side when
  // this._wsError is set, ahead of everything else (it's the most actionable
  // fact when true — everything else in the list is stale by definition).
  _activeIssues() {
    const issues = (this._data?.active_issues ?? []).slice();
    if (this._wsError) {
      const since = this._lastSyncTime
        ? ` — sidst OK kl. ${String(this._lastSyncTime.getHours()).padStart(2, "0")}:${String(this._lastSyncTime.getMinutes()).padStart(2, "0")}`
        : " — intet svar modtaget endnu";
      issues.unshift({
        severity: "critical",
        icon: "🔌",
        message: `Ingen forbindelse til Heat Manager${since}`,
      });
    }
    const order = { critical: 0, warning: 1, info: 2 };
    return issues.sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3));
  }

  // v0.60.0: the v0.32 status center now lives inside the smart status
  // line (see _patchSmartLine()) — kept under its old name because both
  // the full-render path and _patchAll() call it.
  _patchStatusCenter() {
    this._patchSmartLine();
  }

  // Update the version/temp/season line in the header without re-rendering topbar.
  // v0.60.1: the header's outdoor/season/weather sub-line is gone (outdoor
  // temp and weather moved into the smart line) — kept as a no-op because
  // _patchAll() still calls it.
  _patchTopbarVersion() {}

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
      const label   = this._stateLabel(state, room.override_source, false);
      const setpt   = this._roomSetpoint(room);
      const tempStr = room.current_temp != null ? (Math.round(room.current_temp * 10) / 10) + "°C" : "–";
      const battery = room.battery_level != null ? Math.round(room.battery_level) : null;
      const battStr = battery != null ? `${battery}%` : "–";
      // 2026-09-07 audit fix (UI/UX-6): low battery was only colour-coded in
      // the Rum tab — Oversigt showed the same percentage with no warning
      // colour at all, so a critically low TRV battery was easy to miss.
      const battColor = battery == null ? "" : battery <= 15 ? "var(--red)" : battery <= 30 ? "var(--amber)" : "";
      const fillPct = state === "normal" ? "100" : state === "away" ? "20" : state === "window_open" ? "50" : state === "pre_heat" ? "75" : "40";

      // Update card styles
      card.style.background = grad;
      card.style.borderLeftColor = color;
      card.className = `room-card state-${state}` + (this._remotePulseRooms().has(room.name) ? " remote-pulse" : "");

      // v0.59.0: who holds the room manual, and until when
      const info = card.querySelector(".room-override-info");
      if (info) {
        const txt = this._overrideInfoText(room);
        info.textContent = txt;
        info.hidden = !txt;
      }

      // Update pill
      const pill = card.querySelector(".room-state-pill");
      if (pill) { pill.textContent = label; pill.style.background = `${color}22`; pill.style.color = color; }

      // Update temps
      const vals = card.querySelectorAll(".room-temp-val");
      if (vals[0]) vals[0].textContent = tempStr;
      if (vals[1]) vals[1].textContent = setpt ?? "–";
      if (vals[2]) { vals[2].textContent = battStr; vals[2].style.color = battColor; }

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

      // Update blocking-sources badge (v0.9.0)
      const extraBlocking = this._roomExtraBlocking(room);
      let blk = card.querySelector(".room-blocking-badge");
      if (extraBlocking.length) {
        const title = extraBlocking.map(s => this._blockingLabel(s)).join(", ");
        const txt   = "⛔ " + this._blockingLabel(extraBlocking[0]) + (extraBlocking.length > 1 ? ` +${extraBlocking.length - 1}` : "");
        if (!blk) {
          blk = document.createElement("div");
          blk.className = "room-blocking-badge";
          card.appendChild(blk);
        }
        blk.title = title;
        blk.textContent = txt;
      } else if (blk) { blk.remove(); }

      // 2026-09-07 audit fix (5.2): "window physically open, still inside
      // the close/open delay" badge — see _roomCardHTML()'s comment.
      let wpb = card.querySelector(".room-window-pending-badge");
      if (room.windows_open && state !== "window_open") {
        if (!wpb) {
          wpb = document.createElement("div");
          wpb.className = "room-window-pending-badge";
          wpb.title = "Vindue fysisk åbent — venter på forsinkelse før varmen slås fra";
          wpb.textContent = "🪟 venter";
          card.appendChild(wpb);
        }
      } else if (wpb) { wpb.remove(); }

      // 2026-09-07 audit fix (5.2 follow-up): humidity/CO2 chip line.
      const humidityStr = room.humidity != null ? `${Math.round(room.humidity * 10) / 10}%` : null;
      const co2Str      = room.co2 != null ? `${Math.round(room.co2)} ppm` : null;
      const luxStr      = room.lux != null ? `${Math.round(room.lux)} lux` : null;
      let chips = card.querySelector(".room-extra-chips");
      if (humidityStr || co2Str || luxStr) {
        if (!chips) {
          chips = document.createElement("div");
          chips.className = "room-extra-chips";
          card.querySelector(".room-state-bar")?.insertAdjacentElement("afterend", chips);
        }
        chips.innerHTML = `${humidityStr ? `<span>💧 ${humidityStr}</span>` : ""}${co2Str ? `<span>🫧 ${co2Str}</span>` : ""}${luxStr ? `<span>☀️ ${luxStr}</span>` : ""}`;
      } else if (chips) { chips.remove(); }

      // 2026-09-07 audit fix (5.3): mold-risk badge.
      let moldBadge = card.querySelector(".room-mold-badge");
      if (room.mold_risk) {
        if (!moldBadge) {
          moldBadge = document.createElement("div");
          moldBadge.className = "room-mold-badge";
          moldBadge.title = "Høj fugt tæt på dugpunktet — risiko for skimmelvækst";
          moldBadge.textContent = "⚠️ Skimmelrisiko";
          card.appendChild(moldBadge);
        }
      } else if (moldBadge) { moldBadge.remove(); }

      // 2026-09-14 (punkt 4): combined per-room health score badge.
      let healthBadge = card.querySelector(".room-health-badge");
      if (room.health_score != null && room.health_score < 100) {
        const healthColor = room.health_label === "dårlig" ? "var(--red)" : room.health_label === "ok" ? "var(--amber)" : "var(--sub)";
        if (!healthBadge) {
          healthBadge = document.createElement("div");
          healthBadge.className = "room-health-badge";
          healthBadge.title = "Sundhedsscore — kombinerer batteri, skimmelrisiko, utilgængelige enheder og opvarmningsafvigelse";
          card.appendChild(healthBadge);
        }
        healthBadge.style.color = healthColor;
        healthBadge.textContent = `🩺 ${Math.round(room.health_score)}%`;
      } else if (healthBadge) { healthBadge.remove(); }

      // 2026-09-07 audit fix (5.6/5.9): sync-mode / schedule / TRV-count.
      const metaBadges = [];
      if (room.sync_mode && room.sync_mode !== "disabled") {
        metaBadges.push(`<span class="room-meta-badge" title="Synkroniseringstilstand">🔄 ${this._esc(this._syncModeLabel(room.sync_mode))}</span>`);
      }
      if (room.schedule_entity) {
        metaBadges.push(`<span class="room-meta-badge" title="Schedule-entity konfigureret">🗓 Schedule</span>`);
      }
      if (room.trv_count > 1) {
        metaBadges.push(`<span class="room-meta-badge" title="Antal ventiler i rummet">🔧 ${room.trv_count} ventiler</span>`);
      }
      let metaRow = card.querySelector(".room-meta-row");
      if (metaBadges.length) {
        if (!metaRow) {
          metaRow = document.createElement("div");
          metaRow.className = "room-meta-row";
          card.appendChild(metaRow);
        }
        metaRow.innerHTML = metaBadges.join("");
      } else if (metaRow) { metaRow.remove(); }
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
    // 2026-09-16 ("Sæson"-kontrol): switched from positional indexing
    // (querySelectorAll(".ctrl-meta-chip strong")[n]) to explicit
    // per-chip classes — the season chip is now a <select>, not a
    // <strong>, which would otherwise have silently shifted every
    // subsequent chip's index by one.
    const outdoorStrong = root.querySelector(".ctrl-chip-outdoor strong");
    if (outdoorStrong) outdoorStrong.textContent = otemp != null ? Math.round(otemp) + "°C" : "–";

    const seasonSelect = root.querySelector(".ctrl-season-select");
    // Never override the value while the user has the dropdown focused/open
    // — a poll landing mid-interaction shouldn't yank the selection away.
    if (seasonSelect && document.activeElement !== seasonSelect) seasonSelect.value = season;

    const statusStrong = root.querySelector(".ctrl-chip-status strong");
    if (statusStrong) {
      const eff = this._effSeasonInfo(this._data?.effective_season); // v0.3.9
      statusStrong.textContent = eff.label;
      const chipIcon = statusStrong.parentElement?.firstChild;
      if (chipIcon && chipIcon.nodeType === Node.TEXT_NODE) chipIcon.textContent = eff.icon + " ";
    }
    // 2026-09-11: 4th chip only exists in the DOM when at least one room had
    // Netatmo cloud data at last full render — see _netatmoCloudSummary().
    const netatmoStrong = root.querySelector(".ctrl-chip-netatmo strong");
    if (netatmoStrong) {
      const summary = this._netatmoCloudSummary();
      if (summary) {
        netatmoStrong.textContent = summary.label;
        const chipEl = netatmoStrong.closest(".ctrl-meta-chip");
        if (chipEl) chipEl.title = summary.title || "";
      }
    }

    // Section badge
    // 2026-09-19 (bugfix): was the unscoped ".section-box-badge" selector,
    // which matched whichever such element came first in the CURRENT tab's
    // DOM — this patch runs on every poll regardless of which tab is
    // active, so viewing Konfiguration (which now has several of its own
    // ".section-box-badge" elements — Alarmtavle, PID, etc.) meant this
    // silently overwrote e.g. Alarmtavle's "Konfigureret"/"Ikke sat" badge
    // with the controller's own status text ("Varme aktiv"). Scoped to the
    // dedicated .ctrl-status-badge class the Controller-hero's own badge
    // now carries alongside .section-box-badge (kept for shared styling).
    const badge = root.querySelector(".ctrl-status-badge");
    if (badge) {
      badge.textContent = this._ctrlTitle(ctrl);
      badge.style.background = `${ringColor}22`;
      badge.style.color = ringColor;
    }

    // v0.9.0: global blocking-sources indicator
    const blockingSrc = this._data?.blocking_sources ?? [];
    const blockingRow = root.querySelector("#ctrl-blocking-row");
    if (blockingRow) {
      blockingRow.style.display = blockingSrc.length ? "flex" : "none";
      blockingRow.textContent = blockingSrc.length
        ? "⛔ " + blockingSrc.map(s => this._blockingLabel(s)).join(", ")
        : "";
    }

    // Boost button — active state + remaining-time label, synced on every
    // refresh (not just the one-time initial render). Previously this only
    // lived in _attachEvents(), which runs exactly once at first render, so
    // a boost stopped externally (auto-expiry, heat_manager.boost_stop
    // service, another client) never visually updated the button until the
    // whole panel was reloaded.
    const boostBtn = root.querySelector("#ctrl-btn-boost");
    if (boostBtn) {
      const anyBoostActive = (this._data?.rooms ?? []).some(r => r.boost_active);
      boostBtn.classList.toggle("active", anyBoostActive);
      const remain = this._data?.boost_remaining_minutes;
      boostBtn.textContent = anyBoostActive && remain != null && remain > 0
        ? `⚡ Boost (${remain} min)`
        : "⚡ Boost";
    }
  }

  // Local boost countdown — ticks every 60 s without WS poll, mirrors
  // _startPauseCountdown() below. boost_remaining_minutes comes from the
  // coordinator's own backend auto-expiry (boost_expires_at) — this timer
  // only counts down the locally-cached copy for a smooth display between
  // the 30 s periodic _load() polls; the backend remains authoritative.
  _startBoostCountdown() {
    clearInterval(this._boostTimer);
    const anyBoostActive = (this._data?.rooms ?? []).some(r => r.boost_active);
    if (!anyBoostActive) return;
    this._boostTimer = setInterval(() => {
      const stillActive = (this._data?.rooms ?? []).some(r => r.boost_active);
      if (!this._data || !stillActive) {
        clearInterval(this._boostTimer);
        return;
      }
      if (this._data.boost_remaining_minutes > 0) {
        this._data.boost_remaining_minutes = Math.max(0, this._data.boost_remaining_minutes - 1);
      }
      this._patchControllerHero();
      if (this._data.boost_remaining_minutes === 0) clearInterval(this._boostTimer);
    }, 60000);
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
    // 2026-09-07 audit fix (4.3): don't yank the tab out from under an
    // in-progress slider drag — a poll landing mid-drag used to rebuild the
    // whole tab via innerHTML, which reset the slider's own DOM node (and
    // whatever value the user was in the middle of dragging to) on every
    // 60 s tick. Defer this rebuild; the next poll after release re-syncs.
    if (this._roomsTabDragging) return;
    // v0.66.0: same for a number field being edited — a rebuild would throw
    // away what the user is typing before they press "Gem".
    const focused = root.activeElement;
    if (focused && focused.closest?.(".rooms-detail-container")
        && focused.matches?.("input[type='number'], select")) return;
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
    // The innerHTML rebuild above drops any listeners the previous rows
    // had — re-wire the manual-control and B18 Fase 3 grouping controls.
    this._attachRoomDetailEvents();
  }

  // Manual-control slider/send/reset (existing) + B18 Fase 3 per-room
  // offset slider / group-toggle button. Extracted from _attachEvents() so
  // _patchRoomsTab() can call it again after every poll-driven rebuild of
  // .rooms-detail-container (a full innerHTML replace, which drops
  // whatever listeners were attached to the previous row elements).
  _attachRoomDetailEvents() {
    const root = this.shadowRoot;

    // v0.67.1: collapse/expand a room card (click or Enter/Space on its head).
    root.querySelectorAll(".rd-head[data-action='toggle-room']").forEach(head => {
      const toggle = () => {
        const row = head.closest(".room-detail-row");
        this._setRoomExpanded(row, !row.classList.contains("expanded"));
        this._saveExpandedRooms();
        this._updateFoldAllButton();
      };
      head.addEventListener("click", toggle);
      head.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      });
    });
    // The fold-all button lives outside the rebuilt container: wire it once.
    const foldAll = root.querySelector("#rooms-fold-all");
    if (foldAll && !foldAll.dataset.wired) {
      foldAll.dataset.wired = "1";
      foldAll.addEventListener("click", () => {
        const expand = foldAll.dataset.mode !== "collapse";
        root.querySelectorAll(".room-detail-row").forEach(row => this._setRoomExpanded(row, expand));
        this._saveExpandedRooms();
        this._updateFoldAllButton();
      });
    }
    this._updateFoldAllButton();

    // Manual-control: slider live update + gradient fill
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
      // 2026-09-07 audit fix (4.3): _patchRoomsTab() used to unconditionally
      // rebuild the whole tab via innerHTML on every poll, which could rip
      // this slider out from under the user's finger mid-drag. Track drag
      // state so the poll-driven rebuild can defer itself until release.
      slider.addEventListener("pointerdown", () => { this._roomsTabDragging = true; });
      slider.addEventListener("pointerup",   () => { this._roomsTabDragging = false; });
      slider.addEventListener("change",      () => { this._roomsTabDragging = false; });
    });

    // Manual-control: send button — set_room_temp WS
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
          setTimeout(() => { btn.textContent = "Sæt"; btn.classList.remove("sending"); }, 2000);
        } catch (e) {
          btn.textContent = "Fejl ✗";
          setTimeout(() => { btn.textContent = "Sæt"; btn.classList.remove("sending"); }, 2000);
          this._showToast(`${roomName}: kunne ikke sætte temperatur`, "error"); // v0.3.9
          console.error("[HeatManager] set_room_temp failed:", e);
        }
      });
    });

    // Manual-control: reset button — restore to schedule
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
          this._showToast(`${roomName}: kunne ikke gå tilbage til automatik`, "error"); // v0.3.9
          console.error("[HeatManager] reset_room_temp failed:", e);
        }
        setTimeout(() => { btn.textContent = "↺ Tilbage til automatik"; }, 1500);
      });
    });

    // 2026-09-07 audit fix (1.3): heat_manager.force_room_on existed as a
    // service since presence_engine.py's earliest version but had no UI
    // element calling it anywhere — advanced-users-only via Developer
    // Tools. Simple per-room button, same pattern as room-manual-reset.
    root.querySelectorAll(".room-manual-force").forEach(btn => {
      btn.addEventListener("click", async () => {
        const roomName = btn.dataset.room;
        if (!roomName) return;
        btn.textContent = "⚡ ...";
        try {
          await this._hass.callService("heat_manager", "force_room_on", {
            room_name: roomName,
          });
          btn.textContent = "⚡ OK";
        } catch (e) {
          btn.textContent = "⚡ Fejl";
          this._showToast(`${roomName}: kunne ikke tvinge varme til`, "error");
          console.error("[HeatManager] force_room_on failed:", e);
        }
        setTimeout(() => { btn.textContent = "⚡ Tving varme til"; }, 1500);
      });
    });

    // 2026-09-11: global Target Temp — send the slider's value to every
    // controllable room (climate_entity set) via the same
    // heat_manager/set_room_temp WS command the per-room "Send ↗" button
    // uses, one room at a time (sequential await, not Promise.all — see
    // _globalManualHTML()'s comment on why). Distinct #global-manual-send
    // id, not the generic .room-manual-send class-based handler above (that
    // one no-ops here since this button has no data-room).
    const globalSendBtn = root.querySelector("#global-manual-send");
    if (globalSendBtn) {
      globalSendBtn.addEventListener("click", async () => {
        const slider = root.querySelector(".global-manual-slider");
        const durSel = root.querySelector(".global-manual-dur");
        if (!slider) return;
        const temp = parseFloat(slider.value);
        const duration = parseInt(durSel?.value ?? "60", 10);
        const rooms = (this._data?.rooms ?? []).filter(r => r.climate_entity);
        if (!rooms.length) {
          this._showToast("Ingen rum med ventil at sætte", "error");
          return;
        }
        globalSendBtn.classList.add("sending");
        globalSendBtn.textContent = `Sender 0/${rooms.length}…`;
        let ok = 0;
        const failed = [];
        for (const room of rooms) {
          try {
            await this._hass.callWS({
              type: "heat_manager/set_room_temp",
              room_name: room.name,
              temperature: temp,
              duration_min: duration,
            });
            ok++;
          } catch (e) {
            failed.push(room.name);
            console.error("[HeatManager] global set_room_temp failed for", room.name, e);
          }
          globalSendBtn.textContent = `Sender ${ok + failed.length}/${rooms.length}…`;
        }
        globalSendBtn.classList.remove("sending");
        globalSendBtn.textContent = "Sæt i alle rum";
        if (failed.length) {
          this._showToast(`${ok}/${rooms.length} rum sat til ${temp}°C — fejlede: ${failed.join(", ")}`, "error");
        } else {
          this._showToast(`${ok} rum sat til ${temp}°C`, "success");
        }
      });
    }

    const globalResetBtn = root.querySelector("#global-manual-reset");
    if (globalResetBtn) {
      globalResetBtn.addEventListener("click", async () => {
        const rooms = (this._data?.rooms ?? []).filter(r => r.climate_entity);
        if (!rooms.length) return;
        globalResetBtn.classList.add("sending");
        globalResetBtn.textContent = "↺ ...";
        let ok = 0;
        const failed = [];
        for (const room of rooms) {
          try {
            await this._hass.callWS({
              type: "heat_manager/set_room_temp",
              room_name: room.name,
              temperature: null,
              duration_min: 0,
            });
            ok++;
          } catch (e) {
            failed.push(room.name);
            console.error("[HeatManager] global reset_room_temp failed for", room.name, e);
          }
        }
        globalResetBtn.classList.remove("sending");
        globalResetBtn.textContent = "↺ Alle tilbage til automatik";
        if (failed.length) {
          this._showToast(`${ok}/${rooms.length} rum gendannet — fejlede: ${failed.join(", ")}`, "error");
        } else {
          this._showToast(`${ok} rum tilbage til automatik`, "success");
        }
      });
    }

    // B18 Fase 3: per-room offset slider — live label while dragging,
    // number.set_value on release (same UX as the old global slider).
    root.querySelectorAll(".room-offset-slider").forEach(slider => {
      const updateLabel = () => {
        const val = parseFloat(slider.value);
        slider.style.setProperty("--pct", Math.max(0, Math.min(100, (val + 5) / 10 * 100)) + "%");
        const row   = slider.closest(".room-offset-row");
        const valEl = row?.querySelector(".room-offset-val");
        if (valEl) valEl.textContent = (val >= 0 ? "+" : "") + val.toFixed(1) + "°C";
      };
      updateLabel();
      slider.addEventListener("input", updateLabel);
      slider.addEventListener("pointerdown", () => { this._roomsTabDragging = true; });
      slider.addEventListener("pointerup",   () => { this._roomsTabDragging = false; });
      slider.addEventListener("change", async () => {
        this._roomsTabDragging = false; // safety net for keyboard-driven changes
        const roomName = slider.dataset.room;
        if (!roomName) return;
        const entityId = this._roomOffsetEntityId(roomName);
        if (!entityId) {
          this._showToast(`${roomName}: kunne ikke finde offset-entity`, "error");
          return;
        }
        const val = parseFloat(slider.value);
        try {
          await this._hass.callService("number", "set_value", { entity_id: entityId, value: val });
          const room = (this._data?.rooms ?? []).find(r => r.name === roomName);
          if (room) room.offset = val;
        } catch (e) {
          this._showToast(`${roomName}: kunne ikke sætte offset`, "error");
          console.error("[HeatManager] set room offset failed:", e);
        }
      });
    });

    // B18 Fase 3: per-room group toggle — switch.turn_on/turn_off on the
    // room's RoomGroupToggleSwitch.
    root.querySelectorAll("[data-action='toggle-room-group']").forEach(btn => {
      btn.addEventListener("click", async () => {
        const roomName = btn.dataset.room;
        if (!roomName) return;
        const entityId = this._roomGroupToggleEntityId(roomName);
        if (!entityId) {
          this._showToast(`${roomName}: kunne ikke finde gruppe-entity`, "error");
          return;
        }
        const turningOn = !btn.classList.contains("active");
        btn.disabled = true;
        try {
          await this._hass.callService("switch", turningOn ? "turn_on" : "turn_off", {
            entity_id: entityId,
          });
          const room = (this._data?.rooms ?? []).find(r => r.name === roomName);
          if (room) room.group_enabled = turningOn;
          this._patchRoomsTab();
        } catch (e) {
          this._showToast(`${roomName}: kunne ikke ændre gruppering`, "error");
          console.error("[HeatManager] toggle room group failed:", e);
        } finally {
          btn.disabled = false;
        }
      });
    });

    // Punkt 3 (2026-09-13): inline per-room Target temp / Away temp override
    // save — see roomCfgHTML in _roomDetailRowHTML() and ws_update_room_config()
    // in websocket.py. Same optimistic-checkmark pattern as the Indstillinger
    // tab's generic save-field handler (_attachEvents()), but scoped by
    // data-room + the button's own closest .cfg-edit-row instead of a
    // per-field id — this tab renders one such row per room, all at once, so
    // ids would collide across rooms the way _cfgNumberRow()'s don't need to.
    root.querySelectorAll("[data-action='save-room-cfg']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        // v0.66.0: one "Gem" for both per-room fields (comfort + away temp),
        // sent in a single ws_update_room_config call.
        const roomName = btn.dataset.room;
        const box      = btn.closest(".room-cfg-edit");
        const ok       = box?.querySelector(".room-cfg-ok");
        if (!box || !roomName) return;
        const payload = {};
        for (const input of box.querySelectorAll(".room-cfg-input")) {
          if (input.value === "") continue;
          const val = parseFloat(input.value);
          if (Number.isNaN(val)) {
            this._showToast("Ugyldig værdi", "error");
            return;
          }
          payload[input.dataset.field] = val;
        }
        if (!Object.keys(payload).length) return;
        btn.disabled = true;
        try {
          const res = await this._hass.callWS({
            type: "heat_manager/update_room_config",
            room_name: roomName,
            ...payload,
          });
          if (res?.updated !== false) {
            const room = (this._data?.rooms ?? []).find(r => r.name === roomName);
            if (room) Object.assign(room, payload);
            ok?.classList.add("visible");
            setTimeout(() => ok?.classList.remove("visible"), 2500);
          }
        } catch (e) {
          this._showToast(`${roomName}: kunne ikke gemme rummets indstillinger`, "error");
          console.error("[HeatManager] save room config failed for", roomName, e);
        }
        btn.disabled = false;
      });
    });
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
    // v0.3.9: keep filter chip active-state in sync.
    const filterRow = root.querySelector("#hist-filter-row");
    if (filterRow) filterRow.innerHTML = this._historyFilterChipsHTML();
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
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast("Kunne ikke ændre varme-tilstand", "error");
    }
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
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast("Kunne ikke sætte pause", "error");
    }
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
    } catch (e) {
      console.error("[HeatManager]", e);
      this._showToast("Kunne ikke genoptage varmestyring", "error");
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  _esc(s) { return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

  // State labels & colours — heat semantics
  // v0.59.0: "Normal" → "Auto" and "Override" → "Manuel", so the pill
  // itself answers "is this room automatic or manual?". withSource adds
  // who holds it manual (Rum tab); the Oversigt cards show the source on
  // their own info line instead to keep the pill short.
  _stateLabel(s, source, withSource = true) {
    if (s === "override") {
      const src = withSource ? this._overrideSourceName(source) : null;
      return src ? `Manuel · ${src}` : "Manuel";
    }
    return ({ normal:"Auto", away:"Fraværende", window_open:"Vindue åbent", pre_heat:"Forvarmning" })[s] ?? s ?? "–";
  }
  _overrideSourceName(src) {
    return ({ remote:"Fjernbetjening", panel:"Panel", switch:"Kontakt", trv:"Ventil" })[src] ?? null;
  }
  _overrideSourceIcon(src) {
    return ({ remote:"📡", panel:"🖥", switch:"🔘", trv:"🎚" })[src] ?? "✋";
  }
  // v0.65.3: Danish label for NET-TRV's netatmo_setpoint_mode, with the
  // manual setpoint's end time when Netatmo reports one. "" when the
  // attribute is missing (core netatmo) so the caller can fall back.
  _netatmoModeLabel(room) {
    const mode = room.cloud_setpoint_mode;
    if (!mode) return "";
    const label = ({
      schedule: "tidsplan",
      home:     "tidsplan",
      manual:   "manuel",
      max:      "boost",
      away:     "væk",
      hg:       "frostsikring",
      off:      "slukket",
    })[mode] ?? mode;
    const until = room.cloud_setpoint_end_time ? this._hhmm(room.cloud_setpoint_end_time) : "";
    return until && (mode === "manual" || mode === "max") ? `${label} til ${until}` : label;
  }

  // "20:42" from an ISO timestamp, in the browser's local time.
  _hhmm(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  // One line under a manual room: who holds it manual and until when.
  _overrideInfoText(room) {
    if (room?.state !== "override") return "";
    const src   = room.override_source;
    const name  = this._overrideSourceName(src) ?? "Manuel";
    const until = this._hhmm(room.override_expires_at);
    const since = this._hhmm(room.override_since);
    const parts = [`${this._overrideSourceIcon(src)} ${name}`];
    if (since) parts.push(`siden ${since}`);
    parts.push(until ? `auto igen kl. ${until}` : "uden udløb");
    return parts.join(" · ");
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

  // v0.9.0: self-reporting diagnostics — short Danish tags for the neutral
  // blocking_sources codes the backend sends (coordinator.get_room_blocking_sources).
  _blockingLabel(src) {
    return ({
      controller_off:   "Controller slukket",
      controller_pause: "Controller pause",
      window:           "Vindue åbent",
      presence:         "Fraværende",
    })[src] ?? src;
  }

  // v0.9.0: Konfiguration tab — read-only display label for a room's sync
  // mode (the config-flow wizard remains the way to actually set this).
  _syncModeLabel(mode) {
    return ({ disabled: "Deaktiveret", mirror: "Spejl", lock: "Lås" })[mode] ?? mode;
  }

  // Per-room blocking sources, minus whatever the room's own state pill
  // already communicates (window_open/away) — surfaces only the otherwise
  // invisible controller-level reasons on the room card itself.
  _roomExtraBlocking(room) {
    const src = room.blocking_sources ?? [];
    return src.filter(s => {
      if (s === "window" && room.state === "window_open") return false;
      if (s === "presence" && room.state === "away") return false;
      return true;
    });
  }

  // v0.3.9: event-type metadata for the Historik filter chips + hist-dot colour.
  // Covers every event_type written via coordinator.log_event() across the
  // engines (normal, away, window_open, override, boost, manual).
  _eventTypeInfo(type) {
    return ({
      all:         { label: "Alle",     color: "#94a3b8" },
      normal:      { label: "Normal",   color: "#f97316" },
      away:        { label: "Fravær",   color: "#64748b" },
      window_open: { label: "Vindue",   color: "#ef4444" },
      boost:       { label: "Boost",    color: "#c084fc" },
      manual:      { label: "Manuel",   color: "#0ea5e9" },
      override:    { label: "Override", color: "#a855f7" },
      // 2026-09-11 door feature: interior door open/close events, logged by
      // DoorEngine with event_type="door" — kept separate from window_open
      // (an interior door has no heat-suppression meaning, see
      // engine/door_engine.py) so the "Vindue" filter isn't diluted with
      // unrelated internal door traffic.
      door:        { label: "Dør",      color: "#14b8a6" },
    })[type] ?? { label: type ?? "–", color: "#64748b" };
  }

  // Filter chip row for the Historik tab. Active filter highlighted with its
  // own colour; click handling lives in _attachEvents().
  _historyFilterChipsHTML() {
    const types = ["all","normal","away","window_open","door","boost","manual","override"];
    return types.map(t => {
      const info   = this._eventTypeInfo(t);
      const active = this._historyFilter === t;
      const style  = active
        ? `background:${info.color}22;color:${info.color};border-color:${info.color}66`
        : "";
      return `<button class="hist-filter-chip${active ? " active" : ""}" data-filter="${t}" style="${style}">${info.label}</button>`;
    }).join("");
  }

  _ctrlIcon(s) { return ({ on:"🔥", pause:"⏸", off:"❄️" })[s] ?? "●"; }
  _ctrlTitle(s) { return ({ on:"Varme aktiv", pause:"Pause", off:"Slukket" })[s] ?? s; }

  // v0.3.9: effective_season (dormant/waking/active) → label + icon + colour.
  // Used for the controller-hero meta-chip and the auto-off "Effektiv sæson"
  // card. Distinct from calendar_season/season_mode (winter/spring/...).
  _effSeasonInfo(season) {
    return ({
      dormant: { label: "Dvale",     icon: "😴", color: "#64748b" },
      waking:  { label: "Opvågning", icon: "🌅", color: "#eab308" },
      active:  { label: "Aktiv",      icon: "🔥", color: "#f97316" },
    })[season] ?? { label: "–", icon: "•", color: "#64748b" };
  }

  // 2026-09-11: house-level rollup of the same cloud_preset_mode/
  // cloud_selected_schedule fields _roomDetailRowHTML() already shows per
  // room (see netatmoHTML there). null when no room has Netatmo cloud data
  // at all (Zigbee-only setup); { label, title } otherwise — title is only
  // set (and non-empty) when rooms disagree, so the chip can flag "Blandet"
  // rather than silently picking one room's value and presenting it as the
  // whole house's state.
  _netatmoCloudSummary() {
    const rooms = (this._data?.rooms ?? []).filter(
      r => r.cloud_preset_mode || r.cloud_selected_schedule
    );
    if (!rooms.length) return null;
    const modes  = [...new Set(rooms.map(r => r.cloud_preset_mode).filter(Boolean))];
    const scheds = [...new Set(rooms.map(r => r.cloud_selected_schedule).filter(Boolean))];
    if (modes.length > 1 || scheds.length > 1) {
      const detail = rooms
        .map(r => `${r.name}: ${r.cloud_preset_mode ?? "–"}${r.cloud_selected_schedule ? ` (${r.cloud_selected_schedule})` : ""}`)
        .join(", ");
      return { label: "Blandet", title: detail };
    }
    const mode  = modes[0] ?? "–";
    const sched = scheds[0];
    return { label: `${mode}${sched ? ` (${sched})` : ""}`, title: "" };
  }

  // v0.3.9 (B15): small pill showing which TRV protocol a room uses.
  // room.trv_type comes from websocket.py's get_state room payload.
  _trvBadgeHTML(trvType, netatmoBackend = null) {
    const info = ({
      netatmo: { label: "Netatmo", color: "#0ea5e9" },
      zigbee:  { label: "Zigbee",  color: "#22c55e" },
    })[trvType] ?? { label: trvType ?? "–", color: "#64748b" };
    // v0.67.7: which integration owns the Netatmo valve (detected per valve
    // from the entity registry) — "Netatmo · NET-TRV" / "Netatmo · core".
    if (trvType === "netatmo" && netatmoBackend) {
      const backend = ({ net_trv: "NET-TRV", netatmo: "core" })[netatmoBackend];
      if (backend) info.label = `Netatmo · ${backend}`;
    }
    return `<span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;background:${info.color}1f;color:${info.color}">${info.label}</span>`;
  }

  _climateTemp(id) {
    const t = this._hass?.states?.[id]?.attributes?.current_temperature;
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }
  _climateSetpoint(id) {
    const t = this._hass?.states?.[id]?.attributes?.temperature;
    return t != null ? (Math.round(t * 10) / 10) + "°C" : null;
  }

  // Fase 2 (2026-09-11): Heat Manager's own resolved target (comfort_temp +
  // schedule_override + room_offset + setback — coordinator.
  // get_room_target_temp()) is the authoritative "Target Temp" value. Before
  // this, "Target Temp" read the cloud climate entity's own live 'temperature'
  // attribute via _climateSetpoint() — after the B21 fix (PID no longer
  // writes comfort_temp to that entity for Netatmo rooms) that attribute no
  // longer reflects what Heat Manager is actually asking for, so leaving
  // this unchanged would have silently reintroduced exactly the confusion
  // B21 fixed, just moved into the panel. See
  // audit/heat_manager_target_temp_analysis_2026-09-11.md. Falls back to
  // the old live-cloud-read only if target_temp is unexpectedly absent
  // (e.g. an older backend payload during a rolling update).
  _roomSetpoint(room) {
    if (room?.target_temp != null) {
      return (Math.round(room.target_temp * 10) / 10) + "°C";
    }
    return room?.climate_entity ? this._climateSetpoint(room.climate_entity) : null;
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
      .panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; position: relative; }
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

      /* ── Toast notifications (v0.3.9) ── */
      .toast-container {
        position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%);
        display: flex; flex-direction: column; gap: 6px; z-index: 50;
        width: calc(100% - 28px); max-width: 420px;
        align-items: center; pointer-events: none;
      }
      .toast {
        display: flex; align-items: center; gap: 8px; width: 100%;
        background: var(--bg2); border: 1px solid var(--div); border-left-width: 3px;
        border-radius: 10px; padding: 9px 12px; font-size: 12px; color: var(--text);
        box-shadow: 0 6px 20px rgba(0,0,0,0.35);
        pointer-events: auto; animation: toast-in .2s ease-out;
      }
      .toast-error   { border-left-color: var(--red); }
      .toast-success { border-left-color: var(--green); }
      .toast-msg  { flex: 1; line-height: 1.4; }
      .toast-close {
        background: none; border: none; color: var(--sub); cursor: pointer;
        font-size: 11px; padding: 2px 4px; line-height: 1;
      }
      .toast-out { animation: toast-out .2s ease-in forwards; }
      @keyframes toast-in  { from { opacity:0; transform: translateY(8px); } to { opacity:1; transform: translateY(0); } }
      @keyframes toast-out { from { opacity:1; transform: translateY(0); } to { opacity:0; transform: translateY(8px); } }

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
      .header-text { flex-shrink: 0; }
      .header-text .topbar-badge { margin-top: 5px; }
      .header-refresh {
        margin-left: auto;
        background: var(--bg2); border: 1px solid var(--div);
        color: var(--sub); padding: 7px 13px; border-radius: 10px;
        cursor: pointer; font-size: 13px; font-family: 'DM Sans', sans-serif;
        transition: all .2s;
      }
      .header-refresh:hover { color: var(--amber); border-color: var(--amber); }
      .app-version {
        margin-left: 10px; font-size: 10px; color: var(--sub);
        font-family: 'DM Mono', monospace; letter-spacing: 0.3px;
        opacity: 0.7; flex-shrink: 0;
      }

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
      /* 2026-09-19 ("panel fylder mindre") — Konfiguration-fanen lægges i to
         kolonner på bred skærm, så sektionerne (de fleste nu sammenfoldet som
         standard, se .section-box.collapsed nedenfor) ikke bruger dobbelt så
         meget lodret plads som nødvendigt. Ét-kolonne på smal skærm/mobil.
         align-items:start forhindrer grid'et i at strække korte bokse til
         samme højde som en længere nabo-boks i samme række. Kun brugt af
         _configTabHTML() — andre faners section-box'e står udenfor dette
         wrapper-element og forbliver én kolonne. */
      .config-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
        align-items: start;
      }
      @media (max-width: 760px) {
        .config-grid { grid-template-columns: 1fr; }
      }
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
        box-sizing: border-box; min-height: 44px;
        border-bottom: 1px solid rgba(148,163,184,0.12);
        background: rgba(0,0,0,0.18);
      }
      /* Punkt 5 (2026-09-14) — sammenklappelige sektioner (Konfiguration-fanen).
         Collapsed state lives purely as a .collapsed class on the .section-box
         itself, toggled by clicking a .collapsible header — no per-section id
         or persisted state needed; resets on next full render of the tab. */
      .section-box-header.collapsible { cursor: pointer; user-select: none; }
      .section-box-header.collapsible:hover { background: rgba(0,0,0,0.28); }
      .section-box-header.collapsible::after {
        content: "▾"; margin-left: auto; flex-shrink: 0;
        color: var(--sub); font-size: 11px;
        transition: transform .2s;
      }
      .section-box.collapsed .section-box-header.collapsible::after { transform: rotate(-90deg); }
      /* 2026-09-19 (endelig tredelt struktur): titel+badge (header) og den
         nye altid-synlige bund-beskrivelse (.section-box-footer) er begge
         undtaget fra sammenfoldnings-skjulningen — kun selve
         indstillingerne imellem dem (toggle/number-rækker, evt. længere
         introtekst) skjules. */
      .section-box.collapsed > *:not(.section-box-header):not(.section-box-footer) { display: none !important; }
      .section-box-title {
        font-size: 11px; font-weight: 600;
        text-transform: uppercase; letter-spacing: 1px;
        color: var(--sub); flex: 1; min-width: 0;
      }
      /* 2026-09-19: altid-synlig kort beskrivelse i BUNDEN af hver sektion,
         adskilt fra titlen — titlen står nu alene i headeren (grøn/i brugerens
         illustration), selve indstillingerne er den sammenfoldelige midte
         (rød), og denne footer er den altid-synlige bund (blå). Erstatter
         den tidligere .section-box-desc, som sad lige under titlen. */
      .section-box-footer {
        font-size: 12px; color: var(--sub); line-height: 1.5;
        padding: 10px 16px;
        box-sizing: border-box; min-height: 74px; /* = 3 linjer, så alle sektioner fylder lige meget foldet sammen */
        border-top: 1px solid rgba(148,163,184,0.12);
      }
      .section-box-badge {
        font-size: 9px; font-weight: 700;
        padding: 2px 7px; border-radius: 4px;
        letter-spacing: 0.5px; text-transform: uppercase;
      }
      .section-box-body { padding: 14px 16px; }

      /* Manual TRV control */
      .room-manual {
        padding: 10px 16px 12px;
        background: rgba(99,102,241,0.06);
        border-top: 1px solid rgba(99,102,241,0.15);
      }
      .room-manual-row {
        display: flex; align-items: center; gap: 8px;
      }
      /* B18 Fase 3: per-room grouping box — orange tint, matches the
         offset slider's colour (was the global Controller-section slider). */
      .room-grouping {
        padding: 10px 16px 12px;
        background: rgba(249,115,22,0.05);
        border-top: 1px solid rgba(249,115,22,0.15);
      }
      .room-manual-lbl {
        font-size: 11px; color: var(--sub); width: 72px; flex-shrink: 0;
      }
      /* v0.66.0: room detail card — named sections, stat tiles, rows */
      .rd-sec {
        display: flex; align-items: center; gap: 8px;
        font-size: 10px; font-weight: 700; color: var(--sub);
        text-transform: uppercase; letter-spacing: .08em;
        margin: 14px 0 6px;
      }
      .rd-sec::after { content: ""; flex: 1; border-top: 1px solid var(--div); }
      .rd-grid {
        display: grid; gap: 6px;
        grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      }
      .rd-stat { background: var(--bg3); border-radius: 8px; padding: 7px 10px; min-width: 0; }
      .rd-stat-l { font-size: 10px; color: var(--sub); }
      .rd-stat-v { font-size: 16px; font-weight: 600; font-family: 'DM Mono', monospace; color: var(--text); margin-top: 1px; }
      .rd-stat-s { font-size: 10px; color: var(--sub); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .rd-row { display: flex; align-items: center; gap: 8px; min-height: 24px; font-size: 12px; }
      .rd-row-l { flex: 0 0 150px; color: var(--sub); font-size: 11px; }
      .rd-row-v { color: var(--text); }
      .rd-bar { flex: 1; height: 4px; background: var(--bg3); border-radius: 2px; overflow: hidden; }
      .rd-bar > div { height: 100%; border-radius: 2px; transition: width .4s; }
      .rd-unit { font-size: 11px; color: var(--sub); }
      .rd-note { font-size: 11px; color: var(--amber); margin: 2px 0 4px 158px; line-height: 1.4; }
      .rd-warn { font-size: 11px; color: var(--red); margin: 4px 0; line-height: 1.4; }
      /* v0.67.1: collapsible room cards */
      .rd-head {
        display: flex; align-items: center; justify-content: space-between;
        gap: 8px; margin-bottom: 4px; cursor: pointer; user-select: none;
        border-radius: 6px;
      }
      .rd-head:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px; }
      .rd-chevron {
        display: inline-block; width: 12px; color: var(--sub); font-size: 16px;
        line-height: 1; transition: transform .2s;
      }
      .room-detail-row.expanded .rd-chevron { transform: rotate(90deg); }
      .room-detail-row:not(.expanded) .rd-body { display: none; }
      .room-detail-row.expanded .rd-summary { display: none; }
      .rd-summary {
        font-size: 12px; color: var(--sub); padding-left: 18px;
        display: flex; flex-wrap: wrap; align-items: center; gap: 2px 0;
      }
      .rd-summary b { color: var(--text); font-weight: 600; font-family: 'DM Mono', monospace; }
      .rd-dot { margin: 0 6px; opacity: .6; }
      .rd-fold-all {
        background: transparent; border: 1px solid var(--div); color: var(--sub);
        font: inherit; font-size: 11px; padding: 3px 10px; border-radius: 6px; cursor: pointer;
      }
      .rd-fold-all:hover { color: var(--text); border-color: rgba(148,163,184,0.28); }
      .alarm-state-chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .rd-badge-sensor {
        font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 4px;
        background: var(--bg3); color: var(--sub); letter-spacing: .04em;
      }
      .room-cfg-edit .rd-row { min-height: 38px; }
      .room-cfg-edit .cfg-edit-input { width: 80px; flex: 0 0 80px; }
      @media (max-width: 600px) {
        .room-manual-row { flex-wrap: wrap; row-gap: 6px; }
        .room-manual-row .room-manual-lbl:empty { display: none; }
        .rd-row-l { flex-basis: 120px; }
        .rd-note { margin-left: 0; }
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
      .room-manual-force {
        padding: 5px 10px; border-radius: 7px; border: 1px solid rgba(245,158,11,0.4);
        background: rgba(245,158,11,0.1); color: #f59e0b;
        font-size: 11px; font-weight: 600; cursor: pointer;
        font-family: 'DM Sans', sans-serif; white-space: nowrap;
        transition: background .15s;
      }
      .room-manual-force:hover { background: rgba(245,158,11,0.2); }

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
      /* 2026-09-16 ("Sæson"-kontrol) — styled to look like the plain
         <strong> text it replaces, but with a subtle chevron so it still
         reads as clickable/interactive rather than static. */
      .ctrl-season-select {
        appearance: none; -webkit-appearance: none;
        background: transparent;
        border: none;
        color: var(--text); font-family: inherit; font-size: 12px; font-weight: 600;
        padding: 0 14px 0 0;
        margin: 0;
        cursor: pointer;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2394a3b8' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right center;
      }
      .ctrl-season-select:hover { color: #f97316; }
      .ctrl-season-select option { background: var(--bg2); color: var(--text); }
      .ctrl-blocking-row {
        align-items: center; gap: 5px; margin-top: 8px;
        font-size: 11px; font-weight: 600; color: #fca5a5;
      }

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
      /* B18 Fase 3: per-room offset slider (Rum-fanen — was the global
         Controller-section slider pre-Fase-3, same look, now scoped to
         one room's row instead of a singleton). */
      .room-offset-row { display: flex; align-items: center; gap: 8px; }
      .room-offset-label { font-size: 11px; color: var(--sub); width: 52px; flex-shrink: 0; }
      .room-offset-slider {
        flex: 1; -webkit-appearance: none; appearance: none;
        height: 4px; border-radius: 2px;
        background: linear-gradient(to right, #f97316 var(--pct,50%), var(--bg3) var(--pct,50%));
        outline: none; cursor: pointer;
      }
      .room-offset-slider::-webkit-slider-thumb {
        -webkit-appearance: none; width: 14px; height: 14px;
        border-radius: 50%; background: #fb923c;
        border: 2px solid var(--bg2); cursor: pointer;
      }
      .room-offset-val {
        font-size: 12px; font-weight: 600; font-family: 'DM Mono', monospace;
        color: #fb923c; width: 44px; text-align: right; flex-shrink: 0;
      }
      .room-group-row {
        display: flex; align-items: center; justify-content: space-between; gap: 8px;
      }
      .room-group-lbl { font-size: 11px; color: var(--sub); }
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
      /* Punkt 4 (2026-09-14) — combined per-room health score badge, only
         shown when below 100 (a fully healthy room adds no extra badge). */
      .room-health-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 5px; margin-top: 5px;
        background: rgba(148,163,184,0.12);
      }
      /* ── v0.60.0: smart status line (replaces status center + mode bar) ──
         One tone per state; every tone sets --sl (accent) and --sl-rgb. */
      .sl {
        --sl: #10b981; --sl-rgb: 16,185,129;
        position: relative;
        /* v0.60.1: sits in the header row between title and refresh */
        flex: 1 1 auto; min-width: 0; margin: 0 6px;
        border-radius: 14px;
        border: 1px solid rgba(var(--sl-rgb),0.45);
        /* v0.67.7: solid base under the tinted gradient — a theme with a
           translucent background colour made the line see-through. */
        background-color: #0f1923;
        background-image:
          linear-gradient(135deg, rgba(var(--sl-rgb),0.16) 0%, rgba(var(--sl-rgb),0.04) 100%),
          linear-gradient(var(--bg), var(--bg));
        transition: background .35s, border-color .35s;
      }
      .sl.tone-manual   { --sl: #c084fc; --sl-rgb: 168,85,247; }
      .sl.tone-warning  { --sl: #f59e0b; --sl-rgb: 245,158,11; }
      .sl.tone-critical { --sl: #f87171; --sl-rgb: 239,68,68; }
      .sl.tone-ack      { --sl: #38bdf8; --sl-rgb: 14,165,233; }
      .sl.tone-pause    { --sl: #facc15; --sl-rgb: 234,179,8; }
      .sl.tone-off      { --sl: #94a3b8; --sl-rgb: 148,163,184; }
      .sl.ack { animation: hm-remote-pulse 1.2s ease-out 2; }
      .sl-main {
        display: flex; align-items: center; gap: 12px;
        padding: 9px 12px; cursor: pointer; border-radius: 14px;
      }
      .sl-main:focus-visible { outline: 2px solid var(--sl); outline-offset: 2px; }
      .sl-tile {
        position: relative; flex: 0 0 44px; width: 44px; height: 44px;
        border-radius: 12px; display: flex; align-items: center; justify-content: center;
        background: rgba(var(--sl-rgb),0.16); color: var(--sl); font-size: 19px;
      }
      .sl-ring { position: absolute; inset: 0; width: 44px; height: 44px; }
      .sl-ring-track { stroke: rgba(var(--sl-rgb),0.25); }
      .sl-ring-fill { stroke: var(--sl); transition: stroke-dashoffset .6s ease; }
      .sl-icon { position: relative; line-height: 1; }
      .sl-body { flex: 1 1 auto; min-width: 0; animation: sl-in .35s ease; }
      @keyframes sl-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
      .sl-title {
        font-size: 15px; font-weight: 600; color: var(--sl); line-height: 1.3;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .sl.tone-ok .sl-title { color: var(--text); }
      .sl-sub {
        display: flex; flex-wrap: wrap; gap: 2px 14px; margin-top: 3px;
        font-size: 12px; color: var(--sub); line-height: 1.4;
      }
      .sl-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
      .sl-btn {
        font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap;
        padding: 6px 12px; border-radius: 20px;
        background: var(--bg2); color: var(--sl);
        border: 1px solid rgba(var(--sl-rgb),0.45);
        transition: background .15s;
      }
      .sl-btn:hover { background: rgba(var(--sl-rgb),0.18); }
      .sl-btn.act-release { color: var(--green); border-color: rgba(16,185,129,0.5); }
      .sl-btn.small { padding: 3px 10px; font-size: 11px; color: var(--sub); border-color: var(--div); }
      .sl-dots { display: flex; gap: 5px; padding: 0 2px; }
      .sl-dot {
        width: 7px; height: 7px; padding: 0; border-radius: 50%; border: none; cursor: pointer;
        background: rgba(148,163,184,0.35);
      }
      .sl-dot.on { background: var(--sl); }
      .sl-chev { display: flex; align-items: center; gap: 6px; color: var(--sub); font-size: 12px; }
      .sl-badge {
        font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 10px;
        background: rgba(245,158,11,0.2); color: #f59e0b;
      }
      /* Folds out OVER the page (like the v0.32 dropdown did) so the tabs
         and the scroll area below never jump when it opens. */
      .sl-detail {
        position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 30;
        max-height: min(70vh, 640px); overflow-y: auto;
        /* v0.67.7: solid base — var(--bg2) comes from the HA theme and can be
           translucent, which let the page show through the open dropdown. */
        background-color: #1a2535;
        background-image: linear-gradient(var(--bg2), var(--bg2));
        border: 1px solid rgba(var(--sl-rgb),0.45);
        border-radius: 14px; box-shadow: 0 12px 32px rgba(0,0,0,0.6);
        padding: 8px 16px 14px;
        display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 4px 28px;
      }
      .sl-detail[hidden] { display: none; }
      .sl-sec-title {
        font-size: 11px; font-weight: 700; color: var(--sub);
        text-transform: uppercase; letter-spacing: .08em; margin: 8px 0 4px;
      }
      .sl-sec-hint { font-weight: 400; text-transform: none; letter-spacing: 0; opacity: .7; margin-left: 6px; }
      .sl-row {
        display: flex; align-items: center; gap: 8px; font-size: 12px;
        padding: 6px 0; border-top: 1px solid var(--div);
      }
      .sl-row-icon { flex-shrink: 0; width: 18px; text-align: center; }
      .sl-row-text { flex: 1 1 auto; min-width: 0; color: var(--text); line-height: 1.35; }
      .sl-row-meta { color: var(--sub); white-space: nowrap; font-family: 'DM Mono', monospace; font-size: 11px; }
      .sl-row.sev-critical .sl-row-text { color: #f87171; }
      .sl-row.sev-warning .sl-row-text  { color: #f59e0b; }
      .sl-row.snoozed { opacity: .55; }
      .sl-time { min-width: 38px; }
      .sl-empty { font-size: 12px; color: var(--sub); padding: 6px 0; border-top: 1px solid var(--div); }
      .sl-why { padding: 6px 0; border-top: 1px solid var(--div); cursor: pointer; font-size: 12px; }
      .sl-why-head { display: flex; gap: 10px; align-items: baseline; }
      .sl-why-name { font-weight: 600; color: var(--text); min-width: 90px; }
      .sl-why-short { color: var(--sub); }
      .sl-why.tone-manual .sl-why-short  { color: #c084fc; }
      .sl-why.tone-warning .sl-why-short { color: #f59e0b; }
      .sl-why.tone-info .sl-why-short    { color: #38bdf8; }
      .sl-why-long { margin: 5px 0 2px 100px; color: var(--sub); line-height: 1.45; }
      .room-card.remote-pulse { animation: hm-remote-pulse 1.2s ease-out 3; }
      @keyframes hm-remote-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(14,165,233,0.55); }
        100% { box-shadow: 0 0 0 10px rgba(14,165,233,0); }
      }
      @media (prefers-reduced-motion: reduce) {
        .sl.ack, .room-card.remote-pulse, .sl-body { animation: none; }
        .room-card.remote-pulse { outline: 2px solid var(--teal); }
      }
      .room-override-info {
        font-size: 11px; font-weight: 600; color: #c084fc;
        margin: 2px 0 6px; line-height: 1.35;
      }
      .room-override-info[hidden] { display: none; }
      @media (max-width: 760px) {
        .header { flex-wrap: wrap; }
        .header .sl { order: 10; flex-basis: 100%; margin: 2px 0 0; }
      }
      @media (max-width: 600px) {
        .sl-main { flex-wrap: wrap; }
        .sl-body { flex-basis: calc(100% - 60px); }
        .sl-title { white-space: normal; }
        .sl-actions { width: 100%; justify-content: flex-start; padding-left: 56px; }
        .sl-why-long { margin-left: 0; }
        .sl-chev { position: absolute; top: 14px; right: 12px; }
        .sl-body { padding-right: 18px; }
      }
      .room-boost-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 5px;
        background: rgba(168,85,247,0.15); color: #c084fc;
        text-transform: uppercase; letter-spacing: 0.4px;
      }
      .room-blocking-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 5px; margin-top: 5px;
        background: rgba(239,68,68,0.12); color: #fca5a5;
        text-transform: uppercase; letter-spacing: 0.4px;
      }
      .room-window-pending-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 5px; margin-top: 5px;
        background: rgba(14,165,233,0.12); color: #7dd3fc;
        text-transform: uppercase; letter-spacing: 0.4px;
      }

      /* 2026-09-07 audit fix (5.2/5.3/5.6/5.9): humidity/CO2 chips, mold-risk
         badge, and the sync/schedule/TRV-count meta row on Oversigt cards. */
      .room-extra-chips {
        display: flex; gap: 8px; margin-top: 6px;
        font-size: 10px; color: var(--sub);
      }
      .room-mold-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 700;
        padding: 2px 6px; border-radius: 5px; margin-top: 5px;
        background: rgba(217,119,6,0.14); color: #fbbf24;
        text-transform: uppercase; letter-spacing: 0.4px;
      }
      .room-meta-row {
        display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;
      }
      .room-meta-badge {
        display: inline-flex; align-items: center; gap: 3px;
        font-size: 9px; font-weight: 600;
        padding: 2px 6px; border-radius: 5px;
        background: rgba(148,163,184,0.12); color: var(--sub);
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
        display: grid; grid-template-columns: repeat(6,1fr);
        gap: 8px; padding: 0 16px 14px;
      }
      @media (max-width: 700px) { .qs-grid { grid-template-columns: repeat(3,1fr); } }
      @media (max-width: 380px) { .qs-grid { grid-template-columns: repeat(2,1fr); } }
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
        display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-bottom: 8px;
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

      /* ── History filter chips (v0.3.9) ── */
      .hist-filter-row {
        display: flex; gap: 6px; flex-wrap: wrap;
        padding: 0 16px 10px;
      }
      .hist-filter-chip {
        font-size: 10px; font-weight: 600; padding: 4px 9px;
        border-radius: 999px; border: 1px solid var(--div);
        background: transparent; color: var(--sub);
        cursor: pointer; transition: background .15s, color .15s, border-color .15s;
      }
      .hist-filter-chip:hover:not(.active) { background: rgba(255,255,255,0.04); }

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

      /* ── Info tooltip icon (v0.33.0, point 4) ──
         Hover/focus reveal the popover on desktop via CSS alone; the shared
         outside-click listener (connectedCallback()) toggles .open for tap
         support on mobile — see _infoIcon() for the markup. */
      .info-icon {
        position: relative;
        display: inline-flex; align-items: center; justify-content: center;
        margin-left: 5px;
        width: 14px; height: 14px;
        border-radius: 50%;
        font-size: 11px; line-height: 1; font-style: normal;
        color: var(--sub);
        cursor: help;
        vertical-align: middle;
        outline: none;
      }
      .info-icon:hover, .info-icon:focus { color: #818cf8; }
      .info-popover {
        position: absolute; z-index: 30;
        bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
        width: 220px;
        background: var(--bg2); border: 1px solid var(--div);
        border-radius: 8px; padding: 8px 10px;
        font-size: 11px; font-weight: 400; line-height: 1.4;
        color: var(--fg); text-align: left; white-space: normal;
        box-shadow: 0 8px 20px rgba(0,0,0,0.4);
        visibility: hidden; opacity: 0;
        transition: opacity .12s;
        pointer-events: none;
      }
      .info-icon:hover .info-popover,
      .info-icon:focus .info-popover,
      .info-icon.open .info-popover {
        visibility: visible; opacity: 1;
      }

      /* ── Config edit rows ── */
      .cfg-edit-row {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 16px 10px;
      }
      /* 2026-09-19 — always-visible description under a number row's
         label/input line, matching _cfgToggleRow's own desc styling
         exactly (same font-size/color/line-height). */
      .cfg-edit-row-wrap .cfg-edit-row { padding-bottom: 2px; }
      .cfg-edit-desc {
        font-size: 11px; color: var(--sub); line-height: 1.4;
        padding: 0 16px 10px;
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

  // NB: a client-side _cloudStatus() used to live here, re-deriving Netatmo
  // cloud/gateway health from raw hass.states for #cloud-chip/#health-chip.
  // Removed in v0.32.0 — the same algorithm now runs once, server-side, in
  // websocket_payload.py's build_active_issues(), which the new status center
  // reads via `active_issues` (see _activeIssues()/_patchStatusCenter()
  // above). A full-width _cloudBannerHTML() was already removed here
  // earlier (2026-09, superseded by the topbar chips this removes in turn).

  _topbarHTML() {
    const d      = this._data;
    const ctrl   = d?.controller_state ?? "unknown";
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
          <!-- v0.60.1: controller badge moved under the title (was beside
               the status field); the old outdoor/season/weather sub-line is
               gone — outdoor temp and weather now live in the smart line,
               season in the Controller section. -->
          <div id="topbar-badge" class="topbar-badge"
            style="background:${bc.bg};color:${bc.color};border-color:${bc.border}">
            <div class="badge-dot" style="background:${bc.color}"></div>
            ${this._ctrlTitle(ctrl)}
          </div>
        </div>
        ${this._smartLineHTML()}
        <button class="header-refresh" data-action="refresh">↻ Opdater</button>
        <div class="app-version" title="Heat Manager integration version">v${this._esc(d?.version ?? "–")}</div>
      </div>
      <div class="tabs" role="tablist">${[
        { id:"overview", label:"Oversigt"  },
        { id:"rooms",    label:"Rum"       },
        { id:"history",  label:"Historik"  },
        { id:"config",   label:"Konfiguration" },
      ].map(t => `<button class="tab${this._tab===t.id?" active":""}" data-tab="${t.id}" role="tab" aria-selected="${this._tab===t.id}">${t.label}</button>`).join("")}</div>`;
  }

  _controllerSectionHTML() {
    const ctrl      = this._data?.controller_state ?? "unknown";
    const season    = this._data?.season_mode ?? "auto";
    const otemp     = this._data?.outdoor_temp;
    const pauseLeft = this._data?.pause_remaining ?? 0;
    const showPause = ctrl === "pause" && pauseLeft > 0;
    const eff       = this._effSeasonInfo(this._data?.effective_season); // v0.3.9
    // 2026-09-11: Flemming asked for the same "Netatmo: manual (Vinter)"
    // info the room-detail rows already show (netatmoHTML in
    // _roomDetailRowHTML — cloud_preset_mode + cloud_selected_schedule)
    // surfaced once at house level too, not just per room. A Netatmo Home
    // has exactly one active schedule, so in the normal case every Netatmo
    // room agrees — this only disagrees mid-transition (one room's cloud
    // state hasn't polled through yet) or if a room's preset was flipped
    // individually via its own select.<room>_netatmo_preset_mode entity.
    const netatmoSummary = this._netatmoCloudSummary();

    // Ring: fully lit = ON (amber), half = PAUSE (yellow), empty = OFF (grey)
    const r          = 38;
    const circ       = 2 * Math.PI * r;
    const fill       = ctrl === "on" ? circ : ctrl === "pause" ? circ * 0.5 : 0;
    const dashOffset = circ - fill;
    const ringColor  = ctrl === "on" ? "#f97316" : ctrl === "pause" ? "#eab308" : "#475569";

    // v0.9.0: blocking-sources indicator. B18 Fase 3 removed the old
    // global group_offset here — offset/group controls are per-room now,
    // see _roomDetailRowHTML().
    const blockingSrc  = this._data?.blocking_sources ?? [];

    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Controller</div>
          <div class="section-box-badge ctrl-status-badge" style="background:${ringColor}22;color:${ringColor}">
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
            <div class="ctrl-blocking-row" id="ctrl-blocking-row" style="display:${blockingSrc.length ? "flex" : "none"}">⛔ ${this._esc(blockingSrc.map(s => this._blockingLabel(s)).join(", "))}</div>
            <div class="ctrl-meta-row">
              <div class="ctrl-meta-chip ctrl-chip-outdoor">
                🌡️ <span>Ude</span>
                <strong>${otemp != null ? Math.round(otemp) + "°C" : "–"}</strong>
              </div>
              <div class="ctrl-meta-chip ctrl-chip-season">
                🍂 <span>Sæson</span>
                <select class="ctrl-season-select" data-action="change-season-mode" title="Skift sæsontilstand manuelt — Auto lader Heat Manager selv styre skiftet">
                  <option value="auto" ${season === "auto" ? "selected" : ""}>Auto</option>
                  <option value="winter" ${season === "winter" ? "selected" : ""}>Vinter</option>
                  <option value="spring" ${season === "spring" ? "selected" : ""}>Forår</option>
                  <option value="summer" ${season === "summer" ? "selected" : ""}>Sommer</option>
                  <option value="autumn" ${season === "autumn" ? "selected" : ""}>Efterår</option>
                </select>
              </div>
              <div class="ctrl-meta-chip ctrl-chip-status">
                ${eff.icon} <span>Status</span>
                <strong>${eff.label}</strong>
              </div>
              ${netatmoSummary ? `
              <div class="ctrl-meta-chip ctrl-chip-netatmo" ${netatmoSummary.title ? `title="${this._esc(netatmoSummary.title)}"` : ""}>
                🛰️ <span>Netatmo</span>
                <strong>${this._esc(netatmoSummary.label)}</strong>
              </div>` : ""}
            </div>
          </div>
        </div>

        <div class="ctrl-btns-wrap">
          <div class="ctrl-btn-row">
            <button id="ctrl-btn-on"    class="ctrl-btn" data-action="on">🔥 Tænd</button>
            <button id="ctrl-btn-pause" class="ctrl-btn" data-action="pause">⏸ Pause</button>
            <button id="ctrl-btn-off"   class="ctrl-btn" data-action="off">❄️ Sluk</button>
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

  // ── v0.60.0: smart status line ───────────────────────────────────────────
  //
  // One line under the header replaces both the v0.32 status center and the
  // v0.59 mode bar. It always shows the single most important thing right
  // now as a plain-language sentence, with a tile (icon, or a countdown ring
  // when something will end on its own), a sub-line with context and
  // forecasts, and the actions that make sense for exactly that situation.
  // Several things at once → the line rotates every 6 s (paused on hover);
  // critical problems are pinned and never rotate away. A remote press is
  // acknowledged for 10 s with what was done and which rooms were skipped.
  // Clicking the line folds out everything: manual rooms, warnings (with
  // "hide for 1 hour"), a plain-language "why" for every room, and the
  // latest events.

  _smartLineHTML() {
    return `
      <div id="smart-line" class="sl tone-ok">
        <div class="sl-main" data-sl="toggle" role="button" tabindex="0" aria-expanded="false" aria-live="polite"></div>
        <div class="sl-detail" hidden></div>
      </div>`;
  }

  // "1 t 22 min" / "22 min" / "under 1 min"
  _durText(ms) {
    const min = Math.max(0, Math.round(ms / 60000));
    if (min < 1) return "under 1 min";
    const h = Math.floor(min / 60), m = min % 60;
    return h ? (m ? `${h} t ${m} min` : `${h} t`) : `${m} min`;
  }

  _fmtTemp(v) {
    return v == null || isNaN(v) ? "–" : `${(Math.round(v * 10) / 10).toString().replace(".", ",")}°`;
  }

  // Forecast for the room furthest from its target that is still heating:
  // learned heat-up rate (°C/h, CalibrationEngine) → "Stue når 21,5° ca. kl. 19:40".
  _heatupForecast() {
    let best = null;
    for (const r of this._data?.rooms ?? []) {
      if (!r.climate_entity || r.state !== "normal") continue;
      const cur = r.current_temp, tgt = r.target_temp;
      if (cur == null || tgt == null || tgt - cur < 0.3) continue;
      const rate = r.heatup_rate_door_closed ?? r.heatup_rate_door_open;
      if (!rate || rate <= 0) continue;
      const etaMs = ((tgt - cur) / rate) * 3600000;
      if (etaMs > 12 * 3600000) continue;
      if (!best || etaMs > best.etaMs) best = { room: r, etaMs };
    }
    if (!best) return null;
    const at = new Date(Date.now() + best.etaMs);
    return `${best.room.name} når ${this._fmtTemp(best.room.target_temp)} ca. kl. ${this._hhmm(at.toISOString())}`;
  }

  // "Natsænkning om 3 t 40 min" / "Natsænkning til kl. 07:00" (within 12 h).
  _nightSetbackText() {
    const cfg = this._data?.config ?? {};
    if (!cfg.night_setback_enabled) return null;
    const start = Number(cfg.night_start_hour), end = Number(cfg.night_end_hour);
    if (isNaN(start) || isNaN(end)) return null;
    const now = new Date();
    const h = now.getHours() + now.getMinutes() / 60;
    const inNight = start > end ? (h >= start || h < end) : (h >= start && h < end);
    if (inNight) return `Natsænkning til kl. ${String(end).padStart(2, "0")}:00`;
    const next = new Date(now);
    next.setHours(start, 0, 0, 0);
    if (next <= now) next.setDate(next.getDate() + 1);
    const ms = next - now;
    return ms <= 12 * 3600000 ? `Natsænkning om ${this._durText(ms)}` : null;
  }

  _roomStateWord(state) {
    return ({ window_open: "vindue åbent", away: "fraværende", pre_heat: "forvarmning" })[state] ?? state;
  }

  // Plain-language "why" for one room — short line + longer explanation.
  _roomWhy(room) {
    const st = room.state ?? "normal";
    const blocking = room.blocking_sources ?? [];
    const cur = room.current_temp, tgt = room.target_temp;
    const temps = `${this._fmtTemp(cur)} → ${this._fmtTemp(tgt)}`;
    const valve = room.valve_position != null ? Math.round(room.valve_position) : null;
    const facts = [];
    if (cur != null) facts.push(`rum ${this._fmtTemp(cur)}`);
    if (tgt != null) facts.push(`mål ${this._fmtTemp(tgt)}`);
    if (valve != null) facts.push(`ventil ${valve}%`);
    if (room.pid_power != null) facts.push(`PID ${Math.round(room.pid_power)}%`);
    const factLine = facts.join(" · ");
    if (!room.climate_entity) {
      return { tone: "muted", short: "Kun måling — ingen radiator styres her", long: "Rummet har ingen termostat i Heat Manager, så det måles kun." };
    }
    if (blocking.includes("controller_off")) {
      return { tone: "muted", short: "Varmen er slukket for hele huset", long: `Controlleren står på Sluk. ${factLine}` };
    }
    if (blocking.includes("controller_pause")) {
      return { tone: "muted", short: "Hele huset er på pause", long: `Controlleren står på Pause og fortsætter af sig selv. ${factLine}` };
    }
    if (st === "window_open") {
      return { tone: "warning", short: "Varmen sænket — vindue åbent", long: `Et vindue er åbent, så varmen er sænket. Den kommer igen, når vinduet har været lukket i den indstillede forsinkelse. ${factLine}` };
    }
    if (st === "away") {
      return { tone: "muted", short: "Fraværstemperatur — ingen hjemme", long: `Alle er væk, så rummet holdes på fraværstemperatur. Det varmes op igen, når nogen kommer hjem. ${factLine}` };
    }
    if (st === "pre_heat") {
      return { tone: "info", short: "Forvarmer — nogen er på vej hjem", long: `Rummet varmes op før ankomst ud fra rejsetiden hjem. ${factLine}` };
    }
    if (st === "override") {
      const src = this._overrideSourceName(room.override_source) ?? "manuel ændring";
      const until = this._hhmm(room.override_expires_at);
      return { tone: "manual", short: `Manuel via ${src.toLowerCase()} — ${until ? `auto igen kl. ${until}` : "uden udløb"}`, long: `Automatikken styrer ikke rummet lige nu, fordi det er sat manuelt via ${src.toLowerCase()}. ${until ? `Det går selv tilbage til automatik kl. ${until}.` : "Det bliver manuelt, indtil nogen sætter det tilbage."} ${factLine}` };
    }
    if (room.boost_active) {
      return { tone: "info", short: "Boost — kører på boost-temperatur", long: `Boost er aktivt og stopper af sig selv. ${factLine}` };
    }
    if (cur != null && tgt != null && tgt - cur >= 0.3) {
      const rate = room.heatup_rate_door_closed ?? room.heatup_rate_door_open;
      const eta = rate > 0 ? ` · ca. kl. ${this._hhmm(new Date(Date.now() + ((tgt - cur) / rate) * 3600000).toISOString())}` : "";
      return { tone: "ok", short: `Varmer op: ${temps}${eta}`, long: `Rummet er under målet, så radiatoren åbner. ${factLine}` };
    }
    if (cur != null && tgt != null && cur - tgt >= 0.5) {
      return { tone: "ok", short: `Over mål (${temps}) — radiatoren holder igen`, long: `Rummet er varmere end målet, så der varmes ikke lige nu. ${factLine}` };
    }
    return { tone: "ok", short: `På mål: ${this._fmtTemp(cur ?? tgt)}`, long: `Rummet holder sin temperatur. ${factLine}` };
  }

  // Acknowledgement of a remote press within the last 10 s, or null.
  _remoteAckMessage() {
    const age = this._remoteActionAgeMs();
    const rla = this._data?.remote_last_action;
    if (age == null || age >= 10000 || !rla) return null;
    const n = rla.rooms?.length ?? 0;
    const roomsTxt = `${n} rum`;
    const d = rla.delta != null ? `${rla.delta > 0 ? "+" : "−"}${String(Math.abs(rla.delta)).replace(".", ",")}°` : null;
    const title = ({
      temp_up:   `${d ?? "Op"} modtaget · sendt til ${roomsTxt}`,
      temp_down: `${d ?? "Ned"} modtaget · sendt til ${roomsTxt}`,
      manual:    `Manuel styring slået til i ${roomsTxt}`,
      auto:      `Automatik slået til igen i ${roomsTxt}`,
      boost:     `Boost startet i ${roomsTxt}`,
      release:   `Alle rum tilbage på automatik (${roomsTxt})`,
    })[rla.action] ?? "Fjernbetjening modtaget";
    const subs = [`📡 Fjernbetjening · kl. ${this._hhmm(rla.timestamp)}`];
    const skipped = Object.entries(rla.skipped ?? {});
    if (skipped.length) {
      subs.push(`Sprunget over: ${skipped.map(([room, st]) => `${room} (${this._roomStateWord(st)})`).join(", ")}`);
    }
    return { key: `ack:${rla.timestamp}`, tone: "ack", icon: "✓", title, subs, actions: [] };
  }

  // Every message that could be shown, most important first.
  _smartMessages() {
    const d = this._data ?? {};
    const rooms = d.rooms ?? [];
    const issues = this._activeIssues();
    const msgs = [];
    const issueSubs = (issue) => {
      const subs = [];
      if (issue.id?.startsWith("window_open")) {
        const lowered = rooms.filter(r => r.state === "window_open").map(r => r.name);
        if (lowered.length) subs.push(`Varmen er sænket i ${lowered.join(", ")}`);
        else subs.push("Varmen sænkes, hvis det bliver ved");
      } else if (issue.id?.startsWith("mold_risk")) {
        subs.push("Luft ud i 5–10 min og hold temperaturen jævn");
      } else if (issue.id?.startsWith("heatup_anomaly")) {
        subs.push("Tjek at ventilen ikke sidder fast");
      } else if (issue.id?.startsWith("cloud")) {
        subs.push("Rum med lokal (HomeKit/Zigbee) styring kører videre");
      } else if (issue.id?.startsWith("entities_unavailable")) {
        subs.push("Se rummets sensorer under Rum-fanen");
      }
      return subs;
    };

    for (const issue of issues.filter(i => i.severity === "critical")) {
      msgs.push({ key: `issue:${issue.id ?? issue.message}`, tone: "critical", icon: issue.icon ?? "!", title: issue.message, subs: issueSubs(issue), actions: [], pinned: true });
    }

    const ctrl = d.controller_state;
    if (ctrl === "off") {
      msgs.push({ key: "ctrl:off", tone: "off", icon: "⏻", title: "Varmen er slukket for hele huset", subs: ["Tænd under Controller for at starte automatikken igen"], actions: [] });
    } else if (ctrl === "pause") {
      const left = d.pause_remaining ?? 0;
      msgs.push({ key: "ctrl:pause", tone: "pause", icon: "⏸", title: `Varmen er sat på pause${left ? ` · ${this._durText(left * 60000)} tilbage` : ""}`, subs: ["Fortsætter af sig selv bagefter"], actions: [] });
    }

    for (const issue of issues.filter(i => i.severity === "warning" && !i.snoozed)) {
      msgs.push({ key: `issue:${issue.id ?? issue.message}`, tone: "warning", icon: issue.icon ?? "!", title: issue.message, subs: issueSubs(issue), actions: issue.id ? [{ act: "snooze", id: issue.id, label: "🔕 Skjul 1 t" }] : [] });
    }

    const manual = rooms.filter(r => r.state === "override");
    if (manual.length) {
      const controllable = rooms.filter(r => r.climate_entity).length || rooms.length;
      const exp = manual.map(r => r.override_expires_at ? Date.parse(r.override_expires_at) : NaN);
      const allExp = exp.every(t => !isNaN(t));
      const last = allExp ? Math.max(...exp) : NaN;
      const countTxt = manual.length >= controllable ? "Manuel i alle rum" : `Manuel i ${manual.length} af ${controllable} rum`;
      const title = allExp ? `${countTxt} · auto igen om ${this._durText(last - Date.now())}` : `${countTxt} · uden udløb`;
      const sources = [...new Set(manual.map(r => r.override_source))];
      const since = manual.map(r => r.override_since ? Date.parse(r.override_since) : NaN).filter(t => !isNaN(t));
      const firstSince = since.length ? Math.min(...since) : NaN;
      const srcTxt = sources.map(s => (this._overrideSourceName(s) ?? "manuel ændring").toLowerCase()).join(" og ");
      const subs = [manual.map(r => r.name).join(", "), `sat via ${srcTxt}${!isNaN(firstSince) ? ` kl. ${this._hhmm(new Date(firstSince).toISOString())}` : ""}`];
      let ring = null;
      if (allExp && !isNaN(firstSince) && last > firstSince) {
        ring = Math.min(1, Math.max(0, (last - Date.now()) / (last - firstSince)));
      }
      const actions = [];
      if (exp.some(t => !isNaN(t))) actions.push({ act: "extend", label: "+1 time" });
      actions.push({ act: "release", label: "Auto nu" });
      msgs.push({ key: "manual", tone: "manual", icon: this._overrideSourceIcon(sources.length === 1 ? sources[0] : null), title, subs, actions, ring });
    }

    const boostLeft = d.boost_remaining_minutes ?? 0;
    if (boostLeft > 0) {
      const total = Number(d.config?.boost_default_minutes) || 0;
      const boosted = rooms.filter(r => r.boost_active).map(r => r.name);
      msgs.push({ key: "boost", tone: "ack", icon: "⚡", title: `Boost aktivt · ${this._durText(boostLeft * 60000)} tilbage`, subs: boosted.length ? [boosted.join(", ")] : [], actions: [], ring: total > 0 ? Math.min(1, boostLeft / total) : null });
    }

    if (!msgs.length) {
      const heating = rooms.filter(r => r.climate_entity && r.valve_position != null && r.valve_position > 0).length;
      const subs = [];
      const fc = this._heatupForecast();
      if (fc) subs.push(`🕒 ${fc}`);
      const night = this._nightSetbackText();
      if (night) subs.push(`🌙 ${night}`);
      // Outdoor temp + weather moved here from the header sub-line (v0.60.1).
      // 6.0 m/s mirrors const.py's WIND_FAST_MS — keep in sync if that changes.
      const wx = [d.precipitation > 0 ? "🌧️ regn" : null, d.wind_speed != null && d.wind_speed >= 6.0 ? "💨 blæst" : null].filter(Boolean);
      if (d.outdoor_temp != null) subs.push(`🌡 Ude ${this._fmtTemp(d.outdoor_temp)}${wx.length ? ` · ${wx.join(" · ")}` : ""}`);
      msgs.push({ key: "ok", tone: "ok", icon: "✓", title: heating ? `Alt kører automatisk · ${heating} rum varmer op` : "Alt kører automatisk · alle rum er på mål", subs, actions: [] });
    }
    return msgs;
  }

  _slRingSVG(fraction, tone) {
    const c = 119.38;
    const off = (c * (1 - fraction)).toFixed(1);
    return `<svg class="sl-ring" viewBox="0 0 44 44" aria-hidden="true">
      <circle cx="22" cy="22" r="19" fill="none" class="sl-ring-track" stroke-width="3"/>
      <circle cx="22" cy="22" r="19" fill="none" class="sl-ring-fill tone-${tone}" stroke-width="3" stroke-linecap="round"
        stroke-dasharray="${c}" stroke-dashoffset="${off}" transform="rotate(-90 22 22)"/>
    </svg>`;
  }

  _patchSmartLine() {
    const box = this.shadowRoot.querySelector("#smart-line");
    if (!box) return;
    const ack = this._remoteAckMessage();
    const msgs = this._smartMessages();
    const pinned = msgs.filter(m => m.pinned);
    const pool = ack ? [ack] : (pinned.length ? pinned : msgs);
    const sig = pool.map(m => m.key).join("|");
    if (sig !== this._slSig) { this._slSig = sig; this._slIndex = 0; }
    if (this._slIndex >= pool.length) this._slIndex = 0;
    const m = pool[this._slIndex];

    box.className = `sl tone-${m.tone}${this._slOpen ? " open" : ""}${ack ? " ack" : ""}`;
    const main = box.querySelector(".sl-main");
    main.setAttribute("aria-expanded", String(!!this._slOpen));
    const tile = `<div class="sl-tile">${m.ring != null ? this._slRingSVG(m.ring, m.tone) : ""}<span class="sl-icon">${this._esc(m.icon)}</span></div>`;
    const subs = m.subs?.length ? `<div class="sl-sub">${m.subs.map(s => `<span>${this._esc(s)}</span>`).join("")}</div>` : "";
    const actions = (m.actions ?? []).map(a =>
      `<button class="sl-btn act-${a.act}" data-sl-act="${a.act}"${a.id ? ` data-sl-id="${this._esc(a.id)}"` : ""}>${this._esc(a.label)}</button>`).join("");
    const dots = pool.length > 1
      ? `<div class="sl-dots">${pool.map((_, i) => `<button class="sl-dot${i === this._slIndex ? " on" : ""}" data-sl-dot="${i}" aria-label="Besked ${i + 1} af ${pool.length}"></button>`).join("")}</div>`
      : "";
    const others = this._activeIssues().filter(i => i.severity !== "info").length;
    main.innerHTML = `${tile}
      <div class="sl-body"><div class="sl-title">${this._esc(m.title)}</div>${subs}</div>
      ${actions ? `<div class="sl-actions">${actions}</div>` : ""}
      ${dots}
      <span class="sl-chev" aria-hidden="true">${others && !this._slOpen ? `<span class="sl-badge">${others}</span>` : ""}${this._slOpen ? "▴" : "▾"}</span>`;

    const detail = box.querySelector(".sl-detail");
    detail.hidden = !this._slOpen;
    if (this._slOpen) detail.innerHTML = this._smartDetailHTML();

    this._startSmartRotation(pool.length > 1 && !ack);
    if (ack) this._scheduleAckEnd();
  }

  _smartDetailHTML() {
    const d = this._data ?? {};
    const rooms = d.rooms ?? [];
    const sections = [];

    const manual = rooms.filter(r => r.state === "override");
    if (manual.length) {
      sections.push(`<div class="sl-sec"><div class="sl-sec-title">Styring</div>${manual.map(r => {
        const since = this._hhmm(r.override_since), until = this._hhmm(r.override_expires_at);
        return `<div class="sl-row"><span class="sl-row-icon">${this._overrideSourceIcon(r.override_source)}</span>
          <span class="sl-row-text">${this._esc(r.name)} · ${this._esc((this._overrideSourceName(r.override_source) ?? "manuel ændring").toLowerCase())}</span>
          <span class="sl-row-meta">${since ? `siden ${since} · ` : ""}${until ? `auto ${until}` : "uden udløb"}</span></div>`;
      }).join("")}</div>`);
    }

    const issues = this._activeIssues().filter(i => i.severity !== "info");
    sections.push(`<div class="sl-sec"><div class="sl-sec-title">Advarsler</div>${issues.length ? issues.map(i => `
      <div class="sl-row sev-${i.severity}${i.snoozed ? " snoozed" : ""}">
        <span class="sl-row-icon">${this._esc(i.icon ?? "!")}</span>
        <span class="sl-row-text">${this._esc(i.message)}</span>
        ${i.snoozed
          ? `<span class="sl-row-meta">skjult til ${this._hhmm(i.snoozed_until) ?? ""}</span><button class="sl-btn small" data-sl-act="unsnooze" data-sl-id="${this._esc(i.id)}">Vis</button>`
          : (i.severity === "warning" && i.id ? `<button class="sl-btn small" data-sl-act="snooze" data-sl-id="${this._esc(i.id)}">Skjul 1 t</button>` : "")}
      </div>`).join("") : `<div class="sl-empty">Ingen advarsler 🎉</div>`}</div>`);

    sections.push(`<div class="sl-sec"><div class="sl-sec-title">Hvorfor — rum for rum <span class="sl-sec-hint">klik for detaljer</span></div>${rooms.map(r => {
      const why = this._roomWhy(r);
      const open = this._slWhyOpen?.has(r.name);
      return `<div class="sl-why tone-${why.tone}${open ? " open" : ""}" data-sl-why="${this._esc(r.name)}" role="button" tabindex="0" aria-expanded="${open}">
        <div class="sl-why-head"><span class="sl-why-name">${this._esc(r.name)}</span><span class="sl-why-short">${this._esc(why.short)}</span></div>
        ${open ? `<div class="sl-why-long">${this._esc(why.long)}</div>` : ""}
      </div>`;
    }).join("")}</div>`);

    const events = (this._slEvents ?? []).slice(0, 5);
    sections.push(`<div class="sl-sec"><div class="sl-sec-title">Seneste</div>${events.length ? events.map(e => `
      <div class="sl-row"><span class="sl-row-meta sl-time">${this._esc(e.time ?? "")}</span><span class="sl-row-text">${this._esc(e.description ?? "")}</span></div>`).join("")
      : `<div class="sl-empty">${this._slEventsLoading ? "Henter…" : "Ingen hændelser endnu"}</div>`}</div>`);

    return sections.join("");
  }

  async _loadSmartEvents() {
    if (this._slEventsLoading) return;
    if (this._slEventsAt && Date.now() - this._slEventsAt < 60000) return;
    this._slEventsLoading = true;
    try {
      const res = await this._hass.callWS({ type: "heat_manager/get_history", days: 1 });
      const events = (res?.events ?? []).slice();
      events.sort((a, b) => (Date.parse(b.timestamp) || 0) - (Date.parse(a.timestamp) || 0));
      this._slEvents = events;
      this._slEventsAt = Date.now();
    } catch (e) {
      this._slEvents = this._slEvents ?? [];
    } finally {
      this._slEventsLoading = false;
    }
    this._patchSmartLine();
  }

  _startSmartRotation(enabled) {
    if (!enabled) {
      clearInterval(this._slTimer);
      this._slTimer = null;
      return;
    }
    if (this._slTimer) return;
    this._slTimer = setInterval(() => {
      if (this._slHover || this._slOpen) return;
      this._slIndex = (this._slIndex ?? 0) + 1;
      this._patchSmartLine();
    }, 6000);
  }

  _scheduleAckEnd() {
    if (this._slAckTimer) return;
    const remaining = 10000 - (this._remoteActionAgeMs() ?? 10000) + 200;
    this._slAckTimer = setTimeout(() => {
      this._slAckTimer = null;
      this._patchSmartLine();
    }, Math.max(remaining, 200));
  }

  // Delegated clicks on the smart line — bound once in connectedCallback,
  // since the line's innerHTML is rebuilt on every patch.
  async _onSmartLineClick(e) {
    const actBtn = e.target.closest?.("[data-sl-act]");
    if (actBtn) {
      e.stopPropagation();
      const act = actBtn.dataset.slAct, id = actBtn.dataset.slId;
      try {
        if (act === "release") {
          await this._releaseOverrides();
          return;
        }
        if (act === "extend") {
          const res = await this._hass.callWS({ type: "heat_manager/extend_overrides", minutes: 60 });
          this._showToast(res?.rooms_extended?.length ? "Manuel styring forlænget med 1 time" : "Intet at forlænge", "success");
        } else if (act === "snooze" || act === "unsnooze") {
          await this._hass.callWS({ type: "heat_manager/snooze_issue", issue_id: id, minutes: act === "snooze" ? 60 : 0 });
          this._showToast(act === "snooze" ? "Skjult i 1 time" : "Vises igen", "success");
        }
      } catch (err) {
        this._showToast("Det lykkedes ikke — prøv igen", "error");
      }
      this._load();
      return;
    }
    const dot = e.target.closest?.("[data-sl-dot]");
    if (dot) {
      e.stopPropagation();
      this._slIndex = Number(dot.dataset.slDot) || 0;
      this._patchSmartLine();
      return;
    }
    const why = e.target.closest?.("[data-sl-why]");
    if (why) {
      this._slWhyOpen = this._slWhyOpen ?? new Set();
      const name = why.dataset.slWhy;
      if (this._slWhyOpen.has(name)) this._slWhyOpen.delete(name); else this._slWhyOpen.add(name);
      this._patchSmartLine();
      return;
    }
    if (e.target.closest?.("[data-sl='toggle']")) {
      this._slOpen = !this._slOpen;
      this._patchSmartLine();
      if (this._slOpen) this._loadSmartEvents();
    }
  }

  // Age of the remote's last action in ms, or null. Allows a little clock
  // skew between HA and the browser.
  _remoteActionAgeMs() {
    const ts = this._data?.remote_last_action?.timestamp;
    const t = ts ? Date.parse(ts) : NaN;
    if (isNaN(t)) return null;
    const age = Date.now() - t;
    return age > -60000 ? Math.max(age, 0) : null;
  }

  _remotePulseActive() {
    const age = this._remoteActionAgeMs();
    return age != null && age < 15000;
  }

  _remotePulseRooms() {
    if (!this._remotePulseActive()) return new Set();
    return new Set(this._data?.remote_last_action?.rooms ?? []);
  }

  // Re-patch once the pulse window has passed so the room highlight goes
  // away without waiting for the next 60 s poll.
  _schedulePulseEnd() {
    if (this._pulseTimer || !this._remotePulseActive()) return;
    const remaining = 15000 - (this._remoteActionAgeMs() ?? 15000) + 250;
    this._pulseTimer = setTimeout(() => {
      this._pulseTimer = null;
      this._patchSmartLine();
      this._patchRooms();
    }, Math.max(remaining, 250));
  }

  // set hass() runs on every HA state change; the Hub "Control mode" and
  // "Status" sensors change whenever a room enters/leaves manual, a window
  // opens, boost/pause starts or the remote acts. Re-fetch right away
  // (debounced) instead of waiting up to 60 s for the next poll.
  _checkControlModeChange() {
    const states = this._hass?.states ?? {};
    // Look the entities up once they exist; while they don't (hass not set
    // yet, or an older backend without them) retry at most every 30 s
    // rather than scanning every state on every hass update.
    if (!this._controlModeEntityId && Date.now() >= (this._controlModeRetryAt ?? 0)) {
      this._controlModeEntityId = Object.keys(states).find(id =>
        id.startsWith("sensor.") && states[id]?.attributes?.override_sources !== undefined
          && Array.isArray(states[id]?.attributes?.manual_rooms)) ?? null;
      this._houseStatusEntityId = Object.keys(states).find(id =>
        id.startsWith("sensor.") && Array.isArray(states[id]?.attributes?.window_rooms)
          && states[id]?.attributes?.boost_remaining_min !== undefined) ?? null;
      if (!this._controlModeEntityId && this._hass) this._controlModeRetryAt = Date.now() + 30000;
    }
    const st = this._controlModeEntityId ? states[this._controlModeEntityId] : null;
    if (!st) return;
    const hs = this._houseStatusEntityId ? states[this._houseStatusEntityId] : null;
    const sig = st.state + "|" + JSON.stringify(st.attributes?.manual_rooms ?? [])
      + "|" + JSON.stringify(st.attributes?.override_sources ?? {})
      + "|" + JSON.stringify(st.attributes?.override_expires_at ?? {})
      + "|" + (st.attributes?.remote_last_action_at ?? "")
      + "|" + (hs ? hs.state + JSON.stringify(hs.attributes?.window_rooms ?? []) : "");
    if (this._controlModeSig === undefined) { this._controlModeSig = sig; return; }
    if (sig === this._controlModeSig) return;
    this._controlModeSig = sig;
    clearTimeout(this._modeRefreshTimer);
    this._modeRefreshTimer = setTimeout(() => {
      this._modeRefreshTimer = null;
      this._load();
    }, 500);
  }

  async _releaseOverrides() {
    try {
      const res = await this._hass.callWS({ type: "heat_manager/release_overrides" });
      const n = res?.rooms_released?.length ?? 0;
      this._showToast(n ? `${n} rum tilbage på automatik` : "Alle rum kører allerede automatisk", "success");
    } catch (e) {
      this._showToast("Kunne ikke sætte rummene tilbage på automatik", "error");
    }
    this._load();
  }

  // Build a single room card HTML string (with data-room-id for surgical patching).
  _roomCardHTML(room) {
    const state    = room.state ?? "normal";
    const color    = this._stateColor(state);
    const grad     = this._stateGradient(state);
    const label    = this._stateLabel(state, room.override_source, false);
    const overrideInfo = this._overrideInfoText(room);
    const pulseCls = this._remotePulseRooms().has(room.name) ? " remote-pulse" : "";
    const setpt    = this._roomSetpoint(room);
    const tempStr  = room.current_temp != null ? (Math.round(room.current_temp * 10) / 10) + "°C" : "–";
    const battery  = room.battery_level != null ? Math.round(room.battery_level) : null;
    const battStr  = battery != null ? `${battery}%` : "–";
    const battColor = battery == null ? "" : battery <= 15 ? "var(--red)" : battery <= 30 ? "var(--amber)" : "";
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
    // v0.9.0: blocking-sources badge (controller_off/controller_pause only —
    // window/presence are already shown via the state pill)
    const extraBlocking = this._roomExtraBlocking(room);
    const blockingBadge = extraBlocking.length
      ? `<div class="room-blocking-badge" title="${this._esc(extraBlocking.map(s => this._blockingLabel(s)).join(", "))}">⛔ ${this._esc(this._blockingLabel(extraBlocking[0]))}${extraBlocking.length > 1 ? ` +${extraBlocking.length - 1}` : ""}</div>`
      : "";
    // 2026-09-07 audit fix (5.2): `windows_open` (the raw sensor reading)
    // was already in the payload but never shown — a window physically
    // open during the configured close/open delay looked identical to a
    // fully closed one until the state pill actually flipped to
    // "Vindue åbent". Only shown for that in-between case.
    const windowPendingBadge = room.windows_open && state !== "window_open"
      ? `<div class="room-window-pending-badge" title="Vindue fysisk åbent — venter på forsinkelse før varmen slås fra">🪟 venter</div>`
      : "";
    // 2026-09-07 audit fix (5.2 follow-up): humidity/CO2 were already in the
    // payload (used by the Rum-detaljer tab) but never shown on the
    // Oversigt cards — same slim chip line, just here too.
    const humidityStr = room.humidity != null ? `${Math.round(room.humidity * 10) / 10}%` : null;
    const co2Str      = room.co2 != null ? `${Math.round(room.co2)} ppm` : null;
    const luxStr      = room.lux != null ? `${Math.round(room.lux)} lux` : null;
    const extraChips  = (humidityStr || co2Str || luxStr)
      ? `<div class="room-extra-chips">${humidityStr ? `<span>💧 ${humidityStr}</span>` : ""}${co2Str ? `<span>🫧 ${co2Str}</span>` : ""}${luxStr ? `<span>☀️ ${luxStr}</span>` : ""}</div>`
      : "";
    // 2026-09-07 audit fix (5.3): mold-risk badge (see websocket.py comment
    // at the mold_risk field for the algorithm).
    const moldBadge = room.mold_risk
      ? `<div class="room-mold-badge" title="Høj fugt tæt på dugpunktet — risiko for skimmelvækst">⚠️ Skimmelrisiko</div>`
      : "";
    // 2026-09-14 (punkt 4) — combined per-room health score, only shown
    // when it's below 100 so a fully healthy room stays badge-free.
    const healthColor = room.health_label === "dårlig" ? "var(--red)" : room.health_label === "ok" ? "var(--amber)" : "var(--sub)";
    const healthBadge = (room.health_score != null && room.health_score < 100)
      ? `<div class="room-health-badge" style="color:${healthColor}" title="Sundhedsscore — kombinerer batteri, skimmelrisiko, utilgængelige enheder og opvarmningsafvigelse">🩺 ${Math.round(room.health_score)}%</div>`
      : "";
    // 2026-09-07 audit fix (5.6/5.9): sync-mode, schedule and multi-TRV were
    // already in the payload (Rum-detaljer tab, config-only fields) but
    // absent from Oversigt — grouped into one compact meta row so they
    // don't push the valve/blocking badges further down the card.
    const metaBadges = [];
    if (room.sync_mode && room.sync_mode !== "disabled") {
      metaBadges.push(`<span class="room-meta-badge" title="Synkroniseringstilstand">🔄 ${this._esc(this._syncModeLabel(room.sync_mode))}</span>`);
    }
    if (room.schedule_entity) {
      metaBadges.push(`<span class="room-meta-badge" title="Schedule-entity konfigureret">🗓 Schedule</span>`);
    }
    if (room.trv_count > 1) {
      metaBadges.push(`<span class="room-meta-badge" title="Antal ventiler i rummet">🔧 ${room.trv_count} ventiler</span>`);
    }
    const metaRow = metaBadges.length ? `<div class="room-meta-row">${metaBadges.join("")}</div>` : "";
    // 2026-09-11 (monitoring-only rooms): a room with no TRV at all (e.g.
    // "Gang" — a hallway with only a temp sensor) always showed "Target Temp –"
    // and "Trv batt –", reading as something broken/missing rather than as
    // the deliberate, expected state of a room that has no TRV to have a
    // setpoint or a battery for. Only render those two boxes when the room
    // actually has one; "Rum temp" alone still applies (that's the whole
    // point of a monitoring-only room).
    const hasTrv = !!room.climate_entity;
    const tempsRowHTML = hasTrv
      ? `<div class="room-temps">
           <div class="room-temp-box">
             <div class="room-temp-val">${tempStr}</div>
             <div class="room-temp-lbl">I rummet</div>
           </div>
           <div class="room-temp-box">
             <div class="room-temp-val">${setpt ?? "–"}</div>
             <div class="room-temp-lbl">Mål nu</div>
           </div>
           <div class="room-temp-box">
             <div class="room-temp-val" style="${battColor ? `color:${battColor}` : ""}">${battStr}</div>
             <div class="room-temp-lbl">Batteri</div>
           </div>
         </div>`
      : `<div class="room-temps" style="grid-template-columns:1fr">
           <div class="room-temp-box">
             <div class="room-temp-val">${tempStr}</div>
             <div class="room-temp-lbl">I rummet</div>
           </div>
         </div>`;
    return `
      <div class="room-card state-${state}${pulseCls}" data-room-id="${this._esc(room.name)}"
           style="background:${grad};border-left-color:${color}">
        <div class="room-card-header">
          <div class="room-card-name">${this._esc(room.name)}</div>
          <div style="display:flex;align-items:center;gap:5px">
            ${boostBadge}
            <div class="room-state-pill" style="background:${color}22;color:${color}">${label}</div>
          </div>
        </div>
        <div class="room-override-info"${overrideInfo ? "" : " hidden"}>${this._esc(overrideInfo)}</div>
        ${tempsRowHTML}
        <div class="room-state-bar">
          <div class="room-state-fill" style="width:${fillPct}%;background:${color}"></div>
        </div>
        ${extraChips}
        ${valveBadge}
        ${moldBadge}
        ${healthBadge}
        ${blockingBadge}
        ${windowPendingBadge}
        ${metaRow}
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
    // 2026-09 audit fix: auto_off_reason was computed by the backend and
    // sent in every payload, but never actually displayed anywhere — the
    // "Slukket" badge below gave no clue *why*. Label only the two reasons
    // that actually fire (see AutoOffReason in const.py); "none" needs no
    // label since isOff is already false whenever it applies.
    const reasonLabel = { season: "sæson", temperature: "temperatur" }[d?.auto_off_reason] ?? null;
    const calMap = { winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår" };
    const calLabel = calMap[d?.calendar_season] ?? "–";
    // v0.3.9 fix: effective_season is dormant/waking/active, not a calendar
    // season — previously looked up in calMap and always showed "–".
    const eff      = this._effSeasonInfo(d?.effective_season);
    const otemp  = d?.outdoor_temp != null ? Math.round(d.outdoor_temp) + "°C" : "–";
    // v0.70.0: why the season is (not) "Opvågning" — the indoor wake sensor
    // AND the outdoor minimum both have to be met (SeasonEngine.wake_check).
    const wc = d?.wake_check;
    const fmtC = (v) => (v == null ? "–" : String(v).replace(".", ",") + " °C");
    const wakeLine = wc
      ? `Inde ${fmtC(wc.indoor)} ${wc.indoor >= wc.threshold ? "≥" : "<"} ${fmtC(wc.threshold)} · ude ${fmtC(wc.outdoor)} ${wc.outdoor == null || wc.outdoor >= wc.min_outdoor ? "≥" : "<"} ${fmtC(wc.min_outdoor)}`
      : "";
    return `
      <div class="section-box-header">
        <div class="section-box-title">Auto-off status</div>
        <div class="section-box-badge" style="background:${isOff?"rgba(239,68,68,0.15)":"rgba(249,115,22,0.15)"};color:${isOff?"#ef4444":"#f97316"}">
          ${isOff ? "Slukket" + (reasonLabel ? ` (${reasonLabel})` : "") : "Aktiv"}
        </div>
      </div>
      <div class="autooff-grid">
        <div class="aocard">
          <div class="aocard-lbl">Kalender-sæson</div>
          <div class="aocard-val">${calLabel}</div>
        </div>
        <div class="aocard">
          <div class="aocard-lbl">Effektiv sæson</div>
          <div class="aocard-val">${eff.icon} ${eff.label}</div>
          ${wakeLine ? `<div class="aocard-lbl" style="margin-top:4px;text-transform:none;letter-spacing:0">${this._esc(wakeLine)}</div>` : ""}
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

  _historyRowsHTML() {
    const all = this._history?.events ?? [];
    const events = this._historyFilter === "all"
      ? all
      : all.filter(e => (e.type ?? "normal") === this._historyFilter);
    if (!events.length) {
      return `<div class="empty">${all.length ? "Ingen hændelser af denne type" : "Ingen hændelser endnu"}</div>`;
    }
    return events.slice(0, 25).map(e => `
      <div class="hist-row">
        <div class="hist-dot" style="background:${this._eventTypeInfo(e.type ?? "normal").color}"></div>
        <div class="hist-time">${this._esc(e.time ?? "")}</div>
        <div class="hist-desc">${this._esc(e.description ?? "")}</div>
        <div class="hist-reason">${this._esc(e.reason ?? "")}</div>
      </div>`).join("");
  }

  // ── Tab builders ──────────────────────────────────────────────────────────

  // NB: _remoteLastActionHTML()/_patchRemoteLastAction() and the Oversigt-
  // only #remote-last-action-box they drove used to live here (2026-09-07
  // audit fix 5.4). Removed in v0.32.0 — coordinator.remote_last_action is
  // now one of the entries websocket_payload.py's build_active_issues() folds into
  // `active_issues` (same 30-min freshness window), so it shows in the
  // header status center from every tab instead of only Oversigt.

  _overviewHTML() {
    const rooms  = this._data?.rooms ?? [];
    // 2026-09-11: a monitoring-only room (no TRV — v0.24.1) still gets a
    // room.state from the coordinator, but nothing is actively controlling
    // heat in it. Counting it under "Aktiv" overstated how many rooms are
    // really under active heat control, so it gets its own "Passiv" tile
    // instead. Kept mutually exclusive with the other tiles: a monitoring-
    // only room in "away"/"window_open" still counts under those (its real,
    // more specific state), "Passiv" only catches the otherwise-uneventful
    // monitoring-only rooms, so every room lands in exactly one tile.
    const active  = rooms.filter(r => r.state === "normal" && r.climate_entity).length;
    const passive = rooms.filter(r => r.state === "normal" && !r.climate_entity).length;
    const away   = rooms.filter(r => r.state === "away").length;
    const winOpen = rooms.filter(r => r.state === "window_open").length;
    // 2026-09 audit fix: window_engine.get_open_windows() reads the actual
    // window/door sensors directly (real-time truth) — winOpen above counts
    // rooms already in the WINDOW_OPEN *state*, which lags slightly behind
    // during the open/close delay windows. Surface the sensor-level list as
    // a tooltip on the card rather than a second, easily-confused counter.
    const openWindowsList = this._data?.open_windows ?? [];
    const winOpenTitle = openWindowsList.length ? openWindowsList.join(", ") : "";
    // 2026-09-11: interior doors (v0.24.0) already carry a live "is_open"
    // per door from the sensor itself — same real-time-truth pattern as
    // open_windows above, just doors instead of windows.
    const doorsList = this._data?.doors ?? [];
    const openDoors = doorsList.filter(d => d.is_open);
    const doorsOpenTitle = openDoors.map(d => `${d.room_a} ↔ ${d.room_b}`).join(", ");
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
            <div class="qs-icon">🛋️</div>
            <div class="qs-value" data-qs="qs-passive" style="color:var(--sub)">${passive}</div>
            <div class="qs-label">Passiv</div>
          </div>
          <div class="qs-card" ${winOpenTitle ? `title="${this._esc(winOpenTitle)}"` : ""}>
            <div class="qs-icon">🪟</div>
            <div class="qs-value" data-qs="qs-window" style="color:${winOpen > 0 ? "var(--red)" : "var(--sub)"}">${winOpen}</div>
            <div class="qs-label">Vindue åbent</div>
          </div>
          <div class="qs-card" ${doorsOpenTitle ? `title="${this._esc(doorsOpenTitle)}"` : ""}>
            <div class="qs-icon">🚪</div>
            <div class="qs-value" data-qs="qs-doors" style="color:${openDoors.length > 0 ? "var(--red)" : "var(--sub)"}">${openDoors.length}</div>
            <div class="qs-label">Åbne døre</div>
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
    // v0.66.0: rebuilt into named sections (Temperatur / Ventil / Indeklima /
    // Rummets indstillinger / Midlertidig ændring) with one distinct Danish
    // name per value. The old layout showed "Target temp" three times with
    // three different meanings (live target, comfort setting, manual slider).
    // Rooms without a valve ("Kun sensorer") show measurements only.
    const state    = room.state ?? "normal";
    const color    = this._stateColor(state);
    const esc      = (v) => this._esc(v);
    const fmtT     = (v) => v != null ? `${Math.round(v * 10) / 10}°C` : "–";
    const hasTrv   = !!room.climate_entity;
    const roomName = esc(room.name);

    // ── Header ────────────────────────────────────────────────────────────
    const trvBadge = room.trv_type
      ? this._trvBadgeHTML(room.trv_type, room.netatmo_backend)
      : `<span class="rd-badge-sensor">Kun sensorer</span>`;
    const boostBadge = room.boost_active
      ? `<span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;background:rgba(168,85,247,0.15);color:#c084fc;margin-left:4px">⚡ BOOST</span>`
      : "";
    const stateBadge = hasTrv
      ? `<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;background:${color}22;color:${color}">${this._stateLabel(state, room.override_source)}</span>`
      : "";
    const overrideInfo = this._overrideInfoText(room);
    const unavailableList = room.unavailable_entities ?? [];
    const unavailableHTML = unavailableList.length
      ? `<div class="rd-warn" title="${esc(unavailableList.join(", "))}">⚠ ${unavailableList.length} ${unavailableList.length > 1 ? "enheder svarer" : "enhed svarer"} ikke: ${esc(unavailableList.join(", "))}</div>`
      : "";

    // Small building blocks.
    const section = (title) => `<div class="rd-sec">${title}</div>`;
    const stat = (label, value, sub = "", desc = "") => `
      <div class="rd-stat">
        <div class="rd-stat-l">${label}${desc ? this._infoIcon(desc) : ""}</div>
        <div class="rd-stat-v">${value}</div>
        ${sub ? `<div class="rd-stat-s">${sub}</div>` : ""}
      </div>`;
    const row = (label, value, valueStyle = "", desc = "") => `
      <div class="rd-row">
        <span class="rd-row-l">${label}${desc ? this._infoIcon(desc) : ""}</span>
        <span class="rd-row-v" style="${valueStyle}">${value}</span>
      </div>`;

    // ── Temperatur ────────────────────────────────────────────────────────
    const roomTempDesc = "Rummets faktiske temperatur — fra ekstern temperatursensor, hvis rummet har en, ellers fra ventilens egen måling.";
    const targetDesc = "Den temperatur Heat Manager styrer efter lige nu: komforttemperaturen efter skema, offset, natsænkning og fravær.";
    const sentDesc = "Det sætpunkt PID'en sender til ventilen lige nu. Kan ligge over målet, mens rummet stadig er koldt. Vises kun i normal, automatisk drift.";
    const radiatorDesc = "Ventilens egen måling. Den sidder på radiatoren og viser typisk 1-3°C mere end rummet.";
    const setpt     = this._roomSetpoint(room);
    const trvTemp   = hasTrv ? this._climateTemp(room.climate_entity) : null;
    const comfortSub = room.comfort_temp != null ? `komfort ${Math.round(room.comfort_temp * 10) / 10}°C` : "";
    const tempHTML = hasTrv
      ? `${section("Temperatur")}
         <div class="rd-grid">
           ${stat("I rummet", fmtT(room.current_temp), "", roomTempDesc)}
           ${stat("Mål nu", setpt ?? "–", comfortSub, targetDesc)}
           ${stat("Sendt til ventil", fmtT(room.trv_setpoint), room.trv_setpoint != null ? "PID-sætpunkt" : "ikke i auto", sentDesc)}
           ${stat("Ved radiatoren", trvTemp ?? "–", "ventilens måling", radiatorDesc)}
         </div>`
      : `${section("Temperatur")}
         <div class="rd-grid" style="max-width:220px">${stat("I rummet", fmtT(room.current_temp), "", roomTempDesc)}</div>`;

    // ── Ventil ────────────────────────────────────────────────────────────
    let valveHTML = "";
    if (hasTrv) {
      const valve  = room.valve_position != null ? Math.round(room.valve_position) : null;
      const isHeat = valve != null && valve > 0;
      const valveBar = valve != null
        ? `<div class="rd-row">
             <span class="rd-row-l">Åbning</span>
             <div class="rd-bar"><div style="width:${valve}%;background:${isHeat ? "#f97316" : "#475569"}"></div></div>
             <span class="rd-row-v" style="min-width:42px;text-align:right;color:${isHeat ? "#f97316" : "var(--sub)"}">${valve}%${isHeat ? " 🔥" : ""}</span>
           </div>`
        : "";
      const battery = room.battery_level != null ? Math.round(room.battery_level) : null;
      const batteryColor = battery == null ? "" : battery <= 15 ? "color:var(--red)" : battery <= 30 ? "color:var(--amber)" : "";
      const calib = room.calibration_offset != null
        ? `${room.calibration_offset >= 0 ? "+" : ""}${room.calibration_offset.toFixed(1)}°C`
        : null;
      valveHTML = `${section("Ventil")}
        ${valveBar}
        ${room.pid_power != null ? row("Varmebehov (PID)", `${Math.round(room.pid_power)}%`, "", "Hvor meget varme PID-regulatoren beder om lige nu, 0-100%.") : ""}
        ${calib ? row("Kalibrering", calib) : ""}
        ${battery != null ? row("Batteri", `${battery}%`, batteryColor) : ""}
        ${this._netatmoRowsHTML(room, row)}`;
    }

    // ── Indeklima ─────────────────────────────────────────────────────────
    const doors = (this._data?.doors ?? []).filter(d => d.room_a === room.name || d.room_b === room.name);
    const doorRows = doors.map(d => {
      const other = d.room_a === room.name ? d.room_b : d.room_a;
      const value = d.available === false ? "utilgængelig" : (d.is_open ? "Åben" : "Lukket");
      return row(`Dør til ${esc(other)}`, value, d.is_open ? "color:var(--amber)" : "");
    }).join("");
    const climateRows = [
      room.humidity != null ? row("Luftfugtighed", `${Math.round(room.humidity * 10) / 10}%`) : "",
      room.co2 != null ? row("CO₂", `${Math.round(room.co2)} ppm`) : "",
      room.lux != null ? row("Lys", `${Math.round(room.lux)} lux`) : "",
      room.window_duration_today != null ? row("Vindue åbent i dag", `${room.window_duration_today} min`) : "",
      doorRows,
      room.has_heated_doors ? row("Yderdør", room.heated_door_open ? "Åben" : "Lukket", room.heated_door_open ? "color:var(--amber)" : "") : "",
    ].join("");
    const climateHTML = climateRows.trim() ? `${section("Indeklima")}${climateRows}` : "";

    // ── Rummets indstillinger ─────────────────────────────────────────────
    // Inline editing of the room's comfort temperature (ws_update_room_config).
    // v0.67.0: the per-room "away temp" is gone — it was really the PID/setback
    // floor and is now the global "Laveste rumtemperatur" in Indstillinger.
    const comfortDesc = "Den temperatur rummet skal have, når nogen er hjemme. Natsænkning og offset trækkes fra denne, men aldrig under laveste rumtemperatur (Indstillinger).";
    const settingsHTML = hasTrv ? `${section("Rummets indstillinger")}
         <div class="room-cfg-edit" data-room="${roomName}">
           <div class="rd-row">
             <span class="rd-row-l">Komforttemperatur${this._infoIcon(comfortDesc)}</span>
             <input class="cfg-edit-input room-cfg-input" type="number" min="15" max="26" step="0.5"
               value="${esc(room.comfort_temp ?? "")}" data-field="comfort_temp">
             <span class="rd-unit">°C</span>
             <button class="cfg-save-btn" data-action="save-room-cfg" data-room="${roomName}">Gem</button>
             <span class="cfg-save-ok room-cfg-ok">✔</span>
           </div>
         </div>` : "";

    // ── Midlertidig ændring ───────────────────────────────────────────────
    const manualHTML = (hasTrv && this._manualControlEnabled) ? `
      <div class="room-manual" data-room="${roomName}">
        <div class="rd-sec" style="margin-top:0">Midlertidig ændring</div>
        <div class="room-manual-row">
          <span class="room-manual-lbl">Temperatur</span>
          <input class="room-manual-slider" type="range" min="10" max="28" step="0.5"
            value="${setpt ? parseFloat(setpt) : 20}"
            data-room="${roomName}">
          <span class="room-manual-val">${setpt ? parseFloat(setpt) : 20}°C</span>
        </div>
        <div class="room-manual-row" style="margin-top:6px">
          <span class="room-manual-lbl">Varighed</span>
          <select class="room-manual-dur" data-room="${roomName}">
            <option value="30">30 min</option>
            <option value="60" selected>1 time</option>
            <option value="120">2 timer</option>
            <option value="0">Indtil videre</option>
          </select>
          <button class="room-manual-send" data-room="${roomName}">Sæt</button>
        </div>
        <div class="room-manual-row" style="margin-top:6px">
          <span class="room-manual-lbl"></span>
          <button class="room-manual-reset" data-room="${roomName}"
            title="Fjern den midlertidige ændring og følg skemaet igen">↺ Tilbage til automatik</button>
          <button class="room-manual-force" data-room="${roomName}"
            title="Tving rummet til at varme nu, uanset tilstedeværelse og vinduer (heat_manager.force_room_on)">⚡ Tving varme til</button>
        </div>
      </div>` : "";

    // B18 Fase 3: grouping controls — only rendered for rooms with 2+
    // physical TRVs (RoomOffsetNumber/RoomGroupToggleSwitch only exist for
    // those). group_enabled defaults true (matches coordinator.py's
    // room_group_enabled.get(name, True)).
    const trvCount     = room.trv_count ?? 1;
    const groupEnabled = room.group_enabled !== false;
    const roomOffset   = room.offset ?? 0;
    const groupingHTML = (hasTrv && trvCount > 1) ? `
      <div class="room-grouping" data-room="${roomName}">
        <div class="rd-sec" style="margin-top:0">Ventilgruppe</div>
        <div class="room-group-row">
          <span class="room-group-lbl">🔗 ${trvCount} ventiler</span>
          <button class="toggle-btn room-group-toggle${groupEnabled ? " active" : ""}"
            data-action="toggle-room-group" data-room="${roomName}">
            ${groupEnabled ? "Grupperet" : "Frigivet"}
          </button>
        </div>
        <div class="room-offset-row" style="margin-top:8px">
          <span class="room-offset-label">Offset</span>
          <input class="room-offset-slider" type="range" min="-5" max="5" step="0.5"
            value="${roomOffset}" data-room="${roomName}">
          <span class="room-offset-val" data-room="${roomName}">${(roomOffset >= 0 ? "+" : "") + roomOffset.toFixed(1)}°C</span>
        </div>
        ${!groupEnabled ? `<div style="font-size:10px;color:var(--sub);margin-top:6px;line-height:1.5">De ekstra ventiler styres ikke af Heat Manager lige nu — kun den primære ventil følger skemaet.</div>` : ""}
      </div>` : "";

    // ── Collapsed summary (v0.67.1) ───────────────────────────────────────
    // One line with what matters at a glance; everything else sits in the
    // .rd-body blocks that only show when the card is expanded.
    const summaryParts = [];
    if (room.current_temp != null) {
      summaryParts.push(hasTrv && setpt
        ? `<span><b>${fmtT(room.current_temp)}</b>&nbsp;→ mål ${setpt}</span>`
        : `<b>${fmtT(room.current_temp)}</b>`);
    }
    if (hasTrv && room.valve_position != null) {
      const v = Math.round(room.valve_position);
      summaryParts.push(v > 0 ? `<span style="color:#f97316">ventil ${v}%</span>` : `ventil ${v}%`);
    }
    if (room.humidity != null) summaryParts.push(`fugt ${Math.round(room.humidity)}%`);
    if (room.co2 != null) summaryParts.push(`CO₂ ${Math.round(room.co2)} ppm`);
    if (doors.some(d => d.is_open) || room.heated_door_open) {
      summaryParts.push(`<span style="color:var(--amber)">dør åben</span>`);
    }
    if (hasTrv && room.battery_level != null && room.battery_level <= 30) {
      summaryParts.push(`<span style="color:var(--amber)">batteri ${Math.round(room.battery_level)}%</span>`);
    }
    const expanded = this._expandedRooms.has(room.name);

    return `
      <div class="room-detail-row${expanded ? " expanded" : ""}" data-room="${roomName}" style="border-bottom:1px solid var(--div)">
        <div style="padding:12px 16px">
          <div class="rd-head" data-action="toggle-room" data-room="${roomName}"
            role="button" tabindex="0" aria-expanded="${expanded}"
            title="${expanded ? "Fold sammen" : "Vis detaljer"}">
            <div style="display:flex;align-items:center;gap:6px;min-width:0">
              <span class="rd-chevron" aria-hidden="true">›</span>
              <span style="font-size:14px;font-weight:600">${roomName}</span>
              ${trvBadge}
              ${boostBadge}
            </div>
            ${stateBadge}
          </div>
          <div class="rd-summary">${summaryParts.join('<span class="rd-dot">·</span>')}</div>
          ${overrideInfo ? `<div class="room-override-info">${esc(overrideInfo)}</div>` : ""}
          ${unavailableHTML}
          <div class="rd-body">
            ${tempHTML}
            ${valveHTML}
            ${climateHTML}
            ${settingsHTML}
          </div>
        </div>
        <div class="rd-body">
          ${manualHTML}
          ${groupingHTML}
        </div>
      </div>`;
  }

  _loadExpandedRooms() {
    try {
      const raw = sessionStorage.getItem("heat_manager_expanded_rooms");
      const list = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(list) ? list : []);
    } catch (_e) {
      return new Set();
    }
  }

  _saveExpandedRooms() {
    try {
      sessionStorage.setItem("heat_manager_expanded_rooms", JSON.stringify([...this._expandedRooms]));
    } catch (_e) { /* storage unavailable — state just isn't remembered */ }
  }

  // v0.67.1: expand/collapse without rebuilding — flip the class on the row.
  _setRoomExpanded(row, expanded) {
    const name = row?.dataset.room;
    if (!name) return;
    row.classList.toggle("expanded", expanded);
    const head = row.querySelector(".rd-head");
    head?.setAttribute("aria-expanded", String(expanded));
    head?.setAttribute("title", expanded ? "Fold sammen" : "Vis detaljer");
    if (expanded) this._expandedRooms.add(name); else this._expandedRooms.delete(name);
  }

  _updateFoldAllButton() {
    const btn = this.shadowRoot.querySelector("#rooms-fold-all");
    if (!btn) return;
    const rows = [...this.shadowRoot.querySelectorAll(".room-detail-row")];
    const allOpen = rows.length > 0 && rows.every(r => r.classList.contains("expanded"));
    btn.textContent = allOpen ? "Fold alle sammen" : "Fold alle ud";
    btn.dataset.mode = allOpen ? "collapse" : "expand";
  }

  // v0.66.0: Netatmo's own view of the room as plain Danish rows — who
  // controls it ("Følger tidsplan «Vinter»", "Manuel til 18:30"), whether it
  // is heating, and Netatmo's own setpoint with a written-out warning when
  // it differs from Heat Manager's target. Only for rooms with a Netatmo
  // cloud entity (all cloud_* fields are null otherwise).
  _netatmoRowsHTML(room, row) {
    const modeLabel = this._netatmoModeLabel(room);
    const sched = room.cloud_selected_schedule;
    const parts = [];
    if (modeLabel === "tidsplan") {
      parts.push(sched ? `Følger tidsplan «${this._esc(sched)}»` : "Følger tidsplan");
    } else if (modeLabel) {
      parts.push(this._esc(modeLabel.charAt(0).toUpperCase() + modeLabel.slice(1)));
    } else if (room.cloud_preset_mode) {
      parts.push(`Forvalg: ${this._esc(room.cloud_preset_mode)}${sched ? ` («${this._esc(sched)}»)` : ""}`);
    } else if (sched) {
      parts.push(`Tidsplan «${this._esc(sched)}»`);
    }
    const action = room.cloud_hvac_action;
    if (action) {
      parts.push(({ heating: "varmer", idle: "varmer ikke", off: "slukket" })[action] ?? this._esc(action));
    }
    let html = parts.length ? row("Netatmo", parts.join(" · "), "color:var(--text)") : "";
    if (room.cloud_temperature != null) {
      // Compare with what Heat Manager actually sent to the valve when known
      // (the PID setpoint can sit above the target on purpose); fall back to
      // the target otherwise. Comparing with the target alone flagged normal
      // PID operation as a mismatch.
      const cloud = Math.round(room.cloud_temperature * 10) / 10;
      const ref = room.trv_setpoint ?? room.target_temp;
      const refLabel = room.trv_setpoint != null ? "har sendt" : "vil have";
      const diverges = ref != null && Math.abs(room.cloud_temperature - ref) >= 0.5;
      html += row("Sætpunkt i Netatmo", `${cloud}°C`, diverges ? "color:var(--amber)" : "",
        "Det sætpunkt Netatmo selv viser for rummet — ikke nødvendigvis det Heat Manager vil have.");
      if (diverges) {
        const refVal = Math.round(ref * 10) / 10;
        html += `<div class="rd-note">⚠ Netatmo står på ${cloud}°C, Heat Manager ${refLabel} ${refVal}°C.</div>`;
      }
    }
    return html;
  }

  // 2026-09-11: global counterpart to the per-room manual-override slider
  // (room-manual-*, _roomDetailRowHTML()). Reuses the exact same
  // heat_manager/set_room_temp WS command in a loop — no backend changes —
  // one call per controllable room, awaited sequentially (not Promise.all)
  // so this can never burst-call Netatmo's cloud API across every room at
  // once (see coordinator.py's asyncio.sleep(0.6)-between-rooms rationale
  // for the same concern on the PID tick side). Skips monitoring-only rooms
  // (no climate_entity) — there is nothing there to set a temperature on.
  // Only rendered when "Manuel TRV-kontrol" is on, same gate as the
  // per-room sliders it sits above.
  _globalManualHTML() {
    if (!this._manualControlEnabled) return "";
    const controllable = (this._data?.rooms ?? []).filter(r => r.climate_entity).length;
    return `
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Alle rum — midlertidig ændring</div>
        </div>
        <div class="room-manual" style="padding:12px 16px">
          <div class="room-manual-row">
            <span class="room-manual-lbl">Temperatur</span>
            <input class="room-manual-slider global-manual-slider" type="range" min="10" max="28" step="0.5" value="20">
            <span class="room-manual-val global-manual-val">20°C</span>
          </div>
          <div class="room-manual-row" style="margin-top:6px">
            <span class="room-manual-lbl">Varighed</span>
            <select class="room-manual-dur global-manual-dur">
              <option value="30">30 min</option>
              <option value="60" selected>1 time</option>
              <option value="120">2 timer</option>
              <option value="0">Indtil videre</option>
            </select>
            <button class="room-manual-send global-manual-send" id="global-manual-send">Sæt i alle rum</button>
            <button class="room-manual-reset global-manual-reset" id="global-manual-reset">↺ Alle tilbage til automatik</button>
          </div>
          <div style="font-size:10px;color:var(--sub);margin-top:6px">
            Sætter ${controllable} rum med ventil til samme temperatur — rum med kun sensorer springes over.
          </div>
        </div>
      </div>`;
  }

  _roomsTabHTML() {
    const rooms = this._data?.rooms ?? [];
    const heatingCount = rooms.filter(r => (r.valve_position ?? 0) > 0).length;
    return `
      ${this._globalManualHTML()}
      <div class="section-box">
        <div class="section-box-header">
          <div class="section-box-title">Rum — detaljer</div>
          <div style="display:flex;align-items:center;gap:8px">
            <button class="rd-fold-all" id="rooms-fold-all" type="button">Fold alle ud</button>
            <div class="section-box-badge rooms-detail-badge" style="background:rgba(249,115,22,0.15);color:var(--amber)">
              ${heatingCount} / ${rooms.length} varmer
            </div>
          </div>
        </div>
        <div class="rooms-detail-container">
          ${rooms.length
            ? rooms.map(r => this._roomDetailRowHTML(r)).join("")
            : `<div class="empty">Ingen rum konfigureret</div>`}
        </div>
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
        <div id="hist-filter-row" class="hist-filter-row">${this._historyFilterChipsHTML()}</div>
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

  // Fase 2, del 1 (2026-09-13) — "Indstillinger": shared row builders used by
  // the PID/Boost/Vindue/Nat-sætpunkt/Grace/Auto-off section-boxes below.
  // One generic save-field/toggle-field click handler in _attachEvents()
  // handles every row these produce — see planning/heat_manager_fase2_spec.
  _cfgNumberRow(label, field, value, { min, max, step, unit = "", desc = "", cast = "float" } = {}) {
    // 2026-09-19 (ønske: konsekvent beskrivelses-stil): var før en (i)-hover-
    // ikon (_infoIcon) — skjult indtil man aktivt hoverede/tappede den, i
    // modstrid med _cfgToggleRow's altid-synlige beskrivelse lige under
    // label'et. Nu samme mønster begge steder: beskrivelsen står direkte
    // under label-rækken, aldrig skjult. Gælder alle kald af denne funktion
    // på tværs af alle 14 sektioner i Konfiguration — én ændring her slår
    // igennem overalt, ingen af de øvrige kaldesteder skal røres.
    return `
      <div class="cfg-edit-row-wrap">
        <div class="cfg-edit-row">
          <span class="cfg-edit-label" style="flex:0 0 150px">${this._esc(label)}</span>
          <input class="cfg-edit-input" type="number"
            id="cfg-${field}-input" min="${min}" max="${max}" step="${step}"
            value="${this._esc(value)}">
          ${unit ? `<span class="cfg-edit-label" style="flex-shrink:0">${this._esc(unit)}</span>` : ""}
          <button class="cfg-save-btn" data-action="save-field" data-field="${field}" data-cast="${cast}">Gem</button>
          <span class="cfg-save-ok" id="cfg-${field}-ok">✔</span>
        </div>
        ${desc ? `<div class="cfg-edit-desc">${this._esc(desc)}</div>` : ""}
      </div>`;
  }

  // v0.67.7: which alarm states put the house in away. Toggle chips; each
  // click saves the whole list (heat_manager/update_config alarm_away_states).
  static get ALARM_STATE_LABELS() {
    return {
      armed_away: "Armeret væk",
      armed_vacation: "Armeret ferie",
      armed_night: "Armeret nat",
      armed_home: "Armeret hjemme",
      armed_custom_bypass: "Armeret brugerdefineret",
    };
  }

  _alarmStatesHTML(states) {
    const active = new Set(states ?? ["armed_away"]);
    const labels = this.constructor.ALARM_STATE_LABELS;
    return `
      <div class="cfg-edit-row-wrap" style="padding:4px 0 10px">
        <div class="cfg-edit-desc" style="margin-bottom:6px">Slukker varmen (fravær) ved:</div>
        <div class="alarm-state-chips">
          ${Object.entries(labels).map(([key, label]) => `
            <button type="button" class="toggle-btn alarm-state-chip${active.has(key) ? " active" : ""}"
              data-action="toggle-alarm-state" data-state="${key}"
              aria-pressed="${active.has(key)}">${label}</button>`).join("")}
        </div>
      </div>`;
  }

  _alarmFooterText(states) {
    const labels = this.constructor.ALARM_STATE_LABELS;
    const list = (states ?? ["armed_away"]).map(s => labels[s] ?? s);
    const strong = (t) => `<strong style="color:var(--text)">${this._esc(t)}</strong>`;
    if (!list.length) {
      return "Ingen alarmtilstand er valgt — alarmen sætter ikke huset i fravær.";
    }
    return `Når alarmen går i ${list.map(strong).join(" eller ")}, aktiveres fraværsmodus øjeblikkeligt uden grace period. Ved frakoblet eller en anden armeret tilstand genoptages opvarmningen, når nogen er hjemme.`;
  }

  // v0.67.0: Netatmo's home-level away temperature (NET-TRV number on the
  // relay). Written straight to Netatmo with number.set_value — it is the same
  // value as in the Netatmo app, stored on the active schedule. Without
  // NET-TRV (core netatmo) there is no such entity: say where it is set.
  _awayTempRowHTML(minRoomTemp) {
    const a = this._data?.netatmo_away_temp;
    if (!a) {
      return `
      <div class="cfg-edit-row-wrap">
        <div class="cfg-edit-row">
          <span class="cfg-edit-label" style="flex:0 0 150px">Fraværstemperatur</span>
          <span class="cfg-edit-label">Styres i Netatmo-appen</span>
        </div>
        <div class="cfg-edit-desc">Med NET-TRV kan den sættes herfra. Den bruges af alle Netatmo-ventiler, når huset er tomt.</div>
      </div>`;
    }
    const low = a.value != null && minRoomTemp != null && a.value < minRoomTemp;
    const sched = a.schedule ? ` Gemmes på Netatmo-tidsplanen «${this._esc(a.schedule)}».` : "";
    return `
      <div class="cfg-edit-row-wrap">
        <div class="cfg-edit-row">
          <span class="cfg-edit-label" style="flex:0 0 150px">Fraværstemperatur</span>
          <input class="cfg-edit-input" type="number" id="cfg-netatmo-away-input"
            min="${a.min ?? 7}" max="${a.max ?? 30}" step="${a.step ?? 0.5}"
            value="${a.value ?? ""}">
          <span class="cfg-edit-label" style="flex-shrink:0">°C</span>
          <button class="cfg-save-btn" data-action="save-netatmo-away"
            data-entity="${this._esc(a.entity_id)}">Gem</button>
          <span class="cfg-save-ok" id="cfg-netatmo-away-ok">✔</span>
        </div>
        <div class="cfg-edit-desc">Netatmos egen fraværstemperatur — den alle ventiler går til, når huset er tomt. Samme værdi som i Netatmo-appen.${sched}</div>
        ${low ? `<div class="cfg-edit-desc" style="color:var(--amber)">⚠ Fraværstemperaturen (${a.value} °C) er lavere end laveste rumtemperatur (${minRoomTemp} °C). Rummene kan blive koldere end minimum, når huset er tomt.</div>` : ""}
      </div>`;
  }

  // v0.33.0 (point 4 — tooltips): a small "i" mark that shows a short
  // explanation of what a setting/column actually does. Hover/focus reveal
  // it via CSS alone (:hover/:focus); the shared click listener bound once
  // in connectedCallback() toggles an .open class for tap support on
  // mobile, and closes it again on any click elsewhere.
  _infoIcon(text) {
    return `<span class="info-icon" tabindex="0" role="note" aria-label="${this._esc(text)}">ⓘ<span class="info-popover">${this._esc(text)}</span></span>`;
  }

  // 2026-09-19: stable per-section collapse-state class, keyed by the same
  // id used for data-section-id — see this._expandedConfigSections in the
  // constructor and the toggle-section click handler in _attachEvents().
  _cfgSectionClass(id) {
    return "section-box" + (this._expandedConfigSections.has(id) ? "" : " collapsed");
  }

  // 2026-09-19 (ønske #2): a small colour dot alongside the existing
  // Aktiv/Inaktiv text — quicker to scan at a glance than reading the word,
  // especially once most sections sit collapsed showing only their header.
  _cfgStatusDot(active) {
    return `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${active ? "#22c55e" : "#64748b"};margin-right:5px;vertical-align:middle;flex-shrink:0"></span>`;
  }

  _cfgToggleRow(label, field, value, desc = "") {
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 16px">
        <div>
          <div style="font-size:13px;font-weight:600">${this._esc(label)}</div>
          ${desc ? `<div style="font-size:11px;color:var(--sub);margin-top:2px;line-height:1.4">${this._esc(desc)}</div>` : ""}
        </div>
        <button class="toggle-btn${value ? " active" : ""}" style="flex-shrink:0" data-action="toggle-field" data-field="${field}">
          ${value ? "Slå fra" : "Slå til"}
        </button>
      </div>`;
  }

  _configTabHTML() {
    const d   = this._data?.config ?? {};
    const cfg = [
      ["Weather entity",      d.weather_entity           ?? "–"],
      ["Outdoor temp sensor", d.outdoor_temp_sensor      ?? "–"],
    ];
    return `
      <div class="config-grid">
      <div class="${this._cfgSectionClass('global')}" data-section-id="global">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Global konfiguration</div>
        </div>
        ${cfg.map(([k,v]) =>
          `<div class="cfg-row"><span class="cfg-k">${k}</span><span class="cfg-v">${this._esc(v)}</span></div>`
        ).join("")}
        <div class="section-box-footer">Vejr-entiteten leverer udetemperatur til sæson, vejrkompensation, auto-off og nat-sætpunkt. Sættes under opsætningen — kan ikke redigeres herfra.</div>
      </div>

      <div class="${this._cfgSectionClass('alarm')}" data-section-id="alarm">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Alarmtavle</div>
          <div class="section-box-badge" style="background:rgba(249,115,22,0.12);color:var(--amber)">
            ${this._cfgStatusDot(!!d.alarm_panel)}${d.alarm_panel ? 'Konfigureret' : 'Ikke sat'}
          </div>
        </div>
        <div class="cfg-edit-row" style="padding-top:12px">
          <input class="cfg-edit-input" id="cfg-alarm-input"
            placeholder="alarm_control_panel.mit_alarm"
            value="${this._esc(d.alarm_panel ?? '')}">
          <button class="cfg-save-btn" data-action="save-alarm">Gem</button>
          <span class="cfg-save-ok" id="cfg-alarm-ok">✔</span>
        </div>
        ${this._alarmStatesHTML(d.alarm_away_states)}
        <div class="section-box-footer">${this._alarmFooterText(d.alarm_away_states)}</div>
      </div>

      <div class="${this._cfgSectionClass('manual_trv')}" data-section-id="manual_trv">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Manuel TRV-kontrol</div>
          <div class="section-box-badge" style="background:${this._manualControlEnabled?'rgba(99,102,241,0.15)':'rgba(71,85,105,0.15)'};color:${this._manualControlEnabled?'#818cf8':'var(--sub)'}">
            ${this._cfgStatusDot(this._manualControlEnabled)}${this._manualControlEnabled ? 'Aktiv' : 'Inaktiv'}
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
        <div class="section-box-footer">Viser en ekstra kontrol i Rum-fanen til at sætte en midlertidig temperatur direkte på én eller alle ventiler — uden om skema og PID. Til hurtige justeringer.</div>
      </div>

      <!-- Fase 2, del 1 (2026-09-13) — "Indstillinger": driftsparametre der
           før kun kunne ændres via options-flow'ets klik-igennem-dialog,
           flyttet hertil med samme live-gem-mønster som Alarmtavle ovenfor.
           Options-flow'en beholder de samme felter uændret (fallback for
           førstegangsopsætning) — se
           planning/heat_manager_fase2_spec_2026-09-11.md, "Del 1". -->

      <div class="${this._cfgSectionClass('pid')}" data-section-id="pid">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">PID-regulator</div>
          <div class="section-box-badge" data-badge-field="pid_enabled" style="background:${d.pid_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.pid_enabled ? "#818cf8" : "var(--sub)"}">
            ${this._cfgStatusDot(!!d.pid_enabled)}${d.pid_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("PID-regulering aktiveret", "pid_enabled", !!d.pid_enabled)}
        ${this._cfgNumberRow("Kp", "pid_kp", d.pid_kp ?? "", {
          min: 0, max: 5, step: 0.05, cast: "float",
          desc: "Hvor kraftigt effekten reagerer på den aktuelle temperaturafvigelse. Højere værdi = hurtigere, men mere ustabil regulering.",
        })}
        ${this._cfgNumberRow("Ki", "pid_ki", d.pid_ki ?? "", {
          min: 0, max: 0.5, step: 0.01, cast: "float",
          desc: "Retter en vedvarende, langsom afvigelse over tid. Hold lav — for høj værdi giver overshoot.",
        })}
        ${this._cfgNumberRow("Kd", "pid_kd", d.pid_kd ?? "", {
          min: 0, max: 2, step: 0.05, cast: "float",
          desc: "Reagerer på hvor hurtigt temperaturen ændrer sig. Sjældent nødvendig, da TRV'er har flere minutters egen forsinkelse.",
        })}
        ${this._cfgNumberRow("Setpoint-margin", "pid_setpoint_margin", d.pid_setpoint_margin ?? "", {
          min: 0.5, max: 6.0, step: 0.5, unit: "°C", cast: "float",
          desc: "Loft for hvor mange grader OVER rummets eget mål en TRV må bedes om at gå, uanset trv_max. Sænk for tættere styring, hæv hvis opvarmningen føles for langsom.",
        })}
        <div class="section-box-footer">PID-regulatoren styrer, hvor meget effekt hvert rum beder sine TRV'er om, ud fra afvigelsen mellem rummets aktuelle temperatur og målet.</div>
      </div>

      <!-- 2026-09-13 (architekturgennemgang #5) — vejrkompensationskurven
           (udetemperatur → proaktivt effektbidrag oven i PID'en) fandtes
           allerede som en fast, altid-aktiv konstant. Nu konfigurerbar, med
           default = de tidligere hardkodede værdier, så eksisterende
           installationer opfører sig uændret indtil felterne rent faktisk
           redigeres her. -->
      <div class="${this._cfgSectionClass('weather_comp')}" data-section-id="weather_comp">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Vejrkompensation</div>
          <div class="section-box-badge" data-badge-field="weather_compensation_enabled" style="background:${d.weather_compensation_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.weather_compensation_enabled ? "#818cf8" : "var(--sub)"}">
            ${this._cfgStatusDot(!!d.weather_compensation_enabled)}${d.weather_compensation_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("Vejrkompensation aktiveret", "weather_compensation_enabled", !!d.weather_compensation_enabled)}
        ${this._cfgNumberRow("Referenceudetemperatur", "ff_reference_outdoor_temp", d.ff_reference_outdoor_temp ?? "", {
          min: -10, max: 22, step: 0.5, unit: "°C", cast: "float",
          desc: "Udetemperatur ved/over hvilken vejrkompensationen bidrager med 0.",
        })}
        ${this._cfgNumberRow("Vægt", "ff_weight", d.ff_weight ?? "", {
          min: 0, max: 0.1, step: 0.005, cast: "float",
          desc: "Ekstra effektandel tilføjet pr. °C udetemperaturen er under referencen.",
        })}
        ${this._cfgNumberRow("Maksimalt bidrag", "ff_max_contribution", d.ff_max_contribution ?? "", {
          min: 0, max: 0.6, step: 0.05, cast: "float",
          desc: "Loft — vejrkompensation alene tilføjer aldrig mere end denne andel af effekten.",
        })}
        <div class="section-box-footer">Tilføjer et proaktivt effektbidrag baseret på udetemperaturen, oven i PID'ens reaktive korrektion — en klassisk "varmekurve".</div>
      </div>

      <!-- 2026-09-14 (punkt 7) — solindfald: reducerer PID-effekten pr. rum
           når sol.sol (sun.sun) er over horisonten og rummets lux-sensor
           (konfigureres pr. rum under "Rum & klimaentiteter"/rediger rum)
           viser lys. Genbruger de samme generiske toggle/number-rækker
           (og dermed den samme gem-logik) som Vejrkompensation ovenfor. -->
      <div class="${this._cfgSectionClass('solar_gain')}" data-section-id="solar_gain">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Solindfald</div>
          <div class="section-box-badge" data-badge-field="solar_gain_enabled" style="background:${d.solar_gain_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.solar_gain_enabled ? "#818cf8" : "var(--sub)"}">
            ${this._cfgStatusDot(!!d.solar_gain_enabled)}${d.solar_gain_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("Solindfald aktiveret", "solar_gain_enabled", !!d.solar_gain_enabled)}
        ${this._cfgNumberRow("Lux-grænse", "solar_gain_lux_threshold", d.solar_gain_lux_threshold ?? "", {
          min: 500, max: 30000, step: 500, unit: "lux", cast: "float",
          desc: "Lux-niveau, hvorover rummet regnes for at få reel sol lige nu.",
        })}
        ${this._cfgNumberRow("Vægt", "solar_gain_weight", d.solar_gain_weight ?? "", {
          min: 0, max: 0.5, step: 0.01, cast: "float",
          desc: "Hvor meget effekten reduceres pr. gang rummets lux overstiger grænsen.",
        })}
        ${this._cfgNumberRow("Maksimal reduktion", "solar_gain_max_reduction", d.solar_gain_max_reduction ?? "", {
          min: 0, max: 0.8, step: 0.05, cast: "float",
          desc: "Loft — solindfald alene fjerner aldrig mere end denne andel af effekten.",
        })}
        <div class="section-box-footer">Reducerer PID-effekten i rum med lux-sensor, mens solen er oppe og sensoren viser lys — direkte sol kræver mindre varme fra TRV'en.</div>
      </div>

      <div class="${this._cfgSectionClass('door_heat_share')}" data-section-id="door_heat_share">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Dør-varmedeling</div>
          <div class="section-box-badge" data-badge-field="door_heat_share_enabled" style="background:${d.door_heat_share_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.door_heat_share_enabled ? "#818cf8" : "var(--sub)"}">
            ${this._cfgStatusDot(!!d.door_heat_share_enabled)}${d.door_heat_share_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("Dør-varmedeling aktiveret", "door_heat_share_enabled", !!d.door_heat_share_enabled)}
        ${this._cfgNumberRow("Naborums minimumseffekt", "door_heat_share_min_neighbor_power", d.door_heat_share_min_neighbor_power ?? "", {
          min: 0, max: 1.0, step: 0.05, cast: "float",
          desc: "Naborummets egen PID-effekt skal være mindst dette, før dets varme tæller som reelt leveret lige nu.",
        })}
        ${this._cfgNumberRow("Minimum temperaturforskel", "door_heat_share_min_temp_diff", d.door_heat_share_min_temp_diff ?? "", {
          min: 0.5, max: 6.0, step: 0.5, unit: "°C", cast: "float",
          desc: "Hvor meget varmere naborummet mindst skal være, før nogen reduktion sker.",
        })}
        ${this._cfgNumberRow("Vægt", "door_heat_share_weight", d.door_heat_share_weight ?? "", {
          min: 0, max: 0.5, step: 0.01, cast: "float",
          desc: "Hvor meget effekten reduceres pr. grad temperaturforskellen overstiger grænsen.",
        })}
        ${this._cfgNumberRow("Maksimal reduktion", "door_heat_share_max_reduction", d.door_heat_share_max_reduction ?? "", {
          min: 0, max: 0.8, step: 0.05, cast: "float",
          desc: "Loft — dør-varmedeling alene fjerner aldrig mere end denne andel af effekten.",
        })}
        <div class="section-box-footer">Reducerer PID-effekten, når en åben indendørs dør fører til et varmere naborum, der selv varmer aktivt. Ændrer aldrig rummets mål — kun effekten.</div>
      </div>

      <div class="${this._cfgSectionClass('boost')}" data-section-id="boost">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Boost — standardværdier</div>
        </div>
        ${this._cfgNumberRow("Standardtemperatur", "boost_default_temp", d.boost_default_temp ?? "", {
          min: 15, max: 32, step: 0.5, unit: "°C", cast: "float",
          desc: "Temperaturen rummet sættes til, når Boost startes uden selv at angive en anden.",
        })}
        ${this._cfgNumberRow("Standardvarighed", "boost_default_minutes", d.boost_default_minutes ?? "", {
          min: 1, max: 240, step: 1, unit: "min", cast: "float",
          desc: "Hvor længe Boost varer, når det startes uden selv at angive en anden varighed.",
        })}
        <div class="section-box-footer">Bruges af Boost-knappen og <span style="font-family:'DM Mono',monospace">heat_manager.boost_start</span>, når intet andet angives eksplicit.</div>
      </div>

      <div class="${this._cfgSectionClass('temp_limits')}" data-section-id="temp_limits">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Temperaturgrænser</div>
        </div>
        ${this._cfgNumberRow("Laveste rumtemperatur", "min_room_temp", d.min_room_temp ?? "", {
          min: 5, max: 22, step: 0.5, unit: "°C", cast: "float",
          desc: "Gælder alle rum. PID'en sender aldrig et lavere sætpunkt til en ventil, og natsænkningen går aldrig under denne. Standard 17 °C — et almindeligt minimum mod skimmel.",
        })}
        ${this._awayTempRowHTML(d.min_room_temp)}
        <div class="section-box-footer">Laveste rumtemperatur styrer Heat Manager selv. Fraværstemperaturen er Netatmos egen og bruges, når huset er tomt.</div>
      </div>

      <div class="${this._cfgSectionClass('window')}" data-section-id="window">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Vindue</div>
        </div>
        ${this._cfgNumberRow("Forsinkelse før sluk", "window_delay_default_min", d.window_delay_default_min ?? "", {
          min: 0, max: 60, step: 1, unit: "min", cast: "int",
          desc: "Hvor længe et vindue skal være åbent, før varmen reelt slås fra. Gælder alle rum. Sættes automatisk ned ved kraftig vind eller regn.",
        })}
        ${this._cfgNumberRow("Sluk-temperatur", "window_off_temp", d.window_off_temp ?? "", {
          min: 5, max: 20, step: 0.5, unit: "°C", cast: "float",
          desc: "Temperaturen der sendes til rummets ventil, når varmen slås fra pga. åbent vindue. Gælder kun mens vinduet er åbent og er uafhængig af laveste rumtemperatur.",
        })}
        ${this._cfgNumberRow("Advarsel efter", "window_warning_min", d.window_warning_min ?? "", {
          min: 5, max: 180, step: 5, unit: "min", cast: "int",
          desc: "Hvor længe et vindue skal have været åbent, før du får en ekstra påmindelse om at det stadig er åbent — påvirker ikke selve sluk-funktionen ovenfor.",
        })}
        ${this._cfgToggleRow("Notifikation ved åbent vindue", "notify_windows", !!d.notify_windows, "Send en notifikation når et vindue åbnes eller lukkes.")}
        ${this._cfgToggleRow("30-minutters-advarsel", "notify_window_warning_30", !!d.notify_window_warning_30, "Send en ekstra påmindelse hvis vinduet stadig er åbent efter tiden angivet i «Advarsel efter» ovenfor.")}
        <div class="section-box-footer">Styrer hvornår og hvordan varmen slås fra, når et vindue står åbent — og hvornår du får besked om det.</div>
      </div>

      <div class="${this._cfgSectionClass('night_setback')}" data-section-id="night_setback">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Nat-sætpunkt</div>
          <div class="section-box-badge" data-badge-field="night_setback_enabled" style="background:${d.night_setback_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.night_setback_enabled ? "#818cf8" : "var(--sub)"}">
            ${this._cfgStatusDot(!!d.night_setback_enabled)}${d.night_setback_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("Nat-sætpunkt aktiveret", "night_setback_enabled", !!d.night_setback_enabled)}
        ${this._cfgNumberRow("Temperatur (sænkning)", "night_setback_temp", d.night_setback_temp ?? "", {
          min: 0.5, max: 5.0, step: 0.5, unit: "°C", cast: "float",
          desc: "Antal grader der trækkes fra måltemperaturen i nat-perioden. Går aldrig under laveste rumtemperatur (Temperaturgrænser).",
        })}
        ${this._cfgNumberRow("Start time", "night_start_hour", d.night_start_hour ?? "", {
          min: 18, max: 23, step: 1, unit: "h", cast: "int",
          desc: "Klokkeslæt (lokal tid) hvor nat-sænkningen begynder.",
        })}
        ${this._cfgNumberRow("Slut time", "night_end_hour", d.night_end_hour ?? "", {
          min: 4, max: 10, step: 1, unit: "h", cast: "int",
          desc: "Klokkeslæt (lokal tid) hvor rummet igen varmer til fuld måltemperatur.",
        })}
        <div class="section-box-footer">Sænker rummenes måltemperatur automatisk i nat-perioden og hæver den igen om morgenen.</div>
      </div>

      <div class="${this._cfgSectionClass('grace')}" data-section-id="grace">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Grace-perioder</div>
        </div>
        ${this._cfgNumberRow("Dag", "grace_day_min", d.grace_day_min ?? "", {
          min: 5, max: 120, step: 5, unit: "min", cast: "int",
          desc: "Hvor længe der ventes, efter alle er gået, før huset om dagen sættes på fraværstemperatur.",
        })}
        ${this._cfgNumberRow("Nat", "grace_night_min", d.grace_night_min ?? "", {
          min: 5, max: 60, step: 5, unit: "min", cast: "int",
          desc: "Samme ventetid, men om natten — typisk kortere, da man sjældent forlader huset midt om natten uden grund.",
        })}
        <div class="section-box-footer">Hvor længe Heat Manager venter, efter alle er gået hjemmefra, før et rum rent faktisk sættes på fraværstemperatur — så en kort tur ud til bilen ikke udløser unødig nedkøling.</div>
      </div>

      <div class="${this._cfgSectionClass('auto_off')}" data-section-id="auto_off">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Auto-off ved mildt vejr</div>
        </div>
        ${this._cfgNumberRow("Temperaturgrænse", "auto_off_temp_threshold", d.auto_off_temp_threshold ?? "", {
          min: 10, max: 30, step: 1, unit: "°C", cast: "float",
          desc: "Udetemperatur hvorover en dag tæller med i rækken af milde dage nedenfor.",
        })}
        ${this._cfgNumberRow("Dage i træk", "auto_off_temp_days", d.auto_off_temp_days ?? "", {
          min: 1, max: 14, step: 1, unit: "dage", cast: "int",
          desc: "Antal sammenhængende dage over temperaturgrænsen, før hele huset automatisk slukkes for sæsonen.",
        })}
        <div class="section-box-footer">Slukker automatisk hele huset for sæsonen, hvis udetemperaturen holder sig over grænsen i det angivne antal dage i træk — typisk relevant i overgangen til forår/sommer.</div>
      </div>

      <div class="${this._cfgSectionClass('notifications')}" data-section-id="notifications">
        <div class="section-box-header collapsible" data-action="toggle-section">
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
            <div style="margin-top:4px">
              ${this._cfgToggleRow("Tilstedeværelse/fravær", "notify_presence", !!d.notify_presence, "Send en notifikation når nogen kommer hjem, eller alle går.")}
              ${this._cfgToggleRow("Forvarmning", "notify_preheat", !!d.notify_preheat, "Send en notifikation når forvarmning starter forud for en persons hjemkomst.")}
              ${this._cfgToggleRow("Skimmelrisiko", "notify_mold_risk", !!d.notify_mold_risk, "Send en notifikation når høj luftfugtighed tæt på dugpunktet registreres i et rum.")}
              ${this._cfgToggleRow("Eskalér langvarige problemer", "notify_issue_escalation", !!d.notify_issue_escalation, "Send én notifikation når et statuscenter-problem har stået på uafbrudt i mindst så mange minutter som angivet nedenfor.")}
              ${this._cfgNumberRow("Eskalér efter", "issue_escalation_minutes", d.issue_escalation_minutes ?? "", {
                min: 10, max: 360, step: 10, unit: "min", cast: "int",
                desc: "Et statuscenter-problem (skimmel, åbent vindue, langsom opvarmning m.fl.) der har stået på uafbrudt i så mange minutter, sender én push-notifikation.",
              })}
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
            </div>
          </div>` : ''}

        </div>
        <div class="section-box-footer">Vælg hvilke hændelser der sender en push-notifikation via Home Assistants notify-tjeneste, og/eller en talt meddelelse via House Voice, hvis den er installeret.</div>
      </div>

      <div class="${this._cfgSectionClass('rooms_summary')}" data-section-id="rooms_summary">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Rum &amp; klimaentiteter</div>
        </div>
        ${(this._data?.rooms ?? []).map(r => {
          // v0.9.0: read-only summary of the optional per-room engines —
          // configure these via the config-flow wizard (reconfigure flow),
          // not from this panel.
          const extras = [];
          if (r.calibration_entity) extras.push("🎚 Kalibrering");
          if (r.sync_mode && r.sync_mode !== "disabled") extras.push(`🔄 Sync: ${this._syncModeLabel(r.sync_mode)}`);
          if (r.schedule_entity) extras.push("🗓 Schedule");
          return `<div class="cfg-row">
            <span class="cfg-k">${this._esc(r.name)}</span>
            <span class="cfg-v" style="color:${this._stateColor(r.state ?? "normal")}">${this._esc(r.climate_entity ?? "–")}</span>
          </div>` + (extras.length ? `<div class="cfg-row" style="padding-top:0">
            <span class="cfg-k"></span>
            <span class="cfg-v" style="font-size:11px;font-weight:400;color:var(--sub)">${this._esc(extras.join(" · "))}</span>
          </div>` : "");
        }).join("") || `<div class="empty">Ingen rum</div>`}
        <div class="section-box-footer">Skrivebeskyttet oversigt over hvert rums klimaentitet og valgfrie ekstrafunktioner. Ændres via Home Assistants rekonfigurering af integrationen.</div>
      </div>
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
        <div id="toast-container" class="toast-container" role="status" aria-live="polite"></div>
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
    // v0.32.0: status center replaces cloud-chip/health-chip/ws-error-chip/
    // remote-last-action-box — one patch call instead of four, and (per the
    // 2026-09-11 statustjek lesson this comment used to document) it's
    // called from BOTH the full-render path here and _patchAll(), so a fresh
    // page load never sits stuck on stale/hidden status for up to a 60s poll.
    this._patchStatusCenter();
    this._schedulePulseEnd(); // v0.59.0
    this._startPauseCountdown();
    this._startBoostCountdown();
    this._attachEvents();
  }

  _attachEvents() {
    const root = this.shadowRoot;
    root.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
      this._tab = btn.dataset.tab;
      // 2026-09-19 (ønske: alle 14 sektioner altid ens når man lander på
      // siden): fold-tilstand blev tidligere husket på ubestemt tid (se
      // v0.57.1) — nyttigt så en gemning ikke klapper den sektion man lige
      // sad i, men det betød også at en sektion åbnet for lang tid siden
      // stod åben igen, hver gang man kom tilbage til fanen, og så anderledes
      // ud end resten. Nulstilles nu hver gang man klikker IND på
      // Konfiguration — alle 14 starter garanteret sammenfoldet og ens ved
      // hvert besøg, mens en sektion stadig får lov at blive stående åben
      // så længe man rent faktisk er i gang med at redigere i den.
      if (this._tab === "config") this._expandedConfigSections.clear();
      if (this._tab === "history" && !this._history) this._loadHistory().then(() => this._scheduleRender());
      else this._scheduleRender();
    }));
    root.querySelector("[data-action='refresh']")?.addEventListener("click", () => this._load(true));
    // 2026-09-16 ("Sæson"-kontrol): mirrors controller_state's own
    // set_controller_state service call, but season_mode has no equivalent
    // custom service — calling HA's built-in select.select_option directly
    // on the existing select.<entry>_season_mode entity (already tracked in
    // this._seasonEntityId for the read-only display above) does exactly
    // what select.py's own SeasonModeSelect.async_select_option does, with
    // no backend changes needed. Bound once here since the <select> element
    // itself persists across _patchControllerHero() polls (only its
    // .value is patched, never replaced).
    root.querySelector(".ctrl-season-select")?.addEventListener("change", async (e) => {
      const option = e.target.value;
      const seasonLabel = ({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[option] ?? option;
      if (!this._seasonEntityId) {
        this._showToast("Sæson-entity ikke fundet", "error");
        return;
      }
      try {
        await this._hass.callService("select", "select_option", { entity_id: this._seasonEntityId, option });
        if (this._data) this._data.season_mode = option;
        this._showToast(`Sæson sat til ${seasonLabel}`, "success");
      } catch (err) {
        this._showToast("Kunne ikke skifte sæson", "error");
      }
    });
    root.querySelector("[data-action='on']"    )?.addEventListener("click", () => this._setController("on"));
    // 2026-09-07 audit fix (UI/UX-5): "Sluk hele huset" had no confirmation
    // at all — one misclick turned off heating for every room. Click-to-arm
    // instead of a blocking native confirm(), consistent with the rest of
    // this panel's non-blocking UI (toasts, inline patches).
    root.querySelector("[data-action='off']"   )?.addEventListener("click", (e) => {
      const btn = e.currentTarget;
      if (btn.dataset.confirmOff === "1") {
        clearTimeout(this._offConfirmTimer);
        delete btn.dataset.confirmOff;
        btn.textContent = btn.dataset.offOrigLabel || "❄️ Sluk";
        this._setController("off");
        return;
      }
      btn.dataset.offOrigLabel = btn.dataset.offOrigLabel || btn.textContent;
      btn.dataset.confirmOff = "1";
      btn.textContent = "Tryk igen for at slukke";
      this._offConfirmTimer = setTimeout(() => {
        delete btn.dataset.confirmOff;
        btn.textContent = btn.dataset.offOrigLabel;
      }, 3000);
    });
    root.querySelector("[data-action='resume']")?.addEventListener("click", () => this._resume());
    root.querySelector("[data-action='pause']" )?.addEventListener("click", () => {
      const min = parseInt(root.querySelector("#pause-dur")?.value ?? "120", 10);
      this._pause(min);
    });

    // B18 Fase 3: the old global group_offset slider is gone — per-room
    // offset sliders + group toggles are wired in _attachRoomDetailEvents(),
    // called both here and from _patchRoomsTab() since that rebuilds the
    // rows' innerHTML on every poll.

    // Boost button active-state + countdown syncing now lives in
    // _patchControllerHero(), called on every refresh via _patchAll() —
    // see that method for why the old one-time sync here was insufficient.

    // D) Boost button — toggles boost service if available
    root.querySelector("[data-action='boost']")?.addEventListener("click", async () => {
      const btn = root.querySelector("#ctrl-btn-boost");
      if (!btn) return;
      const isActive = btn.classList.contains("active");
      try {
        const result = await this._hass.callWS({ type: isActive ? "heat_manager/boost_stop" : "heat_manager/boost_start" });
        // Reflect immediately instead of waiting for the next 30 s poll —
        // _load() below will reconcile with authoritative backend data shortly.
        if (this._data) {
          this._data.boost_remaining_minutes = isActive ? 0 : (result?.boost_remaining_minutes ?? 30);
          (this._data.rooms ?? []).forEach(r => { r.boost_active = !isActive; });
        }
        this._patchControllerHero();
        this._startBoostCountdown();
        this._showToast(isActive ? "Boost deaktiveret" : "Boost aktiveret", "success"); // v0.3.9
        // Refresh data so room cards update
        setTimeout(() => this._load(), 300);
      } catch (e) {
        btn.style.opacity = "0.4";
        setTimeout(() => { btn.style.opacity = ""; }, 800);
        this._showToast("Kunne ikke ændre boost-tilstand", "error"); // v0.3.9
        console.info("[HeatManager] boost WS failed:", e);
      }
    });
    // v0.60.0: the smart status line's clicks are delegated from the root
    // listener in connectedCallback() (bound once) — not here, since this
    // method runs on every full render and shadowRoot is never recreated.

    // Manual TRV control toggle — persisted server-side since 2026-09-13
    // (was a plain JS field, reset on every page reload).
    root.querySelector("[data-action='toggle-manual-control']")?.addEventListener("click", async () => {
      const newVal = !this._manualControlEnabled;
      this._manualControlEnabled = newVal;      // optimistic — reflect immediately
      this._scheduleRender();
      try {
        await this._hass.callWS({
          type: "heat_manager/update_config",
          manual_trv_control: newVal,
        });
        if (this._data?.config) this._data.config.manual_trv_control = newVal;
      } catch (e) {
        this._manualControlEnabled = !newVal;   // revert — save failed
        this._scheduleRender();
        this._showToast("Kunne ikke gemme Manuel TRV-kontrol", "error");
        console.error("Heat Manager: save manual_trv_control failed", e);
      }
    });

    // Manual-control slider/send/reset + B18 Fase 3 grouping controls — see
    // _attachRoomDetailEvents(): extracted so _patchRoomsTab() can re-wire
    // them too, since it rebuilds .rooms-detail-container's innerHTML on
    // every poll (losing whatever listeners were attached here otherwise).
    this._attachRoomDetailEvents();

    // Punkt 5 (2026-09-14) — sammenklappelige sektioner i Konfiguration-
    // fanen. 2026-09-19 fix: state is now ALSO tracked in
    // this._expandedConfigSections (keyed by each section's stable
    // data-section-id), not just the DOM's .collapsed class — a full
    // rebuild of _configTabHTML() (which every field save triggers, via
    // _scheduleRender()) used to hardcode every section back to collapsed,
    // snapping shut whatever the user had just opened right as they
    // clicked a toggle inside it. See _css() for the matching collapse rule.
    root.querySelectorAll(".section-box-header.collapsible").forEach((header) => {
      header.addEventListener("click", () => {
        const box = header.closest(".section-box");
        if (!box) return;
        const isNowCollapsed = box.classList.toggle("collapsed");
        const sectionId = box.dataset.sectionId;
        if (sectionId) {
          if (isNowCollapsed) this._expandedConfigSections.delete(sectionId);
          else this._expandedConfigSections.add(sectionId);
        }
      });
    });

    // G) History manual refresh
    root.querySelector("[data-action='refresh-history']")?.addEventListener("click", async () => {
      this._history = null;
      this._historyFetchedAt = null;
      await this._loadHistory();
      this._patchHistoryTab();
    });

    // v0.3.9: event-type filter chips (Historik tab). Delegated on the wrapper
    // so the listener survives _patchHistoryTab() rebuilding the chip buttons.
    root.querySelector("#hist-filter-row")?.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".hist-filter-chip");
      if (!btn) return;
      this._historyFilter = btn.dataset.filter;
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
      } catch(e) {
        this._showToast("Kunne ikke gemme alarm-panel", "error"); // v0.3.9
        console.error("Heat Manager: save alarm failed", e);
      }
      btn.disabled = false;
    });

    root.querySelectorAll("[data-action='toggle-alarm-state']").forEach((chip) => {
      chip.addEventListener("click", async () => {
        const chips = [...root.querySelectorAll("[data-action='toggle-alarm-state']")];
        chip.classList.toggle("active");
        const states = chips.filter(c => c.classList.contains("active")).map(c => c.dataset.state);
        chips.forEach(c => { c.disabled = true; });
        try {
          await this._hass.callWS({ type: "heat_manager/update_config", alarm_away_states: states });
          if (this._data?.config) this._data.config.alarm_away_states = states;
          chip.setAttribute("aria-pressed", String(chip.classList.contains("active")));
          const footer = chip.closest("[data-section-id='alarm']")?.querySelector(".section-box-footer");
          if (footer) footer.innerHTML = this._alarmFooterText(states);
        } catch (e) {
          chip.classList.toggle("active"); // revert
          this._showToast("Kunne ikke gemme alarmtilstande", "error");
          console.error("Heat Manager: save alarm states failed", e);
        }
        chips.forEach(c => { c.disabled = false; });
      });
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
      } catch(e) {
        this._showToast("Kunne ikke gemme notify-service", "error"); // v0.3.9
        console.error("Heat Manager: save notify failed", e);
      }
      btn.disabled = false;
    });

    // ── Config tab: "Indstillinger" generic field save (Fase 2, del 1, 2026-09-13) ──
    // One handler for every numeric field the settings sections above add
    // (PID, Boost, Vindue, Nat-sætpunkt, Grace, Auto-off), instead of a
    // hand-written save-* handler per field like save-alarm/save-notify
    // above — see _cfgNumberRow()/_cfgToggleRow() and websocket.py's
    // matching _NUMERIC_CONFIG_FIELDS/_BOOL_CONFIG_FIELD_DEFAULTS tables.
    root.querySelectorAll("[data-action='save-netatmo-away']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const entityId = btn.dataset.entity;
        const input = root.querySelector("#cfg-netatmo-away-input");
        const ok    = root.querySelector("#cfg-netatmo-away-ok");
        const value = parseFloat(input?.value ?? "");
        if (!entityId || Number.isNaN(value)) {
          this._showToast("Ugyldig værdi", "error");
          return;
        }
        btn.disabled = true;
        try {
          await this._hass.callService("number", "set_value", { entity_id: entityId, value });
          if (this._data?.netatmo_away_temp) this._data.netatmo_away_temp.value = value;
          ok?.classList.add("visible");
          setTimeout(() => ok?.classList.remove("visible"), 2500);
        } catch (e) {
          this._showToast("Kunne ikke gemme fraværstemperaturen i Netatmo", "error");
          console.error("Heat Manager: set Netatmo away temperature failed", e);
        }
        btn.disabled = false;
      });
    });

    root.querySelectorAll("[data-action='save-field']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const field = btn.dataset.field;
        const cast  = btn.dataset.cast || "float";
        const input = root.querySelector(`#cfg-${field}-input`);
        const ok    = root.querySelector(`#cfg-${field}-ok`);
        if (!input) return;
        const raw   = cast === "int" ? parseInt(input.value, 10) : parseFloat(input.value);
        if (Number.isNaN(raw)) {
          this._showToast("Ugyldig værdi", "error");
          return;
        }
        btn.disabled = true;
        try {
          const res = await this._hass.callWS({
            type: "heat_manager/update_config",
            [field]: raw,
          });
          if (res?.updated !== false) {
            if (this._data?.config) this._data.config[field] = raw;
            ok?.classList.add("visible");
            setTimeout(() => ok?.classList.remove("visible"), 2500);
          }
        } catch (e) {
          this._showToast(`Kunne ikke gemme ${field}`, "error");
          console.error(`Heat Manager: save ${field} failed`, e);
        }
        btn.disabled = false;
      });
    });

    // Generic boolean toggle save — mirrors toggle-manual-control above
    // (optimistic update, revert + toast on failure), for every bool field
    // added by _cfgToggleRow() (PID enabled, night setback enabled, window/
    // presence/preheat notify toggles).
    // 2026-09-19 (fold-tilstand-fix, endelig version): this used to call
    // _scheduleRender() on both the optimistic update AND any revert —
    // regenerating the WHOLE Konfiguration tab from scratch every single
    // toggle. Even with the per-section fold-state Set (v0.57.1) and the
    // per-tab-entry reset (v0.58.1), a full rebuild is simply the wrong
    // tool for "one boolean changed": it's the root cause of every
    // collapse/expand confusion this evening, since ANY full render
    // reapplies the ENTIRE section list from the template literal. Fixed
    // properly this time by never touching the DOM tree at all beyond the
    // one button and its section's own badge (via the new data-badge-field
    // attribute on the five Aktiv/Inaktiv-badged sections) — the section's
    // open/closed state literally cannot change, because nothing about the
    // section's own DOM node is ever replaced.
    root.querySelectorAll("[data-action='toggle-field']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const field   = btn.dataset.field;
        const current = !!(this._data?.config?.[field] ?? false);
        const newVal  = !current;

        const applyVisual = (on) => {
          btn.textContent = on ? "Slå fra" : "Slå til";
          btn.classList.toggle("active", on);
          const badge = btn.closest(".section-box")?.querySelector(
            `[data-badge-field="${field}"]`
          );
          if (badge) {
            badge.style.background = on ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)";
            badge.style.color = on ? "#818cf8" : "var(--sub)";
            badge.innerHTML = `${this._cfgStatusDot(on)}${on ? "Aktiv" : "Inaktiv"}`;
          }
        };

        if (this._data?.config) this._data.config[field] = newVal; // optimistic
        applyVisual(newVal);
        try {
          await this._hass.callWS({
            type: "heat_manager/update_config",
            [field]: newVal,
          });
        } catch (e) {
          if (this._data?.config) this._data.config[field] = current; // revert
          applyVisual(current);
          this._showToast(`Kunne ikke gemme ${field}`, "error");
          console.error(`Heat Manager: save ${field} failed`, e);
        }
      });
    });
  }
}

if (!customElements.get("heat-manager-panel")) {
  customElements.define("heat-manager-panel", HeatManagerPanel);
}
