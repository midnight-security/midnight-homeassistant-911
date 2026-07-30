"""Constants for Midnight Alerts integration."""
from typing import Final

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)

DOMAIN = "midnight_alerts"
CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"
CONF_ENABLE_CRASH_REPORTING = "enable_crash_reporting"

# --- Midnight Alarm (alarm_control_panel platform) ---

SUBENTRY_TYPE_AREA: Final = "area"
SUBENTRY_TYPE_USER: Final = "user"
SUBENTRY_TYPE_SENSOR_GROUP: Final = "sensor_group"

# "area" subentry data keys
CONF_NAME: Final = "name"
CONF_MODES: Final = "modes"
CONF_ENABLED: Final = "enabled"
CONF_EXIT_TIME: Final = "exit_time"
CONF_ENTRY_TIME: Final = "entry_time"
CONF_TRIGGER_TIME: Final = "trigger_time"

# "user" subentry data keys
CONF_CODE: Final = "code"
CONF_CAN_ARM: Final = "can_arm"
CONF_CAN_DISARM: Final = "can_disarm"
CONF_IS_OVERRIDE_CODE: Final = "is_override_code"
CONF_AREA_LIMIT: Final = "area_limit"

# "sensor_group" subentry data keys
CONF_ENTITIES: Final = "entities"
CONF_TIMEOUT: Final = "timeout"
CONF_EVENT_COUNT: Final = "event_count"

# per-sensor entity-registry option keys (options[DOMAIN][...] on the sensor entity)
CONF_AREA_SUBENTRY_ID: Final = "area_subentry_id"
CONF_SENSOR_TYPE: Final = "sensor_type"
CONF_ALWAYS_ON: Final = "always_on"
CONF_ALLOW_OPEN: Final = "allow_open"
CONF_USE_EXIT_DELAY: Final = "use_exit_delay"
CONF_USE_ENTRY_DELAY: Final = "use_entry_delay"
CONF_SENSOR_ENTRY_DELAY: Final = "entry_delay"
CONF_ARM_ON_CLOSE: Final = "arm_on_close"
CONF_DELAY_ON: Final = "delay_on"

DEFAULT_EXIT_TIME: Final = 60
DEFAULT_ENTRY_TIME: Final = 60
DEFAULT_TRIGGER_TIME: Final = 1800
DEFAULT_SENSOR_GROUP_TIMEOUT: Final = 10
DEFAULT_SENSOR_GROUP_EVENT_COUNT: Final = 2

ARM_MODES: Final = (
    AlarmControlPanelState.ARMED_AWAY,
    AlarmControlPanelState.ARMED_HOME,
    AlarmControlPanelState.ARMED_NIGHT,
    AlarmControlPanelState.ARMED_VACATION,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
)

MODE_TO_FEATURE: Final = {
    AlarmControlPanelState.ARMED_HOME: AlarmControlPanelEntityFeature.ARM_HOME,
    AlarmControlPanelState.ARMED_AWAY: AlarmControlPanelEntityFeature.ARM_AWAY,
    AlarmControlPanelState.ARMED_NIGHT: AlarmControlPanelEntityFeature.ARM_NIGHT,
    AlarmControlPanelState.ARMED_VACATION: AlarmControlPanelEntityFeature.ARM_VACATION,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: (
        AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
    ),
}
