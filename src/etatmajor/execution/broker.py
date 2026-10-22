"""Simulated broker.

The broker owns the order lifecycle and the execution model. It never touches
the portfolio: it produces :class:`Fill` objects that the engine books.

Execution model (Phase 2)
-------------------------
* Market orders are filled at the **open of the next bar** after the bar that
  produced the signal. A signal is therefore never executed retroactively on
  its own bar.
* Limit orders fill when the bar range touches the limit price, at the limit
  price (plus adverse slippage).
* Stop orders trigger when the bar range touches the stop price. When the bar
  opens beyond the stop level the fill happens at the open (gap), otherwise at
  the stop price.
* Intra-bar ambiguity (a bar touching both a stop and a target) is not
  resolved: Phase 2 fills at most one order per bar, in submission order.
  This conservative rule is documented in ``docs/ARCHITECTURE.md``.
"""

from __future__ import annotations

import random

from ..core.config import ExecutionConfig
from ..core.events import Fill, Order
from ..core.types import OrderSide, OrderStatus, OrderType
from ..data.models import Bar


class SimulatedBroker:
    """Deterministic broker simulation (seeded, no network access)."""

    def __init__(self, config: ExecutionConfig, seed: int = 0) -> None:
        config.validate()
        self.config = config
        self._rng = random.Random(seed)
        self._order_seq = 0
        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self.pending: list[Order] = []
        self.reject_reasons: list[str] = []

    # -- helpers ------------------------------------------------------
    def _next_order_id(self) -> str:
        self._order_seq += 1
        return f"O-{self._order_seq:06d}"

    def new_order_id(self) -> str:
        """Allocate a deterministic order identifier."""
        return self._next_order_id()

    def _slippage(self) -> float:
        """Total adverse slippage for one fill."""
        slippage = self.config.slippage_price
        if self.config.slippage_random_max > 0:
            slippage += self._rng.uniform(0.0, self.config.slippage_random_max)
        return slippage

    def _commission(self, quantity: float) -> float:
        """Commission charged for one fill (entry and exit are charged apart)."""
        lots = quantity / self.config.lot_size if self.config.lot_size else quantity
        return (
            self.config.commission_per_lot_per_side * lots
            + self.config.commission_fixed_per_order
        )

    # -- order lifecycle ----------------------------------------------
    def submit(self, order: Order, ts_ns: int) -> Order:
        """Accept or reject a newly submitted order."""
        order.submit_ts_ns = ts_ns
        order.updated_ts_ns = ts_ns
        self.orders.append(order)

        reason = self._pre_trade_check(order)
        if reason is None and self.config.reject_probability > 0.0:
            if self._rng.random() < self.config.reject_probability:
                reason = "simulated broker rejection (configured probability)"

        if reason is not None:
            order.status = OrderStatus.REJECTED
            order.reason = reason
            self.reject_reasons.append(reason)
            return order

        order.status = OrderStatus.ACCEPTED
        self.pending.append(order)
        return order

    def _pre_trade_check(self, order: Order) -> str | None:
        if order.quantity <= 0:
            return "invalid quantity: must be strictly positive"
        if order.quantity < self.config.min_quantity:
            return (
                f"invalid quantity {order.quantity}: below broker minimum "
                f"{self.config.min_quantity}"
            )
        if order.quantity > self.config.max_quantity:
            return (
                f"invalid quantity {order.quantity}: above broker maximum "
                f"{self.config.max_quantity}"
            )
        if order.side is OrderSide.SELL and not self.config.allow_short:
            return "short selling is disabled by the broker configuration"
        if order.order_type is OrderType.LIMIT and order.limit_price is None:
            return "limit order without a limit price"
        if order.order_type is OrderType.STOP and order.stop_price is None:
            return "stop order without a stop price"
        return None

    def cancel(self, order: Order, ts_ns: int, reason: str = "") -> Order:
        """Cancel a pending order."""
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return order
        order.status = OrderStatus.CANCELLED
        order.updated_ts_ns = ts_ns
        order.reason = reason
        if order in self.pending:
            self.pending.remove(order)
        return order

    # -- execution ----------------------------------------------------
    def on_bar_open(self, bar: Bar, ts_ns: int, symbol: str) -> list[Fill]:
        """Process pending orders of ``symbol`` against a bar.

        Market orders are filled at the bar open. Limit and stop orders are
        checked against the bar range (and are filled at the bar open if the
        bar opens beyond their trigger level).
        """
        fills: list[Fill] = []
        for order in list(self.pending):
            if order.symbol != symbol:
                continue
            fill = self._maybe_fill(order, bar, ts_ns)
            if fill is not None:
                fills.append(fill)
                if order in self.pending:
                    self.pending.remove(order)
        return fills

    def execute_market(
        self, order: Order, bar: Bar, ts_ns: int
    ) -> Fill | None:
        """Immediately execute an accepted market order against ``bar``.

        Used by the end-of-replay closure policy with a synthetic bar whose
        open equals the last known close price.
        """
        if order.status is not OrderStatus.ACCEPTED:
            return None
        fill = self._maybe_fill(order, bar, ts_ns)
        if fill is not None and order in self.pending:
            self.pending.remove(order)
        return fill

    def _maybe_fill(self, order: Order, bar: Bar, ts_ns: int) -> Fill | None:
        if order.order_type is OrderType.MARKET:
            price = self._market_price_from(bar.open, order.side)
        elif order.order_type is OrderType.LIMIT:
            limit = float(order.limit_price or 0.0)
            if order.side is OrderSide.BUY:
                if bar.low > limit:
                    return None
                price = limit + self._slippage()
            else:
                if bar.high < limit:
                    return None
                price = limit - self._slippage()
        else:  # stop order
            stop = float(order.stop_price or 0.0)
            if order.side is OrderSide.BUY:
                if bar.high < stop:
                    return None
                base = bar.open if bar.open >= stop else stop
                price = self._market_price_from(base, OrderSide.BUY)
            else:
                if bar.low > stop:
                    return None
                base = bar.open if bar.open <= stop else stop
                price = self._market_price_from(base, OrderSide.SELL)

        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=round(price, 10),
            commission=round(self._commission(order.quantity), 10),
            ts_ns=ts_ns,
        )
        order.status = OrderStatus.FILLED
        order.updated_ts_ns = ts_ns
        order.filled_quantity = order.quantity
        order.average_fill_price = fill.price
        order.commission = fill.commission
        self.fills.append(fill)
        return fill

    def _market_price_from(self, base: float, side: OrderSide) -> float:
        half_spread = self.config.spread_price / 2.0
        slippage = self._slippage()
        if side is OrderSide.BUY:
            return base + half_spread + slippage
        return base - half_spread - slippage

    # -- introspection -------------------------------------------------
    def open_orders(self) -> list[Order]:
        return [
            o
            for o in self.orders
            if o.status in (OrderStatus.PENDING, OrderStatus.ACCEPTED)
        ]
