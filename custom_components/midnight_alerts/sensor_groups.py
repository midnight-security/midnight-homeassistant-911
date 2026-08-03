"""N-of-M cross-zone sensor group confirmation.

Kept free of HA-entity imports so the tally/score math is unit-testable
with plain datetimes. A "sensor group" isn't a real HA entity, own
database, or automation rule - it's a narrow, fixed-purpose filter in
front of ordinary sensors, the same category as an entry/exit delay.

Two independent confirmation models are supported:

- `GroupTally`/`is_confirmed`: a member's trip only counts once
  `event_count` members have tripped within `timeout` seconds of each
  other, filtering out e.g. a single pet-triggered motion sensor.
- `GroupScore`/`is_score_confirmed`: each member has its own weight: a
  trip adds that weight to a running score, the score decays over time,
  and confirmation fires once the score crosses a threshold - lets some
  sensors count for more than others instead of every member being
  equal.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta


@dataclass(frozen=True)
class GroupTally:
    """Recent trip timestamps for one sensor group's members."""

    trips: dict[str, datetime] = field(default_factory=dict)

    def record_trip(self, entity_id: str, now: datetime) -> "GroupTally":
        return replace(self, trips={**self.trips, entity_id: now})

    def confirmed_count(self, *, now: datetime, timeout: int) -> int:
        cutoff = now - timedelta(seconds=timeout)
        return sum(1 for ts in self.trips.values() if ts >= cutoff)


def is_confirmed(
    tally: GroupTally, *, now: datetime, timeout: int, event_count: int
) -> bool:
    """Whether enough members have tripped recently enough to count as one event."""
    return tally.confirmed_count(now=now, timeout=timeout) >= event_count


@dataclass(frozen=True)
class GroupScore:
    """Running weighted trip score for one sensor group, decaying over time."""

    score: float = 0.0
    last_update: datetime | None = None

    def record_trip(
        self, *, weight: float, decay_per_minute: float, now: datetime
    ) -> "GroupScore":
        decayed = self._decayed(now=now, decay_per_minute=decay_per_minute)
        return GroupScore(score=decayed + weight, last_update=now)

    def _decayed(self, *, now: datetime, decay_per_minute: float) -> float:
        if self.last_update is None:
            return self.score
        elapsed_minutes = (now - self.last_update).total_seconds() / 60
        return max(self.score - decay_per_minute * elapsed_minutes, 0.0)


def is_score_confirmed(score: GroupScore, *, threshold: float) -> bool:
    """Whether the group's current weighted score has crossed the threshold."""
    return score.score >= threshold
