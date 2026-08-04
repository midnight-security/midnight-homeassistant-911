"""Integration tests for the Midnight Alarm alarm_control_panel platform."""
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
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
    CONF_DECAY_PER_MINUTE,
    CONF_ENTITIES,
    CONF_EVENT_COUNT,
    CONF_GROUP_MODE,
    CONF_MODES,
    CONF_NAME,
    CONF_THRESHOLD,
    CONF_TIMEOUT,
    CONF_WEIGHTS,
    DOMAIN,
    EVENT_ARM_FAILED,
    MODE_WEIGHTED_DECAY,
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
    subentry_id: str,
    *,
    entities: list[str],
    timeout: int = 10,
    event_count: int = 2,
    mode: str | None = None,
    weights: dict[str, float] | None = None,
    decay_per_minute: float = 1,
    threshold: float = 10,
) -> dict:
    data = {
        CONF_NAME: "Group",
        CONF_ENTITIES: entities,
        CONF_TIMEOUT: timeout,
        CONF_EVENT_COUNT: event_count,
    }
    if mode is not None:
        data[CONF_GROUP_MODE] = mode
        data[CONF_WEIGHTS] = weights or {}
        data[CONF_DECAY_PER_MINUTE] = decay_per_minute
        data[CONF_THRESHOLD] = threshold
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_SENSOR_GROUP,
        "title": "Group",
        "unique_id": None,
        "data": data,
    }


async def _setup_entry(hass, *, subentries_data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "test-key"},
        subentries_data=subentries_data,
    )
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value={})):
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


async def test_open_sensors_attribute_reflects_current_sensor_state(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(hass, sensor_entity_id, area_subentry_id="area1")

    await _setup_entry(hass, subentries_data=[_area_subentry("area1")])
    entity_id = _find_entity_id(hass, "area1")
    assert hass.states.get(entity_id).attributes["open_sensors"] == [sensor_entity_id]

    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["open_sensors"] == []


async def test_bypassed_sensors_attribute_only_set_for_override_armed_session(hass, freezer):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "on")  # already open at arm time
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", arm_on_close=True
    )

    entry = await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=10)])
    entity_id = _find_entity_id(hass, "area1")

    # not yet armed - no bypass to report
    assert "bypassed_sensors" not in hass.states.get(entity_id).attributes

    await _add_user(hass, entry, is_override_code=True)
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id, "code": "1234"},
        blocking=True,
    )
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY
    assert hass.states.get(entity_id).attributes["bypassed_sensors"] == [
        sensor_entity_id
    ]


async def test_next_state_change_exposes_the_exit_deadline_while_arming(hass, freezer):
    await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=60)])
    entity_id = _find_entity_id(hass, "area1")

    arm_time = dt_util.utcnow()
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert hass.states.get(entity_id).attributes["next_state_change"] == (
        arm_time + timedelta(seconds=60)
    ).isoformat()

    # once ARMED, the stale arming_until deadline must not still be reported
    freezer.move_to(arm_time + timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY
    assert "next_state_change" not in hass.states.get(entity_id).attributes


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


async def _add_user(hass, entry, *, is_override_code: bool) -> None:
    hashed = await pin.async_hash_code(hass, "1234")
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                CONF_NAME: "Alice",
                "code": hashed,
                "can_arm": True,
                "can_disarm": True,
                "is_override_code": is_override_code,
                "area_limit": [],
                "enabled": True,
            },
            subentry_type=SUBENTRY_TYPE_USER,
            title="Alice",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()


async def test_override_code_bypasses_arm_on_close_hold(hass, freezer):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "on")  # already open at arm time
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", arm_on_close=True
    )

    entry = await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=10)])
    await _add_user(hass, entry, is_override_code=True)
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id, "code": "1234"},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    # exit delay elapses; the sensor is STILL open, but an override-code arm
    # must finish anyway rather than holding for it to close
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_AWAY


async def test_non_override_code_still_holds_for_arm_on_close(hass, freezer):
    """Regression check: a non-override user's arm is unaffected."""
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", arm_on_close=True
    )

    entry = await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=10)])
    await _add_user(hass, entry, is_override_code=False)
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id, "code": "1234"},
        blocking=True,
    )
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING


