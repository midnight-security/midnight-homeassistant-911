"""Button platform for Midnight Alerts."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MidnightAlertsConfigEntry
from .api import MidnightAlertsApiError, MidnightAlertsApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MidnightAlertsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([MidnightAlertButton(entry, entry.runtime_data.client)])


class MidnightAlertButton(ButtonEntity):
    """Representation of a Midnight Alert button.

    Deliberately never overrides `available` (stays HA's default True
    always) - this is the integration's only network-calling entity, but
    HA's own entity_service_call dispatch (helpers/service.py) filters out
    unavailable entities *before* invoking them, and this button has no
    polling/coordinator to ever retry and flip availability back. Setting
    _attr_available = False on a failed press would silently lock out
    every future button.press call forever - a permanent lockout of the
    emergency alert button after one transient failure. Always-available
    plus a real logged error on press (see async_press) is the safer
    behavior for this entity specifically.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "trigger_alert"

    def __init__(self, entry: ConfigEntry, client: MidnightAlertsApiClient) -> None:
        """Bind this button entity to a config entry and API client."""
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_trigger_alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            # Matches __init__.py's own device name - deliberately not
            # "Midnight 911 Integration" (see the comment there).
            name="Midnight 911",
            manufacturer="Midnight Security",
            model="Alert System",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Trigger the alert when button is pressed."""
        if not self._client.is_configured:
            _LOGGER.error(
                "Cannot send alert: no Midnight Alerts API key configured yet - "
                "add one from Settings > Devices & services > Midnight 911 "
                "Integration > Reconfigure"
            )
            return

        payload = {
            "lat": self.hass.config.latitude,
            "lng": self.hass.config.longitude,
        }

        try:
            await self._client.async_trigger_alert(payload)
            _LOGGER.info("Alert successfully sent")
        except MidnightAlertsApiError as err:
            _LOGGER.error("Failed to send alert: %s", err)
