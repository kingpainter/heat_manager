"""
Tests for HeatManagerConfigFlow and HeatManagerOptionsFlow.

Covers:
- setup wizard (steps: user → room → person → presence_global → notifications)
- validation errors: entity_not_found, duplicate_room, duplicate_person, no_rooms
- abort: already_configured
- options flow: global settings, add/delete rooms and persons, notifications
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from custom_components.heat_manager.const import (
    CONF_AWAY_TEMP_COLD,
    CONF_AWAY_TEMP_MILD,
    CONF_CLIMATE_ENTITY,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_NOTIFY_PRESENCE,
    CONF_NOTIFY_WINDOWS,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PERSONS,
    CONF_PREHEAT_LEAD_TIME_MIN,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)
from custom_components.heat_manager.config_flow import (
    HeatManagerConfigFlow,
    HeatManagerOptionsFlow,
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
    return hass


def _minimal_room(name="Kitchen", climate="climate.kitchen"):
    return {CONF_ROOM_NAME: name, CONF_CLIMATE_ENTITY: climate, CONF_WINDOW_SENSORS: []}


def _minimal_person(entity="person.flemming"):
    return {
        CONF_PERSON_ENTITY: entity,
        CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20,
    }


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
    hass = _make_hass({
        "climate.kitchen": MagicMock(state="heat"),
        "person.flemming": MagicMock(state="home"),
    })

    flow = HeatManagerConfigFlow()
    flow.hass = hass
    await flow.async_step_user()  # initialise

    # Step 1 — global settings (no weather entity)
    result = await flow.async_step_user(user_input={
        CONF_WEATHER_ENTITY: "",
        "notify_service": "",
        CONF_AWAY_TEMP_MILD: 17.0,
        CONF_AWAY_TEMP_COLD: 15.0,
        "mild_threshold": 8.0,
        CONF_GRACE_DAY_MIN: 30,
        CONF_GRACE_NIGHT_MIN: 15,
        "auto_off_temp_threshold": 18.0,
        "auto_off_temp_days": 5,
    })
    assert result["type"] == "form"
    assert result["step_id"] == "room"

    # Step 2 — add a room, then move on
    result = await flow.async_step_room(user_input={
        CONF_ROOM_NAME: "Kitchen",
        CONF_CLIMATE_ENTITY: "climate.kitchen",
        CONF_WINDOW_SENSORS: [],
        "window_delay_min": 5,
        "away_temp_override": 10.0,
        "_action": "next",
    })
    assert result["type"] == "form"
    assert result["step_id"] == "person"

    # Step 3 — add a person, then move on
    result = await flow.async_step_person(user_input={
        CONF_PERSON_ENTITY: "person.flemming",
        CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20,
        "_action": "next",
    })
    assert result["type"] == "form"
    assert result["step_id"] == "presence_global"

    # Step 4 — alarm panel (optional, leave blank)
    result = await flow.async_step_presence_global(user_input={"alarm_panel": ""})
    assert result["type"] == "form"
    assert result["step_id"] == "notifications"

    # Step 5 — notifications → creates entry
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
    hass = _make_hass({
        "climate.kitchen":  MagicMock(),
        "climate.bedroom":  MagicMock(),
        "person.flemming":  MagicMock(),
        "person.lukas":     MagicMock(),
    })
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    await flow.async_step_user()

    await flow.async_step_user(user_input={
        CONF_WEATHER_ENTITY: "", "notify_service": "",
        CONF_AWAY_TEMP_MILD: 17, CONF_AWAY_TEMP_COLD: 15, "mild_threshold": 8,
        CONF_GRACE_DAY_MIN: 30, CONF_GRACE_NIGHT_MIN: 15,
        "auto_off_temp_threshold": 18, "auto_off_temp_days": 5,
    })

    # Room 1 — add another
    await flow.async_step_room(user_input={
        CONF_ROOM_NAME: "Kitchen", CONF_CLIMATE_ENTITY: "climate.kitchen",
        CONF_WINDOW_SENSORS: [], "window_delay_min": 5, "away_temp_override": 10,
        "_action": "add",
    })
    # Room 2 — move on
    await flow.async_step_room(user_input={
        CONF_ROOM_NAME: "Bedroom", CONF_CLIMATE_ENTITY: "climate.bedroom",
        CONF_WINDOW_SENSORS: [], "window_delay_min": 5, "away_temp_override": 10,
        "_action": "next",
    })

    # Person 1 — add another
    await flow.async_step_person(user_input={
        CONF_PERSON_ENTITY: "person.flemming", CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20, "_action": "add",
    })
    # Person 2 — move on
    await flow.async_step_person(user_input={
        CONF_PERSON_ENTITY: "person.lukas", CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20, "_action": "next",
    })

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

    # Simulate unique_id already set
    flow._async_current_entries = MagicMock(return_value=[existing])

    with patch.object(flow, "_abort_if_unique_id_configured",
                      side_effect=Exception("already_configured")):
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
    await flow.async_step_user()

    result = await flow.async_step_user(user_input={
        CONF_WEATHER_ENTITY: "weather.nonexistent",
        "notify_service": "",
        CONF_AWAY_TEMP_MILD: 17, CONF_AWAY_TEMP_COLD: 15, "mild_threshold": 8,
        CONF_GRACE_DAY_MIN: 30, CONF_GRACE_NIGHT_MIN: 15,
        "auto_off_temp_threshold": 18, "auto_off_temp_days": 5,
    })
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert CONF_WEATHER_ENTITY in result["errors"]
    assert result["errors"][CONF_WEATHER_ENTITY] == "entity_not_found"


@pytest.mark.asyncio
async def test_step_room_invalid_climate_entity():
    """Unknown climate entity → entity_not_found error, stays on room step."""
    hass = _make_hass()  # climate.kitchen not registered
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = []
    flow._persons = []

    result = await flow.async_step_room(user_input={
        CONF_ROOM_NAME: "Kitchen",
        CONF_CLIMATE_ENTITY: "climate.nonexistent",
        CONF_WINDOW_SENSORS: [],
        "window_delay_min": 5,
        "away_temp_override": 10,
        "_action": "next",
    })
    assert result["type"] == "form"
    assert result["step_id"] == "room"
    assert CONF_CLIMATE_ENTITY in result["errors"]
    assert result["errors"][CONF_CLIMATE_ENTITY] == "entity_not_found"


@pytest.mark.asyncio
async def test_step_room_duplicate_name():
    """Adding a room with a name that already exists → duplicate_room error."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = [_minimal_room("Kitchen", "climate.kitchen")]
    flow._persons = []

    result = await flow.async_step_room(user_input={
        CONF_ROOM_NAME: "Kitchen",  # duplicate
        CONF_CLIMATE_ENTITY: "climate.kitchen",
        CONF_WINDOW_SENSORS: [],
        "window_delay_min": 5,
        "away_temp_override": 10,
        "_action": "add",
    })
    assert result["type"] == "form"
    assert result["step_id"] == "room"
    assert result["errors"].get(CONF_ROOM_NAME) == "duplicate_room"


