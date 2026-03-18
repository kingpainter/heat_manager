"""
Heat Manager — Config Flow

4-step setup wizard:
  Step 1: Season & global settings (weather, notify, grace periods, auto-off)
  Step 2: Rooms (repeatable — add as many as needed)
  Step 3: Persons (repeatable — supports tracking-disabled persons like Sebastian)
  Step 4: Notification preferences

Options flow mirrors Step 1 + Step 4 for post-setup edits.
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
    CONF_MILD_THRESHOLD,
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
    DEFAULT_WINDOW_DELAY_MIN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


# ── Step schemas ──────────────────────────────────────────────────────────────

def _step1_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Optional(
            CONF_WEATHER_ENTITY,
            default=defaults.get(CONF_WEATHER_ENTITY, ""),
        ): selector.selector({"entity": {"domain": "weather"}}),

        vol.Optional(
            CONF_NOTIFY_SERVICE,
            default=defaults.get(CONF_NOTIFY_SERVICE, ""),
        ): selector.selector({"text": {}}),

        vol.Optional(
            CONF_AWAY_TEMP_MILD,
            default=defaults.get(CONF_AWAY_TEMP_MILD, DEFAULT_AWAY_TEMP_MILD),
        ): selector.selector({
            "number": {"min": 5, "max": 25, "step": 0.5, "unit_of_measurement": "°C"}
        }),

        vol.Optional(
            CONF_AWAY_TEMP_COLD,
            default=defaults.get(CONF_AWAY_TEMP_COLD, DEFAULT_AWAY_TEMP_COLD),
        ): selector.selector({
            "number": {"min": 5, "max": 25, "step": 0.5, "unit_of_measurement": "°C"}
        }),

        vol.Optional(
            CONF_MILD_THRESHOLD,
            default=defaults.get(CONF_MILD_THRESHOLD, DEFAULT_MILD_THRESHOLD),
        ): selector.selector({
            "number": {"min": 0, "max": 20, "step": 1, "unit_of_measurement": "°C"}
        }),

        vol.Optional(
            CONF_GRACE_DAY_MIN,
            default=defaults.get(CONF_GRACE_DAY_MIN, DEFAULT_GRACE_DAY_MIN),
        ): selector.selector({
            "number": {"min": 5, "max": 120, "step": 5, "unit_of_measurement": "min"}
        }),

        vol.Optional(
            CONF_GRACE_NIGHT_MIN,
            default=defaults.get(CONF_GRACE_NIGHT_MIN, DEFAULT_GRACE_NIGHT_MIN),
        ): selector.selector({
            "number": {"min": 5, "max": 60, "step": 5, "unit_of_measurement": "min"}
        }),

        vol.Optional(
            CONF_AUTO_OFF_TEMP_THRESHOLD,
            default=defaults.get(
                CONF_AUTO_OFF_TEMP_THRESHOLD, DEFAULT_AUTO_OFF_TEMP_THRESHOLD
            ),
        ): selector.selector({
            "number": {"min": 10, "max": 30, "step": 1, "unit_of_measurement": "°C"}
        }),

        vol.Optional(
            CONF_AUTO_OFF_TEMP_DAYS,
            default=defaults.get(CONF_AUTO_OFF_TEMP_DAYS, DEFAULT_AUTO_OFF_TEMP_DAYS),
        ): selector.selector({
            "number": {"min": 1, "max": 14, "step": 1, "unit_of_measurement": "days"}
        }),
    })


def _room_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Required(
            CONF_ROOM_NAME,
            default=defaults.get(CONF_ROOM_NAME, ""),
        ): selector.selector({"text": {}}),

        vol.Required(
            CONF_CLIMATE_ENTITY,
            default=defaults.get(CONF_CLIMATE_ENTITY, ""),
        ): selector.selector({"entity": {"domain": "climate"}}),

        vol.Optional(
            CONF_WINDOW_SENSORS,
            default=defaults.get(CONF_WINDOW_SENSORS, []),
        ): selector.selector({
            "entity": {"domain": "binary_sensor", "multiple": True}
        }),

        vol.Optional(
            CONF_WINDOW_DELAY_MIN,
            default=defaults.get(CONF_WINDOW_DELAY_MIN, DEFAULT_WINDOW_DELAY_MIN),
        ): selector.selector({
            "number": {"min": 1, "max": 30, "step": 1, "unit_of_measurement": "min"}
        }),

        vol.Optional(
            CONF_AWAY_TEMP_OVERRIDE,
            default=defaults.get(CONF_AWAY_TEMP_OVERRIDE, 10),
        ): selector.selector({
            "number": {"min": 5, "max": 20, "step": 0.5, "unit_of_measurement": "°C"}
        }),
    })


def _person_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Required(
            CONF_PERSON_ENTITY,
            default=defaults.get(CONF_PERSON_ENTITY, ""),
        ): selector.selector({"entity": {"domain": "person"}}),

        vol.Optional(
            CONF_PERSON_TRACKING,
            default=defaults.get(CONF_PERSON_TRACKING, True),
        ): selector.selector({"boolean": {}}),

        vol.Optional(
            CONF_PREHEAT_LEAD_TIME_MIN,
            default=defaults.get(
                CONF_PREHEAT_LEAD_TIME_MIN, DEFAULT_PREHEAT_LEAD_TIME_MIN
            ),
        ): selector.selector({
            "number": {"min": 5, "max": 60, "step": 5, "unit_of_measurement": "min"}
        }),
    })


def _notifications_schema(defaults: dict = {}) -> vol.Schema:
    return vol.Schema({
        vol.Optional(
            CONF_NOTIFY_PRESENCE,
            default=defaults.get(CONF_NOTIFY_PRESENCE, True),
        ): selector.selector({"boolean": {}}),

        vol.Optional(
            CONF_NOTIFY_WINDOWS,
            default=defaults.get(CONF_NOTIFY_WINDOWS, True),
        ): selector.selector({"boolean": {}}),

        vol.Optional(
            CONF_NOTIFY_WINDOW_WARNING_30,
            default=defaults.get(CONF_NOTIFY_WINDOW_WARNING_30, True),
        ): selector.selector({"boolean": {}}),

        vol.Optional(
            CONF_NOTIFY_PREHEAT,
            default=defaults.get(CONF_NOTIFY_PREHEAT, True),
        ): selector.selector({"boolean": {}}),

        vol.Optional(
            CONF_ENERGY_TRACKING,
            default=defaults.get(CONF_ENERGY_TRACKING, True),
        ): selector.selector({"boolean": {}}),
    })


# ── Config Flow ───────────────────────────────────────────────────────────────

class HeatManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict] = []
        self._persons: list[dict] = []

    # ── Step 1: Global settings ───────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """First shown step when user clicks Add Integration."""
        # Prevent duplicate entries
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

    # ── Step 2: Add rooms (repeatable) ────────────────────────────────────────

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.pop("_action", "add_more")

            if user_input.get(CONF_ROOM_NAME) and user_input.get(CONF_CLIMATE_ENTITY):
                climate = user_input.get(CONF_CLIMATE_ENTITY, "")
                if self.hass.states.get(climate) is None:
                    errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
                else:
                    self._rooms.append(dict(user_input))

            if not errors:
                if action == "done":
                    if not self._rooms:
                        errors["base"] = "no_rooms"
                    else:
                        self._data[CONF_ROOMS] = self._rooms
                        return await self.async_step_person()

        schema = vol.Schema({
            **_room_schema(user_input or {}).schema,
            vol.Optional("_action", default="add_more"): selector.selector({
                "select": {
                    "options": [
                        {"value": "add_more", "label": "Save and add another room"},
                        {"value": "done", "label": "Save and continue"},
                    ]
                }
            }),
        })

        return self.async_show_form(
            step_id="room",
            data_schema=schema,
            errors=errors,
            description_placeholders={"room_count": str(len(self._rooms))},
        )

    # ── Step 3: Add persons (repeatable) ─────────────────────────────────────

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.pop("_action", "add_more")

            if user_input.get(CONF_PERSON_ENTITY):
                person = user_input.get(CONF_PERSON_ENTITY, "")
                if self.hass.states.get(person) is None:
                    errors[CONF_PERSON_ENTITY] = "entity_not_found"
                else:
                    self._persons.append(dict(user_input))

            if not errors:
                if action == "done":
                    self._data[CONF_PERSONS] = self._persons
                    return await self.async_step_presence_global()

        schema = vol.Schema({
            **_person_schema(user_input or {}).schema,
            vol.Optional("_action", default="add_more"): selector.selector({
                "select": {
                    "options": [
                        {"value": "add_more", "label": "Save and add another person"},
                        {"value": "done", "label": "Save and continue"},
                    ]
                }
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
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_notifications()

        return self.async_show_form(
            step_id="presence_global",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ALARM_PANEL,
                    default="",
                ): selector.selector({
                    "entity": {"domain": "alarm_control_panel"}
                }),
            }),
        )

    # ── Step 4: Notifications ─────────────────────────────────────────────────

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
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
    """Post-setup options editing."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            section = user_input.get("section")
            if section == "global":
                return await self.async_step_global()
            if section == "notifications":
                return await self.async_step_notifications()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("section"): selector.selector({
                    "select": {
                        "options": [
                            {"value": "global", "label": "Season & global settings"},
                            {"value": "notifications", "label": "Notification preferences"},
                        ]
                    }
                })
            }),
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={**self._config_entry.options, **user_input}
            )
        current = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="global",
            data_schema=_step1_schema(current),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={**self._config_entry.options, **user_input}
            )
        current = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="notifications",
            data_schema=_notifications_schema(current),
        )
