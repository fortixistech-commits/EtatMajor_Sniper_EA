"""Modeles metier du socle (Mission 1 du cahier des charges).

Ces objets sont les contrats ecrits entre les composants : ils sont
immuables, serialisables et valides a la construction quand un invariant est
essentiel. Un objet invalide est refuse : il ne doit jamais circuler sous
une forme incomplete, car un plan de mission incomplet ou une intention sans
risque defini sont explicitement interdits.

Les objets d'evenement (Signal, Order, Fill, Position, RiskDecision) restent
dans `core.events` : ils decrivent ce qui s'est produit. Les objets de ce
module decrivent **ce qui est decide**.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .types import OrderSide, OrderStatus, OrderType


class DataQuality(str, Enum):
    """Etat de confiance d'une donnee de marche."""

    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


class ChallengeState(str, Enum):
    """Etats de la machine a etats du challenge (Mission 7)."""

    READY = "READY"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INVALID = "INVALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def is_conclusive(self) -> bool:
        """``True`` si l'etat constitue un verdict."""
        return self in (ChallengeState.PASSED, ChallengeState.FAILED)


@dataclass(frozen=True)
class MarketTick:
    """Un tick unitaire (preparation de l'adaptateur MT5, Mission 8)."""

    symbol: str
    ts_ns: int
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0

    def __post_init__(self) -> None:
        if self.ask < self.bid:
            raise ValueError(f"ask ({self.ask}) must be greater than bid ({self.bid})")
        if self.bid <= 0:
            raise ValueError(f"bid must be strictly positive (got {self.bid})")

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketSnapshot:
    """Etat du marche disponible a l'instant de la decision.

    ``data_age_ns`` est l'anciennete de la donnee au moment de la decision :
    une donnee perimee doit bloquer la decision, pas seulement l'alerter.
    """

    symbol: str
    ts_ns: int
    bid: float
    ask: float
    last_price: float
    quality: DataQuality = DataQuality.UNVERIFIED
    data_age_ns: int = 0
    max_data_age_ns: int | None = None

    def __post_init__(self) -> None:
        if self.ask < self.bid:
            raise ValueError(f"ask ({self.ask}) must be greater than bid ({self.bid})")
        if self.bid <= 0:
            raise ValueError(f"bid must be strictly positive (got {self.bid})")

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def is_fresh(self) -> bool:
        """``True`` si la donnee est assez recente pour autoriser une decision."""
        if self.quality is not DataQuality.FRESH:
            return False
        if self.max_data_age_ns is None:
            return True
        return self.data_age_ns <= self.max_data_age_ns

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quality"] = self.quality.value
        return payload


@dataclass(frozen=True)
class MissionPlan:
    """Plan complet d'une operation, prealable a tout engagement.

    Un plan sans invalidation, sans stop ou sans risque calcule est
    **incomplet** : il est refuse a la construction. C'est l'application
    directe de la doctrine : « un ordre sans plan complet est interdit ».
    """

    plan_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    side: OrderSide
    order_type: OrderType
    created_ts_ns: int
    quantity: float
    entry_price: float
    stop_price: float
    risk_amount: float
    estimated_costs: float = 0.0
    target_price: float | None = None
    max_duration_ns: int | None = None
    expires_ts_ns: int | None = None
    invalidation_reason: str = ""
    rationale: str = ""
    data_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be strictly positive (got {self.quantity})")
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be strictly positive (got {self.entry_price})")
        if self.stop_price <= 0:
            raise ValueError(f"stop_price must be strictly positive (got {self.stop_price})")
        if self.risk_amount <= 0:
            raise ValueError(f"risk_amount must be strictly positive (got {self.risk_amount})")
        if not self.invalidation_reason:
            raise ValueError("a mission plan must declare its invalidation level")
        if self.side is OrderSide.BUY and self.stop_price >= self.entry_price:
            raise ValueError(
                f"a long plan requires stop_price < entry_price "
                f"(stop={self.stop_price}, entry={self.entry_price})"
            )
        if self.side is OrderSide.SELL and self.stop_price <= self.entry_price:
            raise ValueError(
                f"a short plan requires stop_price > entry_price "
                f"(stop={self.stop_price}, entry={self.entry_price})"
            )
        if self.target_price is not None:
            if self.side is OrderSide.BUY and self.target_price <= self.entry_price:
                raise ValueError("a long plan requires target_price > entry_price")
            if self.side is OrderSide.SELL and self.target_price >= self.entry_price:
                raise ValueError("a short plan requires target_price < entry_price")

    @property
    def risk_per_unit(self) -> float:
        """Distance de risque par unite de taille."""
        return abs(self.entry_price - self.stop_price)

    @property
    def reward_risk_ratio(self) -> float | None:
        """Ratio rendement/risque apres couts, ``None`` si pas d'objectif."""
        if self.target_price is None:
            return None
        reward = abs(self.target_price - self.entry_price)
        risk = self.risk_per_unit
        if risk == 0:
            return None
        return (reward - self.estimated_costs / self.quantity) / risk

    def is_expired(self, now_ns: int) -> bool:
        """``True`` si le plan a expire a l'instant ``now_ns``."""
        return self.expires_ts_ns is not None and self.expires_ts_ns < now_ns

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value
        payload["order_type"] = self.order_type.value
        payload["data_refs"] = list(self.data_refs)
        return payload


