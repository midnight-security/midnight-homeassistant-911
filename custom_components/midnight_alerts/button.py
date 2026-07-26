"""Button platform for Midnight Alerts."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import MidnightAlertsApiClient, MidnightAlertsApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button."""
    client = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MidnightAlertButton(entry, client)])


class MidnightAlertButton(ButtonEntity):
    """Representation of a Midnight Alert button."""

    _attr_has_entity_name = True
    _attr_name = "Trigger Alert"
    _attr_icon = "mdi:phone-alert"

    def __init__(self, entry: ConfigEntry, client: MidnightAlertsApiClient | None) -> None:
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_trigger_alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Midnight 911",
            manufacturer="Midnight Security",
            model="Alert System",
            entry_type=DeviceEntryType.SERVICE,
            suggested_area="Security",
        )

    @property
    def available(self) -> bool:
        """Return whether an API key has been configured."""
        return self._client is not None

    async def async_press(self) -> None:
        """Trigger the alert when button is pressed."""
        if self._client is None:
            raise HomeAssistantError(
                "Add a Midnight 911 API key first: Settings > Devices & Services "
                "> Midnight 911 > Configure"
            )

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
