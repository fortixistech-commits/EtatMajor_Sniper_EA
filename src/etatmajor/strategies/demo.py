"""Reference strategy used to exercise the order lifecycle.

This strategy exists **only** to validate the platform: it opens a position,
closes it, and can leave a deliberately unfillable limit order behind so that
the end-of-replay policy is exercised. It makes no claim of profitability and
must never be used as a trading strategy.
"""

from __future__ import annotations

from typing import Sequence

from ..core.events import Signal
from ..core.types import OrderType, SignalAction
from .base import StrategyContext


class DemoLifecycleStrategy:
    """Buy at ``entry_index``, sell at ``exit_index``."""

    strategy_id = "demo-lifecycle"
    strategy_version = "1.0.0"

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        quantity: float = 1_000.0,
        entry_index: int = 2,
        exit_index: int = 5,
        place_pending_limit: bool = False,
        pending_limit_offset: float = 0.50,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.quantity = quantity
        self.entry_index = entry_index
        self.exit_index = exit_index
        self.place_pending_limit = place_pending_limit
        self.pending_limit_offset = pending_limit_offset

    # -- lifecycle ----------------------------------------------------
    def on_start(self, context: StrategyContext) -> None:
        self.entry_sent = False
        self.exit_sent = False
        self.pending_sent = False

    def on_bar(self, context: StrategyContext) -> Sequence[Signal]:
        signals: list[Signal] = []

        if (
            self.place_pending_limit
            and not self.pending_sent
            and context.index == max(self.entry_index - 1, 0)
        ):
            # A limit far below the market: it must never be filled and must be
            # cancelled by the end-of-replay policy.
            signals.append(
                self._signal(
                    context,
                    action=SignalAction.BUY,
                    order_type=OrderType.LIMIT,
                    limit_price=round(context.bar.close - self.pending_limit_offset, 10),
                    reason="demo: unfillable limit order to exercise pending policy",
                )
            )
            self.pending_sent = True

        if not self.entry_sent and context.index == self.entry_index:
            signals.append(
                self._signal(
                    context,
                    action=SignalAction.BUY,
                    order_type=OrderType.MARKET,
                    reason="demo: scheduled market entry",
                )
            )
            self.entry_sent = True

        if not self.exit_sent and context.index == self.exit_index:
            signals.append(
                self._signal(
                    context,
                    action=SignalAction.SELL,
                    order_type=OrderType.MARKET,
                    reason="demo: scheduled market exit",
                )
            )
            self.exit_sent = True

        return signals

    def on_stop(self, context: StrategyContext) -> None:
        return None

    # -- helpers ------------------------------------------------------
    def _signal(
        self,
        context: StrategyContext,
        action: SignalAction,
        order_type: OrderType,
        reason: str,
        limit_price: float | None = None,
    ) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            symbol=self.symbol,
            timeframe=self.timeframe,
            decision_ts_ns=context.clock.now(),
            action=action,
            quantity=self.quantity,
            order_type=order_type,
            limit_price=limit_price,
            reason=reason,
            data_refs=(f"bar[{context.index}]",),
        )
