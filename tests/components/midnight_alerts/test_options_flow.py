"""Test the Midnight Alerts options flow."""
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts.const import CONF_API_KEY, CONF_ENABLE_CRASH_REPORTING, DOMAIN


async def test_options_flow_defaults_to_disabled(hass):
    """Crash reporting must default to off."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={CONF_API_KEY: "key"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    schema = result["data_schema"].schema
    (default_container,) = [k for k in schema if k == CONF_ENABLE_CRASH_REPORTING]
    assert default_container.default() is False


async def test_options_flow_enables_crash_reporting(hass):
    """Toggling the option on persists it to the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={CONF_API_KEY: "key"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENABLE_CRASH_REPORTING: True}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENABLE_CRASH_REPORTING] is True
