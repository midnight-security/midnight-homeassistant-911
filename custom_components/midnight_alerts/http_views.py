"""HTTP view that receives the redirect back from app.midnight.security."""
import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import UnknownFlowError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MidnightAlertsApiError, async_exchange_code
from .const import CALLBACK_URL_PATH, CONF_API_KEY, DOMAIN

_LOGGER = logging.getLogger(__name__)

_CLOSE_WINDOW_HTML = (
    "<html><body>Login complete. You can close this window and return to "
    "Home Assistant.<script>window.close()</script></body></html>"
)


class MidnightAlertsExternalCallbackView(HomeAssistantView):
    """Resume the config flow once app.midnight.security redirects back."""

    url = CALLBACK_URL_PATH
    name = f"api:{DOMAIN}:external:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Handle the redirect."""
        hass: HomeAssistant = request.app["hass"]
        flow_id = request.query.get("flow_id")

        if not flow_id:
            return web.Response(status=400, text="Missing flow_id parameter.")

        if error := request.query.get("error"):
            return await self._resume_flow(hass, flow_id, {"error": error})

        code = request.query.get("code")
        if not code:
            return web.Response(status=400, text="Missing code parameter.")

        try:
            api_key = await async_exchange_code(async_get_clientsession(hass), code)
        except MidnightAlertsApiError as err:
            _LOGGER.error("Failed to exchange Midnight Alerts login code: %s", err)
            return await self._resume_flow(hass, flow_id, {"error": "exchange_failed"})

        return await self._resume_flow(hass, flow_id, {CONF_API_KEY: api_key})

    async def _resume_flow(
        self, hass: HomeAssistant, flow_id: str, user_input: dict
    ) -> web.Response:
        """Push the result back into the waiting config flow."""
        try:
            await hass.config_entries.flow.async_configure(
                flow_id=flow_id, user_input=user_input
            )
        except UnknownFlowError:
            return web.Response(
                status=400,
                text=(
                    "Setup session expired. Please restart the integration "
                    "setup in Home Assistant."
                ),
            )
        return web.Response(
            headers={"content-type": "text/html"}, text=_CLOSE_WINDOW_HTML
        )
