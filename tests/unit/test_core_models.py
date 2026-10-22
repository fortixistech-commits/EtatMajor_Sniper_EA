"""Tests des modeles metier du socle (Mission 1).

Les invariants testes ici sont ceux qui rendent un plan de mission, une
intention ou un etat de compte **exploitables** : un plan sans invalidation
est refuse, une donnee perimee n'autorise pas une decision, une identite de
session est deterministe.
"""

from __future__ import annotations

import pytest

from etatmajor.core.models import (
    AccountState,
    AuditEvent,
    ChallengeState,
    ExecutionEvent,
    MarketSnapshot,
    MarketTick,
    MissionPlan,
    OrderResult,
    PortfolioState,
    TradeIntent,
)
from etatmajor.core.session import build_session_identity
from etatmajor.core.types import OrderSide, OrderStatus, OrderType
from etatmajor.core.models import DataQuality


def make_plan(**kwargs) -> MissionPlan:
    defaults = dict(
        plan_id="PLAN-1",
        strategy_id="demo",
        strategy_version="1.0.0",
        symbol="EURUSD",
        timeframe="1m",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_ts_ns=1_767_571_260_000_000_000,
        quantity=10_000.0,
        entry_price=1.10000,
        stop_price=1.09900,
        risk_amount=10.0,
        invalidation_reason="invalidation sous le dernier plus bas",
        rationale="plan de test",
    )
    defaults.update(kwargs)
    return MissionPlan(**defaults)


# --- MissionPlan ----------------------------------------------------------
def test_a_complete_plan_is_accepted():
    plan = make_plan()
    assert plan.risk_per_unit == pytest.approx(0.001)
    assert plan.reward_risk_ratio is None


def test_a_plan_without_invalidation_is_refused():
    with pytest.raises(ValueError) as excinfo:
        make_plan(invalidation_reason="")
    assert "invalidation" in str(excinfo.value)


def test_a_plan_without_positive_risk_is_refused():
    with pytest.raises(ValueError):
        make_plan(risk_amount=0.0)


def test_a_long_plan_requires_the_stop_below_the_entry():
    with pytest.raises(ValueError):
        make_plan(stop_price=1.10100)


def test_a_short_plan_requires_the_stop_above_the_entry():
    with pytest.raises(ValueError):
        make_plan(side=OrderSide.SELL, stop_price=1.09900)


def test_a_long_target_must_be_above_the_entry():
    with pytest.raises(ValueError):
        make_plan(target_price=1.09900)


def test_the_reward_risk_ratio_accounts_for_the_costs():
    plan = make_plan(target_price=1.10300, estimated_costs=10.0)
    # gain brut 0.003, moins 0.001 de cout par unite, sur un risque de 0.001
    assert plan.reward_risk_ratio == pytest.approx(2.0)


def test_an_expired_plan_is_detected():
    plan = make_plan(expires_ts_ns=1_767_571_260_000_000_000)
    assert plan.is_expired(1_767_571_261_000_000_000) is True
    assert plan.is_expired(1_767_571_259_000_000_000) is False


# --- TradeIntent ----------------------------------------------------------
def test_an_intention_carries_the_plan_without_the_risk_limits():
    plan = make_plan()
    intent = TradeIntent(intent_id="INT-1", plan=plan, decision_ts_ns=1)
    assert intent.symbol == "EURUSD"
    assert intent.side is OrderSide.BUY
    assert intent.quantity == 10_000.0
    assert intent.reference_price == 1.10000
    assert intent.notional == pytest.approx(11_000.0)


# --- MarketSnapshot / MarketTick -----------------------------------------
def test_a_fresh_snapshot_authorises_a_decision():
    snapshot = MarketSnapshot(
        symbol="EURUSD",
        ts_ns=1,
        bid=1.10000,
        ask=1.10010,
        last_price=1.10005,
        quality=DataQuality.FRESH,
        data_age_ns=1_000_000,
        max_data_age_ns=5_000_000,
    )
    assert snapshot.spread == pytest.approx(0.00010)
    assert snapshot.is_fresh is True


