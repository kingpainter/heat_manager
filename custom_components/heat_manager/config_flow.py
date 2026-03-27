"""
Heat Manager — Config Flow

4-step setup wizard:
  Step 1: Season & global settings
  Step 2: Rooms (repeatable)
  Step 3: Persons (repeatable)
  Step 4: Notification preferences

Options flow allows editing global settings, managing rooms,
managing persons, and notification preferences after setup.

FIX: FlowResult → ConfigFlowResult (HA 2024+ correct type)
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ALARM_PANEL,
    CONF_AUTO_OFF_TEMP_DAYS,
    CONF_AUTO_OFF_TEMP_THRESHOLD,
    CONF_AWAY_TEMP_COLD,
    CONF_AWAY_TEMP_MILD,
    CONF_AWAY_TEMP_OVERRIDE,
    CONF_CLIMATE_ENTITY,
    CONF_ENERGY_TRACKING,
    CONF_GRACE_DAY_MIN,
    CONF_GRACE_NIGHT_MIN,
    CONF_HOMEKIT_CLIMATE_ENTITY,
    CONF_MILD_THRESHOLD,
    CONF_PI_DEMAND_ENTITY,
    CONF_TRV_TYPE,
    TRV_TYPE_NETATMO,
    TRV_TYPE_OPTIONS,
    CONF_NOTIFY_PRESENCE,
    CONF_NOTIFY_PREHEAT,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_WINDOW_WARNING_30,
    CONF_NOTIFY_WINDOWS,
    CONF_PERSON_ENTITY,
    CONF_PERSON_TRACKING,
    CONF_PERSONS,
    CONF_PREHEAT_LEAD_TIME_MIN,
    CONF_ROOM_NAME,
    CONF_ROOM_WATTAGE,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_DELAY_MIN,
    CONF_WINDOW_SENSORS,
    DEFAULT_AUTO_OFF_TEMP_DAYS,
    DEFAULT_AUTO_OFF_TEMP_THRESHOLD,
    DEFAULT_AWAY_TEMP_COLD,
    DEFAULT_AWAY_TEMP_MILD,
    DEFAULT_GRACE_DAY_MIN,
    DEFAULT_GRACE_NIGHT_MIN,
    DEFAULT_MILD_THRESHOLD,
    DEFAULT_PREHEAT_LEAD_TIME_MIN,
    DEFAULT_ROOM_WATTAGE,
    DEFAULT_WINDOW_DELAY_MIN,
    DOMAIN,
)


_LOGGER = logging.getLogger(__name__)


# ── Shared schemas ────────────────────────────────────────────────────────────

def _step1_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_WEATHER_ENTITY, default=defaults.get(CONF_WEATHER_ENTITY, "")):
            selector.selector({"entity": {"domain": "weather"}}),
        vol.Optional(CONF_NOTIFY_SERVICE, default=defaults.get(CONF_NOTIFY_SERVICE, "")):
            selector.selector({"text": {}}),
        vol.Optional(CONF_AWAY_TEMP_MILD, default=defaults.get(CONF_AWAY_TEMP_MILD, DEFAULT_AWAY_TEMP_MILD)):
            selector.selector({"number": {"min": 5, "max": 25, "step": 0.5, "unit_of_measurement": "°C"}}),
        vol.Optional(CONF_AWAY_TEMP_COLD, default=defaults.get(CONF_AWAY_TEMP_COLD, DEFAULT_AWAY_TEMP_COLD)):
            selector.selector({"number": {"min": 5, "max": 25, "step": 0.5, "unit_of_measurement": "°C"}}),
        vol.Optional(CONF_MILD_THRESHOLD, default=defaults.get(CONF_MILD_THRESHOLD, DEFAULT_MILD_THRESHOLD)):
            selector.selector({"number": {"min": 0, "max": 20, "step": 1, "unit_of_measurement": "°C"}}),
        vol.Optional(CONF_GRACE_DAY_MIN, default=defaults.get(CONF_GRACE_DAY_MIN, DEFAULT_GRACE_DAY_MIN)):
            selector.selector({"number": {"min": 5, "max": 120, "step": 5, "unit_of_measurement": "min"}}),
        vol.Optional(CONF_GRACE_NIGHT_MIN, default=defaults.get(CONF_GRACE_NIGHT_MIN, DEFAULT_GRACE_NIGHT_MIN)):
            selector.selector({"number": {"min": 5, "max": 60, "step": 5, "unit_of_measurement": "min"}}),
        vol.Optional(CONF_AUTO_OFF_TEMP_THRESHOLD, default=defaults.get(CONF_AUTO_OFF_TEMP_THRESHOLD, DEFAULT_AUTO_OFF_TEMP_THRESHOLD)):
            selector.selector({"number": {"min": 10, "max": 30, "step": 1, "unit_of_measurement": "°C"}}),
        vol.Optional(CONF_AUTO_OFF_TEMP_DAYS, default=defaults.get(CONF_AUTO_OFF_TEMP_DAYS, DEFAULT_AUTO_OFF_TEMP_DAYS)):
            selector.selector({"number": {"min": 1, "max": 14, "step": 1, "unit_of_measurement": "days"}}),
    })


def _room_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_ROOM_NAME, default=defaults.get(CONF_ROOM_NAME, "")):
            selector.selector({"text": {}}),
        vol.Required(CONF_CLIMATE_ENTITY, default=defaults.get(CONF_CLIMATE_ENTITY, "")):
            selector.selector({"entity": {"domain": "climate"}}),
        vol.Optional(CONF_HOMEKIT_CLIMATE_ENTITY, default=defaults.get(CONF_HOMEKIT_CLIMATE_ENTITY, "")):
            selector.selector({"entity": {"domain": "climate"}}),
        vol.Optional(CONF_WINDOW_SENSORS, default=defaults.get(CONF_WINDOW_SENSORS, [])):
            selector.selector({"entity": {"domain": "binary_sensor", "multiple": True}}),
        vol.Optional(CONF_WINDOW_DELAY_MIN, default=defaults.get(CONF_WINDOW_DELAY_MIN, DEFAULT_WINDOW_DELAY_MIN)):
            selector.selector({"number": {"min": 1, "max": 30, "step": 1, "unit_of_measurement": "min"}}),
        vol.Optional(CONF_AWAY_TEMP_OVERRIDE, default=defaults.get(CONF_AWAY_TEMP_OVERRIDE, 10)):
            selector.selector({"number": {"min": 5, "max": 20, "step": 0.5, "unit_of_measurement": "°C"}}),
        vol.Optional(CONF_ROOM_WATTAGE, default=defaults.get(CONF_ROOM_WATTAGE, DEFAULT_ROOM_WATTAGE)):
            selector.selector({"number": {"min": 100, "max": 5000, "step": 100, "unit_of_measurement": "W"}}),
        vol.Optional(CONF_TRV_TYPE, default=defaults.get(CONF_TRV_TYPE, TRV_TYPE_NETATMO)):
            selector.selector({"select": {"options": [
                {"value": "netatmo", "label": "Netatmo NRV (preset_mode: away/schedule)"},
                {"value": "zigbee",  "label": "Zigbee TRV via Z2M (hvac_mode: off/heat)"},
            ]}}),
        vol.Optional(CONF_PI_DEMAND_ENTITY, default=defaults.get(CONF_PI_DEMAND_ENTITY, "")):
            selector.selector({"entity": {"domain": "sensor"}}),
    })


def _person_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_PERSON_ENTITY, default=defaults.get(CONF_PERSON_ENTITY, "")):
            selector.selector({"entity": {"domain": "person"}}),
        vol.Optional(CONF_PERSON_TRACKING, default=defaults.get(CONF_PERSON_TRACKING, True)):
            selector.selector({"boolean": {}}),
        vol.Optional(CONF_PREHEAT_LEAD_TIME_MIN, default=defaults.get(CONF_PREHEAT_LEAD_TIME_MIN, DEFAULT_PREHEAT_LEAD_TIME_MIN)):
            selector.selector({"number": {"min": 5, "max": 60, "step": 5, "unit_of_measurement": "min"}}),
    })


def _notifications_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_NOTIFY_PRESENCE, default=defaults.get(CONF_NOTIFY_PRESENCE, True)):
            selector.selector({"boolean": {}}),
        vol.Optional(CONF_NOTIFY_WINDOWS, default=defaults.get(CONF_NOTIFY_WINDOWS, True)):
            selector.selector({"boolean": {}}),
        vol.Optional(CONF_NOTIFY_WINDOW_WARNING_30, default=defaults.get(CONF_NOTIFY_WINDOW_WARNING_30, True)):
            selector.selector({"boolean": {}}),
        vol.Optional(CONF_NOTIFY_PREHEAT, default=defaults.get(CONF_NOTIFY_PREHEAT, True)):
            selector.selector({"boolean": {}}),
        vol.Optional(CONF_ENERGY_TRACKING, default=defaults.get(CONF_ENERGY_TRACKING, True)):
            selector.selector({"boolean": {}}),
    })


# ── Config Flow ───────────────────────────────────────────────────────────────

class HeatManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict] = []
        self._persons: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            weather = user_input.get(CONF_WEATHER_ENTITY, "")
            if weather and self.hass.states.get(weather) is None:
                errors[CONF_WEATHER_ENTITY] = "entity_not_found"
            if not errors:
                self._data.update(user_input)
                return await self.async_step_room()

        return self.async_show_form(
            step_id="user",
            data_schema=_step1_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            action    = user_input.pop("_action", "add_more")
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()
            climate   = user_input.get(CONF_CLIMATE_ENTITY, "")

            if room_name and climate:
                existing_names = [r[CONF_ROOM_NAME].lower() for r in self._rooms]
                if room_name.lower() in existing_names:
                    errors[CONF_ROOM_NAME] = "duplicate_room"
                elif self.hass.states.get(climate) is None:
                    errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
                else:
                    user_input[CONF_ROOM_NAME] = room_name
                    self._rooms.append(dict(user_input))

            if not errors and action == "done":
                if not self._rooms:
                    errors["base"] = "no_rooms"
                else:
                    self._data[CONF_ROOMS] = self._rooms
                    return await self.async_step_person()

        schema = vol.Schema({
            **_room_schema(user_input or {}).schema,
            vol.Optional("_action", default="add_more"): selector.selector({
                "select": {"options": [
                    {"value": "add_more", "label": "Save and add another room"},
                    {"value": "done",     "label": "Save and continue"},
                ]}
            }),
        })

        return self.async_show_form(
            step_id="room",
            data_schema=schema,
            errors=errors,
            description_placeholders={"room_count": str(len(self._rooms))},
        )

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.pop("_action", "add_more")
            person = user_input.get(CONF_PERSON_ENTITY, "")

            if person:
                existing = [p[CONF_PERSON_ENTITY] for p in self._persons]
                if person in existing:
                    errors[CONF_PERSON_ENTITY] = "duplicate_person"
                elif self.hass.states.get(person) is None:
                    errors[CONF_PERSON_ENTITY] = "entity_not_found"
                else:
                    self._persons.append(dict(user_input))

            if not errors and action == "done":
                self._data[CONF_PERSONS] = self._persons
                return await self.async_step_presence_global()

        schema = vol.Schema({
            **_person_schema(user_input or {}).schema,
            vol.Optional("_action", default="add_more"): selector.selector({
                "select": {"options": [
                    {"value": "add_more", "label": "Save and add another person"},
                    {"value": "done",     "label": "Save and continue"},
                ]}
            }),
        })

        return self.async_show_form(
            step_id="person",
            data_schema=schema,
            errors=errors,
            description_placeholders={"person_count": str(len(self._persons))},
        )

    async def async_step_presence_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_notifications()

        return self.async_show_form(
            step_id="presence_global",
            data_schema=vol.Schema({
                vol.Optional(CONF_ALARM_PANEL, default=""):
                    selector.selector({"entity": {"domain": "alarm_control_panel"}}),
            }),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="Heat Manager", data=self._data)

        return self.async_show_form(
            step_id="notifications",
            data_schema=_notifications_schema(),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HeatManagerOptionsFlow:
        return HeatManagerOptionsFlow(config_entry)


# ── Options Flow ──────────────────────────────────────────────────────────────

class HeatManagerOptionsFlow(config_entries.OptionsFlow):
    """Post-setup options: edit global, manage rooms/persons, notifications."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._rooms: list[dict] = []
        self._persons: list[dict] = []

    def _current(self) -> dict:
        return {**self._config_entry.data, **self._config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            section = user_input.get("section")
            if section == "global":        return await self.async_step_global()
            if section == "rooms":         return await self.async_step_rooms_menu()
            if section == "persons":       return await self.async_step_persons_menu()
            if section == "notifications": return await self.async_step_notifications()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("section"): selector.selector({
                    "select": {"options": [
                        {"value": "global",        "label": "Season & global settings"},
                        {"value": "rooms",         "label": "Manage rooms"},
                        {"value": "persons",       "label": "Manage persons"},
                        {"value": "notifications", "label": "Notification preferences"},
                    ]}
                })
            }),
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._current(), **user_input})
        return self.async_show_form(
            step_id="global",
            data_schema=_step1_schema(self._current()),
        )

    async def async_step_rooms_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current_rooms = self._current().get(CONF_ROOMS, [])

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._rooms = list(current_rooms)
                return await self.async_step_room_add()
            if action and action.startswith("delete:"):
                room_name = action[len("delete:"):]
                updated = [r for r in current_rooms if r.get(CONF_ROOM_NAME) != room_name]
                return self.async_create_entry(data={**self._current(), CONF_ROOMS: updated})

        options = [
            {"value": f"delete:{r[CONF_ROOM_NAME]}", "label": f"Delete: {r[CONF_ROOM_NAME]}"}
            for r in current_rooms
        ]
        options.append({"value": "add", "label": "Add a new room"})

        return self.async_show_form(
            step_id="rooms_menu",
            data_schema=vol.Schema({
                vol.Required("action"): selector.selector({"select": {"options": options}})
            }),
            description_placeholders={"room_count": str(len(current_rooms))},
        )

    async def async_step_room_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            room_name = user_input.get(CONF_ROOM_NAME, "").strip()
            climate   = user_input.get(CONF_CLIMATE_ENTITY, "")
            existing_names = [r[CONF_ROOM_NAME].lower() for r in self._rooms]

            if room_name.lower() in existing_names:
                errors[CONF_ROOM_NAME] = "duplicate_room"
            elif climate and self.hass.states.get(climate) is None:
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            else:
                user_input[CONF_ROOM_NAME] = room_name
                self._rooms.append(dict(user_input))
                return self.async_create_entry(data={**self._current(), CONF_ROOMS: self._rooms})

        return self.async_show_form(
            step_id="room_add",
            data_schema=_room_schema(),
            errors=errors,
        )

    async def async_step_persons_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current_persons = self._current().get(CONF_PERSONS, [])

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._persons = list(current_persons)
                return await self.async_step_person_add()
            if action and action.startswith("delete:"):
                entity_id = action[len("delete:"):]
                updated = [p for p in current_persons if p.get(CONF_PERSON_ENTITY) != entity_id]
                return self.async_create_entry(data={**self._current(), CONF_PERSONS: updated})

        options = [
            {"value": f"delete:{p[CONF_PERSON_ENTITY]}", "label": f"Delete: {p[CONF_PERSON_ENTITY].split('.')[-1]}"}
            for p in current_persons
        ]
        options.append({"value": "add", "label": "Add a new person"})

        return self.async_show_form(
            step_id="persons_menu",
            data_schema=vol.Schema({
                vol.Required("action"): selector.selector({"select": {"options": options}})
            }),
            description_placeholders={"person_count": str(len(current_persons))},
        )

    async def async_step_person_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            person = user_input.get(CONF_PERSON_ENTITY, "")
            existing = [p[CONF_PERSON_ENTITY] for p in self._persons]
            if person in existing:
                errors[CONF_PERSON_ENTITY] = "duplicate_person"
            elif person and self.hass.states.get(person) is None:
                errors[CONF_PERSON_ENTITY] = "entity_not_found"
            else:
                self._persons.append(dict(user_input))
                return self.async_create_entry(data={**self._current(), CONF_PERSONS: self._persons})

        return self.async_show_form(
            step_id="person_add",
            data_schema=_person_schema(),
            errors=errors,
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._current(), **user_input})
        return self.async_show_form(
            step_id="notifications",
            data_schema=_notifications_schema(self._current()),
        )
