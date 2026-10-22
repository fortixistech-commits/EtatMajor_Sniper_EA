"""Enumerations shared by the data, execution, risk and reporting layers."""

from __future__ import annotations

from enum import Enum


class OrderSide(str, Enum):
    """Direction of an order."""

    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """``+1`` for a buy, ``-1`` for a sell."""
        return 1 if self is OrderSide.BUY else -1

    @property
    def opposite(self) -> "OrderSide":
        """The opposing side."""
        return OrderSide.SELL if self is OrderSide.BUY else OrderSide.BUY


class OrderType(str, Enum):
    """Supported order types in the Phase 2 simulated broker."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    """Lifecycle states of an order.

    The state machine is deliberately explicit:

    ``PENDING`` -> ``ACCEPTED`` -> ``FILLED``
                             -> ``CANCELLED``
                             -> ``REJECTED``
    """

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(str, Enum):
    """Supported time-in-force policies."""

    GTC = "GTC"
    IOC = "IOC"
    DAY = "DAY"


class EndOfReplayPolicy(str, Enum):
    """Policy applied to pending orders and open positions at replay end."""

    CLOSE_AT_LAST_PRICE = "CLOSE_AT_LAST_PRICE"
    MARK_TO_MARKET = "MARK_TO_MARKET"


class SignalAction(str, Enum):
    """Action requested by a strategy."""

    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class EventType(str, Enum):
    """Types of events recorded in the journal."""

    BAR = "BAR"
    SIGNAL = "SIGNAL"
    RISK_DECISION = "RISK_DECISION"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    REPLAY_STARTED = "REPLAY_STARTED"
    REPLAY_FINISHED = "REPLAY_FINISHED"
    ERROR = "ERROR"
