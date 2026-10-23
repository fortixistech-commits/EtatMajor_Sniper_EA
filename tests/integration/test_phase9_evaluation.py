"""Phase 9 integration: report metrics, robustness and selection truth."""

from __future__ import annotations

import pytest

from etatmajor.evaluation.robustness import build_robustness
from etatmajor.evaluation.selection import rank_candidates
from etatmajor.evaluation.validation import evaluate_validation
from etatmajor.reporting.metrics import trades_from_report
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset
from tests.integration.test_phase7_pipeline import build_demo, winning_prices


def replay(*, winning: bool) -> object:
    prices = winning_prices() if winning else [1.10000] * 4 + [0.98000] * 16
    return build_demo(prices, capital=1_000.0, quantity=500.0)


def test_the_report_contains_reconciled_performance_metrics():
    result = replay(winning=True)
    performance = result.report["performance"]

    assert performance["trades"] == 1
    assert performance["winning_trades"] == 1
    assert performance["net_pnl"] > 0
    assert performance["account_net_pnl"] == pytest.approx(performance["net_pnl"])
    assert performance["open_position_pnl"] == 0.0
    assert performance["max_drawdown"] >= 0.0
    assert len(performance["equity_curve"]) == performance["equity_curve_points"]
    assert result.report["schema_version"] == "1.4"


def test_a_loss_is_visible_in_trade_and_account_metrics():
    result = replay(winning=False)
    performance = result.report["performance"]

    assert performance["trades"] == 1
    assert performance["losing_trades"] == 1
    assert performance["net_pnl"] < 0
    assert performance["largest_loss"] < 0


def test_a_pass_dossier_and_a_failing_candidate_rank_the_pass_first():
    winner = replay(winning=True)
    loser = replay(winning=False)
    criteria = {
        "min_trades": 1,
        "min_expectancy": 0.0,
        "require_reconciled": True,
        "require_simulation_only": True,
    }
    candidates = []
    for label, result in (("loser", loser), ("winner", winner)):
        trades = trades_from_report(result.report)
        robustness = build_robustness(trades, iterations=20, seed=3)
        dossier = evaluate_validation(result.report, robustness, criteria)
        candidates.append(
            {"label": label, "dossier": dossier, "robustness": robustness}
        )

    selection = rank_candidates(candidates)

    assert selection["selected"] == "winner"
    assert [row["label"] for row in selection["candidates"]] == ["winner", "loser"]


def test_the_dossier_is_deterministic_for_the_same_report():
    result = replay(winning=True)
    first_trades = trades_from_report(result.report)
    second_trades = trades_from_report(result.report)
    first = evaluate_validation(
        result.report,
        build_robustness(first_trades, iterations=30, seed=11),
        {"min_trades": 1},
    )
    second = evaluate_validation(
        result.report,
        build_robustness(second_trades, iterations=30, seed=11),
        {"min_trades": 1},
    )

    assert first == second
