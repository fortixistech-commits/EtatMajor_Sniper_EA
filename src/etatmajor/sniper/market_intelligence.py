"""Market Intelligence : lecture explicable des conditions de marche.

Ce module ne produit pas de signal et ne predit rien. Il rassemble les
mesures qui justifient une abstention ou un engagement :

* regime de tendance (EMA) et force de tendance (ADX / DI) ;
* volatilite absolue (ATR) et relative (rang percentile) ;
* momentum (RSI, taux de variation) ;
* structure (sommets et creux, ou canaux de repli) ;
* alignement multi-timeframe, calcule sur des bougies **cloturees** ;
* qualite des donnees (barres manquantes, avertissements).

Chaque valeur est derivee des seules bougies visibles. Deux prefixes
identiques produisent le meme instantane : aucun etat cache, aucun alea.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Mapping
from statistics import median
from typing import Any, Sequence

from ..data.models import Bar
from .context import session_of
from .regime import (
    MarketRegime,
    RegimeDetector,
    RegimeSnapshot,
    atr as simple_atr,
)

TIMEFRAME_NS: dict[str, int] = {
    "1m": 60_000_000_000,
    "5m": 5 * 60_000_000_000,
    "15m": 15 * 60_000_000_000,
    "30m": 30 * 60_000_000_000,
    "1h": 3_600_000_000_000,
    "4h": 4 * 3_600_000_000_000,
    "1d": 86_400_000_000_000,
}


class TrendStrength(str, Enum):
    """Force de tendance lue sur l'ADX."""

    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"
    WEAK = "WEAK"
    STRONG = "STRONG"
    VERY_STRONG = "VERY_STRONG"


class VolatilityRegime(str, Enum):
    """Niveau de volatilite relativement a son propre historique."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class MarketStructure(str, Enum):
    """Sequence de sommets et de creux."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    UNDEFINED = "UNDEFINED"


class MomentumState(str, Enum):
    """Lecture du momentum, sans promesse de continuation."""

    OVERSOLD = "OVERSOLD"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"
    OVERBOUGHT = "OVERBOUGHT"


class StructuralEvent(str, Enum):
    """Evenement de structure sur la derniere bougie."""

    NONE = "NONE"
    BREAK_UP = "BREAK_UP"
    BREAK_DOWN = "BREAK_DOWN"


class HtfAlignment(str, Enum):
    """Relation entre le timeframe courant et un timeframe superieur."""

    ALIGNED = "ALIGNED"
    CONFLICT = "CONFLICT"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DataQualityAssessment:
    """Qualite des donnees telle qu'elle influence la confiance.

    Les erreurs sont fatales en amont ; ici seules les informations non
    bloquantes (barres manquantes, avertissements) sont prises en compte.
    """

    bar_count: int = 0
    missing_bars: int = 0
    expected_bars: int = 0
    errors: int = 0
    warnings: int = 0

    @property
    def missing_ratio(self) -> float:
        if self.expected_bars <= 0:
            return 0.0
        return min(1.0, max(0.0, self.missing_bars / self.expected_bars))

    @property
    def confidence_factor(self) -> float:
        """Facteur multiplicatif, borne pour ne jamais annuler la mesure."""
        if self.errors:
            return 0.4
        return max(0.4, 1.0 - 2.0 * self.missing_ratio)

    @classmethod
    def from_report(cls, report: Any) -> "DataQualityAssessment":
        """Construit l'evaluation depuis un `DataQualityReport` ou son dict."""
        if isinstance(report, Mapping):
            bar_count = report.get("bar_count", report.get("rows_accepted", 0))
            missing_bars = report.get("missing_bars", 0)
            expected_bars = report.get("expected_bars", 0)
            errors = report.get("errors", ())
            warnings = report.get("warnings", ())
        else:
            bar_count = getattr(report, "bar_count", 0) or getattr(
                report, "rows_accepted", 0
            )
            missing_bars = getattr(report, "missing_bars", 0)
            expected_bars = getattr(report, "expected_bars", 0)
            errors = getattr(report, "errors", ())
            warnings = getattr(report, "warnings", ())
        def count(value: Any) -> int:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
            return len(value or ())

        return cls(
            bar_count=int(bar_count or 0),
            missing_bars=int(missing_bars or 0),
            expected_bars=int(expected_bars or 0),
            errors=count(errors),
            warnings=count(warnings),
        )

    def to_dict(self) -> dict:
        return {
            "bar_count": self.bar_count,
            "missing_bars": self.missing_bars,
            "expected_bars": self.expected_bars,
            "missing_ratio": self.missing_ratio,
            "errors": self.errors,
            "warnings": self.warnings,
            "confidence_factor": self.confidence_factor,
        }


