"""Test the Midnight Alerts config flow."""
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
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


def _validate_result(hass, *, matches=True):
    """A validate() response as the server would return it - the distance
    math itself lives server-side now, so tests just fix the outcome."""
    return {"valid": True, "location_match": matches}


async def test_form_user_success(hass):
    """A valid API key with a matching account location creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Midnight 911"
    assert result["data"] == {CONF_API_KEY: "test-key"}


async def test_form_location_mismatch(hass):
    """An account location far from hass.config's own location blocks setup."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass, matches=False))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "location_mismatch"}


async def test_form_no_account_location(hass):
    """An API key with no address on file yet blocks setup with a distinct error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    validate_result = {"valid": True, "location_match": None}
    with patch(VALIDATE, new=AsyncMock(return_value=validate_result)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_account_location"}


async def test_form_invalid_auth(hass):
    """A rejected API key shows invalid_auth and lets the user retry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsAuthError("bad key"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "wrong-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass):
    """A connection failure shows cannot_connect and lets the user retry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsApiError("boom"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "test-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(hass):
    """A second instance aborts since only one account is supported."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_API_KEY: "existing-key"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
