"""Config flow for Midnight Alerts."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentry,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import pin, sensors, alarmo_import
from .api import (
    MidnightAlertsApiError,
    MidnightAlertsApiClient,
    MidnightAlertsAuthError,
)
from .const import (
    DOMAIN,
    ARM_MODES,
    CONF_CODE,
    CONF_NAME,
    CONF_MODES,
    CONF_API_KEY,
    CONF_CAN_ARM,
    CONF_ENABLED,
    CONF_TIMEOUT,
    CONF_WEIGHTS,
    CONF_DELAY_ON,
    CONF_ENTITIES,
    CONF_ALWAYS_ON,
    CONF_EXIT_TIME,
    CONF_THRESHOLD,
    DEFAULT_WEIGHT,
    CONF_AREA_LIMIT,
    CONF_CAN_DISARM,
    CONF_ENTRY_TIME,
    CONF_GROUP_MODE,
    CONF_EVENT_COUNT,
    CONF_ARM_ON_CLOSE,
    CONF_TRIGGER_TIME,
    DEFAULT_EXIT_TIME,
    DEFAULT_THRESHOLD,
    MODE_COUNT_WINDOW,
    DEFAULT_ENTRY_TIME,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_USER,
    MODE_WEIGHTED_DECAY,
    DEFAULT_TRIGGER_TIME,
    CONF_DECAY_PER_MINUTE,
    CONF_IS_OVERRIDE_CODE,
    CONF_SENSOR_ENTRY_DELAY,
    DEFAULT_DECAY_PER_MINUTE,
    SUBENTRY_TYPE_SENSOR_GROUP,
    CONF_ENABLE_CRASH_REPORTING,
    SUBENTRY_TYPE_ALARMO_IMPORT,
    DEFAULT_SENSOR_GROUP_TIMEOUT,
    DEFAULT_SENSOR_GROUP_EVENT_COUNT,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_API_KEY, default=""): str,
        vol.Required(CONF_ENABLE_CRASH_REPORTING, default=False): bool,
    }
)

# Reauth exists to fix a rejected key specifically - crash reporting isn't
# part of that. It's asked once at initial setup, and editable afterward in
# exactly one place: reconfigure, alongside the API key (see
# _user_data_schema). No separate Configure/options flow exists for it.
API_KEY_ONLY_SCHEMA = vol.Schema({vol.Optional(CONF_API_KEY, default=""): str})


class MidnightAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Midnight Alerts."""

    VERSION = 1

    @override
    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle the initial step - also reused for reauth/reconfigure.

        Crash reporting is asked here, alongside the API key, at both
        initial setup and reconfigure (see _user_data_schema) - opt-in
        consent belongs in the same place the account itself is set up,
        and reconfigure is the one place to revisit it afterward. Not
        reauth though: that exists to fix a rejected key specifically, and
        there's no separate Configure/options flow to leave it out of.

        The API key itself is optional: the alarm engine (areas, sensors,
        PINs, arm/disarm/trigger) is entirely local and works fully without
        one - only the Trigger Alert button actually calls Midnight's API,
        and it already handles being unconfigured gracefully (button.py).
        Leaving it blank skips validation/location-check entirely and
        finishes immediately; a key can be added anytime afterward via
        Reconfigure (async_step_reconfigure).
        """
        errors = {}

        if user_input is not None:
            # Pulled out of user_input: it belongs in the entry's options
            # (an ordinary, changeable-anytime preference), not its data
            # (the API key, which is what data_updates/data replace). None
            # on reauth/reconfigure, where the field isn't shown at all -
            # _async_finish leaves those entries' existing options alone.
            enable_crash_reporting = user_input.pop(CONF_ENABLE_CRASH_REPORTING, None)
            api_key = user_input[CONF_API_KEY].strip()
            user_input[CONF_API_KEY] = api_key

            if not api_key:
                return await self._async_finish(user_input, enable_crash_reporting)

            client = MidnightAlertsApiClient(
                api_key, async_get_clientsession(self.hass)
            )
            try:
                result = await client.async_validate(
                    latitude=self.hass.config.latitude,
                    longitude=self.hass.config.longitude,
                )
            except MidnightAlertsAuthError:
                errors["base"] = "invalid_auth"
            except MidnightAlertsApiError:
                errors["base"] = "cannot_connect"
            else:
                # location_match is computed server-side (single source of
                # truth for the distance math): True/False is a real
                # comparison, None means no address is on file yet.
                location_match = result.get("location_match")
                if location_match is None:
                    errors["base"] = "no_account_location"
                elif location_match is False:
                    errors["base"] = "location_mismatch"
                else:
                    return await self._async_finish(user_input, enable_crash_reporting)

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_data_schema(),
            errors=errors,
        )

    async def _async_finish(
        self, user_input: dict[str, Any], enable_crash_reporting: bool | None
    ) -> ConfigFlowResult:
        """Create the entry, or update+reload an existing one on reauth/reconfigure.

        enable_crash_reporting is None only on reauth - that's the one
        source whose schema doesn't include the field, so the entry's
        existing options carry over unchanged rather than being overwritten
        with a value never asked for in that flow.
        """
        if self.source == config_entries.SOURCE_REAUTH:
            entry = self._get_reauth_entry()
        elif self.source == config_entries.SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
        else:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Midnight 911 Integration",
                data=user_input,
                options={CONF_ENABLE_CRASH_REPORTING: enable_crash_reporting},
            )

        options = (
            entry.options
            if enable_crash_reporting is None
            else {**entry.options, CONF_ENABLE_CRASH_REPORTING: enable_crash_reporting}
        )
        return self.async_update_reload_and_abort(
            entry, data_updates=user_input, options=options
        )

    def _user_data_schema(self) -> vol.Schema:
        """The full schema at initial setup and on reconfigure; API key alone on reauth.

        Reauth deliberately leaves the API key itself blank rather than
        suggesting the old one - it's here because that key stopped
        working, so re-showing it would just invite resubmitting the same
        broken value, and crash reporting isn't part of fixing a rejected
        key. Reconfigure is the one place to revisit *both* fields after
        setup - it suggests the current API key (editing, or filling in a
        previously-blank one, is the whole point of that flow) and the
        current crash-reporting choice.
        """
        if self.source == config_entries.SOURCE_REAUTH:
            return API_KEY_ONLY_SCHEMA
        if self.source != config_entries.SOURCE_RECONFIGURE:
            return DATA_SCHEMA
        entry = self._get_reconfigure_entry()
        return self.add_suggested_values_to_schema(
            DATA_SCHEMA,
            {
                CONF_API_KEY: entry.data.get(CONF_API_KEY, ""),
                CONF_ENABLE_CRASH_REPORTING: entry.options.get(
                    CONF_ENABLE_CRASH_REPORTING, False
                ),
            },
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        """Handle reauth when the stored API key stops validating.

        Home Assistant core triggers this automatically whenever
        async_setup_entry raises ConfigEntryAuthFailed - reuses
        async_step_user's form/validation as-is (single api_key field,
        same location check), branching only at the end on self.source.
        """
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Handle a user-initiated edit of the API key and/or crash reporting.

        The one place to change either after initial setup - there's no
        separate Configure/options flow duplicating this.

        Only ever called once, same as async_step_reauth above - the form
        it shows has step_id "user", so the frontend's actual submission
        routes straight to async_step_user, not back through here. Reuses
        that same form/validation as-is; the only real difference between
        the three sources is which branch of _async_finish they end up in.
        """
        return await self.async_step_user()

    @classmethod
    @callback
    @override
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
        vol.Required("enabled_modes", default=_DEFAULT_ENABLED_MODES): _MODE_SELECTOR,
    }
)


