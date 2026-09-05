"""
Tests for coordinator._async_pid_tick()

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import (
    ControllerState,
    EffectiveSeason,
    RoomState,
    SeasonMode,
)
from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.pid_controller import PidController

# ── Minimal coordinator stub ───────────────────────────────────────────────────


def make_coordinator(
    *,
    pid_enabled: bool = True,
    controller_state: ControllerState = ControllerState.ON,
    effective_season: SeasonMode = SeasonMode.WINTER,
    room_name: str = "living_room",
    climate_id: str = "climate.living_room",
    room_state: RoomState = RoomState.NORMAL,
    current_temp: float = 20.0,
    target_temp: float = 22.0,
    trv_max: float = 28.0,
    away_temp_override: float = 10.0,
    climate_unavailable: bool = False,
    climate_missing_temps: bool = False,
    homekit_entity: str | None = "climate.living_room_homekit",
    comfort_temp: float = 20.0,
    outdoor_temperature: float | None = None,
) -> MagicMock:
    """Build a mock coordinator for _async_pid_tick() tests.

    homekit_entity defaults to a configured value so existing tests exercise
    the Netatmo/HomeKit split-entity path by default, same as before this
    parameter existed — previously get_homekit_climate_entity() was an
    unconfigured MagicMock attribute, which auto-returns a (truthy) MagicMock
    instance rather than a real string or None. That accidentally worked for
    the old code (any truthy value took the "has HomeKit" branch) but is
    fragile and doesn't let tests explicitly select the local/Zigbee path —
    pass homekit_entity=None for that.

    outdoor_temperature defaults to None (matching a fresh coordinator before
    its first _refresh_outdoor_temperature() tick) so the outdoor-feedforward
    code added in the hybrid PID engine doesn't perform arithmetic on an
    unconfigured MagicMock, which raises TypeError in max()/comparisons.
    """
    coord = MagicMock()
    coord.pid_enabled = pid_enabled
    coord.controller_state = controller_state
    coord.effective_season = effective_season
    coord.trv_max_temp = trv_max
    coord.outdoor_temperature = outdoor_temperature
    coord.rooms = [
        {
            "room_name": room_name,
            "climate_entity": climate_id,
            "away_temp_override": away_temp_override,
            "comfort_temp": comfort_temp,
        }
    ]
    coord.get_room_state = MagicMock(return_value=room_state)
    coord.get_homekit_climate_entity = MagicMock(return_value=homekit_entity)
    # B18: the PID tick's write step now fans out over get_room_trvs()
    # instead of writing a single room-level entity. Default to a single
    # TRV built from this room's own flat fields, so every existing
    # single-TRV test keeps writing to exactly the same entity as before.
    _trv = {"climate_entity": climate_id}
    if homekit_entity:
        _trv["homekit_climate_entity"] = homekit_entity
    coord.get_room_trvs = MagicMock(return_value=[_trv])
    pid = PidController(kp=0.5, ki=0.02, kd=0.0, room_name=room_name)
    coord.pid_controllers = {room_name: pid}
    if climate_unavailable:
        cs = MagicMock()
        cs.state = "unavailable"
        cs.attributes = {}
    elif climate_missing_temps:
        cs = MagicMock()
        cs.state = "heat"
        cs.attributes = {}
    else:
        cs = MagicMock()
        cs.state = "heat"
        cs.attributes = {
            "current_temperature": current_temp,
            "temperature": target_temp,
        }
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(return_value=cs)
    coord.hass.services.async_call = AsyncMock()
    coord.night_setback_delta = MagicMock(return_value=0.0)
    coord.wake_setback_delta = MagicMock(return_value=0.0)
    coord.get_room_current_temp = MagicMock(return_value=current_temp)
    # v0.9.0 / B18 Fase 3: real values, not auto-vivified MagicMocks —
    # room_offsets is read with .get() and its value added to target_temp,
    # last_expected_setpoint is written to as a real dict, and
    # schedule_override is read with .get() by _async_pid_tick(), so all
    # three need concrete types here.
    coord.room_offsets = {}
    coord.last_expected_setpoint = {}
    coord.schedule_override = {}
    return coord


_pid_tick = HeatManagerCoordinator._async_pid_tick


# ── Guard: pid_enabled = False ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pid_disabled_no_service_call():
    coord = make_coordinator(pid_enabled=False)
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_not_called()


# ── Guard: controller not ON ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_controller_paused_resets_pid():
    coord = make_coordinator(controller_state=ControllerState.PAUSE)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    assert pid.integral != 0.0
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_controller_off_resets_pid():
    coord = make_coordinator(controller_state=ControllerState.OFF)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


# ── Guard: summer season ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summer_season_resets_pid_no_call():
    coord = make_coordinator(effective_season=EffectiveSeason.DORMANT)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


# ── Guard: room not NORMAL ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_room_away_resets_pid():
    coord = make_coordinator(room_state=RoomState.AWAY)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_room_window_open_resets_pid():
    coord = make_coordinator(room_state=RoomState.WINDOW_OPEN)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_room_preheat_resets_pid():
    coord = make_coordinator(room_state=RoomState.PRE_HEAT)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


# ── Guard: climate unavailable ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_climate_unavailable_resets_pid():
    coord = make_coordinator(climate_unavailable=True)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


# ── Guard: missing temperature attributes ─────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_temp_attrs_skips_tick_no_reset():
    """No temperature data → skip tick but do NOT reset (brief unavailability)."""
    coord = make_coordinator(climate_missing_temps=True)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    integral_before = pid.integral
    await _pid_tick(coord)
    assert pid.integral == pytest.approx(integral_before)
    coord.hass.services.async_call.assert_not_called()


# ── Happy path: setpoint sent when delta >= 0.5 ───────────────────────────────


@pytest.mark.asyncio
async def test_pid_sends_setpoint_when_delta_large_enough():
    """2 °C below target → PID produces power > 0 → TRV setpoint sent."""
    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][0] == "climate"
    assert call_args[0][1] == "set_temperature"
    assert call_args[0][2]["temperature"] > 22.0


# ── No call when TRV is already at the PID floor ──────────────────────────────


@pytest.mark.asyncio
async def test_pid_no_call_when_setpoint_already_at_trv_min():
    """
    Room at target (error=0) → power=0 → trv_setpoint=trv_min=10.
    Climate already reports setpoint=10 → delta=0 < 0.5 → no call.
    """
    coord = make_coordinator(current_temp=22.0, target_temp=22.0)
    cs = MagicMock()
    cs.state = "heat"
    cs.attributes = {"current_temperature": 22.0, "temperature": 10.0}
    coord.hass.states.get = MagicMock(return_value=cs)
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_not_called()


# ── B18 Fase 3: per-room offset (replaces the old global group_offset) ───────


@pytest.mark.asyncio
async def test_room_offset_shifts_this_rooms_target():
    """
    current=12.0, schedule target=10.0 (both read from the same climate
    state, as make_coordinator wires it) → error = 10 - 12 = -2 → power
    clamps to 0 → trv_setpoint floors to trv_min (10.0), which already
    matches the reported setpoint (10.0) → no call, same shape as
    test_pid_no_call_when_setpoint_already_at_trv_min above.

    A +5.0 room offset (GROUP_OFFSET_MAX) shifts the target to 15.0:
    error = 15 - 12 = 3 → power = Kp * 3 = 1.5, clamped to 1.0 →
    trv_setpoint = 12 + 1.0 * (28 - 12) = 28.0 — far from the still-10.0
    reported setpoint → a call must go out.
    """
    coord = make_coordinator(current_temp=12.0, target_temp=10.0)
    coord.room_offsets = {"living_room": 5.0}
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["temperature"] == 28.0


@pytest.mark.asyncio
async def test_room_offset_does_not_leak_to_other_rooms():
    """An offset keyed to a different room must not affect this room's
    target — regression coverage for the old global group_offset behaviour
    B18 Fase 3 deliberately removes."""
    coord = make_coordinator(current_temp=12.0, target_temp=10.0)
    coord.room_offsets = {"some_other_room": 5.0}
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_not_called()


# ── Regression: B-PID-2 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bug_b_pid_2_no_call_when_delta_below_threshold():
    """
    B-PID-2: delta < 0.5 °C → no TRV command spam.

    Setup: current_temperature=21.8, climate.temperature (schedule target)=22.0
    error = 22.0 - 21.8 = 0.2
    power = Kp * 0.2 = 0.5 * 0.2 = 0.1  (Ki=0 for clean math)
    trv_setpoint = 21.8 + 0.1 * (28.0 - 21.8) = 21.8 + 0.62 = 22.42 → rounds to 22.4
    current climate setpoint = 22.0
    delta = |22.4 - 22.0| = 0.4 < 0.5 → no service call.
    """
    coord = MagicMock()
    coord.pid_enabled = True
    coord.controller_state = ControllerState.ON
    coord.effective_season = SeasonMode.WINTER
    coord.trv_max_temp = 28.0
    coord.outdoor_temperature = None
    coord.rooms = [
        {
            "room_name": "kitchen",
            "climate_entity": "climate.kitchen",
            "away_temp_override": 10.0,
        }
    ]
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.get_homekit_climate_entity = MagicMock(return_value="climate.kitchen_homekit")
    coord.get_room_trvs = MagicMock(
        return_value=[
            {
                "climate_entity": "climate.kitchen",
                "homekit_climate_entity": "climate.kitchen_homekit",
            }
        ]
    )
    pid = PidController(kp=0.5, ki=0.0, kd=0.0, room_name="kitchen")
    coord.pid_controllers = {"kitchen": pid}
    cs = MagicMock()
    cs.state = "heat"
    cs.attributes = {"current_temperature": 21.8, "temperature": 22.0}
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(return_value=cs)
    coord.hass.services.async_call = AsyncMock()
    coord.night_setback_delta = MagicMock(return_value=0.0)
    coord.wake_setback_delta = MagicMock(return_value=0.0)
    coord.get_room_current_temp = MagicMock(return_value=21.8)
    coord.room_offsets = {}
    coord.last_expected_setpoint = {}
    coord.schedule_override = {}
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_not_called()


# ── Hybrid engine: local/Zigbee path (no homekit_climate_entity) ──────────────


@pytest.mark.asyncio
async def test_local_path_uses_comfort_temp_as_target():
    """Room with no HomeKit entity: target comes from comfort_temp, not the
    primary climate entity's own 'temperature' attribute — writes directly
    to the room's single climate_entity."""
    coord = make_coordinator(
        homekit_entity=None,
        comfort_temp=22.0,
        current_temp=20.0,
        target_temp=99.0,  # should be ignored on the local path
        climate_id="climate.zigbee_bedroom",
    )
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][0] == "climate"
    assert call_args[0][1] == "set_temperature"
    # Written directly to the room's own entity — no separate write channel.
    assert call_args[0][2]["entity_id"] == "climate.zigbee_bedroom"
    assert call_args[0][2]["temperature"] > 20.0