@dataclass(frozen=True)
class HigherTimeframeView:
    """Lecture d'un timeframe superieur agrege, sans bougie incomplete."""

    factor: int
    timeframe_ns: int
    regime: RegimeSnapshot
    adx: float
    bars_used: int
    alignment: HtfAlignment

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "timeframe_ns": self.timeframe_ns,
            "regime": self.regime.to_dict(),
            "adx": self.adx,
            "bars_used": self.bars_used,
            "alignment": self.alignment.value,
        }


@dataclass(frozen=True)
class MarketIntelligenceSnapshot:
    """Photo explicable du terrain, avec toutes ses variables."""

    bars_used: int
    ts_ns: int
    regime: RegimeSnapshot
    trend_strength: TrendStrength
    adx: float
    plus_di: float
    minus_di: float
    rsi: float
    roc: float
    momentum: MomentumState
    atr: float
    atr_percentile: float
    volatility_regime: VolatilityRegime
    structure: MarketStructure
    structure_method: str
    last_swing_high: float | None
    last_swing_low: float | None
    structural_event: StructuralEvent
    session: str
    higher_timeframe: HigherTimeframeView | None
    data_quality: DataQualityAssessment
    confidence: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "bars_used": self.bars_used,
            "ts_ns": self.ts_ns,
            "regime": self.regime.to_dict(),
            "trend_strength": self.trend_strength.value,
            "adx": self.adx,
            "plus_di": self.plus_di,
            "minus_di": self.minus_di,
            "rsi": self.rsi,
            "roc": self.roc,
            "momentum": self.momentum.value,
            "atr": self.atr,
            "atr_percentile": self.atr_percentile,
            "volatility_regime": self.volatility_regime.value,
            "structure": self.structure.value,
            "structure_method": self.structure_method,
            "last_swing_high": self.last_swing_high,
            "last_swing_low": self.last_swing_low,
            "structural_event": self.structural_event.value,
            "session": self.session,
            "higher_timeframe": (
                self.higher_timeframe.to_dict() if self.higher_timeframe else None
            ),
            "data_quality": self.data_quality.to_dict(),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """True Range pour chaque bougie apres la premiere."""
    ranges: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return ranges


def directional_index(
    bars: Sequence[Bar], period: int = 14
) -> tuple[float, float, float]:
    """ADX, +DI et -DI (lissage Wilder).

    Retourne ``(0.0, 0.0, 0.0)`` si l'historique est insuffisant ou si le
    marche est parfaitement immobile : l'absence de mesure est explicite.
    """
    if period <= 0 or len(bars) < period + 1:
        return 0.0, 0.0, 0.0

    ranges: list[float] = []
    plus_moves: list[float] = []
    minus_moves: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_moves.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_moves.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    atr_sum = sum(ranges[:period])
    plus_sum = sum(plus_moves[:period])
    minus_sum = sum(minus_moves[:period])

    dx_values: list[float] = []
    last_plus_di = 0.0
    last_minus_di = 0.0

    for index in range(period - 1, len(ranges)):
        if index >= period:
            atr_sum = atr_sum - atr_sum / period + ranges[index]
            plus_sum = plus_sum - plus_sum / period + plus_moves[index]
            minus_sum = minus_sum - minus_sum / period + minus_moves[index]

        plus_di = 100.0 * _safe_div(plus_sum, atr_sum)
        minus_di = 100.0 * _safe_div(minus_sum, atr_sum)
        last_plus_di = plus_di
        last_minus_di = minus_di
        di_sum = plus_di + minus_di
        dx_values.append(100.0 * _safe_div(abs(plus_di - minus_di), di_sum))

    if not dx_values:
        return 0.0, last_plus_di, last_minus_di
    if len(dx_values) < period:
        return sum(dx_values) / len(dx_values), last_plus_di, last_minus_di

    adx_value = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx_value = (adx_value * (period - 1) + dx) / period
    return adx_value, last_plus_di, last_minus_di


