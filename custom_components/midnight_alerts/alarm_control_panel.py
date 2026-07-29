"""Alarm control panel platform for Midnight Alerts ("Midnight Alarm").

One entity per configured "area" subentry on the Midnight 911 config entry.
Unlike homeassistant.components.manual (100% service-call-driven), this
entity also subscribes to real sensor entities, since automatic
entry/exit-delay and sensor-driven triggering is the actual value this adds
over the stock `manual` platform.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Self

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from . import pin, sensors
from .alarm_state import ARM_MODES, AreaFsm, display_state
from . import alarm_state as alarm_state_lib
from .const import (
    CONF_ALWAYS_ON,
    CONF_ENABLED,
    CONF_ENTRY_TIME,
    CONF_EXIT_TIME,
    CONF_MODES,
    CONF_SENSOR_ENTRY_DELAY,
    CONF_TRIGGER_TIME,
    CONF_USE_EXIT_DELAY,
    DEFAULT_ENTRY_TIME,
    DEFAULT_EXIT_TIME,
    DEFAULT_TRIGGER_TIME,
    DOMAIN,
    MODE_TO_FEATURE,
    SUBENTRY_TYPE_AREA,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one alarm_control_panel entity per configured area."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_AREA:
            continue
        async_add_entities(
            [MidnightAlarmArea(entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class _AreaFsmExtraData(ExtraStoredData):
    """Restore-state wrapper so a mid-countdown FSM survives a restart."""

    def __init__(self, fsm: AreaFsm) -> None:
        self.fsm = fsm

    def as_dict(self) -> dict[str, Any]:
        return {
            "settled_state": str(self.fsm.settled_state),
            "previous_state": (
                str(self.fsm.previous_state) if self.fsm.previous_state else None
            ),
            "arming_until": self.fsm.arming_until.isoformat()
            if self.fsm.arming_until
            else None,
            "pending_until": self.fsm.pending_until.isoformat()
            if self.fsm.pending_until
            else None,
            "trigger_until": self.fsm.trigger_until.isoformat()
            if self.fsm.trigger_until
            else None,
            "disarm_after_trigger": self.fsm.disarm_after_trigger,
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> Self | None:
        def _dt(value: str | None) -> datetime | None:
            return dt_util.parse_datetime(value) if value else None

        try:
            fsm = AreaFsm(
                settled_state=AlarmControlPanelState(restored["settled_state"]),
                previous_state=(
                    AlarmControlPanelState(restored["previous_state"])
                    if restored.get("previous_state")
                    else None
                ),
                arming_until=_dt(restored.get("arming_until")),
                pending_until=_dt(restored.get("pending_until")),
                trigger_until=_dt(restored.get("trigger_until")),
                disarm_after_trigger=bool(restored.get("disarm_after_trigger")),
            )
        except (KeyError, ValueError):
            return None
        return cls(fsm)


class MidnightAlarmArea(AlarmControlPanelEntity, RestoreEntity):
    """One alarm area (partition) within a Midnight 911 config entry."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_code_format = CodeFormat.NUMBER

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the area."""
        self._entry = entry
        self._subentry = subentry
        self._fsm = AreaFsm()
        self._unsub_callbacks: list[CALLBACK_TYPE] = []

        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Midnight Security",
            model="Midnight Alarm",
            name=subentry.title,
            identifiers={(DOMAIN, f"{entry.entry_id}_{subentry.subentry_id}")},
            via_device=(DOMAIN, entry.entry_id),
        )

        features = AlarmControlPanelEntityFeature.TRIGGER
        for mode, mode_config in subentry.data.get(CONF_MODES, {}).items():
            if mode_config.get(CONF_ENABLED) and mode in MODE_TO_FEATURE:
                features |= MODE_TO_FEATURE[mode]
        self._attr_supported_features = features

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        """Derive ARMING/PENDING/TRIGGERED from the FSM at read time."""
        state, fsm = display_state(self._fsm, dt_util.utcnow())
        self._fsm = fsm
        return state

    @property
    def code_arm_required(self) -> bool:
        """No code is demanded at all until at least one user is configured."""
        return pin.any_users_configured(self._entry)

    def _mode_config(self, mode: AlarmControlPanelState | None) -> dict[str, Any]:
        if mode is None:
            return {}
        return self._subentry.data.get(CONF_MODES, {}).get(mode, {})

    # --- lifecycle -----------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore FSM state and subscribe to configured sensors."""
        await super().async_added_to_hass()

        if (extra := await self.async_get_last_extra_data()) is not None:
            if restored := _AreaFsmExtraData.from_dict(extra.as_dict()):
                self._fsm = restored.fsm
                self._async_schedule(
                    self._fsm.arming_until,
                    self._fsm.pending_until,
                    self._fsm.trigger_until,
                )

        entity_ids = sensors.sensors_for_area(self.hass, self._subentry.subentry_id)
        if entity_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, entity_ids, self._async_sensor_event
                )
            )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any outstanding scheduled callbacks."""
        self._async_cancel_scheduled()
        await super().async_will_remove_from_hass()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        """Persist the FSM so a mid-countdown restart resumes correctly."""
        return _AreaFsmExtraData(self._fsm)

    # --- scheduling ------------------------------------------------------

    def _async_cancel_scheduled(self) -> None:
        for unsub in self._unsub_callbacks:
            unsub()
        self._unsub_callbacks = []

    def _async_schedule(self, *deadlines: datetime | None) -> None:
        """Force a state write at each deadline - nothing else polls this entity."""
        self._async_cancel_scheduled()
        for deadline in deadlines:
            if deadline is not None:
                self._unsub_callbacks.append(
                    async_track_point_in_time(
                        self.hass, self._async_scheduled_update, deadline
                    )
                )

    @callback
    def _async_scheduled_update(self, now: datetime) -> None:
        self.async_write_ha_state()

    # --- arm / disarm / trigger -----------------------------------------

    async def _async_start_arming(
        self, mode: AlarmControlPanelState, code: str | None
    ) -> None:
        match = await pin.async_validate_code(
            self.hass,
            self._entry,
            code=code,
            area_subentry_id=self._subentry.subentry_id,
            action="arm",
        )
        self._attr_changed_by = match.changed_by if match else None
        exit_time = self._mode_config(mode).get(CONF_EXIT_TIME, DEFAULT_EXIT_TIME)
        self._fsm = alarm_state_lib.start_arming(
            self._fsm, mode=mode, now=dt_util.utcnow(), exit_time=exit_time
        )
        self.async_write_ha_state()
        self._async_schedule(self._fsm.arming_until)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm away."""
        await self._async_start_arming(AlarmControlPanelState.ARMED_AWAY, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm home."""
        await self._async_start_arming(AlarmControlPanelState.ARMED_HOME, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Arm night."""
        await self._async_start_arming(AlarmControlPanelState.ARMED_NIGHT, code)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        """Arm vacation."""
        await self._async_start_arming(AlarmControlPanelState.ARMED_VACATION, code)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        """Arm custom bypass."""
        await self._async_start_arming(
            AlarmControlPanelState.ARMED_CUSTOM_BYPASS, code
        )

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm - always immediate, no delay."""
        match = await pin.async_validate_code(
            self.hass,
            self._entry,
            code=code,
            area_subentry_id=self._subentry.subentry_id,
            action="disarm",
        )
        self._attr_changed_by = match.changed_by if match else None
        self._async_cancel_scheduled()
        self._fsm = alarm_state_lib.disarm()
        self.async_write_ha_state()

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        """Manual trigger (e.g. a panic button) - immediate, no entry delay."""
        mode = self._fsm.settled_state if self._fsm.settled_state in ARM_MODES else None
        trigger_time = self._mode_config(mode).get(
            CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME
        )
        self._async_begin_trigger(entry_delay=0, trigger_time=trigger_time)

    # --- sensor-driven transitions ----------------------------------------

    def _async_begin_trigger(self, *, entry_delay: int, trigger_time: int) -> None:
        self._fsm = alarm_state_lib.start_trigger(
            self._fsm,
            now=dt_util.utcnow(),
            entry_delay=entry_delay,
            trigger_time=trigger_time,
            disarm_after_trigger=False,
        )
        self.async_write_ha_state()
        self._async_schedule(self._fsm.pending_until, self._fsm.trigger_until)

    @callback
    def _async_sensor_event(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None or sensors.parse_sensor_state(new_state.state) != "open":
            return  # Phase 1 only reacts to opening edges, matching Alarmo's core behavior

        entity_id = event.data["entity_id"]
        options = sensors.async_get_sensor_options(self.hass, entity_id) or {}
        display = self.alarm_state  # also runs any pending auto-revert derivation

        if options.get(CONF_ALWAYS_ON):
            self._async_begin_trigger(
                entry_delay=0,
                trigger_time=self._mode_config(
                    self._fsm.settled_state
                    if self._fsm.settled_state in ARM_MODES
                    else None
                ).get(CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME),
            )
            return

        if display == AlarmControlPanelState.ARMING:
            if not options.get(CONF_USE_EXIT_DELAY, True):
                self._fsm = alarm_state_lib.abort_arming(self._fsm)
                self._attr_changed_by = None
                self.async_write_ha_state()
                self._async_schedule(self._fsm.arming_until)
            return

        if display not in ARM_MODES and display != AlarmControlPanelState.TRIGGERED:
            return  # disarmed, not always_on - ignore

        mode_membership = options.get(CONF_MODES)
        if (
            display in ARM_MODES
            and mode_membership is not None
            and display not in mode_membership
        ):
            return

        mode = display if display in ARM_MODES else self._fsm.previous_state
        entry_delay = options.get(CONF_SENSOR_ENTRY_DELAY)
        if entry_delay is None:
            entry_delay = self._mode_config(mode).get(
                CONF_ENTRY_TIME, DEFAULT_ENTRY_TIME
            )

        if display == AlarmControlPanelState.TRIGGERED:
            self._fsm = alarm_state_lib.shorten_pending(
                self._fsm, now=dt_util.utcnow(), entry_delay=entry_delay
            )
            self.async_write_ha_state()
            self._async_schedule(self._fsm.pending_until, self._fsm.trigger_until)
            return

        trigger_time = self._mode_config(mode).get(
            CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME
        )
        self._async_begin_trigger(entry_delay=entry_delay, trigger_time=trigger_time)