@pytest.mark.asyncio
async def test_local_path_defaults_comfort_temp_when_unset():
    """Room with no comfort_temp key at all falls back to DEFAULT_COMFORT_TEMP
    (20°C) rather than crashing."""
    from custom_components.heat_manager.const import DEFAULT_COMFORT_TEMP

    coord = make_coordinator(homekit_entity=None, current_temp=15.0)
    coord.rooms[0].pop("comfort_temp", None)
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_called_once()
    # error = DEFAULT_COMFORT_TEMP - 15.0 should drive power > 0
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["temperature"] > 15.0
    assert DEFAULT_COMFORT_TEMP == 20.0


# ── Hybrid engine: outdoor feedforward ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_feedforward_adds_power_when_cold_outside():
    """With outdoor temperature well below FF_REFERENCE_OUTDOOR_TEMP, the
    computed TRV setpoint should be higher than with no outdoor data at all,
    for the identical room/PID state — feedforward is additive. Uses a small
    target/current delta (0.5°C) so baseline PID power is well under 1.0 and
    has headroom left for feedforward to actually move the result — a larger
    delta would already saturate power at the trv_max ceiling on its own."""
    coord_baseline = make_coordinator(
        current_temp=20.0, target_temp=20.5, outdoor_temperature=None
    )
    await _pid_tick(coord_baseline)
    baseline_setpoint = coord_baseline.hass.services.async_call.call_args[0][2][
        "temperature"
    ]

    coord_cold = make_coordinator(
        current_temp=20.0, target_temp=20.5, outdoor_temperature=-5.0
    )
    await _pid_tick(coord_cold)
    cold_setpoint = coord_cold.hass.services.async_call.call_args[0][2]["temperature"]

    assert cold_setpoint > baseline_setpoint


