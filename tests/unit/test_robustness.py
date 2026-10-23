"""Phase 9: chronological partitions and deterministic Monte-Carlo."""

from __future__ import annotations

import pytest

from etatmajor.evaluation.robustness import (
    build_robustness,
    monte_carlo,
    split_trades,
)
from etatmajor.reporting.metrics import Trade


def trade(index: int, pnl: float) -> Trade:
    return Trade(
        trade_id=f"T{index}",
        symbol="EURUSD",
        side="BUY" if pnl >= 0 else "SELL",
        quantity=1.0,
        entry_ts_ns=index,
        exit_ts_ns=index + 1,
        entry_price=1.0,
        exit_price=1.0 + pnl,
        gross_pnl=pnl,
        fees=0.0,
        net_pnl=pnl,
        entry_order_id=f"E{index}",
        exit_order_id=f"X{index}",
        exit_reason="test",
    )


def trades(count: int = 10) -> list[Trade]:
    return [trade(index, 1.0 if index % 2 == 0 else -0.5) for index in range(count)]


def test_chronological_split_never_shuffles():
    partitions = split_trades(trades(10), 0.6, 0.2)

    assert [item.trade_id for item in partitions["train"]] == [
        f"T{index}" for index in range(6)
    ]
    assert [item.trade_id for item in partitions["validation"]] == ["T6", "T7"]
    assert [item.trade_id for item in partitions["test"]] == ["T8", "T9"]


def test_split_refuses_invalid_ratios():
    with pytest.raises(ValueError):
        split_trades(trades(3), 0.9, 0.2)
    with pytest.raises(ValueError):
        split_trades(trades(3), 0.0, 0.2)


def test_monte_carlo_is_reproducible_for_a_fixed_seed():
    first = monte_carlo(trades(10), iterations=100, seed=7)
    second = monte_carlo(trades(10), iterations=100, seed=7)

    assert first == second
    assert first["status"] == "OK"
    assert 0.0 <= first["probability_positive"] <= 1.0
    assert first["total_net_pnl"]["p05"] <= first["total_net_pnl"]["p95"]


def test_a_single_trade_is_explicitly_insufficient():
    result = monte_carlo(trades(1), iterations=100, seed=7)

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["iterations"] == 0


def test_robustness_reports_out_of_sample_degradation():
    section = build_robustness(trades(10), iterations=50, seed=7)

    assert section["status"] == "OK"
    assert section["partitions"]["train"]["trades"] == 6
    assert section["partitions"]["validation"]["trades"] == 2
    assert section["partitions"]["test"]["trades"] == 2
    assert section["holdout_degradation_percent"] is not None
    assert section["parameter_sensitivity"]["status"] == "NOT_AVAILABLE"


def test_robustness_refuses_a_useless_iteration_count():
    with pytest.raises(ValueError):
        build_robustness(trades(3), iterations=0)