@dataclass(frozen=True)
class TradeIntent:
    """Intention de trade prete a etre soumise a l'autorite de risque.

    L'intention encapsule un plan valide ; elle ne porte jamais les limites
    de risque : celles-ci appartiennent au RiskGovernor.
    """

    intent_id: str
    plan: MissionPlan
    decision_ts_ns: int

    @property
    def symbol(self) -> str:
        return self.plan.symbol

    @property
    def side(self) -> OrderSide:
        return self.plan.side

    @property
    def quantity(self) -> float:
        return self.plan.quantity

    @property
    def reference_price(self) -> float:
        """Prix de reference pour le calcul du risque (prix d'entree)."""
        return self.plan.entry_price

    @property
    def notional(self) -> float:
        return abs(self.plan.quantity) * self.plan.entry_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "decision_ts_ns": self.decision_ts_ns,
            "plan": self.plan.to_dict(),
        }


@dataclass(frozen=True)
class OrderResult:
    """Resultat d'un ordre soumis a un broker (simule ou reel)."""

    order_id: str
    client_order_id: str
    symbol: str
    status: OrderStatus
    ts_ns: int
    reason: str = ""
    filled_quantity: float = 0.0
    average_price: float = 0.0
    commission: float = 0.0

    @property
    def is_filled(self) -> bool:
        return self.status is OrderStatus.FILLED

    @property
    def is_rejected(self) -> bool:
        return self.status is OrderStatus.REJECTED

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class AccountState:
    """Etat du compte : capital, solde, equity, marge."""

    account_id: str
    currency: str
    balance: float
    equity: float
    ts_ns: int
    margin_used: float = 0.0
    margin_available: float = 0.0

    @property
    def drawdown_amount(self) -> float:
        """Perte latente par rapport au solde (solde - equity)."""
        return self.balance - self.equity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioState:
    """Vue du portefeuille : positions, ordres ouverts, exposition."""

    ts_ns: int
    positions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    open_orders: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    exposure_by_symbol: dict[str, float] = field(default_factory=dict)
    gross_exposure: float = 0.0
    net_exposure: float = 0.0

    @property
    def open_positions(self) -> int:
        return sum(1 for position in self.positions if abs(position.get("quantity", 0.0)) > 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_ns": self.ts_ns,
            "positions": [dict(p) for p in self.positions],
            "open_orders": [dict(o) for o in self.open_orders],
            "exposure_by_symbol": dict(self.exposure_by_symbol),
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
        }


@dataclass(frozen=True)
class ExecutionEvent:
    """Evenement d'execution type (complete le journal d'evenements)."""

    ts_ns: int
    kind: str
    symbol: str
    order_id: str = ""
    side: OrderSide | None = None
    quantity: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    liquidity: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value if self.side is not None else None
        return payload


@dataclass(frozen=True)
class AuditEvent:
    """Evenement d'audit : qui a fait quoi, pourquoi."""

    ts_ns: int
    actor: str
    action: str
    subject: str = ""
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
