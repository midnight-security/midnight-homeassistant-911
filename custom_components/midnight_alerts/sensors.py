"""Entity-registry-options helpers for sensors attached to a Midnight Alarm area.

Each sensor is an existing HA entity (e.g. binary_sensor.front_door) - its
alarm-specific config lives in that entity's own registry options under the
DOMAIN key, the same mechanism AlarmControlPanelEntity itself already uses
for `default_code`. Sensors are deliberately not config subentries: a stale
subentry could point at a deleted entity forever, while a registry option
dies with its entity automatically.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONF_AREA_SUBENTRY_ID


def async_get_sensor_options(
    hass: HomeAssistant, entity_id: str
) -> dict[str, Any] | None:
    """Return this entity's Midnight Alarm options, or None if not configured."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    return entry.options.get(DOMAIN)


def async_set_sensor_options(
    hass: HomeAssistant, entity_id: str, **fields: Any
) -> None:
    """Merge `fields` into this entity's Midnight Alarm options."""
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None:
        raise ValueError(f"{entity_id} is not a registered entity")
    options = dict(entry.options.get(DOMAIN, {}))
    options.update(fields)
    registry.async_update_entity_options(entity_id, DOMAIN, options)


def async_clear_sensor_options(hass: HomeAssistant, entity_id: str) -> None:
    """Detach a sensor from Midnight Alarm entirely."""
    er.async_get(hass).async_update_entity_options(entity_id, DOMAIN, None)


def sensors_for_area(hass: HomeAssistant, area_subentry_id: str) -> list[str]:
    """Return entity_ids of every sensor configured for this area."""
    result: list[str] = []
    for entry in er.async_get(hass).entities.values():
        options = entry.options.get(DOMAIN)
        if (
            options is not None
            and options.get(CONF_AREA_SUBENTRY_ID) == area_subentry_id
        ):
            result.append(entry.entity_id)
    return result


def parse_sensor_state(state: str | None) -> str:
    """Normalize a binary_sensor state to open/closed/unavailable/unknown."""
    if state == "on":
        return "open"
    if state == "off":
        return "closed"
    if state in (None, "unavailable"):
        return "unavailable"
    return "unknown"
