"""
Heat Manager — Integration setup.

Lifecycle
---------
async_setup_entry   Called when HA loads the config entry.
                    Creates the coordinator, starts all engines,
                    registers services, and registers the Lovelace
                    frontend resource.
async_unload_entry  Called when the user removes the integration.
"""
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
    LOVELACE_RESOURCE_PATH,
    PLATFORMS,
    SERVICE_FORCE_ROOM_ON,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_SET_CONTROLLER_STATE,
    ControllerState,
)
from .coordinator import HeatManagerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heat Manager from a config entry."""
    coordinator = HeatManagerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    _register_services(hass, coordinator)

    # Register Lovelace frontend resource
    _register_frontend(hass)

    # Listen for options updates
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
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# ── Service registration ──────────────────────────────────────────────────────

def _register_services(hass: HomeAssistant, coordinator: HeatManagerCoordinator) -> None:
    """Register all Heat Manager services."""

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
        room_name = call.data["room_name"]
        await coordinator.presence_engine.force_room_on(room_name)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CONTROLLER_STATE,
        handle_set_controller_state,
        schema=vol.Schema({
            vol.Required("state"): vol.In(CONTROLLER_STATE_OPTIONS),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE,
        handle_pause,
        schema=vol.Schema({
            vol.Optional("duration_minutes", default=DEFAULT_PAUSE_DURATION_MIN): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=480)
            ),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME,
        handle_resume,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_ROOM_ON,
        handle_force_room_on,
        schema=vol.Schema({
            vol.Required("room_name"): cv.string,
        }),
    )


# ── Lovelace frontend resource ────────────────────────────────────────────────

def _register_frontend(hass: HomeAssistant) -> None:
    """
    Register the bundled Lovelace card as a static resource.
    The JS file lives at custom_components/heat_manager/frontend/heat-manager-card.js
    and is served at /heat_manager/heat-manager-card.js
    """
    import pathlib

    frontend_dir = pathlib.Path(__file__).parent / "frontend"
    if not frontend_dir.exists():
        _LOGGER.debug(
            "Frontend directory not yet present — skipping resource registration"
        )
        return

    card_file = frontend_dir / "heat-manager-card.js"
    if not card_file.exists():
        _LOGGER.debug("heat-manager-card.js not found — skipping resource registration")
        return

    hass.http.register_static_path(
        LOVELACE_RESOURCE_PATH,
        str(card_file),
        cache_headers=False,
    )
    _LOGGER.debug("Registered Lovelace resource at %s", LOVELACE_RESOURCE_PATH)
