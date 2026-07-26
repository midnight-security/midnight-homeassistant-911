"""Config flow for Midnight Alerts."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MidnightAlertsApiClient, MidnightAlertsApiError, MidnightAlertsAuthError
from .const import DOMAIN, CONF_API_KEY, ACCOUNT_URL


class MidnightAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Midnight Alerts."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Install the integration; the API key is added afterward via Configure."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Midnight 911", data={})

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "MidnightAlertsOptionsFlow":
        """Get the options flow for this handler."""
        return MidnightAlertsOptionsFlow()


class MidnightAlertsOptionsFlow(config_entries.OptionsFlow):
    """Handle setting or updating the API key after installation."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._verified_key: str | None = None

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Collect the API key and verify it against the Midnight Alerts server."""
        errors = {}

        if user_input is not None:
            client = MidnightAlertsApiClient(
                user_input[CONF_API_KEY], async_get_clientsession(self.hass)
            )
            try:
                await client.async_validate()
            except MidnightAlertsAuthError:
                errors["base"] = "invalid_auth"
            except MidnightAlertsApiError:
                errors["base"] = "cannot_connect"
            else:
                self._verified_key = user_input[CONF_API_KEY]
                return await self.async_step_verified()

        current_key = self.config_entry.options.get(CONF_API_KEY, "")
        schema = vol.Schema({
            vol.Required(CONF_API_KEY, default=current_key): str,
        })
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"account_url": ACCOUNT_URL},
        )

    async def async_step_verified(self, user_input=None) -> FlowResult:
        """Confirm the key was verified successfully before saving it."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={CONF_API_KEY: self._verified_key}
            )

        return self.async_show_form(step_id="verified", data_schema=vol.Schema({}))
