"""Test the Midnight Alerts trigger button."""
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts.api import (
    MidnightAlertsApiClient,
    MidnightAlertsApiError,
)
from custom_components.midnight_alerts.button import MidnightAlertButton
from custom_components.midnight_alerts.const import DOMAIN


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={})


def test_available_reflects_whether_a_client_is_configured():
    """The button is unavailable until an API key/client has been set up."""
    assert MidnightAlertButton(_make_entry(), None).available is False

    client = AsyncMock(spec=MidnightAlertsApiClient)
    assert MidnightAlertButton(_make_entry(), client).available is True


async def test_async_press_without_client_raises():
    """Pressing the button before an API key is configured raises a clear error."""
    button = MidnightAlertButton(_make_entry(), None)

    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_async_press_with_client_triggers_alert():
    """Pressing the button sends an alert through the configured client."""
    client = AsyncMock(spec=MidnightAlertsApiClient)
    button = MidnightAlertButton(_make_entry(), client)

    await button.async_press()

    client.async_trigger_alert.assert_awaited_once()
    (payload,) = client.async_trigger_alert.await_args.args
    assert "address" in payload
    assert "lat" in payload
    assert "lng" in payload


async def test_async_press_swallows_api_error():
    """An API failure while sending the alert is logged, not raised to the UI."""
    client = AsyncMock(spec=MidnightAlertsApiClient)
    client.async_trigger_alert.side_effect = MidnightAlertsApiError("boom")
    button = MidnightAlertButton(_make_entry(), client)

    await button.async_press()
