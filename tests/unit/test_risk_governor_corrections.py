"""Tests des corrections du RiskGovernor (phase C, C4).

Le governor doit raisonner sur l'exposition **agregee apres** l'operation,
distinguer une vraie reduction d'un retournement de position, refuser des
donnees invalides et rester fail-closed.
"""

from __future__ import annotations

import math

import pytest

from etatmajor.core.config import RiskConfig
from etatmajor.core.events import Fill
from etatmajor.core.types import OrderSide
from etatmajor.execution.accounting import Portfolio
from etatmajor.risk.governor import MinimalRiskGovernor, OrderRequest


def config(**overrides) -> RiskConfig:
    values = dict(
        max_position_quantity=1_000_000.0,
        max_order_notional=1_000_000_000.0,
        max_open_positions=5,
        max_leverage=1.0,
    )
    values.update(overrides)
    return RiskConfig(**values)


def portfolio_with(positions: list[tuple[str, float, float]]) -> Portfolio:
    capital = 100_000.0
    portfolio = Portfolio(capital)
    for symbol, quantity, price in positions:
        portfolio.apply_fill(
            Fill(
                order_id=f"O-{symbol}",
                symbol=symbol,
                side=OrderSide.BUY if quantity > 0 else OrderSide.SELL,
                quantity=abs(quantity),
                price=price,
                commission=0.0,
                ts_ns=1,
            )
        )
        portfolio.mark(symbol, price)
    return portfolio


def request(**overrides) -> OrderRequest:
    values = dict(
        symbol="EURUSD",
        side=OrderSide.BUY,
        quantity=10_000.0,
        reference_price=1.10000,
    )
    values.update(overrides)
    return OrderRequest(**values)


# --- exposition agregee ----------------------------------------------------
def test_the_projected_exposure_includes_existing_positions():
    governor = MinimalRiskGovernor(config(max_leverage=1.0))
    snapshot = portfolio_with([("GBPUSD", 50_000.0, 1.30000)]).snapshot()

    # Nouvel ordre : 60 000 EURUSD a 1,10 = 66 000. Exposition totale
    # projettee : 66 000 + 65 000 = 131 000 > equity 100 000.
    decision = governor.authorize(
        request(quantity=60_000.0, reference_price=1.10000), snapshot
    )

    assert decision.approved is False
    assert "projected gross exposure" in decision.reason


def test_an_order_that_fits_the_aggregate_limit_is_authorised():
    governor = MinimalRiskGovernor(config(max_leverage=2.0))
    snapshot = portfolio_with([("GBPUSD", 30_000.0, 1.30000)]).snapshot()

    decision = governor.authorize(
        request(quantity=50_000.0, reference_price=1.10000), snapshot
    )

    assert decision.approved is True


def test_a_partial_reduction_is_authorised_even_at_the_position_limit():
    governor = MinimalRiskGovernor(config(max_open_positions=1))
    snapshot = portfolio_with([("EURUSD", 10_000.0, 1.10000)]).snapshot()

    decision = governor.authorize(
        request(side=OrderSide.SELL, quantity=4_000.0), snapshot
    )

    assert decision.approved is True


def test_a_full_close_is_authorised_at_the_position_limit():
    governor = MinimalRiskGovernor(config(max_open_positions=1))
    snapshot = portfolio_with([("EURUSD", 10_000.0, 1.10000)]).snapshot()

    decision = governor.authorize(
        request(side=OrderSide.SELL, quantity=10_000.0), snapshot
    )

    assert decision.approved is True


def test_a_flip_is_not_treated_as_a_pure_reduction():
    governor = MinimalRiskGovernor(config(max_open_positions=1))
    snapshot = portfolio_with([("EURUSD", 10_000.0, 1.10000)]).snapshot()

    decision = governor.authorize(
        request(side=OrderSide.SELL, quantity=15_000.0), snapshot
    )

    assert decision.approved is False
    assert "max open positions" in decision.reason


def test_a_flip_cannot_bypass_the_aggregate_exposure_limit():
    # Exposition existante 10 000, equity 3 000, levier 1 : deja au-dessus.
    # Un retournement a 15 000 laisserait 5 000 bruts (moins qu'avant) mais
    # rouvre une position : il ne doit pas etre traite comme une reduction.
    governor = MinimalRiskGovernor(config(max_open_positions=5, max_leverage=1.0))
    portfolio = portfolio_with([("EURUSD", 10_000.0, 1.00000)])
    portfolio.cash = 3_000.0
    snapshot = portfolio.snapshot()

    decision = governor.authorize(
        request(side=OrderSide.SELL, quantity=15_000.0, reference_price=1.00000),
        snapshot,
    )

    assert decision.approved is False
    assert "exposure limit" in decision.reason


def test_an_add_on_at_the_position_limit_is_refused():
    governor = MinimalRiskGovernor(config(max_open_positions=1))
    snapshot = portfolio_with([("EURUSD", 10_000.0, 1.10000)]).snapshot()

    decision = governor.authorize(request(quantity=1_000.0), snapshot)

    assert decision.approved is False
    assert "max open positions" in decision.reason


# --- donnees invalides -----------------------------------------------------
@pytest.mark.parametrize(
    "bad_request",
    [
        request(quantity=float("nan")),
        request(quantity=float("inf")),
        request(quantity=-1.0),
        request(reference_price=0.0),
        request(reference_price=-1.0),
        request(reference_price=float("nan")),
        request(stop_price=float("nan")),
        request(stop_price=0.0),
    ],
)
def test_invalid_request_data_is_refused(bad_request):
    governor = MinimalRiskGovernor(config())
    decision = governor.authorize(bad_request, Portfolio(100_000.0).snapshot())
    assert decision.approved is False
    assert "invalid" in decision.reason


def test_an_empty_symbol_is_refused():
    governor = MinimalRiskGovernor(config())
    decision = governor.authorize(
        request(symbol="  "), Portfolio(100_000.0).snapshot()
    )
    assert decision.approved is False
    assert "invalid symbol" in decision.reason


# --- fail-closed -----------------------------------------------------------
def test_a_missing_mandatory_kill_switch_is_fail_closed(tmp_path):
    path = tmp_path / "kill.json"
    governor = MinimalRiskGovernor(
        config(kill_switch_path=str(path), kill_switch_required=True)
    )
    assert governor.kill_switch.engaged is True
    assert governor.kill_switch.state_error is True

    decision = governor.authorize(request(), Portfolio(100_000.0).snapshot())
    assert decision.approved is False
    assert "kill switch engaged" in decision.reason


def test_a_corrupted_kill_switch_is_fail_closed(tmp_path):
    path = tmp_path / "kill.json"
    path.write_text('{"engaged": "yes"}', encoding="utf-8")
    governor = MinimalRiskGovernor(config(kill_switch_path=str(path)))
    assert governor.kill_switch.engaged is True
    decision = governor.authorize(request(), Portfolio(100_000.0).snapshot())
    assert decision.approved is False


def test_required_kill_switch_configuration_requires_a_path():
    with pytest.raises(Exception):
        RiskConfig(kill_switch_required=True).validate()


def test_non_finite_equity_is_treated_as_no_exposure_allowance():
    governor = MinimalRiskGovernor(config(max_leverage=1.0))
    portfolio = Portfolio(100_000.0)
    portfolio.cash = math.nan
    decision = governor.authorize(request(), portfolio.snapshot())
    # Une equity non finie ne peut pas autoriser une exposition : le calcul
    # de limite est nul et l'ordre est refuse.
    assert decision.approved is False
