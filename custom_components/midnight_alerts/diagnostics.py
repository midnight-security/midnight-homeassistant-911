"""Diagnostics support for Midnight Alerts.

`ConfigSubentry` is a frozen dataclass, not a `Mapping`, so
`homeassistant.components.diagnostics.async_redact_data` won't recurse into
it directly - passed a raw subentry it just returns the object unchanged,
completely unredacted. Each subentry is converted via its own `.as_dict()`
first, which turns `data` into an ordinary nested dict `async_redact_data`
can actually see into, so a user's `code` (bcrypt-hashed, but still a real,
checkable credential - not a one-way digest we'd be comfortable publishing)
gets caught the same as the API key.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MidnightAlertsConfigEntry, sensors
from .const import CONF_API_KEY, CONF_CODE, SUBENTRY_TYPE_AREA

TO_REDACT = {CONF_API_KEY, CONF_CODE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MidnightAlertsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    subentries = [subentry.as_dict() for subentry in entry.subentries.values()]

    sensor_entries = [
        {"entity_id": entity_id, "options": sensors.async_get_sensor_options(hass, entity_id)}
        for entity_id in _all_configured_sensors(entry, hass)
    ]

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "subentries": async_redact_data(subentries, TO_REDACT),
        "sensors": sensor_entries,
    }


def _all_configured_sensors(
    entry: MidnightAlertsConfigEntry, hass: HomeAssistant
) -> list[str]:
    """Every sensor tagged to any area on this entry."""
    return [
        entity_id
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_AREA
        for entity_id in sensors.sensors_for_area(hass, subentry.subentry_id)
    ]
