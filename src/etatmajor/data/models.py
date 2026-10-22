"""Canonical bar model.

Timestamps are stored as integer nanoseconds since the Unix epoch, in UTC. All
price fields are floats expressed in the instrument quote currency.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    """A single OHLC bar.

    Attributes
    ----------
    ts_open_ns:
        Timestamp of the first tick of the bar (the bar *opens* at that time).
    ts_close_ns:
        Timestamp at which the bar is closed and becomes observable. The
        duration ``ts_close_ns - ts_open_ns`` is the bar timeframe.
    """

    ts_open_ns: int
    ts_close_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def duration_ns(self) -> int:
        return self.ts_close_ns - self.ts_open_ns

    def to_dict(self) -> dict:
        return {
            "ts_open_ns": self.ts_open_ns,
            "ts_close_ns": self.ts_close_ns,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
