"""Midnight Alerts integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.loader import async_get_integration

from .api import MidnightAlertsApiClient, MidnightAlertsApiError, MidnightAlertsAuthError
from .const import CONF_ENABLE_CRASH_REPORTING, DOMAIN, CONF_API_KEY

PLATFORMS = ["button", "alarm_control_panel"]


@dataclass
class MidnightAlertsData:
    """Data stored on the config entry's `runtime_data`."""

    client: MidnightAlertsApiClient


type MidnightAlertsConfigEntry = ConfigEntry[MidnightAlertsData]


async def async_setup_entry(hass: HomeAssistant, entry: MidnightAlertsConfigEntry) -> bool:
    """Set up Midnight Alerts."""
    integration = await async_get_integration(hass, DOMAIN)
    client = MidnightAlertsApiClient(
        entry.data[CONF_API_KEY],
        async_get_clientsession(hass),
        report_errors=entry.options.get(CONF_ENABLE_CRASH_REPORTING, False),
        release=str(integration.version) if integration.version else None,
    )

    try:
        await client.async_validate()
    except MidnightAlertsAuthError as err:
        raise ConfigEntryAuthFailed("Invalid Midnight Alerts API key") from err
    except MidnightAlertsApiError as err:
        raise ConfigEntryNotReady(f"Error connecting to Midnight Alerts: {err}") from err

    entry.runtime_data = MidnightAlertsData(client=client)

    # Created explicitly (and first) so it deterministically exists before
    # any per-area Midnight Alarm device below tries to link to it via
    # via_device - button.py creating its own device as a side effect isn't
    # a reliable ordering guarantee once platforms are set up concurrently.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Midnight 911",
        manufacturer="Midnight Security",
        entry_type=DeviceEntryType.SERVICE,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MidnightAlertsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
