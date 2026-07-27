"""Test Midnight Alerts setup/unload and API-client bootstrapping."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import _async_create_client
from custom_components.midnight_alerts.api import (
    MidnightAlertsApiClient,
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)
from custom_components.midnight_alerts.const import CONF_API_KEY, DOMAIN

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


def _entry(options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={}, options=options or {})


async def test_create_client_returns_none_without_api_key(hass):
    """No client is built when no API key has been configured yet."""
    client = await _async_create_client(hass, _entry())
    assert client is None


async def test_create_client_returns_client_for_valid_key(hass):
    """A valid API key produces a usable, validated client."""
    entry = _entry({CONF_API_KEY: "good-key"})

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        client = await _async_create_client(hass, entry)

    assert isinstance(client, MidnightAlertsApiClient)


async def test_create_client_raises_auth_failed_for_bad_key(hass):
    """An invalid API key surfaces as ConfigEntryAuthFailed so HA prompts reauth."""
    entry = _entry({CONF_API_KEY: "bad-key"})

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsAuthError("nope"))):
        try:
            await _async_create_client(hass, entry)
            assert False, "expected ConfigEntryAuthFailed"
        except ConfigEntryAuthFailed:
            pass


async def test_create_client_raises_not_ready_on_connection_error(hass):
    """A connection failure surfaces as ConfigEntryNotReady so HA retries setup."""
    entry = _entry({CONF_API_KEY: "some-key"})

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsApiError("boom"))):
        try:
            await _async_create_client(hass, entry)
            assert False, "expected ConfigEntryNotReady"
        except ConfigEntryNotReady:
            pass


async def test_setup_entry_without_api_key_loads_with_no_client(hass):
    """The integration loads even before an API key is configured."""
    entry = _entry()
    entry.add_to_hass(hass)

    with (
        patch("custom_components.midnight_alerts.async_setup_alarmo", new=AsyncMock()),
        patch("custom_components.midnight_alerts.async_unload_alarmo", new=AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert hass.data[DOMAIN][entry.entry_id] is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_with_valid_key_stores_client(hass):
    """A valid, verified API key is available to platforms via hass.data."""
    entry = _entry({CONF_API_KEY: "good-key"})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.midnight_alerts.async_setup_alarmo", new=AsyncMock()),
        patch("custom_components.midnight_alerts.async_unload_alarmo", new=AsyncMock()),
        patch(VALIDATE, new=AsyncMock(return_value=None)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert isinstance(hass.data[DOMAIN][entry.entry_id], MidnightAlertsApiClient)


async def test_setup_entry_with_invalid_key_enters_setup_error(hass):
    """A rejected API key leaves the entry in an error state prompting reauth."""
    entry = _entry({CONF_API_KEY: "bad-key"})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.midnight_alerts.async_setup_alarmo", new=AsyncMock()),
        patch("custom_components.midnight_alerts.async_unload_alarmo", new=AsyncMock()),
        patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsAuthError("nope"))),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_ERROR
