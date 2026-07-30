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
from functools import partial
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
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from . import pin, sensors
from . import alarm_state as alarm_state_lib
from .sensor_groups import GroupTally, is_confirmed
from .const import (
    CONF_ALWAYS_ON,
    CONF_ARM_ON_CLOSE,
    CONF_DELAY_ON,
    CONF_ENABLED,
    CONF_ENTITIES,
    CONF_ENTRY_TIME,
    CONF_EVENT_COUNT,
    CONF_EXIT_TIME,
    CONF_MODES,
    CONF_SENSOR_ENTRY_DELAY,
    CONF_TIMEOUT,
    CONF_TRIGGER_TIME,
    CONF_USE_EXIT_DELAY,
    DEFAULT_ENTRY_TIME,
    DEFAULT_EXIT_TIME,
    DEFAULT_SENSOR_GROUP_EVENT_COUNT,
    DEFAULT_SENSOR_GROUP_TIMEOUT,
    DEFAULT_TRIGGER_TIME,
    DOMAIN,
    MODE_TO_FEATURE,
    SUBENTRY_TYPE_AREA,
    SUBENTRY_TYPE_SENSOR_GROUP,
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

    def __init__(self, fsm: alarm_state_lib.AreaFsm) -> None:
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
            "held_open": self.fsm.held_open,
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> Self | None:
        def _dt(value: str | None) -> datetime | None:
            return dt_util.parse_datetime(value) if value else None

        try:
            fsm = alarm_state_lib.AreaFsm(
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
                held_open=bool(restored.get("held_open")),
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
        self._fsm = alarm_state_lib.AreaFsm()
        self._unsub_callbacks: list[CALLBACK_TYPE] = []
        self._delay_on_unsub: dict[str, CALLBACK_TYPE] = {}
        self._group_tallies: dict[str, GroupTally] = {}

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
        state, fsm = alarm_state_lib.display_state(self._fsm, dt_util.utcnow())
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
                if self._fsm.arming_until:
                    self._async_schedule_arming(self._fsm.arming_until)
                else:
                    self._async_schedule(
                        self._fsm.pending_until, self._fsm.trigger_until
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
        for unsub in self._delay_on_unsub.values():
            unsub()
        self._delay_on_unsub = {}
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

    def _async_schedule_arming(self, deadline: datetime | None) -> None:
        """Like _async_schedule, but checks for arm_on_close holds at the deadline."""
        self._async_cancel_scheduled()
        if deadline is not None:
            self._unsub_callbacks.append(
                async_track_point_in_time(
                    self.hass, self._async_arming_deadline_reached, deadline
                )
            )

    @callback
    def _async_scheduled_update(self, now: datetime) -> None:
        self.async_write_ha_state()

    @callback
    def _async_arming_deadline_reached(self, now: datetime) -> None:
        """Exit delay has elapsed - finish arming, unless something holds it open."""
        if self._open_arm_on_close_sensors():
            self._fsm = alarm_state_lib.hold_for_close(self._fsm)
        self.async_write_ha_state()

    def _open_arm_on_close_sensors(self) -> list[str]:
        """Currently-open sensors in this area flagged arm_on_close."""
        open_sensors = []
        for entity_id in sensors.sensors_for_area(
            self.hass, self._subentry.subentry_id
        ):
            options = sensors.async_get_sensor_options(self.hass, entity_id) or {}
            if not options.get(CONF_ARM_ON_CLOSE):
                continue
            state = self.hass.states.get(entity_id)
            if state and sensors.parse_sensor_state(state.state) == "open":
                open_sensors.append(entity_id)
        return open_sensors

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
        self._async_schedule_arming(self._fsm.arming_until)

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
        settled = self._fsm.settled_state
        mode = settled if settled in alarm_state_lib.ARM_MODES else None
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
        if new_state is None:
            return
        entity_id = event.data["entity_id"]
        status = sensors.parse_sensor_state(new_state.state)

        if status == "open":
            self._async_handle_sensor_open(entity_id)
        elif status == "closed":
            self._async_handle_sensor_closed(entity_id)

    def _async_handle_sensor_open(self, entity_id: str) -> None:
        options = sensors.async_get_sensor_options(self.hass, entity_id) or {}

        delay_on = options.get(CONF_DELAY_ON) or 0
        if delay_on:
            # Debounce: only treat this as a real trip if the sensor is
            # *still* open `delay_on` seconds from now - filters a
            # momentary blip (wind, a glitchy contact) from counting.
            if unsub := self._delay_on_unsub.pop(entity_id, None):
                unsub()
            self._delay_on_unsub[entity_id] = async_call_later(
                self.hass,
                delay_on,
                partial(self._async_delay_on_elapsed, entity_id, options),
            )
            return

        self._async_process_open_sensor(entity_id, options)

    @callback
    def _async_delay_on_elapsed(
        self, entity_id: str, options: dict[str, Any], now: datetime
    ) -> None:
        self._delay_on_unsub.pop(entity_id, None)
        state = self.hass.states.get(entity_id)
        if not state or sensors.parse_sensor_state(state.state) != "open":
            return  # closed again before delay_on elapsed - a filtered blip
        self._async_process_open_sensor(entity_id, options)

    def _async_handle_sensor_closed(self, entity_id: str) -> None:
        if unsub := self._delay_on_unsub.pop(entity_id, None):
            unsub()  # the blip ended before its debounce confirmed it

        if not self._fsm.held_open:
            return
        options = sensors.async_get_sensor_options(self.hass, entity_id) or {}
        if not options.get(CONF_ARM_ON_CLOSE):
            return
        if self._open_arm_on_close_sensors():
            return  # other arm_on_close sensors are still open
        self._fsm = alarm_state_lib.release_hold(self._fsm, now=dt_util.utcnow())
        self.async_write_ha_state()

    def _groups_for_sensor(self, entity_id: str) -> list[ConfigSubentry]:
        return [
            subentry
            for subentry in self._entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_SENSOR_GROUP
            and entity_id in subentry.data.get(CONF_ENTITIES, [])
        ]

    def _sensor_confirmed_by_groups(self, entity_id: str, now: datetime) -> bool:
        """Whether this sensor's trip counts as a real event right now.

        A sensor not in any group is ungated (matches Phase 1 behavior). A
        grouped sensor's trip only counts once `event_count` of its group's
        members have tripped within `timeout` seconds of each other -
        filtering out e.g. a single pet-triggered motion sensor.
        """
        groups = self._groups_for_sensor(entity_id)
        if not groups:
            return True

        confirmed = False
        for group in groups:
            tally = self._group_tallies.get(group.subentry_id, GroupTally())
            tally = tally.record_trip(entity_id, now)
            self._group_tallies[group.subentry_id] = tally
            if is_confirmed(
                tally,
                now=now,
                timeout=group.data.get(CONF_TIMEOUT, DEFAULT_SENSOR_GROUP_TIMEOUT),
                event_count=group.data.get(
                    CONF_EVENT_COUNT, DEFAULT_SENSOR_GROUP_EVENT_COUNT
                ),
            ):
                confirmed = True
        return confirmed

    def _async_process_open_sensor(self, entity_id: str, options: dict[str, Any]) -> None:
        display = self.alarm_state  # also runs any pending auto-revert derivation

        if options.get(CONF_ALWAYS_ON):
            self._async_begin_trigger(
                entry_delay=0,
                trigger_time=self._mode_config(
                    self._fsm.settled_state
                    if self._fsm.settled_state in alarm_state_lib.ARM_MODES
                    else None
                ).get(CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME),
            )
            return

        if not self._sensor_confirmed_by_groups(entity_id, dt_util.utcnow()):
            return  # not enough corroborating sensors yet - wait for more

        if display == AlarmControlPanelState.ARMING:
            if not options.get(CONF_USE_EXIT_DELAY, True):
                self._fsm = alarm_state_lib.abort_arming(self._fsm)
                self._attr_changed_by = None
                self.async_write_ha_state()
                self._async_schedule(self._fsm.arming_until)
            return

        armed = display in alarm_state_lib.ARM_MODES
        mid_sequence = (
            AlarmControlPanelState.PENDING,
            AlarmControlPanelState.TRIGGERED,
        )
        if not armed and display not in mid_sequence:
            return  # disarmed, not always_on - ignore

        # Mode membership only gates *starting* a new trigger. Once already
        # TRIGGERED/PENDING, any subsequent sensor is allowed to shorten the
        # countdown regardless of its own mode list - a second sensor
        # tripping during an active sequence is significant on its own
        # merits, and re-litigating membership here isn't worth the
        # complexity for what's already a fast-moving safety path.
        mode_membership = options.get(CONF_MODES)
        if armed and mode_membership is not None and display not in mode_membership:
            return

        mode = display if armed else self._fsm.previous_state
        entry_delay = options.get(CONF_SENSOR_ENTRY_DELAY)
        if entry_delay is None:
            entry_delay = self._mode_config(mode).get(
                CONF_ENTRY_TIME, DEFAULT_ENTRY_TIME
            )

        if display in mid_sequence:
            # A second sensor mid-PENDING can pull the deadline in; one that
            # arrives after the siren has already started (display is
            # already TRIGGERED, so pending_until is already in the past)
            # is a safe no-op - shorten_pending never moves a deadline
            # earlier than "now".
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
