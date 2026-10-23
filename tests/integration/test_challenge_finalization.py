"""Test de la cloture de fin de replay (phase C, C3).

Le dernier mark-to-market ne suffit pas : une position encore ouverte doit
etre liquidee, et le verdict doit refleter le prix de liquidation (spread,
cout de sortie) et non la derniere cloture intermediaire.
"""

from __future__ import annotations

import pytest

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.challenge.profile import ChallengeProfile
from etatmajor.core.types import EndOfReplayPolicy
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset

PRICES = [1.10000] * 12


def challenge_profile() -> ChallengeProfile:
    return ChallengeProfile.from_dict(
        {
            "profile_status": "VERIFIED",
            "profile_id": "finalization-test",
            "profile_version": "1.0.0",
            "verified_on": "2026-10-22",
            "verified_by": "tests",
            "sources": ["https://example.invalid/rules"],
            "program": {"name": "Test", "variant": "New", "platform": "MT5"},
            "account": {"initial_capital": 2500.0, "reference_capital": 2500.0},
            "steps": [
                {
                    "index": 1,
                    "profit_target_percent": 10.0,
                    "profit_target_amount": 250.0,
                    "min_profitable_days": 0,
                }
            ],
            "limits": {
                "max_daily_loss_percent": 5.0,
                "max_daily_loss_amount": 125.0,
                "max_total_loss_percent": 10.0,
                "max_total_loss_amount": 250.0,
                "drawdown_type": "static",
                "drawdown_basis": "balance",
                "daily_reset_time": "00:00",
                "daily_reset_timezone": "UTC",
            },
            "trading_days": {
                "min_profitable_days_per_step": 0,
                "profitable_day_definition": "realised net pnl > 0",
            },
            "evaluation": {"policy": "most_restrictive_interpretation"},
            "ambiguous_rules": [],
        }
    )


def build(policy: EndOfReplayPolicy):
    config = make_config(
        initial_capital=2500.0,
        spread_price=0.0002,
        end_of_replay_policy=policy,
    )
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=1000.0,
        entry_index=7,
        exit_index=999,
    )
    engine = ReplayEngine(
        dataset=make_dataset(PRICES),
        config=config,
        strategy=strategy,
        challenge=ChallengeEngine(challenge_profile(), 2500.0),
    )
    return engine.run()


def test_the_verdict_uses_the_post_liquidation_equity():
    result = build(EndOfReplayPolicy.CLOSE_AT_LAST_PRICE)
    account = result.report["account"]
    verdict = result.report["challenge"]["verdict"]

    # Achat a 1,1001 (demi-spread), liquidation a 1,0999 : -0,2.
    assert account["net_pnl"] == pytest.approx(-0.2, abs=1e-9)
    assert verdict["total_pnl"] == pytest.approx(account["net_pnl"], abs=1e-9)
    assert verdict["max_total_loss"] == pytest.approx(0.2, abs=1e-9)
    positions = result.portfolio.snapshot().positions
    assert all(position["quantity"] == 0.0 for position in positions)


def test_mark_to_market_policy_does_not_realise_the_exit():
    result = build(EndOfReplayPolicy.MARK_TO_MARKET)
    account = result.report["account"]
    verdict = result.report["challenge"]["verdict"]

    assert account["net_pnl"] == pytest.approx(-0.1, abs=1e-9)
    assert verdict["total_pnl"] == pytest.approx(account["net_pnl"], abs=1e-9)
    assert len(result.portfolio.snapshot().positions) == 1
