"""Tests for the global Netatmo backend choice (v0.61.1): config/options flow
field visibility, TRV validation against the chosen backend, and the repair
issue when the chosen integration is missing. Fully offline.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.heat_manager import _async_check_netatmo_backend
from custom_components.heat_manager.config_flow import (
    HeatManagerOptionsFlow,
    _show_netatmo_backend_choice,
    _step1_schema,
    _validate_trv_input,
)
from custom_components.heat_manager.const import (
    CONF_CLIMATE_ENTITY,
    CONF_NETATMO_BACKEND,
    CONF_TRV_TYPE,
    DOMAIN,
    REPAIR_ISSUE_NETATMO_BACKEND_MISSING,
)
from custom_components.heat_manager.coordinator import HeatManagerCoordinator
from custom_components.heat_manager.engine.netatmo_backend import NetatmoBackend

PLATFORMS = {
    "climate.kitchen": "net_trv",
    "climate.kitchen_core": "netatmo",
    "climate.trv_z2m": "mqtt",
}


def _hass(installed: set[str]) -> MagicMock:
    hass = MagicMock()
    hass.states.get = MagicMock(
        side_effect=lambda eid: MagicMock(state="heat") if eid in PLATFORMS else None
    )
    hass.config_entries.async_entries = MagicMock(
        side_effect=lambda domain=None: (
            [MagicMock(disabled_by=None)] if domain in installed else []
        )
    )
    return hass


def _registry() -> MagicMock:
    reg = MagicMock()
    reg.async_get = MagicMock(
        side_effect=lambda eid: (
            SimpleNamespace(platform=PLATFORMS[eid]) if eid in PLATFORMS else None
        )
    )
    return reg


def _patch_er():
    return patch(
        "custom_components.heat_manager.config_flow.er.async_get",
        return_value=_registry(),
    )


# ── Field visibility ──────────────────────────────────────────────────────────


def test_choice_shown_when_both_installed():
    assert _show_netatmo_backend_choice(_hass({"netatmo", "net_trv"}), {}) is True


@pytest.mark.parametrize("installed", [set(), {"netatmo"}, {"net_trv"}])
def test_choice_hidden_with_one_or_no_backend(installed):
    assert _show_netatmo_backend_choice(_hass(installed), {}) is False


def test_choice_still_shown_when_explicit_choice_stored():
    """Core removed after the user picked it → field stays so they can switch."""
    hass = _hass({"net_trv"})
    assert _show_netatmo_backend_choice(hass, {CONF_NETATMO_BACKEND: "netatmo"})


def test_step1_schema_field_only_when_requested():
    keys = {str(k) for k in _step1_schema({}).schema}
    assert CONF_NETATMO_BACKEND not in keys
    schema = _step1_schema({}, show_netatmo_backend=True)
    assert CONF_NETATMO_BACKEND in {str(k) for k in schema.schema}
    assert schema({})[CONF_NETATMO_BACKEND] == "auto"


# ── TRV validation ────────────────────────────────────────────────────────────


def _trv(entity: str, trv_type: str = "netatmo") -> dict:
    return {CONF_CLIMATE_ENTITY: entity, CONF_TRV_TYPE: trv_type}


@pytest.mark.parametrize("choice", ["auto", None])
def test_auto_accepts_either_backend(choice):
    hass = _hass({"netatmo", "net_trv"})
    with _patch_er():
        assert _validate_trv_input(hass, _trv("climate.kitchen"), choice) == {}
        assert _validate_trv_input(hass, _trv("climate.kitchen_core"), choice) == {}


def test_explicit_choice_rejects_other_backend():
    hass = _hass({"netatmo", "net_trv"})
    with _patch_er():
        errors = _validate_trv_input(hass, _trv("climate.kitchen_core"), "net_trv")
        assert errors == {CONF_CLIMATE_ENTITY: "netatmo_backend_mismatch"}
        assert _validate_trv_input(hass, _trv("climate.kitchen"), "net_trv") == {}


def test_explicit_choice_ignores_zigbee_trvs():
    hass = _hass({"netatmo", "net_trv"})
    with _patch_er():
        assert (
            _validate_trv_input(hass, _trv("climate.trv_z2m", "zigbee"), "net_trv")
            == {}
        )


def test_missing_entity_still_entity_not_found():
    hass = _hass({"net_trv"})
    with _patch_er():
        errors = _validate_trv_input(hass, _trv("climate.gone"), "net_trv")
    assert errors == {CONF_CLIMATE_ENTITY: "entity_not_found"}


@pytest.mark.asyncio
async def test_options_trv_add_uses_stored_choice():
    """Options flow validates against the stored global choice."""
    entry = MagicMock()
    entry.data = {CONF_NETATMO_BACKEND: "net_trv"}
    entry.options = {}
    flow = HeatManagerOptionsFlow(entry)
    flow.hass = _hass({"netatmo", "net_trv"})
    with _patch_er():
        result = await flow.async_step_room_trv_add(
            user_input=_trv("climate.kitchen_core")
        )
    assert result["type"] == "form"
    assert result["errors"] == {CONF_CLIMATE_ENTITY: "netatmo_backend_mismatch"}
    assert flow._trv_draft == []


# ── Repair issue ──────────────────────────────────────────────────────────────


# v0.69.3: the check lives on the coordinator (issues layer) and also runs
# every tick, so disabling/removing the chosen integration raises the issue
# without an options save or a restart. Logic is exercised through the real
# method bound to a MagicMock coordinator.
_ISSUES = "custom_components.heat_manager.coordinator.issues"


def _coord(choice: str, effective: NetatmoBackend | None) -> MagicMock:
    coord = MagicMock(spec=HeatManagerCoordinator)
    coord.hass = MagicMock()
    coord.entry = MagicMock(entry_id="abcdef1234567890")
    coord.netatmo_backend_choice = choice
    coord.get_effective_netatmo_backend = MagicMock(return_value=effective)
    coord._netatmo_backend_issue_raised = False
    coord.check_netatmo_backend_choice = (
        HeatManagerCoordinator.check_netatmo_backend_choice.__get__(coord)
    )
    return coord


def _check(coord: MagicMock):
    with (
        patch(f"{_ISSUES}.async_create_issue") as create,
        patch(f"{_ISSUES}.async_delete_issue") as delete,
    ):
        coord.check_netatmo_backend_choice()
    return create, delete


def test_repair_raised_when_chosen_backend_missing():
    create, delete = _check(_coord("netatmo", None))
    create.assert_called_once()
    args, kwargs = create.call_args
    assert args[1] == DOMAIN
    assert args[2] == f"{REPAIR_ISSUE_NETATMO_BACKEND_MISSING}_abcdef12"
    assert kwargs["translation_placeholders"] == {"backend": "netatmo"}
    delete.assert_not_called()


def test_repair_cleared_when_chosen_backend_present():
    create, delete = _check(_coord("net_trv", NetatmoBackend.NET_TRV))
    create.assert_not_called()
    delete.assert_called_once()


def test_auto_never_raises_repair():
    create, delete = _check(_coord("auto", None))
    create.assert_not_called()
    delete.assert_called_once()


def test_bug_repair_follows_integration_disabled_without_options_save(caplog):
    """v0.69.3 regression (live 2026-11-13, A2.3): choosing "Core" and then
    disabling core netatmo never raised the issue — the check only ran at
    setup and on an options change. Now every tick re-evaluates it: raised
    as soon as the backend is gone (WARNING once, not every minute) and
    cleared again when it is back."""
    coord = _coord("netatmo", NetatmoBackend.CORE)
    create, delete = _check(coord)
    create.assert_not_called()

    coord.get_effective_netatmo_backend.return_value = None  # core disabled
    with caplog.at_level("WARNING"):
        create, _ = _check(coord)
        create2, _ = _check(coord)
    create.assert_called_once()
    create2.assert_called_once()
    assert sum("is not installed" in r.message for r in caplog.records) == 1

    coord.get_effective_netatmo_backend.return_value = NetatmoBackend.CORE
    _, delete = _check(coord)
    delete.assert_called_once()
    assert coord._netatmo_backend_issue_raised is False


def test_setup_wrapper_delegates_to_coordinator():
    entry = MagicMock()
    _async_check_netatmo_backend(MagicMock(), entry)
    entry.runtime_data.check_netatmo_backend_choice.assert_called_once()


def test_choice_hidden_when_one_backend_is_disabled():
    """v0.65.1: a disabled core entry is not "installed"."""
    hass = _hass({"net_trv"})
    hass.config_entries.async_entries = MagicMock(
        side_effect=lambda domain=None: {
            "netatmo": [MagicMock(disabled_by="user")],
            "net_trv": [MagicMock(disabled_by=None)],
        }.get(domain, [])
    )
    assert _show_netatmo_backend_choice(hass, {}) is False
