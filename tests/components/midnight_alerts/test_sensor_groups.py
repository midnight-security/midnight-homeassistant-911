"""Pure unit tests for sensor_groups.py - no hass fixture needed."""

from datetime import UTC, datetime, timedelta

from custom_components.midnight_alerts.sensor_groups import (
    GroupScore,
    GroupTally,
    is_confirmed,
    is_score_confirmed,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


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


def test_single_trip_below_threshold_not_confirmed():
    score = GroupScore().record_trip(weight=5, decay_per_minute=1, now=NOW)
    assert is_score_confirmed(score, threshold=10) is False


def test_combined_weight_crossing_threshold_confirms():
    score = GroupScore().record_trip(weight=5, decay_per_minute=1, now=NOW)
    score = score.record_trip(
        weight=6, decay_per_minute=1, now=NOW + timedelta(seconds=5)
    )
    assert is_score_confirmed(score, threshold=10) is True


def test_decay_erases_a_stale_trips_contribution():
    # weight 5, decaying at 1/minute - after 10 minutes it's fully decayed
    score = GroupScore().record_trip(weight=5, decay_per_minute=1, now=NOW)
    score = score.record_trip(
        weight=4, decay_per_minute=1, now=NOW + timedelta(minutes=10)
    )
    # only the second trip's weight remains - not enough to confirm
    assert is_score_confirmed(score, threshold=5) is False


def test_decay_never_pushes_score_below_zero():
    score = GroupScore().record_trip(weight=2, decay_per_minute=1, now=NOW)
    score = score.record_trip(
        weight=0, decay_per_minute=1, now=NOW + timedelta(minutes=30)
    )
    assert score.score == 0.0


def test_group_tally_and_group_score_are_independent():
    tally = GroupTally().record_trip("binary_sensor.a", NOW)
    score = GroupScore().record_trip(weight=1, decay_per_minute=1, now=NOW)
    assert is_confirmed(tally, now=NOW, timeout=10, event_count=2) is False
    assert is_score_confirmed(score, threshold=10) is False
