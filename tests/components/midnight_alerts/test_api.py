"""Test the Midnight Alerts API client."""
import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.midnight_alerts.api import (
    BASE_URL,
    MidnightAlertsApiClient,
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)


async def test_async_validate_success(hass, aioclient_mock):
    """A 200 response means the key is valid."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=200)

    client = MidnightAlertsApiClient("good-key", async_get_clientsession(hass))
    await client.async_validate()


@pytest.mark.parametrize("status", [401, 403])
async def test_async_validate_invalid_auth(hass, aioclient_mock, status):
    """A 401 or 403 response means the key was rejected."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=status)

    client = MidnightAlertsApiClient("bad-key", async_get_clientsession(hass))
    with pytest.raises(MidnightAlertsAuthError):
        await client.async_validate()


async def test_async_validate_server_error(hass, aioclient_mock):
    """Any other non-200 response is a generic API error, not an auth error."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=500, text="boom")

    client = MidnightAlertsApiClient("some-key", async_get_clientsession(hass))
    with pytest.raises(MidnightAlertsApiError):
        await client.async_validate()


async def test_async_validate_connection_error(hass, aioclient_mock):
    """A network failure raises MidnightAlertsApiError, not the raw aiohttp error."""
    aioclient_mock.get(f"{BASE_URL}/validate", exc=aiohttp.ClientError("no route"))

    client = MidnightAlertsApiClient("some-key", async_get_clientsession(hass))
    with pytest.raises(MidnightAlertsApiError):
        await client.async_validate()


async def test_async_trigger_alert_sends_payload_and_auth_header(hass, aioclient_mock):
    """Triggering an alert POSTs the payload with a bearer token."""
    aioclient_mock.post(f"{BASE_URL}/alerts", status=200)

    client = MidnightAlertsApiClient("secret-key", async_get_clientsession(hass))
    payload = {"name": "Test Alert"}
    await client.async_trigger_alert(payload)

    assert len(aioclient_mock.mock_calls) == 1
    method, url, data, headers = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert str(url) == f"{BASE_URL}/alerts"
    assert data == payload
    assert headers["Authorization"] == "Bearer secret-key"


async def test_async_trigger_alert_failure_raises_api_error(hass, aioclient_mock):
    """A rejected alert raises MidnightAlertsApiError."""
    aioclient_mock.post(f"{BASE_URL}/alerts", status=500, text="boom")

    client = MidnightAlertsApiClient("secret-key", async_get_clientsession(hass))
    with pytest.raises(MidnightAlertsApiError):
        await client.async_trigger_alert({"name": "Test Alert"})
