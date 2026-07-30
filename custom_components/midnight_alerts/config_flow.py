"""Config flow for Midnight Alerts."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import alarmo_import, pin, sensors
from .api import MidnightAlertsApiClient, MidnightAlertsApiError, MidnightAlertsAuthError
from .const import (
    ARM_MODES,
    CONF_AREA_LIMIT,
    CONF_API_KEY,
    CONF_ARM_ON_CLOSE,
    CONF_CAN_ARM,
    CONF_CAN_DISARM,
    CONF_CODE,
    CONF_DELAY_ON,
    CONF_ENABLE_CRASH_REPORTING,
    CONF_ENABLED,
    CONF_ENTITIES,
    CONF_ENTRY_TIME,
    CONF_EVENT_COUNT,
    CONF_EXIT_TIME,
    CONF_IS_OVERRIDE_CODE,
    CONF_MODES,
    CONF_NAME,
    CONF_TIMEOUT,
    CONF_TRIGGER_TIME,
    DEFAULT_ENTRY_TIME,
    DEFAULT_EXIT_TIME,
    DEFAULT_SENSOR_GROUP_EVENT_COUNT,
    DEFAULT_SENSOR_GROUP_TIMEOUT,
    DEFAULT_TRIGGER_TIME,
    DOMAIN,
    SUBENTRY_TYPE_ALARMO_IMPORT,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_SENSOR_GROUP,
    SUBENTRY_TYPE_USER,
)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_KEY): str,
})


class MidnightAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Midnight Alerts."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
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
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Midnight 911", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "MidnightAlertsOptionsFlow":
        """Create the options flow."""
        return MidnightAlertsOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the Midnight Alarm subentry types: areas, users, sensor groups."""
        return {
            SUBENTRY_TYPE_AREA: AreaSubentryFlowHandler,
            SUBENTRY_TYPE_USER: UserSubentryFlowHandler,
            SUBENTRY_TYPE_SENSOR_GROUP: SensorGroupSubentryFlowHandler,
            SUBENTRY_TYPE_ALARMO_IMPORT: AlarmoImportSubentryFlowHandler,
        }


class MidnightAlertsOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle options for Midnight Alerts."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_CRASH_REPORTING,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_CRASH_REPORTING, False
                        ),
                    ): bool,
                }
            ),
        )


# --- Midnight Alarm subentries: areas and users ---------------------------

_MODE_VALUES = [mode.value for mode in ARM_MODES]
_DEFAULT_ENABLED_MODES = ["armed_away", "armed_home"]

_MODE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=_MODE_VALUES,
        multiple=True,
        translation_key="arm_modes",
    )
)

AREA_CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(
            "enabled_modes", default=_DEFAULT_ENABLED_MODES
        ): _MODE_SELECTOR,
    }
)

_TIMER_FIELDS = {
    vol.Required(CONF_EXIT_TIME, default=DEFAULT_EXIT_TIME): vol.Coerce(int),
    vol.Required(CONF_ENTRY_TIME, default=DEFAULT_ENTRY_TIME): vol.Coerce(int),
    vol.Required(CONF_TRIGGER_TIME, default=DEFAULT_TRIGGER_TIME): vol.Coerce(int),
}


def _modes_data(enabled_modes: list[str], timers: dict[str, int]) -> dict[str, Any]:
    """Build the per-mode data dict; every enabled mode shares one timer set.

    Phase 1 simplification: the data model already supports independently
    configurable timers per mode, but this flow only exposes one shared set
    across every enabled mode - per-mode timer editing is deferred.
    """
    return {
        mode: {
            CONF_ENABLED: mode in enabled_modes,
            CONF_EXIT_TIME: timers[CONF_EXIT_TIME],
            CONF_ENTRY_TIME: timers[CONF_ENTRY_TIME],
            CONF_TRIGGER_TIME: timers[CONF_TRIGGER_TIME],
        }
        for mode in _MODE_VALUES
    }


