"""Tests for the location_mismatch repair flow."""
from unittest.mock import AsyncMock, patch

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import LOCATION_MISMATCH_ISSUE_ID
from custom_components.midnight_alerts.const import CONF_API_KEY, DOMAIN

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


async def _mismatched_entry(hass) -> MockConfigEntry:
    """A config entry set up once with a location mismatch, issue already raised."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value={"location_match": False})):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _start_fix_flow(hass):
    await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    return manager, await manager.async_init(
        DOMAIN, data={"issue_id": LOCATION_MISMATCH_ISSUE_ID}
    )


async def test_fix_flow_offers_update_key_and_recheck(hass):
    await _mismatched_entry(hass)

    _manager, result = await _start_fix_flow(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == ["update_key", "recheck"]


async def test_update_key_starts_a_reauth_flow_and_leaves_the_issue(hass):
    await _mismatched_entry(hass)

    manager, result = await _start_fix_flow(hass)
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "update_key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_started"

    reauth_flows = [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_REAUTH
    ]
    assert len(reauth_flows) == 1

    # Starting reauth doesn't fix anything by itself - the issue must survive
    # until a reload actually clears it, not be wiped out just because this
    # flow finished.
    issue_registry = ir.async_get(hass)
    assert issue_registry.async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID) is not None


async def test_recheck_reloads_the_entry_and_clears_a_resolved_issue(hass):
    await _mismatched_entry(hass)

    manager, result = await _start_fix_flow(hass)
    with patch(VALIDATE, new=AsyncMock(return_value={"location_match": True})):
        result = await manager.async_configure(
            result["flow_id"], {"next_step_id": "recheck"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "resolved"
    issue_registry = ir.async_get(hass)
    assert issue_registry.async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID) is None


async def test_recheck_leaves_a_still_mismatched_issue_in_place(hass):
    await _mismatched_entry(hass)

    manager, result = await _start_fix_flow(hass)
    with patch(VALIDATE, new=AsyncMock(return_value={"location_match": False})):
        result = await manager.async_configure(
            result["flow_id"], {"next_step_id": "recheck"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "still_mismatched"
    issue_registry = ir.async_get(hass)
    assert issue_registry.async_get_issue(DOMAIN, LOCATION_MISMATCH_ISSUE_ID) is not None
