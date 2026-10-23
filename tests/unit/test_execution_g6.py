"""Phase 6 / G6 : contraintes broker et reconciliation d'execution."""

from __future__ import annotations

import pytest

from etatmajor.core.config import ExecutionConfig
from etatmajor.core.errors import ConfigurationError, ExecutionError
from etatmajor.core.events import Fill, Order
from etatmajor.core.types import OrderSide, OrderStatus, OrderType
from etatmajor.data.instruments import BrokerSymbolSpec, InstrumentSpec
from etatmajor.data.models import Bar
from etatmajor.execution.accounting import Portfolio
from etatmajor.execution.broker import SimulatedBroker
from etatmajor.execution.reconciliation import reconcile
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset


def _instrument(**overrides) -> InstrumentSpec:
    payload = {
        "instrument_id": "XAUUSD",
        "symbol": "XAUUSD",
        "asset_class": "metal",
        "quote_currency": "USD",
        "base_currency": "XAU",
        "price_precision": 2,
        "tick_size": 0.01,
        "min_quantity": 1.0,
        "quantity_step": 1.0,
        "max_quantity": 100.0,
        "tick_value": 1.0,
        "tick_value_currency": "USD",
        "contract_size": 100.0,
        "source": "test",
        "version": "1",
    }
    payload.update(overrides)
    spec = InstrumentSpec(**payload)
    spec.validate()
    return spec


def _order(**kwargs) -> Order:
    defaults = dict(
        order_id="O-1",
        client_order_id="O-1",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10.0,
    )
    defaults.update(kwargs)
    return Order(**defaults)


BAR = Bar(
    ts_open_ns=1_767_571_200_000_000_000,
    ts_close_ns=1_767_571_260_000_000_000,
    open=2000.1234,
    high=2000.50,
    low=1999.50,
    close=2000.25,
    volume=100.0,
)


def test_broker_uses_broker_symbol_constraints():
    instrument = _instrument()
    broker_spec = BrokerSymbolSpec(
        broker_id="mt5",
        symbol="XAUUSD",
        instrument_id="XAUUSD",
        min_quantity=2.0,
        quantity_step=2.0,
        max_quantity=20.0,
    )
    broker = SimulatedBroker(
        ExecutionConfig(min_quantity=0.01, quantity_step=0.01),
        instrument=instrument,
        broker_spec=broker_spec,
    )
    assert broker.submit(_order(quantity=1.0), 1).status is OrderStatus.REJECTED
    assert broker.submit(_order(order_id="O-2", quantity=3.0), 1).status is OrderStatus.REJECTED
    assert broker.submit(_order(order_id="O-3", quantity=2.0), 1).status is OrderStatus.ACCEPTED
    assert broker.submit(_order(order_id="O-4", quantity=22.0), 1).status is OrderStatus.REJECTED


def test_instrument_constraints_are_used_without_a_broker_mapping():
    broker = SimulatedBroker(ExecutionConfig(), instrument=_instrument())
    assert broker.submit(_order(quantity=0.5), 1).status is OrderStatus.REJECTED
    assert broker.submit(_order(order_id="O-2", quantity=10.0), 1).status is OrderStatus.ACCEPTED


def test_commission_uses_the_instrument_contract_size():
    broker = SimulatedBroker(
        ExecutionConfig(
            spread_price=0.0,
            commission_per_lot_per_side=7.0,
            lot_size=1.0,
        ),
        instrument=_instrument(),
    )
    broker.submit(_order(quantity=10.0), 1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "XAUUSD")
    assert broker.fills[0].commission == pytest.approx(10.0 / 100.0 * 7.0)


def test_unaligned_limit_prices_are_rejected():
    broker = SimulatedBroker(ExecutionConfig(), instrument=_instrument())
    bad = broker.submit(
        _order(order_type=OrderType.LIMIT, limit_price=2000.005), 1
    )
    assert bad.status is OrderStatus.REJECTED
    assert "not aligned" in bad.reason
    good = broker.submit(
        _order(order_id="O-2", order_type=OrderType.LIMIT, limit_price=2000.00), 1
    )
    assert good.status is OrderStatus.ACCEPTED


def test_fill_prices_are_rounded_to_the_instrument_precision():
    broker = SimulatedBroker(ExecutionConfig(), instrument=_instrument())
    broker.submit(_order(quantity=10.0), 1)
    broker.on_bar_open(BAR, BAR.ts_open_ns, "XAUUSD")
    assert broker.fills[0].price == pytest.approx(2000.12)


def test_broker_refuses_a_mismatched_instrument_mapping():
    broker_spec = BrokerSymbolSpec(
        broker_id="mt5",
        symbol="XAUUSD",
        instrument_id="EURUSD",
        min_quantity=1.0,
        quantity_step=1.0,
    )
    with pytest.raises(ConfigurationError, match="maps to"):
        SimulatedBroker(ExecutionConfig(), instrument=_instrument(), broker_spec=broker_spec)


