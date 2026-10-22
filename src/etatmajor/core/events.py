"""Event and domain objects exchanged between the components.

Every object here is immutable and JSON-serialisable: the journal and the
reports are built from these objects, which guarantees that a run can be
replayed and audited from the recorded events alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import MissionPlan
from .types import OrderSide, OrderStatus, OrderType, SignalAction


@dataclass(frozen=True)
class Signal:
    """A structured trading proposal produced by a strategy.

    A strategy either emits a :class:`Signal` or explicitly emits nothing
    (absence of opportunity). The absence of a signal is never implicit.
    """

    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    decision_ts_ns: int
    action: SignalAction
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    reason: str = ""
    data_refs: tuple[str, ...] = ()
    expires_ts_ns: int | None = None
    plan: MissionPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["order_type"] = self.order_type.value
        payload["data_refs"] = list(self.data_refs)
        payload["plan"] = self.plan.to_dict() if self.plan is not None else None
        return payload


@dataclass(frozen=True)
class RiskDecision:
    """Verdict of the risk authority for a given order request."""

    approved: bool
    reason: str = ""
    risk_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Order:
    """An order tracked by the simulated broker."""

    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    status: OrderStatus = OrderStatus.PENDING
    limit_price: float | None = None
    stop_price: float | None = None
    created_ts_ns: int = 0
    submit_ts_ns: int = 0
    updated_ts_ns: int = 0
    reason: str = ""
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    commission: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value
        payload["order_type"] = self.order_type.value
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class Fill:
    """A single execution against an order."""

    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    ts_ns: int
    liquidity: str = "TAKER"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value
        return payload


@dataclass
class Position:
    """A netted position on a single instrument."""

    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    realized_pnl: float = 0.0
    commission: float = 0.0
    opened_ts_ns: int = 0
    last_price: float = 0.0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0.0

    def unrealized_pnl(self, mark_price: float) -> float:
        """Unrealised PnL of the position valued at ``mark_price``."""
        if self.quantity == 0.0:
            return 0.0
        direction = 1.0 if self.quantity > 0 else -1.0
        return self.quantity * (mark_price - self.average_price) * direction

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_flat"] = self.is_flat
        return payload


@dataclass
class JournalEntry:
    """A structured, timestamped entry of the event journal."""

    seq: int
    ts_ns: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts_ns": self.ts_ns,
            "type": self.type,
            "payload": self.payload,
        }
