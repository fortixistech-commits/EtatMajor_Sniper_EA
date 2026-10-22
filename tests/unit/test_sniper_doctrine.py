"""Tests de la doctrine Sniper (Mission 6).

Les regles sont explicites et testables ; l'absence d'opportunite est un
resultat valide. Ces tests verifient des **valeurs** (regime detecte, setup
detecte, taille calculee, motifs d'abstention), pas l'absence d'exception.

Aucune de ces regles ne pretend a un avantage statistique : le jeu de
dononces utilise ici est synthetique et construit pour verifier la
mecanique, pas pour mesurer une performance.
"""

from __future__ import annotations

import math

import pytest

from etatmajor.core.models import DataQuality, MarketSnapshot
from etatmajor.data.models import Bar
from etatmajor.sniper.context import ContextFilter, session_of
from etatmajor.sniper.engine import SniperEngine
from etatmajor.sniper.planner import MissionPlanner, PlanningError
from etatmajor.sniper.regime import (
    MarketRegime,
    RegimeDetector,
    VolatilityState,
)
from etatmajor.sniper.setup import PullbackSetupDetector
from etatmajor.sniper.strategy import SniperStrategy
from etatmajor.strategies.base import StrategyContext, VisibleBars
from etatmajor.core.clock import SimClock
from etatmajor.core.events import Fill
from etatmajor.execution.accounting import Portfolio
from tests.conftest import make_config, make_dataset

BASE_NS = 1_767_571_200_000_000_000
HOUR_NS = 3_600_000_000_000
DAY_NS = 86_400_000_000_000
# Les series de test commencent a 08:00 UTC : la session de Londres est
# autorisee par defaut, ce qui evite que le filtre de contexte masque les
# autres comportements.
SERIES_BASE_NS = BASE_NS + 8 * HOUR_NS