class AreaSubentryFlowHandler(ConfigSubentryFlow):
    """Create/reconfigure a Midnight Alarm area."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new area with default timers, applied to the selected modes."""
        if user_input is not None:
            timers = {
                CONF_EXIT_TIME: DEFAULT_EXIT_TIME,
                CONF_ENTRY_TIME: DEFAULT_ENTRY_TIME,
                CONF_TRIGGER_TIME: DEFAULT_TRIGGER_TIME,
            }
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_MODES: _modes_data(user_input["enabled_modes"], timers),
                },
            )
        return self.async_show_form(step_id="user", data_schema=AREA_CREATE_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Menu: edit name/timers, or manage attached sensors."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["edit_timers", "manage_sensors"],
        )

    async def async_step_edit_timers(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit name, enabled modes, and the shared timer set."""
        subentry = self._get_reconfigure_subentry()
        modes_data = subentry.data.get(CONF_MODES, {})
        currently_enabled = [
            mode for mode, cfg in modes_data.items() if cfg.get(CONF_ENABLED)
        ]
        any_mode_cfg = next(iter(modes_data.values()), {})

        if user_input is not None:
            timers = {
                CONF_EXIT_TIME: user_input[CONF_EXIT_TIME],
                CONF_ENTRY_TIME: user_input[CONF_ENTRY_TIME],
                CONF_TRIGGER_TIME: user_input[CONF_TRIGGER_TIME],
            }
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data_updates={
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_MODES: _modes_data(user_input["enabled_modes"], timers),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(
                    "enabled_modes", default=currently_enabled
                ): _MODE_SELECTOR,
            }
        ).extend(_TIMER_FIELDS)
        return self.async_show_form(
            step_id="edit_timers",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_NAME: subentry.data.get(CONF_NAME),
                    CONF_EXIT_TIME: any_mode_cfg.get(CONF_EXIT_TIME, DEFAULT_EXIT_TIME),
                    CONF_ENTRY_TIME: any_mode_cfg.get(
                        CONF_ENTRY_TIME, DEFAULT_ENTRY_TIME
                    ),
                    CONF_TRIGGER_TIME: any_mode_cfg.get(
                        CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME
                    ),
                },
            ),
        )

    async def async_step_manage_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Attach/detach binary_sensor entities to/from this area.

        `arm_on_close`/`delay_on` here apply only to newly-attached sensors
        in this same submission - already-attached sensors keep whatever
        they had. Per-sensor editing of an already-attached sensor's flags
        isn't exposed yet; re-detach and re-attach it to change them.
        """
        subentry = self._get_reconfigure_subentry()
        hass = self.hass
        current = sensors.sensors_for_area(hass, subentry.subentry_id)

        if user_input is not None:
            selected = user_input["sensors"]
            for entity_id in current:
                if entity_id not in selected:
                    sensors.async_clear_sensor_options(hass, entity_id)
            for entity_id in selected:
                if entity_id not in current:
                    sensors.async_set_sensor_options(
                        hass,
                        entity_id,
                        area_subentry_id=subentry.subentry_id,
                        always_on=False,
                        allow_open=False,
                        use_exit_delay=True,
                        arm_on_close=user_input.get(CONF_ARM_ON_CLOSE, False),
                        delay_on=user_input.get(CONF_DELAY_ON, 0),
                    )
            # Sensor associations live in entity-registry options on the
            # *sensor* entities, not in this subentry's own data - so
            # async_update_and_abort's normal "did the data change" reload
            # detection never fires for this step. The area entity's sensor
            # subscription is only built once, in async_added_to_hass, so
            # without an explicit reload here a newly attached/detached
            # sensor would silently have no effect until the next restart.
            await self.hass.config_entries.async_reload(self._get_entry().entry_id)
            return self.async_abort(reason="sensors_updated")

        return self.async_show_form(
            step_id="manage_sensors",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "sensors", default=current
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="binary_sensor", multiple=True
                        )
                    ),
                    vol.Optional(CONF_ARM_ON_CLOSE, default=False): bool,
                    vol.Optional(CONF_DELAY_ON, default=0): vol.Coerce(int),
                }
            ),
        )


USER_CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_CODE): str,
        vol.Required(CONF_CAN_ARM, default=True): bool,
        vol.Required(CONF_CAN_DISARM, default=True): bool,
        vol.Optional(CONF_IS_OVERRIDE_CODE, default=False): bool,
        vol.Optional(CONF_ENABLED, default=True): bool,
    }
)

