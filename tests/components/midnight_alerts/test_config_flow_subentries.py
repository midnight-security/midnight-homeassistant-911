"""Tests for the area/user config subentry flows."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigSubentry
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import pin, sensors
from custom_components.midnight_alerts.const import (
    CONF_API_KEY,
    CONF_CODE,
    CONF_MODES,
    CONF_NAME,
    DOMAIN,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_USER,
)

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"


async def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_add_area(hass):
    entry = await _entry(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_AREA),
        context={"source": "user"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Home", "enabled_modes": ["armed_away", "armed_home"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    (subentry,) = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_AREA
    ]
    assert subentry.title == "Home"
    assert subentry.data[CONF_MODES]["armed_away"]["enabled"] is True
    assert subentry.data[CONF_MODES]["armed_night"]["enabled"] is False


async def test_edit_area_timers(hass):
    entry = await _entry(hass)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                CONF_NAME: "Home",
                CONF_MODES: {
                    "armed_away": {
                        "enabled": True,
                        "exit_time": 60,
                        "entry_time": 30,
                        "trigger_time": 120,
                    },
                    "armed_home": {"enabled": False},
                    "armed_night": {"enabled": False},
                    "armed_vacation": {"enabled": False},
                    "armed_custom_bypass": {"enabled": False},
                },
            },
            subentry_type=SUBENTRY_TYPE_AREA,
            title="Home",
            unique_id=None,
        ),
    )
    (subentry,) = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_AREA
    ]

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit_timers"}
    )
    assert result["step_id"] == "edit_timers"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Home",
            "enabled_modes": ["armed_away"],
            "exit_time": 45,
            "entry_time": 15,
            "trigger_time": 90,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated = entry.subentries[subentry.subentry_id]
    assert updated.data[CONF_MODES]["armed_away"]["exit_time"] == 45
    assert updated.data[CONF_MODES]["armed_home"]["enabled"] is False


async def test_manage_sensors_attaches_and_reloads(hass):
    entry = await _entry(hass)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                CONF_NAME: "Home",
                CONF_MODES: {
                    "armed_away": {
                        "enabled": True,
                        "exit_time": 60,
                        "entry_time": 30,
                        "trigger_time": 120,
                    },
                    "armed_home": {"enabled": False},
                    "armed_night": {"enabled": False},
                    "armed_vacation": {"enabled": False},
                    "armed_custom_bypass": {"enabled": False},
                },
            },
            subentry_type=SUBENTRY_TYPE_AREA,
            title="Home",
            unique_id=None,
        ),
    )
    (subentry,) = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_AREA
    ]
    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_or_create(
        "binary_sensor", "test", "front_door"
    ).entity_id

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "manage_sensors"}
    )
    assert result["step_id"] == "manage_sensors"

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"sensors": [sensor_entity_id]}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "sensors_updated"

    assert sensors.sensors_for_area(hass, subentry.subentry_id) == [sensor_entity_id]


async def test_add_user_hashes_code(hass):
    entry = await _entry(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_USER),
        context={"source": "user"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Alice",
            CONF_CODE: "4242",
            "can_arm": True,
            "can_disarm": True,
            "is_override_code": False,
            "enabled": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    (subentry,) = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_USER
    ]
    assert subentry.data[CONF_CODE] != "4242"  # stored hashed, never plaintext
    assert pin._check_code_sync("4242", subentry.data[CONF_CODE]) is True


async def test_reconfigure_user_blank_code_keeps_existing(hass):
    entry = await _entry(hass)
    hashed = await pin.async_hash_code(hass, "4242")
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                CONF_NAME: "Alice",
                CONF_CODE: hashed,
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
    (subentry,) = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_USER
    ]

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Alice",
            CONF_CODE: "",
            "can_arm": False,
            "can_disarm": True,
            "is_override_code": False,
            "enabled": True,
        },
    )
    assert result["type"] is FlowResultType.ABORT

    updated = entry.subentries[subentry.subentry_id]
    assert updated.data[CONF_CODE] == hashed  # unchanged
    assert updated.data["can_arm"] is False  # other fields did update
