"""Heat Manager — Integration setup."""
from __future__ import annotations

import logging

from homeassistant.components.repairs import IssueSeverity, async_create_issue, async_delete_issue
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    CONTROLLER_STATE_OPTIONS,
    DEFAULT_PAUSE_DURATION_MIN,
    DOMAIN,
    PLATFORMS,
    REPAIR_ISSUE_MISSING_CLIMATE,
    SERVICE_FORCE_ROOM_ON,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_SET_CONTROLLER_STATE,
    ControllerState,
)
from .coordinator import HeatManagerCoordinator
from .panel import async_register_panel, async_register_static_paths, async_unregister_panel
from .websocket import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Heat Manager at module level.

    Registers static HTTP paths (panel JS, card JS, logo) immediately at
    HA startup so they are always accessible — even if the config entry
    raises ConfigEntryNotReady and async_setup_entry never completes.
    Without this, Lovelace returns 404 for the card resource on the first
    load after a restart + cache-clear.
    """
    await async_register_static_paths(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heat Manager from a config entry."""
    coordinator = HeatManagerCoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="setup_failed",
        ) from err

    # Raise ConfigEntryNotReady if no configured climate entity is reachable yet.
    # HA will retry setup automatically once entities become available.
    rooms = entry.data.get(CONF_ROOMS, [])
    if rooms:
        reachable = [
            r for r in rooms
            if hass.states.get(r.get("climate_entity", "")) is not None
        ]
        if not reachable:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="setup_failed",
            )

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass, coordinator)
    async_register_websocket_commands(hass)
    await async_register_panel(hass)

    # F-3: raise RepairIssue for rooms whose climate entity is missing
    _async_check_repair_issues(hass, entry)

    # Remove device registry entries for rooms that no longer exist
    _async_remove_stale_devices(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Heat Manager loaded — %d room(s), weather=%s",
        len(rooms),
        entry.data.get(CONF_WEATHER_ENTITY, "none"),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HeatManagerCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
        async_unregister_panel(hass)
        # Clear all repair issues for this entry on unload
        rooms = entry.data.get(CONF_ROOMS, [])
        for room in rooms:
            room_name = room.get("room_name", "")
            if room_name:
                safe = room_name.lower().replace(" ", "_")
                async_delete_issue(
                    hass, DOMAIN,
                    f"{REPAIR_ISSUE_MISSING_CLIMATE}_{safe}_{entry.entry_id[:8]}",
                )
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_check_repair_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """F-3: Create a RepairIssue for every room whose climate entity is absent.

    Called after setup completes.  If the entity exists the issue is deleted
    so it clears automatically after a reload when the entity reappears.
    Issue ID is scoped per room + entry so multiple entries don't collide.
    """
    rooms = {**entry.data, **entry.options}.get(CONF_ROOMS, [])
    for room in rooms:
        room_name  = room.get("room_name", "")
        climate_id = room.get("climate_entity", "")
        if not room_name or not climate_id:
            continue
        safe     = room_name.lower().replace(" ", "_")
        issue_id = f"{REPAIR_ISSUE_MISSING_CLIMATE}_{safe}_{entry.entry_id[:8]}"

        if hass.states.get(climate_id) is None:
            _LOGGER.warning(
                "Heat Manager: climate entity '%s' (room '%s') not found in HA —"
                " raised RepairIssue '%s'",
                climate_id, room_name, issue_id,
            )
            async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key=REPAIR_ISSUE_MISSING_CLIMATE,
                translation_placeholders={
                    "room_name":  room_name,
                    "climate_id": climate_id,
                },
            )
        else:
            # Entity present — clear any lingering issue from a previous load
            async_delete_issue(hass, DOMAIN, issue_id)


def _async_remove_stale_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove device registry entries for rooms that no longer exist in config.

    Called after every setup/reload.  Compares the set of per-room device
    identifiers in the registry against the current room list and removes
    any that are no longer configured.
    """
    dev_reg = dr.async_get(hass)
    current_rooms = {**entry.data, **entry.options}.get(CONF_ROOMS, [])

    # Build the set of valid per-room identifiers for this entry
    valid_identifiers: set[frozenset] = set()
    for room in current_rooms:
        room_name = room.get("room_name", "")
        if room_name:
            safe = room_name.lower().replace(" ", "_")
            valid_identifiers.add(
                frozenset([(DOMAIN, f"{entry.entry_id}_{safe}")])
            )
    # Always keep the global device
    valid_identifiers.add(frozenset([(DOMAIN, entry.entry_id)]))

    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        device_id_set = frozenset(device.identifiers)
        if device_id_set not in valid_identifiers:
            _LOGGER.info(
                "Heat Manager: removing stale device '%s' from device registry",
                device.name,
            )
            dev_reg.async_remove_device(device.id)


def _register_services(hass: HomeAssistant, coordinator: HeatManagerCoordinator) -> None:
    async def handle_set_controller_state(call: ServiceCall) -> None:
        state_str = call.data["state"]
        try:
            new_state = ControllerState(state_str)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_controller_state",
                translation_placeholders={"state": state_str},
            ) from err
        await coordinator.controller.set_state(new_state)

    async def handle_pause(call: ServiceCall) -> None:
        duration = call.data.get("duration_minutes", DEFAULT_PAUSE_DURATION_MIN)
        await coordinator.controller.pause(duration_minutes=int(duration))

    async def handle_resume(call: ServiceCall) -> None:
        await coordinator.controller.resume()

    async def handle_force_room_on(call: ServiceCall) -> None:
        room_name = call.data["room_name"]
        if not coordinator.get_climate_entity(room_name):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="room_not_found",
                translation_placeholders={"room_name": room_name},
            )
        await coordinator.presence_engine.force_room_on(room_name)

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