def _clean_records():
    order = _order(quantity=100.0, status=OrderStatus.FILLED)
    order.filled_quantity = 100.0
    order.average_fill_price = 1.10
    fill = Fill(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=100.0,
        price=1.10,
        commission=1.0,
        ts_ns=10,
    )
    portfolio = Portfolio(10_000.0)
    portfolio.apply_fill(fill)
    portfolio.mark("XAUUSD", 1.11)
    return [order], [fill], portfolio


def test_a_clean_record_reconciles():
    orders, fills, portfolio = _clean_records()
    report = reconcile(orders, fills, portfolio)
    assert report.reconciled is True
    assert report.orders == 1
    assert report.fills == 1
    assert report.filled_orders == 1
    assert report.to_dict()["issues"] == []


def test_an_orphan_fill_is_detected():
    orders, fills, portfolio = _clean_records()
    orphan = Fill(
        order_id="O-UNKNOWN",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        quantity=1.0,
        price=1.10,
        commission=0.0,
        ts_ns=11,
    )
    portfolio.apply_fill(orphan)
    report = reconcile(orders, [*fills, orphan], portfolio)
    assert report.reconciled is False
    assert "ORPHAN_FILL" in {issue.code for issue in report.issues}


def test_a_position_divergence_is_detected():
    orders, fills, portfolio = _clean_records()
    portfolio.position("XAUUSD").quantity = 50.0
    report = reconcile(orders, fills, portfolio)
    assert "POSITION_MISMATCH" in {issue.code for issue in report.issues}


def test_a_fee_divergence_is_detected():
    orders, fills, portfolio = _clean_records()
    portfolio.fees += 1.0
    report = reconcile(orders, fills, portfolio)
    codes = {issue.code for issue in report.issues}
    assert "FEE_MISMATCH" in codes
    assert "CASH_INVARIANT" in codes


def test_a_realised_pnl_divergence_is_detected():
    orders, fills, portfolio = _clean_records()
    portfolio.realized_pnl += 5.0
    report = reconcile(orders, fills, portfolio)
    assert "REALIZED_PNL_MISMATCH" in {issue.code for issue in report.issues}


def test_a_duplicate_order_id_is_detected():
    orders, fills, portfolio = _clean_records()
    report = reconcile([*orders, orders[0]], fills, portfolio)
    assert "DUPLICATE_ORDER_ID" in {issue.code for issue in report.issues}


def test_a_filled_order_with_a_wrong_volume_is_detected():
    orders, fills, portfolio = _clean_records()
    orders[0].quantity = 200.0
    report = reconcile(orders, fills, portfolio)
    assert "ORDER_VOLUME_MISMATCH" in {issue.code for issue in report.issues}


def test_a_non_filled_order_with_fills_is_detected():
    orders, fills, portfolio = _clean_records()
    orders[0].status = OrderStatus.ACCEPTED
    report = reconcile(orders, fills, portfolio)
    assert "ORDER_STATUS_MISMATCH" in {issue.code for issue in report.issues}


def test_the_replay_engine_publishes_a_reconciliation_section():
    config = make_config(commission_per_lot_per_side=1.0, lot_size=100_000.0)
    dataset = make_dataset([1.1000, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050])
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=10_000.0,
        entry_index=2,
        exit_index=4,
    )
    result = ReplayEngine(dataset=dataset, config=config, strategy=strategy).run()
    assert result.report["reconciliation"]["reconciled"] is True
    assert any(
        entry.type == "RECONCILIATION" for entry in result.journal.entries
    )


def test_the_replay_engine_refuses_an_unreconciled_execution(monkeypatch):
    from etatmajor.execution.reconciliation import (
        ReconciliationIssue,
        ReconciliationReport,
    )

    def failed_reconcile(*args, **kwargs):
        return ReconciliationReport(
            orders=0,
            fills=0,
            filled_orders=0,
            fees=0.0,
            issues=(ReconciliationIssue("TEST", "injected mismatch"),),
        )

    monkeypatch.setattr("etatmajor.replay.engine.reconcile", failed_reconcile)
    config = make_config()
    dataset = make_dataset([1.1000, 1.1010, 1.1020, 1.1030])
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=10_000.0,
        entry_index=1,
        exit_index=2,
    )
    engine = ReplayEngine(dataset=dataset, config=config, strategy=strategy)
    with pytest.raises(ExecutionError, match="reconciliation failed"):
        engine.run()

def test_the_replay_engine_wires_instrument_constraints_into_the_broker():
    instrument = _instrument(
        instrument_id="EURUSD",
        symbol="EURUSD",
        asset_class="forex",
        base_currency="EUR",
        quote_currency="USD",
        price_precision=5,
        tick_size=0.00001,
        min_quantity=20_000.0,
        quantity_step=1_000.0,
        max_quantity=1_000_000.0,
        contract_size=100_000.0,
    )
    config = make_config()
    dataset = make_dataset([1.1000, 1.1010, 1.1020, 1.1030, 1.1040])
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=10_000.0,
        entry_index=1,
        exit_index=3,
    )
    result = ReplayEngine(
        dataset=dataset, config=config, strategy=strategy, instrument=instrument
    ).run()
    assert result.report["rejections"]["broker_count"] == 2
    assert result.report["reconciliation"]["reconciled"] is True
