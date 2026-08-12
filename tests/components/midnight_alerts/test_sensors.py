"""Tests for sensors.py's entity-registry-options helpers."""

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.midnight_alerts import sensors


@pytest.fixture
def registered_sensor(hass):
    """Give binary_sensor.front_door a real entity-registry row."""
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "binary_sensor", "test", "front_door_unique_id"
    )
    return entry.entity_id


async def test_get_sensor_options_none_when_unconfigured(hass, registered_sensor):
    assert sensors.async_get_sensor_options(hass, registered_sensor) is None


async def test_get_sensor_options_none_when_entity_not_registered_at_all(hass):
    assert sensors.async_get_sensor_options(hass, "binary_sensor.nonexistent") is None


async def test_set_and_get_sensor_options(hass, registered_sensor):
    sensors.async_set_sensor_options(
        hass, registered_sensor, area_subentry_id="area1", always_on=True
    )
    options = sensors.async_get_sensor_options(hass, registered_sensor)
    assert options == {"area_subentry_id": "area1", "always_on": True}


async def test_set_sensor_options_merges_fields(hass, registered_sensor):
    sensors.async_set_sensor_options(hass, registered_sensor, area_subentry_id="area1")
    sensors.async_set_sensor_options(hass, registered_sensor, always_on=True)
    options = sensors.async_get_sensor_options(hass, registered_sensor)
    assert options == {"area_subentry_id": "area1", "always_on": True}


async def test_set_sensor_options_missing_entity_raises(hass):
    with pytest.raises(ValueError):
        sensors.async_set_sensor_options(
            hass, "binary_sensor.does_not_exist", area_subentry_id="area1"
        )


async def test_clear_sensor_options(hass, registered_sensor):
    sensors.async_set_sensor_options(hass, registered_sensor, area_subentry_id="area1")
    sensors.async_clear_sensor_options(hass, registered_sensor)
    assert sensors.async_get_sensor_options(hass, registered_sensor) is None


async def test_sensors_for_area(hass):
    registry = er.async_get(hass)
    front = registry.async_get_or_create("binary_sensor", "test", "front").entity_id
    back = registry.async_get_or_create("binary_sensor", "test", "back").entity_id
    other = registry.async_get_or_create("binary_sensor", "test", "other").entity_id

    sensors.async_set_sensor_options(hass, front, area_subentry_id="area1")
    sensors.async_set_sensor_options(hass, back, area_subentry_id="area1")
    sensors.async_set_sensor_options(hass, other, area_subentry_id="area2")

    result = sensors.sensors_for_area(hass, "area1")
    assert sorted(result) == sorted([front, back])


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("on", "open"),
        ("off", "closed"),
        (None, "unavailable"),
        ("unavailable", "unavailable"),
        ("unknown", "unknown"),
    ],
)
def test_parse_sensor_state(state, expected):
    assert sensors.parse_sensor_state(state) == expected
