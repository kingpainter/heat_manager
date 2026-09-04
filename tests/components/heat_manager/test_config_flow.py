"""
Tests for HeatManagerConfigFlow and HeatManagerOptionsFlow.

Covers:
- setup wizard (steps: user → room → room_trvs_menu/room_trv_add → person →
  presence_global → notifications)
- validation errors: entity_not_found, duplicate_room, duplicate_person
- abort: already_configured
- options flow: global settings, add/delete rooms and persons, notifications
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.heat_manager.config_flow import (
    HeatManagerConfigFlow,
    HeatManagerOptionsFlow,
    _room_schema,
    _step1_schema,
    _trv_schema,
)
from custom_components.heat_manager.const import (
    CONF_ALARM_PANEL,
    CONF_AWAY_TEMP_COLD,
    CONF_AWAY_TEMP_MILD,
    CONF_CALIBRATION_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_NOTIFY_PRESENCE,
    CONF_NOTIFY_WINDOWS,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PERSONS,
    CONF_PI_DEMAND_ENTITY,
    CONF_PREHEAT_LEAD_TIME_MIN,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_SCHEDULE_ENTITY,
    CONF_SYNC_MODE,
    CONF_TRV_TYPE,
    CONF_TRVS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_hass(states: dict | None = None) -> MagicMock:
    """Return a minimal mock hass with controllable states."""
    hass = MagicMock()
    known = states or {}

    def states_get(entity_id):
        return known.get(entity_id)

    hass.states.get.side_effect = states_get
    hass.config_entries.async_entries.return_value = []
    hass.config_entries.async_get_entry.return_value = None
    return hass


def _minimal_room(name="Kitchen", climate="climate.kitchen"):
    """A room in the post-migration shape: CONF_TRVS plus the flat mirror
    of trvs[0] that migrations.migrate_room_to_trvs() would produce (see
    B18) — this is what HeatManagerOptionsFlow always actually sees, since
    async_migrate_entry() runs before any config entry can be opened."""
    return {
        CONF_ROOM_NAME: name,
        CONF_CLIMATE_ENTITY: climate,
        CONF_WINDOW_SENSORS: [],
        CONF_TRVS: [{CONF_CLIMATE_ENTITY: climate}],
    }


def _minimal_person(entity="person.flemming"):
    return {
        CONF_PERSON_ENTITY: entity,
        CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20,
    }


async def _finish_room_via_trvs_menu(flow, new_trvs, *, finish_action="done"):
    """From a just-returned room_trvs_menu step, add each TRV field dict in
    `new_trvs` (via trvs_menu "add" -> trv_add), then finish with
    `finish_action` ("done" / "done_add_room"). Works for both
    HeatManagerConfigFlow and HeatManagerOptionsFlow, since both expose the
    same room_trvs_menu/room_trv_add step names. Returns the result of the
    final trvs_menu submission.
    """
    for trv in new_trvs:
        result = await flow.async_step_room_trvs_menu(user_input={"action": "add"})
        assert result["step_id"] == "room_trv_add"
        result = await flow.async_step_room_trv_add(user_input=dict(trv))
        assert result["step_id"] == "room_trvs_menu"

    return await flow.async_step_room_trvs_menu(user_input={"action": finish_action})


async def _add_room_via_config_flow(flow, room_fields, trvs, *, finish_action):
    """Drive one room through the new room -> trvs_menu -> trv_add(...) ->
    trvs_menu(finish_action) sequence used by HeatManagerConfigFlow.

    `trvs` is a list of TRV field dicts (each needs at least
    CONF_CLIMATE_ENTITY). `finish_action` is "done" or "done_add_room".
    Returns the result of the final trvs_menu submission.
    """
    result = await flow.async_step_room(user_input=dict(room_fields))
    assert result["step_id"] == "room_trvs_menu"
    return await _finish_room_via_trvs_menu(flow, trvs, finish_action=finish_action)


def _notifications_data():
    return {
        "notify_presence": True,
        "notify_windows": True,
        "notify_window_warning_30": True,
        "notify_preheat": True,
        "energy_tracking": True,
    }


# ── Config flow — happy path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_setup_wizard_creates_entry():
    """
    Complete 5-step wizard with one room and one person produces a valid config entry.
    """
    hass = _make_hass(
        {
            "climate.kitchen": MagicMock(state="heat"),
            "person.flemming": MagicMock(state="home"),
        }
    )

    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow.context = {}

    with (
        patch(
            "custom_components.heat_manager.config_flow.HeatManagerConfigFlow._abort_if_unique_id_configured"
        ),
        patch(
            "custom_components.heat_manager.config_flow.HeatManagerConfigFlow.async_set_unique_id",
            new=AsyncMock(),
        ),
    ):
        await flow.async_step_user()  # initialise

        result = await flow.async_step_user(
            user_input={
                CONF_WEATHER_ENTITY: "",
                "notify_service": "",
                CONF_AWAY_TEMP_MILD: 17.0,
                CONF_AWAY_TEMP_COLD: 15.0,
                "mild_threshold": 8.0,
                CONF_GRACE_DAY_MIN: 30,
                CONF_GRACE_NIGHT_MIN: 15,
                "auto_off_temp_threshold": 18.0,
                "auto_off_temp_days": 5,
            }
        )

    assert result["type"] == "form"
    assert result["step_id"] == "room"

    result = await _add_room_via_config_flow(
        flow,
        {
            CONF_ROOM_NAME: "Kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10.0,
        },
        [{CONF_CLIMATE_ENTITY: "climate.kitchen"}],
        finish_action="done",
    )
    assert result["type"] == "form"
    assert result["step_id"] == "person"

    result = await flow.async_step_person(
        user_input={
            CONF_PERSON_ENTITY: "person.flemming",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
            "_action": "done",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "presence_global"

    result = await flow.async_step_presence_global(user_input={"alarm_panel": ""})
    assert result["type"] == "form"
    assert result["step_id"] == "notifications"

    result = await flow.async_step_notifications(user_input=_notifications_data())
    assert result["type"] == "create_entry"
    assert result["title"] == "Heat Manager"

    data = result["data"]
    assert len(data[CONF_ROOMS]) == 1
    assert data[CONF_ROOMS][0][CONF_ROOM_NAME] == "Kitchen"
    assert len(data[CONF_PERSONS]) == 1
    assert data[CONF_PERSONS][0][CONF_PERSON_ENTITY] == "person.flemming"


@pytest.mark.asyncio
async def test_multiple_rooms_and_persons():
    """Wizard accumulates multiple rooms and persons correctly."""
    hass = _make_hass(
        {
            "climate.kitchen": MagicMock(),
            "climate.bedroom": MagicMock(),
            "person.flemming": MagicMock(),
            "person.lukas": MagicMock(),
        }
    )
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow.context = {}

    with (
        patch(
            "custom_components.heat_manager.config_flow.HeatManagerConfigFlow._abort_if_unique_id_configured"
        ),
        patch(
            "custom_components.heat_manager.config_flow.HeatManagerConfigFlow.async_set_unique_id",
            new=AsyncMock(),
        ),
    ):
        await flow.async_step_user()

        await flow.async_step_user(
            user_input={
                CONF_WEATHER_ENTITY: "",
                "notify_service": "",
                CONF_AWAY_TEMP_MILD: 17,
                CONF_AWAY_TEMP_COLD: 15,
                "mild_threshold": 8,
                CONF_GRACE_DAY_MIN: 30,
                CONF_GRACE_NIGHT_MIN: 15,
                "auto_off_temp_threshold": 18,
                "auto_off_temp_days": 5,
            }
        )

    # Room 1 — add another
    await _add_room_via_config_flow(
        flow,
        {
            CONF_ROOM_NAME: "Kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        },
        [{CONF_CLIMATE_ENTITY: "climate.kitchen"}],
        finish_action="done_add_room",
    )
    # Room 2 — move on
    await _add_room_via_config_flow(
        flow,
        {
            CONF_ROOM_NAME: "Bedroom",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        },
        [{CONF_CLIMATE_ENTITY: "climate.bedroom"}],
        finish_action="done",
    )

    # Person 1 — add another
    await flow.async_step_person(
        user_input={
            CONF_PERSON_ENTITY: "person.flemming",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
            "_action": "add_more",
        }
    )
    # Person 2 — move on
    await flow.async_step_person(
        user_input={
            CONF_PERSON_ENTITY: "person.lukas",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
            "_action": "done",
        }
    )

    await flow.async_step_presence_global(user_input={"alarm_panel": ""})
    result = await flow.async_step_notifications(user_input=_notifications_data())

    assert result["type"] == "create_entry"
    assert len(result["data"][CONF_ROOMS]) == 2
    assert len(result["data"][CONF_PERSONS]) == 2


# ── Config flow — already configured ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_abort_if_already_configured():
    """Second setup attempt must abort with already_configured."""
    hass = _make_hass()
    existing = MagicMock()
    existing.domain = DOMAIN
    hass.config_entries.async_entries.return_value = [existing]

    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow._async_current_entries = MagicMock(return_value=[existing])

    with patch.object(
        flow,
        "_abort_if_unique_id_configured",
        side_effect=Exception("already_configured"),
    ):
        try:
            await flow.async_step_user()
        except Exception as e:
            assert "already_configured" in str(e)


# ── Config flow — validation errors ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_step_user_invalid_weather_entity():
    """Unknown weather entity → entity_not_found error, stays on step_user."""
    hass = _make_hass()  # no entities registered
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow.context = {}

    with (
        patch(
            "custom_components.heat_manager.config_flow.HeatManagerConfigFlow._abort_if_unique_id_configured"
        ),
        patch(
            "custom_components.heat_manager.config_flow.HeatManagerConfigFlow.async_set_unique_id",
            new=AsyncMock(),
        ),
    ):
        await flow.async_step_user()

        result = await flow.async_step_user(
            user_input={
                CONF_WEATHER_ENTITY: "weather.nonexistent",
                "notify_service": "",
                CONF_AWAY_TEMP_MILD: 17,
                CONF_AWAY_TEMP_COLD: 15,
                "mild_threshold": 8,
                CONF_GRACE_DAY_MIN: 30,
                CONF_GRACE_NIGHT_MIN: 15,
                "auto_off_temp_threshold": 18,
                "auto_off_temp_days": 5,
            }
        )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert CONF_WEATHER_ENTITY in result["errors"]
    assert result["errors"][CONF_WEATHER_ENTITY] == "entity_not_found"


@pytest.mark.asyncio
async def test_step_room_trv_add_invalid_climate_entity():
    """Unknown climate entity on a TRV → entity_not_found, stays on
    room_trv_add — climate entity validation now happens per-TRV, not on
    the room step (see B18 / TRV grouping groundwork)."""
    hass = _make_hass()  # climate.nonexistent not registered
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = []
    flow._persons = []

    result = await flow.async_step_room(
        user_input={
            CONF_ROOM_NAME: "Kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["step_id"] == "room_trvs_menu"

    result = await flow.async_step_room_trvs_menu(user_input={"action": "add"})
    assert result["step_id"] == "room_trv_add"

    result = await flow.async_step_room_trv_add(
        user_input={CONF_CLIMATE_ENTITY: "climate.nonexistent"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "room_trv_add"
    assert CONF_CLIMATE_ENTITY in result["errors"]
    assert result["errors"][CONF_CLIMATE_ENTITY] == "entity_not_found"
    # The rejected TRV must not have been added to the draft.
    assert flow._trv_draft == []


@pytest.mark.asyncio
async def test_step_room_duplicate_name():
    """Adding a room with a name that already exists → duplicate_room error."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = [_minimal_room("Kitchen", "climate.kitchen")]
    flow._persons = []

    result = await flow.async_step_room(
        user_input={
            CONF_ROOM_NAME: "Kitchen",  # duplicate
            CONF_CLIMATE_ENTITY: "climate.kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
            "_action": "add",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "room"
    assert result["errors"].get(CONF_ROOM_NAME) == "duplicate_room"


@pytest.mark.asyncio
async def test_step_room_blank_name_redisplays_room_form():
    """Submitting a blank room name just redisplays the room step — it
    can never be reached with zero total rooms any more, since a room is
    only appended to self._rooms once room_trvs_menu's "done" is chosen,
    which itself requires at least one TRV (see B18)."""
    hass = _make_hass()
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = []
    flow._persons = []

    result = await flow.async_step_room(
        user_input={
            CONF_ROOM_NAME: "",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "room"
    assert flow._rooms == []


@pytest.mark.asyncio
async def test_step_room_trvs_menu_hides_done_until_a_trv_is_added():
    """The room can't be finished with zero TRVs — "done" isn't even an
    offered action until at least one has been added."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = []
    flow._persons = []

    result = await flow.async_step_room(
        user_input={
            CONF_ROOM_NAME: "Kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["step_id"] == "room_trvs_menu"
    offered = {
        opt["value"] for opt in result["data_schema"].schema["action"].config["options"]
    }
    assert "done" not in offered
    assert "done_add_room" not in offered
    assert "add" in offered


@pytest.mark.asyncio
async def test_step_person_invalid_entity():
    """Unknown person entity → entity_not_found error."""
    hass = _make_hass()
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = [_minimal_room()]
    flow._persons = []

    result = await flow.async_step_person(
        user_input={
            CONF_PERSON_ENTITY: "person.nobody",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
            "_action": "next",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "person"
    assert result["errors"].get(CONF_PERSON_ENTITY) == "entity_not_found"


@pytest.mark.asyncio
async def test_step_person_duplicate():
    """Adding the same person twice → duplicate_person error."""
    hass = _make_hass({"person.flemming": MagicMock()})
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = [_minimal_room()]
    flow._persons = [_minimal_person("person.flemming")]

    result = await flow.async_step_person(
        user_input={
            CONF_PERSON_ENTITY: "person.flemming",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
            "_action": "add",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "person"
    assert result["errors"].get(CONF_PERSON_ENTITY) == "duplicate_person"


# ── Options flow — happy path ─────────────────────────────────────────────────


def _make_entry(rooms=None, persons=None):
    entry = MagicMock()
    entry.data = {
        CONF_ROOMS: rooms or [_minimal_room()],
        CONF_PERSONS: persons or [_minimal_person()],
        CONF_AWAY_TEMP_MILD: 17.0,
        CONF_AWAY_TEMP_COLD: 15.0,
        "mild_threshold": 8.0,
        CONF_GRACE_DAY_MIN: 30,
        CONF_GRACE_NIGHT_MIN: 15,
        "auto_off_temp_threshold": 18.0,
        "auto_off_temp_days": 5,
        "notify_service": "",
        CONF_WEATHER_ENTITY: "",
    }
    entry.options = {}
    return entry


@pytest.mark.asyncio
async def test_options_flow_global_settings():
    """Options flow can update global settings and create entry."""
    hass = _make_hass()
    entry = _make_entry()

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    # Init step — select "global"
    result = await flow.async_step_init(user_input={"section": "global"})
    assert result["type"] == "form"
    assert result["step_id"] == "global"

    # Submit new global settings
    result = await flow.async_step_global(
        user_input={
            CONF_WEATHER_ENTITY: "",
            "notify_service": "",
            CONF_AWAY_TEMP_MILD: 18.0,  # changed
            CONF_AWAY_TEMP_COLD: 14.0,
            "mild_threshold": 8.0,
            CONF_GRACE_DAY_MIN: 45,
            CONF_GRACE_NIGHT_MIN: 15,
            "auto_off_temp_threshold": 20.0,
            "auto_off_temp_days": 7,
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_AWAY_TEMP_MILD] == 18.0
    assert result["data"][CONF_GRACE_DAY_MIN] == 45


@pytest.mark.asyncio
async def test_options_flow_add_room():
    """Options flow can add a new room."""
    hass = _make_hass({"climate.bedroom": MagicMock()})
    entry = _make_entry(rooms=[_minimal_room("Kitchen", "climate.kitchen")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    await flow.async_step_rooms_menu(user_input={"action": "add"})

    result = await flow.async_step_room_add(
        user_input={
            CONF_ROOM_NAME: "Bedroom",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["step_id"] == "room_trvs_menu"
    result = await _finish_room_via_trvs_menu(
        flow, [{CONF_CLIMATE_ENTITY: "climate.bedroom"}]
    )
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert len(rooms) == 2
    bedroom = next(r for r in rooms if r[CONF_ROOM_NAME] == "Bedroom")
    assert bedroom[CONF_TRVS][0][CONF_CLIMATE_ENTITY] == "climate.bedroom"


@pytest.mark.asyncio
async def test_options_flow_delete_room():
    """Options flow can delete an existing room."""
    hass = _make_hass()
    entry = _make_entry(
        rooms=[
            _minimal_room("Kitchen", "climate.kitchen"),
            _minimal_room("Bedroom", "climate.bedroom"),
        ]
    )

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})

    # Select Kitchen for deletion
    result = await flow.async_step_rooms_menu(user_input={"action": "delete:Kitchen"})
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert len(rooms) == 1
    assert rooms[0][CONF_ROOM_NAME] == "Bedroom"


@pytest.mark.asyncio
async def test_options_flow_edit_room_updates_window_sensor():
    """Editing a room replaces its window sensor without touching other rooms."""
    hass = _make_hass(
        {
            "climate.kitchen": MagicMock(),
            "climate.bedroom": MagicMock(),
        }
    )
    entry = _make_entry(
        rooms=[
            _minimal_room("Kitchen", "climate.kitchen"),
            _minimal_room("Bedroom", "climate.bedroom"),
        ]
    )

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    result = await flow.async_step_rooms_menu(user_input={"action": "edit:Kitchen"})
    assert result["type"] == "form"
    assert result["step_id"] == "room_edit"

    result = await flow.async_step_room_edit(
        user_input={
            CONF_ROOM_NAME: "Kitchen",
            CONF_WINDOW_SENSORS: ["binary_sensor.kitchen_window_new"],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["step_id"] == "room_trvs_menu"
    # No new TRVs added — the existing one (seeded from CONF_TRVS) must
    # survive the edit untouched.
    result = await _finish_room_via_trvs_menu(flow, [])
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert len(rooms) == 2
    kitchen = next(r for r in rooms if r[CONF_ROOM_NAME] == "Kitchen")
    assert kitchen[CONF_WINDOW_SENSORS] == ["binary_sensor.kitchen_window_new"]
    assert kitchen[CONF_TRVS][0][CONF_CLIMATE_ENTITY] == "climate.kitchen"
    bedroom = next(r for r in rooms if r[CONF_ROOM_NAME] == "Bedroom")
    assert bedroom[CONF_TRVS][0][CONF_CLIMATE_ENTITY] == "climate.bedroom"


@pytest.mark.asyncio
async def test_options_flow_edit_room_invalid_climate_entity():
    """Editing a room's TRV with an unknown climate entity →
    entity_not_found error (the climate entity now lives on the TRV, not
    the room — see B18)."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    entry = _make_entry(rooms=[_minimal_room("Kitchen", "climate.kitchen")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    await flow.async_step_rooms_menu(user_input={"action": "edit:Kitchen"})

    result = await flow.async_step_room_edit(
        user_input={
            CONF_ROOM_NAME: "Kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["step_id"] == "room_trvs_menu"

    result = await flow.async_step_room_trvs_menu(user_input={"action": "edit:0"})
    assert result["step_id"] == "room_trv_edit"

    result = await flow.async_step_room_trv_edit(
        user_input={CONF_CLIMATE_ENTITY: "climate.nonexistent"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "room_trv_edit"
    assert result["errors"].get(CONF_CLIMATE_ENTITY) == "entity_not_found"


@pytest.mark.asyncio
async def test_options_flow_edit_room_duplicate_name():
    """Renaming a room to another existing room's name → duplicate_room error."""
    hass = _make_hass(
        {
            "climate.kitchen": MagicMock(),
            "climate.bedroom": MagicMock(),
        }
    )
    entry = _make_entry(
        rooms=[
            _minimal_room("Kitchen", "climate.kitchen"),
            _minimal_room("Bedroom", "climate.bedroom"),
        ]
    )

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    await flow.async_step_rooms_menu(user_input={"action": "edit:Bedroom"})

    result = await flow.async_step_room_edit(
        user_input={
            CONF_ROOM_NAME: "Kitchen",  # collides with the other room
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["type"] == "form"
    assert result["errors"].get(CONF_ROOM_NAME) == "duplicate_room"


@pytest.mark.asyncio
async def test_options_flow_edit_room_keeps_own_name():
    """Saving a room edit without changing its name must not trigger duplicate_room."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    entry = _make_entry(rooms=[_minimal_room("Kitchen", "climate.kitchen")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    await flow.async_step_rooms_menu(user_input={"action": "edit:Kitchen"})

    result = await flow.async_step_room_edit(
        user_input={
            CONF_ROOM_NAME: "Kitchen",  # unchanged
            CONF_WINDOW_SENSORS: ["binary_sensor.kitchen_window"],
            "window_delay_min": 10,
            "away_temp_override": 12,
        }
    )
    assert result["step_id"] == "room_trvs_menu"
    result = await _finish_room_via_trvs_menu(flow, [])
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert len(rooms) == 1
    assert rooms[0]["window_delay_min"] == 10


@pytest.mark.asyncio
async def test_options_flow_add_person():
    """Options flow can add a new person."""
    hass = _make_hass({"person.lukas": MagicMock()})
    entry = _make_entry(persons=[_minimal_person("person.flemming")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    await flow.async_step_persons_menu(user_input={"action": "add"})

    result = await flow.async_step_person_add(
        user_input={
            CONF_PERSON_ENTITY: "person.lukas",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
        }
    )
    assert result["type"] == "create_entry"
    persons = result["data"][CONF_PERSONS]
    assert len(persons) == 2


@pytest.mark.asyncio
async def test_options_flow_delete_person():
    """Options flow can delete an existing person."""
    hass = _make_hass()
    entry = _make_entry(
        persons=[
            _minimal_person("person.flemming"),
            _minimal_person("person.lukas"),
        ]
    )

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    result = await flow.async_step_persons_menu(
        user_input={"action": "delete:person.flemming"}
    )
    assert result["type"] == "create_entry"
    persons = result["data"][CONF_PERSONS]
    assert len(persons) == 1
    assert persons[0][CONF_PERSON_ENTITY] == "person.lukas"


@pytest.mark.asyncio
async def test_options_flow_edit_person():
    """Editing a person updates its fields without touching other persons."""
    hass = _make_hass(
        {
            "person.flemming": MagicMock(),
            "person.lukas": MagicMock(),
        }
    )
    entry = _make_entry(
        persons=[
            _minimal_person("person.flemming"),
            _minimal_person("person.lukas"),
        ]
    )

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    result = await flow.async_step_persons_menu(
        user_input={"action": "edit:person.flemming"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "person_edit"

    result = await flow.async_step_person_edit(
        user_input={
            CONF_PERSON_ENTITY: "person.flemming",
            CONF_PERSON_TRACKING: False,
            CONF_PREHEAT_LEAD_TIME_MIN: 30,
        }
    )
    assert result["type"] == "create_entry"
    persons = result["data"][CONF_PERSONS]
    assert len(persons) == 2
    flemming = next(p for p in persons if p[CONF_PERSON_ENTITY] == "person.flemming")
    assert flemming[CONF_PERSON_TRACKING] is False
    assert flemming[CONF_PREHEAT_LEAD_TIME_MIN] == 30
    lukas = next(p for p in persons if p[CONF_PERSON_ENTITY] == "person.lukas")
    assert lukas[CONF_PERSON_TRACKING] is True


@pytest.mark.asyncio
async def test_options_flow_edit_person_invalid_entity():
    """Editing a person to an unknown entity → entity_not_found error."""
    hass = _make_hass({"person.flemming": MagicMock()})
    entry = _make_entry(persons=[_minimal_person("person.flemming")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    await flow.async_step_persons_menu(user_input={"action": "edit:person.flemming"})

    result = await flow.async_step_person_edit(
        user_input={
            CONF_PERSON_ENTITY: "person.nobody",
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "person_edit"
    assert result["errors"].get(CONF_PERSON_ENTITY) == "entity_not_found"


@pytest.mark.asyncio
async def test_options_flow_edit_person_duplicate():
    """Editing a person to an entity already used by another person → duplicate_person."""
    hass = _make_hass(
        {
            "person.flemming": MagicMock(),
            "person.lukas": MagicMock(),
        }
    )
    entry = _make_entry(
        persons=[
            _minimal_person("person.flemming"),
            _minimal_person("person.lukas"),
        ]
    )

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    await flow.async_step_persons_menu(user_input={"action": "edit:person.lukas"})

    result = await flow.async_step_person_edit(
        user_input={
            CONF_PERSON_ENTITY: "person.flemming",  # collides with the other person
            CONF_PERSON_TRACKING: True,
            CONF_PREHEAT_LEAD_TIME_MIN: 20,
        }
    )
    assert result["type"] == "form"
    assert result["errors"].get(CONF_PERSON_ENTITY) == "duplicate_person"


@pytest.mark.asyncio
async def test_options_flow_add_duplicate_room():
    """Options flow rejects a room name that already exists."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    entry = _make_entry(rooms=[_minimal_room("Kitchen", "climate.kitchen")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    await flow.async_step_rooms_menu(user_input={"action": "add"})

    result = await flow.async_step_room_add(
        user_input={
            CONF_ROOM_NAME: "Kitchen",  # duplicate
            CONF_CLIMATE_ENTITY: "climate.kitchen",
            CONF_WINDOW_SENSORS: [],
            "window_delay_min": 5,
            "away_temp_override": 10,
        }
    )
    assert result["type"] == "form"
    assert result["errors"].get(CONF_ROOM_NAME) == "duplicate_room"


@pytest.mark.asyncio
async def test_options_flow_notifications():
    """Options flow can update notification preferences."""
    hass = _make_hass()
    entry = _make_entry()

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "notifications"})
    result = await flow.async_step_notifications(
        user_input={
            CONF_NOTIFY_PRESENCE: False,
            CONF_NOTIFY_WINDOWS: True,
            "notify_window_warning_30": False,
            "notify_preheat": True,
            "energy_tracking": True,
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_NOTIFY_PRESENCE] is False
    assert result["data"][CONF_NOTIFY_WINDOWS] is True


# ── Bug B17 — optional entity selectors rejected empty values ─────────────────
#
# CONF_CALIBRATION_ENTITY, CONF_SCHEDULE_ENTITY, CONF_WEATHER_ENTITY and
# CONF_ALARM_PANEL are all labelled "(optional)" in strings.json, but their
# vol.Optional(..., default=defaults.get(CONF_X, "")) previously fed an
# empty string into an entity selector. HA's entity selector requires a
# real entity ID and rejects "", so the *schema itself* raised
# vol.Invalid — before the step handler's own body (and its correct
# `if x and hass.states.get(x) is None` guards) ever ran. This reproduces
# what HA's FlowManager does on submit (`data_schema(user_input)`), which
# calling the step function directly with a plain dict does not exercise.


@pytest.mark.asyncio
async def test_bug_b17_room_edit_allows_schedule_left_empty():
    """
    Regression test for B17.
    Editing an existing room while leaving the optional schedule/calendar
    entity unset must not raise vol.Invalid, and the saved room must not
    carry that key at all.
    """
    hass = _make_hass({"climate.bathroom": MagicMock()})
    room = _minimal_room("Bathroom", "climate.bathroom")
    entry = _make_entry(rooms=[room])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass
    flow._rooms = [room]
    flow._editing_room_name = "Bathroom"

    form = await flow.async_step_room_edit()
    schema = form["data_schema"]

    submitted = {CONF_ROOM_NAME: "Bathroom"}
    validated = schema(submitted)  # must not raise vol.Invalid

    assert CONF_SCHEDULE_ENTITY not in validated

    result = await flow.async_step_room_edit(user_input=validated)
    assert result["step_id"] == "room_trvs_menu"
    result = await _finish_room_via_trvs_menu(flow, [])
    assert result["type"] == "create_entry"
    saved_room = next(
        r for r in result["data"][CONF_ROOMS] if r[CONF_ROOM_NAME] == "Bathroom"
    )
    assert CONF_SCHEDULE_ENTITY not in saved_room


@pytest.mark.asyncio
async def test_bug_b17_trv_edit_allows_calibration_left_empty():
    """
    Regression test for B17, now at the TRV level (see B18 — calibration
    entity moved from the room to each TRV).
    Editing an existing TRV while leaving the optional calibration entity
    unset must not raise vol.Invalid, and the saved TRV must not carry that
    key at all.
    """
    hass = _make_hass({"climate.bathroom": MagicMock()})
    room = _minimal_room("Bathroom", "climate.bathroom")
    entry = _make_entry(rooms=[room])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass
    flow._rooms = [room]
    flow._editing_room_name = "Bathroom"
    flow._room_draft = dict(room)
    flow._trv_draft = list(room.get(CONF_TRVS, []))
    flow._editing_trv_index = 0

    form = await flow.async_step_room_trv_edit()
    schema = form["data_schema"]

    submitted = {CONF_CLIMATE_ENTITY: "climate.bathroom"}
    validated = schema(submitted)  # must not raise vol.Invalid

    assert CONF_CALIBRATION_ENTITY not in validated

    result = await flow.async_step_room_trv_edit(user_input=validated)
    assert result["step_id"] == "room_trvs_menu"
    result = await flow.async_step_room_trvs_menu(user_input={"action": "done"})
    assert result["type"] == "create_entry"
    saved_room = next(
        r for r in result["data"][CONF_ROOMS] if r[CONF_ROOM_NAME] == "Bathroom"
    )
    assert CONF_CALIBRATION_ENTITY not in saved_room[CONF_TRVS][0]


def test_bug_b17_room_schema_self_heals_stale_empty_string_schedule():
    """
    Regression test for B17.
    A room saved before the fix could have schedule_entity stored as ""
    (the old buggy default). Re-opening the edit form for such a room must
    not carry that "" forward as an invalid selector default.
    """
    stale_room = {
        CONF_ROOM_NAME: "Bathroom",
        CONF_SCHEDULE_ENTITY: "",
    }
    schema = _room_schema(stale_room)
    # Re-submitting without touching the field must not raise.
    result = schema({CONF_ROOM_NAME: "Bathroom"})
    assert CONF_SCHEDULE_ENTITY not in result


def test_bug_b17_trv_schema_self_heals_stale_empty_string_calibration():
    """
    Regression test for B17, now at the TRV level (see B18).
    A TRV saved before the fix could have calibration_entity stored as ""
    (the old buggy default). Re-opening the edit form for such a TRV must
    not carry that "" forward as an invalid selector default.
    """
    stale_trv = {
        CONF_CLIMATE_ENTITY: "climate.bathroom",
        CONF_CALIBRATION_ENTITY: "",
    }
    schema = _trv_schema(stale_trv)
    # Re-submitting without touching the field must not raise.
    result = schema({CONF_CLIMATE_ENTITY: "climate.bathroom"})
    assert CONF_CALIBRATION_ENTITY not in result


def test_bug_b17_trv_schema_still_accepts_a_real_calibration_entity():
    """B17 fix must not affect TRVs that do set a calibration entity."""
    schema = _trv_schema({CONF_CLIMATE_ENTITY: "climate.bathroom"})
    result = schema(
        {
            CONF_CLIMATE_ENTITY: "climate.bathroom",
            CONF_CALIBRATION_ENTITY: "number.trv_calibration",
        }
    )
    assert result[CONF_CALIBRATION_ENTITY] == "number.trv_calibration"


def test_bug_b17_global_schema_allows_weather_entity_left_empty():
    """
    Regression test for B17.
    The global-settings schema (setup step 1 and options-flow "global" step)
    must accept a submission with no weather entity selected.
    """
    schema = _step1_schema({})
    result = schema({})
    assert CONF_WEATHER_ENTITY not in result


@pytest.mark.asyncio
async def test_bug_b17_presence_global_allows_alarm_panel_left_empty():
    """
    Regression test for B17.
    The presence_global step (initial setup wizard) must accept a
    submission with no alarm panel selected.
    """
    hass = _make_hass()
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow.context = {}

    form = await flow.async_step_presence_global()
    schema = form["data_schema"]

    validated = schema({})  # must not raise vol.Invalid
    assert CONF_ALARM_PANEL not in validated


# ── _trv_schema (B18 — per-TRV fields) ──────────────────────────────────────


def test_trv_schema_requires_climate_entity():
    """CONF_CLIMATE_ENTITY is the one Required field on a TRV — omitting
    it must raise, unlike every other TRV field."""
    schema = _trv_schema()
    with pytest.raises(vol.Invalid):
        schema({})


def test_trv_schema_minimal_submission_only_carries_climate_entity():
    """A submission with just the required climate entity must validate,
    and must not pick up "" defaults for any of the optional text/entity
    fields."""
    schema = _trv_schema()
    result = schema({CONF_CLIMATE_ENTITY: "climate.bathroom"})

    assert result[CONF_CLIMATE_ENTITY] == "climate.bathroom"
    assert CONF_CALIBRATION_ENTITY not in result


def test_trv_schema_full_submission_round_trips_all_fields():
    """Every TRV field set at once must validate and round-trip
    unchanged."""
    schema = _trv_schema()
    submitted = {
        CONF_CLIMATE_ENTITY: "climate.bathroom",
        CONF_HOMEKIT_CLIMATE_ENTITY: "Bathroom",
        CONF_TRV_TYPE: "zigbee",
        CONF_PI_DEMAND_ENTITY: "sensor.bathroom_pi_demand",
        CONF_CALIBRATION_ENTITY: "number.bathroom_calibration",
        CONF_SYNC_MODE: "lock",
    }
    result = schema(submitted)
    assert result == submitted


def test_trv_schema_defaults_prefill_from_an_existing_trv():
    """Re-opening the edit form for an existing TRV (defaults passed in)
    must prefill its fields, so a resubmission with no changes keeps them."""
    existing = {
        CONF_CLIMATE_ENTITY: "climate.bathroom",
        CONF_TRV_TYPE: "zigbee",
        CONF_SYNC_MODE: "mirror",
    }
    schema = _trv_schema(existing)
    result = schema({CONF_CLIMATE_ENTITY: "climate.bathroom"})

    assert result[CONF_TRV_TYPE] == "zigbee"
    assert result[CONF_SYNC_MODE] == "mirror"
