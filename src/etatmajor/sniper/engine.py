"""Sniper Engine : orchestration de la doctrine.

Cycle applique :

```text
reconnaissance (regime) -> filtres de securite (contexte) -> selection (setup)
-> planification (mission) -> intention (TradeIntent)
```

A chaque etape, une seule issue est possible : engager ou s'abstenir.
**L'abstention est un resultat valide** : elle est journalisee comme telle,
avec ses motifs, au meme titre qu'une entree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.models import MarketSnapshot, MissionPlan, TradeIntent
from ..strategies.base import StrategyContext
from .context import ContextDecision, ContextFilter
from .planner import MissionPlanner, PlanningError
from .regime import RegimeDetector, RegimeSnapshot
from .setup import PullbackSetupDetector, SetupDetection


@dataclass(frozen=True)
class SniperDecision:
    """Decision du Sniper Engine pour une bougie."""

    intent: TradeIntent | None
    abstained: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    regime: RegimeSnapshot | None = None
    context: ContextDecision | None = None
    setup: SetupDetection | None = None
    plan: MissionPlan | None = None

    def to_dict(self) -> dict:
        return {
            "engaged": self.intent is not None,
            "abstained": self.abstained,
            "reasons": list(self.reasons),
            "regime": self.regime.to_dict() if self.regime else None,
            "context": self.context.to_dict() if self.context else None,
            "setup": self.setup.to_dict() if self.setup else None,
            "plan": self.plan.to_dict() if self.plan else None,
        }


class SniperEngine:
    """Orchestre la doctrine Sniper sur un contexte de strategie."""

    strategy_id = "sniper-engine"
    strategy_version = "0.1.0"

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        regime_detector: RegimeDetector | None = None,
        context_filter: ContextFilter | None = None,
        setup_detector: PullbackSetupDetector | None = None,
        planner: MissionPlanner | None = None,
        market_snapshot: Any | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.regime_detector = regime_detector or RegimeDetector()
        self.context_filter = context_filter or ContextFilter()
        self.setup_detector = setup_detector or PullbackSetupDetector()
        self.planner = planner or MissionPlanner()
        self._market_snapshot = market_snapshot

    def evaluate(self, context: StrategyContext) -> SniperDecision:
        """Decide d'engager ou de s'abstenir."""
        reasons: list[str] = []

        regime = self.regime_detector.evaluate(list(context.visible_bars))
        if not regime.is_trending:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(f"no trend to exploit: regime is {regime.regime.value}",),
                regime=regime,
            )

        snapshot = self._market_snapshot
        if snapshot is None:
            snapshot = self._synthetic_snapshot(context)
        context_decision = self.context_filter.evaluate(
            context.clock.now(), snapshot, regime
        )
        if not context_decision.allowed:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=context_decision.reasons,
                regime=regime,
                context=context_decision,
            )

        setup = self.setup_detector.detect(list(context.visible_bars), regime)
        if setup is None:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=("no configuration detected on the current bar",),
                regime=regime,
                context=context_decision,
            )

        try:
            plan = self.planner.plan(
                setup,
                symbol=self.symbol,
                timeframe=self.timeframe,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                created_ts_ns=context.clock.now(),
                plan_id=f"PLAN-{context.index:06d}",
            )
        except PlanningError as exc:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(f"the mission cannot be planned: {exc}",),
                regime=regime,
                context=context_decision,
                setup=setup,
            )

        intent = TradeIntent(
            intent_id=f"INT-{context.index:06d}", plan=plan, decision_ts_ns=context.clock.now()
        )
        return SniperDecision(
            intent=intent,
            abstained=False,
            reasons=setup.reasons,
            regime=regime,
            context=context_decision,
            setup=setup,
            plan=plan,
        )

    def _synthetic_snapshot(self, context: StrategyContext) -> MarketSnapshot:
        """Instantane de marche derive des donnees visibles.

        En laboratoire, le spread est celui de la configuration d'execution ;
        la qualite est `FRESH` car les donnees sont par construction a jour.
        La freshness reelle sera verifiee par l'adaptateur de donnees live
        (Mission 8).
        """
        from ..core.models import DataQuality

        close = context.bar.close
        spread = 0.00010
        return MarketSnapshot(
            symbol=self.symbol,
            ts_ns=context.clock.now(),
            bid=round(close - spread / 2.0, 10),
            ask=round(close + spread / 2.0, 10),
            last_price=close,
            quality=DataQuality.FRESH,
            data_age_ns=0,
            max_data_age_ns=None,
        )