USER_RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Optional(CONF_CODE, default=""): str,
        vol.Required(CONF_CAN_ARM, default=True): bool,
        vol.Required(CONF_CAN_DISARM, default=True): bool,
        vol.Optional(CONF_IS_OVERRIDE_CODE, default=False): bool,
        vol.Optional(CONF_ENABLED, default=True): bool,
    }
)


class UserSubentryFlowHandler(ConfigSubentryFlow):
    """Create/reconfigure a Midnight Alarm user (PIN).

    Phase 1 scope: `area_limit` always defaults to `[]` (unrestricted) - the
    data model and PIN-resolution logic already support restricting a user
    to specific areas, but there's no UI to set it yet.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new user."""
        if user_input is not None:
            hashed = await pin.async_hash_code(self.hass, user_input[CONF_CODE])
            data = {**user_input, CONF_CODE: hashed, CONF_AREA_LIMIT: []}
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        return self.async_show_form(step_id="user", data_schema=USER_CREATE_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an existing user. Leave the code blank to keep it unchanged."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            data_updates = dict(user_input)
            new_code = data_updates.pop(CONF_CODE, "")
            data_updates[CONF_CODE] = (
                await pin.async_hash_code(self.hass, new_code)
                if new_code
                else subentry.data.get(CONF_CODE, "")
            )
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data_updates=data_updates,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_RECONFIGURE_SCHEMA,
                {k: v for k, v in subentry.data.items() if k != CONF_CODE},
            ),
        )


SENSOR_GROUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_ENTITIES): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
        ),
        vol.Required(
            CONF_TIMEOUT, default=DEFAULT_SENSOR_GROUP_TIMEOUT
        ): vol.Coerce(int),
        vol.Required(
            CONF_EVENT_COUNT, default=DEFAULT_SENSOR_GROUP_EVENT_COUNT
        ): vol.Coerce(int),
    }
)


class SensorGroupSubentryFlowHandler(ConfigSubentryFlow):
    """Create/reconfigure an N-of-M cross-zone sensor group.

    Membership here is a *filter* layered on top of ordinary sensors, not a
    fourth thing to attach - every member must also be individually attached
    to the relevant area via the area's "manage sensors" step, or the area
    entity never subscribes to its state changes in the first place and the
    group can never see it trip.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new sensor group."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=user_input
            )
        return self.async_show_form(
            step_id="user", data_schema=SENSOR_GROUP_SCHEMA
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an existing sensor group."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data_updates=user_input,
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SENSOR_GROUP_SCHEMA, subentry.data
            ),
        )


class AlarmoImportSubentryFlowHandler(ConfigSubentryFlow):
    """One-shot "Import from Alarmo" migration.

    Doesn't create a subentry of its own type - it's a UI entry point (via
    the entry's "Add" menu, like any other subentry type) for a bulk action
    that creates area/user/sensor_group subentries directly, then always
    ends in async_abort with a summary.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show a preview of what would be imported, then apply on confirm."""
        raw = await alarmo_import.async_read_alarmo_storage(self.hass)
        if raw is None:
            return self.async_abort(reason="alarmo_not_found")

        plan = alarmo_import.parse_import(raw)
        if plan is None:
            return self.async_abort(reason="alarmo_version_mismatch")

        if user_input is not None:
            summary = await alarmo_import.async_apply_import(
                self.hass, self._get_entry(), plan
            )
            if summary.already_imported:
                return self.async_abort(reason="already_imported")
            return self.async_abort(
                reason="import_complete",
                description_placeholders={
                    "areas": str(summary.areas_imported),
                    "users": str(summary.users_imported),
                    "sensor_groups": str(summary.sensor_groups_imported),
                    "sensors": str(summary.sensors_imported),
                    "sensors_skipped": str(len(summary.sensors_skipped)),
                    "automations_skipped": str(summary.automations_skipped),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "areas": str(len(plan.areas)),
                "users": str(len(plan.users)),
                "sensor_groups": str(len(plan.sensor_groups)),
                "sensors": str(len(plan.sensor_imports)),
                "automations_skipped": str(plan.automation_count),
            },
        )
