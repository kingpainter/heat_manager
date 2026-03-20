"""
Heat Manager — Panel and Lovelace card registration.

FIX: CARDS_FILE corrected to "heat-manager-card.js" (no 's').
FIX: async_register_static_paths raises RuntimeError if same URL is
     registered twice — session-level flag prevents this on reload.
FIX: _register_lovelace_resource now cleans up ALL existing heat_manager
     card resources before adding the canonical one, preventing duplicates.
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
CARDS_FILE   = "heat-manager-card.js"
FRONTEND_DIR = "frontend"

_SESSION_KEY = f"{DOMAIN}_session_registered"

# All URL prefixes that could belong to a previous registration of this card
_CARD_URL_PREFIXES = (
    f"/api/{DOMAIN}-cards",
    f"/{DOMAIN}/heat-manager-card",
    f"/{DOMAIN}/heat-manager-cards",
)


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register sidebar panel and Lovelace card resource."""
    root_dir     = os.path.join(hass.config.path("custom_components"), DOMAIN)
    frontend_dir = os.path.join(root_dir, FRONTEND_DIR)
    panel_file   = os.path.join(frontend_dir, PANEL_FILE)
    cards_file   = os.path.join(frontend_dir, CARDS_FILE)

    _LOGGER.debug("Panel: %s exists=%s", panel_file, os.path.exists(panel_file))
    _LOGGER.debug("Cards: %s exists=%s", cards_file, os.path.exists(cards_file))

    # ── Static HTTP paths — once per HA session ───────────────────────────────
    if not hass.data.get(_SESSION_KEY, False):
        static_paths: list[StaticPathConfig] = []
        if os.path.exists(panel_file):
            static_paths.append(StaticPathConfig(PANEL_URL, panel_file, cache_headers=False))
        if os.path.exists(cards_file):
            static_paths.append(StaticPathConfig(CARDS_URL, cards_file, cache_headers=False))

        if static_paths:
            try:
                await hass.http.async_register_static_paths(static_paths)
                _LOGGER.info(
                    "Registered static paths: %s",
                    [p.url_path for p in static_paths],
                )
            except RuntimeError as err:
                _LOGGER.debug("Static paths already registered: %s", err)

        hass.data[_SESSION_KEY] = True

    # ── Sidebar panel — once per session ──────────────────────────────────────
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("_panel_registered", False):
        if os.path.exists(panel_file):
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
        hass.data[DOMAIN]["_panel_registered"] = True

    # ── Lovelace resource ─────────────────────────────────────────────────────
    if os.path.exists(cards_file):
        try:
            cards_mtime = int(os.path.getmtime(cards_file))
        except OSError:
            cards_mtime = 0
        await _register_lovelace_resource(
            hass,
            canonical_url=f"{CARDS_URL}?v={VERSION}&m={cards_mtime}",
        )
    else:
        _LOGGER.warning("Card JS not found at %s", cards_file)


async def _register_lovelace_resource(
    hass: HomeAssistant,
    canonical_url: str,
) -> None:
    """
    Ensure exactly one Lovelace resource entry for the heat_manager card.

    Removes ALL existing entries whose URL starts with any known prefix
    for this card, then adds the single canonical URL. This prevents the
    duplicate-resource problem visible in Settings → Dashboards → Resources.
    """
    import asyncio

    try:
        resources = hass.data.get("lovelace_resources")
        if resources is None:
            lovelace = hass.data.get("lovelace")
            if lovelace is None:
                _LOGGER.warning(
                    "Lovelace not available — add '%s' manually as a JS module resource",
                    canonical_url,
                )
                return
            resources = getattr(lovelace, "resources", None)

        if resources is None:
            _LOGGER.warning("Cannot find Lovelace resource store")
            return

        # Wait for resource store to load
        for _ in range(10):
            if getattr(resources, "loaded", True):
                break
            await asyncio.sleep(1)

        # Remove ALL existing entries for this card (any known prefix)
        existing = [
            r for r in resources.async_items()
            if any(r["url"].startswith(prefix) for prefix in _CARD_URL_PREFIXES)
        ]

        for resource in existing:
            if resource["url"] == canonical_url and len(existing) == 1:
                # Already correct and no duplicates — nothing to do
                _LOGGER.debug("Lovelace resource already up to date: %s", canonical_url)
                return
            await resources.async_delete_item(resource["id"])
            _LOGGER.info("Removed stale Lovelace resource: %s", resource["url"])

        # Add the single canonical entry
        await resources.async_create_item({"res_type": "module", "url": canonical_url})
        _LOGGER.info(
            "Registered Lovelace card resource: %s — "
            "heat-manager-card is now available in the card picker",
            canonical_url,
        )

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register Lovelace resource: %s", err)


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel on config entry unload."""
    from homeassistant.components import frontend

    if hass.data.get(DOMAIN, {}).get("_panel_registered", False):
        try:
            frontend.async_remove_panel(hass, DOMAIN)
            _LOGGER.debug("Panel removed from sidebar")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not remove panel: %s", err)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["_panel_registered"] = False
