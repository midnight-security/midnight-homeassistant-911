"""Test the Midnight Alerts options flow (API key entry and verification)."""
from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts.api import (
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)
from custom_components.midnight_alerts.const import CONF_API_KEY, DOMAIN

VALIDATE = (
    "custom_components.midnight_alerts.config_flow."
    "MidnightAlertsApiClient.async_validate"
)


def _add_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={})
    entry.add_to_hass(hass)
    return entry


async def test_options_flow_valid_key_asks_for_confirmation(hass):
    """A valid API key moves to a confirmation step before saving."""
    entry = _add_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_API_KEY: "good-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "verified"


async def test_options_flow_confirmation_saves_key(hass):
    """Confirming the verified step persists the API key to the entry."""
    entry = _add_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_API_KEY: "good-key"}
        )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: "good-key"}


async def test_options_flow_invalid_auth(hass):
    """A rejected API key shows invalid_auth and lets the user retry."""
    entry = _add_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsAuthError("bad key"))):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_API_KEY: "wrong-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow_cannot_connect(hass):
    """A connection failure shows cannot_connect and lets the user retry."""
    entry = _add_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsApiError("boom"))):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_API_KEY: "some-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"base": "cannot_connect"}
