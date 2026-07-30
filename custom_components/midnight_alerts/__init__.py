"""Midnight Alerts integration."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MidnightAlertsApiClient, MidnightAlertsApiError, MidnightAlertsAuthError
from .const import DOMAIN, CONF_API_KEY
from .http_views import MidnightAlertsExternalCallbackView

PLATFORMS = ["button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Midnight Alerts integration.

    Registers the HTTP view that app.midnight.security redirects back to
    once a login/API key exchange finishes, even before any config entry
    exists.
    """
    hass.http.register_view(MidnightAlertsExternalCallbackView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Midnight Alerts."""
    client = MidnightAlertsApiClient(
        entry.data[CONF_API_KEY], async_get_clientsession(hass)
    )

    # midnight-noo-api has no /api/validate endpoint yet; re-enable once it exists.
    # try:
    #     await client.async_validate()
    # except MidnightAlertsAuthError as err:
    #     raise ConfigEntryAuthFailed("Invalid Midnight Alerts API key") from err
    # except MidnightAlertsApiError as err:
    #     raise ConfigEntryNotReady(f"Error connecting to Midnight Alerts: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
