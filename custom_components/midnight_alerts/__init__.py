"""Midnight Alerts integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.loader import async_get_integration

from .api import MidnightAlertsApiClient, MidnightAlertsApiError, MidnightAlertsAuthError
from .const import CONF_ENABLE_CRASH_REPORTING, DOMAIN, CONF_API_KEY

LOCATION_MISMATCH_ISSUE_ID = "location_mismatch"

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
        result = await client.async_validate(
            latitude=hass.config.latitude, longitude=hass.config.longitude
        )
    except MidnightAlertsAuthError as err:
        raise ConfigEntryAuthFailed("Invalid Midnight Alerts API key") from err
    except MidnightAlertsApiError as err:
        raise ConfigEntryNotReady(f"Error connecting to Midnight Alerts: {err}") from err

    # Non-blocking: a location drift after initial setup (e.g. hass.config's
    # own location changed) shouldn't take the whole integration down - it's
    # surfaced as a persistent repair issue instead, same as any other
    # ongoing-but-not-fatal problem a user needs to go fix. location_match is
    # computed server-side (single source of truth for the distance math);
    # None means there was nothing to compare and isn't treated as a mismatch.
    if result.get("location_match") is False:
        ir.async_create_issue(
            hass,
            DOMAIN,
            LOCATION_MISMATCH_ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=LOCATION_MISMATCH_ISSUE_ID,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, LOCATION_MISMATCH_ISSUE_ID)

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
