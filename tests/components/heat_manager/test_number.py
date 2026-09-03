"""Tests for number.py — GroupOffsetNumber (v0.9.0).

All tests run completely offline — HA core is mocked with MagicMock/AsyncMock.

GroupOffsetNumber.__init__ does not call super().__init__(), so the entity
can be instantiated directly without hass/entity-registry machinery.
RestoreEntity.async_added_to_hass() itself is a genuine no-op (an extension
point with no body), so `await super().async_added_to_hass()` inside
GroupOffsetNumber.async_added_to_hass() is safe to call as-is. What DOES
need HA's restore-state cache is async_get_last_number_data() — tests stub
that directly on the instance rather than dragging in the real restore
machinery, the same seam RestoreNumber itself exposes to integrations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager.const import DEFAULT_GROUP_OFFSET
from custom_components.heat_manager.number import GroupOffsetNumber

# ── shared fixtures ──────────────────────────────────────────────────────────


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.group_offset = 0.0
    coord.log_event = MagicMock()
    coord.global_device_info = MagicMock(return_value={"identifiers": {("x", "y")}})
    return coord


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry123"
    return entry


def _last_number_data(native_value):
    data = MagicMock()
    data.native_value = native_value
    return data


# ── __init__ ─────────────────────────────────────────────────────────────────


def test_init_sets_default_value_and_identity():
    coord = _make_coordinator()
    entity = GroupOffsetNumber(coord, _entry())
    assert entity.native_value == DEFAULT_GROUP_OFFSET
    assert entity.unique_id == "entry123_group_offset"


# ── async_added_to_hass: restore-on-restart ─────────────────────────────────


@pytest.mark.asyncio
async def test_added_to_hass_restores_previous_value():
    coord = _make_coordinator()
    entity = GroupOffsetNumber(coord, _entry())
    entity.async_get_last_number_data = AsyncMock(return_value=_last_number_data(2.5))

    await entity.async_added_to_hass()

    assert entity.native_value == 2.5
    assert coord.group_offset == 2.5


@pytest.mark.asyncio
async def test_added_to_hass_no_previous_state_keeps_default():
    coord = _make_coordinator()
    entity = GroupOffsetNumber(coord, _entry())
    entity.async_get_last_number_data = AsyncMock(return_value=None)

    await entity.async_added_to_hass()

    assert entity.native_value == DEFAULT_GROUP_OFFSET
    assert coord.group_offset == DEFAULT_GROUP_OFFSET


@pytest.mark.asyncio
async def test_added_to_hass_previous_native_value_none_keeps_default():
    """A restored record whose native_value is itself None (e.g. the entity
    had never been set before HA's last shutdown) must not overwrite the
    compiled-in default with None."""
    coord = _make_coordinator()
    entity = GroupOffsetNumber(coord, _entry())
    entity.async_get_last_number_data = AsyncMock(return_value=_last_number_data(None))

    await entity.async_added_to_hass()

    assert entity.native_value == DEFAULT_GROUP_OFFSET
    assert coord.group_offset == DEFAULT_GROUP_OFFSET


# ── async_set_native_value ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_native_value_updates_coordinator_and_logs():
    coord = _make_coordinator()
    entity = GroupOffsetNumber(coord, _entry())
    entity.async_write_ha_state = MagicMock()  # entity never added to hass

    await entity.async_set_native_value(3.0)

    assert entity.native_value == 3.0
    assert coord.group_offset == 3.0
    coord.log_event.assert_called_once()
    entity.async_write_ha_state.assert_called_once()