def _modes_data(
    enabled_modes: list[str], mode_timers: dict[str, dict[str, int]]
) -> dict[str, Any]:
    """Build the per-mode data dict; each enabled mode keeps its own timer set.

    `mode_timers` need only cover the enabled modes - a mode missing from it
    (e.g. one that was never configured, or one that's disabled) falls back
    to the stock defaults.
    """
    return {
        mode: {
            CONF_ENABLED: mode in enabled_modes,
            CONF_EXIT_TIME: mode_timers.get(mode, {}).get(
                CONF_EXIT_TIME, DEFAULT_EXIT_TIME
            ),
            CONF_ENTRY_TIME: mode_timers.get(mode, {}).get(
                CONF_ENTRY_TIME, DEFAULT_ENTRY_TIME
            ),
            CONF_TRIGGER_TIME: mode_timers.get(mode, {}).get(
                CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME
            ),
        }
        for mode in _MODE_VALUES
    }


def _mode_timer_field_key(mode: str, field: str) -> str:
    return f"{mode}_{field}"


def _mode_timers_schema(enabled_modes: list[str]) -> vol.Schema:
    """One exit/entry/trigger triplet per enabled mode, each its own field."""
    fields: dict[Any, Any] = {}
    for mode in enabled_modes:
        fields[
            vol.Required(
                _mode_timer_field_key(mode, CONF_EXIT_TIME), default=DEFAULT_EXIT_TIME
            )
        ] = vol.Coerce(int)
        fields[
            vol.Required(
                _mode_timer_field_key(mode, CONF_ENTRY_TIME),
                default=DEFAULT_ENTRY_TIME,
            )
        ] = vol.Coerce(int)
        fields[
            vol.Required(
                _mode_timer_field_key(mode, CONF_TRIGGER_TIME),
                default=DEFAULT_TRIGGER_TIME,
            )
        ] = vol.Coerce(int)
    return vol.Schema(fields)


