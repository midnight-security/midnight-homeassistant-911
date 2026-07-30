"""Pure unit tests for sensor_groups.py - no hass fixture needed."""
from datetime import datetime, timedelta, timezone

from custom_components.midnight_alerts.sensor_groups import GroupTally, is_confirmed

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_single_trip_not_confirmed_for_2_of_2():
    tally = GroupTally().record_trip("binary_sensor.a", NOW)
    assert is_confirmed(tally, now=NOW, timeout=10, event_count=2) is False


def test_two_trips_within_timeout_confirms():
    tally = GroupTally().record_trip("binary_sensor.a", NOW)
    tally = tally.record_trip("binary_sensor.b", NOW + timedelta(seconds=5))
    assert (
        is_confirmed(tally, now=NOW + timedelta(seconds=5), timeout=10, event_count=2)
        is True
    )


def test_trips_outside_timeout_window_dont_count():
    tally = GroupTally().record_trip("binary_sensor.a", NOW)
    tally = tally.record_trip("binary_sensor.b", NOW + timedelta(seconds=20))
    # at t=20, sensor a's trip (t=0) is outside a 10s window - only 1 counts
    assert (
        is_confirmed(tally, now=NOW + timedelta(seconds=20), timeout=10, event_count=2)
        is False
    )


def test_same_sensor_retripping_doesnt_double_count():
    tally = GroupTally().record_trip("binary_sensor.a", NOW)
    tally = tally.record_trip("binary_sensor.a", NOW + timedelta(seconds=1))
    assert tally.confirmed_count(now=NOW + timedelta(seconds=1), timeout=10) == 1


def test_event_count_of_one_confirms_on_first_trip():
    tally = GroupTally().record_trip("binary_sensor.a", NOW)
    assert is_confirmed(tally, now=NOW, timeout=10, event_count=1) is True
