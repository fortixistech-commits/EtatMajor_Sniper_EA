"""Portfolio accounting tests (invariants, no double counting)."""

from __future__ import annotations

import pytest

from etatmajor.core.events import Fill
from etatmajor.core.types import OrderSide
from etatmajor.execution.accounting import Portfolio


def make_fill(side, quantity, price, commission=0.0, ts_ns=1, order_id="O-1"):
    return Fill(
        order_id=order_id,
        symbol="EURUSD",
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        ts_ns=ts_ns,
    )


def test_initial_state():
    portfolio = Portfolio(100_000.0)
    assert portfolio.cash == 100_000.0
    assert portfolio.equity == 100_000.0
    assert portfolio.net_pnl == 0.0
    assert portfolio.realized_pnl == 0.0
    assert portfolio.fees == 0.0


def test_opening_a_long_position_marks_to_market():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.BUY, 10_000.0, 1.10000, commission=1.0))
    portfolio.mark("EURUSD", 1.10500)

    assert portfolio.net_quantity("EURUSD") == 10_000.0
    assert portfolio.position("EURUSD").average_price == pytest.approx(1.10000)
    assert portfolio.cash == pytest.approx(100_000.0 - 1.0)
    assert portfolio.unrealized_pnl == pytest.approx(10_000.0 * 0.00500)
    assert portfolio.equity == pytest.approx(100_000.0 - 1.0 + 50.0)
    assert portfolio.net_pnl == pytest.approx(49.0)


def test_closing_a_long_position_realises_the_pnl():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.BUY, 10_000.0, 1.10000, commission=1.0))
    portfolio.apply_fill(make_fill(OrderSide.SELL, 10_000.0, 1.10500, commission=1.0))

    assert portfolio.net_quantity("EURUSD") == 0.0
    assert portfolio.realized_pnl == pytest.approx(50.0)
    assert portfolio.fees == pytest.approx(2.0)
    assert portfolio.cash == pytest.approx(100_000.0 + 50.0 - 2.0)
    assert portfolio.equity == pytest.approx(100_000.0 + 48.0)
    assert portfolio.net_pnl == pytest.approx(48.0)


def test_average_price_is_weighted():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.BUY, 10_000.0, 1.10000))
    portfolio.apply_fill(make_fill(OrderSide.BUY, 30_000.0, 1.20000))
    assert portfolio.position("EURUSD").average_price == pytest.approx(
        (10_000.0 * 1.10000 + 30_000.0 * 1.20000) / 40_000.0
    )
    assert portfolio.net_quantity("EURUSD") == 40_000.0


def test_short_then_buy_realises_the_loss():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.SELL, 10_000.0, 1.10000))
    assert portfolio.net_quantity("EURUSD") == -10_000.0
    portfolio.apply_fill(make_fill(OrderSide.BUY, 10_000.0, 1.10500))
    assert portfolio.net_quantity("EURUSD") == 0.0
    assert portfolio.realized_pnl == pytest.approx(-50.0)


def test_partially_closing_keeps_the_average_price():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.BUY, 10_000.0, 1.10000))
    portfolio.apply_fill(make_fill(OrderSide.SELL, 4_000.0, 1.10500))
    assert portfolio.net_quantity("EURUSD") == 6_000.0
    assert portfolio.position("EURUSD").average_price == pytest.approx(1.10000)
    assert portfolio.realized_pnl == pytest.approx(20.0)


def test_flipping_a_position_resets_the_average_price():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.SELL, 10_000.0, 1.10000))
    portfolio.apply_fill(make_fill(OrderSide.BUY, 15_000.0, 1.10000))
    assert portfolio.net_quantity("EURUSD") == 5_000.0
    assert portfolio.position("EURUSD").average_price == pytest.approx(1.10000)


def test_accounting_invariants_hold_after_a_sequence():
    portfolio = Portfolio(100_000.0)
    fills = [
        make_fill(OrderSide.BUY, 10_000.0, 1.10000, commission=0.7, ts_ns=1, order_id="O-1"),
        make_fill(OrderSide.SELL, 4_000.0, 1.10500, commission=0.3, ts_ns=2, order_id="O-2"),
        make_fill(OrderSide.BUY, 2_000.0, 1.10200, commission=0.2, ts_ns=3, order_id="O-3"),
    ]
    for fill in fills:
        portfolio.apply_fill(fill)
    portfolio.mark("EURUSD", 1.10300)

    snapshot = portfolio.snapshot()
    assert snapshot.cash == pytest.approx(
        100_000.0 + snapshot.realized_pnl - snapshot.fees
    )
    assert snapshot.equity == pytest.approx(snapshot.cash + snapshot.unrealized_pnl)
    assert snapshot.net_pnl == pytest.approx(
        snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.fees
    )
    assert snapshot.fees == pytest.approx(1.2)
    assert snapshot.equity - 100_000.0 == pytest.approx(snapshot.net_pnl)


def test_commission_is_never_counted_twice():
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(make_fill(OrderSide.BUY, 10_000.0, 1.10000, commission=0.7))
    assert portfolio.fees == pytest.approx(0.7)
    assert portfolio.cash == pytest.approx(100_000.0 - 0.7)
    assert portfolio.position("EURUSD").commission == pytest.approx(0.7)
    # A second look at the snapshot must not add anything.
    portfolio.snapshot()
    portfolio.snapshot()
    assert portfolio.fees == pytest.approx(0.7)