def test_a_stale_snapshot_blocks_a_decision():
    snapshot = MarketSnapshot(
        symbol="EURUSD",
        ts_ns=1,
        bid=1.10000,
        ask=1.10010,
        last_price=1.10005,
        quality=DataQuality.FRESH,
        data_age_ns=60_000_000_000,
        max_data_age_ns=5_000_000,
    )
    assert snapshot.is_fresh is False


def test_a_snapshot_of_unknown_quality_is_never_fresh():
    snapshot = MarketSnapshot(
        symbol="EURUSD", ts_ns=1, bid=1.1, ask=1.1, last_price=1.1
    )
    assert snapshot.is_fresh is False


def test_an_inverted_quote_is_refused():
    with pytest.raises(ValueError):
        MarketSnapshot(symbol="EURUSD", ts_ns=1, bid=1.2, ask=1.1, last_price=1.15)
    with pytest.raises(ValueError):
        MarketTick(symbol="EURUSD", ts_ns=1, bid=1.2, ask=1.1)


# --- OrderResult / ExecutionEvent / AuditEvent ---------------------------
def test_an_order_result_exposes_its_outcome():
    result = OrderResult(
        order_id="O-1",
        client_order_id="O-1",
        symbol="EURUSD",
        status=OrderStatus.FILLED,
        ts_ns=1,
        filled_quantity=10_000.0,
        average_price=1.10000,
        commission=0.7,
    )
    assert result.is_filled is True
    assert result.is_rejected is False


def test_an_execution_event_is_serialisable():
    event = ExecutionEvent(
        ts_ns=1, kind="FILL", symbol="EURUSD", order_id="O-1", side=OrderSide.BUY
    )
    assert event.to_dict()["side"] == "BUY"


def test_an_audit_event_is_serialisable():
    event = AuditEvent(ts_ns=1, actor="risk-governor", action="REFUSE", reason="x")
    assert event.to_dict()["action"] == "REFUSE"


# --- AccountState / PortfolioState ---------------------------------------
def test_the_account_state_exposes_the_drawdown():
    account = AccountState(
        account_id="ACCOUNT-001",
        currency="USD",
        balance=100_000.0,
        equity=99_500.0,
        ts_ns=1,
    )
    assert account.drawdown_amount == pytest.approx(500.0)


def test_the_portfolio_state_counts_open_positions():
    portfolio = PortfolioState(
        ts_ns=1,
        positions=({"symbol": "EURUSD", "quantity": 10_000.0}, {"symbol": "GBPUSD", "quantity": 0.0}),
    )
    assert portfolio.open_positions == 1


# --- ChallengeState -------------------------------------------------------
def test_only_passed_and_failed_are_conclusive():
    assert ChallengeState.PASSED.is_conclusive is True
    assert ChallengeState.FAILED.is_conclusive is True
    for state in (
        ChallengeState.READY,
        ChallengeState.RUNNING,
        ChallengeState.INVALID,
        ChallengeState.REVIEW_REQUIRED,
    ):
        assert state.is_conclusive is False


# --- identite de session --------------------------------------------------
def test_the_session_identity_is_deterministic():
    kwargs = dict(
        strategy_id="demo",
        strategy_version="1.0.0",
        config_fingerprint="cfg",
        dataset_fingerprint="data",
        created_ts_ns=1_767_571_200_000_000_000,
        code_version="etatmajor/0.2.0",
    )
    first = build_session_identity(**kwargs)
    second = build_session_identity(**kwargs)
    assert first.session_id == second.session_id
    assert first.session_id.startswith("S-")


def test_the_session_identity_changes_with_its_inputs():
    base = dict(
        strategy_id="demo",
        strategy_version="1.0.0",
        config_fingerprint="cfg",
        dataset_fingerprint="data",
        created_ts_ns=1,
    )
    first = build_session_identity(**base)
    other_dataset = build_session_identity(**{**base, "dataset_fingerprint": "other"})
    other_config = build_session_identity(**{**base, "config_fingerprint": "other"})
    assert first.session_id != other_dataset.session_id
    assert first.session_id != other_config.session_id