def _mode_timers_from_input(
    enabled_modes: list[str], user_input: dict[str, Any]
) -> dict[str, dict[str, int]]:
    return {
        mode: {
            CONF_EXIT_TIME: user_input[_mode_timer_field_key(mode, CONF_EXIT_TIME)],
            CONF_ENTRY_TIME: user_input[_mode_timer_field_key(mode, CONF_ENTRY_TIME)],
            CONF_TRIGGER_TIME: user_input[
                _mode_timer_field_key(mode, CONF_TRIGGER_TIME)
            ],
        }
        for mode in enabled_modes
    }


def _suggested_mode_timers(
    enabled_modes: list[str], modes_data: dict[str, Any]
) -> dict[str, int]:
    """Existing per-mode timers (or defaults, for a newly-enabled mode)."""
    suggested: dict[str, int] = {}
    for mode in enabled_modes:
        cfg = modes_data.get(mode, {})
        suggested[_mode_timer_field_key(mode, CONF_EXIT_TIME)] = cfg.get(
            CONF_EXIT_TIME, DEFAULT_EXIT_TIME
        )
        suggested[_mode_timer_field_key(mode, CONF_ENTRY_TIME)] = cfg.get(
            CONF_ENTRY_TIME, DEFAULT_ENTRY_TIME
        )
        suggested[_mode_timer_field_key(mode, CONF_TRIGGER_TIME)] = cfg.get(
            CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME
        )
    return suggested


