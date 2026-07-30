"""Integration tests for the Midnight Alarm alarm_control_panel platform."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.midnight_alerts import pin, sensors
from custom_components.midnight_alerts.const import (
    CONF_API_KEY,
    CONF_ENTITIES,
    CONF_EVENT_COUNT,
    CONF_MODES,
    CONF_NAME,
    CONF_TIMEOUT,
    DOMAIN,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_SENSOR_GROUP,
    SUBENTRY_TYPE_USER,
)

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


def _area_subentry(
    subentry_id: str = "area1",
    *,
    name: str = "Home",
    exit_time: int = 60,
    entry_time: int = 30,
    trigger_time: int = 120,
) -> dict:
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_AREA,
        "title": name,
        "unique_id": None,
        "data": {
            CONF_NAME: name,
            CONF_MODES: {
                "armed_away": {
                    "enabled": True,
                    "exit_time": exit_time,
                    "entry_time": entry_time,
                    "trigger_time": trigger_time,
                },
                "armed_home": {
                    "enabled": True,
                    "exit_time": 0,
                    "entry_time": entry_time,
                    "trigger_time": trigger_time,
                },
                "armed_night": {"enabled": False},
                "armed_vacation": {"enabled": False},
                "armed_custom_bypass": {"enabled": False},
            },
        },
    }


def _sensor_group_subentry(
    subentry_id: str, *, entities: list[str], timeout: int = 10, event_count: int = 2
) -> dict:
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_SENSOR_GROUP,
        "title": "Group",
        "unique_id": None,
        "data": {
            CONF_NAME: "Group",
            CONF_ENTITIES: entities,
            CONF_TIMEOUT: timeout,
            CONF_EVENT_COUNT: event_count,
        },
    }


async def _setup_entry(hass, *, subentries_data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "test-key"},
        subentries_data=subentries_data,
    )
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _find_entity_id(hass, unique_id: str) -> str:
    entry = er.async_get(hass).async_get_entity_id(
        "alarm_control_panel", DOMAIN, unique_id
    )
    assert entry is not None
    return entry


async def test_area_entity_created_per_area_subentry(hass):
    await _setup_entry(hass, subentries_data=[_area_subentry("area1", name="Home")])
    entity_id = _find_entity_id(hass, "area1")
    state = hass.states.get(entity_id)
    assert state.state == AlarmControlPanelState.DISARMED


async def test_arm_away_goes_through_arming_then_armed(hass, freezer):
    await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=60)])
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # async_fire_time_changed only fires the *event* with a given timestamp -
    # the FSM's own display_state() calls dt_util.utcnow() fresh, so the
    # actual clock has to move too, or it'll still see the old time.
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY


async def test_arm_home_with_zero_exit_time_arms_instantly(hass):
    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME


async def test_disarm_is_immediate(hass):
    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_disarm",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED


async def test_wrong_code_is_rejected_and_state_unchanged(hass):
    entry = await _setup_entry(
        hass,
        subentries_data=[
            _area_subentry("area1"),
        ],
    )
    hashed = await pin.async_hash_code(hass, "1234")
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                CONF_NAME: "Alice",
                "code": hashed,
                "can_arm": True,
                "can_disarm": True,
                "is_override_code": False,
                "area_limit": [],
                "enabled": True,
            },
            subentry_type=SUBENTRY_TYPE_USER,
            title="Alice",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()
    entity_id = _find_entity_id(hass, "area1")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_home",
            {"entity_id": entity_id, "code": "9999"},
            blocking=True,
        )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED


async def test_sensor_trip_while_armed_triggers_after_entry_delay(hass, freezer):
    # The area entity's sensor subscription is built once, in
    # async_added_to_hass - the sensor and its options must exist *before*
    # the config entry (and therefore the entity) is set up, or it won't be
    # in the subscription list. (Attaching a sensor after the fact, via the
    # "manage sensors" flow step, is what forces the reload that's needed
    # for a live change - see config_flow.py.)
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", always_on=False
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1", entry_time=20)])
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING

    freezer.move_to(dt_util.utcnow() + timedelta(seconds=21))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.TRIGGERED


async def test_always_on_sensor_triggers_even_when_disarmed(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "smoke"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", always_on=True
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.TRIGGERED


# --- Phase 2: sensor groups, delay_on, arm_on_close -------------------------


async def test_sensor_group_requires_confirmation_from_multiple_members(hass):
    registry = er.async_get(hass)
    motion1 = registry.async_get_or_create("binary_sensor", "test", "motion1").entity_id
    motion2 = registry.async_get_or_create("binary_sensor", "test", "motion2").entity_id
    for entity_id in (motion1, motion2):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    for entity_id in (motion1, motion2):
        sensors.async_set_sensor_options(hass, entity_id, area_subentry_id="area1")

    await _setup_entry(
        hass,
        subentries_data=[
            _area_subentry("area1"),
            _sensor_group_subentry(
                "group1", entities=[motion1, motion2], timeout=10, event_count=2
            ),
        ],
    )
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    # a single grouped sensor tripping alone must NOT trigger the alarm
    hass.states.async_set(motion1, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    # a second member tripping within the timeout window confirms it
    hass.states.async_set(motion2, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING


async def test_sensor_group_trips_outside_timeout_dont_confirm(hass, freezer):
    registry = er.async_get(hass)
    motion1 = registry.async_get_or_create("binary_sensor", "test", "motion1").entity_id
    motion2 = registry.async_get_or_create("binary_sensor", "test", "motion2").entity_id
    for entity_id in (motion1, motion2):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    for entity_id in (motion1, motion2):
        sensors.async_set_sensor_options(hass, entity_id, area_subentry_id="area1")

    await _setup_entry(
        hass,
        subentries_data=[
            _area_subentry("area1"),
            _sensor_group_subentry(
                "group1", entities=[motion1, motion2], timeout=5, event_count=2
            ),
        ],
    )
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )

    hass.states.async_set(motion1, "on")
    await hass.async_block_till_done()

    freezer.move_to(dt_util.utcnow() + timedelta(seconds=10))
    hass.states.async_set(motion2, "on")
    await hass.async_block_till_done()
    # motion1's trip is now outside the 5s window - still not confirmed
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME


async def test_delay_on_filters_a_momentary_blip(hass, freezer):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", delay_on=5
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    # closes again before the 5s debounce elapses - should be filtered out
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()

    freezer.move_to(dt_util.utcnow() + timedelta(seconds=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME


async def test_delay_on_confirms_a_sustained_open(hass, freezer):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", delay_on=5
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    freezer.move_to(dt_util.utcnow() + timedelta(seconds=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING


async def test_arm_on_close_holds_arming_until_sensor_closes(hass, freezer):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "on")  # already open at arm time
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass,
        sensor_entity_id,
        area_subentry_id="area1",
        arm_on_close=True,
        use_exit_delay=True,
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=10)])
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # exit delay elapses, but the door is still open - must keep holding
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # still holding, arbitrarily later
    freezer.move_to(dt_util.utcnow() + timedelta(minutes=5))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # closing the door finishes arming immediately
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY
