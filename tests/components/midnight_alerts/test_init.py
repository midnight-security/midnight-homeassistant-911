"""Tests for __init__.py's async_setup_entry/async_unload_entry."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import LOCATION_MISMATCH_ISSUE_ID, NO_API_KEY_ISSUE_ID
from custom_components.midnight_alerts.api import (
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)
from custom_components.midnight_alerts.const import CONF_API_KEY, DOMAIN

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


def _validate_result(*, matches=True):
    return {"valid": True, "location_match": matches}


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

    with patch(VALIDATE, new=AsyncMock(return_value={})):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Midnight 911"


async def test_setup_entry_mismatched_location_creates_repair_issue(hass):
    """A location far from hass.config's own location raises a repair issue, non-blocking."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(matches=False))):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    issue = ir.async_get(hass).async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID)
    assert issue is not None


async def test_setup_entry_matching_location_has_no_repair_issue(hass):
    """A location matching hass.config's own location has no repair issue."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result())):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID)
    assert issue is None


async def test_reload_after_location_fixed_clears_repair_issue(hass):
    """A previously-mismatched location that's since been fixed clears the issue on reload."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(matches=False))):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID) is not None

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result())):
        await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID) is None


async def test_setup_entry_without_api_key_loads_without_validating(hass):
    """No key yet is a supported state - setup succeeds, nothing gets validated,
    but a no_api_key repair issue prompts finishing setup rather than staying
    silent about it."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: ""})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(side_effect=AssertionError("should not be called"))):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    issue_registry = ir.async_get(hass)
    assert issue_registry.async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID) is None
    assert issue_registry.async_get_issue(DOMAIN, NO_API_KEY_ISSUE_ID) is not None


async def test_setup_entry_with_api_key_has_no_no_api_key_issue(hass):
    """A key present from the start never raises the issue at all."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result())):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, NO_API_KEY_ISSUE_ID)
    assert issue is None


async def test_reload_after_adding_api_key_clears_no_api_key_issue(hass):
    """Adding a key (e.g. via the no_api_key repair's Reconfigure) and reloading
    clears the issue, same as fixing a location mismatch does."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: ""})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(side_effect=AssertionError("should not be called"))):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, NO_API_KEY_ISSUE_ID) is not None

    hass.config_entries.async_update_entry(entry, data={CONF_API_KEY: "new-key"})
    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result())):
        await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, NO_API_KEY_ISSUE_ID) is None


async def test_unload_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)

    with patch(VALIDATE, new=AsyncMock(return_value={})):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