def make_bar(index: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        ts_open_ns=SERIES_BASE_NS + index * 60_000_000_000,
        ts_close_ns=SERIES_BASE_NS + (index + 1) * 60_000_000_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def trending_bars(count: int = 80, step: float = 0.00040) -> list[Bar]:
    """Serie en hausse reguliere, avec un repli final (zone d'interet)."""
    bars = []
    price = 1.10000
    for index in range(count):
        open_ = price
        close = price + step
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        bars.append(make_bar(index, open_, high, low, close))
        price = close
    return bars


def ranging_bars(count: int = 80) -> list[Bar]:
    """Serie en range : la reconnaissance ne doit pas trouver de tendance."""
    bars = []
    for index in range(count):
        cycle = (index % 10) / 10.0
        close = 1.10000 + (0.00020 if cycle < 0.5 else -0.00020)
        open_ = close - (0.00005 if cycle < 0.5 else -0.00005)
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        bars.append(make_bar(index, open_, high, low, close))
    return bars


def context_for(bars: list[Bar], index: int | None = None) -> StrategyContext:
    index = len(bars) - 1 if index is None else index
    visible = VisibleBars(bars, index + 1)
    portfolio = Portfolio(100_000.0)
    return StrategyContext(
        index=index,
        bar=bars[index],
        visible_bars=visible,
        clock=SimClock(bars[index].ts_close_ns),
        portfolio=portfolio.snapshot(),
    )


# --- reconnaissance --------------------------------------------------------
def test_a_rising_series_is_classified_as_an_uptrend():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    snapshot = detector.evaluate(trending_bars())
    assert snapshot.regime is MarketRegime.TREND_UP
    assert snapshot.is_trending is True
    assert snapshot.reasons


def test_a_flat_series_is_classified_as_a_range():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    snapshot = detector.evaluate(ranging_bars())
    assert snapshot.regime is MarketRegime.RANGE
    assert snapshot.is_trending is False


def test_too_few_bars_leave_the_regime_undefined():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    snapshot = detector.evaluate(trending_bars(12))
    assert snapshot.regime is MarketRegime.UNDEFINED
    assert "not enough visible bars" in snapshot.reasons[0]


def test_the_volatility_state_is_reported():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    snapshot = detector.evaluate(trending_bars())
    assert snapshot.volatility_state in (
        VolatilityState.EXPANDING,
        VolatilityState.CONTRACTING,
        VolatilityState.STABLE,
    )


def test_the_regime_only_uses_visible_bars():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    bars = trending_bars(60)
    partial = detector.evaluate(bars[:30])
    full = detector.evaluate(bars)
    assert partial.bars_used == 30
    assert full.bars_used == 60
    assert partial.regime is not full.regime or partial.ema_slow != full.ema_slow


# --- filtre de contexte ----------------------------------------------------
def test_the_session_is_derived_from_the_timestamp():
    assert session_of(BASE_NS + 9 * HOUR_NS) == "london"
    assert session_of(BASE_NS + 14 * HOUR_NS) == "new_york"
    assert session_of(BASE_NS + 2 * HOUR_NS) == "asia"


def test_a_stale_market_blocks_the_decision():
    filter_ = ContextFilter(max_data_age_ns=1_000_000_000)
    snapshot = MarketSnapshot(
        symbol="EURUSD",
        ts_ns=BASE_NS,
        bid=1.10000,
        ask=1.10010,
        last_price=1.10005,
        quality=DataQuality.FRESH,
        data_age_ns=10_000_000_000,
    )
    decision = filter_.evaluate(BASE_NS + 9 * HOUR_NS, snapshot)
    assert decision.allowed is False
    assert any("stale" in reason for reason in decision.reasons)


def test_a_wide_spread_blocks_the_decision():
    filter_ = ContextFilter(max_spread=0.00020)
    snapshot = MarketSnapshot(
        symbol="EURUSD",
        ts_ns=BASE_NS,
        bid=1.10000,
        ask=1.10050,
        last_price=1.10025,
        quality=DataQuality.FRESH,
    )
    decision = filter_.evaluate(BASE_NS + 9 * HOUR_NS, snapshot)
    assert decision.allowed is False
    assert any("spread" in reason for reason in decision.reasons)


def test_an_authorised_session_and_a_normal_spread_are_accepted():
    filter_ = ContextFilter(max_spread=0.00020)
    snapshot = MarketSnapshot(
        symbol="EURUSD",
        ts_ns=BASE_NS,
        bid=1.10000,
        ask=1.10010,
        last_price=1.10005,
        quality=DataQuality.FRESH,
    )
    decision = filter_.evaluate(BASE_NS + 9 * HOUR_NS, snapshot)
    assert decision.allowed is True
    assert decision.session == "london"


# --- planification ---------------------------------------------------------
def test_the_quantity_is_derived_from_the_risk_and_the_stop_distance():
    planner = MissionPlanner(risk_amount=20.0, volume_step=0.01, min_quantity=0.01)
    from etatmajor.sniper.setup import SetupDetection
    from etatmajor.core.types import OrderSide

    setup = SetupDetection(
        direction=OrderSide.BUY,
        reference_price=1.10000,
        invalidation_price=1.09900,
        target_price=None,
        pullback_low=1.09910,
        pullback_high=1.10010,
        distance_to_ema=0.0001,
        bars_in_pullback=5,
        quality=0.5,
    )
    plan = planner.plan(
        setup, "EURUSD", "1m", "test", "1.0", BASE_NS, "PLAN-1"
    )
    # 20 USD de risque / 0.00100 de distance = 20 000 unites.
    assert plan.quantity == pytest.approx(20_000.0)
    assert plan.risk_amount == pytest.approx(20.0)
    assert plan.target_price == pytest.approx(1.10200)
    assert plan.invalidation_reason


def test_a_risk_too_small_for_the_stop_is_refused():
    from etatmajor.sniper.setup import SetupDetection
    from etatmajor.core.types import OrderSide

    planner = MissionPlanner(risk_amount=0.05, volume_step=0.01, min_quantity=100.0)
    setup = SetupDetection(
        direction=OrderSide.BUY,
        reference_price=1.10000,
        invalidation_price=1.09900,
        target_price=None,
        pullback_low=1.09910,
        pullback_high=1.10010,
        distance_to_ema=0.0001,
        bars_in_pullback=5,
        quality=0.5,
    )
    with pytest.raises(PlanningError) as excinfo:
        planner.plan(setup, "EURUSD", "1m", "test", "1.0", BASE_NS, "PLAN-1")
    assert "too small" in str(excinfo.value)


# --- moteur ----------------------------------------------------------------
def test_the_engine_abstains_when_there_is_no_trend():
    engine = SniperEngine(symbol="EURUSD", timeframe="1m")
    decision = engine.evaluate(context_for(ranging_bars()))
    assert decision.abstained is True
    assert decision.intent is None
    assert any("no trend" in reason for reason in decision.reasons)


def test_the_engine_abstains_without_enough_bars():
    engine = SniperEngine(symbol="EURUSD", timeframe="1m")
    decision = engine.evaluate(context_for(trending_bars(10)))
    assert decision.abstained is True


def test_the_engine_produces_a_complete_mission_plan_when_the_setup_is_valid():
    bars = trending_bars()
    # On ajoute un repli qui touche la moyenne rapide et une bougie de reprise.
    detector = RegimeDetector(fast_period=10, slow_period=30)
    regime = detector.evaluate(bars)
    assert regime.regime is MarketRegime.TREND_UP

    # Construction d'un repli manuel : la derniere bougie revient sur l'ema
    # rapide et repart.
    ema_fast = regime.ema_fast
    last = bars[-1]
    pullback = make_bar(
        len(bars),
        last.close,
        max(ema_fast, last.close) + 0.00020,
        min(ema_fast, last.close) - 0.00020,
        ema_fast,
    )
    resumption = make_bar(
        len(bars) + 1,
        ema_fast,
        ema_fast + 0.00040,
        ema_fast - 0.00010,
        ema_fast + 0.00035,
    )
    series = bars + [pullback, resumption]

    engine = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=detector,
        planner=MissionPlanner(risk_amount=20.0),
    )
    decision = engine.evaluate(context_for(series))
    assert decision.abstained is False
    assert decision.intent is not None
    plan = decision.intent.plan
    assert plan.side.value == "BUY"
    assert plan.stop_price < plan.entry_price
    assert plan.quantity > 0
    assert plan.risk_amount == pytest.approx(20.0, rel=1e-3)
    assert plan.invalidation_reason


def test_the_strategy_emits_nothing_when_the_engine_abstains():
    strategy = SniperStrategy(symbol="EURUSD", timeframe="1m")
    bars = ranging_bars()
    context = context_for(bars)
    strategy.on_start(context)
    signals = strategy.on_bar(context)
    assert list(signals) == []
    assert strategy.abstentions == 1
    assert strategy.engagements == 0
    assert strategy.decisions[0].abstained is True


def test_the_strategy_records_the_reasons_of_the_abstention():
    strategy = SniperStrategy(symbol="EURUSD", timeframe="1m")
    bars = ranging_bars()
    context = context_for(bars)
    strategy.on_start(context)
    strategy.on_bar(context)
    assert strategy.decisions[0].reasons
    assert strategy.decisions[0].to_dict()["abstained"] is True
