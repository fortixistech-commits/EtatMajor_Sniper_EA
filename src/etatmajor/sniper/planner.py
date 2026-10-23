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
from ..data.instruments import BrokerSymbolSpec, InstrumentSpec
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
        *,
        instrument: InstrumentSpec | None = None,
        broker_spec: BrokerSymbolSpec | None = None,
        account_currency: str | None = None,
    ) -> MissionPlan:
        """Construit un plan complet, ou leve `PlanningError`.

        Quand un instrument est fourni, ses contraintes (pas de volume,
        quantite minimale/maximale, precision) remplacent celles du
        planificateur. La valorisation du risque utilise `tick_value` et
        `contract_size` si disponibles et si la devise de cotation est
        compatible avec celle du compte.
        """
        if self.risk_amount <= 0:
            raise PlanningError("risk amount must be strictly positive")
        if self.reward_risk_multiple <= 0:
            raise PlanningError("reward/risk multiple must be strictly positive")
        if self.volume_step <= 0:
            raise PlanningError("volume step must be strictly positive")
        if self.min_quantity < 0:
            raise PlanningError("minimum quantity cannot be negative")
        if self.estimated_cost_per_unit < 0:
            raise PlanningError("estimated cost per unit cannot be negative")
        if self.validity_ns is not None and self.validity_ns <= 0:
            raise PlanningError("validity must be strictly positive")
        if self.max_duration_ns is not None and self.max_duration_ns <= 0:
            raise PlanningError("maximum duration must be strictly positive")

        precision = instrument.price_precision if instrument else None
        entry = setup.reference_price
        stop = setup.invalidation_price
        if precision is not None:
            entry = round(entry, precision)
            stop = round(stop, precision)
        distance = abs(entry - stop)
        if distance <= 0:
            raise PlanningError("the invalidation level is at the entry price")

        is_long = setup.direction.value == "BUY"
        if is_long and stop >= entry:
            raise PlanningError("a buy stop must be strictly below the entry price")
        if not is_long and stop <= entry:
            raise PlanningError("a sell stop must be strictly above the entry price")

        volume_step, min_quantity, max_quantity = self._constraints(
            instrument, broker_spec
        )
        risk_per_unit = self._risk_per_unit(
            instrument, distance, account_currency
        )

        raw_quantity = self.risk_amount / risk_per_unit
        quantity = math.floor(raw_quantity / volume_step) * volume_step
        if max_quantity is not None:
            quantity = min(
                quantity, math.floor(max_quantity / volume_step) * volume_step
            )
        quantity = round(quantity, 8)
        if quantity <= 0 or quantity < min_quantity:
            raise PlanningError(
                f"the risk amount {self.risk_amount:.2f} is too small for a stop at "
                f"{distance:.5f}: the computed quantity {quantity} is below the "
                f"minimum {min_quantity}"
            )

        if is_long:
            target = entry + self.reward_risk_multiple * distance
        else:
            target = entry - self.reward_risk_multiple * distance
        if precision is not None:
            target = round(target, precision)

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
            risk_amount=round(quantity * risk_per_unit, 8),
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

    def _constraints(
        self,
        instrument: InstrumentSpec | None,
        broker_spec: BrokerSymbolSpec | None,
    ) -> tuple[float, float, float | None]:
        volume_step = self.volume_step
        min_quantity = self.min_quantity
        max_quantity: float | None = None
        if instrument is not None:
            volume_step = instrument.quantity_step
            min_quantity = instrument.min_quantity
            max_quantity = instrument.max_quantity
        if broker_spec is not None:
            if instrument is not None and (
                broker_spec.instrument_id != instrument.instrument_id
            ):
                raise PlanningError(
                    f"broker symbol {broker_spec.symbol!r} maps to "
                    f"{broker_spec.instrument_id!r}, not "
                    f"{instrument.instrument_id!r}"
                )
            volume_step = broker_spec.quantity_step
            min_quantity = broker_spec.min_quantity
            if broker_spec.max_quantity is not None:
                max_quantity = broker_spec.max_quantity
        for name, value in (("volume step", volume_step), ("minimum", min_quantity)):
            if not math.isfinite(value) or value < 0:
                raise PlanningError(f"invalid {name} quantity constraint: {value}")
        if volume_step <= 0:
            raise PlanningError("volume step must be strictly positive")
        if max_quantity is not None and max_quantity < min_quantity:
            raise PlanningError("maximum quantity cannot be below the minimum")
        return volume_step, min_quantity, max_quantity

    def _risk_per_unit(
        self,
        instrument: InstrumentSpec | None,
        distance: float,
        account_currency: str | None,
    ) -> float:
        if instrument is None:
            return distance

        has_tick_value = (
            instrument.tick_value is not None
            and instrument.contract_size is not None
        )
        if has_tick_value:
            if (
                account_currency is not None
                and instrument.tick_value_currency is not None
                and instrument.tick_value_currency != account_currency
            ):
                raise PlanningError(
                    f"no conversion from {instrument.tick_value_currency} to "
                    f"account currency {account_currency}"
                )
            value_per_price_unit = instrument.tick_value / (
                instrument.tick_size * instrument.contract_size
            )
            if not math.isfinite(value_per_price_unit) or value_per_price_unit <= 0:
                raise PlanningError("invalid tick value or contract size")
            return distance * value_per_price_unit

        if (
            account_currency is not None
            and instrument.quote_currency.upper() != account_currency.upper()
        ):
            raise PlanningError(
                f"no conversion from {instrument.quote_currency} to account "
                f"currency {account_currency}; provide tick_value and contract_size"
            )
        return distance
