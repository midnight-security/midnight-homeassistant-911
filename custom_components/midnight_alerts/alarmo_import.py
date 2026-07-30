"""One-time "Import from Alarmo" migration.

Reads Alarmo's own storage file directly (never a live
`homeassistant.helpers.storage.Store` against it - `Store` expects to run
its *own* migration chain and would raise against a file whose version
doesn't match what we'd request; reading the raw JSON and validating the
version ourselves lets us degrade gracefully instead: if it's not what we
expect, we ask the user to open Alarmo once, let it self-migrate, and
retry).

Areas/users/sensor-groups reuse Alarmo's own ids as our subentry_id *and*
unique_id (prefixed with "alarmo_"): this makes the sensor/area and
user/area_limit foreign keys a direct string copy with no translation
table, and makes re-running the import a safe no-op (`unique_id` collisions
are skipped, not duplicated) rather than a hazard.

PINs are copied across as-is - Alarmo hashes codes as base64(bcrypt(code)),
the exact format `pin.py` uses, so an imported PIN keeps working
immediately with zero conversion. Automations are never imported (Alarmo's
automations engine is one of the anti-patterns this whole platform exists
to avoid) - they're only counted, so the user knows to recreate the ones
they still need as real HA automations.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from . import sensors
from .const import (
    ALARMO_STORAGE_VERSION,
    CONF_ALLOW_OPEN,
    CONF_ALWAYS_ON,
    CONF_AREA_LIMIT,
    CONF_AREA_SUBENTRY_ID,
    CONF_ARM_ON_CLOSE,
    CONF_CAN_ARM,
    CONF_CAN_DISARM,
    CONF_CODE,
    CONF_DELAY_ON,
    CONF_ENABLED,
    CONF_ENTITIES,
    CONF_ENTRY_TIME,
    CONF_EVENT_COUNT,
    CONF_EXIT_TIME,
    CONF_IS_OVERRIDE_CODE,
    CONF_MODES,
    CONF_NAME,
    CONF_SENSOR_ENTRY_DELAY,
    CONF_SENSOR_TYPE,
    CONF_TIMEOUT,
    CONF_TRIGGER_TIME,
    CONF_USE_ENTRY_DELAY,
    CONF_USE_EXIT_DELAY,
    DEFAULT_ENTRY_TIME,
    DEFAULT_EXIT_TIME,
    DEFAULT_TRIGGER_TIME,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_SENSOR_GROUP,
    SUBENTRY_TYPE_USER,
)

_LOGGER = logging.getLogger(__name__)

_ALARMO_MODES = (
    "armed_away",
    "armed_home",
    "armed_night",
    "armed_vacation",
    "armed_custom_bypass",
)


@dataclass
class SensorImport:
    """One sensor's alarm-specific options, ready for sensors.async_set_sensor_options."""

    entity_id: str
    options: dict[str, Any]


@dataclass
class AlarmoImportPlan:
    """What an import would do - built once, shown to the user, then applied."""

    areas: list[ConfigSubentry] = field(default_factory=list)
    users: list[ConfigSubentry] = field(default_factory=list)
    sensor_groups: list[ConfigSubentry] = field(default_factory=list)
    sensor_imports: list[SensorImport] = field(default_factory=list)
    automation_count: int = 0


@dataclass
class AlarmoImportSummary:
    """What actually happened when the plan was applied."""

    areas_imported: int = 0
    users_imported: int = 0
    sensor_groups_imported: int = 0
    sensors_imported: int = 0
    sensors_skipped: list[str] = field(default_factory=list)
    already_imported: bool = False
    automations_skipped: int = 0


def _subentry_id(kind: str, alarmo_id: str) -> str:
    return f"alarmo_{kind}_{alarmo_id}"


async def async_read_alarmo_storage(hass: HomeAssistant) -> dict[str, Any] | None:
    """Read Alarmo's storage file directly, or None if it isn't present."""
    path = hass.config.path(".storage", "alarmo.storage")
    return await hass.async_add_executor_job(_read_json, path)


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as err:
        _LOGGER.warning("Could not read Alarmo storage at %s: %s", path, err)
        return None


