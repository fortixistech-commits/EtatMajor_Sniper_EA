"""Simulation clock.

The replay engine never reads the wall clock: every decision and execution is
timestamped by a :class:`SimClock` driven by the dataset itself. This is the
foundation of the reproducibility guarantee of Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimClock:
    """A monotonic, fully deterministic simulated clock (nanosecond precision)."""

    now_ns: int = 0

    def advance_to(self, ts_ns: int) -> int:
        """Move the clock forward to ``ts_ns``.

        Moving backwards is refused: the replay must never revisit a past
        timestamp, otherwise the ordering guarantee would be void.
        """
        if ts_ns < self.now_ns:
            raise ValueError(
                f"simulation clock cannot move backwards: {ts_ns} < {self.now_ns}"
            )
        return SimClock(now_ns=ts_ns)

    def now(self) -> int:
        """Current simulated timestamp in nanoseconds."""
        return self.now_ns


def ns_to_iso(ts_ns: int) -> str:
    """Convert a nanosecond epoch timestamp to an ISO-8601 UTC string."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).isoformat()
