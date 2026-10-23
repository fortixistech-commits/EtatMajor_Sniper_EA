"""Execution reconciliation.

The broker owns orders and fills; the portfolio owns money and positions. This
module checks that the two views agree after a run:

* every fill references a known order and matches its side, symbol and volume;
* every filled order is fully accounted for, with a coherent average price;
* the net position of every symbol equals the signed sum of its fills;
* realised PnL, fees and cash obey the accounting invariants.

A mismatch is a hard failure: the replay engine refuses to publish a report
whose execution record cannot be reconciled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from ..core.events import Fill, Order
from ..core.types import OrderStatus
from .accounting import Portfolio

TOL = 1e-7


@dataclass(frozen=True)
class ReconciliationIssue:
    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ReconciliationReport:
    orders: int
    fills: int
    filled_orders: int
    fees: float
    issues: tuple[ReconciliationIssue, ...] = ()

    @property
    def reconciled(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "reconciled": self.reconciled,
            "orders": self.orders,
            "fills": self.fills,
            "filled_orders": self.filled_orders,
            "fees": self.fees,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def reconcile(
    orders: Iterable[Order],
    fills: Iterable[Fill],
    portfolio: Portfolio,
) -> ReconciliationReport:
    """Compare the broker record with the portfolio state."""
    order_list = list(orders)
    fill_list = list(fills)
    issues: list[ReconciliationIssue] = []

    by_id: dict[str, Order] = {}
    for order in order_list:
        if order.order_id in by_id:
            issues.append(
                ReconciliationIssue(
                    "DUPLICATE_ORDER_ID",
                    f"order id {order.order_id!r} appears more than once",
                )
            )
            continue
        by_id[order.order_id] = order

    filled_by_order: dict[str, float] = {}
    notional_by_order: dict[str, float] = {}
    signed_by_symbol: dict[str, float] = {}
    total_fees = 0.0

    for fill in fill_list:
        if not _finite_positive(fill.quantity):
            issues.append(
                ReconciliationIssue(
                    "INVALID_FILL",
                    f"fill for {fill.order_id!r} has invalid quantity {fill.quantity}",
                )
            )
            continue
        if not _finite_positive(fill.price):
            issues.append(
                ReconciliationIssue(
                    "INVALID_FILL",
                    f"fill for {fill.order_id!r} has invalid price {fill.price}",
                )
            )
            continue
        if not math.isfinite(fill.commission) or fill.commission < 0:
            issues.append(
                ReconciliationIssue(
                    "INVALID_FILL",
                    f"fill for {fill.order_id!r} has invalid commission "
                    f"{fill.commission}",
                )
            )
            continue

        order = by_id.get(fill.order_id)
        if order is None:
            issues.append(
                ReconciliationIssue(
                    "ORPHAN_FILL",
                    f"fill references unknown order {fill.order_id!r}",
                )
            )
        else:
            if fill.symbol != order.symbol:
                issues.append(
                    ReconciliationIssue(
                        "FILL_SYMBOL_MISMATCH",
                        f"fill {fill.order_id!r} symbol {fill.symbol!r} != "
                        f"order symbol {order.symbol!r}",
                    )
                )
            if fill.side is not order.side:
                issues.append(
                    ReconciliationIssue(
                        "FILL_SIDE_MISMATCH",
                        f"fill {fill.order_id!r} side {fill.side.value} != "
                        f"order side {order.side.value}",
                    )
                )

        filled_by_order[fill.order_id] = (
            filled_by_order.get(fill.order_id, 0.0) + fill.quantity
        )
        notional_by_order[fill.order_id] = (
            notional_by_order.get(fill.order_id, 0.0)
            + fill.quantity * fill.price
        )
        signed_by_symbol[fill.symbol] = (
            signed_by_symbol.get(fill.symbol, 0.0)
            + fill.quantity * fill.side.sign
        )
        total_fees += fill.commission

    filled_orders = 0
    for order in order_list:
        filled = filled_by_order.get(order.order_id, 0.0)
        if order.status is OrderStatus.FILLED:
            filled_orders += 1
            if abs(filled - order.quantity) > TOL:
                issues.append(
                    ReconciliationIssue(
                        "ORDER_VOLUME_MISMATCH",
                        f"order {order.order_id!r} filled {filled} of "
                        f"{order.quantity}",
                    )
                )
            if abs(order.filled_quantity - filled) > TOL:
                issues.append(
                    ReconciliationIssue(
                        "ORDER_FILL_FIELD_MISMATCH",
                        f"order {order.order_id!r} records filled_quantity "
                        f"{order.filled_quantity} but fills total {filled}",
                    )
                )
            if filled > 0:
                average = notional_by_order[order.order_id] / filled
                if abs(order.average_fill_price - average) > TOL:
                    issues.append(
                        ReconciliationIssue(
                            "ORDER_AVERAGE_PRICE_MISMATCH",
                            f"order {order.order_id!r} average price "
                            f"{order.average_fill_price} != {average}",
                        )
                    )
        elif filled > TOL:
            issues.append(
                ReconciliationIssue(
                    "ORDER_STATUS_MISMATCH",
                    f"order {order.order_id!r} has status "
                    f"{order.status.value} but {filled} filled",
                )
            )

    for symbol, position in portfolio.positions.items():
        expected = signed_by_symbol.get(symbol, 0.0)
        if abs(position.quantity - expected) > TOL:
            issues.append(
                ReconciliationIssue(
                    "POSITION_MISMATCH",
                    f"position {symbol!r} is {position.quantity} but fills imply "
                    f"{expected}",
                )
            )

    for symbol in signed_by_symbol:
        if symbol not in portfolio.positions:
            issues.append(
                ReconciliationIssue(
                    "MISSING_POSITION",
                    f"fills reference {symbol!r} but the portfolio has no position",
                )
            )

    if abs(portfolio.fees - total_fees) > TOL:
        issues.append(
            ReconciliationIssue(
                "FEE_MISMATCH",
                f"portfolio fees {portfolio.fees} != fill commissions {total_fees}",
            )
        )

    expected_realized = realized_pnl(fill_list)
    if abs(portfolio.realized_pnl - expected_realized) > TOL:
        issues.append(
            ReconciliationIssue(
                "REALIZED_PNL_MISMATCH",
                f"portfolio realised PnL {portfolio.realized_pnl} != "
                f"recomputed {expected_realized}",
            )
        )

    expected_cash = portfolio.initial_capital + portfolio.realized_pnl - portfolio.fees
    if abs(portfolio.cash - expected_cash) > TOL:
        issues.append(
            ReconciliationIssue(
                "CASH_INVARIANT",
                f"cash {portfolio.cash} != initial + realised - fees "
                f"{expected_cash}",
            )
        )

    if abs(portfolio.equity - (portfolio.cash + portfolio.unrealized_pnl)) > TOL:
        issues.append(
            ReconciliationIssue(
                "EQUITY_INVARIANT",
                "equity != cash + unrealised PnL",
            )
        )

    return ReconciliationReport(
        orders=len(order_list),
        fills=len(fill_list),
        filled_orders=filled_orders,
        fees=total_fees,
        issues=tuple(issues),
    )


def realized_pnl(fills: Iterable[Fill]) -> float:
    """Recompute realised PnL from fills with the portfolio's netting rules."""
    quantity = 0.0
    average = 0.0
    realised = 0.0
    for fill in sorted(fills, key=lambda f: f.ts_ns):
        signed = fill.quantity * fill.side.sign
        if quantity == 0.0:
            quantity = signed
            average = fill.price
        elif (quantity > 0.0) == (signed > 0.0):
            total = quantity + signed
            average = (
                abs(quantity) * average + fill.quantity * fill.price
            ) / abs(total)
            quantity = total
        else:
            direction = 1.0 if quantity > 0.0 else -1.0
            closing = min(fill.quantity, abs(quantity))
            realised += closing * (fill.price - average) * direction
            new_quantity = quantity + signed
            quantity = new_quantity
            if abs(new_quantity) < 1e-12:
                quantity = 0.0
                average = 0.0
            elif (new_quantity > 0.0) != (direction > 0.0):
                average = fill.price
    return realised


def _finite_positive(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0.0