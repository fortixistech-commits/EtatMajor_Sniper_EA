"""Execution model tests: spread, slippage, commissions, rejects, lifecycle."""

from __future__ import annotations

import pytest

from etatmajor.core.config import ExecutionConfig
from etatmajor.core.events import Order
from etatmajor.core.types import OrderSide, OrderStatus, OrderType
from etatmajor.data.models import Bar
from etatmajor.execution.broker import SimulatedBroker

BAR = Bar(
    ts_open_ns=1_767_571_200_000_000_000,
    ts_close_ns=1_767_571_260_000_000_000,
    open=1.10000,
    high=1.10100,
    low=1.09900,
    close=1.10050,
    volume=1000.0,
)


def make_order(**kwargs) -> Order:
    defaults = dict(
        order_id="O-000001",
        client_order_id="O-000001",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100_000.0,
    )
    defaults.update(kwargs)
    return Order(**defaults)


def test_spread_is_applied_adversely_on_both_sides():
    config = ExecutionConfig(spread_price=0.00020, lot_size=100_000.0)
    broker = SimulatedBroker(config, seed=1)

    buy = broker.submit(make_order(order_id="O-1"), ts_ns=1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    sell = broker.submit(make_order(order_id="O-2", side=OrderSide.SELL), ts_ns=1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")

    assert broker.fills[0].price == pytest.approx(1.10000 + 0.00010)
    assert broker.fills[1].price == pytest.approx(1.10000 - 0.00010)


def test_fixed_slippage_is_applied_adversely():
    config = ExecutionConfig(spread_price=0.0, slippage_price=0.00005)
    broker = SimulatedBroker(config, seed=1)
    broker.submit(make_order(), ts_ns=1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert broker.fills[0].price == pytest.approx(1.10005)


def test_random_slippage_stays_within_its_bounds():
    config = ExecutionConfig(spread_price=0.0, slippage_price=0.0, slippage_random_max=0.00010)
    broker = SimulatedBroker(config, seed=7)
    for index in range(50):
        order = make_order(order_id=f"O-{index}")
        broker.submit(order, ts_ns=1)
        broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    for fill in broker.fills:
        assert 1.10000 <= fill.price <= 1.10010


def test_commission_is_charged_per_lot_and_per_side():
    config = ExecutionConfig(
        spread_price=0.0,
        commission_per_lot_per_side=7.0,
        lot_size=100_000.0,
    )
    broker = SimulatedBroker(config, seed=1)
    broker.submit(make_order(quantity=100_000.0), ts_ns=1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert broker.fills[0].commission == pytest.approx(7.0)

    broker2 = SimulatedBroker(config, seed=1)
    broker2.submit(make_order(quantity=50_000.0), ts_ns=1)
    broker2.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert broker2.fills[0].commission == pytest.approx(3.5)


def test_fixed_commission_is_added():
    config = ExecutionConfig(
        spread_price=0.0, commission_per_lot_per_side=7.0, commission_fixed_per_order=1.5, lot_size=100_000.0
    )
    broker = SimulatedBroker(config, seed=1)
    broker.submit(make_order(quantity=100_000.0), ts_ns=1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert broker.fills[0].commission == pytest.approx(8.5)


def test_broker_can_reject_an_order():
    config = ExecutionConfig(reject_probability=1.0)
    broker = SimulatedBroker(config, seed=1)
    order = broker.submit(make_order(), ts_ns=1)
    assert order.status is OrderStatus.REJECTED
    assert "rejection" in order.reason
    assert broker.open_orders() == []


def test_broker_rejects_invalid_quantity():
    config = ExecutionConfig(min_quantity=100.0)
    broker = SimulatedBroker(config, seed=1)
    order = broker.submit(make_order(quantity=1.0), ts_ns=1)
    assert order.status is OrderStatus.REJECTED
    assert "below broker minimum" in order.reason


def test_limit_order_fills_only_when_the_price_is_reached():
    config = ExecutionConfig(spread_price=0.0)
    broker = SimulatedBroker(config, seed=1)
    order = broker.submit(
        make_order(order_type=OrderType.LIMIT, limit_price=1.09950), ts_ns=1
    )
    assert order.status is OrderStatus.ACCEPTED
    fills = broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(1.09950)

    broker2 = SimulatedBroker(config, seed=1)
    broker2.submit(
        make_order(order_type=OrderType.LIMIT, limit_price=1.09000), ts_ns=1
    )
    assert broker2.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD") == []


def test_stop_order_is_not_triggered_when_the_level_is_not_reached():
    config = ExecutionConfig(spread_price=0.0)
    broker = SimulatedBroker(config, seed=1)
    broker.submit(make_order(order_type=OrderType.STOP, stop_price=1.10500), ts_ns=1)
    assert broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD") == []


def test_stop_order_triggers_on_the_stop_price():
    config = ExecutionConfig(spread_price=0.0)
    broker = SimulatedBroker(config, seed=1)
    broker.submit(make_order(order_type=OrderType.STOP, stop_price=1.10050), ts_ns=1)
    fills = broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(1.10050)


def test_stop_order_gap_is_filled_at_the_open():
    config = ExecutionConfig(spread_price=0.0)
    broker = SimulatedBroker(config, seed=1)
    broker.submit(make_order(order_type=OrderType.STOP, stop_price=1.09500), ts_ns=1)
    fills = broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
    assert len(fills) == 1
    # The bar opens above the stop level: the fill happens at the open.
    assert fills[0].price == pytest.approx(1.10000)


def test_cancelling_an_order_removes_it_from_the_pending_list():
    config = ExecutionConfig(spread_price=0.0)
    broker = SimulatedBroker(config, seed=1)
    order = broker.submit(make_order(order_type=OrderType.LIMIT, limit_price=1.0), ts_ns=1)
    broker.cancel(order, ts_ns=2, reason="operator")
    assert order.status is OrderStatus.CANCELLED
    assert broker.open_orders() == []
    assert broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD") == []


def test_broker_is_deterministic_for_a_given_seed():
    config = ExecutionConfig(spread_price=0.0, slippage_random_max=0.00010)
    prices = []
    for _ in range(2):
        broker = SimulatedBroker(config, seed=99)
        for index in range(10):
            broker.submit(make_order(order_id=f"O-{index}"), ts_ns=1)
            broker.on_bar_open(BAR, BAR.ts_open_ns, "EURUSD")
        prices.append([f.price for f in broker.fills])
    assert prices[0] == prices[1]
