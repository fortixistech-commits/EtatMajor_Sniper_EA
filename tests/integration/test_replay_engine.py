"""Integration tests of the replay engine.

Covered mandatory assertions:
  * #2 deferred execution (no fill on the signal bar)
  * #5 a refused order does not change the portfolio
  * #6 pending orders at the end of the replay
  * #7 end-of-replay closure and accounting reconciliation
"""

from __future__ import annotations

import pytest

from etatmajor.core.types import EndOfReplayPolicy, OrderStatus
from etatmajor.data.loader import load_csv
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset

PRICES = [
    1.10000, 1.10020, 1.10040, 1.10060, 1.10080,
    1.10100, 1.10120, 1.10140, 1.10160, 1.10180,
]


def run(dataset, config, strategy=None):
    strategy = strategy or DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=6
    )
    engine = ReplayEngine(dataset=dataset, config=config, strategy=strategy)
    return engine.run()


def test_full_lifecycle_signal_order_fill_position_close():
    dataset = make_dataset(PRICES)
    config = make_config()
    result = run(dataset, config)

    assert result.report["orders"]["total"] == 2
    assert result.report["executions"]["total"] == 2
    assert result.report["transactions"] == 2
    assert len(result.journal.of_type("SIGNAL")) == 2
    assert len(result.journal.of_type("RISK_DECISION")) == 2
    assert len(result.journal.of_type("ORDER_FILLED")) == 2
    assert len(result.journal.of_type("POSITION_OPENED")) >= 1
    assert len(result.journal.of_type("POSITION_CLOSED")) >= 1


def test_order_is_not_executed_on_the_bar_that_produced_the_signal():
    # A gap between the signal bar and the next bar proves that the execution
    # uses the open of the next bar, never the close of the signal bar.
    closes = [1.10000, 1.10020, 1.10040, 1.10060, 1.10080, 1.10100]
    opens = [1.10000, 1.10020, 1.10040, 1.10500, 1.10080, 1.10100]
    dataset = make_dataset(closes, opens=opens)
    config = make_config()
    result = run(dataset, config)

    signals = result.journal.of_type("SIGNAL")
    fills = result.journal.of_type("ORDER_FILLED")
    assert signals and fills

    signal = signals[0].payload
    fill = fills[0].payload

    # The execution happens on a strictly later bar than the signal bar.
    assert fill["execution_bar_index"] == signal["signal_bar_index"] + 1
    assert fill["execution_price_source"] == "bar_open"

    # The execution price is derived from the open of the next bar, never from
    # the close of the signal bar.
    next_bar = dataset.bars[fill["execution_bar_index"]]
    signal_bar = dataset.bars[signal["signal_bar_index"]]
    assert fill["price"] == pytest.approx(next_bar.open)
    assert fill["price"] != pytest.approx(signal_bar.close)

    # The fill cannot be timestamped before the decision that produced it.
    assert fills[0].ts_ns >= signals[0].ts_ns


def test_gap_dataset_executes_at_the_next_bar_open_not_at_the_signal_close():
    """Contrast with the NautilusTrader probe (artifacts/nautilus_probe_gap.json).

    Same dataset, same bar index: this engine fills at the open of the next
    bar (1.11000) whereas NautilusTrader fills at the close of the signal bar
    (1.10050).
    """
    from tests.conftest import FIXTURES

    dataset = load_csv(
        FIXTURES / "gap_gap.csv",
        symbol="EURUSD",
        timeframe="1m",
        timeframe_ns=60_000_000_000,
    )
    config = make_config()
    result = run(dataset, config)

    fill = result.journal.of_type("ORDER_FILLED")[0].payload
    assert fill["price"] == pytest.approx(1.11000)
    assert fill["execution_bar_index"] == 3
    assert dataset.bars[2].close == pytest.approx(1.10050)


def test_strategy_cannot_observe_future_bars():
    dataset = make_dataset(PRICES)
    config = make_config()
    observed: list[int] = []

    class SpyStrategy(DemoLifecycleStrategy):
        def on_bar(self, context):
            observed.append(len(context.visible_bars))
            assert context.visible_bars[-1].ts_close_ns <= context.clock.now()
            for bar in context.visible_bars:
                assert bar.ts_close_ns <= context.clock.now()
            return []

    run(dataset, config, SpyStrategy(symbol="EURUSD", timeframe="1m"))
    assert observed == list(range(1, len(PRICES) + 1))


