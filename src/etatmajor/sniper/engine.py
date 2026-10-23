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
from ..data.instruments import BrokerSymbolSpec, InstrumentSpec
from ..strategies.base import StrategyContext
from .context import ContextDecision, ContextFilter
from .market_intelligence import (
    DataQualityAssessment,
    HtfAlignment,
    MarketIntelligence,
    MarketIntelligenceSnapshot,
    MarketStructure,
    TIMEFRAME_NS,
    VolatilityRegime,
)
from .planner import MissionPlanner, PlanningError
from .regime import MarketRegime, RegimeDetector, RegimeSnapshot
from .setup import PullbackSetupDetector, SetupDetection


@dataclass(frozen=True)
class DoctrinePolicy:
    """Seuils explicites de la doctrine, separes de l'orchestration.

    Les valeurs par defaut preservent le comportement historique, sauf
    `max_open_positions` : une mission a la fois par instrument. Les autres
    gardes sont activables pour les campagnes G4/G5.
    """

    min_confidence: float = 0.0
    min_setup_quality: float = 0.0
    require_structure_alignment: bool = False
    require_htf_alignment: bool = False
    block_extreme_volatility: bool = False
    max_open_positions: int = 1

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        if not 0.0 <= self.min_setup_quality <= 1.0:
            raise ValueError("min_setup_quality must be in [0, 1]")
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be >= 0")


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
    intelligence: MarketIntelligenceSnapshot | None = None

    def to_dict(self) -> dict:
        return {
            "engaged": self.intent is not None,
            "abstained": self.abstained,
            "reasons": list(self.reasons),
            "regime": self.regime.to_dict() if self.regime else None,
            "intelligence": (
                self.intelligence.to_dict() if self.intelligence else None
            ),
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
        market_intelligence: MarketIntelligence | None = None,
        data_quality: DataQualityAssessment | Any | None = None,
        higher_timeframe_factor: int | None = None,
        max_missing_ratio: float = 0.10,
        policy: DoctrinePolicy | None = None,
        instrument: InstrumentSpec | None = None,
        broker_spec: BrokerSymbolSpec | None = None,
        account_currency: str | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.regime_detector = regime_detector or RegimeDetector()
        self.context_filter = context_filter or ContextFilter()
        self.setup_detector = setup_detector or PullbackSetupDetector()
        self.planner = planner or MissionPlanner()
        self._market_snapshot = market_snapshot
        self.market_intelligence = market_intelligence or MarketIntelligence(
            regime_detector=self.regime_detector,
            base_timeframe_ns=TIMEFRAME_NS.get(timeframe, 60_000_000_000),
        )
        self.data_quality = data_quality
        self.higher_timeframe_factor = higher_timeframe_factor
        self.max_missing_ratio = max_missing_ratio
        self.policy = policy or DoctrinePolicy()
        self.instrument = instrument
        self.broker_spec = broker_spec
        self.account_currency = account_currency

    def evaluate(self, context: StrategyContext) -> SniperDecision:
        """Decide d'engager ou de s'abstenir."""
        assessment = self.data_quality
        if assessment is not None and not isinstance(
            assessment, DataQualityAssessment
        ):
            assessment = DataQualityAssessment.from_report(assessment)

        intelligence = self.market_intelligence.evaluate(
            list(context.visible_bars),
            now_ts_ns=context.clock.now(),
            data_quality=assessment,
            higher_timeframe_factor=self.higher_timeframe_factor,
        )
        regime = intelligence.regime

        if intelligence.data_quality.missing_ratio > self.max_missing_ratio:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(
                    "data quality is insufficient: "
                    f"{intelligence.data_quality.missing_ratio:.1%} of expected bars "
                    f"are missing (maximum {self.max_missing_ratio:.1%})",
                ),
                regime=regime,
                intelligence=intelligence,
            )

        if (
            self.policy.max_open_positions > 0
            and self._position_quantity(context, self.symbol) != 0.0
        ):
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(
                    f"one mission at a time: a position on {self.symbol} is still open",
                ),
                regime=regime,
                intelligence=intelligence,
            )

        if not regime.is_trending:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(f"no trend to exploit: regime is {regime.regime.value}",),
                regime=regime,
                intelligence=intelligence,
            )

        if intelligence.confidence < self.policy.min_confidence:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(
                    f"market confidence {intelligence.confidence:.3f} is below the "
                    f"policy minimum {self.policy.min_confidence:.3f}",
                ),
                regime=regime,
                intelligence=intelligence,
            )

        if self.policy.require_structure_alignment:
            expected = (
                MarketStructure.BULLISH
                if regime.regime is MarketRegime.TREND_UP
                else MarketStructure.BEARISH
            )
            if intelligence.structure is not expected:
                return SniperDecision(
                    intent=None,
                    abstained=True,
                    reasons=(
                        f"market structure {intelligence.structure.value} does not "
                        f"confirm the {regime.regime.value} regime",
                    ),
                    regime=regime,
                    intelligence=intelligence,
                )

        if self.policy.require_htf_alignment:
            higher = intelligence.higher_timeframe
            if higher is None or higher.alignment is not HtfAlignment.ALIGNED:
                actual = higher.alignment.value if higher else "UNAVAILABLE"
                return SniperDecision(
                    intent=None,
                    abstained=True,
                    reasons=(
                        f"higher timeframe alignment is {actual}, "
                        "the policy requires ALIGNED",
                    ),
                    regime=regime,
                    intelligence=intelligence,
                )

        if (
            self.policy.block_extreme_volatility
            and intelligence.volatility_regime is VolatilityRegime.EXTREME
        ):
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=("volatility is extreme; engagement is suspended",),
                regime=regime,
                intelligence=intelligence,
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
                intelligence=intelligence,
            )

        setup = self.setup_detector.detect(list(context.visible_bars), regime)
        if setup is None:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=("no configuration detected on the current bar",),
                regime=regime,
                context=context_decision,
                intelligence=intelligence,
            )

        if setup.quality < self.policy.min_setup_quality:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(
                    f"setup quality {setup.quality:.3f} is below the policy minimum "
                    f"{self.policy.min_setup_quality:.3f}",
                ),
                regime=regime,
                context=context_decision,
                setup=setup,
                intelligence=intelligence,
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
                instrument=self.instrument,
                broker_spec=self.broker_spec,
                account_currency=self.account_currency,
            )
        except PlanningError as exc:
            return SniperDecision(
                intent=None,
                abstained=True,
                reasons=(f"the mission cannot be planned: {exc}",),
                regime=regime,
                context=context_decision,
                setup=setup,
                intelligence=intelligence,
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
            intelligence=intelligence,
        )

    def _position_quantity(self, context: StrategyContext, symbol: str) -> float:
        """Position nette du portefeuille visible, sans supposer son type."""
        portfolio = getattr(context, "portfolio", None)
        if portfolio is None:
            return 0.0
        for position in getattr(portfolio, "positions", ()):
            if position.get("symbol") == symbol:
                return float(position.get("quantity", 0.0))
        return 0.0

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
