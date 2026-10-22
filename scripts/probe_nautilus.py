"""NautilusTrader evaluation probe (Phase 2, "prototype technique preparatoire").

This script is **not** part of the production engine. It answers a single
question: can NautilusTrader 1.231.0 run in this environment and replay a
dataset deterministically with a full order lifecycle?

It is executed in an isolated virtual environment that has the pinned version
installed, and it writes its result to ``artifacts/nautilus_probe.json``::

    python3 -m venv .venv-nautilus
    .venv-nautilus/bin/pip install "nautilus_trader==1.231.0"
    .venv-nautilus/bin/python scripts/probe_nautilus.py \\
        --data data/sample_eurusd_1m.csv --output artifacts/nautilus_probe.json

Findings (documented in docs/ARCHITECTURE_DECISIONS.md):

* NautilusTrader 1.231.0 installs and imports cleanly on CPython 3.13
  (aarch64 manylinux wheel available).
* The order lifecycle works in backtest: order -> fill -> position.
* **The default market order is filled at the close of the bar that produced
  the signal.** For a strategy that computes its signal at the bar close, this
  is a look-ahead bias: the decision is executed at a price that was not
  available when the decision was taken. The internal engine of this project
  executes at the open of the *next* bar instead, which removes the bias.
* The platform keeps its own engine because it needs a contractual risk veto,
  an explicit end-of-replay policy and a deterministic machine readable report
  that the Nautilus objects do not provide out of the box.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OrderSide, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

SYMBOL = "EURUSD"
EVENTS: list[dict] = []
VENUE = "SIM"
BAR_TYPE = f"{SYMBOL}.{VENUE}-1-MINUTE-LAST-EXTERNAL"


class ProbeConfig(StrategyConfig, frozen=True):
    oms_type: str = "NETTING"


class ProbeStrategy(Strategy):
    """Buy on the third bar, sell on the sixth bar: exercises the full cycle."""

    def __init__(self, config: ProbeConfig) -> None:
        super().__init__(config)
        self.bars_seen = 0

    def on_start(self) -> None:
        self.subscribe_bars(bar_type=BarType.from_str(BAR_TYPE))

    def on_bar(self, bar: Bar) -> None:
        self.bars_seen += 1
        if self.bars_seen == 3:
            order = self.order_factory.market(
                instrument_id=InstrumentId.from_str(f"{SYMBOL}.{VENUE}"),
                order_side=OrderSide.BUY,
                quantity=Quantity(10_000, 2),
            )
            self.submit_order(order)
        elif self.bars_seen == 6:
            order = self.order_factory.market(
                instrument_id=InstrumentId.from_str(f"{SYMBOL}.{VENUE}"),
                order_side=OrderSide.SELL,
                quantity=Quantity(10_000, 2),
            )
            self.submit_order(order)

    def on_order_filled(self, event) -> None:
        EVENTS.append(
            {
                "type": "fill",
                "order_id": str(event.client_order_id),
                "price": float(event.last_px),
                "quantity": float(event.last_qty),
                "ts_event": int(event.ts_event),
            }
        )

    def on_position_opened(self, event) -> None:
        EVENTS.append(
            {
                "type": "position_opened",
                "position_id": str(event.position_id),
                "quantity": float(event.quantity),
                "ts_event": int(event.ts_event),
            }
        )

    def on_position_closed(self, event) -> None:
        EVENTS.append(
            {
                "type": "position_closed",
                "position_id": str(event.position_id),
                "ts_event": int(event.ts_event),
            }
        )


def build_instrument() -> CurrencyPair:
    return CurrencyPair(
        instrument_id=InstrumentId.from_str(f"{SYMBOL}.{VENUE}"),
        raw_symbol=Symbol(SYMBOL),
        base_currency=Currency.from_str("EUR"),
        quote_currency=Currency.from_str("USD"),
        price_precision=5,
        size_precision=2,
        price_increment=Price(0.00001, 5),
        size_increment=Quantity(0.01, 2),
        margin_init=0.0,
        margin_maint=0.0,
        maker_fee=0.0,
        taker_fee=0.0,
        ts_event=0,
        ts_init=0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/sample_eurusd_1m.csv")
    parser.add_argument("--output", default="artifacts/nautilus_probe.json")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    args = parser.parse_args()

    frame = pd.read_csv(args.data, parse_dates=["timestamp"]).set_index("timestamp")
    instrument = build_instrument()
    bars = BarDataWrangler(
        bar_type=BarType.from_str(BAR_TYPE), instrument=instrument
    ).process(frame)

    engine = BacktestEngine()
    engine.add_venue(
        venue=Venue(VENUE),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(int(args.starting_capital), Currency.from_str("USD"))],
        base_currency=Currency.from_str("USD"),
    )
    engine.add_instrument(instrument)
    engine.add_data(bars)
    engine.add_strategy(ProbeStrategy(ProbeConfig()))
    engine.run()

    orders = [
        {
            "order_id": str(order.client_order_id),
            "status": order.status.name,
            "side": order.side.name,
            "quantity": float(order.quantity),
        }
        for order in engine.cache.orders()
    ]

    # Look-ahead evidence: the entry order is submitted during the close of
    # bar #2 and is filled at a price that a close-based strategy could not
    # know when it decided.
    signal_bar_close = float(frame["close"].iloc[2])
    next_bar_open = float(frame["open"].iloc[3]) if len(frame) > 3 else None
    entry_fill = next(
        (e["price"] for e in EVENTS if e["type"] == "fill"), None
    )

    payload = {
        "engine": "nautilus_trader",
        "events": EVENTS,
        "lookahead_check": {
            "signal_bar_index": 2,
            "signal_bar_close": signal_bar_close,
            "next_bar_open": next_bar_open,
            "entry_fill_price": entry_fill,
            "filled_at_signal_bar_close": (
                entry_fill is not None
                and abs(entry_fill - signal_bar_close) < 1e-12
            ),
            "filled_at_next_bar_open": (
                next_bar_open is not None
                and entry_fill is not None
                and abs(entry_fill - next_bar_open) < 1e-12
            ),
        },
        "version": __import__("nautilus_trader").__version__,
        "dataset": Path(args.data).name,
        "bars": len(frame),
        "orders": orders,
        "orders_total": len(orders),
        "account": str(engine.portfolio.account(venue=Venue(VENUE))),
        "note": (
            "NautilusTrader fills a market order submitted during on_bar at the "
            "close of that same bar: look-ahead bias for close-based signals."
        ),
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
