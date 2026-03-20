"""Heat Manager — Integration setup."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    CONF_ROOMS,
    CONTROLLER_STATE_OPTIONS,
    DEFAULT_PAUSE_DURATION_MIN,
    DOMAIN,
    PLATFORMS,
    SERVICE_FORCE_ROOM_ON,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_SET_CONTROLLER_STATE,
    ControllerState,
)
from .coordinator import HeatManagerCoordinator
from .panel import async_register_panel, async_unregister_panel
from .websocket import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heat Manager from a config entry."""
    coordinator = HeatManagerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass, coordinator)
    async_register_websocket_commands(hass)
    await async_register_panel(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Heat Manager loaded — %d room(s) configured",
        len(entry.data.get(CONF_ROOMS, [])),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HeatManagerCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
        async_unregister_panel(hass)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant, coordinator: HeatManagerCoordinator) -> None:
    async def handle_set_controller_state(call: ServiceCall) -> None:
        state_str = call.data["state"]
        try:
            new_state = ControllerState(state_str)
        except ValueError as err:
            raise ServiceValidationError(
                f"Invalid controller state: {state_str}"
            ) from err
        await coordinator.controller.set_state(new_state)

    async def handle_pause(call: ServiceCall) -> None:
        duration = call.data.get("duration_minutes", DEFAULT_PAUSE_DURATION_MIN)
        await coordinator.controller.pause(duration_minutes=int(duration))

    async def handle_resume(call: ServiceCall) -> None:
        await coordinator.controller.resume()

    async def handle_force_room_on(call: ServiceCall) -> None:
        await coordinator.presence_engine.force_room_on(call.data["room_name"])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_CONTROLLER_STATE, handle_set_controller_state,
        schema=vol.Schema({vol.Required("state"): vol.In(CONTROLLER_STATE_OPTIONS)}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PAUSE, handle_pause,
        schema=vol.Schema({
            vol.Optional("duration_minutes", default=DEFAULT_PAUSE_DURATION_MIN):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=480)),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESUME, handle_resume,
        schema=vol.Schema({}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_ROOM_ON, handle_force_room_on,
        schema=vol.Schema({vol.Required("room_name"): cv.string}),
    )
