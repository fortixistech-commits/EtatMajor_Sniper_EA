"""Detection d'une configuration technique (famille de reference).

La configuration implementee ici est un **repli dans une tendance** (setup B
du cahier des charges) : un marche en tendance qui revient vers une zone
d'interet, suivi d'une bougie de reprise.

Les regles sont explicites, mesurees et testables. Cette configuration est un
**support de test de l'architecture** : aucune rentabilite n'est presumee et
elle ne sera jugee que par les campagnes de la Mission 12.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..core.types import OrderSide
from ..data.models import Bar
from .regime import MarketRegime, RegimeSnapshot


@dataclass(frozen=True)
class SetupDetection:
    """Configuration detectee, avec ses mesures."""

    direction: OrderSide
    reference_price: float
    invalidation_price: float
    target_price: float | None
    pullback_low: float
    pullback_high: float
    distance_to_ema: float
    bars_in_pullback: int
    quality: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    data_refs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction.value,
            "reference_price": self.reference_price,
            "invalidation_price": self.invalidation_price,
            "target_price": self.target_price,
            "pullback_low": self.pullback_low,
            "pullback_high": self.pullback_high,
            "distance_to_ema": self.distance_to_ema,
            "bars_in_pullback": self.bars_in_pullback,
            "quality": self.quality,
            "reasons": list(self.reasons),
            "data_refs": list(self.data_refs),
        }


class PullbackSetupDetector:
    """Detecte un repli vers la moyenne rapide suivi d'une reprise.

    Regles (long, miroir pour short) :

    1. le regime est une tendance (donne par le detecteur de regime) ;
    2. la bougie courante vient toucher la moyenne rapide (zone d'interet) ;
    3. la bougie de reprise est positive : cloture > ouverture et
       cloture > cloture precedente ;
    4. l'invalidation est le plus bas du repli moins une marge.

    Le signal est produit a la **cloture** de la bougie de reprise : le plan
    sera execute au plus tot sur la bougie suivante.
    """

    def __init__(
        self,
        pullback_window: int = 5,
        max_distance_to_ema_ratio: float = 0.0010,
        min_resumption_body_ratio: float = 0.2,
        stop_buffer_ratio: float = 0.2,
    ) -> None:
        self.pullback_window = pullback_window
        self.max_distance_to_ema_ratio = max_distance_to_ema_ratio
        self.min_resumption_body_ratio = min_resumption_body_ratio
        self.stop_buffer_ratio = stop_buffer_ratio

    def detect(
        self,
        bars: Sequence[Bar],
        regime: RegimeSnapshot,
    ) -> SetupDetection | None:
        """Retourne la configuration detectee, ou ``None`` (absence d'opportunite)."""
        if not regime.is_trending or len(bars) < 3:
            return None

        is_long = regime.regime is MarketRegime.TREND_UP
        current = bars[-1]
        previous = bars[-2]
        window = list(bars[-self.pullback_window :])

        # 2. la bougie courante touche la moyenne rapide et cloture du bon cote
        ema_fast = regime.ema_fast
        distance_ratio = abs(current.close - ema_fast) / ema_fast if ema_fast else 1.0
        touched = current.low <= ema_fast <= current.high
        on_the_right_side = (
            current.close > ema_fast if is_long else current.close < ema_fast
        )
        if (
            not touched
            or not on_the_right_side
            or distance_ratio > self.max_distance_to_ema_ratio
        ):
            return None

        # 3. bougie de reprise
        body = abs(current.close - current.open)
        candle_range = current.high - current.low
        body_ratio = body / candle_range if candle_range else 0.0
        if is_long:
            if not (current.close > current.open and current.close > previous.close):
                return None
        else:
            if not (current.close < current.open and current.close < previous.close):
                return None
        if body_ratio < self.min_resumption_body_ratio:
            return None

        # 4. invalidation structurelle
        pullback_low = min(bar.low for bar in window)
        pullback_high = max(bar.high for bar in window)
        buffer = candle_range * self.stop_buffer_ratio
        if is_long:
            invalidation = pullback_low - buffer
            direction = OrderSide.BUY
        else:
            invalidation = pullback_high + buffer
            direction = OrderSide.SELL

        quality = max(
            0.0,
            min(1.0, body_ratio)
            * min(
                1.0,
                1.0
                - distance_ratio / max(self.max_distance_to_ema_ratio, 1e-9),
            ),
        )
        touched_bars = 0
        for bar in reversed(window):
            interacted = (
                bar.low <= ema_fast if is_long else bar.high >= ema_fast
            )
            if not interacted:
                break
            touched_bars += 1
        reasons = (
            "trend confirmed by the regime detector",
            f"pullback touched the ema fast ({distance_ratio:.6f} distance)",
            f"resumption candle body ratio {body_ratio:.3f}",
            f"{touched_bars} bar(s) interacted with the ema fast",
            f"invalidation at the structural level {invalidation:.5f}",
        )

        if is_long and not invalidation < current.close:
            return None
        if not is_long and not invalidation > current.close:
            return None

        return SetupDetection(
            direction=direction,
            reference_price=current.close,
            invalidation_price=invalidation,
            target_price=None,
            pullback_low=pullback_low,
            pullback_high=pullback_high,
            distance_to_ema=distance_ratio,
            bars_in_pullback=touched_bars,
            quality=quality,
            reasons=reasons,
            data_refs=(f"bar[{current.ts_open_ns}]",),
        )
