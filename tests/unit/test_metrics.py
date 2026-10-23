"""Phase 9: deterministic trade reconstruction and performance metrics."""

from __future__ import annotations

import pytest

from etatmajor.reporting.metrics import (
    Trade,
    drawdown_statistics,
    performance_section,
    reconstruct_trades,
    sample_curve,
    trade_statistics,
)


def fill(order_id, side, quantity, price, commission=0.0, ts_ns=0, symbol="EURUSD"):
    return {
        "order_id": order_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "commission": commission,
        "ts_ns": ts_ns,
    }


def test_a_round_trip_reconstructs_gross_net_and_fees():
    trades = reconstruct_trades(
        [
            fill("O1", "BUY", 10, 100.0, 1.0, 1),
            fill("O2", "SELL", 10, 110.0, 1.0, 2),
        ],
        [{"order_id": "O2", "reason": "target"}],
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.side == "BUY"
    assert trade.quantity == 10
    assert trade.gross_pnl == pytest.approx(100.0)
    assert trade.fees == pytest.approx(2.0)
    assert trade.net_pnl == pytest.approx(98.0)
    assert trade.exit_reason == "target"


def test_a_flip_closes_then_opens_the_residual():
    trades = reconstruct_trades(
        [
            fill("O1", "BUY", 10, 100.0, 0.0, 1),
            fill("O2", "SELL", 15, 110.0, 0.0, 2),
            fill("O3", "BUY", 5, 100.0, 0.0, 3),
        ]
    )

    assert len(trades) == 2
    assert trades[0].side == "BUY"
    assert trades[0].net_pnl == pytest.approx(100.0)
    assert trades[1].side == "SELL"
    assert trades[1].net_pnl == pytest.approx(50.0)


def test_partial_close_allocates_entry_fees_proportionally():
    trades = reconstruct_trades(
        [
            fill("O1", "BUY", 10, 100.0, 2.0, 1),
            fill("O2", "SELL", 5, 110.0, 1.0, 2),
        ]
    )

    assert len(trades) == 1
    assert trades[0].net_pnl == pytest.approx(50.0 - 1.0 - 1.0)


def test_statistics_refuse_to_invent_a_profit_factor_without_losses():
    trades = reconstruct_trades(
        [
            fill("O1", "BUY", 10, 100.0, 0.0, 1),
            fill("O2", "SELL", 10, 110.0, 0.0, 2),
        ]
    )
    stats = trade_statistics(trades)

    assert stats["trades"] == 1
    assert stats["win_rate_percent"] == 100.0
    assert stats["profit_factor"] is None
    assert stats["payoff_ratio"] is None


def test_statistics_compute_profit_factor_and_expectancy():
    trades = [
        Trade("T1", "EURUSD", "BUY", 10, 1, 2, 100, 110, 100, 2, 98, "a", "b", ""),
        Trade("T2", "EURUSD", "SELL", 10, 3, 4, 120, 125, -50, 2, -52, "c", "d", ""),
    ]
    stats = trade_statistics(trades)

    assert stats["net_pnl"] == pytest.approx(46.0)
    assert stats["profit_factor"] == pytest.approx(98 / 52)
    assert stats["expectancy"] == pytest.approx(23.0)
    assert stats["largest_win"] == pytest.approx(98.0)
    assert stats["largest_loss"] == pytest.approx(-52.0)


def test_drawdown_uses_the_peak_and_reports_duration():
    curve = [
        (0, 100.0),
        (1, 110.0),
        (2, 105.0),
        (3, 120.0),
        (4, 90.0),
        (5, 100.0),
    ]
    stats = drawdown_statistics(curve)

    assert stats["max_drawdown"] == pytest.approx(30.0)
    assert stats["max_drawdown_percent"] == pytest.approx(25.0)
    assert stats["max_drawdown_duration_ns"] == 1
    assert stats["max_drawdown_points"] == 1


def test_curve_sampling_keeps_endpoints_and_is_bounded():
    curve = [(index, float(index)) for index in range(1_000)]
    sampled = sample_curve(curve, limit=50)

    assert sampled["equity_curve_points"] == 1_000
    assert sampled["equity_curve_sampled"] is True
    assert len(sampled["equity_curve"]) <= 50
    assert sampled["equity_curve"][0] == [0, 0.0]
    assert sampled["equity_curve"][-1] == [999, 999.0]


def test_performance_section_reconciles_account_and_closed_trades():
    section = performance_section(
        fills=[
            fill("O1", "BUY", 10, 100.0, 1.0, 1),
            fill("O2", "SELL", 10, 110.0, 1.0, 2),
        ],
        orders=[],
        initial_capital=1_000.0,
        net_pnl=98.0,
        fees=2.0,
        equity_curve=[(0, 1_000.0), (1, 1_010.0), (2, 1_098.0)],
    )

    assert section["trades"] == 1
    assert section["account_net_pnl"] == pytest.approx(98.0)
    assert section["open_position_pnl"] == pytest.approx(0.0)
    assert section["return_percent"] == pytest.approx(9.8)
    assert section["turnover"] == pytest.approx(2_100.0)
    assert section["by_side"]["BUY"]["trades"] == 1
    assert section["max_drawdown"] == pytest.approx(0.0)
