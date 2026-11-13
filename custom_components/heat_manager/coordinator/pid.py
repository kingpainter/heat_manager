"""Heat Manager coordinator — PID layer: target temperature and the PID tick.

Resolves each room's target (comfort, schedule, offsets, night and wake
setback, minimum room temperature) and runs the per-room PID controllers,
including weather compensation, solar gain and door heat sharing from
engine/pid_adjustments.py (v0.68.8, T3h).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import (
    State,
)

from ..const import (
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMP,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_PID_SETPOINT_MARGIN,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_PID_KD,
    DEFAULT_PID_KI,
    DEFAULT_PID_KP,
    PID_SETPOINT_MARGIN,
    ControllerState,
    EffectiveSeason,
    RoomState,
)
from ..engine.pid_adjustments import (
    door_heat_share_reduction,
    solar_gain_reduction,
    weather_compensation_feedforward,
)
from ..engine.pid_controller import PidController
from .issues import CoordinatorIssues

_LOGGER = logging.getLogger(__name__)


class CoordinatorPid(CoordinatorIssues):
    """Heat Manager coordinator — PID layer: target temperature and the PID tick."""

    def _track_cloud_degraded(
        self, room_name: str, cloud_id: str, *, cloud_up: bool, hk_alive: bool
    ) -> None:
        """B27: log once when a room's PID falls back to HomeKit-only
        control (cloud entity down, HomeKit reachable) and once when the
        cloud entity is back — never on every tick."""
        degraded = not cloud_up and hk_alive
        if degraded and room_name not in self._pid_cloud_degraded:
            self._pid_cloud_degraded.add(room_name)
            _LOGGER.warning(
                "PID '%s': %s is unavailable — continuing on HomeKit only",
                room_name,
                cloud_id,
            )
        elif cloud_up and room_name in self._pid_cloud_degraded:
            self._pid_cloud_degraded.discard(room_name)
            _LOGGER.info("PID '%s': %s is available again", room_name, cloud_id)

    def _init_pid_controllers(self) -> None:
        kp = float(self.config.get(CONF_PID_KP, DEFAULT_PID_KP))
        ki = float(self.config.get(CONF_PID_KI, DEFAULT_PID_KI))
        kd = float(self.config.get(CONF_PID_KD, DEFAULT_PID_KD))
        for room in self.rooms:
            name = room.get("room_name", "")
            if name:
                self.pid_controllers[name] = PidController(
                    kp=kp, ki=ki, kd=kd, room_name=name
                )

    def wake_setback_delta(self) -> float:
        """Return the wake setback delta in °C. 0.0 when not in WAKING phase.

        Applied to PID setpoints during the transitional WAKING phase so the
        system heats gently rather than at full winter capacity.
        """
        from ..const import CONF_WAKE_SETBACK_TEMP, DEFAULT_WAKE_SETBACK_TEMP

        if self.effective_season != EffectiveSeason.WAKING:
            return 0.0
        return float(self.config.get(CONF_WAKE_SETBACK_TEMP, DEFAULT_WAKE_SETBACK_TEMP))

    def is_night_setback_active(self) -> bool:
        """Return True when night setback is enabled and the current time is within
        the configured night window (CONF_NIGHT_START_HOUR – CONF_NIGHT_END_HOUR).

        The window may span midnight, e.g. 23:00 – 07:00.
        """
        from ..const import (
            CONF_NIGHT_END_HOUR,
            CONF_NIGHT_SETBACK_ENABLED,
            CONF_NIGHT_START_HOUR,
            DEFAULT_NIGHT_END_HOUR,
            DEFAULT_NIGHT_SETBACK_ENABLED,
            DEFAULT_NIGHT_START_HOUR,
        )

        if not self.config.get(
            CONF_NIGHT_SETBACK_ENABLED, DEFAULT_NIGHT_SETBACK_ENABLED
        ):
            return False

        from homeassistant.util.dt import now as ha_now

        hour = ha_now().hour
        start = int(self.config.get(CONF_NIGHT_START_HOUR, DEFAULT_NIGHT_START_HOUR))
        end = int(self.config.get(CONF_NIGHT_END_HOUR, DEFAULT_NIGHT_END_HOUR))

        # Window may span midnight (e.g. 23 – 7)
        if start > end:
            return hour >= start or hour < end
        # Same-day window (unusual, but handle it)
        return start <= hour < end

    def night_setback_delta(self) -> float:
        """Return the setback delta in °C. 0.0 when setback is not active."""
        from ..const import CONF_NIGHT_SETBACK_TEMP, DEFAULT_NIGHT_SETBACK_TEMP

        if not self.is_night_setback_active():
            return 0.0
        return float(
            self.config.get(CONF_NIGHT_SETBACK_TEMP, DEFAULT_NIGHT_SETBACK_TEMP)
        )

    def get_room_target_temp(self, room: dict[str, Any]) -> float:
        """Resolve a room's PID target temperature (°C), before PID power/
        setpoint mapping.

        Layers, identical for every TRV type since v0.19.0 (B21 — Heat
        Manager is the sole target authority regardless of manufacturer):

            CONF_COMFORT_TEMP → schedule_override → room_offset → setback

        Shared by _async_pid_tick() (drives the PID) and ws_get_state()
        (drives the panel's target-temp display, Fase 2), so the two can
        never drift apart — see
        audit/heat_manager_target_temp_analysis_2026-09-11.md.
        """
        room_name = room.get("room_name", "")
        target_temp = float(room.get(CONF_COMFORT_TEMP, DEFAULT_COMFORT_TEMP))

        # ── Schedule override (v0.9.0, Fase D) ──────────────────────────────
        # An active block on the room's CONF_SCHEDULE_ENTITY replaces the
        # comfort_temp base. Read fresh every tick by
        # schedule_engine.async_tick() earlier in this same coordinator tick
        # — releases automatically once the block/event ends, no state to
        # restore.
        schedule_temp = self.schedule_override.get(room_name)
        if schedule_temp is not None:
            target_temp = schedule_temp

        # ── Room offset (B18 Fase 3) — non-destructive per-room shift ───────
        # Mirrors climate_group_helper's "Group Offset": it automatically
        # follows the next schedule/season transition since it is never
        # baked into a stored target, only ever added at read time. See
        # number.py RoomOffsetNumber.
        room_offset = self.room_offsets.get(room_name, 0.0)
        if room_offset:
            target_temp += room_offset

        # ── Setbacks: night + wake — applied cumulatively ───────────────────
        setback = self.night_setback_delta() + self.wake_setback_delta()
        if setback > 0.0:
            before = target_temp
            target_temp = max(target_temp - setback, self.min_room_temp)
            _LOGGER.debug(
                "Setback [%s]: %.1f°C → %.1f°C (night=−%.1f°C wake=−%.1f°C)",
                room_name,
                before,
                target_temp,
                self.night_setback_delta(),
                self.wake_setback_delta(),
            )

        return target_temp

    async def _async_pid_tick(self) -> None:
        """
        Drive the PID controller for every room currently in NORMAL state.

        v0.8.0: generalised to a hybrid PID + outdoor-feedforward engine that
        now regulates BOTH room types, not just Netatmo HomeKit rooms.

        v0.19.0: CONF_COMFORT_TEMP is now the target for BOTH room types —
        Heat Manager is the sole authority for room target temperature,
        regardless of TRV manufacturer:

          - Netatmo rooms (homekit_climate_entity set): target_temp comes
            from CONF_COMFORT_TEMP; PID writes to the local HomeKit entity.
            Before 0.19.0 this read the cloud entity's own 'temperature'
            attribute instead — i.e. whatever Netatmo's own app-side
            schedule dictated — which silently overrode the user's
            configured comfort_temp for every Netatmo room (see
            audit/heat_manager_target_temp_analysis_2026-09-11.md). The
            cloud entity is still read for availability/health and for the
            heating_power_request demand percentage, just no longer for
            the target itself.
          - Local rooms (Zigbee today, Matter/Thread later — no
            homekit_climate_entity): unchanged — CONF_COMFORT_TEMP was
            already the target here. PID writes directly to the room's
            single climate_entity, since Zigbee2MQTT/Matter/Thread are
            local with no cloud rate limit.

        Both paths still layer schedule_override, room_offset and the
        night/wake setbacks on top of this base target identically.

        Both paths now also receive a small proactive "feedforward" power
        contribution based on outdoor temperature (see FF_* constants) on
        top of PID's reactive correction — classic weather-compensation
        "heating curve" behaviour. With a 60 s tick and several minutes of
        TRV thermal lag, pure PID only starts correcting once the room has
        already begun cooling; feedforward starts pushing power up as soon
        as the outdoor temperature drops, reducing undershoot during a
        sudden cold snap.

        current_temperature is read via get_room_current_temp() which
        prefers CONF_ROOM_TEMP_SENSOR over HomeKit entity over cloud entity
        — improves accuracy for Zigbee TRV rooms where the TRV's built-in
        probe sits on the hot radiator body and reads 1–3 °C above actual
        room temp.
        """
        if not self.pid_enabled:
            return
        if self.controller_state != ControllerState.ON:
            for controller_off_pid in self.pid_controllers.values():
                controller_off_pid.reset()
            return
        # PID runs in both ACTIVE and WAKING phases.
        # WAKING uses a reduced setpoint via wake_setback_delta().
        if self.effective_season == EffectiveSeason.DORMANT:
            for dormant_pid in self.pid_controllers.values():
                dormant_pid.reset()
            return

        # 2026-09 performance fix: activate the per-tick TRV cache (see
        # get_all_room_trvs()) for the duration of this loop — always
        # reset in the finally, even if a room's processing raises, so a
        # bug here can never leave every other get_all_room_trvs() call
        # site (all 29 of them) silently reading a stale cache forever.
        self._trv_cache = {}
        try:
            for room in self.rooms:
                room_name = room.get("room_name", "")
                if not room_name:
                    continue
                primary_id = self.get_climate_entity(room_name)
                if not primary_id:
                    continue

                pid = self.pid_controllers.get(room_name)
                if pid is None:
                    continue

                if self.get_room_state(room_name) != RoomState.NORMAL:
                    pid.reset()
                    continue

                # v0.61.2: HomeKit is required for PID on Netatmo valves. A
                # room whose TRVs are all Netatmo-without-HomeKit is left to
                # the Netatmo schedule — reset so the integral can't wind up
                # while nothing is written. See trv_pid_writable().
                # v0.62.0: a valve the integration reports offline counts as
                # not writable too — writes would go nowhere.
                room_trvs = self.get_room_trvs(room_name)
                if room_trvs and not any(
                    self.is_trv_pid_writable(t) and self.is_trv_reachable(t)
                    for t in room_trvs
                ):
                    pid.reset()
                    continue

                # ── Read current temperature via unified helper ────────────────
                # Preference: room_temp_sensor → HomeKit entity → cloud entity
                hk_id = self.get_homekit_climate_entity(room_name)
                primary_state = self.hass.states.get(primary_id)
                primary_down = primary_state is None or primary_state.state in (
                    "unavailable",
                    "unknown",
                )
                # B27 (v0.60.3): a Netatmo room whose cloud entity is down
                # (internet / Netatmo cloud / NET-TRV outage) can still be
                # driven locally through its HomeKit entity, which talks to
                # the relay over the LAN. Treat the cloud entity being
                # unavailable as "no new information", not as the room being
                # gone — only reset when there is no reachable write path.
                hk_alive = (not self._entity_unavailable(hk_id)) if hk_id else False
                self._track_cloud_degraded(
                    room_name, primary_id, cloud_up=not primary_down, hk_alive=hk_alive
                )

                current_temp = self.get_room_current_temp(room_name, primary_id)
                if current_temp is None:
                    # 2026-10-30: a brief loss of every temperature reading
                    # (room sensor / HomeKit / cloud dropout) only skips this
                    # tick — the PID keeps its integral, so the room doesn't
                    # lose the heat demand it had built up over a one-tick
                    # gap. The PID is still reset when the room has no
                    # reachable climate entity at all.
                    if primary_down and not hk_alive:
                        pid.reset()
                    continue

                if hk_id:
                    # ── Netatmo split-entity path ────────────────────────────
                    # v0.19.0: target comes from get_room_target_temp() (same
                    # CONF_COMFORT_TEMP base as the local path below) — see
                    # docstring above. The cloud entity is still read here for
                    # availability/health and the heating_power_request demand
                    # percentage, not for the target itself. B27: a down cloud
                    # entity no longer resets the PID — the HomeKit write
                    # entity's own availability check below decides that.
                    write_id = hk_id
                    if primary_down or primary_state is None:
                        demand_pct = "n/a (cloud unavailable)"
                    else:
                        demand_pct = primary_state.attributes.get(
                            "heating_power_request", "?"
                        )
                else:
                    # ── Local TRV path (Zigbee today, Matter/Thread later) ──
                    # Write directly to the room's own climate_entity:
                    # Z2M/Matter/Thread are local, no rate-limit stagger
                    # needed.
                    write_id = primary_id
                    demand_pct = "n/a (local)"

                # ── Target resolution ────────────────────────────────────────
                # comfort_temp → schedule_override → room_offset → setback,
                # identical for both room types since v0.19.0 (B21). Shared
                # with ws_get_state() via get_room_target_temp() so the
                # panel's displayed target can never drift from what the PID
                # actually chases.
                target_temp = self.get_room_target_temp(room)

                # ── PID tick → power fraction 0..1 ──────────────────────────
                power = pid.update(setpoint=target_temp, current=current_temp)

                # ── Outdoor feedforward (weather compensation) ──────────────
                # Proactive contribution added on top of PID's reactive term.
                # Applies to both room types — independent of write target.
                # 2026-09-13 (architecture review #5): now configurable — see
                # weather_compensation_feedforward() below, a pure helper so
                # it's unit-testable without mocking the whole coordinator.
                feedforward = weather_compensation_feedforward(
                    self.config, self.outdoor_temperature
                )
                if feedforward > 0.0:
                    power = min(1.0, power + feedforward)

                # ── Solar gain (2026-09-14, punkt 7) ─────────────────────────
                # A room currently reading bright sun (per its optional lux
                # sensor) needs less TRV-delivered heat than the schedule
                # alone calls for — subtracted AFTER the weather-compensation
                # feedforward above so the two can partially cancel on a
                # cold-but-sunny day (proactive cold-weather boost, offset by
                # the room actually getting warmed by the sun through its own
                # windows). See solar_gain_reduction()'s docstring for why
                # this is lux-driven rather than a geometric sun-position
                # model, and const.py's CONF_LUX_SENSOR for the per-room
                # opt-in. No effect at all for a room with no lux sensor
                # configured, or while CONF_SOLAR_GAIN_ENABLED is off
                # (default off — unlike weather compensation, this has no
                # prior always-on behaviour to preserve).
                solar_reduction = solar_gain_reduction(
                    self.config,
                    self.get_room_lux(room_name),
                    self.get_sun_elevation(),
                )
                if solar_reduction > 0.0:
                    power = max(0.0, power - solar_reduction)

                # ── Door heat sharing (2026-09-16, punkt 8) ────────────
                # A room with an open interior door to a warmer, actively-
                # heating neighbour needs less TRV-delivered heat right now
                # — part of the work is already being done for free through
                # the doorway. Deliberately does NOT touch comfort_temp/
                # target_temp at all (see const.py's
                # CONF_DOOR_HEAT_SHARE_ENABLED for why: it sidesteps an
                # unresolved "who owns the target while a door is open"
                # question from an earlier design). No effect at all unless
                # CONF_DOOR_HEAT_SHARE_ENABLED is on (default off — no prior
                # always-on behaviour to preserve) and a qualifying open
                # door + actively-heating warmer neighbour exists.
                neighbor_power, temp_diff = self.get_door_heat_share_inputs(
                    room_name, current_temp
                )
                door_share_reduction = door_heat_share_reduction(
                    self.config, neighbor_power, temp_diff
                )
                if door_share_reduction > 0.0:
                    power = max(0.0, power - door_share_reduction)

                trv_setpoint = PidController.power_to_setpoint(
                    power=power,
                    current_temp=current_temp,
                    trv_max=self.trv_max_temp,
                    trv_min=self.min_room_temp,
                )

                # ── Setpoint margin (2026-09-15, overshoot investigation) ───
                # power_to_setpoint() alone caps at the single, global
                # trv_max — which, on a normal call-for-heat, is reached at
                # 100% power well before the room is actually close to
                # target (Kp alone saturates power within a couple of
                # degrees' error). With trv_max sitting only a few degrees
                # above a room's own target_temp, that meant an everyday
                # heat call sent the TRV close to trv_max outright (e.g.
                # target 21°C, trv_max 24°C → setpoint jumps to 24°C), which
                # combined with district-heating/TRV thermal lag produced
                # the 22-25°C overshoot the user reported (2026-09-15).
                # Cap the ACTUAL written setpoint at this room's own target
                # plus a small, tunable margin instead — full power still
                # drives the TRV hard while genuinely far from target, but
                # never past a controlled overshoot allowance once close.
                # trv_max above remains the absolute hardware ceiling; this
                # is a second, tighter, per-room-relative cap on top of it.
                setpoint_margin = self.config.get(
                    CONF_PID_SETPOINT_MARGIN, PID_SETPOINT_MARGIN
                )
                trv_setpoint = min(trv_setpoint, target_temp + setpoint_margin)

                # Record the setpoint this tick computed as "correct" for this
                # room — regardless of whether the suppress-check below actually
                # sends it. SyncEngine reads this to recognise Heat Manager's
                # own expected value and tell a genuine manual/external TRV
                # change apart from it, without duplicating this whole
                # computation (which would double-advance the PID integrator).
                self.last_expected_setpoint[room_name] = trv_setpoint

                # Reset the PID (not just skip) when the room's primary TRV
                # write entity is unavailable — same policy as before B18. A
                # secondary TRV in a multi-TRV room being briefly unavailable
                # does not reset the room's PID; it's just skipped below.
                write_state = self.hass.states.get(write_id)
                if write_state is None or write_state.state in (
                    "unavailable",
                    "unknown",
                    "off",
                ):
                    pid.reset()
                    continue

                # ── Send the same computed setpoint to every TRV in the room ──
                # B18 "grouping": one PID loop per room, N identical outputs.
                # Each TRV resolves its own write entity the same way the
                # primary one above did (its own homekit_climate_entity if
                # configured, else its own climate_entity — no live-reachability
                # fallback, matching pre-B18 behaviour exactly for the primary
                # TRV: an unreachable configured HomeKit entity is skipped and
                # logged, not silently redirected to the cloud entity), and is
                # suppressed independently — a newly-added or differently-typed
                # TRV can sit at a different current setpoint than the room's
                # primary one.
                for trv in self.get_room_trvs(room_name):
                    # v0.61.2: never PID-write a Netatmo valve via the cloud.
                    if not self.is_trv_pid_writable(trv):
                        continue
                    # v0.62.0: skip a valve its integration reports offline.
                    if not self.is_trv_reachable(trv):
                        continue
                    trv_write_id = trv.get(CONF_HOMEKIT_CLIMATE_ENTITY) or trv.get(
                        CONF_CLIMATE_ENTITY
                    )
                    if not trv_write_id:
                        continue

                    trv_state: State | None
                    if trv_write_id == write_id:
                        trv_state = write_state  # already fetched above
                    else:
                        trv_state = self.hass.states.get(trv_write_id)
                        if trv_state is None or trv_state.state in (
                            "unavailable",
                            "unknown",
                            "off",
                        ):
                            continue

                    trv_current_setpoint = trv_state.attributes.get("temperature", 0.0)
                    try:
                        trv_current_setpoint = float(trv_current_setpoint)
                    except (TypeError, ValueError):
                        # 3.1 fix: a malformed/non-numeric setpoint attribute must
                        # not abort the PID tick for every remaining room — skip
                        # just this TRV and let the command below correct it.
                        _LOGGER.debug(
                            "PID tick [%s]: non-numeric current setpoint %r on %s"
                            " — sending setpoint anyway",
                            room_name,
                            trv_current_setpoint,
                            trv_write_id,
                        )
                        trv_current_setpoint = None

                    if (
                        trv_current_setpoint is not None
                        and abs(trv_setpoint - trv_current_setpoint) < 0.5
                    ):
                        continue

                    try:
                        # 2026-09-16 (deep-dive audit fix — highest priority
                        # finding): this used to call
                        # hass.services.async_call("climate", ...) directly.
                        # For a room with a reachable HomeKit entity on this
                        # SAME TRV, trv_write_id above already resolves local
                        # — harmless. But in a multi-TRV (B18 grouping) room
                        # where a SECONDARY TRV has no HomeKit entity of its
                        # own (or a Netatmo room configured without HomeKit
                        # at all), trv_write_id resolves to that TRV's cloud
                        # entity — and this runs on EVERY tick (60 s) for
                        # EVERY room needing a setpoint change, making it by
                        # far the highest-frequency of the 429-lock gaps this
                        # audit found. Routed through
                        # async_call_climate_service() with the same
                        # per-TRV trv_needs_cloud_delay() decision
                        # controller.py's OFF-fallback and the other fixed
                        # engines already use.
                        await self.async_call_climate_service(
                            "set_temperature",
                            trv_write_id,
                            {"temperature": trv_setpoint},
                            needs_delay=self.trv_needs_cloud_delay(trv),
                        )
                        _LOGGER.debug(
                            "PID tick [%s] (%s): target=%.1f cur=%.1f pwr=%.2f → %.1f°C"
                            "  (heating_power_request=%s%%)",
                            room_name,
                            "HomeKit" if hk_id else "local",
                            target_temp,
                            current_temp,
                            power,
                            trv_setpoint,
                            demand_pct,
                        )
                    # broad-except-rationale: one entity failing must not abort the others in this loop
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning(
                            "PID setpoint failed for '%s' via %s: %s",
                            room_name,
                            trv_write_id,
                            err,
                        )
        finally:
            self._trv_cache = None
