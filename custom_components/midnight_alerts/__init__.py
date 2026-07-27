"""Midnight Alerts integration."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .alarmo.coordinator import async_setup_alarmo, async_unload_alarmo
from .api import MidnightAlertsApiClient, MidnightAlertsApiError, MidnightAlertsAuthError
from .const import DOMAIN, CONF_API_KEY

PLATFORMS = ["button", "alarm_control_panel"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Midnight Alerts, including its merged Alarmo alarm panel.

    No API key is required at install time - it's added afterward via the
    integration's Configure (options) flow, so the client may be None here.
    """
    await async_setup_alarmo(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = await _async_create_client(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_create_client(
    hass: HomeAssistant, entry: ConfigEntry
) -> MidnightAlertsApiClient | None:
    """Build and validate the API client, if an API key has been configured."""
    api_key = entry.options.get(CONF_API_KEY)
    if not api_key:
        return None

    client = MidnightAlertsApiClient(api_key, async_get_clientsession(hass))
    try:
        await client.async_validate()
    except MidnightAlertsAuthError as err:
        raise ConfigEntryAuthFailed("Invalid Midnight Alerts API key") from err
    except MidnightAlertsApiError as err:
        raise ConfigEntryNotReady(f"Error connecting to Midnight Alerts: {err}") from err
    return client


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options (e.g. the API key) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await async_unload_alarmo(hass)
    return unloaded
