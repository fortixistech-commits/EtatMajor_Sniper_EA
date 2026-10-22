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


class OperatingMode(str, Enum):
    """Operating mode of the platform.

    Switching from one mode to another is never implicit: each mode has its
    own capabilities and constraints, and a mode that is not available is
    refused at start-up with an explicit message.
    """

    LAB = "LAB"
    CHALLENGE_SIM = "CHALLENGE_SIM"
    PAPER = "PAPER"
    PRODUCTION = "PRODUCTION"

    @property
    def report_label(self) -> str:
        """Label displayed in the reports."""
        return "LABORATORY" if self is OperatingMode.LAB else self.value


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
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
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
