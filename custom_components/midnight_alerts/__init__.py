"""Midnight Alerts integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType

from .api import (
    MidnightAlertsApiError,
    MidnightAlertsApiClient,
    MidnightAlertsAuthError,
)
from .const import DOMAIN, CONF_API_KEY, CONF_ENABLE_CRASH_REPORTING

LOCATION_MISMATCH_ISSUE_ID = "location_mismatch"
NO_API_KEY_ISSUE_ID = "no_api_key"

PLATFORMS = ["button", "alarm_control_panel"]


@dataclass
class MidnightAlertsData:
    """Data stored on the config entry's `runtime_data`."""

    client: MidnightAlertsApiClient


type MidnightAlertsConfigEntry = ConfigEntry[MidnightAlertsData]


async def async_setup_entry(
    hass: HomeAssistant, entry: MidnightAlertsConfigEntry
) -> bool:
    """Set up Midnight Alerts."""
    integration = await async_get_integration(hass, DOMAIN)
    client = MidnightAlertsApiClient(
        entry.data.get(CONF_API_KEY, ""),
        async_get_clientsession(hass),
        report_errors=entry.options.get(CONF_ENABLE_CRASH_REPORTING, False),
        release=str(integration.version) if integration.version else None,
    )

    # No key yet is a valid, supported state, not a setup failure: the alarm
    # engine (areas, sensors, PINs, arm/disarm/trigger) is entirely local
    # and works fully without one - only the Trigger Alert button actually
    # calls Midnight's API, and it already handles being unconfigured
    # gracefully (see button.py). There's nothing to validate or check
    # location for without a key, so skip straight past both - but it's
    # still surfaced as a repair issue, since silently doing nothing would
    # leave a user who skipped the key at setup with no indication they
    # still need to add one before Trigger Alert actually does anything.
    if client.is_configured:
        ir.async_delete_issue(hass, DOMAIN, NO_API_KEY_ISSUE_ID)
        try:
            result = await client.async_validate(
                latitude=hass.config.latitude, longitude=hass.config.longitude
            )
        except MidnightAlertsAuthError as err:
            raise ConfigEntryAuthFailed("Invalid Midnight Alerts API key") from err
        except MidnightAlertsApiError as err:
            raise ConfigEntryNotReady(
                f"Error connecting to Midnight Alerts: {err}"
            ) from err

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
                is_fixable=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key=LOCATION_MISMATCH_ISSUE_ID,
                data={"entry_id": entry.entry_id},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, LOCATION_MISMATCH_ISSUE_ID)
    else:
        ir.async_delete_issue(hass, DOMAIN, LOCATION_MISMATCH_ISSUE_ID)
        ir.async_create_issue(
            hass,
            DOMAIN,
            NO_API_KEY_ISSUE_ID,
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key=NO_API_KEY_ISSUE_ID,
            data={"entry_id": entry.entry_id},
        )

    entry.runtime_data = MidnightAlertsData(client=client)

    # Created explicitly (and first) so it deterministically exists before
    # any per-area Midnight Alarm device below tries to link to it via
    # via_device - button.py creating its own device as a side effect isn't
    # a reliable ordering guarantee once platforms are set up concurrently.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        # Deliberately not "Midnight 911 Integration" (matching the entry
        # title/manifest name below) - has_entity_name derives the button's
        # auto-generated entity_id from this device name, and a longer name
        # here means a longer, churned entity_id for every future install.
        name="Midnight 911",
        manufacturer="Midnight Security",
        entry_type=DeviceEntryType.SERVICE,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MidnightAlertsConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
