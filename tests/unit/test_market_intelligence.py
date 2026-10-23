"""Tests de Market Intelligence (phase 3).

Les series sont synthetiques et servent a verifier la **mecanique** des
mesures, pas a demontrer un avantage statistique. Chaque test controle une
valeur ou un invariant explicite : pente, ADX, percentile, structure,
alignement multi-timeframe, qualite des donnees.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from etatmajor.data.models import Bar
from etatmajor.sniper.engine import SniperEngine
from etatmajor.sniper.market_intelligence import (
    DataQualityAssessment,
    HtfAlignment,
    MarketIntelligence,
    MarketStructure,
    MomentumState,
    TrendStrength,
    VolatilityRegime,
    aggregate_bars,
    directional_index,
    find_swings,
    infer_timeframe_ns,
    percentile_rank,
    relative_strength_index,
    true_ranges,
)
from etatmajor.sniper.regime import MarketRegime, RegimeDetector
from etatmajor.strategies.base import StrategyContext, VisibleBars
from etatmajor.core.clock import SimClock
from etatmajor.execution.accounting import Portfolio

BASE_NS = 1_767_571_200_000_000_000
HOUR_NS = 3_600_000_000_000
MINUTE_NS = 60_000_000_000
# 08:00 UTC : session de Londres.
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


def trend(count: int = 120, step: float = 0.00040, spread: float = 0.00020) -> list[Bar]:
    bars: list[Bar] = []
    price = 1.10000
    for index in range(count):
        open_ = price
        close = price + step
        bars.append(
            make_bar(
                index,
                open_,
                max(open_, close) + spread / 2.0,
                min(open_, close) - spread / 2.0,
                close,
            )
        )
        price = close
    return bars


def flat_range(count: int = 120) -> list[Bar]:
    bars: list[Bar] = []
    for index in range(count):
        close = 1.10020 if index % 2 == 0 else 1.09980
        bars.append(make_bar(index, 1.10000, 1.10025, 1.09975, close))
    return bars


def immobile(count: int = 80) -> list[Bar]:
    return [make_bar(index, 1.10000, 1.10000, 1.10000, 1.10000) for index in range(count)]


def volatile_expansion() -> list[Bar]:
    bars: list[Bar] = []
    price = 1.10000
    for index in range(80):
        open_ = price
        close = price + (0.00010 if index % 2 == 0 else -0.00010)
        bars.append(make_bar(index, open_, max(open_, close) + 0.00005, min(open_, close) - 0.00005, close))
        price = close
    for step in range(15):
        open_ = price
        close = price + 0.00100
        bars.append(make_bar(len(bars), open_, close + 0.00300, open_ - 0.00300, close))
        price = close
    return bars


def zigzag() -> list[Bar]:
    knots = [1.10000, 1.10200, 1.10000, 1.10400, 1.10200, 1.10600, 1.10400, 1.10600]
    closes: list[float] = []
    for start, end in zip(knots, knots[1:]):
        for step in range(10):
            closes.append(start + (end - start) * step / 10.0)
    closes.append(knots[-1])
    return [
        make_bar(index, close, close + 0.00020, close - 0.00020, close)
        for index, close in enumerate(closes)
    ]


def context_for(bars: list[Bar], index: int | None = None) -> StrategyContext:
    index = len(bars) - 1 if index is None else index
    return StrategyContext(
        index=index,
        bar=bars[index],
        visible_bars=VisibleBars(bars, index + 1),
        clock=SimClock(bars[index].ts_close_ns),
        portfolio=Portfolio(100_000.0).snapshot(),
    )


# --- mesures elementaires --------------------------------------------------
def test_true_ranges_use_the_previous_close():
    bars = [
        make_bar(0, 1.1000, 1.1010, 1.0990, 1.1005),
        make_bar(1, 1.1005, 1.1030, 1.1000, 1.1020),
    ]
    assert true_ranges(bars) == pytest.approx([0.0030])


def test_percentile_rank_counts_ties_as_half():
    assert percentile_rank(2.0, [1.0, 2.0, 2.0, 3.0]) == pytest.approx(0.50)
    assert percentile_rank(5.0, []) == 0.5


def test_adx_mirrors_direction_and_stays_bounded():
    up = directional_index(trend(), 14)
    down = directional_index(trend(step=-0.00040), 14)
    assert up[0] > 25.0
    assert up[1] > up[2]
    assert down[1] < down[2]
    assert 0.0 <= down[0] <= 100.0


def test_rsi_is_bounded_and_neutral_when_nothing_moves():
    assert relative_strength_index(trend(), 14) == pytest.approx(100.0)
    assert relative_strength_index(trend(step=-0.00040), 14) == pytest.approx(0.0)
    assert relative_strength_index(immobile(), 14) == pytest.approx(50.0)


def test_swings_require_confirmation_on_both_sides():
    highs, lows = find_swings(zigzag(), left=2, right=2)
    assert len(highs) >= 2
    assert len(lows) >= 2
    assert highs[-2] < highs[-1]
    assert lows[-2] < lows[-1]


# --- instantane ------------------------------------------------------------
def test_an_uptrend_is_described_with_all_its_variables():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    snapshot = analysis.evaluate(trend())
    assert snapshot.regime.regime is MarketRegime.TREND_UP
    assert snapshot.trend_strength in (TrendStrength.STRONG, TrendStrength.VERY_STRONG)
    assert snapshot.adx > 25.0
    assert snapshot.plus_di > snapshot.minus_di
    assert snapshot.roc > 0.0
    assert snapshot.momentum is MomentumState.OVERBOUGHT
    assert snapshot.structure is MarketStructure.BULLISH
    assert snapshot.volatility_regime in (
        VolatilityRegime.LOW,
        VolatilityRegime.NORMAL,
        VolatilityRegime.HIGH,
        VolatilityRegime.EXTREME,
    )
    assert 0.0 <= snapshot.confidence <= 1.0
    assert snapshot.reasons


def test_a_downtrend_is_the_mirror_image():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    snapshot = analysis.evaluate(trend(step=-0.00040))
    assert snapshot.regime.regime is MarketRegime.TREND_DOWN
    assert snapshot.minus_di > snapshot.plus_di
    assert snapshot.roc < 0.0
    assert snapshot.momentum is MomentumState.OVERSOLD
    assert snapshot.structure is MarketStructure.BEARISH


def test_a_flat_series_is_a_range_without_trend_strength():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    snapshot = analysis.evaluate(flat_range())
    assert snapshot.regime.regime is MarketRegime.RANGE
    assert snapshot.trend_strength in (
        TrendStrength.UNKNOWN,
        TrendStrength.ABSENT,
        TrendStrength.WEAK,
    )
    assert snapshot.structure is MarketStructure.MIXED
    assert snapshot.confidence > 0.0


def test_an_immobile_market_does_not_divide_by_zero():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    snapshot = analysis.evaluate(immobile())
    assert snapshot.atr == 0.0
    assert snapshot.atr_percentile == pytest.approx(0.5)
    assert snapshot.rsi == pytest.approx(50.0)
    assert snapshot.volatility_regime is VolatilityRegime.NORMAL
    assert 0.0 <= snapshot.confidence <= 1.0


def test_a_volatility_expansion_is_detected_against_its_own_history():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    snapshot = analysis.evaluate(volatile_expansion())
    assert snapshot.atr_percentile >= 0.80
    assert snapshot.volatility_regime in (
        VolatilityRegime.HIGH,
        VolatilityRegime.EXTREME,
    )


def test_structure_prefers_confirmed_swings_when_available():
    snapshot = MarketIntelligence(
        RegimeDetector(fast_period=10, slow_period=30)
    ).evaluate(zigzag())
    assert snapshot.structure_method == "swings"
    assert snapshot.structure is MarketStructure.BULLISH
    assert snapshot.last_swing_high is not None
    assert snapshot.last_swing_low is not None


def test_a_break_of_structure_is_reported_only_on_the_crossing_bar():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    bars = zigzag()
    crossing = make_bar(
        len(bars), bars[-1].close, 1.10740, 1.10580, 1.10700
    )
    after = make_bar(
        len(bars) + 1, 1.10700, 1.10760, 1.10680, 1.10720
    )
    event = analysis.evaluate(bars + [crossing])
    later = analysis.evaluate(bars + [crossing, after])
    assert event.structural_event.value == "BREAK_UP"
    assert later.structural_event.value == "NONE"


def test_an_undefined_history_returns_an_explicit_snapshot():
    snapshot = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30)).evaluate(trend(12))
    assert snapshot.regime.regime is MarketRegime.UNDEFINED
    assert snapshot.trend_strength is TrendStrength.UNKNOWN
    assert snapshot.structure is MarketStructure.UNDEFINED
    assert snapshot.confidence == 0.0


def test_no_bars_is_a_defined_result():
    snapshot = MarketIntelligence().evaluate([])
    assert snapshot.bars_used == 0
    assert snapshot.regime.regime is MarketRegime.UNDEFINED
    assert snapshot.reasons == ("no visible bars",)


def test_the_snapshot_is_deterministic_and_serialisable():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    first = analysis.evaluate(trend()).to_dict()
    second = analysis.evaluate(trend()).to_dict()
    assert first == second
    json.dumps(first)


def test_the_session_comes_from_the_timestamp():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    snapshot = analysis.evaluate(trend(), now_ts_ns=BASE_NS + 14 * HOUR_NS)
    assert snapshot.session == "new_york"


# --- multi-timeframe -------------------------------------------------------
def test_aggregation_only_returns_closed_buckets():
    bars = trend(52)
    aggregated = aggregate_bars(bars, 5, base_timeframe_ns=MINUTE_NS)
    assert len(aggregated) == 10
    assert all(item.ts_close_ns <= bars[-1].ts_close_ns for item in aggregated)


def test_the_inferred_timeframe_is_robust_to_a_gap():
    bars = trend(10)
    bars.append(
        Bar(
            ts_open_ns=bars[-1].ts_close_ns + 3 * HOUR_NS,
            ts_close_ns=bars[-1].ts_close_ns + 3 * HOUR_NS + MINUTE_NS,
            open=1.12000,
            high=1.12010,
            low=1.11990,
            close=1.12000,
            volume=1000.0,
        )
    )
    assert infer_timeframe_ns(bars) == MINUTE_NS


def test_future_bars_cannot_change_a_decision_taken_earlier():
    engine = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=RegimeDetector(fast_period=10, slow_period=30),
    )
    bars = trend(120)
    early = engine.evaluate(context_for(bars, 59))
    truncated = engine.evaluate(context_for(bars[:60], 59))
    assert early.to_dict() == truncated.to_dict()


def test_a_higher_timeframe_can_confirm_the_current_trend():
    analysis = MarketIntelligence(
        RegimeDetector(fast_period=5, slow_period=10), base_timeframe_ns=MINUTE_NS
    )
    snapshot = analysis.evaluate(trend(80), higher_timeframe_factor=5)
    assert snapshot.higher_timeframe is not None
    assert snapshot.higher_timeframe.bars_used == 16
    assert snapshot.higher_timeframe.alignment is HtfAlignment.ALIGNED
    assert "higher timeframe" in " ".join(snapshot.reasons)


def test_the_higher_timeframe_matches_a_manual_aggregation():
    bars = trend(80)
    aggregated = aggregate_bars(bars, 5, base_timeframe_ns=MINUTE_NS)
    assert aggregated[0].open == pytest.approx(bars[0].open)
    assert aggregated[0].close == pytest.approx(bars[4].close)
    assert aggregated[0].high == pytest.approx(max(bar.high for bar in bars[:5]))
    assert aggregated[0].low == pytest.approx(min(bar.low for bar in bars[:5]))


# --- qualite des donnees ---------------------------------------------------
def test_missing_data_lowers_confidence_and_is_stated():
    analysis = MarketIntelligence(RegimeDetector(fast_period=10, slow_period=30))
    clean = analysis.evaluate(trend())
    degraded = analysis.evaluate(
        trend(),
        data_quality=DataQualityAssessment(
            bar_count=120, missing_bars=60, expected_bars=120, warnings=2
        ),
    )
    assert degraded.confidence < clean.confidence
    assert "missing" in " ".join(degraded.reasons)
    assert degraded.data_quality.confidence_factor == pytest.approx(0.4)


def test_a_quality_report_is_adapted_without_inventing_values():
    report = SimpleNamespace(
        rows_accepted=90,
        missing_bars=10,
        expected_bars=100,
        errors=[],
        warnings=["gap"],
    )
    assessment = DataQualityAssessment.from_report(report)
    assert assessment.missing_ratio == pytest.approx(0.10)
    assert assessment.warnings == 1
    assert assessment.errors == 0


# --- integration au moteur -------------------------------------------------
def test_the_engine_exposes_the_intelligence_snapshot():
    engine = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=RegimeDetector(fast_period=10, slow_period=30),
    )
    decision = engine.evaluate(context_for(trend()))
    assert decision.intelligence is not None
    assert decision.intelligence.bars_used == len(trend())
    payload = decision.to_dict()
    assert payload["intelligence"]["regime"]["regime"] == "TREND_UP"


def test_insufficient_data_quality_blocks_the_engine():
    engine = SniperEngine(
        symbol="EURUSD",
        timeframe="1m",
        regime_detector=RegimeDetector(fast_period=10, slow_period=30),
        data_quality=DataQualityAssessment(
            bar_count=120, missing_bars=60, expected_bars=120
        ),
        max_missing_ratio=0.10,
    )
    decision = engine.evaluate(context_for(trend()))
    assert decision.abstained is True
    assert "data quality" in decision.reasons[0]
    assert decision.regime is not None


def test_invalid_parameters_are_refused():
    with pytest.raises(ValueError):
        MarketIntelligence(atr_period=0)
    with pytest.raises(ValueError):
        MarketIntelligence(low_percentile=0.8, high_percentile=0.5)
    with pytest.raises(ValueError):
        aggregate_bars(trend(10), 0)