def test_refused_order_does_not_change_the_portfolio():
    dataset = make_dataset(PRICES)
    config = make_config(max_position_quantity=1.0)  # any size above 1 is refused
    result = run(dataset, config)

    assert result.report["orders"]["total"] == 0
    assert result.report["executions"]["total"] == 0
    assert result.report["rejections"]["risk_count"] == 2
    assert result.portfolio.cash == pytest.approx(100_000.0)
    assert result.portfolio.net_quantity("EURUSD") == 0.0
    assert result.portfolio.fees == 0.0
    assert result.portfolio.equity == pytest.approx(100_000.0)
    assert result.report["account"]["net_pnl"] == pytest.approx(0.0)


def test_pending_orders_are_cancelled_at_the_end_of_the_replay():
    dataset = make_dataset(PRICES)
    config = make_config()
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=1_000.0,
        entry_index=2,
        exit_index=6,
        place_pending_limit=True,
        pending_limit_offset=0.50,
    )
    result = run(dataset, config, strategy)

    cancelled = result.journal.of_type("ORDER_CANCELLED")
    assert len(cancelled) == 1
    assert cancelled[0].payload["reason"] == "cancelled by end-of-replay policy"
    assert result.broker.open_orders() == []
    assert result.report["orders"]["by_status"]["CANCELLED"] == 1
    # A cancelled order produces no execution.
    assert result.report["executions"]["total"] == 2


def test_close_at_last_price_policy_flattens_the_position():
    dataset = make_dataset(PRICES)
    config = make_config(end_of_replay_policy=EndOfReplayPolicy.CLOSE_AT_LAST_PRICE)
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=99
    )
    result = run(dataset, config, strategy)

    assert result.portfolio.net_quantity("EURUSD") == 0.0
    assert result.portfolio.unrealized_pnl == pytest.approx(0.0)
    account = result.report["account"]
    assert account["final_equity"] == pytest.approx(account["cash"])
    assert account["net_pnl"] == pytest.approx(
        account["realized_pnl"] + account["unrealized_pnl"] - account["fees"]
    )
    assert result.report["end_of_replay_policy"] == "CLOSE_AT_LAST_PRICE"


def test_mark_to_market_policy_keeps_the_position_open():
    dataset = make_dataset(PRICES)
    config = make_config(end_of_replay_policy=EndOfReplayPolicy.MARK_TO_MARKET)
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=99
    )
    result = run(dataset, config, strategy)

    assert result.portfolio.net_quantity("EURUSD") == 1_000.0
    account = result.report["account"]
    assert account["unrealized_pnl"] != 0.0
    assert account["final_equity"] == pytest.approx(
        account["cash"] + account["unrealized_pnl"]
    )
    assert result.report["end_of_replay_policy"] == "MARK_TO_MARKET"


def test_costs_are_integrated_in_the_net_result():
    dataset = make_dataset(PRICES)
    config = make_config(
        spread_price=0.00020,
        slippage_price=0.00005,
        commission_per_lot_per_side=7.0,
        lot_size=1_000.0,
    )
    result = run(dataset, config)
    account = result.report["account"]

    assert account["fees"] == pytest.approx(2 * 7.0)
    assert account["net_pnl"] == pytest.approx(
        account["realized_pnl"] + account["unrealized_pnl"] - account["fees"]
    )


def test_spread_and_slippage_reduce_the_realised_pnl():
    dataset = make_dataset(PRICES)
    plain = run(dataset, make_config())
    costly = run(
        dataset,
        make_config(spread_price=0.00020, slippage_price=0.00005),
    )
    assert costly.report["account"]["realized_pnl"] < plain.report["account"][
        "realized_pnl"
    ]


def test_broker_rejection_is_recorded_and_leaves_no_trace():
    dataset = make_dataset(PRICES)
    config = make_config(reject_probability=1.0)
    result = run(dataset, config)

    assert result.report["executions"]["total"] == 0
    assert result.report["rejections"]["broker_count"] == 2
    assert result.portfolio.cash == pytest.approx(100_000.0)


def test_journal_records_the_full_decision_chain():
    dataset = make_dataset(PRICES)
    config = make_config()
    result = run(dataset, config)

    types = [entry.type for entry in result.journal.entries]
    assert types[0] == "REPLAY_STARTED"
    assert types[-1] == "REPLAY_FINISHED"
    assert "SIGNAL" in types
    assert "RISK_DECISION" in types
    assert "ORDER_SUBMITTED" in types
    assert "ORDER_FILLED" in types

    # The journal sequence numbers are strictly increasing.
    seqs = [entry.seq for entry in result.journal.entries]
    assert seqs == list(range(len(seqs)))


def test_empty_dataset_is_refused():
    dataset = make_dataset([])
    with pytest.raises(ValueError):
        run(dataset, make_config())
