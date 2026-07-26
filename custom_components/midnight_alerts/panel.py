"""Sidebar panel registration for Midnight Alerts."""
import os

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_URL = "/api/midnight_alerts/panel"
PANEL_TITLE = "Midnight 911"
PANEL_ICON = "mdi:phone-alert"
_FRONTEND_FILE = "midnight-panel.js"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the Midnight 911 sidebar panel."""
    view_path = os.path.join(os.path.dirname(__file__), "frontend", _FRONTEND_FILE)

    try:
        cache_bust = int(os.path.getmtime(view_path))
    except OSError:
        cache_bust = 0

    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_URL, view_path, cache_headers=False)]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="midnight-alerts-panel",
        frontend_url_path=DOMAIN,
        module_url=f"{PANEL_URL}?m={cache_bust}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=True,
        config={},
        embed_iframe=False,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Unregister the panel."""
    frontend.async_remove_panel(hass, DOMAIN)
