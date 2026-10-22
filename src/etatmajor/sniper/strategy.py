"""Adaptateur du Sniper Engine au contrat de strategie.

La strategie ne fait qu'un travail : traduire la decision du Sniper Engine
en proposition (`Signal`) ou en abstention. Elle ne modifie jamais la
decision, ne contourne jamais le RiskGovernor et n'invente jamais de plan.
"""

from __future__ import annotations

from typing import Sequence

from ..core.events import Signal
from ..core.types import SignalAction
from ..sniper.engine import SniperDecision, SniperEngine
from ..strategies.base import StrategyContext


class SniperStrategy:
    """Strategie de reference pilotee par le Sniper Engine."""

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        engine: SniperEngine | None = None,
    ) -> None:
        # Un moteur injecte n'est jamais mute : il appartient a son appelant.
        self.engine = engine or SniperEngine(symbol=symbol, timeframe=timeframe)
        self.strategy_id = self.engine.strategy_id
        self.strategy_version = self.engine.strategy_version
        self.decisions: list[SniperDecision] = []
        self.abstentions = 0
        self.engagements = 0

    # -- cycle de vie --------------------------------------------------
    def on_start(self, context: StrategyContext) -> None:
        self.decisions = []
        self.abstentions = 0
        self.engagements = 0

    def on_bar(self, context: StrategyContext) -> Sequence[Signal]:
        decision = self.engine.evaluate(context)
        self.decisions.append(decision)
        if decision.intent is None:
            self.abstentions += 1
            return []
        self.engagements += 1
        plan = decision.intent.plan
        side = (
            SignalAction.BUY
            if plan.side.value == "BUY"
            else SignalAction.SELL
        )
        return [
            Signal(
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                symbol=plan.symbol,
                timeframe=plan.timeframe,
                decision_ts_ns=context.clock.now(),
                action=side,
                quantity=plan.quantity,
                order_type=plan.order_type,
                stop_price=plan.stop_price,
                reason=plan.rationale,
                data_refs=plan.data_refs,
                expires_ts_ns=plan.expires_ts_ns,
                plan=plan,
            )
        ]

    def on_stop(self, context: StrategyContext) -> None:
        return None
