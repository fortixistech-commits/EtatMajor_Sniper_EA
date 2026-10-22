"""Risk governor contract and the minimal Phase 2 implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..core.config import RiskConfig
from ..core.events import RiskDecision
from ..core.models import AuditEvent
from ..core.types import OrderSide
from ..execution.accounting import PortfolioSnapshot


@dataclass(frozen=True)
class OrderRequest:
    """A request for authorisation, produced by the execution layer."""

    symbol: str
    side: OrderSide
    quantity: float
    reference_price: float

    @property
    def notional(self) -> float:
        """Absolute value of the request in the quote currency."""
        return abs(self.quantity) * self.reference_price

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "reference_price": self.reference_price,
            "notional": self.notional,
        }


@runtime_checkable
class RiskGovernor(Protocol):
    """Authority able to authorise or refuse an order.

    The contract is intentionally minimal so that it can be replaced by the
    Phase 5 governor (daily loss, drawdown, challenge profile) without touching
    the strategy engine.
    """

    def authorize(
        self, request: OrderRequest, snapshot: PortfolioSnapshot
    ) -> RiskDecision:
        """Return the verdict for ``request`` given the current portfolio."""
        ...


class MinimalRiskGovernor:
    """Phase 2 governor: position size, notional, open positions and halt."""

    def __init__(self, config: RiskConfig) -> None:
        config.validate()
        self.config = config
        self.audit: list[AuditEvent] = []

    def _record(self, request: OrderRequest, decision: RiskDecision, ts_ns: int) -> None:
        """Trace d'audit : chaque decision, autorisation ou refus, est conservee."""
        self.audit.append(
            AuditEvent(
                ts_ns=ts_ns,
                actor="risk-governor",
                action="AUTHORIZE" if decision.approved else "REFUSE",
                subject=f"{request.symbol} {request.side.value} {request.quantity}",
                reason=decision.reason,
                payload=request.to_dict(),
            )
        )

    def authorize(
        self,
        request: OrderRequest,
        snapshot: PortfolioSnapshot,
        ts_ns: int = 0,
    ) -> RiskDecision:
        decision = self._authorize(request, snapshot)
        self._record(request, decision, ts_ns)
        return decision

    def _authorize(
        self, request: OrderRequest, snapshot: PortfolioSnapshot
    ) -> RiskDecision:
        if self.config.trading_halted:
            return RiskDecision(approved=False, reason="trading is halted")

        if request.quantity <= 0:
            return RiskDecision(
                approved=False, reason="invalid quantity: must be strictly positive"
            )

        if request.quantity > self.config.max_position_quantity:
            return RiskDecision(
                approved=False,
                reason=(
                    f"quantity {request.quantity} exceeds the authorised maximum "
                    f"{self.config.max_position_quantity}"
                ),
            )

        if request.notional > self.config.max_order_notional:
            return RiskDecision(
                approved=False,
                reason=(
                    f"notional {request.notional:.2f} exceeds the authorised maximum "
                    f"{self.config.max_order_notional:.2f}"
                ),
            )

        if snapshot.open_positions >= self.config.max_open_positions:
            if not _reduces_existing_exposure(snapshot, request):
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"max open positions reached ({snapshot.open_positions} / "
                        f"{self.config.max_open_positions})"
                    ),
                )

        return RiskDecision(approved=True, reason="authorized by risk governor")


def _reduces_existing_exposure(
    snapshot: PortfolioSnapshot, request: OrderRequest
) -> bool:
    """``True`` when the request closes part of an existing position."""
    for position in snapshot.positions:
        if position["symbol"] != request.symbol:
            continue
        quantity = float(position["quantity"])
        if quantity == 0.0:
            continue
        if (quantity > 0) != (request.side is OrderSide.BUY):
            return True
    return False
