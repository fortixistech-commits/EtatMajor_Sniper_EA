"""Planification de mission : du setup detecte au plan complet.

Un plan sans plan complet est interdit : le planificateur produit un
`MissionPlan` valide (niveau d'invalidation, stop, taille, risque, couts,
duree) ou refuse de produire quoi que ce soit, avec un motif.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.models import MissionPlan
from ..core.types import OrderType
from .setup import SetupDetection


class PlanningError(Exception):
    """Le plan ne peut pas etre construit (conditions insuffisantes)."""


@dataclass
class MissionPlanner:
    """Construit le plan de mission d'un setup detecte."""

    risk_amount: float = 10.0
    reward_risk_multiple: float = 2.0
    stop_buffer_ratio: float = 0.0
    max_duration_ns: int | None = None
    validity_ns: int | None = None
    volume_step: float = 0.01
    min_quantity: float = 0.01
    estimated_cost_per_unit: float = 0.0

    def plan(
        self,
        setup: SetupDetection,
        symbol: str,
        timeframe: str,
        strategy_id: str,
        strategy_version: str,
        created_ts_ns: int,
        plan_id: str,
    ) -> MissionPlan:
        """Construit un plan complet, ou leve `PlanningError`."""
        if self.risk_amount <= 0:
            raise PlanningError("risk amount must be strictly positive")

        entry = setup.reference_price
        stop = setup.invalidation_price
        distance = abs(entry - stop)
        if distance <= 0:
            raise PlanningError("the invalidation level is at the entry price")

        raw_quantity = self.risk_amount / distance
        quantity = math.floor(raw_quantity / self.volume_step) * self.volume_step
        quantity = round(quantity, 8)
        if quantity < self.min_quantity:
            raise PlanningError(
                f"the risk amount {self.risk_amount:.2f} is too small for a stop at "
                f"{distance:.5f}: the computed quantity {quantity} is below the "
                f"minimum {self.min_quantity}"
            )

        if setup.direction.value == "BUY":
            target = entry + self.reward_risk_multiple * distance
        else:
            target = entry - self.reward_risk_multiple * distance

        return MissionPlan(
            plan_id=plan_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            symbol=symbol,
            timeframe=timeframe,
            side=setup.direction,
            order_type=OrderType.MARKET,
            created_ts_ns=created_ts_ns,
            quantity=quantity,
            entry_price=entry,
            stop_price=stop,
            risk_amount=round(quantity * distance, 8),
            estimated_costs=round(quantity * self.estimated_cost_per_unit, 8),
            target_price=round(target, 10),
            max_duration_ns=self.max_duration_ns,
            expires_ts_ns=(
                created_ts_ns + self.validity_ns if self.validity_ns else None
            ),
            invalidation_reason=(
                f"structural invalidation of the pullback at {stop:.5f}"
            ),
            rationale="; ".join(setup.reasons),
            data_refs=setup.data_refs,
        )
