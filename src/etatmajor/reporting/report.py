"""Run report construction.

The report is the contractual output of a replay: a JSON document that can be
consumed by a program, plus a human readable summary for the command line.

The report contains no wall-clock information: two identical runs produce
byte-identical reports (see ``tests/integration/test_determinism.py``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..core.clock import ns_to_iso
from ..core.config import AppConfig
from ..core.journal import Journal
from ..core.types import OrderStatus
from ..core.models import MarketTick
from ..data.loader import Dataset
from ..execution.accounting import Portfolio
from ..execution.broker import SimulatedBroker


def _reject_summary(rejections: list[dict]) -> dict[str, int]:
    """Count rejections by normalised reason."""
    counts: dict[str, int] = {}
    for rejection in rejections:
        reason = str(rejection.get("reason", "unknown"))
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def build_report(
    dataset: Dataset,
    config: AppConfig,
    portfolio: Portfolio,
    broker: SimulatedBroker,
    strategy: Any,
    risk_rejections: list[dict],
    broker_rejections: list[dict],
    journal: Journal,
    session: dict | None = None,
    challenge: Any | None = None,
) -> dict:
    """Assemble the report of a replay run."""
    snapshot = portfolio.snapshot()
    orders = list(broker.orders)
    fills = list(broker.fills)

    order_status_counts: dict[str, int] = {}
    for order in orders:
        key = order.status.value
        order_status_counts[key] = order_status_counts.get(key, 0) + 1

    fill_volume = sum(fill.quantity for fill in fills)
    fees = sum(fill.commission for fill in fills)

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "project": "ETAT-MAJOR SNIPER EA",
        "session": session or {},
        "phase": "2",
        "mode": config.simulation.mode.report_label,
        "simulation_only": True,
        "strategy": {
            "id": getattr(strategy, "strategy_id", "unknown"),
            "version": getattr(strategy, "strategy_version", "unknown"),
        },
        "dataset": {
            **dataset.to_dict(),
            # The absolute location of the file is environment dependent: only
            # the file name and its hash are recorded, so that two runs of the
            # same dataset produce byte-identical reports.
            "source_path": Path(dataset.source_path).name
            if dataset.source_path
            else None,
        },
        "symbol": dataset.symbol,
        "timeframe": dataset.timeframe,
        "period": {
            "first_ts_ns": dataset.first_ts_ns,
            "last_ts_ns": dataset.last_ts_ns,
            "first_ts_iso": ns_to_iso(dataset.first_ts_ns) if dataset.first_ts_ns else None,
            "last_ts_iso": ns_to_iso(dataset.last_ts_ns) if dataset.last_ts_ns else None,
        },
        "bars": len(dataset.bars),
        "orders": {
            "total": len(orders),
            "by_status": dict(sorted(order_status_counts.items())),
            "details": [order.to_dict() for order in orders],
        },
        "executions": {
            "total": len(fills),
            "volume": fill_volume,
            "details": [fill.to_dict() for fill in fills],
        },
        "transactions": len(fills),
        "fees": fees,
        "account": {
            "initial_capital": snapshot.initial_capital,
            "final_equity": snapshot.equity,
            "cash": snapshot.cash,
            "realized_pnl": snapshot.realized_pnl,
            "unrealized_pnl": snapshot.unrealized_pnl,
            "fees": snapshot.fees,
            "net_pnl": snapshot.net_pnl,
            "currency": config.simulation.currency,
            "positions": [dict(p) for p in snapshot.positions],
        },
        "rejections": {
            "risk": _reject_summary(risk_rejections),
            "broker": _reject_summary(broker_rejections),
            "risk_count": len(risk_rejections),
            "broker_count": len(broker_rejections),
        },
        "market": _market_context(dataset, config),
        "challenge": _challenge_section(challenge),
        "end_of_replay_policy": config.simulation.end_of_replay_policy.value,
        "config": config.to_dict(),
        "config_fingerprint": config.fingerprint(),
        "dataset_fingerprint": dataset.fingerprint(),
        "journal_events": len(journal),
    }

    report["report_fingerprint"] = _fingerprint(report)
    return report


def _challenge_section(challenge: Any | None) -> dict:
    """Section challenge : profil, verdict et hypotheses.

    Un profil non verifiable produit un verdict ``INVALID`` : le rapport
    indique alors ce qui manque pour pouvoir conclure.
    """
    if challenge is None:
        return {"enabled": False}
    verdict = challenge.evaluate()
    return {
        "enabled": True,
        "profile": challenge.profile.to_dict(),
        "verdict": verdict.to_dict(),
    }


def _market_context(dataset: Dataset, config: AppConfig) -> dict:
    """Contexte d'execution de la fin de campagne (bid/ask/mid de reference)."""
    if not dataset.bars:
        return {}
    last = dataset.bars[-1]
    half_spread = config.execution.spread_price / 2.0
    tick = MarketTick(
        symbol=dataset.symbol,
        ts_ns=last.ts_close_ns,
        bid=round(last.close - half_spread, 10),
        ask=round(last.close + half_spread, 10),
    )
    return {
        "last_ts_ns": last.ts_close_ns,
        "bid": tick.bid,
        "ask": tick.ask,
        "mid": round(tick.mid, 10),
        "spread": round(tick.spread, 10),
    }


def _fingerprint(report: dict) -> str:
    """Hash of the report content, excluding the fingerprint field itself."""
    payload = {k: v for k, v in report.items() if k != "report_fingerprint"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def write_report(report: dict, path) -> None:
    """Write the report as pretty-printed JSON."""
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def render_summary(report: dict) -> str:
    """Human readable summary of a report (command line)."""
    account = report["account"]
    orders = report["orders"]
    executions = report["executions"]
    rejections = report["rejections"]
    period = report["period"]

    lines = [
        "=" * 68,
        "ETAT-MAJOR SNIPER EA - replay report (laboratory / simulation only)",
        "=" * 68,
        f"Strategy        : {report['strategy']['id']} v{report['strategy']['version']}",
        f"Instrument      : {report['symbol']} ({report['timeframe']})",
        f"Period          : {period['first_ts_iso']} -> {period['last_ts_iso']}",
        f"Bars            : {report['bars']}",
        f"Orders          : {orders['total']} {orders['by_status']}",
        f"Executions      : {executions['total']} (volume {executions['volume']})",
        f"Transactions    : {report['transactions']}",
        f"Fees            : {report['fees']:.6f}",
        "-" * 68,
        f"Initial capital : {account['initial_capital']:.2f} {account['currency']}",
        f"Final equity    : {account['final_equity']:.2f} {account['currency']}",
        f"Realized PnL    : {account['realized_pnl']:.2f}",
        f"Unrealized PnL  : {account['unrealized_pnl']:.2f}",
        f"Net PnL         : {account['net_pnl']:.2f}",
        "-" * 68,
        f"Risk rejections : {rejections['risk_count']} {rejections['risk']}",
        f"Broker rejects  : {rejections['broker_count']} {rejections['broker']}",
        f"End of replay   : {report['end_of_replay_policy']}",
        f"Fingerprint     : {report['report_fingerprint']}",
        "=" * 68,
        "Reminder: these results come from a simulation. They are not a",
        "performance guarantee and must not be presented as such.",
    ]
    return "\n".join(lines)
