"""Phase 9: criteria are explicit, measurable and fail closed."""

from __future__ import annotations

import pytest

from etatmajor.core.errors import ConfigurationError
from etatmajor.evaluation.robustness import build_robustness
from etatmajor.evaluation.validation import (
    criteria_fingerprint,
    evaluate_validation,
    load_criteria,
    render_dossier,
)
from etatmajor.reporting.metrics import trades_from_report
from etatmajor.reporting.report import report_fingerprint


def fill(order_id, side, quantity, price, commission=0.0, ts_ns=0):
    return {
        "order_id": order_id,
        "symbol": "EURUSD",
        "side": side,
        "quantity": quantity,
        "price": price,
        "commission": commission,
        "ts_ns": ts_ns,
    }


def report(*, winning=True) -> dict:
    exit_price = 110.0 if winning else 90.0
    payload = {
        "schema_version": "1.4",
        "phase": "9",
        "simulation_only": True,
        "account": {
            "initial_capital": 1_000.0,
            "net_pnl": 98.0 if winning else -102.0,
            "fees": 2.0,
        },
        "executions": {
            "total": 2,
            "details": [
                fill("O1", "BUY", 10, 100.0, 1.0, 1),
                fill("O2", "SELL", 10, exit_price, 1.0, 2),
            ],
        },
        "orders": {
            "total": 2,
            "details": [
                {"order_id": "O1", "reason": "entry"},
                {"order_id": "O2", "reason": "exit"},
            ],
        },
        "reconciliation": {"enabled": True, "reconciled": True},
    }
    payload["report_fingerprint"] = report_fingerprint(payload)
    return payload


def criteria(**overrides):
    base = {
        "min_trades": 1,
        "min_expectancy": 0.0,
        "max_drawdown_percent": 100.0,
        "require_reconciled": True,
        "require_simulation_only": True,
    }
    base.update(overrides)
    return base


def dossier_for(payload, **overrides):
    robustness = build_robustness(trades_from_report(payload), iterations=20, seed=7)
    return evaluate_validation(payload, robustness, criteria(**overrides))


def test_a_complete_dossier_passes_and_is_reproducible():
    payload = report()
    first = dossier_for(payload)
    second = dossier_for(payload)

    assert first["verdict"] == "PASS"
    assert first["criteria_fingerprint"] == criteria_fingerprint(criteria())
    assert first["dossier_fingerprint"] == second["dossier_fingerprint"]
    assert all(check["passed"] for check in first["checks"])
    assert "PASS" in render_dossier(first)


def test_a_failed_criterion_fails_the_dossier():
    dossier = dossier_for(report(winning=False))

    assert dossier["verdict"] == "FAIL"
    assert any(not check["passed"] for check in dossier["checks"])


def test_an_unmeasurable_profit_factor_is_not_a_silent_pass():
    dossier = dossier_for(report(), min_profit_factor=1.0)

    check = next(item for item in dossier["checks"] if item["id"] == "min_profit_factor")
    assert check["passed"] is False
    assert "aucune perte" in check["detail"]


def test_a_tampered_report_fails_the_fingerprint_check():
    payload = report()
    payload["account"]["net_pnl"] = 999.0
    dossier = dossier_for(payload)

    check = next(item for item in dossier["checks"] if item["id"] == "report_fingerprint")
    assert check["passed"] is False
    assert dossier["verdict"] == "FAIL"


def test_without_criteria_the_verdict_is_incomplete():
    payload = report()
    robustness = build_robustness(trades_from_report(payload), iterations=10, seed=1)
    dossier = evaluate_validation(payload, robustness, None)

    assert dossier["verdict"] == "INCOMPLETE"
    assert dossier["criteria"] == {}


def test_criteria_loader_refuses_unknown_or_empty_files(tmp_path):
    unknown = tmp_path / "unknown.toml"
    unknown.write_text("[validation]\nmin_trades = 1\nmin_sharpe = 2.0\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown validation criteria"):
        load_criteria(unknown)

    empty = tmp_path / "empty.toml"
    empty.write_text("[validation]\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must not be empty"):
        load_criteria(empty)


def test_criteria_loader_accepts_the_repository_example():
    from tests.conftest import REPO_ROOT

    loaded = load_criteria(REPO_ROOT / "configs" / "validation.toml")
    assert loaded["require_reconciled"] is True