def parse_import(raw: dict[str, Any]) -> AlarmoImportPlan | None:
    """Build an import plan from Alarmo's raw storage envelope.

    Returns None if the file doesn't look like Alarmo's storage or is a
    version we don't understand - reimplementing Alarmo's own multi-version
    migration chain is out of scope; the user should open Alarmo once (it
    self-migrates on load) and retry.
    """
    if raw.get("key") != "alarmo.storage":
        return None
    if raw.get("version") != ALARMO_STORAGE_VERSION:
        return None
    data = raw.get("data")
    if not isinstance(data, dict):
        return None

    plan = AlarmoImportPlan()

    for area in data.get("areas", []):
        area_id = str(area["area_id"])
        modes_data = area.get("modes", {})
        plan.areas.append(
            ConfigSubentry(
                subentry_id=_subentry_id("area", area_id),
                unique_id=_subentry_id("area", area_id),
                subentry_type=SUBENTRY_TYPE_AREA,
                title=area.get("name", "Imported area"),
                data={
                    CONF_NAME: area.get("name", "Imported area"),
                    CONF_MODES: {
                        mode: {
                            CONF_ENABLED: bool(modes_data.get(mode, {}).get("enabled")),
                            CONF_EXIT_TIME: modes_data.get(mode, {}).get("exit_time")
                            or DEFAULT_EXIT_TIME,
                            CONF_ENTRY_TIME: modes_data.get(mode, {}).get("entry_time")
                            or DEFAULT_ENTRY_TIME,
                            CONF_TRIGGER_TIME: modes_data.get(mode, {}).get(
                                "trigger_time"
                            )
                            or DEFAULT_TRIGGER_TIME,
                        }
                        for mode in _ALARMO_MODES
                    },
                },
            )
        )

    for user in data.get("users", []):
        user_id = str(user["user_id"])
        plan.users.append(
            ConfigSubentry(
                subentry_id=_subentry_id("user", user_id),
                unique_id=_subentry_id("user", user_id),
                subentry_type=SUBENTRY_TYPE_USER,
                title=user.get("name", "Imported user"),
                data={
                    CONF_NAME: user.get("name", "Imported user"),
                    CONF_CODE: user.get("code", ""),  # already bcrypt+base64 - same format
                    CONF_CAN_ARM: bool(user.get("can_arm", True)),
                    CONF_CAN_DISARM: bool(user.get("can_disarm", True)),
                    CONF_IS_OVERRIDE_CODE: bool(user.get("is_override_code")),
                    CONF_ENABLED: bool(user.get("enabled", True)),
                    CONF_AREA_LIMIT: [
                        _subentry_id("area", str(a)) for a in user.get("area_limit", [])
                    ],
                },
            )
        )

    for group in data.get("sensor_groups", []):
        group_id = str(group["group_id"])
        plan.sensor_groups.append(
            ConfigSubentry(
                subentry_id=_subentry_id("sensor_group", group_id),
                unique_id=_subentry_id("sensor_group", group_id),
                subentry_type=SUBENTRY_TYPE_SENSOR_GROUP,
                title=group.get("name", "Imported group"),
                data={
                    CONF_NAME: group.get("name", "Imported group"),
                    CONF_ENTITIES: list(group.get("entities", [])),
                    CONF_TIMEOUT: group.get("timeout", 10),
                    CONF_EVENT_COUNT: group.get("event_count", 2),
                },
            )
        )

    for sensor in data.get("sensors", []):
        if not sensor.get("enabled", True):
            continue
        options: dict[str, Any] = {
            CONF_AREA_SUBENTRY_ID: _subentry_id("area", str(sensor.get("area"))),
            CONF_SENSOR_TYPE: sensor.get("type", "other"),
            CONF_ALWAYS_ON: bool(sensor.get("always_on")),
            CONF_ALLOW_OPEN: bool(sensor.get("allow_open")),
            CONF_USE_EXIT_DELAY: bool(sensor.get("use_exit_delay", True)),
            CONF_USE_ENTRY_DELAY: bool(sensor.get("use_entry_delay", True)),
            CONF_ARM_ON_CLOSE: bool(sensor.get("arm_on_close")),
        }
        if sensor.get("modes"):
            options[CONF_MODES] = list(sensor["modes"])
        if sensor.get("entry_delay") is not None:
            options[CONF_SENSOR_ENTRY_DELAY] = sensor["entry_delay"]
        if sensor.get("delay_on") is not None:
            options[CONF_DELAY_ON] = sensor["delay_on"]
        plan.sensor_imports.append(
            SensorImport(entity_id=sensor["entity_id"], options=options)
        )

    plan.automation_count = len(data.get("automations", []))
    return plan


async def async_apply_import(
    hass: HomeAssistant, entry: ConfigEntry, plan: AlarmoImportPlan
) -> AlarmoImportSummary:
    """Apply a previously-built plan: create subentries, set sensor options, reload."""
    summary = AlarmoImportSummary(automations_skipped=plan.automation_count)
    existing_unique_ids = {s.unique_id for s in entry.subentries.values()}

    if any(area.unique_id in existing_unique_ids for area in plan.areas):
        summary.already_imported = True
        return summary

    for area in plan.areas:
        hass.config_entries.async_add_subentry(entry, area)
        summary.areas_imported += 1

    for user in plan.users:
        hass.config_entries.async_add_subentry(entry, user)
        summary.users_imported += 1

    for group in plan.sensor_groups:
        hass.config_entries.async_add_subentry(entry, group)
        summary.sensor_groups_imported += 1

    for sensor_import in plan.sensor_imports:
        try:
            sensors.async_set_sensor_options(
                hass, sensor_import.entity_id, **sensor_import.options
            )
            summary.sensors_imported += 1
        except ValueError:
            summary.sensors_skipped.append(sensor_import.entity_id)

    if summary.areas_imported or summary.sensor_groups_imported:
        await hass.config_entries.async_reload(entry.entry_id)

    return summary
