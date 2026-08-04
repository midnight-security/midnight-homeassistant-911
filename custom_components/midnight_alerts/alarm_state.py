"""Pure state-derivation math for a Midnight Alarm area.

Kept free of any Entity/AlarmControlPanelEntity import so it can be unit
tested with plain datetime values and no `hass` fixture at all.

Mirrors homeassistant.components.manual's read-time derivation: ARMING and
PENDING are never stored as their own state, only derived by comparing a
timestamp against the current time. `alarm_control_panel.py` owns all the
`hass`-facing side effects (scheduling callbacks, writing state, reading
config) - this module only computes what should be displayed right now,
and how the FSM should look afterward.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from homeassistant.components.alarm_control_panel import AlarmControlPanelState

ARM_MODES = (
    AlarmControlPanelState.ARMED_AWAY,
    AlarmControlPanelState.ARMED_HOME,
    AlarmControlPanelState.ARMED_NIGHT,
    AlarmControlPanelState.ARMED_VACATION,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
)


@dataclass(frozen=True)
class AreaFsm:
    """Settled state plus whatever in-flight transition deadlines apply."""

    settled_state: AlarmControlPanelState = AlarmControlPanelState.DISARMED
    previous_state: AlarmControlPanelState | None = None
    arming_until: datetime | None = None
    pending_until: datetime | None = None
    trigger_until: datetime | None = None
    disarm_after_trigger: bool = False
    held_open: bool = False
    armed_with_override: bool = False


def display_state(
    fsm: AreaFsm, now: datetime
) -> tuple[AlarmControlPanelState, AreaFsm]:
    """Return the state to show right now, and the FSM after any auto-revert.

    The only mutation this performs - reverting a TRIGGERED area whose
    trigger_until has passed - mirrors `manual`'s own `alarm_state` property,
    which has the same side effect for the same reason (nothing else polls
    this entity to notice the deadline has passed).
    """
    if fsm.settled_state in ARM_MODES and fsm.arming_until and (
        now < fsm.arming_until or fsm.held_open
    ):
        return AlarmControlPanelState.ARMING, fsm

    if fsm.settled_state == AlarmControlPanelState.TRIGGERED:
        if fsm.pending_until and now < fsm.pending_until:
            return AlarmControlPanelState.PENDING, fsm
        if fsm.trigger_until and now < fsm.trigger_until:
            return AlarmControlPanelState.TRIGGERED, fsm
        reverted = (
            AlarmControlPanelState.DISARMED
            if fsm.disarm_after_trigger or fsm.previous_state is None
            else fsm.previous_state
        )
        return reverted, replace(
            fsm,
            settled_state=reverted,
            arming_until=None,
            pending_until=None,
            trigger_until=None,
        )

    return fsm.settled_state, fsm


def start_arming(
    fsm: AreaFsm,
    *,
    mode: AlarmControlPanelState,
    now: datetime,
    exit_time: int,
    override: bool = False,
) -> AreaFsm:
    """Begin arming into `mode`, with an exit-delay countdown if configured.

    `override` marks this as armed with an override-code PIN: sensors that
    would otherwise hold or abort the arm (arm_on_close, use_exit_delay)
    are bypassed for the life of this armed session.
    """
    deadline = now + timedelta(seconds=exit_time) if exit_time else None
    return replace(
        fsm,
        previous_state=fsm.settled_state,
        settled_state=mode,
        arming_until=deadline,
        pending_until=None,
        trigger_until=None,
        held_open=False,
        armed_with_override=override,
    )


def abort_arming(fsm: AreaFsm) -> AreaFsm:
    """A sensor without use_exit_delay opened mid-countdown - abort immediately."""
    return replace(
        fsm,
        settled_state=fsm.previous_state or AlarmControlPanelState.DISARMED,
        arming_until=None,
        held_open=False,
        armed_with_override=False,
    )


def hold_for_close(fsm: AreaFsm) -> AreaFsm:
    """Exit delay elapsed but an arm_on_close sensor is still open - keep waiting.

    Displays as ARMING indefinitely (no new deadline) until `release_hold`
    is called once that sensor closes.
    """
    return replace(fsm, held_open=True)


def release_hold(fsm: AreaFsm, *, now: datetime) -> AreaFsm:
    """All arm_on_close sensors have closed - finish arming immediately."""
    return replace(fsm, held_open=False, arming_until=now)


def start_trigger(
    fsm: AreaFsm,
    *,
    now: datetime,
    entry_delay: int,
    trigger_time: int,
    disarm_after_trigger: bool,
) -> AreaFsm:
    """A sensor tripped (or alarm_trigger was called) - start the PENDING/TRIGGERED window."""
    previous = (
        fsm.previous_state
        if fsm.settled_state == AlarmControlPanelState.TRIGGERED
        else fsm.settled_state
    )
    pending_until = now + timedelta(seconds=entry_delay) if entry_delay else now
    trigger_until = pending_until + timedelta(seconds=trigger_time)
    return replace(
        fsm,
        previous_state=previous,
        settled_state=AlarmControlPanelState.TRIGGERED,
        pending_until=pending_until,
        trigger_until=trigger_until,
        disarm_after_trigger=disarm_after_trigger,
    )


def shorten_pending(fsm: AreaFsm, *, now: datetime, entry_delay: int) -> AreaFsm:
    """A second, faster-delay sensor tripped mid-PENDING - pull the deadline in.

    Never lengthens an existing deadline, only shortens it, mirroring Alarmo's
    own timer-shortening behavior.
    """
    if fsm.settled_state != AlarmControlPanelState.TRIGGERED or not fsm.pending_until:
        return fsm
    candidate = now + timedelta(seconds=entry_delay) if entry_delay else now
    if candidate >= fsm.pending_until:
        return fsm
    shift = fsm.pending_until - candidate
    trigger_until = fsm.trigger_until - shift if fsm.trigger_until else None
    return replace(fsm, pending_until=candidate, trigger_until=trigger_until)


def disarm() -> AreaFsm:
    """Disarm always resets to a clean, fully-settled DISARMED FSM."""
    return AreaFsm()
