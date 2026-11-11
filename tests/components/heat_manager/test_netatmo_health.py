"""Tests for Netatmo valve health (v0.62.0): sibling-entity role detection,
battery thresholds, coordinator lookups via mocked entity/device registries,
the PID skip for offline valves, and the status-line issues. Fully offline.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.netatmo_backend import (
    HEALTH_BATTERY,
    HEALTH_BATTERY_STATE,
    HEALTH_CONNECTIVITY,
    SiblingEntity,
    battery_is_low,
    pick_health_entities,
)
from custom_components.heat_manager.websocket import _build_active_issues

# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_pick_health_entities_net_trv_room_device():
    siblings = [
        SiblingEntity("climate.kitchen", "climate", "room-1", None),
        SiblingEntity(
            "binary_sensor.kitchen_connectivity",
            "binary_sensor",
            "09:00-connectivity",
            "connectivity",
        ),
        SiblingEntity(
            "sensor.kitchen_battery_state", "sensor", "09:00-battery_state", "enum"
        ),
        SiblingEntity("sensor.kitchen_battery", "sensor", "09:00-battery", "battery"),
        SiblingEntity("sensor.kitchen_firmware", "sensor", "09:00-firmware", None),
    ]
    assert pick_health_entities(siblings) == {
        HEALTH_CONNECTIVITY: ["binary_sensor.kitchen_connectivity"],
        HEALTH_BATTERY_STATE: ["sensor.kitchen_battery_state"],
        HEALTH_BATTERY: ["sensor.kitchen_battery"],
    }


def test_pick_health_entities_ignores_webhook_sensor():
    siblings = [
        SiblingEntity(
            "binary_sensor.relay_webhook",
            "binary_sensor",
            "70:ee-webhook",
            "connectivity",
        )
    ]
    assert pick_health_entities(siblings) == {}


@pytest.mark.parametrize(
    ("state", "percent", "expected"),
    [
        ("very_low", None, True),
        ("low", "90", True),  # state wins over the coarse %
        ("medium", "10", False),
        (None, "15", True),
        (None, "20", False),
        (None, "abc", False),
        (None, None, False),
    ],
)
def test_battery_is_low(state, percent, expected):
    assert battery_is_low(state, percent) is expected


# ── Coordinator lookups ───────────────────────────────────────────────────────

ROOM_DEVICE = "dev-room-kitchen"
RELAY_DEVICE = "dev-relay"


def _entry(entity_id, platform, unique_id, device_id, device_class=None):
    return SimpleNamespace(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        platform=platform,
        unique_id=unique_id,
        device_id=device_id,
        device_class=None,
        original_device_class=device_class,
    )


ENTRIES = [
    _entry("climate.kitchen", "net_trv", "home-room", ROOM_DEVICE),
    _entry(
        "binary_sensor.kitchen_connectivity",
        "net_trv",
        "09:00-connectivity",
        ROOM_DEVICE,
        "connectivity",
    ),
    _entry(
        "sensor.kitchen_battery_state", "net_trv", "09:00-battery_state", ROOM_DEVICE
    ),
    _entry(
        "sensor.kitchen_battery", "net_trv", "09:00-battery", ROOM_DEVICE, "battery"
    ),
    _entry(
        "binary_sensor.relay_webhook",
        "net_trv",
        "70:ee-webhook",
        RELAY_DEVICE,
        "connectivity",
    ),
]


def _coordinator(states: dict[str, str]) -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: (
            SimpleNamespace(state=states[eid]) if eid in states else None
        )
    )
    coord.rooms = [{"room_name": "Kitchen"}]
    coord.get_room_trvs = MagicMock(
        return_value=[{"climate_entity": "climate.kitchen", "trv_type": "netatmo"}]
    )
    coord.get_trv_climate_entity = HeatManagerCoordinator.get_trv_climate_entity
    for name in (
        "get_trv_health_entities",
        "_state_value",
        "is_trv_reachable",
        "_trv_battery_low",
        "get_netatmo_webhook_entity",
        "get_netatmo_health",
    ):
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )
    return coord


def _registries():
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(
        side_effect=lambda eid: next((e for e in ENTRIES if e.entity_id == eid), None)
    )
    dev_reg = MagicMock()
    dev_reg.async_get = MagicMock(
        side_effect=lambda did: (
            SimpleNamespace(via_device_id=RELAY_DEVICE) if did == ROOM_DEVICE else None
        )
    )
    mod = "custom_components.heat_manager.coordinator"
    return (
        patch(f"{mod}.er.async_get", return_value=ent_reg),
        patch(
            f"{mod}.er.async_entries_for_device",
            side_effect=lambda reg, did: [e for e in ENTRIES if e.device_id == did],
        ),
        patch(f"{mod}.dr.async_get", return_value=dev_reg),
    )


def _health(states: dict[str, str]) -> dict:
    coord = _coordinator(states)
    p1, p2, p3 = _registries()
    with p1, p2, p3:
        return coord.get_netatmo_health()


def test_healthy_valve_reports_nothing():
    assert _health(
        {
            "binary_sensor.kitchen_connectivity": "on",
            "sensor.kitchen_battery_state": "full",
            "binary_sensor.relay_webhook": "on",
        }
    ) == {"offline_rooms": [], "low_battery_rooms": [], "webhook_down": False}


def test_offline_low_battery_and_webhook_down():
    assert _health(
        {
            "binary_sensor.kitchen_connectivity": "off",
            "sensor.kitchen_battery_state": "very_low",
            "sensor.kitchen_battery": "10",
            "binary_sensor.relay_webhook": "off",
        }
    ) == {
        "offline_rooms": ["Kitchen"],
        "low_battery_rooms": ["Kitchen"],
        "webhook_down": True,
    }


def test_unknown_connectivity_is_not_offline():
    """Unknown/unavailable says nothing about the valve — no warning."""
    health = _health({"binary_sensor.kitchen_connectivity": "unavailable"})
    assert health["offline_rooms"] == []


def test_battery_state_wins_over_percent():
    health = _health(
        {"sensor.kitchen_battery_state": "high", "sensor.kitchen_battery": "5"}
    )
    assert health["low_battery_rooms"] == []


def test_non_netatmo_trv_has_no_health_entities():
    coord = _coordinator({})
    p1, p2, p3 = _registries()
    with p1, p2, p3:
        assert coord.get_trv_health_entities({"climate_entity": "climate.z2m"}) == {}
        assert coord.is_trv_reachable({"climate_entity": "climate.z2m"}) is True


# ── PID skip for offline valves ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pid_skips_offline_valve_and_resets():
    from tests.components.heat_manager.test_pid_tick import _pid_tick, make_coordinator

    coord = make_coordinator(current_temp=20.0, target_temp=22.0)
    coord.is_trv_reachable = MagicMock(return_value=False)
    pid = coord.pid_controllers["living_room"]
    pid.update(22.0, 20.0)

    await _pid_tick(coord)

    assert pid.integral == pytest.approx(0.0)
    coord.hass.services.async_call.assert_not_called()


# ── Status line ───────────────────────────────────────────────────────────────


def _issues_coord(health: dict, rooms_cfg: list[dict] | None = None) -> MagicMock:
    from tests.components.heat_manager.test_websocket_active_issues import (
        _make_coordinator,
    )

    coord = _make_coordinator(rooms_cfg)
    coord.get_netatmo_health = MagicMock(return_value=health)
    return coord


def _health_dict(offline=(), low=(), webhook_down=False) -> dict:
    return {
        "offline_rooms": list(offline),
        "low_battery_rooms": list(low),
        "webhook_down": webhook_down,
    }


def test_offline_valve_replaces_generic_cloud_line():
    rooms = [{"room_name": "Kitchen"}, {"room_name": "Bath"}]
    coord = _issues_coord(_health_dict(offline=["Kitchen"]), rooms)
    coord.get_climate_entity = MagicMock(side_effect=lambda n: f"climate.{n.lower()}")
    healthy = MagicMock(state="heat", last_updated=None)
    coord.hass.states.get = MagicMock(
        side_effect=lambda eid: None if eid == "climate.kitchen" else healthy
    )
    issues = _build_active_issues(coord, [])
    ids = [i["id"] for i in issues]
    assert "valve_offline:Kitchen" in ids
    assert not any(i.startswith("cloud_unavailable") for i in ids)


def test_battery_and_webhook_issues():
    coord = _issues_coord(_health_dict(low=["Bath"], webhook_down=True))
    issues = {i["id"]: i for i in _build_active_issues(coord, [])}
    assert issues["battery_low:Bath"]["severity"] == "warning"
    assert issues["webhook_down"]["severity"] == "info"
