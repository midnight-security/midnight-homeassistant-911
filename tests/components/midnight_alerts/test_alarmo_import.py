"""Tests for the Alarmo import parser and apply step."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.midnight_alerts import alarmo_import, pin, sensors
from custom_components.midnight_alerts.const import (
    CONF_API_KEY,
    CONF_AREA_LIMIT,
    CONF_CODE,
    CONF_EXIT_TIME,
    CONF_MODES,
    DOMAIN,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_SENSOR_GROUP,
    SUBENTRY_TYPE_USER,
)

VALIDATE = "custom_components.midnight_alerts.api.MidnightAlertsApiClient.async_validate"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "alarmo_storage_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_parse_import_builds_expected_areas():
    plan = alarmo_import.parse_import(_load_fixture())
    assert plan is not None
    (area,) = plan.areas
    assert area.title == "Home"
    assert area.subentry_type == SUBENTRY_TYPE_AREA
    assert area.data[CONF_MODES]["armed_away"]["enabled"] is True
    assert area.data[CONF_MODES]["armed_away"][CONF_EXIT_TIME] == 45
    assert area.data[CONF_MODES]["armed_night"]["enabled"] is False
    # a mode with exit_time: null falls back to our default, not None/0
    assert area.data[CONF_MODES]["armed_home"][CONF_EXIT_TIME] == 60


def test_parse_import_carries_pin_hash_across_unchanged():
    raw = _load_fixture()
    original_hash = raw["data"]["users"][0]["code"]
    plan = alarmo_import.parse_import(raw)
    (user,) = plan.users
    assert user.subentry_type == SUBENTRY_TYPE_USER
    assert user.data[CONF_CODE] == original_hash
    # and that hash must actually still verify the original PIN
    assert pin._check_code_sync("1234", user.data[CONF_CODE]) is True


def test_parse_import_maps_area_limit_to_our_area_ids():
    raw = _load_fixture()
    raw["data"]["users"][0]["area_limit"] = ["1700000000"]
    plan = alarmo_import.parse_import(raw)
    (user,) = plan.users
    (area,) = plan.areas
    assert user.data[CONF_AREA_LIMIT] == [area.subentry_id]


def test_parse_import_sensor_groups():
    plan = alarmo_import.parse_import(_load_fixture())
    (group,) = plan.sensor_groups
    assert group.subentry_type == SUBENTRY_TYPE_SENSOR_GROUP
    assert group.data["entities"] == ["binary_sensor.motion1", "binary_sensor.motion2"]
    assert group.data["event_count"] == 2


def test_parse_import_skips_disabled_sensors():
    plan = alarmo_import.parse_import(_load_fixture())
    imported_ids = {s.entity_id for s in plan.sensor_imports}
    assert "binary_sensor.disabled_sensor" not in imported_ids
    assert "binary_sensor.front_door" in imported_ids


def test_parse_import_sensor_options_map_correctly():
    plan = alarmo_import.parse_import(_load_fixture())
    front_door = next(
        s for s in plan.sensor_imports if s.entity_id == "binary_sensor.front_door"
    )
    assert front_door.options["arm_on_close"] is True
    assert front_door.options["sensor_type"] == "door"

    motion1 = next(
        s for s in plan.sensor_imports if s.entity_id == "binary_sensor.motion1"
    )
    assert motion1.options["entry_delay"] == 15
    assert motion1.options["delay_on"] == 3


def test_parse_import_counts_but_does_not_import_automations():
    plan = alarmo_import.parse_import(_load_fixture())
    assert plan.automation_count == 2
    assert not hasattr(plan, "automations")


def test_parse_import_rejects_wrong_version():
    raw = _load_fixture()
    raw["version"] = 5
    assert alarmo_import.parse_import(raw) is None


def test_parse_import_rejects_wrong_key():
    raw = _load_fixture()
    raw["key"] = "something_else"
    assert alarmo_import.parse_import(raw) is None


async def test_read_alarmo_storage_missing_file_returns_none(hass, tmp_path, monkeypatch):
    # hass.config.path() otherwise resolves into a *shared*, non-isolated
    # directory inside the installed pytest_homeassistant_custom_component
    # package itself - not a per-test tmp dir - so tests that write a real
    # file there must redirect config_dir to an isolated tmp_path, or they
    # leak state into every other test (and even future test runs) that
    # doesn't expect an alarmo.storage file to exist.
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    assert await alarmo_import.async_read_alarmo_storage(hass) is None


async def test_read_alarmo_storage_reads_real_file(hass, tmp_path, monkeypatch):
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    storage_dir = Path(hass.config.path(".storage"))
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "alarmo.storage").write_text(FIXTURE_PATH.read_text())

    raw = await alarmo_import.async_read_alarmo_storage(hass)
    assert raw is not None
    assert raw["key"] == "alarmo.storage"


async def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "test-key"})
    entry.add_to_hass(hass)
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_apply_import_creates_subentries_and_sensor_options(hass):
    entry = await _entry(hass)
    registry = er.async_get(hass)
    for name in ("front_door", "motion1", "motion2"):
        registry.async_get_or_create("binary_sensor", "test", name, suggested_object_id=name)
        hass.states.async_set(f"binary_sensor.{name}", "off")
    await hass.async_block_till_done()

    plan = alarmo_import.parse_import(_load_fixture())
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        summary = await alarmo_import.async_apply_import(hass, entry, plan)
        await hass.async_block_till_done()

    assert summary.areas_imported == 1
    assert summary.users_imported == 1
    assert summary.sensor_groups_imported == 1
    assert summary.sensors_imported == 3  # disabled_sensor was already excluded by parse_import
    assert summary.sensors_skipped == []
    assert summary.automations_skipped == 2
    assert summary.already_imported is False

    area_subentries = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_AREA
    ]
    assert len(area_subentries) == 1
    assert sensors.async_get_sensor_options(hass, "binary_sensor.front_door")[
        "arm_on_close"
    ] is True


async def test_apply_import_reports_missing_entities(hass):
    entry = await _entry(hass)
    # deliberately do NOT register the sensor entities - simulates them not
    # existing in this HA instance
    plan = alarmo_import.parse_import(_load_fixture())

    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        summary = await alarmo_import.async_apply_import(hass, entry, plan)
        await hass.async_block_till_done()

    assert summary.sensors_imported == 0
    assert set(summary.sensors_skipped) == {
        "binary_sensor.front_door",
        "binary_sensor.motion1",
        "binary_sensor.motion2",
    }


async def test_apply_import_twice_is_a_safe_no_op(hass):
    entry = await _entry(hass)
    registry = er.async_get(hass)
    for name in ("front_door", "motion1", "motion2"):
        registry.async_get_or_create("binary_sensor", "test", name, suggested_object_id=name)
    await hass.async_block_till_done()

    plan = alarmo_import.parse_import(_load_fixture())
    with patch(VALIDATE, new=AsyncMock(return_value=None)):
        first = await alarmo_import.async_apply_import(hass, entry, plan)
        await hass.async_block_till_done()
        second = await alarmo_import.async_apply_import(hass, entry, plan)
        await hass.async_block_till_done()

    assert first.already_imported is False
    assert first.areas_imported == 1
    assert second.already_imported is True
    assert second.areas_imported == 0

    area_subentries = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_AREA
    ]
    assert len(area_subentries) == 1  # not duplicated