@pytest.mark.asyncio
async def test_feedforward_zero_when_mild_outside():
    """Outdoor temperature at/above FF_REFERENCE_OUTDOOR_TEMP contributes no
    feedforward — result should match the no-outdoor-data baseline exactly."""
    from custom_components.heat_manager.const import FF_REFERENCE_OUTDOOR_TEMP

    coord_baseline = make_coordinator(
        current_temp=20.0, target_temp=22.0, outdoor_temperature=None
    )
    await _pid_tick(coord_baseline)
    baseline_setpoint = coord_baseline.hass.services.async_call.call_args[0][2][
        "temperature"
    ]

    coord_mild = make_coordinator(
        current_temp=20.0,
        target_temp=22.0,
        outdoor_temperature=FF_REFERENCE_OUTDOOR_TEMP,
    )
    await _pid_tick(coord_mild)
    mild_setpoint = coord_mild.hass.services.async_call.call_args[0][2]["temperature"]

    assert mild_setpoint == pytest.approx(baseline_setpoint)


@pytest.mark.asyncio
async def test_feedforward_capped_at_max_contribution():
    """Extremely cold outdoor temperature must not push power beyond
    FF_MAX_CONTRIBUTION worth of extra setpoint versus a moderately cold day —
    the cap is a hard ceiling, not a linear runaway."""
    coord_very_cold = make_coordinator(
        current_temp=20.0, target_temp=22.0, outdoor_temperature=-40.0
    )
    await _pid_tick(coord_very_cold)
    very_cold_setpoint = coord_very_cold.hass.services.async_call.call_args[0][2][
        "temperature"
    ]

    coord_cold = make_coordinator(
        current_temp=20.0, target_temp=22.0, outdoor_temperature=-10.0
    )
    await _pid_tick(coord_cold)
    cold_setpoint = coord_cold.hass.services.async_call.call_args[0][2]["temperature"]

    # Both are already past the point where feedforward saturates at
    # FF_MAX_CONTRIBUTION, so the two setpoints should be equal, not
    # increasing further with -40°C vs -10°C.
    assert very_cold_setpoint == pytest.approx(cold_setpoint)


