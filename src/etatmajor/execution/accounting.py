"""Portfolio accounting.

The portfolio is the single owner of the money. Orders, fills and positions are
booked here exactly once, which is what guarantees that commissions and PnL are
never counted twice.

Invariants (asserted in ``tests/unit/test_accounting.py``)
----------------------------------------------------------
* ``cash == initial_capital + realized_pnl - fees``
* ``equity == cash + unrealized_pnl``
* ``net_pnl == realized_pnl + unrealized_pnl - fees``
* a position has a zero quantity **or** a strictly positive average price.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.events import Fill, Position


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Read-only view of the portfolio exposed to strategies."""

    initial_capital: float
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    net_pnl: float
    positions: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def open_positions(self) -> int:
        return sum(1 for p in self.positions if abs(p["quantity"]) > 0.0)


class Portfolio:
    """Cash, positions and PnL of a single account."""

    def __init__(self, initial_capital: float, currency: str = "USD") -> None:
        self.initial_capital = float(initial_capital)
        self.currency = currency
        self.cash = float(initial_capital)
        self.realized_pnl = 0.0
        self.fees = 0.0
        self.positions: dict[str, Position] = {}
        self.mark_prices: dict[str, float] = {}
        self.trade_count = 0

    # -- positions ----------------------------------------------------
    def position(self, symbol: str) -> Position:
        """Return (creating if needed) the position of ``symbol``."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def net_quantity(self, symbol: str) -> float:
        position = self.positions.get(symbol)
        return position.quantity if position else 0.0

    def open_symbols(self) -> list[str]:
        return [s for s, p in self.positions.items() if not p.is_flat]

    # -- booking ------------------------------------------------------
    def apply_fill(self, fill: Fill) -> Position:
        """Book a fill: position, realised PnL, fees and cash."""
        position = self.position(fill.symbol)
        signed = fill.quantity * fill.side.sign
        realised = 0.0

        if position.quantity == 0.0:
            position.quantity = signed
            position.average_price = fill.price
            position.opened_ts_ns = fill.ts_ns
        elif (position.quantity > 0) == (signed > 0):
            total = position.quantity + signed
            position.average_price = (
                abs(position.quantity) * position.average_price
                + fill.quantity * fill.price
            ) / abs(total)
            position.quantity = total
        else:
            old_quantity = position.quantity
            direction = 1.0 if old_quantity > 0 else -1.0
            closing = min(fill.quantity, abs(old_quantity))
            realised = closing * (fill.price - position.average_price) * direction
            position.realized_pnl += realised
            self.realized_pnl += realised
            self.cash += realised
            remaining = fill.quantity - closing
            new_quantity = old_quantity + signed
            position.quantity = new_quantity
            if abs(new_quantity) < 1e-12:
                position.quantity = 0.0
                position.average_price = 0.0
            elif (new_quantity > 0) != (direction > 0):
                # The position flipped: the residual opens at the fill price.
                position.average_price = fill.price

        position.commission += fill.commission
        position.last_price = fill.price
        self.fees += fill.commission
        self.cash -= fill.commission
        self.trade_count += 1
        return position

    def mark(self, symbol: str, price: float) -> None:
        """Update the mark price used to value open positions."""
        self.mark_prices[symbol] = price

    # -- valuation ----------------------------------------------------
    def compute_unrealized(self) -> float:
        """Unrealised PnL of every open position, valued at the mark prices."""
        total = 0.0
        for symbol, position in self.positions.items():
            if position.is_flat:
                continue
            mark = self.mark_prices.get(symbol, position.last_price)
            total += position.unrealized_pnl(mark)
        return total

    @property
    def unrealized_pnl(self) -> float:
        """Unrealised PnL of the portfolio (always recomputed from the marks)."""
        return self.compute_unrealized()

    @property
    def equity(self) -> float:
        return self.cash + self.compute_unrealized()

    @property
    def net_pnl(self) -> float:
        return self.equity - self.initial_capital

    def notional(self, symbol: str, price: float | None = None) -> float:
        """Absolute market value of the position of ``symbol``."""
        position = self.positions.get(symbol)
        if position is None or position.is_flat:
            return 0.0
        mark = price if price is not None else self.mark_prices.get(symbol, position.last_price)
        return abs(position.quantity) * mark

    def snapshot(self) -> PortfolioSnapshot:
        """Immutable snapshot handed to strategies and the risk authority."""
        unrealized = self.compute_unrealized()
        positions = tuple(
            {
                "symbol": symbol,
                "quantity": position.quantity,
                "average_price": position.average_price,
                "realized_pnl": position.realized_pnl,
                "commission": position.commission,
                "last_price": position.last_price,
            }
            for symbol, position in sorted(self.positions.items())
        )
        return PortfolioSnapshot(
            initial_capital=self.initial_capital,
            cash=self.cash,
            equity=self.cash + unrealized,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            fees=self.fees,
            net_pnl=self.cash + unrealized - self.initial_capital,
            positions=positions,
        )

    def to_dict(self) -> dict:
        snapshot = self.snapshot()
        return {
            "initial_capital": snapshot.initial_capital,
            "cash": snapshot.cash,
            "equity": snapshot.equity,
            "realized_pnl": snapshot.realized_pnl,
            "unrealized_pnl": snapshot.unrealized_pnl,
            "fees": snapshot.fees,
            "net_pnl": snapshot.net_pnl,
            "trade_count": self.trade_count,
            "positions": [dict(p) for p in snapshot.positions],
        }
