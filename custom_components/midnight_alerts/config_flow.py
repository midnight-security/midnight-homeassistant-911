"""Config flow for Midnight Alerts."""
from urllib.parse import quote

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import CALLBACK_URL_PATH, CONF_API_KEY, DOMAIN, LOGIN_URL


class MidnightAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Midnight Alerts."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Kick off the browser-based login."""
        return await self.async_step_auth()

    async def async_step_auth(self, user_input=None) -> FlowResult:
        """Open app.midnight.security and wait for it to redirect back."""
        if user_input is not None:
            if user_input.get("error"):
                return self.async_abort(reason="login_failed")
            self._api_key = user_input[CONF_API_KEY]
            return self.async_external_step_done(next_step_id="creation")

        try:
            base_url = get_url(self.hass, allow_internal=True, allow_ip=True)
        except NoURLAvailableError:
            return self.async_abort(reason="no_url_available")

        callback_url = f"{base_url}{CALLBACK_URL_PATH}"
        auth_url = (
            f"{LOGIN_URL}?flow_id={self.flow_id}"
            f"&redirect_uri={quote(callback_url, safe='')}"
        )
        return self.async_external_step(step_id="auth", url=auth_url)

    async def async_step_creation(self, user_input=None) -> FlowResult:
        """Create the config entry from the API key obtained during login."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Midnight 911", data={CONF_API_KEY: self._api_key}
        )
