"""
Tests for coordinator._async_pid_tick()

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import ControllerState, EffectiveSeason, RoomState, SeasonMode
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
    coord.rooms = [{
        "room_name": room_name,
        "climate_entity": climate_id,
        "away_temp_override": away_temp_override,
        "comfort_temp": comfort_temp,
    }]
    coord.get_room_state = MagicMock(return_value=room_state)
    coord.get_homekit_climate_entity = MagicMock(return_value=homekit_entity)
    pid = PidController(kp=0.5, ki=0.02, kd=0.0, room_name=room_name)
    coord.pid_controllers = {room_name: pid}
    if climate_unavailable:
        cs = MagicMock(); cs.state = "unavailable"; cs.attributes = {}
    elif climate_missing_temps:
        cs = MagicMock(); cs.state = "heat"; cs.attributes = {}
    else:
        cs = MagicMock(); cs.state = "heat"
        cs.attributes = {"current_temperature": current_temp, "temperature": target_temp}
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(return_value=cs)
    coord.hass.services.async_call = AsyncMock()
    coord.night_setback_delta = MagicMock(return_value=0.0)
    coord.wake_setback_delta = MagicMock(return_value=0.0)
    coord.get_room_current_temp = MagicMock(return_value=current_temp)
    return coord


from custom_components.heat_manager.coordinator import HeatManagerCoordinator
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
    cs = MagicMock(); cs.state = "heat"
    cs.attributes = {"current_temperature": 22.0, "temperature": 10.0}
    coord.hass.states.get = MagicMock(return_value=cs)
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
    coord.rooms = [{"room_name": "kitchen", "climate_entity": "climate.kitchen",
                    "away_temp_override": 10.0}]
    coord.get_room_state = MagicMock(return_value=RoomState.NORMAL)
    coord.get_homekit_climate_entity = MagicMock(return_value="climate.kitchen_homekit")
    pid = PidController(kp=0.5, ki=0.0, kd=0.0, room_name="kitchen")
    coord.pid_controllers = {"kitchen": pid}
    cs = MagicMock(); cs.state = "heat"
    cs.attributes = {"current_temperature": 21.8, "temperature": 22.0}
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(return_value=cs)
    coord.hass.services.async_call = AsyncMock()
    coord.night_setback_delta = MagicMock(return_value=0.0)
    coord.wake_setback_delta = MagicMock(return_value=0.0)
    coord.get_room_current_temp = MagicMock(return_value=21.8)
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
    coord_baseline = make_coordinator(current_temp=20.0, target_temp=20.5, outdoor_temperature=None)
    await _pid_tick(coord_baseline)
    baseline_setpoint = coord_baseline.hass.services.async_call.call_args[0][2]["temperature"]

    coord_cold = make_coordinator(current_temp=20.0, target_temp=20.5, outdoor_temperature=-5.0)
    await _pid_tick(coord_cold)
    cold_setpoint = coord_cold.hass.services.async_call.call_args[0][2]["temperature"]

    assert cold_setpoint > baseline_setpoint


@pytest.mark.asyncio
async def test_feedforward_zero_when_mild_outside():
    """Outdoor temperature at/above FF_REFERENCE_OUTDOOR_TEMP contributes no
    feedforward — result should match the no-outdoor-data baseline exactly."""
    from custom_components.heat_manager.const import FF_REFERENCE_OUTDOOR_TEMP

    coord_baseline = make_coordinator(current_temp=20.0, target_temp=22.0, outdoor_temperature=None)
    await _pid_tick(coord_baseline)
    baseline_setpoint = coord_baseline.hass.services.async_call.call_args[0][2]["temperature"]

    coord_mild = make_coordinator(
        current_temp=20.0, target_temp=22.0, outdoor_temperature=FF_REFERENCE_OUTDOOR_TEMP
    )
    await _pid_tick(coord_mild)
    mild_setpoint = coord_mild.hass.services.async_call.call_args[0][2]["temperature"]

    assert mild_setpoint == pytest.approx(baseline_setpoint)


@pytest.mark.asyncio
async def test_feedforward_capped_at_max_contribution():
    """Extremely cold outdoor temperature must not push power beyond
    FF_MAX_CONTRIBUTION worth of extra setpoint versus a moderately cold day —
    the cap is a hard ceiling, not a linear runaway."""
    coord_very_cold = make_coordinator(current_temp=20.0, target_temp=22.0, outdoor_temperature=-40.0)
    await _pid_tick(coord_very_cold)
    very_cold_setpoint = coord_very_cold.hass.services.async_call.call_args[0][2]["temperature"]

    coord_cold = make_coordinator(current_temp=20.0, target_temp=22.0, outdoor_temperature=-10.0)
    await _pid_tick(coord_cold)
    cold_setpoint = coord_cold.hass.services.async_call.call_args[0][2]["temperature"]

    # Both are already past the point where feedforward saturates at
    # FF_MAX_CONTRIBUTION, so the two setpoints should be equal, not
    # increasing further with -40°C vs -10°C.
    assert very_cold_setpoint == pytest.approx(cold_setpoint)