def relative_strength_index(bars: Sequence[Bar], period: int = 14) -> float:
    """RSI de Wilder, borne dans ``[0, 100]``.

    Une serie immobile retourne 50 : aucune pression acheteuse ou vendeuse
    ne peut etre deduite d'une absence de variation.
    """
    if period <= 0 or len(bars) < period + 1:
        return 50.0

    closes = [bar.close for bar in bars]
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period

    if average_gain == 0.0 and average_loss == 0.0:
        return 50.0
    if average_loss == 0.0:
        return 100.0
    relative = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative)


def rate_of_change(bars: Sequence[Bar], period: int = 10) -> float:
    if period <= 0 or len(bars) <= period:
        return 0.0
    reference = bars[-period - 1].close
    return _safe_div(bars[-1].close - reference, reference)


def atr_history(
    bars: Sequence[Bar], period: int = 14, limit: int = 200
) -> list[float]:
    """ATR roulant sur chaque prefixe, tronque aux ``limit`` dernieres valeurs."""
    ranges = true_ranges(bars)
    if period <= 0 or len(ranges) < period:
        return []
    values: list[float] = []
    window_sum = sum(ranges[:period])
    values.append(window_sum / period)
    for index in range(period, len(ranges)):
        window_sum += ranges[index] - ranges[index - period]
        values.append(window_sum / period)
    return values[-limit:]


def percentile_rank(value: float, sample: Sequence[float]) -> float:
    """Rang percentile avec les ex aequo comptes a moitie."""
    if not sample:
        return 0.5
    less = sum(1 for item in sample if item < value)
    equal = sum(1 for item in sample if item == value)
    return (less + 0.5 * equal) / len(sample)


def find_swings(
    bars: Sequence[Bar], left: int = 2, right: int = 2
) -> tuple[list[float], list[float]]:
    """Sommets et creux locaux stricts, avec confirmation a droite."""
    highs: list[float] = []
    lows: list[float] = []
    if left < 1 or right < 1 or len(bars) < left + right + 1:
        return highs, lows

    for index in range(left, len(bars) - right):
        high = bars[index].high
        low = bars[index].low
        left_highs = [bar.high for bar in bars[index - left : index]]
        right_highs = [bar.high for bar in bars[index + 1 : index + right + 1]]
        left_lows = [bar.low for bar in bars[index - left : index]]
        right_lows = [bar.low for bar in bars[index + 1 : index + right + 1]]
        if high > max(left_highs) and high > max(right_highs):
            highs.append(high)
        if low < min(left_lows) and low < min(right_lows):
            lows.append(low)
    return highs, lows


def infer_timeframe_ns(bars: Sequence[Bar]) -> int:
    """Duree mediane entre ouvertures, robuste aux interruptions de marche."""
    differences = [
        current.ts_open_ns - previous.ts_open_ns
        for previous, current in zip(bars, bars[1:])
        if current.ts_open_ns > previous.ts_open_ns
    ]
    return int(median(differences)) if differences else 0


