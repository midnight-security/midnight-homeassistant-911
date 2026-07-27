"""Panel registration for Alarmo integration."""

import os
import logging

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import (
    VERSION,
    PANEL_URL,
    PANEL_ICON,
    PANEL_NAME,
    PANEL_TITLE,
    PANEL_FOLDER,
    PANEL_FILENAME,
)
# The panel's URL path/sidebar target uses the real midnight_alerts domain,
# not alarmo/const.py's DOMAIN (which is only an internal hass.data/storage
# namespace key - see the comment there).
from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_register_panel(hass):
    """Register the panel."""
    panel_dir = os.path.join(os.path.dirname(__file__), PANEL_FOLDER)
    view_url = os.path.join(panel_dir, PANEL_FILENAME)

    try:
        cache_bust = int(os.path.getmtime(view_url))
    except OSError:
        cache_bust = 0

    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_URL, view_url, cache_headers=False)]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_NAME,
        frontend_url_path=DOMAIN,
        module_url=f"{PANEL_URL}?v={VERSION}&m={cache_bust}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=True,
        config={},
    )


def async_unregister_panel(hass):
    """Unregister the panel."""
    frontend.async_remove_panel(hass, DOMAIN)
    _LOGGER.debug("Removing panel")
