"""Reconnaissance du terrain : classification du regime de marche.

Le detecteur ne predit pas le marche. Il **classe** les conditions a partir
de l'historique visible et expose les variables qui ont justifie son
classement, afin que la decision reste explicable.

Toutes les mesures sont calculees sur les seules bougies visibles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from ..data.models import Bar


class MarketRegime(str, Enum):
    """Classification du regime de marche."""

    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    UNDEFINED = "UNDEFINED"


class VolatilityState(str, Enum):
    """Etat de la volatilite relative."""

    EXPANDING = "EXPANDING"
    CONTRACTING = "CONTRACTING"
    STABLE = "STABLE"


@dataclass(frozen=True)
class RegimeSnapshot:
    """Resultat de la reconnaissance, avec ses variables justificatives."""

    regime: MarketRegime
    volatility_state: VolatilityState
    ema_fast: float
    ema_slow: float
    slope: float
    atr: float
    atr_ratio: float
    bars_used: int
    confidence: float = 0.0
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_trending(self) -> bool:
        return self.regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN)

    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "volatility_state": self.volatility_state.value,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "slope": self.slope,
            "atr": self.atr,
            "atr_ratio": self.atr_ratio,
            "bars_used": self.bars_used,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


def ema(values: Sequence[float], period: int) -> float:
    """Moyenne exponentielle, calculee de facon iterative (sans dependance)."""
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def atr(bars: Sequence[Bar], period: int) -> float:
    """Average True Range simplifie (True Range sans gap)."""
    if len(bars) < 2:
        return 0.0
    ranges = []
    for previous, current in zip(bars, bars[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    window = ranges[-period:]
    return sum(window) / len(window) if window else 0.0


class RegimeDetector:
    """Classifie le regime a partir des bougies visibles.

    Regles (volontairement simples et explicites) :

    * **tendance haussière** : l'EMA rapide est au-dessus de l'EMA lente, la
      pente de l'EMA lente est positive, et le prix est au-dessus de l'EMA
      lente ;
    * **tendance baissiere** : le miroir ;
    * **range** : les EMA sont proches, la pente est faible et le prix oscille
      autour de l'EMA rapide ;
    * **indetermine** : pas assez de bougies.
    """

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        atr_period: int = 14,
        slope_window: int = 5,
        trend_spread_ratio: float = 0.0005,
        max_slope_atr: float = 0.15,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.slope_window = slope_window
        self.trend_spread_ratio = trend_spread_ratio
        self.max_slope_atr = max_slope_atr

    def evaluate(self, bars: Sequence[Bar]) -> RegimeSnapshot:
        """Classe le regime a partir des bougies visibles."""
        closes = [bar.close for bar in bars]
        if len(closes) < self.slow_period:
            return RegimeSnapshot(
                regime=MarketRegime.UNDEFINED,
                volatility_state=VolatilityState.STABLE,
                ema_fast=0.0,
                ema_slow=0.0,
                slope=0.0,
                atr=0.0,
                atr_ratio=0.0,
                bars_used=len(closes),
                reasons=(f"not enough visible bars ({len(closes)} < {self.slow_period})",),
            )

        ema_fast = ema(closes, self.fast_period)
        ema_slow = ema(closes, self.slow_period)
        slope = ema_slow - ema(closes[-self.slow_period : -self.slope_window], self.slow_period)
        current_atr = atr(bars, self.atr_period)
        previous_atr = atr(bars[:-1], self.atr_period) if len(bars) > 2 else current_atr
        atr_ratio = current_atr / previous_atr if previous_atr else 1.0
        price = closes[-1]

        volatility = VolatilityState.STABLE
        if atr_ratio > 1.15:
            volatility = VolatilityState.EXPANDING
        elif atr_ratio < 0.85:
            volatility = VolatilityState.CONTRACTING

        spread = abs(ema_fast - ema_slow)
        spread_ratio = spread / price if price else 0.0
        slope_in_atr = abs(slope) / current_atr if current_atr else 0.0
        reasons: list[str] = []

        if spread_ratio > self.trend_spread_ratio and slope_in_atr > self.max_slope_atr:
            if ema_fast > ema_slow and slope > 0 and price > ema_slow:
                regime = MarketRegime.TREND_UP
                reasons.append("ema fast above ema slow, positive slope, price above ema slow")
            elif ema_fast < ema_slow and slope < 0 and price < ema_slow:
                regime = MarketRegime.TREND_DOWN
                reasons.append("ema fast below ema slow, negative slope, price below ema slow")
            else:
                regime = MarketRegime.RANGE
                reasons.append("ema separation present but price is not on the trend side")
        else:
            regime = MarketRegime.RANGE
            reasons.append(
                f"ema separation {spread_ratio:.6f} and slope {slope_in_atr:.3f} atr "
                f"below the trend thresholds"
            )

        if regime is MarketRegime.RANGE:
            # Plus la marche est plate (slope faible), plus la classification
            # de range est sure.
            confidence = min(
                1.0, 1.0 - slope_in_atr / max(self.max_slope_atr, 1e-9)
            )
        else:
            confidence = min(
                1.0, spread_ratio / max(self.trend_spread_ratio, 1e-9) * 0.5
            )

        return RegimeSnapshot(
            regime=regime,
            volatility_state=volatility,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            slope=slope,
            atr=current_atr,
            atr_ratio=atr_ratio,
            bars_used=len(closes),
            confidence=confidence,
            reasons=tuple(reasons),
        )
