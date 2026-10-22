"""Risk governor contract and the minimal Phase 2 implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from typing import Any

from ..core.config import RiskConfig
from ..core.events import RiskDecision
from ..core.models import AccountState, AuditEvent
from ..core.types import OrderSide
from ..execution.accounting import PortfolioSnapshot
from .killswitch import KillSwitch


@dataclass(frozen=True)
class OrderRequest:
    """A request for authorisation, produced by the execution layer."""

    symbol: str
    side: OrderSide
    quantity: float
    reference_price: float
    stop_price: float | None = None

    @property
    def notional(self) -> float:
        """Absolute value of the request in the quote currency."""
        return abs(self.quantity) * self.reference_price

    @property
    def risk_amount(self) -> float:
        """Monetary risk of the request, when a stop is known."""
        if self.stop_price is None:
            return 0.0
        return abs(self.quantity) * abs(self.reference_price - self.stop_price)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "reference_price": self.reference_price,
            "stop_price": self.stop_price,
            "notional": self.notional,
            "risk_amount": self.risk_amount,
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
    """Governor: taille, notionnel, positions, risque par operation, challenge.

    Le contrat reste minimal et injectable : les limites avancees du challenge
    (perte journaliere, perte totale, drawdown) sont appliquees par
    delegation a un moteur de challenge, lorsqu'il est fourni.
    """

    def __init__(
        self,
        config: RiskConfig,
        challenge: Any | None = None,
        kill_switch: KillSwitch | None = None,
        account_state: Any | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.challenge = challenge
        self.kill_switch = kill_switch or KillSwitch(
            config.kill_switch_path if config.kill_switch_path else None
        )
        self._account_state = account_state
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

        if self.kill_switch.engaged:
            return RiskDecision(
                approved=False,
                reason=(
                    f"kill switch engaged: {self.kill_switch.state.reason or 'no reason given'}"
                ),
            )

        if self.config.require_stop_loss and request.stop_price is None:
            return RiskDecision(
                approved=False,
                reason="a stop loss is required by the active risk profile",
            )

        if (
            self.config.max_risk_per_trade > 0
            and request.stop_price is not None
            and request.risk_amount > self.config.max_risk_per_trade
        ):
            return RiskDecision(
                approved=False,
                reason=(
                    f"risk amount {request.risk_amount:.2f} exceeds the authorised "
                    f"maximum {self.config.max_risk_per_trade:.2f}"
                ),
            )

        if self.challenge is not None:
            blocked, reason = self.challenge.blocks_new_risk()
            if blocked:
                return RiskDecision(approved=False, reason=reason)

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

        exposure_limit = self.config.max_leverage * max(0.0, snapshot.equity)
        if request.notional > exposure_limit:
            return RiskDecision(
                approved=False,
                reason=(
                    f"notional {request.notional:.2f} exceeds the exposure limit "
                    f"{exposure_limit:.2f} (leverage {self.config.max_leverage} on "
                    f"equity {snapshot.equity:.2f})"
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
