"""Deterministic historical replay engine.

Timeline of a bar ``i``
-----------------------
1. ``ts_open(i)``: the broker processes the orders that were accepted at the
   close of bar ``i-1``. Market orders fill at the open of bar ``i``.
2. ``ts_close(i)``: the bar becomes observable. The portfolio is marked at the
   close, the strategy receives the bar and may emit proposals.
3. Proposals are submitted to the risk authority; accepted orders are queued
   for execution at ``ts_open(i+1)``.

Because a proposal is only submitted *after* the close of the bar that
produced it, and executed at the open of the *next* bar, a strategy can never
be executed on information it did not have (anti-look-ahead rule).

The engine never reads the wall clock and never opens a network connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.clock import SimClock
from ..core.config import AppConfig
from ..core.events import Fill, Order, Signal
from ..core.journal import Journal
from ..core.types import EventType, OrderSide, OrderStatus, OrderType, SignalAction
from ..data.loader import Dataset
from ..execution.accounting import Portfolio
from ..execution.broker import SimulatedBroker
from ..risk.governor import MinimalRiskGovernor, OrderRequest, RiskGovernor
from ..strategies.base import Strategy, StrategyContext


@dataclass
class ReplayResult:
    """Everything produced by a replay run."""

    report: dict
    journal: Journal
    portfolio: Portfolio
    broker: SimulatedBroker
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    risk_rejections: list[dict] = field(default_factory=list)
    broker_rejections: list[dict] = field(default_factory=list)


class ReplayEngine:
    """Replay a dataset against a strategy, a risk authority and a broker."""

    def __init__(
        self,
        dataset: Dataset,
        config: AppConfig,
        strategy: Strategy,
        risk_governor: RiskGovernor | None = None,
        broker: SimulatedBroker | None = None,
        journal: Journal | None = None,
    ) -> None:
        config.validate()
        if not dataset.bars:
            raise ValueError("cannot replay an empty dataset")

        self.dataset = dataset
        self.config = config
        self.strategy = strategy
        self.risk_governor = risk_governor or MinimalRiskGovernor(config.risk)
        self.broker = broker or SimulatedBroker(
            config.execution, seed=config.simulation.seed
        )
        self.journal = journal or Journal()
        self.portfolio = Portfolio(
            config.simulation.initial_capital, currency=config.simulation.currency
        )
        self.clock = SimClock()
        self.risk_rejections: list[dict] = []
        self.broker_rejections: list[dict] = []

    # -- main loop ----------------------------------------------------
    def run(self) -> ReplayResult:
        symbol = self.dataset.symbol
        self.journal.append(
            self.clock.now(),
            EventType.REPLAY_STARTED.value,
            {
                "symbol": symbol,
                "timeframe": self.dataset.timeframe,
                "bars": len(self.dataset.bars),
                "strategy_id": getattr(self.strategy, "strategy_id", "unknown"),
                "config_fingerprint": self.config.fingerprint(),
                "dataset_fingerprint": self.dataset.fingerprint(),
                "end_of_replay_policy": self.config.simulation.end_of_replay_policy.value,
            },
        )

        bars = self.dataset.bars
        self._call_on_start(bars)
        for index, bar in enumerate(bars):
            self._process_bar_open(index, bar)
            self._process_bar_close(index, bar)

        self._finish_replay()
        return self._build_result()

    # -- steps --------------------------------------------------------
    def _call_on_start(self, bars) -> None:
        """Notify the strategy before the first bar.

        The context uses ``index = -1``: no bar has been consumed yet and no
        decision may be taken on it.
        """
        first = bars[0]
        self.clock = self.clock.advance_to(first.ts_open_ns)
        context = StrategyContext(
            index=-1,
            bar=first,
            visible_bars=(),
            clock=self.clock,
            portfolio=self.portfolio.snapshot(),
            recent_fills=(),
        )
        try:
            self.strategy.on_start(context)
        except Exception as exc:  # pragma: no cover - defensive
            self.journal.append(
                self.clock.now(),
                EventType.ERROR.value,
                {"where": "strategy.on_start", "error": repr(exc)},
            )
            raise

    def _process_bar_open(self, index: int, bar) -> None:
        self.clock = self.clock.advance_to(bar.ts_open_ns)
        fills = self.broker.on_bar_open(bar, bar.ts_open_ns, self.dataset.symbol)
        for fill in fills:
            before = self.portfolio.net_quantity(fill.symbol)
            position = self.portfolio.apply_fill(fill)
            after = position.quantity
            self.journal.append(
                fill.ts_ns,
                EventType.ORDER_FILLED.value,
                {
                    "order_id": fill.order_id,
                    "symbol": fill.symbol,
                    "side": fill.side.value,
                    "quantity": fill.quantity,
                    "price": fill.price,
                    "commission": fill.commission,
                    "position_quantity": after,
                    "execution_bar_index": index,
                    "execution_price_source": "bar_open",
                },
            )
            if before == 0.0 and after != 0.0:
                self.journal.append(
                    fill.ts_ns,
                    EventType.POSITION_OPENED.value,
                    {
                        "symbol": fill.symbol,
                        "quantity": after,
                        "average_price": position.average_price,
                    },
                )
            elif before != 0.0 and after == 0.0:
                self.journal.append(
                    fill.ts_ns,
                    EventType.POSITION_CLOSED.value,
                    {
                        "symbol": fill.symbol,
                        "realized_pnl": position.realized_pnl,
                        "commission": position.commission,
                    },
                )
            elif before != 0.0:
                self.journal.append(
                    fill.ts_ns,
                    EventType.POSITION_OPENED.value,
                    {
                        "symbol": fill.symbol,
                        "quantity": after,
                        "average_price": position.average_price,
                        "update": "increased",
                    },
                )
            else:
                self.journal.append(
                    fill.ts_ns,
                    EventType.POSITION_CLOSED.value,
                    {
                        "symbol": fill.symbol,
                        "realized_pnl": position.realized_pnl,
                        "commission": position.commission,
                        "update": "reduced",
                    },
                )

    def _process_bar_close(self, index: int, bar) -> None:
        self.clock = self.clock.advance_to(bar.ts_close_ns)
        self.portfolio.mark(self.dataset.symbol, bar.close)

        context = StrategyContext(
            index=index,
            bar=bar,
            visible_bars=tuple(self.dataset.bars[: index + 1]),
            clock=self.clock,
            portfolio=self.portfolio.snapshot(),
            recent_fills=tuple(self.broker.fills[-10:]),
        )
        try:
            signals = self.strategy.on_bar(context) or []
        except Exception as exc:  # pragma: no cover - defensive
            self.journal.append(
                self.clock.now(),
                EventType.ERROR.value,
                {"where": "strategy.on_bar", "error": repr(exc)},
            )
            raise

        for signal in signals:
            self._handle_signal(signal, bar, index)

    def _handle_signal(self, signal: Signal, bar, bar_index: int) -> None:
        self.journal.append(
            self.clock.now(),
            EventType.SIGNAL.value,
            {**signal.to_dict(), "signal_bar_index": bar_index},
        )
        if signal.action is SignalAction.NONE:
            return

        side = OrderSide.BUY if signal.action is SignalAction.BUY else OrderSide.SELL
        reference_price = (
            signal.limit_price
            if signal.limit_price is not None
            else signal.stop_price
            if signal.stop_price is not None
            else bar.close
        )
        request = OrderRequest(
            symbol=signal.symbol,
            side=side,
            quantity=signal.quantity,
            reference_price=float(reference_price),
        )
        decision = self.risk_governor.authorize(request, self.portfolio.snapshot())
        self.journal.append(
            self.clock.now(),
            EventType.RISK_DECISION.value,
            {
                "request": request.to_dict(),
                "approved": decision.approved,
                "reason": decision.reason,
                "risk_ns": decision.risk_ns,
            },
        )
        if not decision.approved:
            rejection = {
                "ts_ns": self.clock.now(),
                "stage": "risk",
                "symbol": request.symbol,
                "side": side.value,
                "quantity": request.quantity,
                "reason": decision.reason,
            }
            self.risk_rejections.append(rejection)
            self.journal.append(
                self.clock.now(),
                EventType.ORDER_REJECTED.value,
                rejection,
            )
            return

        order = Order(
            order_id=self.broker.new_order_id(),
            client_order_id="",
            symbol=request.symbol,
            side=side,
            order_type=signal.order_type,
            quantity=request.quantity,
            limit_price=signal.limit_price,
            stop_price=signal.stop_price,
            created_ts_ns=self.clock.now(),
            reason=signal.reason,
        )
        order.client_order_id = order.order_id
        self.broker.submit(order, self.clock.now())

        self.journal.append(
            self.clock.now(),
            EventType.ORDER_SUBMITTED.value,
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": side.value,
                "order_type": order.order_type.value,
                "quantity": order.quantity,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
                "strategy_id": signal.strategy_id,
            },
        )
        if order.status is OrderStatus.REJECTED:
            rejection = {
                "ts_ns": self.clock.now(),
                "stage": "broker",
                "symbol": order.symbol,
                "side": side.value,
                "quantity": order.quantity,
                "reason": order.reason,
            }
            self.broker_rejections.append(rejection)
            self.journal.append(
                self.clock.now(),
                EventType.ORDER_REJECTED.value,
                rejection,
            )
        else:
            self.journal.append(
                self.clock.now(),
                EventType.ORDER_ACCEPTED.value,
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "quantity": order.quantity,
                    "reason": signal.reason,
                },
            )

    # -- end of replay -------------------------------------------------
    def _finish_replay(self) -> None:
        bars = self.dataset.bars
        if not bars:
            return
        last_bar = bars[-1]
        self.clock = self.clock.advance_to(last_bar.ts_close_ns)
        symbol = self.dataset.symbol
        policy = self.config.simulation.end_of_replay_policy

        # 1. Pending orders are cancelled.
        for order in list(self.broker.open_orders()):
            self.broker.cancel(
                order, self.clock.now(), reason="cancelled by end-of-replay policy"
            )
            self.journal.append(
                self.clock.now(),
                EventType.ORDER_CANCELLED.value,
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "quantity": order.quantity,
                    "reason": "cancelled by end-of-replay policy",
                },
            )

        # 2. Open positions are closed or valued, depending on the policy.
        position = self.portfolio.positions.get(symbol)
        if position is not None and not position.is_flat:
            if policy.value == "CLOSE_AT_LAST_PRICE":
                self._close_position_at_last_price(position, last_bar)
            else:
                self.portfolio.mark(symbol, last_bar.close)
                self.journal.append(
                    self.clock.now(),
                    EventType.POSITION_CLOSED.value,
                    {
                        "symbol": symbol,
                        "update": "marked_to_market",
                        "quantity": position.quantity,
                        "mark_price": last_bar.close,
                        "unrealized_pnl": position.unrealized_pnl(last_bar.close),
                    },
                )

        self.journal.append(
            self.clock.now(),
            EventType.REPLAY_FINISHED.value,
            {
                "end_of_replay_policy": policy.value,
                "equity": self.portfolio.equity,
                "net_pnl": self.portfolio.net_pnl,
            },
        )

    def _close_position_at_last_price(self, position, last_bar) -> None:
        symbol = position.symbol
        side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
        quantity = abs(position.quantity)
        order = Order(
            order_id=self.broker.new_order_id(),
            client_order_id="",
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            created_ts_ns=self.clock.now(),
            reason="end-of-replay closure",
        )
        order.client_order_id = order.order_id
        self.broker.submit(order, self.clock.now())
        self.journal.append(
            self.clock.now(),
            EventType.ORDER_SUBMITTED.value,
            {
                "order_id": order.order_id,
                "symbol": symbol,
                "side": side.value,
                "order_type": order.order_type.value,
                "quantity": quantity,
                "reason": "end-of-replay closure",
            },
        )
        if order.status is OrderStatus.REJECTED:
            self.broker_rejections.append(
                {
                    "ts_ns": self.clock.now(),
                    "stage": "broker",
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "reason": order.reason,
                }
            )
            self.journal.append(
                self.clock.now(),
                EventType.ORDER_REJECTED.value,
                {
                    "ts_ns": self.clock.now(),
                    "stage": "broker",
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "reason": order.reason,
                },
            )
            return

        fill = self.broker.execute_market(order, self._synthetic_bar(last_bar), self.clock.now())
        if fill is None:  # pragma: no cover - market orders always fill
            return
        closed = self.portfolio.apply_fill(fill)
        self.journal.append(
            fill.ts_ns,
            EventType.ORDER_FILLED.value,
            {
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "price": fill.price,
                "commission": fill.commission,
                "position_quantity": closed.quantity,
                "reason": "end-of-replay closure",
            },
        )
        self.journal.append(
            fill.ts_ns,
            EventType.POSITION_CLOSED.value,
            {
                "symbol": fill.symbol,
                "realized_pnl": closed.realized_pnl,
                "commission": closed.commission,
                "reason": "end-of-replay closure",
            },
        )

    def _synthetic_bar(self, last_bar):
        """Bar whose open equals the last close, used for the final closure."""
        from ..data.models import Bar

        return Bar(
            ts_open_ns=self.clock.now(),
            ts_close_ns=self.clock.now(),
            open=last_bar.close,
            high=last_bar.close,
            low=last_bar.close,
            close=last_bar.close,
            volume=0.0,
        )

    # -- result --------------------------------------------------------
    def _build_result(self) -> ReplayResult:
        from ..reporting.report import build_report

        report = build_report(
            dataset=self.dataset,
            config=self.config,
            portfolio=self.portfolio,
            broker=self.broker,
            strategy=self.strategy,
            risk_rejections=self.risk_rejections,
            broker_rejections=self.broker_rejections,
            journal=self.journal,
        )
        return ReplayResult(
            report=report,
            journal=self.journal,
            portfolio=self.portfolio,
            broker=self.broker,
            orders=list(self.broker.orders),
            fills=list(self.broker.fills),
            risk_rejections=list(self.risk_rejections),
            broker_rejections=list(self.broker_rejections),
        )