class AreaSubentryFlowHandler(ConfigSubentryFlow):
    """Create/reconfigure a Midnight Alarm area.

    Name/enabled-modes and per-mode timers are two steps, not one - the
    timers step's schema is built *from* the modes just chosen, the same
    "pick members, then configure per-member fields" shape
    SensorGroupSubentryFlowHandler's weights step already uses below. A
    single combined form can't do this: the set of timer fields to show
    depends on an answer from the same submission.
    """

    _pending_data: dict[str, Any]
    _pending_subentry: ConfigSubentry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: name and enabled modes."""
        if user_input is not None:
            self._pending_data = user_input
            return await self.async_step_timers()
        return self.async_show_form(step_id="user", data_schema=AREA_CREATE_SCHEMA)

    async def async_step_timers(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: exit/entry/trigger time, individually per enabled mode."""
        enabled_modes = self._pending_data["enabled_modes"]
        if user_input is not None:
            mode_timers = _mode_timers_from_input(enabled_modes, user_input)
            return self.async_create_entry(
                title=self._pending_data[CONF_NAME],
                data={
                    CONF_NAME: self._pending_data[CONF_NAME],
                    CONF_MODES: _modes_data(enabled_modes, mode_timers),
                },
            )
        return self.async_show_form(
            step_id="timers", data_schema=_mode_timers_schema(enabled_modes)
        )

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
        """Reconfigure step 1: name and enabled modes."""
        subentry = self._get_reconfigure_subentry()
        modes_data = subentry.data.get(CONF_MODES, {})
        currently_enabled = [
            mode for mode, cfg in modes_data.items() if cfg.get(CONF_ENABLED)
        ]

        if user_input is not None:
            self._pending_data = user_input
            self._pending_subentry = subentry
            return await self.async_step_reconfigure_timers()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(
                    "enabled_modes", default=currently_enabled
                ): _MODE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="edit_timers",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_NAME: subentry.data.get(CONF_NAME),
                },
            ),
        )

    async def async_step_reconfigure_timers(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure step 2: exit/entry/trigger time, per enabled mode."""
        # Only ever reachable via async_step_edit_timers, which always sets
        # this immediately before returning here.
        assert self._pending_subentry is not None
        subentry = self._pending_subentry
        enabled_modes = self._pending_data["enabled_modes"]
        modes_data = subentry.data.get(CONF_MODES, {})

        if user_input is not None:
            mode_timers = _mode_timers_from_input(enabled_modes, user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=self._pending_data[CONF_NAME],
                data_updates={
                    CONF_NAME: self._pending_data[CONF_NAME],
                    CONF_MODES: _modes_data(enabled_modes, mode_timers),
                },
            )

        return self.async_show_form(
            step_id="reconfigure_timers",
            data_schema=self.add_suggested_values_to_schema(
                _mode_timers_schema(enabled_modes),
                _suggested_mode_timers(enabled_modes, modes_data),
            ),
        )

    async def async_step_manage_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Attach/detach binary_sensor entities to/from this area.

        `arm_on_close`/`delay_on`/`always_on`/`entry_delay`/`modes` here
        apply only to newly-attached sensors in this same submission -
        already-attached sensors keep whatever they had. Per-sensor editing
        of an already-attached sensor's flags isn't exposed yet; re-detach
        and re-attach it to change them.
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
                    # entry_delay/modes only get set if the user actually
                    # picked something - an empty modes list would mean
                    # "restricted to zero modes" (blocks every mode), not
                    # "unrestricted", so it must stay absent rather than [].
                    extra_options: dict[str, Any] = {}
                    if user_input.get(CONF_SENSOR_ENTRY_DELAY) is not None:
                        extra_options[CONF_SENSOR_ENTRY_DELAY] = user_input[
                            CONF_SENSOR_ENTRY_DELAY
                        ]
                    if user_input.get(CONF_MODES):
                        extra_options[CONF_MODES] = user_input[CONF_MODES]
                    sensors.async_set_sensor_options(
                        hass,
                        entity_id,
                        area_subentry_id=subentry.subentry_id,
                        always_on=user_input.get(CONF_ALWAYS_ON, False),
                        allow_open=False,
                        use_exit_delay=True,
                        arm_on_close=user_input.get(CONF_ARM_ON_CLOSE, False),
                        delay_on=user_input.get(CONF_DELAY_ON, 0),
                        **extra_options,
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
                    vol.Required("sensors", default=current): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="binary_sensor", multiple=True
                        )
                    ),
                    vol.Optional(CONF_ARM_ON_CLOSE, default=False): bool,
                    vol.Optional(CONF_DELAY_ON, default=0): vol.Coerce(int),
                    vol.Optional(CONF_ALWAYS_ON, default=False): bool,
                    vol.Optional(CONF_SENSOR_ENTRY_DELAY): vol.Coerce(int),
                    vol.Optional(CONF_MODES, default=[]): _MODE_SELECTOR,
                }
            ),
        )


def _area_limit_selector(entry: ConfigEntry) -> selector.SelectSelector:
    """Multi-select of the entry's current areas, by subentry_id."""
    options: list[selector.SelectOptionDict] = [
        {"value": subentry.subentry_id, "label": subentry.title}
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_AREA
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, multiple=True)
    )


def _user_schema(entry: ConfigEntry, *, code_required: bool) -> vol.Schema:
    code_field = (
        vol.Required(CONF_CODE)
        if code_required
        else vol.Optional(CONF_CODE, default="")
    )
    return vol.Schema(
        {
            vol.Required(CONF_NAME): str,
            code_field: str,
            vol.Required(CONF_CAN_ARM, default=True): bool,
            vol.Required(CONF_CAN_DISARM, default=True): bool,
            vol.Optional(CONF_IS_OVERRIDE_CODE, default=False): bool,
            vol.Optional(CONF_ENABLED, default=True): bool,
            vol.Optional(CONF_AREA_LIMIT, default=[]): _area_limit_selector(entry),
        }
    )


class UserSubentryFlowHandler(ConfigSubentryFlow):
    """Create/reconfigure a Midnight Alarm user (PIN)."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new user."""
        if user_input is not None:
            hashed = await pin.async_hash_code(self.hass, user_input[CONF_CODE])
            data = {**user_input, CONF_CODE: hashed}
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._get_entry(), code_required=True),
        )

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
                _user_schema(self._get_entry(), code_required=False),
                {k: v for k, v in subentry.data.items() if k != CONF_CODE},
            ),
        )