@pytest.mark.asyncio
async def test_step_room_no_rooms_on_next():
    """Clicking next without any rooms → no_rooms error."""
    hass = _make_hass()
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = []
    flow._persons = []

    result = await flow.async_step_room(user_input={
        CONF_ROOM_NAME: "",
        CONF_CLIMATE_ENTITY: "",
        CONF_WINDOW_SENSORS: [],
        "window_delay_min": 5,
        "away_temp_override": 10,
        "_action": "next",
    })
    assert result["type"] == "form"
    assert result["step_id"] == "room"
    assert result["errors"].get("base") == "no_rooms"


@pytest.mark.asyncio
async def test_step_person_invalid_entity():
    """Unknown person entity → entity_not_found error."""
    hass = _make_hass()
    flow = HeatManagerConfigFlow()
    flow.hass = hass
    flow._data = {}
    flow._rooms = [_minimal_room()]
    flow._persons = []

    result = await flow.async_step_person(user_input={
        CONF_PERSON_ENTITY: "person.nobody",
        CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20,
        "_action": "next",
    })
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

    result = await flow.async_step_person(user_input={
        CONF_PERSON_ENTITY: "person.flemming",
        CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20,
        "_action": "add",
    })
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
    result = await flow.async_step_global(user_input={
        CONF_WEATHER_ENTITY: "",
        "notify_service": "",
        CONF_AWAY_TEMP_MILD: 18.0,  # changed
        CONF_AWAY_TEMP_COLD: 14.0,
        "mild_threshold": 8.0,
        CONF_GRACE_DAY_MIN: 45,
        CONF_GRACE_NIGHT_MIN: 15,
        "auto_off_temp_threshold": 20.0,
        "auto_off_temp_days": 7,
    })
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

    result = await flow.async_step_room_add(user_input={
        CONF_ROOM_NAME: "Bedroom",
        CONF_CLIMATE_ENTITY: "climate.bedroom",
        CONF_WINDOW_SENSORS: [],
        "window_delay_min": 5,
        "away_temp_override": 10,
    })
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert len(rooms) == 2
    assert any(r[CONF_ROOM_NAME] == "Bedroom" for r in rooms)


