"""Tests for __init__.py's async_setup_entry/async_unload_entry."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts.api import (
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)
from custom_components.midnight_alerts.const import CONF_API_KEY, DOMAIN

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


async def test_setup_entry_auth_failure_triggers_reauth(hass):
    """A rejected API key on (re)load, not just at config-flow time, needs reauth."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "bad-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsAuthError("nope"))):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is False
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connect_failure_retries(hass):
    """A transient connection failure should retry, not hard-fail."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsApiError("down"))):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is False
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_creates_hub_device(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Midnight 911"


async def test_unload_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
