"""API client for Midnight Alerts."""
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from . import error_reporting

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.midnight.security/functions/v1"


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
        self._api_key = api_key
        self._session = session
        self._report_errors = report_errors
        self._release = release

    async def async_validate(self) -> None:
        """Validate the API key, raising if it is rejected."""
        await self._async_request("GET", "validate")

    async def async_trigger_alert(self, payload: dict) -> None:
        """Trigger an alert."""
        await self._async_request("POST", "alerts", json=payload)

    async def _async_request(self, method: str, path: str, **kwargs: Any) -> None:
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
