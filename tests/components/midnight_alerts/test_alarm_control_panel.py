"""Integration tests for the Midnight Alarm alarm_control_panel platform."""
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.midnight_alerts import pin, sensors
from custom_components.midnight_alerts.alarm_control_panel import (
    MidnightAlarmArea,
    _AreaFsmExtraData,
)
from custom_components.midnight_alerts.alarm_state import AreaFsm
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


async def test_arm_on_close_ignores_non_flagged_and_waits_for_all_flagged(hass, freezer):
    registry = er.async_get(hass)
    flagged_a = registry.async_get_or_create("binary_sensor", "test", "front_door").entity_id
    flagged_b = registry.async_get_or_create("binary_sensor", "test", "back_door").entity_id
    unflagged = registry.async_get_or_create("binary_sensor", "test", "motion").entity_id
    for entity_id in (flagged_a, flagged_b, unflagged):
        hass.states.async_set(entity_id, "on")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, flagged_a, area_subentry_id="area1", arm_on_close=True
    )
    sensors.async_set_sensor_options(
        hass, flagged_b, area_subentry_id="area1", arm_on_close=True
    )
    sensors.async_set_sensor_options(hass, unflagged, area_subentry_id="area1")

    await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=10)])
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )

    freezer.move_to(dt_util.utcnow() + timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # a non-flagged sensor closing must have zero effect on the hold
    hass.states.async_set(unflagged, "off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # only one of the two flagged sensors closing must still hold open
    hass.states.async_set(flagged_a, "off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # the last flagged sensor closing finally releases the hold
    hass.states.async_set(flagged_b, "off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY


def _area_subentry_all_modes(subentry_id: str = "area1") -> dict:
    modes = {
        mode: {"enabled": True, "exit_time": 0, "entry_time": 30, "trigger_time": 120}
        for mode in (
            "armed_away",
            "armed_home",
            "armed_night",
            "armed_vacation",
            "armed_custom_bypass",
        )
    }
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_AREA,
        "title": "Home",
        "unique_id": None,
        "data": {CONF_NAME: "Home", CONF_MODES: modes},
    }


async def test_arm_night_vacation_and_custom_bypass(hass):
    await _setup_entry(hass, subentries_data=[_area_subentry_all_modes("area1")])
    entity_id = _find_entity_id(hass, "area1")

    for service, expected in (
        ("alarm_arm_night", AlarmControlPanelState.ARMED_NIGHT),
        ("alarm_arm_vacation", AlarmControlPanelState.ARMED_VACATION),
        ("alarm_arm_custom_bypass", AlarmControlPanelState.ARMED_CUSTOM_BYPASS),
    ):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            {"entity_id": entity_id},
            blocking=True,
        )
        await hass.services.async_call(
            "alarm_control_panel", service, {"entity_id": entity_id}, blocking=True
        )
        assert hass.states.get(entity_id).state == expected


async def test_manual_trigger_starts_triggered_immediately(hass):
    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_trigger",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.TRIGGERED


async def test_sensor_removed_event_is_ignored(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(hass, sensor_entity_id, area_subentry_id="area1")

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")

    hass.states.async_remove(sensor_entity_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED


async def test_delay_on_reopen_while_pending_cancels_and_restarts_timer(hass, freezer):
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

    start = dt_util.utcnow()
    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()

    # Re-opens mid-debounce (a distinguishable event, since HA dedupes
    # identical state+attributes) - the first timer (due at start+5s) must
    # be cancelled, not left running alongside the new one.
    freezer.move_to(start + timedelta(seconds=3))
    hass.states.async_set(sensor_entity_id, "on", {"seq": 2})
    await hass.async_block_till_done()

    # Past the *original* deadline, but the restarted one (start+3+5=8s)
    # hasn't fired yet - if the first timer weren't actually cancelled, it
    # would have fired here and this would already be PENDING.
    freezer.move_to(start + timedelta(seconds=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    freezer.move_to(start + timedelta(seconds=9))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING


async def test_delay_on_elapsed_while_sensor_unavailable_is_filtered(hass, freezer):
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

    # Goes unavailable (not "closed") before the debounce elapses - unlike a
    # clean close, this does NOT cancel the pending timer via
    # _async_handle_sensor_closed (that only reacts to a "closed" status),
    # so the timer must still fire and filter it out itself.
    hass.states.async_set(sensor_entity_id, "unavailable")
    await hass.async_block_till_done()

    freezer.move_to(dt_util.utcnow() + timedelta(seconds=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME


async def test_use_exit_delay_false_sensor_aborts_arming_immediately(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", use_exit_delay=False
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=60)])
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED


async def test_non_always_on_sensor_ignored_while_disarmed(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "motion"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(hass, sensor_entity_id, area_subentry_id="area1")

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.DISARMED


async def test_sensor_restricted_to_other_mode_is_ignored(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", modes=["armed_away"]
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
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
    # sensor is only active in armed_away, not armed_home - must be ignored
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME


async def test_second_faster_sensor_shortens_pending_countdown(hass, freezer):
    registry = er.async_get(hass)
    door = registry.async_get_or_create("binary_sensor", "test", "front_door").entity_id
    window = registry.async_get_or_create("binary_sensor", "test", "window").entity_id
    for entity_id in (door, window):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(hass, door, area_subentry_id="area1")
    sensors.async_set_sensor_options(
        hass, window, area_subentry_id="area1", entry_delay=5
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1", entry_time=30)])
    entity_id = _find_entity_id(hass, "area1")
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": entity_id},
        blocking=True,
    )

    start = dt_util.utcnow()
    hass.states.async_set(door, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING

    freezer.move_to(start + timedelta(seconds=5))
    hass.states.async_set(window, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING

    # The door sensor's original 30s deadline (start+30) hasn't passed, but
    # the window's shorter 5s delay pulled it in to start+5+5=start+10.
    freezer.move_to(start + timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.TRIGGERED


# --- restore-state (restart mid-countdown) -----------------------------------


def test_area_fsm_extra_data_round_trip():
    fsm = AreaFsm(
        settled_state=AlarmControlPanelState.ARMED_AWAY,
        previous_state=AlarmControlPanelState.DISARMED,
        arming_until=dt_util.utcnow(),
        disarm_after_trigger=True,
        held_open=True,
    )
    restored = _AreaFsmExtraData.from_dict(_AreaFsmExtraData(fsm).as_dict())
    assert restored is not None
    assert restored.fsm == fsm


def test_area_fsm_extra_data_from_dict_rejects_invalid_state():
    assert _AreaFsmExtraData.from_dict({"settled_state": "not_a_real_state"}) is None


async def test_will_remove_from_hass_cancels_pending_delay_on_timers():
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    subentry = ConfigSubentry(
        data=_area_subentry("area1")["data"],
        subentry_type=SUBENTRY_TYPE_AREA,
        title="Home",
        unique_id=None,
        subentry_id="area1",
    )
    area = MidnightAlarmArea(entry, subentry)
    unsub = Mock()
    area._delay_on_unsub["binary_sensor.front_door"] = unsub

    await area.async_will_remove_from_hass()

    unsub.assert_called_once()
    assert area._delay_on_unsub == {}


async def test_restart_mid_arming_restores_and_resumes_countdown(hass, freezer):
    entry = await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=60)])
    entity_id = _find_entity_id(hass, "area1")

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    arming_until = dt_util.utcnow() + timedelta(seconds=30)
    extra_data = _AreaFsmExtraData(
        AreaFsm(
            settled_state=AlarmControlPanelState.ARMED_AWAY,
            previous_state=AlarmControlPanelState.DISARMED,
            arming_until=arming_until,
        )
    ).as_dict()
    mock_restore_cache_with_extra_data(
        hass, [(State(entity_id, AlarmControlPanelState.ARMING), extra_data)]
    )

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    freezer.move_to(arming_until + timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY


async def test_restart_mid_pending_restores_and_resumes_countdown(hass, freezer):
    entry = await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    now = dt_util.utcnow()
    pending_until = now + timedelta(seconds=10)
    trigger_until = pending_until + timedelta(seconds=60)
    extra_data = _AreaFsmExtraData(
        AreaFsm(
            settled_state=AlarmControlPanelState.TRIGGERED,
            previous_state=AlarmControlPanelState.ARMED_HOME,
            pending_until=pending_until,
            trigger_until=trigger_until,
        )
    ).as_dict()
    mock_restore_cache_with_extra_data(
        hass, [(State(entity_id, AlarmControlPanelState.PENDING), extra_data)]
    )

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING

    freezer.move_to(pending_until + timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.TRIGGERED
