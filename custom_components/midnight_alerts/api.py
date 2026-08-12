"""API client for Midnight Alerts."""
import logging

from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)

# alerts.midnight.security still points at the old, decommissioned
# midnight-noo-api Railway service (502s). dev.api.midnight.security is the
# dev-environment equivalent of api.midnight.security (proxies to the
# `develop` branch Supabase project) -- matches dev.app.midnight.security,
# which is what all API keys/HA testing has actually been done against.
BASE_URL = "https://dev.api.midnight.security/functions/v1"


class MidnightAlertsApiError(Exception):
    """Raised when a Midnight Alerts API call fails."""


class MidnightAlertsAuthError(MidnightAlertsApiError):
    """Raised when the API key is rejected."""


class MidnightAlertsApiClient:
    """Client for the Midnight Alerts API."""

    def __init__(self, api_key: str, session: ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def async_validate(self) -> None:
        """Validate the API key, raising if it is rejected."""
        await self._async_request("GET", "oauth/token")

    async def async_trigger_alert(self, payload: dict) -> None:
        """Trigger an alert."""
        await self._async_request("POST", "alerts", json=payload)

    async def _async_request(self, method: str, path: str, **kwargs) -> None:
        url = f"{BASE_URL}/{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with self._session.request(
                method, url, headers=headers, **kwargs
            ) as resp:
                if resp.status in (401, 403):
                    raise MidnightAlertsAuthError(f"Invalid API key ({resp.status})")
                if resp.status != 200:
                    raise MidnightAlertsApiError(
                        f"{method} {path} failed: {resp.status} {await resp.text()}"
                    )
        except ClientError as err:
            raise MidnightAlertsApiError(f"Error connecting to API: {err}") from err
