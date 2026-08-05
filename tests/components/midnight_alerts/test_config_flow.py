"""Test the Midnight Alerts config flow."""
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts.api import (
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)
from custom_components.midnight_alerts.const import (
    CONF_API_KEY,
    CONF_ENABLE_CRASH_REPORTING,
    DOMAIN,
)

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
    # not submitted at all - voluptuous fills the schema's own default
    assert result["options"] == {CONF_ENABLE_CRASH_REPORTING: False}


async def test_form_user_success_records_an_accepted_crash_reporting_choice(hass):
    """Checking the box during setup is honored immediately, no separate Configure step needed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-key", CONF_ENABLE_CRASH_REPORTING: True},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # the API key alone stays in data - crash reporting lives in options
    assert result["data"] == {CONF_API_KEY: "test-key"}
    assert result["options"] == {CONF_ENABLE_CRASH_REPORTING: True}


async def test_form_user_success_without_api_key_creates_an_inert_entry(hass):
    """A blank key is a supported choice - setup finishes with no validation attempted."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(VALIDATE, new=AsyncMock(side_effect=AssertionError("should not be called"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "  "}  # whitespace-only counts as blank
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: ""}


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


async def test_reauth_success_updates_existing_entry(hass):
    """A working new key completes reauth and updates the existing entry in place."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_API_KEY: "old-key"}
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_API_KEY: "new-key"}
    # still the same entry, not a duplicate second one
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reauth_still_invalid_shows_form_again(hass):
    """A still-bad key during reauth re-shows the form instead of aborting."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_API_KEY: "old-key"}
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    with patch(VALIDATE, new=AsyncMock(side_effect=MidnightAlertsAuthError("bad key"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "still-wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data == {CONF_API_KEY: "old-key"}


async def test_reauth_does_not_show_or_touch_crash_reporting(hass):
    """Crash reporting is only asked at setup - Configure is the one place to
    revisit it afterward, not duplicated into reauth too (that was confusing)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: "old-key"},
        options={CONF_ENABLE_CRASH_REPORTING: True},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    field_names = {str(marker) for marker in result["data_schema"].schema}
    assert CONF_ENABLE_CRASH_REPORTING not in field_names

    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_API_KEY: "new-key"}
    # untouched, not reset to the schema's own default
    assert entry.options == {CONF_ENABLE_CRASH_REPORTING: True}


async def test_reconfigure_suggests_the_current_api_key_and_crash_reporting_choice(hass):
    """Reconfigure is the one place to revisit both fields after setup - it
    pre-fills the existing key (editing, or filling in a previously-blank
    one, is the whole point here) and the current crash-reporting choice."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: "existing-key"},
        options={CONF_ENABLE_CRASH_REPORTING: True},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    for marker in result["data_schema"].schema:
        if str(marker) == CONF_API_KEY:
            assert marker.description == {"suggested_value": "existing-key"}
        elif str(marker) == CONF_ENABLE_CRASH_REPORTING:
            assert marker.description == {"suggested_value": True}


async def test_reconfigure_can_add_a_previously_blank_api_key(hass):
    """The main path this exists for: add a key to an entry set up without one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: ""},
        options={CONF_ENABLE_CRASH_REPORTING: True},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key", CONF_ENABLE_CRASH_REPORTING: False}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_API_KEY: "new-key"}
    assert entry.options == {CONF_ENABLE_CRASH_REPORTING: False}
    # still the same entry, not a duplicate second one
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_location_mismatch_shows_form_again(hass):
    """Reconfigure goes through the exact same validation path as initial setup."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={CONF_API_KEY: "old-key"})
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    with patch(VALIDATE, new=AsyncMock(return_value=_validate_result(hass, matches=False))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "location_mismatch"}
    assert entry.data == {CONF_API_KEY: "old-key"}
