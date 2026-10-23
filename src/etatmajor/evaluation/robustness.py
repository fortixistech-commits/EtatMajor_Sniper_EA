"""Robustness diagnostics for a replay report.

Three independent views are produced from the closed trades:

* a chronological train / validation / test split;
* a deterministic bootstrap Monte-Carlo of the trade sequence;
* a degradation measure between in-sample and out-of-sample expectancy.

Parameter sensitivity is intentionally not invented here: it requires actual
candidate reports produced with different parameters. The section states that
limitation instead of displaying a fake score.
"""

from __future__ import annotations

import random
from typing import Any, Iterable

from ..reporting.metrics import Trade, trade_statistics

DEFAULT_ITERATIONS = 1_000
DEFAULT_SEED = 42
DEFAULT_TRAIN_RATIO = 0.60
DEFAULT_VALIDATION_RATIO = 0.20


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(fraction, 0.0), 1.0) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def split_trades(
    trades: Iterable[Trade],
    train_ratio: float = DEFAULT_TRAIN_RATIO,
    validation_ratio: float = DEFAULT_VALIDATION_RATIO,
) -> dict[str, list[Trade]]:
    """Split closed trades chronologically without shuffling."""
    items = sorted(trades, key=lambda trade: (trade.exit_ts_ns, trade.trade_id))
    if not 0.0 < train_ratio < 1.0:
        raise ValueError("train_ratio must be within (0, 1)")
    if not 0.0 <= validation_ratio < 1.0:
        raise ValueError("validation_ratio must be within [0, 1)")
    if train_ratio + validation_ratio >= 1.0:
        raise ValueError("train_ratio + validation_ratio must be < 1")
    count = len(items)
    train_end = int(count * train_ratio)
    validation_end = train_end + int(count * validation_ratio)
    if count >= 3:
        train_end = max(1, train_end)
        validation_end = max(train_end, min(count - 1, validation_end))
    return {
        "train": items[:train_end],
        "validation": items[train_end:validation_end],
        "test": items[validation_end:],
    }


def _partition(trades: list[Trade], total: int) -> dict[str, Any]:
    stats = trade_statistics(trades)
    return {
        "trades": len(trades),
        "share_percent": 100.0 * len(trades) / total if total else 0.0,
        "net_pnl": stats["net_pnl"],
        "expectancy": stats["expectancy"],
        "win_rate_percent": stats["win_rate_percent"],
        "profit_factor": stats["profit_factor"],
        "average_win": stats["average_win"],
        "average_loss": stats["average_loss"],
    }


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def monte_carlo(
    trades: Iterable[Trade],
    *,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Bootstrap the closed-trade sequence with a fixed seed."""
    items = list(trades)
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if len(items) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "iterations": 0,
            "seed": seed,
            "reason": "at least two closed trades are required",
        }

    rng = random.Random(seed)
    totals: list[float] = []
    drawdowns: list[float] = []
    for _ in range(iterations):
        sample = [rng.choice(items).net_pnl for _ in range(len(items))]
        equity = 0.0
        curve: list[float] = []
        for pnl in sample:
            equity += pnl
            curve.append(equity)
        totals.append(equity)
        drawdowns.append(_max_drawdown(curve))

    positive = sum(1 for total in totals if total > 0)
    return {
        "status": "OK",
        "iterations": iterations,
        "seed": seed,
        "sample_size": len(items),
        "probability_positive": positive / iterations,
        "total_net_pnl": {
            "p05": _percentile(totals, 0.05),
            "p50": _percentile(totals, 0.50),
            "p95": _percentile(totals, 0.95),
            "min": min(totals),
            "max": max(totals),
        },
        "max_drawdown": {
            "p50": _percentile(drawdowns, 0.50),
            "p95": _percentile(drawdowns, 0.95),
            "max": max(drawdowns),
        },
    }


def build_robustness(
    trades: Iterable[Trade],
    *,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
    train_ratio: float = DEFAULT_TRAIN_RATIO,
    validation_ratio: float = DEFAULT_VALIDATION_RATIO,
) -> dict[str, Any]:
    """Build the complete robustness section from closed trades."""
    items = list(trades)
    partitions = split_trades(items, train_ratio, validation_ratio)
    total = len(items)
    train = _partition(partitions["train"], total)
    validation = _partition(partitions["validation"], total)
    test = _partition(partitions["test"], total)

    degradation = None
    if train["trades"] and test["trades"] and train["expectancy"] != 0.0:
        degradation = (
            100.0
            * (train["expectancy"] - test["expectancy"])
            / abs(train["expectancy"])
        )

    status = "OK"
    if total < 3 or not validation["trades"] or not test["trades"]:
        status = "INSUFFICIENT_DATA"

    return {
        "status": status,
        "trade_count": total,
        "split": {
            "train_ratio": train_ratio,
            "validation_ratio": validation_ratio,
            "test_ratio": 1.0 - train_ratio - validation_ratio,
            "policy": "chronological, no shuffle",
        },
        "partitions": {
            "train": train,
            "validation": validation,
            "test": test,
        },
        "holdout_degradation_percent": degradation,
        "monte_carlo": monte_carlo(items, iterations=iterations, seed=seed),
        "parameter_sensitivity": {
            "status": "NOT_AVAILABLE",
            "reason": "candidate reports with different parameters are required",
        },
        "limitations": [
            "les partitions restent des echantillons historiques, pas des donnees futures",
            "le bootstrap suppose les trades independants et identiquement distribues",
            "les couts de spread/slippage sont deja inclus dans les fills simules",
            "la selection sur le meme echantillon de test peut surestimer la performance",
        ],
    }