# ── Schedule override (v0.9.0, Fase D) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_override_replaces_local_comfort_temp():
    """An active schedule/calendar block for the room overrides
    CONF_COMFORT_TEMP on the local (no-HomeKit) path."""
    coord = make_coordinator(
        homekit_entity=None,
        comfort_temp=16.0,  # would normally drive a low/no-op setpoint
        current_temp=16.0,
        climate_id="climate.zigbee_bedroom",
    )
    coord.schedule_override = {"living_room": 24.0}  # far above comfort_temp
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    # Room was already at target under comfort_temp=16 → current=16, but the
    # schedule override (24.0) creates a large positive error → setpoint rises.
    assert call_args[0][2]["temperature"] > 16.0


@pytest.mark.asyncio
async def test_schedule_override_replaces_cloud_schedule_target():
    """An active schedule/calendar block overrides the Netatmo cloud
    schedule's own 'temperature' attribute on the HomeKit split-entity path."""
    coord = make_coordinator(current_temp=20.0, target_temp=17.0)  # cloud says 17°C
    coord.schedule_override = {"living_room": 23.0}  # schedule engine overrides
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["temperature"] > 20.0


# ── B18: multi-TRV grouping — one PID loop, N identical outputs ───────────────


@pytest.mark.asyncio
async def test_multi_trv_room_sends_same_setpoint_to_every_trv():
    """A room with two TRVs (mixed Netatmo HomeKit + local Zigbee) both
    below the computed setpoint receives the identical trv_setpoint on
    both write entities — B18 grouping."""
    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    primary_state = MagicMock()
    primary_state.state = "heat"
    primary_state.attributes = {"temperature": 10.0}
    second_state = MagicMock()
    second_state.state = "heat"
    second_state.attributes = {"temperature": 10.0}
    # get_homekit_climate_entity()/primary "temperature" read still comes
    # from the universal cs mock inside make_coordinator (current_temp=20,
    # target_temp=22); only the *write* entities are distinguished here.
    coord.get_room_trvs = MagicMock(
        return_value=[
            {
                "climate_entity": "climate.living_room",
                "homekit_climate_entity": "climate.living_room_homekit",
            },
            {"climate_entity": "climate.living_room_zigbee_trv2"},
        ]
    )
    base_get = coord.hass.states.get
    entity_states = {
        "climate.living_room_homekit": primary_state,
        "climate.living_room_zigbee_trv2": second_state,
    }

    def _get(entity_id):
        return entity_states.get(entity_id, base_get.return_value)

    coord.hass.states.get = MagicMock(side_effect=_get)

    await _pid_tick(coord)

    assert coord.hass.services.async_call.await_count == 2
    sent = {
        call.args[2]["entity_id"]: call.args[2]["temperature"]
        for call in coord.hass.services.async_call.await_args_list
    }
    assert set(sent) == {
        "climate.living_room_homekit",
        "climate.living_room_zigbee_trv2",
    }
    # Same computed setpoint sent to both — "N identical outputs".
    assert (
        sent["climate.living_room_homekit"] == sent["climate.living_room_zigbee_trv2"]
    )


