"""Tests des garde-fous du RiskGovernor (Mission 5).

Le governor est une barriere obligatoire : il refuse, il journalise, et il
ne peut etre contourne. Ces tests couvrent les limites aes seuils exacts,
l'arret d'urgence persistant et l'impossibilite de prendre un risque quand
le challenge l'interdit.
"""

from __future__ import annotations

import json

import pytest

from etatmajor.core.config import RiskConfig
from etatmajor.core.events import Fill
from etatmajor.core.types import OrderSide
from etatmajor.execution.accounting import Portfolio
from etatmajor.risk.governor import MinimalRiskGovernor, OrderRequest
from etatmajor.risk.killswitch import KillSwitch


def snapshot(equity: float = 100_000.0, quantity: float = 0.0):
    portfolio = Portfolio(equity)
    if quantity:
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


def base_config(**kwargs) -> RiskConfig:
    """Configuration permissive : chaque test n'ajoute que la limite qu'il etudie."""
    defaults = dict(
        max_position_quantity=1_000_000.0,
        max_order_notional=1_000_000_000.0,
        max_open_positions=5,
    )
    defaults.update(kwargs)
    return RiskConfig(**defaults)


def request(**kwargs) -> OrderRequest:
    defaults = dict(
        symbol="EURUSD", side=OrderSide.BUY, quantity=10_000.0, reference_price=1.10000
    )
    defaults.update(kwargs)
    return OrderRequest(**defaults)


# --- risque par operation -------------------------------------------------
def test_the_risk_amount_is_computed_from_the_stop():
    req = request(quantity=10_000.0, reference_price=1.10000, stop_price=1.09900)
    assert req.risk_amount == pytest.approx(10.0)
    assert req.notional == pytest.approx(11_000.0)


def test_a_request_without_stop_has_no_known_risk():
    assert request().risk_amount == 0.0


def test_a_trade_above_the_risk_limit_is_refused():
    # 10 000 unites x 0,00100 de distance = 10 USD de risque, pour un plafond de 5.
    governor = MinimalRiskGovernor(base_config(max_risk_per_trade=5.0))
    decision = governor.authorize(
        request(quantity=10_000.0, reference_price=1.10000, stop_price=1.09900),
        snapshot(),
    )
    assert decision.approved is False
    assert "risk amount" in decision.reason


def test_a_trade_below_the_risk_limit_is_authorised():
    governor = MinimalRiskGovernor(base_config(max_risk_per_trade=50.0))
    decision = governor.authorize(
        request(quantity=10_000.0, reference_price=1.10000, stop_price=1.09990),
        snapshot(),
    )
    assert decision.approved is True


def test_a_missing_stop_is_refused_when_the_profile_requires_one():
    governor = MinimalRiskGovernor(base_config(require_stop_loss=True))
    decision = governor.authorize(request(), snapshot())
    assert decision.approved is False
    assert "stop loss is required" in decision.reason


# --- exposition ------------------------------------------------------------
def test_the_exposure_is_capped_by_the_equity():
    governor = MinimalRiskGovernor(base_config(max_leverage=1.0))
    decision = governor.authorize(
        request(quantity=10_000.0, reference_price=1.10000), snapshot(equity=5_000.0)
    )
    assert decision.approved is False
    assert "exposure limit" in decision.reason


def test_an_exposure_within_the_leverage_is_authorised():
    # 11 000 de notionnel pour 10 000 d'equity et un levier de 2 : admis.
    governor = MinimalRiskGovernor(base_config(max_leverage=2.0))
    decision = governor.authorize(
        request(quantity=10_000.0, reference_price=1.10000), snapshot(equity=10_000.0)
    )
    assert decision.approved is True


# --- kill switch -----------------------------------------------------------
def test_an_engaged_kill_switch_refuses_everything(tmp_path):
    path = tmp_path / "kill_switch.json"
    switch = KillSwitch(path)
    switch.engage("manual emergency stop", ts_ns=1)
    governor = MinimalRiskGovernor(base_config(), kill_switch=switch)
    decision = governor.authorize(request(), snapshot())
    assert decision.approved is False
    assert "kill switch engaged" in decision.reason


def test_the_kill_switch_survives_a_restart(tmp_path):
    path = tmp_path / "kill_switch.json"
    KillSwitch(path).engage("crash during a trade", ts_ns=42)
    # Nouvel instance : l'etat est relu depuis le disque.
    reloaded = KillSwitch(path)
    assert reloaded.engaged is True
    assert "crash during a trade" in reloaded.state.reason
    assert reloaded.state.engaged_ts_ns == 42


def test_the_kill_switch_can_be_rearmed_explicitly(tmp_path):
    path = tmp_path / "kill_switch.json"
    switch = KillSwitch(path)
    switch.engage("incident", ts_ns=1)
    switch.reset("review completed")
    assert KillSwitch(path).engaged is False


def test_an_unreadable_kill_switch_file_fails_safe(tmp_path):
    path = tmp_path / "kill_switch.json"
    path.write_text("{not json", encoding="utf-8")
    switch = KillSwitch(path)
    assert switch.engaged is True
    assert "unreadable" in switch.state.reason


# --- audit -----------------------------------------------------------------
def test_every_decision_is_audited():
    governor = MinimalRiskGovernor(base_config(max_position_quantity=20_000.0))
    governor.authorize(request(), snapshot(), ts_ns=7)      # 10 000 : autorise
    governor.authorize(request(quantity=30_000.0), snapshot(), ts_ns=8)  # refuse
    assert len(governor.audit) == 2
    assert governor.audit[0].action == "AUTHORIZE"
    assert governor.audit[1].action == "REFUSE"
    assert governor.audit[1].ts_ns == 8
    assert "exceeds the authorised maximum" in governor.audit[1].reason


def test_the_audit_is_serialisable():
    governor = MinimalRiskGovernor(base_config())
    governor.authorize(request(), snapshot(), ts_ns=1)
    payload = governor.audit[0].to_dict()
    assert json.dumps(payload)
    assert payload["actor"] == "risk-governor"
