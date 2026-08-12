"""API client for Midnight Alerts."""

import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from . import error_reporting
from .const import BASE_API_URL

_LOGGER = logging.getLogger(__name__)


class MidnightAlertsApiError(Exception):
    """Raised when a Midnight Alerts API call fails."""


class MidnightAlertsAuthError(MidnightAlertsApiError):
    """Raised when the API key is rejected."""


class MidnightAlertsApiClient:
    """Client for the Midnight Alerts API."""

    def __init__(
        self,
        api_key: str,
        session: ClientSession,
        *,
        report_errors: bool = False,
        release: str | None = None,
    ) -> None:
        """Create a client bound to a single API key and aiohttp session."""
        self._api_key = api_key
        self._session = session
        self._report_errors = report_errors
        self._release = release

    @property
    def is_configured(self) -> bool:
        """Whether an API key has actually been set.

        The integration can be added with this blank (the alarm engine
        works entirely locally regardless), so callers that would otherwise
        make a doomed request - the button, mainly - can check this first.
        """
        return bool(self._api_key)

    async def async_validate(self, *, latitude: float, longitude: float) -> dict:
        """Validate the API key, raising if it is rejected.

        Sends this Home Assistant instance's own configured location so the
        server can check it against the address on file for the account -
        that comparison lives entirely server-side, not in this client.
        Returns the response body, e.g. {"valid": true, "location_match":
        true | false | null} - null means there was nothing to compare
        (e.g. no address on file yet).
        """
        return await self._async_request(
            "GET", "validate", params={"lat": latitude, "lng": longitude}
        )

    async def async_trigger_alert(self, payload: dict) -> None:
        """Trigger an alert."""
        await self._async_request("POST", "alerts", json=payload)

    async def _async_request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{BASE_API_URL}/{path}"
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
                    # The body is often an upstream gateway's raw HTML error
                    # page (e.g. an nginx 502), not anything meant for a
                    # user - keep that out of the exception message HA shows
                    # verbatim in the UI, but keep it in the debug log for
                    # actually troubleshooting.
                    body = await resp.text()
                    _LOGGER.debug(
                        "Midnight Alerts %s %s returned %s: %s",
                        method,
                        path,
                        resp.status,
                        body,
                    )
                    raise MidnightAlertsApiError(
                        f"{method} {path} failed with HTTP {resp.status}"
                    )
                return await resp.json()
        except ClientError as err:
            wrapped = MidnightAlertsApiError(f"Error connecting to API: {err}")
            error_reporting.report_exception(
                wrapped,
                operation=path,
                enabled=self._report_errors,
                release=self._release,
            )
            raise wrapped from err
        except MidnightAlertsApiError as err:
            error_reporting.report_exception(
                err,
                operation=path,
                enabled=self._report_errors,
                release=self._release,
            )
            raise
