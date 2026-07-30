"""Pure unit tests for alarm_state.py - no hass fixture needed."""
from datetime import datetime, timedelta, timezone

from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.midnight_alerts.alarm_state import (
    AreaFsm,
    abort_arming,
    disarm,
    display_state,
    hold_for_close,
    release_hold,
    shorten_pending,
    start_arming,
    start_trigger,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_disarmed_has_no_countdown():
    fsm = AreaFsm()
    state, new_fsm = display_state(fsm, NOW)
    assert state == AlarmControlPanelState.DISARMED
    assert new_fsm == fsm


def test_arming_then_armed():
    fsm = start_arming(
        AreaFsm(), mode=AlarmControlPanelState.ARMED_AWAY, now=NOW, exit_time=60
    )
    state, fsm = display_state(fsm, NOW + timedelta(seconds=30))
    assert state == AlarmControlPanelState.ARMING

    state, fsm = display_state(fsm, NOW + timedelta(seconds=61))
    assert state == AlarmControlPanelState.ARMED_AWAY


def test_zero_exit_time_arms_instantly():
    fsm = start_arming(
        AreaFsm(), mode=AlarmControlPanelState.ARMED_HOME, now=NOW, exit_time=0
    )
    state, _ = display_state(fsm, NOW)
    assert state == AlarmControlPanelState.ARMED_HOME


def test_abort_arming_reverts_to_previous_state():
    fsm = AreaFsm(settled_state=AlarmControlPanelState.DISARMED)
    fsm = start_arming(
        fsm, mode=AlarmControlPanelState.ARMED_AWAY, now=NOW, exit_time=60
    )
    fsm = abort_arming(fsm)
    state, _ = display_state(fsm, NOW)
    assert state == AlarmControlPanelState.DISARMED


def test_trigger_pending_then_triggered_then_auto_revert():
    fsm = AreaFsm(settled_state=AlarmControlPanelState.ARMED_AWAY)
    fsm = start_trigger(
        fsm, now=NOW, entry_delay=30, trigger_time=120, disarm_after_trigger=False
    )

    state, fsm = display_state(fsm, NOW + timedelta(seconds=10))
    assert state == AlarmControlPanelState.PENDING

    state, fsm = display_state(fsm, NOW + timedelta(seconds=31))
    assert state == AlarmControlPanelState.TRIGGERED

    state, fsm = display_state(fsm, NOW + timedelta(seconds=200))
    assert state == AlarmControlPanelState.ARMED_AWAY  # reverted to previous
    assert fsm.trigger_until is None


def test_trigger_disarm_after_trigger_reverts_to_disarmed():
    fsm = AreaFsm(settled_state=AlarmControlPanelState.ARMED_AWAY)
    fsm = start_trigger(
        fsm, now=NOW, entry_delay=0, trigger_time=60, disarm_after_trigger=True
    )
    state, _ = display_state(fsm, NOW + timedelta(seconds=61))
    assert state == AlarmControlPanelState.DISARMED


def test_shorten_pending_pulls_deadline_in():
    fsm = AreaFsm(settled_state=AlarmControlPanelState.ARMED_AWAY)
    fsm = start_trigger(
        fsm, now=NOW, entry_delay=60, trigger_time=120, disarm_after_trigger=False
    )
    original_trigger_until = fsm.trigger_until

    fsm = shorten_pending(fsm, now=NOW + timedelta(seconds=5), entry_delay=10)
    assert fsm.pending_until == NOW + timedelta(seconds=15)
    # trigger_until should shift by the same amount the deadline was pulled in
    assert fsm.trigger_until == original_trigger_until - timedelta(seconds=45)


def test_shorten_pending_never_lengthens():
    fsm = AreaFsm(settled_state=AlarmControlPanelState.ARMED_AWAY)
    fsm = start_trigger(
        fsm, now=NOW, entry_delay=10, trigger_time=120, disarm_after_trigger=False
    )
    original_pending_until = fsm.pending_until

    longer = shorten_pending(fsm, now=NOW, entry_delay=60)
    assert longer.pending_until == original_pending_until


def test_held_open_keeps_showing_arming_past_the_deadline():
    fsm = start_arming(
        AreaFsm(), mode=AlarmControlPanelState.ARMED_AWAY, now=NOW, exit_time=60
    )
    # exit delay has fully elapsed...
    state, fsm = display_state(fsm, NOW + timedelta(seconds=61))
    assert state == AlarmControlPanelState.ARMED_AWAY  # would normally finish arming

    # ...but a blocking sensor is still open, so we hold instead
    fsm = hold_for_close(fsm)
    state, fsm = display_state(fsm, NOW + timedelta(seconds=61))
    assert state == AlarmControlPanelState.ARMING

    # still holds arbitrarily far past the original deadline
    state, fsm = display_state(fsm, NOW + timedelta(hours=1))
    assert state == AlarmControlPanelState.ARMING


def test_release_hold_finishes_arming_immediately():
    fsm = start_arming(
        AreaFsm(), mode=AlarmControlPanelState.ARMED_AWAY, now=NOW, exit_time=60
    )
    fsm = hold_for_close(fsm)
    later = NOW + timedelta(minutes=5)

    fsm = release_hold(fsm, now=later)
    state, _ = display_state(fsm, later)
    assert state == AlarmControlPanelState.ARMED_AWAY


def test_abort_arming_clears_held_open():
    fsm = start_arming(
        AreaFsm(), mode=AlarmControlPanelState.ARMED_AWAY, now=NOW, exit_time=60
    )
    fsm = hold_for_close(fsm)
    fsm = abort_arming(fsm)
    assert fsm.held_open is False


def test_disarm_resets_everything():
    fsm = start_trigger(
        AreaFsm(settled_state=AlarmControlPanelState.ARMED_AWAY),
        now=NOW,
        entry_delay=30,
        trigger_time=120,
        disarm_after_trigger=False,
    )
    fsm = disarm()
    assert fsm == AreaFsm()
