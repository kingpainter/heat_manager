"""Regression tests for coordinator.get_climate_entity() / get_homekit_
climate_entity() resolving a room's primary TRV via CONF_TRVS.

Bug: both methods used to read the room's flat CONF_CLIMATE_ENTITY /
CONF_HOMEKIT_CLIMATE_ENTITY fields directly. migrate_room_to_trvs() only
ever mirrors those fields onto the room dict in memory (per-call, e.g. from
get_all_room_trvs()) — config_flow's per-TRV edit UI persists CONF_TRVS
only, never re-writing the flat mirror back to the config entry. Any room
saved through that UI therefore had no flat climate_entity at all, so the
old code silently returned None: Sætpunkt/TRV temp/valve % went blank in
the panel, and window_engine._open_after_delay() silently skipped writing
a reduced setpoint on window-open (climate_id was falsy → early return).

Both methods now resolve via get_all_room_trvs() (CONF_TRVS, migrated on
the fly) instead, which is unaffected by whether the flat mirror was ever
persisted.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.heat_manager.const import CONF_TRVS
from custom_components.heat_manager.coordinator import HeatManagerCoordinator


def _make_coordinator(rooms: list[dict]) -> MagicMock:
    """Coordinator mock with the real get_climate_entity() /
    get_homekit_climate_entity() / get_all_room_trvs() bound, so the actual
    CONF_TRVS resolution logic runs — only .rooms is faked."""
    coord = MagicMock()
    coord.rooms = rooms
    for name in (
        "get_climate_entity",
        "get_homekit_climate_entity",
        "get_all_room_trvs",
    ):
        setattr(
            coord,
            name,
            getattr(HeatManagerCoordinator, name).__get__(coord, type(coord)),
        )
    return coord


# ── get_climate_entity ───────────────────────────────────────────────────────


def test_climate_entity_resolves_from_trvs_only_room():
    """B18 UI regression: a room saved through the per-TRV edit UI has
    CONF_TRVS but no flat climate_entity — must still resolve."""
    coord = _make_coordinator(
        [{"room_name": "Køkken", CONF_TRVS: [{"climate_entity": "climate.kokken"}]}]
    )
    assert coord.get_climate_entity("Køkken") == "climate.kokken"


def test_climate_entity_resolves_from_legacy_flat_only_room():
    """Old data with no CONF_TRVS key at all — migrate_room_to_trvs()
    synthesizes it from the flat field on the fly."""
    coord = _make_coordinator([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    assert coord.get_climate_entity("Stue") == "climate.stue"


def test_climate_entity_prefers_trvs_over_stale_flat_mirror():
    """CONF_TRVS is the source of truth even when a stale flat field is
    still sitting on the room dict from an earlier migration."""
    coord = _make_coordinator(
        [
            {
                "room_name": "Lukas",
                "climate_entity": "climate.old_stale_entity",
                CONF_TRVS: [{"climate_entity": "climate.lukas_new"}],
            }
        ]
    )
    assert coord.get_climate_entity("Lukas") == "climate.lukas_new"


def test_climate_entity_none_for_room_with_no_trv_configured():
    coord = _make_coordinator([{"room_name": "Badeværelse"}])
    assert coord.get_climate_entity("Badeværelse") is None


def test_climate_entity_none_for_unknown_room():
    coord = _make_coordinator([{"room_name": "Stue", "climate_entity": "climate.stue"}])
    assert coord.get_climate_entity("Ukendt rum") is None


# ── get_homekit_climate_entity ───────────────────────────────────────────────


def test_homekit_climate_entity_resolves_from_trvs_only_room():
    coord = _make_coordinator(
        [
            {
                "room_name": "Køkken",
                CONF_TRVS: [
                    {
                        "climate_entity": "climate.kokken",
                        "homekit_climate_entity": "climate.kokken_hap",
                    }
                ],
            }
        ]
    )
    assert coord.get_homekit_climate_entity("Køkken") == "climate.kokken_hap"


def test_homekit_climate_entity_none_when_not_set():
    coord = _make_coordinator(
        [{"room_name": "Køkken", CONF_TRVS: [{"climate_entity": "climate.kokken"}]}]
    )
    assert coord.get_homekit_climate_entity("Køkken") is None


def test_homekit_climate_entity_none_for_room_with_no_trv_configured():
    coord = _make_coordinator([{"room_name": "Badeværelse"}])
    assert coord.get_homekit_climate_entity("Badeværelse") is None
