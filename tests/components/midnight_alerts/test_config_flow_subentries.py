"""Tests for the area/user config subentry flows."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigSubentry
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import pin, sensors
from custom_components.midnight_alerts.const import (
    CONF_API_KEY,
    CONF_ALWAYS_ON,
    CONF_AREA_LIMIT,
    CONF_ARM_ON_CLOSE,
    CONF_CODE,
    CONF_DELAY_ON,
    CONF_ENTITIES,
    CONF_EVENT_COUNT,
    CONF_MODES,
    CONF_NAME,
    CONF_SENSOR_ENTRY_DELAY,
    CONF_TIMEOUT,
    DOMAIN,
    SUBENTRY_TYPE_ALARMO_IMPORT,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_SENSOR_GROUP,
    SUBENTRY_TYPE_USER,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "alarmo_storage_sample.json"
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


async def test_manage_sensors_detaches_previously_attached_sensor(hass):
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
    sensors.async_set_sensor_options(
        hass, sensor_entity_id, area_subentry_id=subentry.subentry_id
    )

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "manage_sensors"}
    )
    assert result["data_schema"]({})["sensors"] == [sensor_entity_id]

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"sensors": []}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "sensors_updated"

    assert sensors.sensors_for_area(hass, subentry.subentry_id) == []
    assert sensors.async_get_sensor_options(hass, sensor_entity_id) is None


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


async def test_add_sensor_group(hass):
    entry = await _entry(hass)
    registry = er.async_get(hass)
    motion1 = registry.async_get_or_create("binary_sensor", "test", "motion1").entity_id
    motion2 = registry.async_get_or_create("binary_sensor", "test", "motion2").entity_id

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_SENSOR_GROUP),
        context={"source": "user"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Motion confirm",
            CONF_ENTITIES: [motion1, motion2],
            CONF_TIMEOUT: 15,
            CONF_EVENT_COUNT: 2,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    (subentry,) = [
        s
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_TYPE_SENSOR_GROUP
    ]
    assert subentry.title == "Motion confirm"
    assert subentry.data[CONF_ENTITIES] == [motion1, motion2]
    assert subentry.data[CONF_TIMEOUT] == 15


async def test_reconfigure_sensor_group(hass):
    entry = await _entry(hass)
    registry = er.async_get(hass)
    motion1 = registry.async_get_or_create("binary_sensor", "test", "motion1").entity_id
    motion2 = registry.async_get_or_create("binary_sensor", "test", "motion2").entity_id
    motion3 = registry.async_get_or_create("binary_sensor", "test", "motion3").entity_id
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                CONF_NAME: "Motion confirm",
                CONF_ENTITIES: [motion1, motion2],
                CONF_TIMEOUT: 10,
                CONF_EVENT_COUNT: 2,
            },
            subentry_type=SUBENTRY_TYPE_SENSOR_GROUP,
            title="Motion confirm",
            unique_id=None,
        ),
    )
    (subentry,) = [
        s
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_TYPE_SENSOR_GROUP
    ]

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Motion confirm",
            CONF_ENTITIES: [motion1, motion2, motion3],
            CONF_TIMEOUT: 20,
            CONF_EVENT_COUNT: 3,
        },
    )
    assert result["type"] is FlowResultType.ABORT

    updated = entry.subentries[subentry.subentry_id]
    assert updated.data[CONF_ENTITIES] == [motion1, motion2, motion3]
    assert updated.data[CONF_EVENT_COUNT] == 3


async def test_manage_sensors_applies_arm_on_close_and_delay_on_to_new_sensors(hass):
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

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                "sensors": [sensor_entity_id],
                CONF_ARM_ON_CLOSE: True,
                CONF_DELAY_ON: 5,
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT

    options = sensors.async_get_sensor_options(hass, sensor_entity_id)
    assert options[CONF_ARM_ON_CLOSE] is True
    assert options[CONF_DELAY_ON] == 5


def _home_area_subentry() -> ConfigSubentry:
    return ConfigSubentry(
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
    )


async def test_manage_sensors_applies_always_on_entry_delay_and_modes_to_new_sensors(
    hass,
):
    entry = await _entry(hass)
    hass.config_entries.async_add_subentry(entry, _home_area_subentry())
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

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                "sensors": [sensor_entity_id],
                CONF_ALWAYS_ON: True,
                CONF_SENSOR_ENTRY_DELAY: 15,
                CONF_MODES: ["armed_away"],
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT

    options = sensors.async_get_sensor_options(hass, sensor_entity_id)
    assert options[CONF_ALWAYS_ON] is True
    assert options[CONF_SENSOR_ENTRY_DELAY] == 15
    assert options[CONF_MODES] == ["armed_away"]


async def test_manage_sensors_leaves_entry_delay_and_modes_unset_when_blank(hass):
    """An empty modes selection must stay absent, not [] (which would mean

    "restricted to zero modes" - i.e. blocked in every mode - rather than
    "unrestricted").
    """
    entry = await _entry(hass)
    hass.config_entries.async_add_subentry(entry, _home_area_subentry())
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

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"sensors": [sensor_entity_id]}
        )
        await hass.async_block_till_done()

    options = sensors.async_get_sensor_options(hass, sensor_entity_id)
    assert CONF_SENSOR_ENTRY_DELAY not in options
    assert CONF_MODES not in options


def _write_alarmo_storage(hass) -> None:
    storage_dir = Path(hass.config.path(".storage"))
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "alarmo.storage").write_text(FIXTURE_PATH.read_text())


async def test_alarmo_import_flow_shows_preview_then_applies(hass, tmp_path, monkeypatch):
    # See test_alarmo_import.py's test_read_alarmo_storage_missing_file_returns_none
    # for why config_dir must be redirected before writing a real storage file.
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    entry = await _entry(hass)
    _write_alarmo_storage(hass)
    registry = er.async_get(hass)
    for name in ("front_door", "motion1", "motion2"):
        registry.async_get_or_create(
            "binary_sensor", "test", name, suggested_object_id=name
        )
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALARMO_IMPORT),
        context={"source": "user"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["description_placeholders"]["areas"] == "1"
    assert result["description_placeholders"]["sensors"] == "3"
    assert result["description_placeholders"]["automations_skipped"] == "2"

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "import_complete"
    assert result["description_placeholders"]["areas"] == "1"

    area_subentries = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_AREA
    ]
    assert len(area_subentries) == 1


async def test_alarmo_import_flow_no_file_aborts(hass, tmp_path, monkeypatch):
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    entry = await _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALARMO_IMPORT),
        context={"source": "user"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "alarmo_not_found"


async def test_alarmo_import_flow_version_mismatch_aborts(hass, tmp_path, monkeypatch):
    """A storage file from an unmigrated Alarmo version must abort, not crash."""
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    entry = await _entry(hass)
    storage_dir = Path(hass.config.path(".storage"))
    storage_dir.mkdir(parents=True, exist_ok=True)
    raw = json.loads(FIXTURE_PATH.read_text())
    raw["version"] = 5
    (storage_dir / "alarmo.storage").write_text(json.dumps(raw))

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALARMO_IMPORT),
        context={"source": "user"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "alarmo_version_mismatch"


async def test_alarmo_import_flow_twice_reports_already_imported(hass, tmp_path, monkeypatch):
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    entry = await _entry(hass)
    _write_alarmo_storage(hass)
    registry = er.async_get(hass)
    for name in ("front_door", "motion1", "motion2"):
        registry.async_get_or_create(
            "binary_sensor", "test", name, suggested_object_id=name
        )
    await hass.async_block_till_done()

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        for _ in range(2):
            result = await hass.config_entries.subentries.async_init(
                (entry.entry_id, SUBENTRY_TYPE_ALARMO_IMPORT),
                context={"source": "user"},
            )
            result = await hass.config_entries.subentries.async_configure(
                result["flow_id"], {}
            )
            await hass.async_block_till_done()

    assert result["reason"] == "already_imported"
