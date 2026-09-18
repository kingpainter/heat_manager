// Heat Manager Panel
// Version: 0.17.2 (comment log below is stale — see manifest.json for the
// actual running version; panel.py reads it from there at runtime, not
// from this comment. See CHANGELOG.md for everything since v0.17.2.)
//
// v0.22.0 (2026-09-11 — "Energi i dag" removed):
//   • The waste-calculator-based "Energi i dag" section (spildt/sparet kWh,
//     efficiency ring) and the Historik tab's "Energi — sidste 7 dage" bar
//     chart are removed entirely, at the user's request: the whole model
//     estimates kWh from an assumed electrical radiator wattage
//     (CONF_ROOM_WATTAGE), which has no meaning for a district-heating
//     (fjernvarme) system with no water/heat metering — the numbers were
//     never real. Removed backend-side too: WasteCalculator, its 5
//     coordinator properties/tick/shutdown hooks, the 3 sensor entities
//     (EnergyWastedSensor/EnergySavedSensor/EfficiencyScoreSensor), the
//     HeatingWastedSensor binary sensor, CONF_ENERGY_TRACKING/
//     CONF_ROOM_WATTAGE config, and the ws_get_state()/get_history() fields.
//     engine/waste_calculator.py is left in place but fully disconnected —
//     safe to delete manually.
//   • Fixed a third instance of the display-vs-[hidden] bug (see v0.21.0
//     below): #remote-last-action-box (the "📡" pill) used an inline
//     style="display:flex", which beats every stylesheet rule including the
//     [hidden] override added in v0.21.0 — so it was PERMANENTLY visible as
//     an empty pill whenever there was no recent remote-control action.
//     Moved the layout into a .remote-last-action-box class covered by the
//     same [hidden] override.
//
// v0.21.0 (2026-09-11 statustjek):
//   • Fixed a real, confirmed-by-screenshot bug: #cloud-chip, #health-chip
//     and #ws-error-chip all set `display` unconditionally in their own
//     CSS class, which — because author CSS always wins over the browser's
//     default `[hidden] { display: none }` rule, regardless of selector
//     specificity — completely neutralised `chip.hidden = true/false`.
//     #cloud-chip/#health-chip were permanently visible as empty pills
//     (label only ever gets text when there's an issue) and #ws-error-chip
//     was very likely showing "Ingen forbindelse" all the time, defeating
//     the 2026-09-07 UI/UX-2 fix it exists for. Added the missing
//     `.cloud-chip[hidden], .ws-error-chip[hidden] { display: none; }`.
//   • _cloudStatus() previously only flagged "Netatmo cloud nede" when
//     EVERY configured room's climate entity was unavailable at once — a
//     partial outage (2 of 5 rooms down, say) silently reported `ok: true`
//     and never showed anything. Now three distinct, separately-worded
//     states: all rooms down (cloud/gateway — see docstring), some rooms
//     down (single device, more likely battery/RF), or stale-but-available
//     (cloud responding, not updating).
//   • #ws-error-chip now shows the last-known-good time ("Ingen forbindelse
//     — sidst OK kl. HH:MM") instead of a static, undated message.
//   • _render() (the full first-load render path) was missing the
//     _patchWsErrorChip()/_patchRemoteLastAction() calls that _patchAll()
//     already had — both could sit stuck in their template-default hidden
//     state for up to a 60s poll cycle after a fresh page load.
//   • See audit/heat_manager_status_check_2026-09-11.md for the full
//     analysis, including why a true "gateway" layer distinct from
//     "cloud" isn't observable from HA's own Netatmo integration for
//     thermostat/valve devices.
//
// v0.17.2:
//   • Frontend-parity + health-check pass. New per-room "Rum detaljer" chips
//     for PID power, calibration offset and window-open-minutes-today (all
//     3 computed by the backend already but only ever visible via HA's own
//     entity page — see sensor.py's enabled_default flip and websocket.py's
//     ws_get_state() this same session). New "entity health" topbar chip
//     (#health-chip/_patchHealthChip()), separate from the existing Netatmo
//     cloud chip — covers every entity a room actually depends on (all
//     TRVs, not just the primary; window/humidity/CO2/battery sensors too),
//     not just Netatmo cloud staleness. Removed the dead full-width
//     _cloudBannerHTML() (superseded by the topbar chip since v0.16.0,
//     never actually called).
//
// v0.17.0:
//   • Oversigt-cards now show humidity/CO2 chips, a mold-risk badge, and a
//     sync-mode/schedule/TRV-count meta row — data that already existed in
//     the get_state payload but was only ever shown in the Rum-detaljer tab.
//
// v0.16.0:
//   • Version banner corrected — this file had said 0.3.10 since before
//     v0.9.1's frontend surfacing work, several releases out of date.
//   • Removed dead code left over from the removed "Energi i dag" card:
//     _patchEnergyToday(), _reasonLabel(), _seasonTriggerLabel(),
//     _energyTodaySectionHTML() (2.2).
//   • Backend/frontend audit fix pass — see CHANGELOG.md.
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
//
// v0.3.9 — UI/UX pass:
//   • Overview: new "Energi i dag" card (sparet/spildt kWh + efficiency ring),
//     using energy_saved_today/energy_wasted_today/efficiency_score (already
//     in the get_state payload).
//   • Controller hero: third meta-chip shows the *effective* season
//     (Dvale/Opvågning/Aktiv) with icon. Also fixes a pre-existing bug where
//     "Effektiv sæson" on the auto-off card always showed "–" because it was
//     looked up in the calendar-season label map (winter/summer/...) instead
//     of the DORMANT/WAKING/ACTIVE map.
//   • Rum tab: TRV-type badge (Netatmo/Zigbee) per room detail row. Backend
//     now includes "trv_type" in the room payload (websocket.py).
//   • Historik tab: weekly energy chart (existing _energyChartHTML, formerly
//     only on Rum tab) moved above the event log, plus filter chips to show
//     only one event type (alle/normal/away/window/boost/manual/override).
//   • Toast notifications: action failures (boost, manual TRV, config save)
//     now surface a dismissible toast instead of only console.error.
//   • a11y: cloud-status dismiss button gets aria-label; tab buttons get
//     role="tab"/aria-selected.
//
// v0.3.10:
//   • Boost button active/countdown state was only ever synced once, at the
//     panel's very first render (_attachEvents()) — every later 30 s refresh
//     went through _patchAll() instead, which never touched it. A boost
//     stopped externally (backend auto-expiry, the heat_manager.boost_stop
//     service, another client) left the button stuck "active" until a full
//     reload. Sync moved into _patchControllerHero(), called every refresh.
//   • Boost button now shows a live "⚡ Boost (N min)" countdown using
//     boost_remaining_minutes from the WS payload. New _startBoostCountdown()
//     mirrors the existing _startPauseCountdown() 60 s local-tick pattern.

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
    this._historyFilter   = "all"; // v0.3.9: event-type filter on Historik tab
    this._toastTimer      = null;  // v0.3.9: auto-dismiss timer for toast
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
    // v0.32.0: close the status-center detail dropdown on any click outside
    // it. Bound once here (not in _attachEvents(), which re-runs on every
    // full render) — shadowRoot persists across renders, so a listener
    // added there would accumulate one extra copy per render instead of
    // being replaced with the old DOM.
    // v0.33.0: the same listener also drives the info-icon tooltips (point
    // 4 — hover on PC via CSS :hover/:focus, tap on mobile via this click
    // toggle) — one shared listener instead of a second one accumulating
    // alongside it.
    if (!this._outsideClickBound) {
      this._outsideClickBound = true;
      root.addEventListener("click", (e) => {
        if (this._statusCenterOpen && !e.target.closest?.("#status-center")) {
          this._statusCenterOpen = false;
          this._patchStatusCenter();
        }
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
  // (websocket.py's _build_active_issues()) directly. The one thing that
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

  _statusCenterHTML() {
    return `
      <div id="status-center" class="status-center ok" data-action="toggle-status-center"
        role="button" tabindex="0" aria-expanded="false" aria-label="Status, advarsler og fejl">
        <div class="status-center-main">
          <span class="status-center-icon">✓</span>
          <span class="status-center-text">Alt kører normalt</span>
          <span class="status-center-count" hidden></span>
        </div>
        <div id="status-center-detail" class="status-center-detail" hidden></div>
      </div>`;
  }

  _statusIssueRowHTML(issue) {
    return `
      <div class="status-issue-row sev-${issue.severity}">
        <span class="status-issue-icon">${issue.icon ?? "•"}</span>
        <span class="status-issue-text">${this._esc(issue.message)}</span>
      </div>`;
  }

  _patchStatusCenter() {
    const box = this.shadowRoot.querySelector("#status-center");
    if (!box) return;
    const issues = this._activeIssues();
    const hasCritical = issues.some(i => i.severity === "critical");
    const hasWarning  = issues.some(i => i.severity === "warning");

    box.classList.toggle("ok", issues.length === 0);
    box.classList.toggle("has-critical", hasCritical);
    box.classList.toggle("has-warning", !hasCritical && hasWarning);
    box.classList.toggle("has-info-only", !hasCritical && !hasWarning && issues.length > 0);
    box.setAttribute("aria-expanded", String(this._statusCenterOpen && issues.length > 0));

    const iconEl  = box.querySelector(".status-center-icon");
    const textEl  = box.querySelector(".status-center-text");
    const countEl = box.querySelector(".status-center-count");
    if (!issues.length) {
      iconEl.textContent  = "✓";
      textEl.textContent  = "Alt kører normalt";
      countEl.hidden = true;
    } else {
      iconEl.textContent = issues[0].icon ?? "•";
      textEl.textContent = issues[0].message;
      countEl.hidden = issues.length <= 1;
      if (issues.length > 1) countEl.textContent = `+${issues.length - 1}`;
    }

    const detail = box.querySelector("#status-center-detail");
    if (detail) {
      detail.hidden = !(this._statusCenterOpen && issues.length > 0);
      if (!detail.hidden) {
        detail.innerHTML = issues.map(i => this._statusIssueRowHTML(i)).join("");
      }
    }
  }

  // Update the version/temp/season line in the header without re-rendering topbar.
  _patchTopbarVersion() {
    const root   = this.shadowRoot;
    const verEl  = root.querySelector(".header-text .version");
    if (!verEl) return;
    const d      = this._data;
    const season = ({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[d?.season_mode] ?? "Auto";
    const otemp  = d?.outdoor_temp != null ? `${Math.round(d.outdoor_temp)}°C · ` : "";
    // 6.0 m/s mirrors const.py's WIND_FAST_MS — keep in sync if that changes.
    const wxIcons = [
      d?.precipitation > 0 ? "🌧️" : null,
      d?.wind_speed != null && d.wind_speed >= 6.0 ? "💨" : null,
    ].filter(Boolean).join(" ");
    verEl.textContent = `${otemp}${season}${wxIcons ? " · " + wxIcons : ""}`;
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
      const label   = this._stateLabel(state, room.override_source);
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
      card.className = `room-card state-${state}`;

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
        metaBadges.push(`<span class="room-meta-badge" title="Antal TRV'er i rummet">🔧 ${room.trv_count} TRV'er</span>`);
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
    const badge = root.querySelector(".section-box-badge");
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
          setTimeout(() => { btn.textContent = "Send ↗"; btn.classList.remove("sending"); }, 2000);
        } catch (e) {
          btn.textContent = "Fejl ✗";
          setTimeout(() => { btn.textContent = "Send ↗"; btn.classList.remove("sending"); }, 2000);
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
          this._showToast(`${roomName}: kunne ikke gendanne schedule`, "error"); // v0.3.9
          console.error("[HeatManager] reset_room_temp failed:", e);
        }
        setTimeout(() => { btn.textContent = "↺ Schedule"; }, 1500);
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
        setTimeout(() => { btn.textContent = "⚡ Tving til"; }, 1500);
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
          this._showToast("Ingen rum med TRV at sætte", "error");
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
        globalSendBtn.textContent = "Send til alle ↗";
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
        globalResetBtn.textContent = "↺ Alle til schedule";
        if (failed.length) {
          this._showToast(`${ok}/${rooms.length} rum gendannet — fejlede: ${failed.join(", ")}`, "error");
        } else {
          this._showToast(`${ok} rum gendannet til schedule`, "success");
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
    root.querySelectorAll("[data-action='save-room-field']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const roomName = btn.dataset.room;
        const field    = btn.dataset.field;
        const cast     = btn.dataset.cast || "float";
        const row      = btn.closest(".cfg-edit-row");
        const input    = row?.querySelector(".room-cfg-input");
        const ok       = row?.querySelector(".room-cfg-ok");
        if (!input || !roomName || !field) return;
        const raw = cast === "int" ? parseInt(input.value, 10) : parseFloat(input.value);
        if (Number.isNaN(raw)) {
          this._showToast("Ugyldig værdi", "error");
          return;
        }
        btn.disabled = true;
        try {
          const res = await this._hass.callWS({
            type: "heat_manager/update_room_config",
            room_name: roomName,
            [field]: raw,
          });
          if (res?.updated !== false) {
            const room = (this._data?.rooms ?? []).find(r => r.name === roomName);
            if (room) room[field] = raw;
            ok?.classList.add("visible");
            setTimeout(() => ok?.classList.remove("visible"), 2500);
          }
        } catch (e) {
          const label = field === "comfort_temp" ? "target temp" : "away temp override";
          this._showToast(`${roomName}: kunne ikke gemme ${label}`, "error");
          console.error(`[HeatManager] save room ${field} failed for`, roomName, e);
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
  _fmt(val, unit, decimals = 0) {
    if (val == null) return "–";
    const n = parseFloat(val);
    return isNaN(n) ? "–" : n.toFixed(decimals) + "\u00a0" + unit;
  }

  // State labels & colours — heat semantics
  // v0.14.0: source param distinguishes who engaged OVERRIDE — "remote"
  // (RemoteButtonEngine) gets its own badge, "switch"/undefined keeps the
  // plain "Override" label as before.
  _stateLabel(s, source) {
    if (s === "override" && source === "remote") return "📡 Fjernbetjening";
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
  _trvBadgeHTML(trvType) {
    const info = ({
      netatmo: { label: "Netatmo", color: "#0ea5e9" },
      zigbee:  { label: "Zigbee",  color: "#22c55e" },
    })[trvType] ?? { label: trvType ?? "–", color: "#64748b" };
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
      .section-box.collapsed > *:not(.section-box-header) { display: none; }
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

      /* ── Status center (v0.32.0) ──
         Replaces the old cloud-chip / health-chip / ws-error-chip /
         remote-last-action-box quartet with one consolidated header field.
         Server computes almost everything into active_issues (see
         _build_active_issues() in websocket.py); the one thing the server
         genuinely cannot report on itself is its own dead connection, so
         that one issue is injected client-side in _activeIssues() and
         merged into the same sorted list before rendering here.

         Deliberately no unconditional display declaration on any element
         that also gets toggled via [hidden] below (#status-center-count,
         #status-center-detail) — an earlier generation of these chips had
         exactly that bug (own display rule always beats the browser's
         default [hidden] { display:none }, regardless of specificity),
         which permanently showed empty pills. See
         audit/heat_manager_status_check_2026-09-11.md for the history;
         not repeating it here. */
      .status-center {
        flex: 1 1 0%; max-width: 50%; min-width: 0;
        align-self: stretch; min-height: 90%;
        position: relative;
        display: flex; flex-direction: column; justify-content: center;
        padding: 6px 14px;
        border-radius: 12px;
        border: 1px solid var(--div);
        background: var(--bg2);
        cursor: pointer; font-family: 'DM Sans', sans-serif;
        transition: background .15s, border-color .15s;
      }
      .status-center.ok {
        border-color: rgba(34,197,94,0.3);
        background: rgba(34,197,94,0.08);
      }
      .status-center.has-info-only {
        border-color: rgba(148,163,184,0.35);
        background: rgba(148,163,184,0.08);
      }
      .status-center.has-warning {
        border-color: rgba(234,179,8,0.4);
        background: rgba(234,179,8,0.12);
      }
      .status-center.has-critical {
        border-color: rgba(239,68,68,0.45);
        background: rgba(239,68,68,0.15);
      }
      .status-center:hover { filter: brightness(1.15); }
      .status-center-main {
        display: flex; align-items: center; gap: 8px; min-width: 0;
      }
      .status-center-icon { font-size: 14px; flex-shrink: 0; }
      .status-center-text {
        font-size: 12px; font-weight: 600; color: var(--fg);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        flex: 1 1 auto; min-width: 0;
      }
      .status-center-count {
        font-size: 10px; font-weight: 700; color: var(--sub);
        background: rgba(148,163,184,0.15);
        border-radius: 10px; padding: 1px 6px; flex-shrink: 0;
      }
      .status-center-detail {
        position: absolute; top: calc(100% + 6px); left: 0; right: 0;
        z-index: 20; max-height: 260px; overflow-y: auto;
        background: var(--bg2); border: 1px solid var(--div);
        border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        padding: 6px;
      }
      .status-issue-row {
        display: flex; align-items: flex-start; gap: 8px;
        padding: 7px 8px; border-radius: 8px; font-size: 12px;
        cursor: default; text-align: left;
      }
      .status-issue-row + .status-issue-row { margin-top: 2px; }
      .status-issue-icon { flex-shrink: 0; }
      .status-issue-text { color: var(--fg); line-height: 1.35; }
      .status-issue-row.sev-critical { background: rgba(239,68,68,0.12); }
      .status-issue-row.sev-warning  { background: rgba(234,179,8,0.1); }
      .status-issue-row.sev-info     { background: rgba(148,163,184,0.08); }

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
  // websocket.py's _build_active_issues(), which the new status center
  // reads via `active_issues` (see _activeIssues()/_patchStatusCenter()
  // above). A full-width _cloudBannerHTML() was already removed here
  // earlier (2026-09, superseded by the topbar chips this removes in turn).

  _topbarHTML() {
    const d      = this._data;
    const ctrl   = d?.controller_state ?? "unknown";
    const season = ({ winter:"Vinter", spring:"Forår", summer:"Sommer", autumn:"Efterår", auto:"Auto" })[d?.season_mode] ?? "Auto";
    const otemp  = d?.outdoor_temp != null ? `${Math.round(d.outdoor_temp)}°C · ` : "";
    // 2026-09-07 audit fix (5.8): wind/precipitation were already read by
    // WindowEngine/WasteCalculator to shape delay/waste decisions but never
    // reached the panel payload at all — small icons next to outdoor temp.
    // 6.0 m/s mirrors const.py's WIND_FAST_MS — keep in sync if that changes.
    const wxIcons = [
      d?.precipitation > 0 ? "🌧️" : null,
      d?.wind_speed != null && d.wind_speed >= 6.0 ? "💨" : null,
    ].filter(Boolean).join(" ");
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
          <div class="version">${otemp}${season}${wxIcons ? " · " + wxIcons : ""}</div>
        </div>
        ${this._statusCenterHTML()}
        <div id="topbar-badge" class="topbar-badge"
          style="background:${bc.bg};color:${bc.color};border-color:${bc.border}">
          <div class="badge-dot" style="background:${bc.color}"></div>
          ${this._ctrlTitle(ctrl)}
        </div>
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

  // Build a single room card HTML string (with data-room-id for surgical patching).
  _roomCardHTML(room) {
    const state    = room.state ?? "normal";
    const color    = this._stateColor(state);
    const grad     = this._stateGradient(state);
    const label    = this._stateLabel(state, room.override_source);
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
      metaBadges.push(`<span class="room-meta-badge" title="Antal TRV'er i rummet">🔧 ${room.trv_count} TRV'er</span>`);
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
             <div class="room-temp-lbl">Rum temp</div>
           </div>
           <div class="room-temp-box">
             <div class="room-temp-val">${setpt ?? "–"}</div>
             <div class="room-temp-lbl">Target Temp</div>
           </div>
           <div class="room-temp-box">
             <div class="room-temp-val" style="${battColor ? `color:${battColor}` : ""}">${battStr}</div>
             <div class="room-temp-lbl">Trv batt</div>
           </div>
         </div>`
      : `<div class="room-temps" style="grid-template-columns:1fr">
           <div class="room-temp-box">
             <div class="room-temp-val">${tempStr}</div>
             <div class="room-temp-lbl">Rum temp</div>
           </div>
         </div>`;
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
  // now one of the entries websocket.py's _build_active_issues() folds into
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
    const state    = room.state ?? "normal";
    const color    = this._stateColor(state);
    // Rum temp = coordinator's best-available reading (external room_temp_sensor
    // when configured, else the TRV's own temp) — this is the room's real
    // temperature. Trv temp = the TRV's own current_temperature attribute,
    // shown separately since it sits on the radiator body and commonly reads
    // 1-3°C hot (see coordinator.get_room_current_temp docstring).
    const trvTemp  = room.climate_entity ? this._climateTemp(room.climate_entity) : null;
    const setpt    = this._roomSetpoint(room);
    const roomTempStr = room.current_temp != null ? (Math.round(room.current_temp * 10) / 10) + "°C" : "–";
    const trvTempStr  = trvTemp ?? "–";
    const battery     = room.battery_level != null ? Math.round(room.battery_level) : null;
    const batteryColor = battery == null ? "var(--sub)" : battery <= 15 ? "var(--red)" : battery <= 30 ? "var(--amber)" : "var(--sub)";
    const batteryStr  = battery != null ? `${battery}%` : "–";
    const humidityStr = room.humidity != null ? `${Math.round(room.humidity * 10) / 10}%` : null;
    const co2Str      = room.co2 != null ? `${Math.round(room.co2)} ppm` : null;
    const luxStr      = room.lux != null ? `${Math.round(room.lux)} lux` : null;
    // 2026-09 frontend-parity fix: these were computed by the backend
    // (PID's own power output, calibration_engine's last written offset,
    // RoomWindowDurationSensor's running total) but only ever visible via
    // HA's own entity page — same "Rum detaljer" pattern as humidity/CO2
    // above, just added a session later once ws_get_state() started
    // reporting them.
    const pidPowerStr  = room.pid_power != null ? `${Math.round(room.pid_power)}%` : null;
    const calibStr     = room.calibration_offset != null
      ? `${room.calibration_offset >= 0 ? "+" : ""}${room.calibration_offset.toFixed(1)}°C`
      : null;
    const windowDurStr = room.window_duration_today != null ? `${room.window_duration_today} min` : null;
    // 2026-09-11 door feature (level A visibility): only shown for rooms
    // actually connected to a configured interior door — room.door_open is
    // otherwise just "false" for every door-less room too, which would
    // silently show every room as "door closed".
    const connectedDoors = (this._data?.doors ?? []).filter(
      d => d.room_a === room.name || d.room_b === room.name
    );
    const doorStr = connectedDoors.length
      ? (room.door_open ? "Åben" : "Lukket")
      : null;
    const heatedDoorStr = room.has_heated_doors
      ? (room.heated_door_open ? "Åben" : "Lukket")
      : null;
    // 2026-09 audit fix (UI/UX #8): unavailable_entities lists every entity
    // this room depends on (all TRVs, window/humidity/CO2/battery sensors)
    // that's currently missing/unavailable/unknown — a small warning chip
    // here surfaces it without waiting for the top-level Netatmo-only
    // cloud banner to notice (a dead window-sensor battery, say, is not a
    // cloud outage and never trips that banner).
    const unavailableList = room.unavailable_entities ?? [];
    const valve    = room.valve_position != null ? Math.round(room.valve_position) : null;
    const isHeat   = valve != null && valve > 0;
    // v0.3.9 (B15); 2026-09-11: no badge at all for a monitoring-only room
    // with no TRV (room.trv_type is None — see websocket.py) rather than a
    // misleading "–" badge.
    const trvBadge = room.trv_type ? this._trvBadgeHTML(room.trv_type) : "";
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
          <span class="room-manual-lbl">Target Temp</span>
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
        <div class="room-manual-row" style="margin-top:6px">
          <button class="room-manual-force" data-room="${this._esc(room.name)}"
            title="Tving rummet til at varme nu, uanset tilstedeværelse/vindue (heat_manager.force_room_on)">⚡ Tving til</button>
        </div>
      </div>` : "";

    // B18 Fase 3: grouping controls — only rendered for rooms with 2+
    // physical TRVs (RoomOffsetNumber/RoomGroupToggleSwitch only exist for
    // those). group_enabled defaults true (matches coordinator.py's
    // room_group_enabled.get(name, True)) so a payload from before Fase 4
    // widened the backend (unlikely, but the field is new) still reads as
    // grouped rather than falsely "released".
    const trvCount     = room.trv_count ?? 1;
    const groupEnabled = room.group_enabled !== false;
    const roomOffset   = room.offset ?? 0;
    const groupingHTML = trvCount > 1 ? `
      <div class="room-grouping" data-room="${this._esc(room.name)}">
        <div class="room-group-row">
          <span class="room-group-lbl">🔗 Gruppe (${trvCount} TRV'er)</span>
          <button class="toggle-btn room-group-toggle${groupEnabled ? " active" : ""}"
            data-action="toggle-room-group" data-room="${this._esc(room.name)}">
            ${groupEnabled ? "Grupperet" : "Frigivet"}
          </button>
        </div>
        <div class="room-offset-row" style="margin-top:8px">
          <span class="room-offset-label">Offset</span>
          <input class="room-offset-slider" type="range" min="-5" max="5" step="0.5"
            value="${roomOffset}" data-room="${this._esc(room.name)}">
          <span class="room-offset-val" data-room="${this._esc(room.name)}">${(roomOffset >= 0 ? "+" : "") + roomOffset.toFixed(1)}°C</span>
        </div>
        ${!groupEnabled ? `<div style="font-size:10px;color:var(--sub);margin-top:6px;line-height:1.5">Ekstra TRV'er styres ikke af Heat Manager lige nu — kun den primære TRV følger skemaet.</div>` : ""}
      </div>` : "";

    // Rum detaljer: 4-stat row (Rum temp / Target Temp / Trv temp / Trv batt),
    // plus humidity/CO2 chips when the room has those sensors configured.
    // v0.33.0 (point 4): desc, when given, adds an _infoIcon() next to the
    // label — this is exactly the "hvad er hvad" confusion Flemming flagged
    // (set point vs. target temp vs. rum temp vs. trv temp) made explicit
    // in the UI itself instead of only in chat.
    const statBox = (label, value, color, desc = "") => `
           <div style="text-align:center">
             <div style="font-size:13px;font-weight:600;font-family:'DM Mono',monospace;color:${color ?? "var(--text)"}">${value}</div>
             <div style="font-size:9px;color:var(--sub);text-transform:uppercase;letter-spacing:.04em;margin-top:2px">${label}${desc ? this._infoIcon(desc) : ""}</div>
           </div>`;
    // 2026-09-11 (monitoring-only rooms): Target Temp/Trv temp/Trv batt are all
    // meaningless for a room with no TRV at all (e.g. "Gang") — same
    // reasoning as the Oversigt card fix above. Only Rum temp applies.
    const hasTrv = !!room.climate_entity;
    const roomTempDesc = "Rummets faktiske temperatur — fra ekstern temperatur-sensor hvis rummet har en, ellers TRV'ens egen sensor.";
    const targetTempDesc = "Den rumtemperatur Heat Manager forsøger at opnå lige nu (\"set point\") — comfort-temp efter skema, offset og evt. nat-sænkning. Ikke nødvendigvis det tal der sendes til TRV'en: PID'en oversætter dette til en styringsværdi for ventilen, som kan ligge et stykke over eller under selve target-temperaturen.";
    const trvTempDesc = "TRV'ens egen temperaturmåling. Den sidder på radiatoren og viser derfor typisk 1-3°C varmere end den faktiske rumtemperatur — brug Rum temp som den reelle temperatur.";
    const trvSetpointStr = room.trv_setpoint != null ? (Math.round(room.trv_setpoint * 10) / 10) + "°C" : "–";
    const trvSetpointDesc = "Det setpoint PID'en rent faktisk sender til TRV'en lige nu — efter effekt-beregning og setpoint-margin (se overshoot-fixet). Kan ligge et stykke over Target Temp, mens rummet stadig er langt fra sit mål. Vises kun når rummet er i normal, automatisk drift.";
    const statsRowHTML = hasTrv
      ? `<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-top:8px;padding-top:8px;border-top:1px solid var(--div)">
           ${statBox("Rum temp", roomTempStr, null, roomTempDesc)}
           ${statBox("Target Temp", setpt ?? "–", null, targetTempDesc)}
           ${statBox("Trv setpoint", trvSetpointStr, null, trvSetpointDesc)}
           ${statBox("Trv temp", trvTempStr, null, trvTempDesc)}
           ${statBox("Trv batt", batteryStr, batteryColor)}
         </div>`
      : `<div style="display:grid;grid-template-columns:1fr;gap:4px;margin-top:8px;padding-top:8px;border-top:1px solid var(--div)">
           ${statBox("Rum temp", roomTempStr, null, roomTempDesc)}
         </div>`;
    const extraSensorsHTML = (humidityStr || co2Str || luxStr || pidPowerStr || calibStr || windowDurStr || doorStr || heatedDoorStr || unavailableList.length) ? `
         <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
           ${humidityStr ? `<span style="font-size:10px;color:var(--sub)">💧 ${humidityStr}</span>` : ""}
           ${co2Str ? `<span style="font-size:10px;color:var(--sub)">🫧 CO₂ ${co2Str}</span>` : ""}
           ${luxStr ? `<span style="font-size:10px;color:var(--sub)">☀️ ${luxStr}</span>` : ""}
           ${pidPowerStr ? `<span style="font-size:10px;color:var(--sub)">⚙️ PID ${pidPowerStr}</span>` : ""}
           ${calibStr ? `<span style="font-size:10px;color:var(--sub)">🎯 ${calibStr}</span>` : ""}
           ${windowDurStr ? `<span style="font-size:10px;color:var(--sub)">🪟 ${windowDurStr} i dag</span>` : ""}
           ${doorStr ? `<span style="font-size:10px;color:var(--sub)">🚪 Dør ${doorStr}</span>` : ""}
           ${heatedDoorStr ? `<span style="font-size:10px;color:var(--sub)">🚪 Yderdør ${heatedDoorStr}</span>` : ""}
           ${unavailableList.length ? `<span style="font-size:10px;color:var(--red)" title="${this._esc(unavailableList.join(", "))}">⚠️ ${unavailableList.length} utilgængelig${unavailableList.length > 1 ? "e" : ""}</span>` : ""}
         </div>` : "";
    // Fase 2 (2026-09-11) — the user's `select.mit_hjem`-style visibility
    // request: what Netatmo's OWN cloud entity currently reports, shown
    // side by side with Heat Manager's "Target Temp" above so the two can
    // never be confused again the way they were before B21. Only present
    // for rooms with a Netatmo cloud climate entity (cloud_preset_mode etc.
    // are null for Zigbee/local rooms — see websocket.py ws_get_state()).
    // Actually switching the mode lives on the new
    // select.<room>_netatmo_preset_mode entity (select.py) — usable from
    // any standard HA dashboard/Entities page already; not yet wired into
    // this custom panel's own controls.
    const netatmoDiverges = room.cloud_temperature != null && room.target_temp != null
      && Math.abs(room.cloud_temperature - room.target_temp) >= 0.5;
    const netatmoHTML = (room.cloud_preset_mode || room.cloud_selected_schedule || room.cloud_temperature != null) ? `
         <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center">
           <span style="font-size:10px;color:var(--sub)">🛰️ Netatmo:</span>
           ${room.cloud_preset_mode ? `<span style="font-size:10px;color:var(--sub)">${this._esc(room.cloud_preset_mode)}</span>` : ""}
           ${room.cloud_selected_schedule ? `<span style="font-size:10px;color:var(--sub)">(${this._esc(room.cloud_selected_schedule)})</span>` : ""}
           ${room.cloud_hvac_action ? `<span style="font-size:10px;color:var(--sub)">${this._esc(room.cloud_hvac_action)}</span>` : ""}
           ${room.cloud_temperature != null ? `<span style="font-size:10px;color:${netatmoDiverges ? "var(--amber)" : "var(--sub)"}" title="Netatmo-appens eget sidst kendte sætpunkt for denne enhed — ikke det Heat Manager beder om">${(Math.round(room.cloud_temperature * 10) / 10)}°C${netatmoDiverges ? " ⚠" : ""}</span>` : ""}
         </div>` : "";

    // Punkt 3 (2026-09-13): inline live editing of Target temp/Away temp
    // override, directly in this room card — no options-flow round-trip.
    // Deliberately scoped to just these two fields (CO₂ threshold etc. stay
    // options-flow-only). Reuses the exact same cfg-edit-row/cfg-edit-input/
    // cfg-save-btn/cfg-save-ok visual pattern as the Indstillinger tab's
    // _cfgNumberRow() — but data-room/data-field-scoped instead of
    // id-scoped, since (unlike Indstillinger) many of these rows render at
    // once. Only for rooms with a TRV — nothing to target-temp-edit on a
    // monitoring-only room. See ws_update_room_config() in websocket.py.
    const awayTempDesc = "Rummets gulvtemperatur når huset er tomt eller om natten (bruges også som bund for nat-sætpunktet). Ikke det samme som den globale vindue-sluk-temperatur.";
    const roomCfgHTML = hasTrv ? `
         <div class="room-cfg-edit" data-room="${this._esc(room.name)}" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--div)">
           <div class="cfg-edit-row">
             <span class="cfg-edit-label" style="flex:0 0 130px">Target temp</span>
             <input class="cfg-edit-input room-cfg-input" type="number" min="15" max="26" step="0.5"
               value="${this._esc(room.comfort_temp ?? "")}"
               data-room="${this._esc(room.name)}" data-field="comfort_temp">
             <span class="cfg-edit-label" style="flex-shrink:0">°C</span>
             <button class="cfg-save-btn" data-action="save-room-field"
               data-room="${this._esc(room.name)}" data-field="comfort_temp" data-cast="float">Gem</button>
             <span class="cfg-save-ok room-cfg-ok" data-room="${this._esc(room.name)}" data-field="comfort_temp">✔</span>
           </div>
           <div class="cfg-edit-row">
             <span class="cfg-edit-label" style="flex:0 0 130px">Away temp${this._infoIcon(awayTempDesc)}</span>
             <input class="cfg-edit-input room-cfg-input" type="number" min="5" max="20" step="0.5"
               value="${this._esc(room.away_temp_override ?? "")}"
               data-room="${this._esc(room.name)}" data-field="away_temp_override">
             <span class="cfg-edit-label" style="flex-shrink:0">°C</span>
             <button class="cfg-save-btn" data-action="save-room-field"
               data-room="${this._esc(room.name)}" data-field="away_temp_override" data-cast="float">Gem</button>
             <span class="cfg-save-ok room-cfg-ok" data-room="${this._esc(room.name)}" data-field="away_temp_override">✔</span>
           </div>
         </div>` : "";

    return `
      <div class="room-detail-row" style="border-bottom:1px solid var(--div)">
        <div style="padding:12px 16px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
            <div style="display:flex;align-items:center;gap:6px">
              <span style="font-size:14px;font-weight:600">${this._esc(room.name)}</span>
              ${trvBadge}
              ${boostBadge}
            </div>
            <span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;background:${color}22;color:${color}">${this._stateLabel(state, room.override_source)}</span>
          </div>
          ${statsRowHTML}
          ${extraSensorsHTML}
          ${netatmoHTML}
          ${valveBar}
          ${roomCfgHTML}
        </div>
        ${manualHTML}
        ${groupingHTML}
      </div>`;
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
          <div class="section-box-title">Alle rum — Target Temp</div>
        </div>
        <div class="room-manual" style="padding:12px 16px">
          <div class="room-manual-row">
            <span class="room-manual-lbl">Target Temp</span>
            <input class="room-manual-slider global-manual-slider" type="range" min="10" max="28" step="0.5" value="20">
            <span class="room-manual-val global-manual-val">20°C</span>
          </div>
          <div class="room-manual-row" style="margin-top:6px">
            <span class="room-manual-lbl">Varighed</span>
            <select class="room-manual-dur global-manual-dur">
              <option value="30">30 min</option>
              <option value="60" selected>1 time</option>
              <option value="120">2 timer</option>
              <option value="0">Permanent</option>
            </select>
            <button class="room-manual-send global-manual-send" id="global-manual-send">Send til alle ↗</button>
            <button class="room-manual-reset global-manual-reset" id="global-manual-reset">↺ Alle til schedule</button>
          </div>
          <div style="font-size:10px;color:var(--sub);margin-top:6px">
            Sætter ${controllable} rum med TRV til samme temperatur — rum uden TRV (kun overvågning) springes over.
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
          <div class="section-box-badge rooms-detail-badge" style="background:rgba(249,115,22,0.15);color:var(--amber)">
            ${heatingCount} / ${rooms.length} varmer
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
    return `
      <div class="cfg-edit-row">
        <span class="cfg-edit-label" style="flex:0 0 150px">${this._esc(label)}${desc ? this._infoIcon(desc) : ""}</span>
        <input class="cfg-edit-input" type="number"
          id="cfg-${field}-input" min="${min}" max="${max}" step="${step}"
          value="${this._esc(value)}">
        ${unit ? `<span class="cfg-edit-label" style="flex-shrink:0">${this._esc(unit)}</span>` : ""}
        <button class="cfg-save-btn" data-action="save-field" data-field="${field}" data-cast="${cast}">Gem</button>
        <span class="cfg-save-ok" id="cfg-${field}-ok">✔</span>
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
      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Global konfiguration</div>
        </div>
        ${cfg.map(([k,v]) =>
          `<div class="cfg-row"><span class="cfg-k">${k}</span><span class="cfg-v">${this._esc(v)}</span></div>`
        ).join("")}
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
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
        <div class="section-box-header collapsible" data-action="toggle-section">
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

      <!-- Fase 2, del 1 (2026-09-13) — "Indstillinger": driftsparametre der
           før kun kunne ændres via options-flow'ets klik-igennem-dialog,
           flyttet hertil med samme live-gem-mønster som Alarmtavle ovenfor.
           Options-flow'en beholder de samme felter uændret (fallback for
           førstegangsopsætning) — se
           planning/heat_manager_fase2_spec_2026-09-11.md, "Del 1". -->

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">PID-regulator</div>
          <div class="section-box-badge" style="background:${d.pid_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.pid_enabled ? "#818cf8" : "var(--sub)"}">
            ${d.pid_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("PID-regulering aktiveret", "pid_enabled", !!d.pid_enabled)}
        ${this._cfgNumberRow("Kp", "pid_kp", d.pid_kp ?? "", { min: 0, max: 5, step: 0.05, cast: "float" })}
        ${this._cfgNumberRow("Ki", "pid_ki", d.pid_ki ?? "", { min: 0, max: 0.5, step: 0.01, cast: "float" })}
        ${this._cfgNumberRow("Kd", "pid_kd", d.pid_kd ?? "", { min: 0, max: 2, step: 0.05, cast: "float" })}
        ${this._cfgNumberRow("Setpoint-margin", "pid_setpoint_margin", d.pid_setpoint_margin ?? "", {
          min: 0.5, max: 6.0, step: 0.5, unit: "°C", cast: "float",
          desc: "2026-09-15: loft for hvor mange grader OVER rummets eget mål en TRV må blive bedt om at gå — uanset trv_max. Ved 100% PID-effekt sendte systemet før et setpoint helt op mod trv_max (fx 24°C ved et 21°C-mål), hvilket var årsagen til den observerede overskydning til 22-25°C. Sænk denne for tættere styring, hæv den hvis opvarmningen føles for langsom.",
        })}
      </div>

      <!-- 2026-09-13 (architekturgennemgang #5) — vejrkompensationskurven
           (udetemperatur → proaktivt effektbidrag oven i PID'en) fandtes
           allerede som en fast, altid-aktiv konstant. Nu konfigurerbar, med
           default = de tidligere hardkodede værdier, så eksisterende
           installationer opfører sig uændret indtil felterne rent faktisk
           redigeres her. -->
      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Vejrkompensation</div>
          <div class="section-box-badge" style="background:${d.weather_compensation_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.weather_compensation_enabled ? "#818cf8" : "var(--sub)"}">
            ${d.weather_compensation_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        <div style="padding:10px 16px 4px;font-size:12px;color:var(--sub);line-height:1.5">
          Tilføjer et proaktivt effektbidrag baseret på udetemperaturen, oven i PID'ens
          reaktive korrektion — en klassisk "varmekurve".
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
      </div>

      <!-- 2026-09-14 (punkt 7) — solindfald: reducerer PID-effekten pr. rum
           når sol.sol (sun.sun) er over horisonten og rummets lux-sensor
           (konfigureres pr. rum under "Rum & klimaentiteter"/rediger rum)
           viser lys. Genbruger de samme generiske toggle/number-rækker
           (og dermed den samme gem-logik) som Vejrkompensation ovenfor. -->
      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Solindfald</div>
          <div class="section-box-badge" style="background:${d.solar_gain_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.solar_gain_enabled ? "#818cf8" : "var(--sub)"}">
            ${d.solar_gain_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        <div style="padding:10px 16px 4px;font-size:12px;color:var(--sub);line-height:1.5">
          Reducerer PID-effekten i et rum, mens solen er oppe og rummets lux-sensor
          (sat pr. rum) viser lys — direkte sol gennem vinduerne kræver mindre varme
          fra TRV'en lige nu. Kun rum med en lux-sensor konfigureret påvirkes;
          nuværende: Stuen, Køkken, Gang.
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
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Dør-varmedeling</div>
          <div class="section-box-badge" style="background:${d.door_heat_share_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.door_heat_share_enabled ? "#818cf8" : "var(--sub)"}">
            ${d.door_heat_share_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        <div style="padding:10px 16px 4px;font-size:12px;color:var(--sub);line-height:1.5">
          Reducerer PID-effekten i et rum, når en åben indendørs dør (konfigureret
          under Rum &amp; klimaentiteter) fører til et varmere naborum der selv
          varmer aktivt lige nu. Ændrer ALDRIG rummets eget mål (comfort_temp) —
          kun den effekt TRV'en beder om. Forsvinder automatisk når døren lukkes
          eller naboen holder op med at varme.
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
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Boost — standardværdier</div>
        </div>
        <div style="padding:10px 16px 4px;font-size:12px;color:var(--sub);line-height:1.5">
          Bruges af Boost-knappen og <span style="font-family:'DM Mono',monospace">heat_manager.boost_start</span>,
          når intet andet angives eksplicit.
        </div>
        ${this._cfgNumberRow("Standardtemperatur", "boost_default_temp", d.boost_default_temp ?? "", { min: 15, max: 32, step: 0.5, unit: "°C", cast: "float" })}
        ${this._cfgNumberRow("Standardvarighed", "boost_default_minutes", d.boost_default_minutes ?? "", { min: 1, max: 240, step: 1, unit: "min", cast: "float" })}
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Vindue</div>
        </div>
        ${this._cfgNumberRow("Forsinkelse før sluk", "window_delay_default_min", d.window_delay_default_min ?? "", {
          min: 0, max: 60, step: 1, unit: "min", cast: "int",
          desc: "Hvor længe et vindue skal være åbent, før varmen reelt slås fra. Gælder alle rum. Sættes automatisk ned ved kraftig vind eller regn.",
        })}
        ${this._cfgNumberRow("Sluk-temperatur", "window_off_temp", d.window_off_temp ?? "", {
          min: 5, max: 20, step: 0.5, unit: "°C", cast: "float",
          desc: "Temperaturen der sendes til rummets TRV når varmen slås fra pga. åbent vindue. Uafhængig af PID'ens minimumstemperatur nedenfor.",
        })}
        ${this._cfgNumberRow("Advarsel efter", "window_warning_min", d.window_warning_min ?? "", {
          min: 5, max: 180, step: 5, unit: "min", cast: "int",
          desc: "Hvor længe et vindue skal have været åbent, før du får en ekstra påmindelse om at det stadig er åbent — påvirker ikke selve sluk-funktionen ovenfor.",
        })}
        ${this._cfgToggleRow("Notifikation ved åbent vindue", "notify_windows", !!d.notify_windows)}
        ${this._cfgToggleRow("30-minutters-advarsel", "notify_window_warning_30", !!d.notify_window_warning_30)}
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Nat-sætpunkt</div>
          <div class="section-box-badge" style="background:${d.night_setback_enabled ? "rgba(99,102,241,0.15)" : "rgba(71,85,105,0.15)"};color:${d.night_setback_enabled ? "#818cf8" : "var(--sub)"}">
            ${d.night_setback_enabled ? "Aktiv" : "Inaktiv"}
          </div>
        </div>
        ${this._cfgToggleRow("Nat-sætpunkt aktiveret", "night_setback_enabled", !!d.night_setback_enabled)}
        ${this._cfgNumberRow("Temperatur (sænkning)", "night_setback_temp", d.night_setback_temp ?? "", { min: 0.5, max: 5.0, step: 0.5, unit: "°C", cast: "float" })}
        ${this._cfgNumberRow("Start time", "night_start_hour", d.night_start_hour ?? "", { min: 18, max: 23, step: 1, unit: "h", cast: "int" })}
        ${this._cfgNumberRow("Slut time", "night_end_hour", d.night_end_hour ?? "", { min: 4, max: 10, step: 1, unit: "h", cast: "int" })}
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Grace-perioder</div>
        </div>
        ${this._cfgNumberRow("Dag", "grace_day_min", d.grace_day_min ?? "", { min: 5, max: 120, step: 5, unit: "min", cast: "int" })}
        ${this._cfgNumberRow("Nat", "grace_night_min", d.grace_night_min ?? "", { min: 5, max: 60, step: 5, unit: "min", cast: "int" })}
      </div>

      <div class="section-box">
        <div class="section-box-header collapsible" data-action="toggle-section">
          <div class="section-box-title">Auto-off ved mildt vejr</div>
        </div>
        ${this._cfgNumberRow("Temperaturgrænse", "auto_off_temp_threshold", d.auto_off_temp_threshold ?? "", { min: 10, max: 30, step: 1, unit: "°C", cast: "float" })}
        ${this._cfgNumberRow("Dage i træk", "auto_off_temp_days", d.auto_off_temp_days ?? "", { min: 1, max: 14, step: 1, unit: "dage", cast: "int" })}
      </div>

      <div class="section-box" style="padding:0">
        <div class="section-box-header collapsible" data-action="toggle-section" style="padding:12px 16px 10px;border-bottom:1px solid var(--div)">
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
              ${this._cfgToggleRow("Tilstedeværelse/fravær", "notify_presence", !!d.notify_presence)}
              ${this._cfgToggleRow("Forvarmning", "notify_preheat", !!d.notify_preheat)}
              ${this._cfgToggleRow("Skimmelrisiko", "notify_mold_risk", !!d.notify_mold_risk)}
              ${this._cfgToggleRow("Eskalér langvarige problemer", "notify_issue_escalation", !!d.notify_issue_escalation)}
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
      </div>

      <div class="section-box">
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
    this._startPauseCountdown();
    this._startBoostCountdown();
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
    // v0.32.0: status center — click/Enter toggles the detail dropdown.
    // Replaces the old per-chip dismiss-cloud-banner/dismiss-health-banner
    // handlers (no per-issue dismissal now — consolidating three chips into
    // one field already removes most of the reason to hide it). The
    // "click elsewhere closes it" listener is attached once from
    // connectedCallback() instead of here — this method runs on every full
    // render (see _scheduleRender()/_render()), and shadowRoot itself is
    // NOT recreated on a re-render, so a root-level listener added here
    // would stack up one extra copy per render instead of replacing itself.
    const statusCenter = root.querySelector("#status-center");
    if (statusCenter) {
      const toggle = () => {
        this._statusCenterOpen = !this._statusCenterOpen;
        this._patchStatusCenter();
      };
      statusCenter.addEventListener("click", toggle);
      statusCenter.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      });
    }

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
    // fanen. Collapsed state is purely a .collapsed class on the closest
    // .section-box, toggled per header click — no per-section id needed,
    // resets on the next full render (tab switch, or any action that calls
    // _scheduleRender()). See _css() for the matching collapse rule.
    root.querySelectorAll(".section-box-header.collapsible").forEach((header) => {
      header.addEventListener("click", () => {
        header.closest(".section-box")?.classList.toggle("collapsed");
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
    root.querySelectorAll("[data-action='toggle-field']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const field   = btn.dataset.field;
        const current = !!(this._data?.config?.[field] ?? false);
        const newVal  = !current;
        if (this._data?.config) this._data.config[field] = newVal; // optimistic
        this._scheduleRender();
        try {
          await this._hass.callWS({
            type: "heat_manager/update_config",
            [field]: newVal,
          });
        } catch (e) {
          if (this._data?.config) this._data.config[field] = current; // revert
          this._scheduleRender();
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