@pytest.mark.asyncio
async def test_multi_trv_room_skips_trv_already_at_setpoint():
    """A second TRV already within 0.5°C of the computed setpoint is left
    alone even on a tick where the primary TRV still needs the command —
    each TRV is suppressed independently. Uses ki=0 so the (stateless)
    proportional-only computed setpoint is identical across both ticks."""
    from custom_components.heat_manager.engine.pid_controller import PidController

    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    coord.pid_controllers["living_room"] = PidController(
        kp=0.5, ki=0.0, kd=0.0, room_name="living_room"
    )
    coord.get_room_trvs = MagicMock(
        return_value=[
            {
                "climate_entity": "climate.living_room",
                "homekit_climate_entity": "climate.living_room_homekit",
            },
            {"climate_entity": "climate.living_room_zigbee_trv2"},
        ]
    )
    primary_state = MagicMock()
    primary_state.state = "heat"
    primary_state.attributes = {"temperature": 10.0}  # far off — will be sent
    second_state = MagicMock()
    second_state.state = "heat"
    second_state.attributes = {"temperature": 10.0}  # far off — will be sent

    # Capture the original (valid) cloud-state mock BEFORE reassigning
    # coord.hass.states.get below — otherwise the fallback branch would
    # resolve against the *new* mock's own (unconfigured) return_value.
    original_cs_state = coord.hass.states.get.return_value

    def _get(entity_id):
        if entity_id == "climate.living_room_homekit":
            return primary_state
        if entity_id == "climate.living_room_zigbee_trv2":
            return second_state
        return original_cs_state

    coord.hass.states.get = MagicMock(side_effect=_get)

    # First tick: both far from target → both receive the command.
    await _pid_tick(coord)
    assert coord.hass.services.async_call.await_count == 2
    computed_setpoint = coord.hass.services.async_call.await_args_list[0].args[2][
        "temperature"
    ]

    # Both TRVs now report that exact setpoint — next tick (ki=0, so the
    # computed setpoint is unchanged) must send nothing to either.
    primary_state.attributes = {"temperature": computed_setpoint}
    second_state.attributes = {"temperature": computed_setpoint}
    coord.hass.services.async_call.reset_mock()
    await _pid_tick(coord)
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_multi_trv_room_secondary_unavailable_does_not_reset_pid():
    """If only the *secondary* TRV is unavailable, the room's PID is not
    reset and the primary TRV still receives its command — only the
    primary TRV's unavailability resets the PID (B18). If pid.reset() were
    (incorrectly) called here, the per-TRV loop would still run since
    reset() doesn't itself skip the room — the real risk this guards is a
    stray `continue` treating any unavailable TRV as room-wide, which
    would suppress the primary TRV's otherwise-due command entirely."""
    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    coord.get_room_trvs = MagicMock(
        return_value=[
            {
                "climate_entity": "climate.living_room",
                "homekit_climate_entity": "climate.living_room_homekit",
            },
            {"climate_entity": "climate.living_room_zigbee_trv2"},
        ]
    )
    primary_state = MagicMock()
    primary_state.state = "heat"
    primary_state.attributes = {"temperature": 10.0}

    # Capture the original (valid) cloud-state mock BEFORE reassigning
    # coord.hass.states.get below — otherwise the fallback branch would
    # resolve against the *new* mock's own (unconfigured) return_value.
    original_cs_state = coord.hass.states.get.return_value

    def _get(entity_id):
        if entity_id == "climate.living_room_homekit":
            return primary_state
        if entity_id == "climate.living_room_zigbee_trv2":
            return None  # unavailable
        return original_cs_state

    coord.hass.states.get = MagicMock(side_effect=_get)
    await _pid_tick(coord)

    coord.hass.services.async_call.assert_called_once()
    assert (
        coord.hass.services.async_call.call_args[0][2]["entity_id"]
        == "climate.living_room_homekit"
    )


