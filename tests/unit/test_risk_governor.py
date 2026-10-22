"""Risk authority tests (mandatory assertion 5)."""

from __future__ import annotations

import pytest

from etatmajor.core.config import RiskConfig
from etatmajor.core.types import OrderSide
from etatmajor.execution.accounting import Portfolio
from etatmajor.risk.governor import MinimalRiskGovernor, OrderRequest


def snapshot_with_open_position(quantity: float = 10_000.0):
    portfolio = Portfolio(100_000.0)
    from etatmajor.core.events import Fill

    portfolio.apply_fill(
        Fill(
            order_id="O-1",
            symbol="EURUSD",
            side=OrderSide.BUY,
            quantity=quantity,
            price=1.10000,
            commission=0.0,
            ts_ns=1,
        )
    )
    portfolio.mark("EURUSD", 1.10000)
    return portfolio.snapshot()


def test_authorises_a_conforming_request():
    governor = MinimalRiskGovernor(RiskConfig(max_position_quantity=10_000.0))
    request = OrderRequest("EURUSD", OrderSide.BUY, 10_000.0, 1.10000)
    decision = governor.authorize(request, Portfolio(100_000.0).snapshot())
    assert decision.approved is True


def test_refuses_a_quantity_above_the_limit():
    governor = MinimalRiskGovernor(RiskConfig(max_position_quantity=1_000.0))
    request = OrderRequest("EURUSD", OrderSide.BUY, 10_000.0, 1.10000)
    decision = governor.authorize(request, Portfolio(100_000.0).snapshot())
    assert decision.approved is False
    assert "exceeds the authorised maximum" in decision.reason


def test_refuses_a_notional_above_the_limit():
    governor = MinimalRiskGovernor(
        RiskConfig(max_position_quantity=1_000_000.0, max_order_notional=10_000.0)
    )
    request = OrderRequest("EURUSD", OrderSide.BUY, 10_000.0, 1.10000)
    decision = governor.authorize(request, Portfolio(100_000.0).snapshot())
    assert decision.approved is False
    assert "notional" in decision.reason


def test_refuses_when_trading_is_halted():
    governor = MinimalRiskGovernor(RiskConfig(trading_halted=True))
    request = OrderRequest("EURUSD", OrderSide.BUY, 1.0, 1.10000)
    decision = governor.authorize(request, Portfolio(100_000.0).snapshot())
    assert decision.approved is False
    assert "halted" in decision.reason


def test_refuses_a_new_position_when_the_position_limit_is_reached():
    governor = MinimalRiskGovernor(RiskConfig(max_open_positions=1))
    request = OrderRequest("EURUSD", OrderSide.BUY, 1.0, 1.10000)
    decision = governor.authorize(request, snapshot_with_open_position())
    assert decision.approved is False
    assert "max open positions" in decision.reason


def test_allows_an_order_that_reduces_an_existing_position():
    governor = MinimalRiskGovernor(RiskConfig(max_open_positions=1))
    request = OrderRequest("EURUSD", OrderSide.SELL, 1.0, 1.10000)
    decision = governor.authorize(request, snapshot_with_open_position())
    assert decision.approved is True


def test_refuses_a_non_positive_quantity():
    governor = MinimalRiskGovernor(RiskConfig())
    request = OrderRequest("EURUSD", OrderSide.BUY, 0.0, 1.10000)
    decision = governor.authorize(request, Portfolio(100_000.0).snapshot())
    assert decision.approved is False
    assert "strictly positive" in decision.reason


@pytest.mark.parametrize(
    "config",
    [
        RiskConfig(max_position_quantity=0.0),
        RiskConfig(max_order_notional=-1.0),
        RiskConfig(max_open_positions=-1),
    ],
)
def test_invalid_risk_configuration_is_refused(config):
    with pytest.raises(Exception):
        MinimalRiskGovernor(config)