def aggregate_bars(
    bars: Sequence[Bar],
    factor: int,
    base_timeframe_ns: int | None = None,
) -> list[Bar]:
    """Agrege des bougies en ``factor`` fois plus grandes.

    Seules les periodes **entierement cloturees** sont retournees : la
    derniere bougie visible ne peut donc pas contribuer a une bougie
    superieure encore en formation.
    """
    if factor < 1:
        raise ValueError("factor must be >= 1")
    if not bars:
        return []

    duration_ns = base_timeframe_ns or infer_timeframe_ns(bars)
    if duration_ns <= 0:
        return []

    bucket_ns = duration_ns * factor
    last_close_ns = bars[-1].ts_close_ns
    aggregated: list[Bar] = []
    current_start: int | None = None
    current: list[Bar] = []

    def flush(start: int, group: Sequence[Bar]) -> None:
        end = start + bucket_ns
        if end > last_close_ns or not group:
            return
        aggregated.append(
            Bar(
                ts_open_ns=start,
                ts_close_ns=end,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
                volume=sum(bar.volume for bar in group),
            )
        )

    for bar in bars:
        start = (bar.ts_open_ns // bucket_ns) * bucket_ns
        if current_start is None:
            current_start = start
        elif start != current_start:
            flush(current_start, current)
            current_start = start
            current = []
        current.append(bar)
    if current_start is not None:
        flush(current_start, current)
    return aggregated


class MarketIntelligence:
    """Assemble les mesures de terrain en un instantane explicable."""

    def __init__(
        self,
        regime_detector: RegimeDetector | None = None,
        base_timeframe_ns: int = 60_000_000_000,
        atr_period: int = 14,
        adx_period: int = 14,
        rsi_period: int = 14,
        roc_period: int = 10,
        swing_left: int = 2,
        swing_right: int = 2,
        structure_lookback: int = 10,
        atr_history_limit: int = 200,
        low_percentile: float = 0.25,
        high_percentile: float = 0.85,
        extreme_percentile: float = 0.97,
    ) -> None:
        if base_timeframe_ns <= 0:
            raise ValueError("base_timeframe_ns must be positive")
        for name, value in (
            ("atr_period", atr_period),
            ("adx_period", adx_period),
            ("rsi_period", rsi_period),
            ("roc_period", roc_period),
            ("swing_left", swing_left),
            ("swing_right", swing_right),
            ("structure_lookback", structure_lookback),
            ("atr_history_limit", atr_history_limit),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if not (0.0 <= low_percentile < high_percentile < extreme_percentile <= 1.0):
            raise ValueError("percentile thresholds must be strictly increasing")

        self.regime_detector = regime_detector or RegimeDetector()
        self.base_timeframe_ns = base_timeframe_ns
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.rsi_period = rsi_period
        self.roc_period = roc_period
        self.swing_left = swing_left
        self.swing_right = swing_right
        self.structure_lookback = structure_lookback
        self.atr_history_limit = atr_history_limit
        self.low_percentile = low_percentile
        self.high_percentile = high_percentile
        self.extreme_percentile = extreme_percentile

    def evaluate(
        self,
        bars: Sequence[Bar],
        *,
        now_ts_ns: int | None = None,
        data_quality: DataQualityAssessment | None = None,
        higher_timeframe_factor: int | None = None,
    ) -> MarketIntelligenceSnapshot:
        visible = list(bars)
        quality = data_quality or DataQualityAssessment(bar_count=len(visible))
        regime = self.regime_detector.evaluate(visible)
        ts_ns = now_ts_ns if now_ts_ns is not None else (
            visible[-1].ts_close_ns if visible else 0
        )
        session = session_of(ts_ns) if ts_ns else "unknown"

        if not visible:
            return MarketIntelligenceSnapshot(
                bars_used=0,
                ts_ns=ts_ns,
                regime=regime,
                trend_strength=TrendStrength.UNKNOWN,
                adx=0.0,
                plus_di=0.0,
                minus_di=0.0,
                rsi=50.0,
                roc=0.0,
                momentum=MomentumState.NEUTRAL,
                atr=0.0,
                atr_percentile=0.5,
                volatility_regime=VolatilityRegime.NORMAL,
                structure=MarketStructure.UNDEFINED,
                structure_method="none",
                last_swing_high=None,
                last_swing_low=None,
                structural_event=StructuralEvent.NONE,
                session=session,
                higher_timeframe=None,
                data_quality=quality,
                confidence=0.0,
                reasons=("no visible bars",),
            )

        adx_value, plus_di, minus_di = directional_index(visible, self.adx_period)
        strength = self._trend_strength(adx_value)
        rsi_value = relative_strength_index(visible, self.rsi_period)
        roc_value = rate_of_change(visible, self.roc_period)
        momentum = self._momentum_state(rsi_value, roc_value)

        current_atr = simple_atr(visible, self.atr_period)
        history = atr_history(visible, self.atr_period, self.atr_history_limit)
        previous_history = history[:-1] if len(history) > 1 else []
        atr_percentile = percentile_rank(current_atr, previous_history)
        volatility_regime = self._volatility_regime(atr_percentile)

        highs, lows = find_swings(visible, self.swing_left, self.swing_right)
        structure, method = self._structure(visible, highs, lows)
        last_swing_high = highs[-1] if highs else None
        last_swing_low = lows[-1] if lows else None
        structural_event = self._structural_event(
            visible, last_swing_high, last_swing_low
        )

        higher: HigherTimeframeView | None = None
        if higher_timeframe_factor and higher_timeframe_factor > 1:
            aggregated = aggregate_bars(
                visible,
                higher_timeframe_factor,
                base_timeframe_ns=self.base_timeframe_ns,
            )
            if aggregated:
                higher_regime = self.regime_detector.evaluate(aggregated)
                higher_adx, _, _ = directional_index(aggregated, self.adx_period)
                alignment = self._alignment(regime, higher_regime)
                higher = HigherTimeframeView(
                    factor=higher_timeframe_factor,
                    timeframe_ns=self.base_timeframe_ns * higher_timeframe_factor,
                    regime=higher_regime,
                    adx=higher_adx,
                    bars_used=len(aggregated),
                    alignment=alignment,
                )

        confidence = self._confidence(
            regime=regime,
            strength=strength,
            structure=structure,
            higher=higher,
            quality=quality,
        )
        reasons = self._reasons(
            regime=regime,
            adx=adx_value,
            plus_di=plus_di,
            minus_di=minus_di,
            strength=strength,
            rsi=rsi_value,
            roc=roc_value,
            momentum=momentum,
            atr=current_atr,
            atr_percentile=atr_percentile,
            volatility=volatility_regime,
            structure=structure,
            method=method,
            event=structural_event,
            session=session,
            higher=higher,
            quality=quality,
        )

        return MarketIntelligenceSnapshot(
            bars_used=len(visible),
            ts_ns=ts_ns,
            regime=regime,
            trend_strength=strength,
            adx=adx_value,
            plus_di=plus_di,
            minus_di=minus_di,
            rsi=rsi_value,
            roc=roc_value,
            momentum=momentum,
            atr=current_atr,
            atr_percentile=atr_percentile,
            volatility_regime=volatility_regime,
            structure=structure,
            structure_method=method,
            last_swing_high=last_swing_high,
            last_swing_low=last_swing_low,
            structural_event=structural_event,
            session=session,
            higher_timeframe=higher,
            data_quality=quality,
            confidence=confidence,
            reasons=tuple(reasons),
        )

    # -- classifications ------------------------------------------------
    def _trend_strength(self, adx_value: float) -> TrendStrength:
        if adx_value <= 0.0:
            return TrendStrength.UNKNOWN
        if adx_value < 20.0:
            return TrendStrength.ABSENT
        if adx_value < 25.0:
            return TrendStrength.WEAK
        if adx_value < 40.0:
            return TrendStrength.STRONG
        return TrendStrength.VERY_STRONG

    def _momentum_state(self, rsi_value: float, roc_value: float) -> MomentumState:
        if rsi_value >= 70.0:
            return MomentumState.OVERBOUGHT
        if rsi_value <= 30.0:
            return MomentumState.OVERSOLD
        if rsi_value >= 55.0 and roc_value > 0.0:
            return MomentumState.BULLISH
        if rsi_value <= 45.0 and roc_value < 0.0:
            return MomentumState.BEARISH
        return MomentumState.NEUTRAL

    def _volatility_regime(self, percentile: float) -> VolatilityRegime:
        if percentile >= self.extreme_percentile:
            return VolatilityRegime.EXTREME
        if percentile >= self.high_percentile:
            return VolatilityRegime.HIGH
        if percentile < self.low_percentile:
            return VolatilityRegime.LOW
        return VolatilityRegime.NORMAL

    def _structure(
        self, bars: Sequence[Bar], highs: Sequence[float], lows: Sequence[float]
    ) -> tuple[MarketStructure, str]:
        if len(highs) >= 2 and len(lows) >= 2:
            higher_high = highs[-1] > highs[-2]
            higher_low = lows[-1] > lows[-2]
            lower_high = highs[-1] < highs[-2]
            lower_low = lows[-1] < lows[-2]
            if higher_high and higher_low:
                return MarketStructure.BULLISH, "swings"
            if lower_high and lower_low:
                return MarketStructure.BEARISH, "swings"
            return MarketStructure.MIXED, "swings"

        lookback = self.structure_lookback
        if len(bars) < 2 * lookback:
            return MarketStructure.UNDEFINED, "none"

        recent = bars[-lookback:]
        previous = bars[-2 * lookback : -lookback]
        recent_high = max(bar.high for bar in recent)
        previous_high = max(bar.high for bar in previous)
        recent_low = min(bar.low for bar in recent)
        previous_low = min(bar.low for bar in previous)
        if recent_high > previous_high and recent_low > previous_low:
            return MarketStructure.BULLISH, "channels"
        if recent_high < previous_high and recent_low < previous_low:
            return MarketStructure.BEARISH, "channels"
        return MarketStructure.MIXED, "channels"

    def _structural_event(
        self,
        bars: Sequence[Bar],
        last_swing_high: float | None,
        last_swing_low: float | None,
    ) -> StructuralEvent:
        """Detecte le franchissement **a la bougie courante**, pas un etat."""
        if len(bars) < 2:
            return StructuralEvent.NONE
        previous_close = bars[-2].close
        close = bars[-1].close
        if (
            last_swing_high is not None
            and previous_close <= last_swing_high < close
        ):
            return StructuralEvent.BREAK_UP
        if (
            last_swing_low is not None
            and previous_close >= last_swing_low > close
        ):
            return StructuralEvent.BREAK_DOWN
        return StructuralEvent.NONE

    def _alignment(
        self, current: RegimeSnapshot, higher: RegimeSnapshot
    ) -> HtfAlignment:
        if higher.regime is MarketRegime.UNDEFINED:
            return HtfAlignment.UNKNOWN
        if higher.regime is MarketRegime.RANGE:
            return HtfAlignment.NEUTRAL
        if current.is_trending and current.regime is higher.regime:
            return HtfAlignment.ALIGNED
        if current.is_trending:
            return HtfAlignment.CONFLICT
        return HtfAlignment.NEUTRAL

    def _confidence(
        self,
        *,
        regime: RegimeSnapshot,
        strength: TrendStrength,
        structure: MarketStructure,
        higher: HigherTimeframeView | None,
        quality: DataQualityAssessment,
    ) -> float:
        if regime.regime is MarketRegime.UNDEFINED:
            return 0.0

        score = 0.55 * regime.confidence
        if regime.is_trending:
            score += 0.10
            if strength is TrendStrength.STRONG:
                score += 0.10
            elif strength is TrendStrength.VERY_STRONG:
                score += 0.05
            elif strength is TrendStrength.ABSENT:
                score -= 0.10
            if structure is MarketStructure.BULLISH and regime.regime is MarketRegime.TREND_UP:
                score += 0.15
            elif structure is MarketStructure.BEARISH and regime.regime is MarketRegime.TREND_DOWN:
                score += 0.15
            elif structure in (MarketStructure.BULLISH, MarketStructure.BEARISH):
                score -= 0.15
        else:
            score += 0.10

        if higher is not None:
            if higher.alignment is HtfAlignment.ALIGNED:
                score += 0.15
            elif higher.alignment is HtfAlignment.CONFLICT:
                score -= 0.15

        score *= quality.confidence_factor
        return round(_clamp(score), 6)

    def _reasons(
        self,
        *,
        regime: RegimeSnapshot,
        adx: float,
        plus_di: float,
        minus_di: float,
        strength: TrendStrength,
        rsi: float,
        roc: float,
        momentum: MomentumState,
        atr: float,
        atr_percentile: float,
        volatility: VolatilityRegime,
        structure: MarketStructure,
        method: str,
        event: StructuralEvent,
        session: str,
        higher: HigherTimeframeView | None,
        quality: DataQualityAssessment,
    ) -> list[str]:
        reasons = [
            f"regime {regime.regime.value} (confidence {regime.confidence:.3f})",
            f"trend strength {strength.value}: adx {adx:.1f}, "
            f"+di {plus_di:.1f}, -di {minus_di:.1f}",
            f"momentum {momentum.value}: rsi {rsi:.1f}, roc {roc:.5f}",
            f"volatility {volatility.value}: atr {atr:.5f}, "
            f"percentile {atr_percentile:.3f}",
            f"structure {structure.value} via {method}",
            f"session {session}",
            f"data quality: {quality.missing_ratio:.1%} missing, "
            f"{quality.warnings} warning(s), {quality.errors} error(s)",
        ]
        if event is not StructuralEvent.NONE:
            reasons.append(f"structural event {event.value}")
        if higher is not None:
            reasons.append(
                f"higher timeframe x{higher.factor}: {higher.regime.regime.value}, "
                f"adx {higher.adx:.1f}, alignment {higher.alignment.value}"
            )
        return reasons