@pytest.mark.asyncio
async def test_multi_trv_room_primary_unavailable_resets_pid_skips_all():
    """If the *primary* TRV's write entity is unavailable, the room's PID
    resets and nothing is sent to any TRV this tick — even a perfectly
    healthy secondary TRV is skipped, matching the pre-B18 single-TRV
    policy of resetting on the room's authoritative write target."""
    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)
    coord.get_room_trvs = MagicMock(
        return_value=[
            {
                "climate_entity": "climate.living_room",
                "homekit_climate_entity": "climate.living_room_homekit",
            },
            {"climate_entity": "climate.living_room_zigbee_trv2"},
        ]
    )
    second_state = MagicMock()
    second_state.state = "heat"
    second_state.attributes = {"temperature": 10.0}

    def _get(entity_id):
        if entity_id == "climate.living_room_homekit":
            return None  # primary unavailable
        if entity_id == "climate.living_room_zigbee_trv2":
            return second_state
        return coord.hass.states.get.return_value

    coord.hass.states.get = MagicMock(side_effect=_get)
    await _pid_tick(coord)

    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_no_schedule_override_uses_normal_target():
    """Room absent from schedule_override (no CONF_SCHEDULE_ENTITY, or no
    active block) falls through to the normal target unchanged."""
    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    assert coord.schedule_override == {}
    await _pid_tick(coord)
    call_args = coord.hass.services.async_call.call_args
    assert call_args[0][2]["temperature"] > 22.0
