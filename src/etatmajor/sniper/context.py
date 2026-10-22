"""Filtre de contexte : les conditions de securite avant toute selection.

Ce filtre ne cherche pas d'opportunite. Il verifie que les conditions
d'engagement sont acceptables : donnee fiable et fraiche, session autorisee,
cout d'execution dans le domaine valide. Un refus ici est une **abstention**,
pas une erreur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from ..core.models import DataQuality, MarketSnapshot
from .regime import RegimeSnapshot


@dataclass(frozen=True)
class ContextDecision:
    """Decision du filtre de contexte."""

    allowed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    session: str = "unknown"
    spread: float = 0.0

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "session": self.session,
            "spread": self.spread,
        }


def session_of(ts_ns: int) -> str:
    """Session de marche (UTC) : elle est un filtre, pas une prediction."""
    hour = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).hour
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 16:
        return "new_york"
    if 0 <= hour < 7:
        return "asia"
    return "off_hours"


class ContextFilter:
    """Verifie que le contexte d'execution autorise un engagement."""

    def __init__(
        self,
        allowed_sessions: Sequence[str] = ("london", "new_york"),
        max_spread: float = 0.00030,
        max_data_age_ns: int = 5_000_000_000,
        require_fresh_data: bool = True,
        min_confidence: float = 0.0,
    ) -> None:
        self.allowed_sessions = tuple(allowed_sessions)
        self.max_spread = max_spread
        self.max_data_age_ns = max_data_age_ns
        self.require_fresh_data = require_fresh_data
        self.min_confidence = min_confidence

    def evaluate(
        self,
        ts_ns: int,
        market: MarketSnapshot | None,
        regime: RegimeSnapshot | None = None,
    ) -> ContextDecision:
        """Verifie le contexte et retourne la decision motivee."""
        reasons: list[str] = []
        session = session_of(ts_ns)

        if market is None:
            return ContextDecision(
                allowed=False,
                reasons=("no market snapshot available",),
                session=session,
            )

        if market.quality is not DataQuality.FRESH:
            reasons.append(f"market data quality is {market.quality.value}")
        if self.require_fresh_data and market.data_age_ns > self.max_data_age_ns:
            reasons.append(
                f"market data is stale ({market.data_age_ns} ns > {self.max_data_age_ns} ns)"
            )
        if market.spread > self.max_spread:
            reasons.append(
                f"spread {market.spread:.5f} exceeds the authorised maximum "
                f"{self.max_spread:.5f}"
            )
        if session not in self.allowed_sessions:
            reasons.append(f"session {session!r} is not authorised")
        if regime is not None and regime.confidence < self.min_confidence:
            reasons.append(
                f"regime confidence {regime.confidence:.3f} is below the minimum "
                f"{self.min_confidence:.3f}"
            )

        return ContextDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            session=session,
            spread=market.spread,
        )