@pytest.mark.asyncio
async def test_options_flow_delete_room():
    """Options flow can delete an existing room."""
    hass = _make_hass()
    entry = _make_entry(rooms=[
        _minimal_room("Kitchen", "climate.kitchen"),
        _minimal_room("Bedroom", "climate.bedroom"),
    ])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})

    # Select Kitchen for deletion
    result = await flow.async_step_rooms_menu(user_input={"action": "delete_Kitchen"})
    assert result["type"] == "create_entry"
    rooms = result["data"][CONF_ROOMS]
    assert len(rooms) == 1
    assert rooms[0][CONF_ROOM_NAME] == "Bedroom"


@pytest.mark.asyncio
async def test_options_flow_add_person():
    """Options flow can add a new person."""
    hass = _make_hass({"person.lukas": MagicMock()})
    entry = _make_entry(persons=[_minimal_person("person.flemming")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    await flow.async_step_persons_menu(user_input={"action": "add"})

    result = await flow.async_step_person_add(user_input={
        CONF_PERSON_ENTITY: "person.lukas",
        CONF_PERSON_TRACKING: True,
        CONF_PREHEAT_LEAD_TIME_MIN: 20,
    })
    assert result["type"] == "create_entry"
    persons = result["data"][CONF_PERSONS]
    assert len(persons) == 2


@pytest.mark.asyncio
async def test_options_flow_delete_person():
    """Options flow can delete an existing person."""
    hass = _make_hass()
    entry = _make_entry(persons=[
        _minimal_person("person.flemming"),
        _minimal_person("person.lukas"),
    ])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "persons"})
    result = await flow.async_step_persons_menu(
        user_input={"action": "delete_person.flemming"}
    )
    assert result["type"] == "create_entry"
    persons = result["data"][CONF_PERSONS]
    assert len(persons) == 1
    assert persons[0][CONF_PERSON_ENTITY] == "person.lukas"


@pytest.mark.asyncio
async def test_options_flow_add_duplicate_room():
    """Options flow rejects a room name that already exists."""
    hass = _make_hass({"climate.kitchen": MagicMock()})
    entry = _make_entry(rooms=[_minimal_room("Kitchen", "climate.kitchen")])

    flow = HeatManagerOptionsFlow(entry)
    flow.hass = hass

    await flow.async_step_init(user_input={"section": "rooms"})
    await flow.async_step_rooms_menu(user_input={"action": "add"})

    result = await flow.async_step_room_add(user_input={
        CONF_ROOM_NAME: "Kitchen",  # duplicate
        CONF_CLIMATE_ENTITY: "climate.kitchen",
        CONF_WINDOW_SENSORS: [],
        "window_delay_min": 5,
        "away_temp_override": 10,
    })
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
    result = await flow.async_step_notifications(user_input={
        CONF_NOTIFY_PRESENCE: False,
        CONF_NOTIFY_WINDOWS: True,
        "notify_window_warning_30": False,
        "notify_preheat": True,
        "energy_tracking": True,
    })
    assert result["type"] == "create_entry"
    assert result["data"][CONF_NOTIFY_PRESENCE] is False
    assert result["data"][CONF_NOTIFY_WINDOWS] is True
