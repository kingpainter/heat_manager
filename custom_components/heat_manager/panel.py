"""
Heat Manager — Panel and Lovelace card registration.

FIX: async_register_static_paths raises RuntimeError if the same URL is
     registered twice in the same HA session (aiohttp routes cannot be
     removed). We guard with a hass.data flag so registration only happens
     once per HA session, regardless of how many times the config entry
     is loaded or reloaded.
"""
from __future__ import annotations

import logging
import os

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

PANEL_URL    = f"/api/{DOMAIN}-panel"
CARDS_URL    = f"/api/{DOMAIN}-cards"
PANEL_NAME   = "heat-manager-panel"
PANEL_TITLE  = "Heat Manager"
PANEL_ICON   = "mdi:radiator"
PANEL_FILE   = "heat-manager-panel.js"
CARDS_FILE   = "heat-manager-cards.js"
FRONTEND_DIR = "frontend"

# hass.data key for tracking what has already been registered this session
_SESSION_KEY = f"{DOMAIN}_session_registered"


async def async_register_panel(hass: HomeAssistant) -> None:
    """
    Register sidebar panel and Lovelace card resource.

    Static HTTP paths and the sidebar panel are registered at most once per
    HA session. The _panel_registered flag in hass.data[DOMAIN] tracks
    whether the panel entry itself has been created (it survives reloads
    within the same session because it lives in frontend, not in the entry).
    """
    root_dir     = os.path.join(hass.config.path("custom_components"), DOMAIN)
    frontend_dir = os.path.join(root_dir, FRONTEND_DIR)
    panel_file   = os.path.join(frontend_dir, PANEL_FILE)
    cards_file   = os.path.join(frontend_dir, CARDS_FILE)

    # ── Static HTTP paths — register once per HA session ─────────────────────
    # aiohttp does not allow re-registering the same GET route. We use a
    # session-level flag stored directly on hass.data to survive entry reloads.
    if not hass.data.get(_SESSION_KEY, False):
        static_paths: list[StaticPathConfig] = []
        if os.path.exists(panel_file):
            static_paths.append(StaticPathConfig(PANEL_URL, panel_file, cache_headers=False))
        if os.path.exists(cards_file):
            static_paths.append(StaticPathConfig(CARDS_URL, cards_file, cache_headers=False))

        if static_paths:
            try:
                await hass.http.async_register_static_paths(static_paths)
                _LOGGER.info("Registered %d static path(s) for Heat Manager", len(static_paths))
            except RuntimeError as err:
                # Path already registered from a previous load — safe to ignore
                _LOGGER.debug("Static paths already registered (safe to ignore): %s", err)

        hass.data[_SESSION_KEY] = True

    # ── Sidebar panel — register once per HA session ──────────────────────────
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get("_panel_registered", False):
        _LOGGER.debug("Panel already registered — skipping")
        return

    if not os.path.exists(panel_file):
        _LOGGER.debug("Panel JS not found — skipping sidebar registration")
        return

    try:
        panel_mtime = int(os.path.getmtime(panel_file))
    except OSError:
        panel_mtime = 0

    try:
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name=PANEL_NAME,
            frontend_url_path=DOMAIN,
            module_url=f"{PANEL_URL}?v={VERSION}&m={panel_mtime}",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
            config={},
        )
        _LOGGER.info("Sidebar panel registered at /%s", DOMAIN)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register sidebar panel: %s", err)

    # ── Lovelace resource ─────────────────────────────────────────────────────
    if os.path.exists(cards_file):
        try:
            cards_mtime = int(os.path.getmtime(cards_file))
        except OSError:
            cards_mtime = 0
        await _register_lovelace_resource(
            hass,
            url=f"{CARDS_URL}?v={VERSION}&m={cards_mtime}",
            url_base=CARDS_URL,
        )

    hass.data[DOMAIN]["_panel_registered"] = True


async def _register_lovelace_resource(
    hass: HomeAssistant, url: str, url_base: str
) -> None:
    """Add or update the cards JS as a Lovelace resource."""
    import asyncio

    try:
        resources = hass.data.get("lovelace_resources")
        if resources is None:
            lovelace = hass.data.get("lovelace")
            if lovelace is None:
                _LOGGER.warning(
                    "Lovelace not available — add '%s' manually as a JS module resource", url
                )
                return
            resources = getattr(lovelace, "resources", None)

        if resources is None:
            _LOGGER.warning("Cannot find Lovelace resource store")
            return

        for _ in range(10):
            if getattr(resources, "loaded", True):
                break
            await asyncio.sleep(1)

        existing = [r for r in resources.async_items() if r["url"].startswith(url_base)]
        if existing:
            resource = existing[0]
            if resource["url"] != url:
                await resources.async_update_item(resource["id"], {"res_type": "module", "url": url})
                _LOGGER.info("Updated Lovelace card resource: %s", url)
        else:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered Lovelace card resource: %s", url)

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register Lovelace resource: %s", err)


def async_unregister_panel(hass: HomeAssistant) -> None:
    """
    Remove the sidebar panel entry on config entry unload.
    Does NOT clear the session-level static path flag — those routes
    live for the entire HA session and cannot be removed from aiohttp.
    """
    from homeassistant.components import frontend

    if hass.data.get(DOMAIN, {}).get("_panel_registered", False):
        try:
            frontend.async_remove_panel(hass, DOMAIN)
            _LOGGER.debug("Panel removed from sidebar")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not remove panel: %s", err)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["_panel_registered"] = False
