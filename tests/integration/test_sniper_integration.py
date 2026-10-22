"""Tests d'integration de la doctrine Sniper dans le rejeu (Mission 6).

La chaine complete est verifiee : reconnaissance -> filtres -> selection ->
plan -> risque -> execution simulee. Et, surtout, le cas de l'abstention :
une serie sans tendance ne doit produire **aucun** ordre.
"""

from __future__ import annotations

import pytest

from etatmajor.core.types import OperatingMode
from etatmajor.replay.engine import ReplayEngine
from etatmajor.sniper.planner import MissionPlanner
from etatmajor.sniper.regime import RegimeDetector
from etatmajor.sniper.strategy import SniperStrategy
from tests.conftest import make_config, make_dataset

from etatmajor.data.models import Bar
from etatmajor.replay.engine import Dataset

LONDON_BASE_NS = 1_767_571_200_000_000_000 + 8 * 3_600_000_000_000  # 08:00 UTC

def make_london_dataset(closes: list[float], timeframe_ns: int = 60_000_000_000) -> Dataset:
    """Dataset qui debute a 08:00 UTC (session Londres)."""
    bars = []
    for index, close in enumerate(closes):
        open_ = closes[index - 1] if index else close
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        bars.append(
            Bar(
                ts_open_ns=LONDON_BASE_NS + index * timeframe_ns,
                ts_close_ns=LONDON_BASE_NS + (index + 1) * timeframe_ns,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
            )
        )
    return Dataset(symbol="EURUSD", timeframe="1m", bars=tuple(bars))


TRENDING = [1.10000 + 0.00020 * index for index in range(120)]
RANGING = [1.10000 + (0.00020 if (index // 5) % 2 == 0 else -0.00020) for index in range(120)]

def trending_with_pullback():
    """Serie qui produit un setup valide (verifie numeriquement).

    60 barres de tendance a +0.00005/bar, puis :
    - bougie de repli fermant sur l'ema_fast (~ 1.10248) ;
    - bougie de reprise fermant a ema_fast + 0.00010, haussiere.
    La derniere bougie touche l'ema, son corps est suffisant, le regime
    reste TREND_UP : le detecteur produit un setup BUY a chaque run.
    """
    closes = [1.10000 + 0.00005 * i for i in range(60)]
    closes.append(1.10248)
    closes.append(1.10258)
    return closes







def build(closes, risk_amount: float = 20.0):
    dataset = make_london_dataset(closes)
    config = make_config()
    strategy = SniperStrategy(
        symbol="EURUSD",
        timeframe="1m",
        engine=None,
    )
    # Use default RegimeDetector (fast=20, slow=50)
    strategy.engine.planner = MissionPlanner(risk_amount=risk_amount, min_quantity=0.01)
    engine = ReplayEngine(dataset=dataset, config=config, strategy=strategy)
    return engine.run(), strategy


def test_a_ranging_series_produces_no_order_at_all():
    result, strategy = build(RANGING)
    assert result.report["executions"]["total"] == 0
    assert result.report["orders"]["total"] == 0
    assert strategy.engagements == 0
    assert strategy.abstentions > 0
    assert result.portfolio.net_quantity("EURUSD") == 0.0


def test_the_abstentions_are_explained():
    result, strategy = build(RANGING)
    assert strategy.decisions
    first = strategy.decisions[0]
    assert first.abstained is True
    assert first.reasons
    assert first.regime is not None


def test_a_trending_series_can_produce_a_signal():
    result, strategy = build(trending_with_pullback())
    # Avec un repli valide, le moteur doit engager au moins une fois
    assert strategy.engagements > 0
    for decision in strategy.decisions:
        if decision.intent is not None:
            plan = decision.intent.plan
            assert plan.quantity > 0
            assert plan.stop_price < plan.entry_price
            assert plan.risk_amount <= 20.0 * 1.001
            assert plan.invalidation_reason
            assert plan.data_refs


def test_every_signal_carries_a_complete_mission_plan():
    result, strategy = build(trending_with_pullback())
    signals = [
        entry
        for entry in result.journal.of_type("SIGNAL")
    ]
    assert len(signals) > 0
    for entry in signals:
        payload = entry.payload
        assert payload["plan"] is not None
        assert payload["plan"]["stop_price"] is not None
        assert payload["plan"]["risk_amount"] > 0
        assert payload["plan"]["invalidation_reason"]


def test_the_risk_governor_can_refuse_the_sniper():
    """Une taille hors de la limite autorisee est refusee, sans exécution."""
    dataset = make_london_dataset(trending_with_pullback())
    config = make_config(max_position_quantity=1.0)
    strategy = SniperStrategy(symbol="EURUSD", timeframe="1m")
    # Use default RegimeDetector (fast=20, slow=50)
    strategy.engine.planner = MissionPlanner(risk_amount=20.0, min_quantity=0.01)
    engine = ReplayEngine(dataset=dataset, config=config, strategy=strategy)
    result = engine.run()

    assert result.report["executions"]["total"] == 0
    assert result.report["rejections"]["risk_count"] >= 1
    assert result.portfolio.net_quantity("EURUSD") == 0.0
    assert result.portfolio.cash == pytest.approx(100_000.0)
