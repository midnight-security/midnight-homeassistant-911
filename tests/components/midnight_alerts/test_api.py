"""Test the Midnight Alerts API client."""
from unittest.mock import patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.midnight_alerts import error_reporting
from custom_components.midnight_alerts.api import (
    BASE_URL,
    MidnightAlertsApiClient,
    MidnightAlertsApiError,
    MidnightAlertsAuthError,
)


def _client(hass, **kwargs):
    """Build a client bound to the mocked aiohttp session."""
    return MidnightAlertsApiClient("test-key", async_get_clientsession(hass), **kwargs)


async def test_async_validate_hits_versioned_base_url(hass, aioclient_mock):
    """validate() must call BASE_URL/validate with a bearer Authorization header."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=200)

    await _client(hass).async_validate()

    assert aioclient_mock.call_count == 1
    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert str(url) == f"{BASE_URL}/validate"
    assert headers["Authorization"] == "Bearer test-key"


async def test_async_trigger_alert_posts_json_payload(hass, aioclient_mock):
    """trigger_alert() must POST the payload to BASE_URL/alerts."""
    aioclient_mock.post(f"{BASE_URL}/alerts", status=200)

    await _client(hass).async_trigger_alert({"area": "home"})

    method, url, data, _ = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert str(url) == f"{BASE_URL}/alerts"
    assert data == {"area": "home"}


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_rejection_raises_auth_error(hass, aioclient_mock, status):
    """401/403 must raise MidnightAlertsAuthError specifically, not the generic error."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=status)

    with pytest.raises(MidnightAlertsAuthError, match=str(status)):
        await _client(hass).async_validate()


async def test_non_200_error_message_excludes_response_body(hass, aioclient_mock, caplog):
    """The raised message must not leak an upstream gateway's raw HTML body.

    That body still needs to be visible for troubleshooting, so it's expected
    in the debug log instead.
    """
    body = "<html><body>502 Bad Gateway</body></html>"
    aioclient_mock.get(f"{BASE_URL}/validate", status=502, text=body)

    with caplog.at_level("DEBUG"):
        with pytest.raises(MidnightAlertsApiError) as exc_info:
            await _client(hass).async_validate()

    assert str(exc_info.value) == "GET validate failed with HTTP 502"
    assert body not in str(exc_info.value)
    assert body in caplog.text


async def test_connection_failure_wrapped_in_api_error(hass, aioclient_mock):
    """A transport-level failure (no HTTP response at all) is wrapped, not leaked raw."""
    aioclient_mock.get(f"{BASE_URL}/validate", exc=ClientConnectionError("boom"))

    with pytest.raises(MidnightAlertsApiError, match="Error connecting to API"):
        await _client(hass).async_validate()


async def test_failures_reported_with_operation_and_release_when_enabled(
    hass, aioclient_mock
):
    """report_errors=True must forward failures to error_reporting with the path as operation."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=500, text="boom")

    with patch.object(error_reporting, "report_exception") as mock_report:
        with pytest.raises(MidnightAlertsApiError):
            await _client(hass, report_errors=True, release="1.2.3").async_validate()

    mock_report.assert_called_once()
    _, kwargs = mock_report.call_args
    assert kwargs["operation"] == "validate"
    assert kwargs["enabled"] is True
    assert kwargs["release"] == "1.2.3"


async def test_failures_not_enabled_for_reporting_by_default(hass, aioclient_mock):
    """report_errors defaults to False, so error_reporting must be told not to report."""
    aioclient_mock.get(f"{BASE_URL}/validate", status=500, text="boom")

    with patch.object(error_reporting, "report_exception") as mock_report:
        with pytest.raises(MidnightAlertsApiError):
            await _client(hass).async_validate()

    _, kwargs = mock_report.call_args
    assert kwargs["enabled"] is False


async def test_connection_failure_also_reported_when_enabled(hass, aioclient_mock):
    """The ClientError path must report through error_reporting too, not just API errors."""
    aioclient_mock.get(f"{BASE_URL}/validate", exc=ClientConnectionError("boom"))

    with patch.object(error_reporting, "report_exception") as mock_report:
        with pytest.raises(MidnightAlertsApiError):
            await _client(hass, report_errors=True).async_validate()

    mock_report.assert_called_once()
    _, kwargs = mock_report.call_args
    assert kwargs["operation"] == "validate"
    assert kwargs["enabled"] is True