async def test_override_code_bypasses_use_exit_delay_false_abort(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", use_exit_delay=False
    )

    entry = await _setup_entry(hass, subentries_data=[_area_subentry("area1", exit_time=60)])
    await _add_user(hass, entry, is_override_code=True)
    entity_id = _find_entity_id(hass, "area1")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id, "code": "1234"},
        blocking=True,
    )
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING

    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()
    # would normally abort back to DISARMED - override keeps it ARMING
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMING


async def test_area_limit_set_via_real_flow_is_enforced_by_the_engine(hass):
    """area_limit, set through the actual "Add user" flow (not a hand-built
    ConfigSubentry), must actually restrict which area the code works in -
    proving the manage-users UI is wired to the real PIN engine, not just
    that the field persists.
    """
    entry = await _setup_entry(
        hass,
        subentries_data=[_area_subentry("area1"), _area_subentry("area2")],
    )
    (area1,) = [
        s
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_TYPE_AREA and s.subentry_id == "area1"
    ]

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_USER),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Alice",
            "code": "1234",
            "can_arm": True,
            "can_disarm": True,
            "is_override_code": False,
            "enabled": True,
            "area_limit": [area1.subentry_id],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    area1_entity_id = _find_entity_id(hass, "area1")
    area2_entity_id = _find_entity_id(hass, "area2")

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_home",
        {"entity_id": area1_entity_id, "code": "1234"},
        blocking=True,
    )
    assert hass.states.get(area1_entity_id).state == AlarmControlPanelState.ARMED_HOME

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_home",
            {"entity_id": area2_entity_id, "code": "1234"},
            blocking=True,
        )
    assert hass.states.get(area2_entity_id).state == AlarmControlPanelState.DISARMED


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


async def test_use_entry_delay_false_sensor_triggers_instantly(hass):
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id
    hass.states.async_set(sensor_entity_id, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id="area1", use_entry_delay=False
    )

    await _setup_entry(hass, subentries_data=[_area_subentry("area1", entry_time=60)])
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
    # no PENDING period at all, despite the area's 60s entry_time
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


async def test_weighted_group_single_high_weight_sensor_confirms_alone(hass):
    registry = er.async_get(hass)
    window = registry.async_get_or_create("binary_sensor", "test", "window").entity_id
    hass.states.async_set(window, "off")
    await hass.async_block_till_done()
    sensors.async_set_sensor_options(hass, window, area_subentry_id="area1")

    await _setup_entry(
        hass,
        subentries_data=[
            _area_subentry("area1"),
            _sensor_group_subentry(
                "group1",
                entities=[window],
                mode=MODE_WEIGHTED_DECAY,
                weights={window: 15},
                threshold=10,
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

    hass.states.async_set(window, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING


async def test_weighted_group_two_low_weight_sensors_combine_to_confirm(hass, freezer):
    # freeze time so decay between the two trips doesn't shave the combined
    # weight (5+5=10, exactly the threshold) below the boundary
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
                "group1",
                entities=[motion1, motion2],
                mode=MODE_WEIGHTED_DECAY,
                weights={motion1: 5, motion2: 5},
                threshold=10,
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
    assert hass.states.get(entity_id).state == AlarmControlPanelState.ARMED_HOME

    hass.states.async_set(motion2, "on")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING


async def test_weighted_group_score_decays_out_before_second_trip(hass, freezer):
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
                "group1",
                entities=[motion1, motion2],
                mode=MODE_WEIGHTED_DECAY,
                weights={motion1: 5, motion2: 5},
                decay_per_minute=1,
                threshold=10,
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

    # 10 minutes later motion1's contribution has fully decayed away
    freezer.move_to(dt_util.utcnow() + timedelta(minutes=10))
    hass.states.async_set(motion2, "on")
    await hass.async_block_till_done()
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


async def test_aborted_arming_fires_arm_failed_event(hass):
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
    events = async_capture_events(hass, EVENT_ARM_FAILED)

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )
    hass.states.async_set(sensor_entity_id, "on")
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "entity_id": entity_id,
        "sensor": sensor_entity_id,
        "mode": "armed_away",
    }


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

    with patch(VALIDATE, new=AsyncMock(return_value={})):
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

    with patch(VALIDATE, new=AsyncMock(return_value={})):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.PENDING

    freezer.move_to(pending_until + timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == AlarmControlPanelState.TRIGGERED
