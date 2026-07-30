"""API client for Midnight Alerts."""
import logging

from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://alerts.midnight.security/api"


class MidnightAlertsApiError(Exception):
    """Raised when a Midnight Alerts API call fails."""


class MidnightAlertsAuthError(MidnightAlertsApiError):
    """Raised when the API key is rejected."""


async def async_exchange_code(session: ClientSession, code: str) -> str:
    """Exchange a one-time login code from app.midnight.security for an API key."""
    url = f"{BASE_URL}/oauth/exchange"
    try:
        async with session.post(url, json={"code": code}) as resp:
            if resp.status in (400, 401, 403):
                raise MidnightAlertsAuthError(f"Login code rejected ({resp.status})")
            if resp.status != 200:
                raise MidnightAlertsApiError(
                    f"POST oauth/exchange failed: {resp.status} {await resp.text()}"
                )
            data = await resp.json()
    except ClientError as err:
        raise MidnightAlertsApiError(f"Error connecting to API: {err}") from err

    api_key = data.get("api_key")
    if not api_key:
        raise MidnightAlertsApiError("Exchange response missing api_key")
    return api_key


class MidnightAlertsApiClient:
    """Client for the Midnight Alerts API."""

    def __init__(self, api_key: str, session: ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def async_validate(self) -> None:
        """Validate the API key, raising if it is rejected."""
        await self._async_request("GET", "validate")

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
