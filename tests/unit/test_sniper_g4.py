"""Tests de qualification G4 du Sniper Engine.

Ils verifient la doctrine, pas une performance : geometrie du setup, niveau
d'invalidation, plan complet, refus explicites et gardes de politique.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from etatmajor.core.clock import SimClock
from etatmajor.core.events import Fill
from etatmajor.core.models import MissionPlan
from etatmajor.core.types import OrderSide
from etatmajor.data.models import Bar
from etatmajor.execution.accounting import Portfolio
from etatmajor.sniper.engine import DoctrinePolicy, SniperEngine
from etatmajor.sniper.market_intelligence import HtfAlignment
from etatmajor.sniper.planner import MissionPlanner, PlanningError
from etatmajor.sniper.regime import MarketRegime, RegimeDetector
from etatmajor.sniper.setup import PullbackSetupDetector, SetupDetection
from etatmajor.strategies.base import StrategyContext, VisibleBars

BASE_NS = 1_767_571_200_000_000_000
HOUR_NS = 3_600_000_000_000
MINUTE_NS = 60_000_000_000
SERIES_BASE_NS = BASE_NS + 8 * HOUR_NS


def make_bar(index: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        ts_open_ns=SERIES_BASE_NS + index * MINUTE_NS,
        ts_close_ns=SERIES_BASE_NS + (index + 1) * MINUTE_NS,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def trend(count: int = 80, step: float = 0.00040) -> list[Bar]:
    bars: list[Bar] = []
    price = 1.10000
    for index in range(count):
        open_ = price
        close = price + step
        bars.append(
            make_bar(
                index,
                open_,
                max(open_, close) + 0.00010,
                min(open_, close) - 0.00010,
                close,
            )
        )
        price = close
    return bars


def with_long_pullback(bars: list[Bar], detector: RegimeDetector) -> list[Bar]:
    regime = detector.evaluate(bars)
    ema = regime.ema_fast
    last = bars[-1]
    pullback = make_bar(
        len(bars),
        last.close,
        max(ema, last.close) + 0.00020,
        min(ema, last.close) - 0.00020,
        ema,
    )
    resumption = make_bar(
        len(bars) + 1,
        ema,
        ema + 0.00040,
        ema - 0.00010,
        ema + 0.00035,
    )
    return bars + [pullback, resumption]


def with_short_pullback(bars: list[Bar], detector: RegimeDetector) -> list[Bar]:
    regime = detector.evaluate(bars)
    ema = regime.ema_fast
    last = bars[-1]
    pullback = make_bar(
        len(bars),
        last.close,
        max(ema, last.close) + 0.00020,
        min(ema, last.close) - 0.00020,
        ema,
    )
    resumption = make_bar(
        len(bars) + 1,
        ema,
        ema + 0.00010,
        ema - 0.00040,
        ema - 0.00035,
    )
    return bars + [pullback, resumption]


def context_for(bars: list[Bar], index: int | None = None) -> StrategyContext:
    index = len(bars) - 1 if index is None else index
    return StrategyContext(
        index=index,
        bar=bars[index],
        visible_bars=VisibleBars(bars, index + 1),
        clock=SimClock(bars[index].ts_close_ns),
        portfolio=Portfolio(100_000.0).snapshot(),
    )


def long_setup() -> tuple[list[Bar], PullbackSetupDetector, RegimeDetector]:
    detector = RegimeDetector(fast_period=10, slow_period=30)
    bars = with_long_pullback(trend(), detector)
    return bars, PullbackSetupDetector(), detector


# --- setup -----------------------------------------------------------------
def test_a_valid_pullback_produces_a_structural_long_setup():
    bars, setup_detector, detector = long_setup()
    regime = detector.evaluate(bars)
    assert regime.regime is MarketRegime.TREND_UP
    setup = setup_detector.detect(bars, regime)
    assert setup is not None
    assert setup.direction is OrderSide.BUY
    assert setup.invalidation_price < setup.reference_price
    assert setup.target_price is None
    assert 0.0 <= setup.quality <= 1.0
    assert setup.bars_in_pullback >= 1
    assert any("touched the ema" in reason for reason in setup.reasons)


def test_the_invalidation_is_below_the_pullback_low_with_a_buffer():
    bars, setup_detector, detector = long_setup()
    regime = detector.evaluate(bars)
    setup = setup_detector.detect(bars, regime)
    assert setup is not None
    window_low = min(bar.low for bar in bars[-setup_detector.pullback_window :])
    candle_range = bars[-1].high - bars[-1].low
    assert setup.invalidation_price == pytest.approx(
        window_low - candle_range * setup_detector.stop_buffer_ratio
    )


def test_a_short_pullback_is_the_mirror_image():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    bars = with_short_pullback(trend(step=-0.00040), detector)
    regime = detector.evaluate(bars)
    assert regime.regime is MarketRegime.TREND_DOWN
    setup = PullbackSetupDetector().detect(bars, regime)
    assert setup is not None
    assert setup.direction is OrderSide.SELL
    assert setup.invalidation_price > setup.reference_price


def test_a_resumption_closing_on_the_wrong_side_is_refused():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    bars = trend()
    regime = detector.evaluate(bars)
    ema = regime.ema_fast
    last = bars[-1]
    pullback = make_bar(
        len(bars), last.close, ema + 0.00020, ema - 0.00020, ema - 0.00030
    )
    resumption = make_bar(
        len(bars) + 1, ema - 0.00030, ema - 0.00010, ema - 0.00040, ema - 0.00015
    )
    series = bars + [pullback, resumption]
    assert PullbackSetupDetector().detect(series, detector.evaluate(series)) is None


def test_a_resumption_with_a_tiny_body_is_refused():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    bars = trend()
    regime = detector.evaluate(bars)
    ema = regime.ema_fast
    last = bars[-1]
    pullback = make_bar(
        len(bars), last.close, max(ema, last.close) + 0.0002,
        min(ema, last.close) - 0.0002, ema,
    )
    resumption = make_bar(
        len(bars) + 1, ema, ema + 0.00030, ema - 0.00001, ema + 0.00002
    )
    series = bars + [pullback, resumption]
    assert PullbackSetupDetector().detect(series, detector.evaluate(series)) is None


def test_a_bar_that_does_not_touch_the_ema_is_not_a_pullback():
    detector = RegimeDetector(fast_period=10, slow_period=30)
    bars = trend()
    regime = detector.evaluate(bars)
    assert PullbackSetupDetector().detect(bars, regime) is None


# --- planificateur ---------------------------------------------------------
def sample_setup(direction: OrderSide = OrderSide.BUY) -> SetupDetection:
    if direction is OrderSide.BUY:
        invalidation = 1.09900
    else:
        invalidation = 1.10100
    return SetupDetection(
        direction=direction,
        reference_price=1.10000,
        invalidation_price=invalidation,
        target_price=None,
        pullback_low=1.09910,
        pullback_high=1.10010,
        distance_to_ema=0.0001,
        bars_in_pullback=5,
        quality=0.5,
    )


def test_the_plan_is_complete_and_the_risk_never_exceeds_the_request():
    planner = MissionPlanner(
        risk_amount=20.0, volume_step=100.0, min_quantity=100.0,
        estimated_cost_per_unit=0.00002,
    )
    plan = planner.plan(sample_setup(), "EURUSD", "1m", "test", "1.0", BASE_NS, "P1")
    assert isinstance(plan, MissionPlan)
    assert plan.stop_price < plan.entry_price
    assert plan.target_price == pytest.approx(1.10200)
    assert plan.quantity % 100.0 == pytest.approx(0.0)
    assert plan.risk_amount <= 20.0
    assert plan.risk_amount > 0.0
    assert plan.estimated_costs > 0.0
    assert plan.invalidation_reason


def test_a_buy_plan_with_a_stop_above_the_entry_is_refused():
    planner = MissionPlanner()
    bad = replace(sample_setup(), invalidation_price=1.10100)
    with pytest.raises(PlanningError) as excinfo:
        planner.plan(bad, "EURUSD", "1m", "test", "1.0", BASE_NS, "P1")
    assert "below the entry" in str(excinfo.value)


def test_a_sell_plan_with_a_stop_below_the_entry_is_refused():
    planner = MissionPlanner()
    bad = replace(sample_setup(OrderSide.SELL), invalidation_price=1.09900)
    with pytest.raises(PlanningError) as excinfo:
        planner.plan(bad, "EURUSD", "1m", "test", "1.0", BASE_NS, "P1")
    assert "above the entry" in str(excinfo.value)


def test_a_zero_quantity_is_always_refused():
    planner = MissionPlanner(
        risk_amount=1e-12, volume_step=0.01, min_quantity=0.0
    )
    with pytest.raises(PlanningError) as excinfo:
        planner.plan(sample_setup(), "EURUSD", "1m", "test", "1.0", BASE_NS, "P1")
    assert "below the minimum" in str(excinfo.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"risk_amount": 0.0},
        {"reward_risk_multiple": 0.0},
        {"volume_step": 0.0},
        {"min_quantity": -1.0},
        {"estimated_cost_per_unit": -0.0001},
        {"validity_ns": 0},
        {"max_duration_ns": 0},
    ],
)
def test_invalid_planner_settings_are_refused(overrides):
    planner = MissionPlanner(**overrides)
    with pytest.raises(PlanningError):
        planner.plan(sample_setup(), "EURUSD", "1m", "test", "1.0", BASE_NS, "P1")


# --- politique de doctrine -------------------------------------------------
def test_an_open_position_blocks_a_second_mission():
    bars, _, detector = long_setup()
    context = context_for(bars)
    portfolio = Portfolio(100_000.0)
    portfolio.apply_fill(
        Fill(
            "F1", "EURUSD", OrderSide.BUY, 10_000.0, 1.10000, 0.0,
            context.clock.now(),
        )
    )
    context = replace(context, portfolio=portfolio.snapshot())
    decision = SniperEngine(
        symbol="EURUSD", timeframe="1m", regime_detector=detector
    ).evaluate(context)
    assert decision.abstained is True
    assert "one mission at a time" in decision.reasons[0]


def test_a_confidence_floor_can_veto_the_engine():
    bars, _, detector = long_setup()
    decision = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=detector,
        policy=DoctrinePolicy(min_confidence=0.99),
    ).evaluate(context_for(bars))
    assert decision.abstained is True
    assert "market confidence" in decision.reasons[0]


def test_a_missing_higher_timeframe_is_refused_when_required():
    bars, _, detector = long_setup()
    decision = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=detector,
        policy=DoctrinePolicy(require_htf_alignment=True),
    ).evaluate(context_for(bars))
    assert decision.abstained is True
    assert "UNAVAILABLE" in decision.reasons[0]


def test_a_closed_higher_timeframe_can_satisfy_the_alignment_policy():
    detector = RegimeDetector(fast_period=5, slow_period=10)
    bars = with_long_pullback(trend(), detector)
    engine = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=detector,
        higher_timeframe_factor=5,
        policy=DoctrinePolicy(
            require_htf_alignment=True, min_setup_quality=0.1
        ),
    )
    decision = engine.evaluate(context_for(bars))
    assert decision.intelligence is not None
    assert decision.intelligence.higher_timeframe.alignment is HtfAlignment.ALIGNED
    assert decision.abstained is False
    assert decision.intent is not None


def test_a_setup_quality_floor_can_veto_the_engine():
    bars, _, detector = long_setup()
    decision = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=detector,
        policy=DoctrinePolicy(min_setup_quality=0.999),
    ).evaluate(context_for(bars))
    assert decision.abstained is True
    assert "setup quality" in decision.reasons[0]


def test_extreme_volatility_can_suspend_engagement():
    from tests.unit.test_market_intelligence import volatile_expansion

    engine = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=RegimeDetector(fast_period=10, slow_period=30),
        policy=DoctrinePolicy(block_extreme_volatility=True),
    )
    decision = engine.evaluate(context_for(volatile_expansion()))
    assert decision.abstained is True
    assert "volatility is extreme" in decision.reasons[0]


def test_invalid_policy_values_are_refused():
    with pytest.raises(ValueError):
        DoctrinePolicy(min_confidence=1.5)
    with pytest.raises(ValueError):
        DoctrinePolicy(min_setup_quality=-0.1)
    with pytest.raises(ValueError):
        DoctrinePolicy(max_open_positions=-1)
