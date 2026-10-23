"""Risk governor contract and the minimal Phase 2 implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..core.config import RiskConfig
from ..core.events import RiskDecision
from ..core.models import AccountState, AuditEvent
from ..core.types import OrderSide
from ..execution.accounting import PortfolioSnapshot
from .killswitch import KillSwitch

_EPSILON = 1e-9


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
    """Governor: taille, exposition agregee, positions, risque, challenge.

    Le contrat reste minimal et injectable : les limites avancees du challenge
    (perte journaliere, perte totale, drawdown) sont appliquees par
    delegation a un moteur de challenge, lorsqu'il est fourni.

    L'exposition est toujours verifiee **apres** l'operation envisagee. Une
    demande opposee ne reduit l'exposition que pour la quantite qu'elle peut
    reellement cloturer : un ordre excedentaire qui retourne la position ne
    beneficie pas du traitement « reduction de risque ».
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
            config.kill_switch_path if config.kill_switch_path else None,
            required=config.kill_switch_required,
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

        # -- donnees d'entree : toute valeur douteuse est refusee ----------
        if not request.symbol or not str(request.symbol).strip():
            return RiskDecision(approved=False, reason="invalid symbol: must not be empty")

        if not _is_finite(request.quantity) or request.quantity <= 0:
            return RiskDecision(
                approved=False, reason="invalid quantity: must be strictly positive"
            )

        if not _is_finite(request.reference_price) or request.reference_price <= 0:
            return RiskDecision(
                approved=False,
                reason="invalid reference price: must be finite and strictly positive",
            )

        if request.stop_price is not None and (
            not _is_finite(request.stop_price) or request.stop_price <= 0
        ):
            return RiskDecision(
                approved=False,
                reason="invalid stop price: must be finite and strictly positive",
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

        if request.quantity > self.config.max_position_quantity:
            return RiskDecision(
                approved=False,
                reason=(
                    f"quantity {request.quantity} exceeds the authorised maximum "
                    f"{self.config.max_position_quantity}"
                ),
            )

        # -- exposition agregee avant / apres l'operation -------------------
        gross_before, gross_after = _projected_exposure(snapshot, request)
        exposure_limit = self.config.max_leverage * max(0.0, snapshot.equity)
        # Une vraie reduction est toujours acceptee (elle diminue le risque).
        # En revanche un retournement de position, meme s'il reduit
        # l'exposition brute, rouvre une exposition : il doit tenir dans la
        # limite. Sinon un ordre excedentaire contournerait le plafond.
        if (
            gross_after > exposure_limit + _EPSILON
            and not _is_pure_reduction(snapshot, request)
        ):
            return RiskDecision(
                approved=False,
                reason=(
                    f"projected gross exposure {gross_after:.2f} exceeds the exposure "
                    f"limit {exposure_limit:.2f} (leverage {self.config.max_leverage} on "
                    f"equity {snapshot.equity:.2f}); current exposure {gross_before:.2f}"
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
            if not _is_pure_reduction(snapshot, request):
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"max open positions reached ({snapshot.open_positions} / "
                        f"{self.config.max_open_positions}); only an order that "
                        f"reduces an existing position is allowed"
                    ),
                )

        return RiskDecision(approved=True, reason="authorized by risk governor")


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _position_price(position: dict, fallback: float) -> float:
    price = position.get("last_price", 0.0)
    if _is_finite(price) and float(price) > 0:
        return float(price)
    return float(fallback)


def _projected_exposure(
    snapshot: PortfolioSnapshot, request: OrderRequest
) -> tuple[float, float]:
    """Exposition brute (avant, apres) si l'ordre est execute.

    Le symbole cible est valorise au prix de reference de la demande ; les
    autres positions conservent leur dernier prix connu. Une position existante
    au meme symbole est augmentee, reduite ou retournee selon la quantite
    signee de la demande.
    """
    target_price = float(request.reference_price)
    signed = float(request.quantity) * request.side.sign
    gross_before = 0.0
    gross_after = 0.0
    target_seen = False

    for position in snapshot.positions:
        quantity = float(position.get("quantity", 0.0))
        is_target = position.get("symbol") == request.symbol
        if is_target:
            target_seen = True
            price = target_price
            after = quantity + signed
            if abs(after) < 1e-12:
                after = 0.0
        else:
            price = _position_price(position, target_price)
            after = quantity
        gross_before += abs(quantity) * price
        gross_after += abs(after) * price

    if not target_seen:
        gross_after += abs(signed) * target_price

    return gross_before, gross_after


def _is_pure_reduction(snapshot: PortfolioSnapshot, request: OrderRequest) -> bool:
    """``True`` si la demande ne fait que reduire une position existante.

    Une quantite superieure a la position (retournement) n'est pas une pure
    reduction : elle rouvre une exposition dans l'autre sens.
    """
    signed = request.quantity * request.side.sign
    for position in snapshot.positions:
        if position.get("symbol") != request.symbol:
            continue
        quantity = float(position.get("quantity", 0.0))
        if quantity == 0.0:
            continue
        if (quantity > 0) == (signed > 0):
            return False
        return request.quantity <= abs(quantity) + _EPSILON
    return False
