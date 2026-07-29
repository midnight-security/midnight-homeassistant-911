"""Button platform for Midnight Alerts."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MidnightAlertsConfigEntry
from .api import MidnightAlertsApiClient, MidnightAlertsApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MidnightAlertsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([MidnightAlertButton(entry, entry.runtime_data.client)])


class MidnightAlertButton(ButtonEntity):
    """Representation of a Midnight Alert button."""

    _attr_has_entity_name = True
    _attr_name = "Trigger Alert"
    _attr_icon = "mdi:alert"

    def __init__(self, entry: ConfigEntry, client: MidnightAlertsApiClient) -> None:
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_trigger_alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Midnight 911",
            manufacturer="Midnight Security",
            model="Alert System",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Trigger the alert when button is pressed."""
        payload = {
          "address": {
            "city": "New York",
            "country": "US",
            "name": "NY",
            "postal_code": "10023",
            "state": "NY",
            "street_1": "3 Park Ave"
          },
          "lat": 40.7128,
          "lng": -74.006,
          "name": "NYC School"
        }

        try:
            await self._client.async_trigger_alert(payload)
            _LOGGER.info("Alert successfully sent")
        except MidnightAlertsApiError as err:
            _LOGGER.error("Failed to send alert: %s", err)
