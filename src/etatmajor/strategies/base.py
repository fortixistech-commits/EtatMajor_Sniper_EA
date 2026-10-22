"""Strategy contract.

A strategy is a decision maker, not an execution engine. It receives the
information available at the simulated instant, observes the portfolio, and
returns structured proposals. It never books a fill, never touches the
portfolio and never bypasses the risk authority.

Anti-look-ahead guarantee
--------------------------
The context exposes only the bars whose closing time is at or before the
current simulated time. A strategy cannot reach the future: the engine builds
the visible slice of the dataset and hands it over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from ..core.clock import SimClock
from ..core.events import Fill, Signal
from ..data.models import Bar
from ..execution.accounting import PortfolioSnapshot


@dataclass(frozen=True)
class StrategyContext:
    """Everything a strategy is allowed to see at decision time."""

    index: int
    bar: Bar
    visible_bars: tuple[Bar, ...]
    clock: SimClock
    portfolio: PortfolioSnapshot
    recent_fills: tuple[Fill, ...] = field(default_factory=tuple)

    @property
    def close(self) -> float:
        return self.bar.close

    @property
    def close_price(self) -> float:
        return self.bar.close

    def last_bars(self, count: int) -> tuple[Bar, ...]:
        """The ``count`` last visible bars (never more than what is visible)."""
        return self.visible_bars[-count:] if count > 0 else ()

    def position_quantity(self, symbol: str) -> float:
        for position in self.portfolio.positions:
            if position["symbol"] == symbol:
                return float(position["quantity"])
        return 0.0


@runtime_checkable
class Strategy(Protocol):
    """Interface implemented by every strategy of the platform."""

    strategy_id: str
    strategy_version: str

    def on_start(self, context: StrategyContext) -> None:
        """Called once before the first bar."""
        ...

    def on_bar(self, context: StrategyContext) -> Sequence[Signal]:
        """Called at each bar close; returns zero or more proposals."""
        ...

    def on_stop(self, context: StrategyContext) -> None:
        """Called once after the last bar."""
        ...