_GROUP_MODE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=[MODE_COUNT_WINDOW, MODE_WEIGHTED_DECAY])
)

SENSOR_GROUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_ENTITIES): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
        ),
        vol.Required(CONF_TIMEOUT, default=DEFAULT_SENSOR_GROUP_TIMEOUT): vol.Coerce(
            int
        ),
        vol.Required(
            CONF_EVENT_COUNT, default=DEFAULT_SENSOR_GROUP_EVENT_COUNT
        ): vol.Coerce(int),
        vol.Optional(CONF_GROUP_MODE, default=MODE_COUNT_WINDOW): _GROUP_MODE_SELECTOR,
    }
)


def _weights_schema(entities: list[str]) -> vol.Schema:
    """Build a decay/threshold/per-member-weight form from the chosen members."""
    fields: dict[Any, Any] = {
        vol.Optional(
            CONF_DECAY_PER_MINUTE, default=DEFAULT_DECAY_PER_MINUTE
        ): vol.Coerce(float),
        vol.Optional(CONF_THRESHOLD, default=DEFAULT_THRESHOLD): vol.Coerce(float),
    }
    for entity_id in entities:
        fields[vol.Optional(entity_id, default=DEFAULT_WEIGHT)] = vol.Coerce(float)
    return vol.Schema(fields)


def _weighted_group_data(
    pending_data: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    entities = pending_data[CONF_ENTITIES]
    return {
        **pending_data,
        CONF_DECAY_PER_MINUTE: user_input[CONF_DECAY_PER_MINUTE],
        CONF_THRESHOLD: user_input[CONF_THRESHOLD],
        CONF_WEIGHTS: {entity_id: user_input[entity_id] for entity_id in entities},
    }


class SensorGroupSubentryFlowHandler(ConfigSubentryFlow):
    """Create/reconfigure an N-of-M cross-zone sensor group.

    Membership here is a *filter* layered on top of ordinary sensors, not a
    fourth thing to attach - every member must also be individually attached
    to the relevant area via the area's "manage sensors" step, or the area
    entity never subscribes to its state changes in the first place and the
    group can never see it trip.

    Two confirmation modes: the default `count_window` needs no more than
    this one form. Opting into `weighted_decay` adds a second "weights" step
    (built from the members just chosen) to set a per-sensor weight, a decay
    rate, and a confirmation threshold.
    """

    _pending_data: dict[str, Any]
    _pending_subentry: ConfigSubentry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new sensor group."""
        if user_input is not None:
            if user_input.get(CONF_GROUP_MODE) == MODE_WEIGHTED_DECAY:
                self._pending_data = user_input
                return await self.async_step_weights()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=SENSOR_GROUP_SCHEMA)

    async def async_step_weights(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Second step of a weighted_decay group: per-entity weight and decay."""
        entities = self._pending_data[CONF_ENTITIES]
        if user_input is not None:
            data = _weighted_group_data(self._pending_data, user_input)
            return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(
            step_id="weights", data_schema=_weights_schema(entities)
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an existing sensor group."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            if user_input.get(CONF_GROUP_MODE) == MODE_WEIGHTED_DECAY:
                self._pending_data = user_input
                self._pending_subentry = subentry
                return await self.async_step_reconfigure_weights()
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

    async def async_step_reconfigure_weights(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Second reconfigure step for a weighted_decay group."""
        # Only ever reachable via async_step_reconfigure, which always sets
        # this immediately before returning here.
        assert self._pending_subentry is not None
        subentry = self._pending_subentry
        entities = self._pending_data[CONF_ENTITIES]
        if user_input is not None:
            data = _weighted_group_data(self._pending_data, user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=data[CONF_NAME],
                data_updates=data,
            )
        suggested = {
            **subentry.data.get(CONF_WEIGHTS, {}),
            CONF_DECAY_PER_MINUTE: subentry.data.get(
                CONF_DECAY_PER_MINUTE, DEFAULT_DECAY_PER_MINUTE
            ),
            CONF_THRESHOLD: subentry.data.get(CONF_THRESHOLD, DEFAULT_THRESHOLD),
        }
        return self.async_show_form(
            step_id="reconfigure_weights",
            data_schema=self.add_suggested_values_to_schema(
                _weights_schema(entities), suggested
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
