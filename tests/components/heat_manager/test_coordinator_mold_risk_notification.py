"""Tests for coordinator._async_check_mold_risk() / _notify_mold_risk()
(v0.31.0 — "mold risk as push notification" roadmap item).

MoldRiskSensor (binary_sensor.py) already exposes mold risk as an entity,
but as a passive CoordinatorEntity property it has no way to push a
notification on its own. _async_check_mold_risk() mirrors that sensor's
exact RH/dewpoint algorithm and edge-detects the False -> True transition
per room, firing CONF_NOTIFY_SERVICE exactly once per risk episode — the
same pattern engine/window_engine.py uses for its own open/close
notifications.

All tests run completely offline — HA core is mocked with MagicMock/
AsyncMock, same minimal-coordinator pattern as
test_coordinator_night_setback.py / test_coordinator_boost_defaults.py: only
the methods under test are bound to real coordinator functions, everything
they touch is an explicitly-configured MagicMock attribute.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import (
    CONF_HUMIDITY_SENSOR,
    CONF_NOTIFY_MOLD_RISK,
    CONF_NOTIFY_SERVICE,
)

# RH 95% / 10.0 C room temp -> dewpoint ~9.24 C -> 10.0 <= 9.24 + 1.0 -> at risk.
_RISK_RH = "95"
_RISK_TEMP = 10.0
# RH below the 70% threshold -> never at risk, regardless of temperature.
_SAFE_RH = "40"


def _state(value: str) -> MagicMock:
    return MagicMock(state=value)


def _make_coordinator(config: dict, rooms: list[dict]) -> MagicMock:
    """Minimal coordinator mock with only the two methods under test bound
    to the real implementation."""
    coord = MagicMock()
    coord.config = config
    coord.rooms = rooms
    coord._mold_risk_state = {}
    coord.log_event = MagicMock()
    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()

    from custom_components.heat_manager.coordinator import HeatManagerCoordinator

    coord._async_check_mold_risk = HeatManagerCoordinator._async_check_mold_risk.__get__(
        coord, type(coord)
    )
    coord._notify_mold_risk = HeatManagerCoordinator._notify_mold_risk.__get__(
        coord, type(coord)
    )
    return coord


_ROOM = {"room_name": "Kælder", CONF_HUMIDITY_SENSOR: "sensor.kaelder_rh"}


@pytest.mark.asyncio
async def test_notification_sent_on_risk_edge():
    """RH/temp cross into risk for the first time -> exactly one notification,
    one log_event, and the room's risk state is recorded as True."""
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM]
    )
    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_awaited_once()
    args, kwargs = coord.hass.services.async_call.call_args
    assert args[0] == "notify"
    assert args[1] == "mobile_app_phone"
    assert "Kælder" in args[2]["message"]
    assert args[2]["title"] == "Heat Manager"
    assert kwargs == {"blocking": True}
    assert coord.log_event.call_count == 1
    assert coord._mold_risk_state["Kælder"] is True


@pytest.mark.asyncio
async def test_no_duplicate_notification_within_same_episode():
    """Risk stays True across two consecutive ticks -> notified only once."""
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM]
    )
    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()
    await coord._async_check_mold_risk()

    assert coord.hass.services.async_call.await_count == 1


@pytest.mark.asyncio
async def test_notification_rearms_after_risk_clears():
    """Risk True -> False -> True again fires a second, independent
    notification (re-armed only once the episode actually ended)."""
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM]
    )
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")

    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)
    await coord._async_check_mold_risk()

    coord.hass.states.get = MagicMock(return_value=_state(_SAFE_RH))
    await coord._async_check_mold_risk()

    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    await coord._async_check_mold_risk()

    assert coord.hass.services.async_call.await_count == 2


@pytest.mark.asyncio
async def test_no_notification_when_rh_below_threshold():
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM]
    )
    coord.hass.states.get = MagicMock(return_value=_state(_SAFE_RH))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_not_awaited()
    assert coord._mold_risk_state["Kælder"] is False


@pytest.mark.asyncio
async def test_room_without_humidity_sensor_is_skipped():
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"},
        [{"room_name": "Gang"}],
    )
    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_climate_entity = MagicMock(return_value=None)
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_not_awaited()
    assert coord._mold_risk_state == {}


@pytest.mark.asyncio
async def test_unavailable_humidity_sensor_is_skipped():
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM]
    )
    coord.hass.states.get = MagicMock(return_value=_state("unavailable"))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_temperature_is_skipped():
    """get_room_current_temp() returns None (all temp sources unavailable)
    -> the room is skipped rather than crashing on the dewpoint math."""
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM]
    )
    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=None)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_mold_risk_defaults_to_true_when_unset():
    """CONF_NOTIFY_MOLD_RISK absent from a fresh-install config (key never
    persisted to entry.options) must still notify — same "true unless
    explicitly turned off" contract as the other notify_* toggles."""
    coord = _make_coordinator({CONF_NOTIFY_SERVICE: "notify.mobile_app_phone"}, [_ROOM])
    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_check_at_all_when_notify_mold_risk_disabled():
    """CONF_NOTIFY_MOLD_RISK explicitly False -> the whole check is a no-op,
    including never touching _mold_risk_state (mirrors the panel's own
    "off means off" toggle semantics)."""
    coord = _make_coordinator(
        {CONF_NOTIFY_SERVICE: "notify.mobile_app_phone", CONF_NOTIFY_MOLD_RISK: False},
        [_ROOM],
    )
    coord.hass.states.get = MagicMock(return_value=_state(_RISK_RH))
    coord.get_climate_entity = MagicMock(return_value="climate.kaelder")
    coord.get_room_current_temp = MagicMock(return_value=_RISK_TEMP)

    await coord._async_check_mold_risk()

    coord.hass.services.async_call.assert_not_awaited()
    assert coord._mold_risk_state == {}


@pytest.mark.asyncio
async def test_notify_mold_risk_no_service_configured():
    """_notify_mold_risk() is a silent no-op when CONF_NOTIFY_SERVICE is
    unset — must not raise."""
    coord = _make_coordinator({}, [_ROOM])

    await coord._notify_mold_risk("Mold risk — Kælder (95% RH, 10.0C)")

    coord.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_mold_risk_splits_domain_and_service():
    coord = _make_coordinator({CONF_NOTIFY_SERVICE: "notify.mobile_app_min_telefon"}, [])

    await coord._notify_mold_risk("Mold risk — Kælder (95% RH, 10.0C)")

    coord.hass.services.async_call.assert_awaited_once_with(
        "notify",
        "mobile_app_min_telefon",
        {"message": "Mold risk — Kælder (95% RH, 10.0C)", "title": "Heat Manager"},
        blocking=True,
    )
