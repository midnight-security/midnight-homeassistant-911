"""N-of-M cross-zone sensor group confirmation.

Kept free of HA-entity imports so the tally math is unit-testable with
plain datetimes. A "sensor group" isn't a real HA entity, own database, or
automation rule - it's a narrow, fixed-purpose filter in front of ordinary
sensors, the same category as an entry/exit delay: an individual member's
trip is only treated as a real event once `event_count` members have
tripped within `timeout` seconds of each other, filtering out e.g. a single
pet-triggered motion sensor from counting as a confirmed intrusion.
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
