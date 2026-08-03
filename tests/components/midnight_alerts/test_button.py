"""Tests for the Trigger Alert button."""
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts.api import MidnightAlertsApiError
from custom_components.midnight_alerts.const import CONF_API_KEY, DOMAIN

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"
TRIGGER = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_trigger_alert"


async def _setup_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value={})):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_button_press_success(hass, caplog):
    await _setup_entry(hass)

    with patch(TRIGGER, new=AsyncMock(return_value=None)) as mock_trigger:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.midnight_911_trigger_alert"},
            blocking=True,
        )
    mock_trigger.assert_called_once()
    assert mock_trigger.call_args.args[0] == {
        "lat": hass.config.latitude,
        "lng": hass.config.longitude,
    }
    assert "Alert successfully sent" in caplog.text


async def test_button_press_failure_is_logged_not_raised(hass, caplog):
    await _setup_entry(hass)

    with patch(
        TRIGGER, new=AsyncMock(side_effect=MidnightAlertsApiError("boom"))
    ):
        # Must not raise - a failed alert send is a logged error, not a
        # crash of the button press service call.
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.midnight_911_trigger_alert"},
            blocking=True,
        )
    assert "Failed to send alert" in caplog.text
