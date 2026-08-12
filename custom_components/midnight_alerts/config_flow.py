"""Config flow for Midnight Alerts."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_API_KEY, DOMAIN, GET_KEY_URL


class MidnightAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Midnight Alerts."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Ask for the API key, with a link to get one from the web app."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Midnight 911", data={CONF_API_KEY: user_input[CONF_API_KEY]}
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            description_placeholders={"get_key_url": GET_KEY_URL},
        )
