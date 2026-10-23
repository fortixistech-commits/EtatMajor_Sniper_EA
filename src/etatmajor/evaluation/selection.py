"""Deterministic candidate ranking for the validation dossier.

Selection never overrides the verdict: a failed candidate is ranked below a
passing one, whatever its headline return. Ranking uses the lower bootstrap
percentile first, so a fragile candidate cannot win on its best-case run.
"""

from __future__ import annotations

from typing import Any


def _p05(robustness: dict[str, Any]) -> float:
    monte_carlo = robustness.get("monte_carlo")
    if not isinstance(monte_carlo, dict):
        return float("-inf")
    total = monte_carlo.get("total_net_pnl")
    if not isinstance(total, dict):
        return float("-inf")
    value = total.get("p05")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def rank_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank candidates with the verdict first, then the worst-case bootstrap."""
    ranked = sorted(
        candidates,
        key=lambda item: (
            0 if item["dossier"].get("verdict") == "PASS" else 1,
            -_p05(item["robustness"]),
            -float(item["dossier"].get("summary", {}).get("expectancy") or 0.0),
            str(item["dossier"].get("report_fingerprint") or ""),
        ),
    )
    rows = []
    for position, item in enumerate(ranked, start=1):
        robustness = item["robustness"]
        rows.append(
            {
                "rank": position,
                "label": item["label"],
                "verdict": item["dossier"].get("verdict"),
                "report_fingerprint": item["dossier"].get("report_fingerprint"),
                "p05_net_pnl": _p05(robustness),
                "expectancy": item["dossier"].get("summary", {}).get("expectancy"),
                "max_drawdown_percent": item["dossier"]
                .get("summary", {})
                .get("max_drawdown_percent"),
                "robustness_status": robustness.get("status"),
            }
        )
    selected = rows[0]["label"] if rows and rows[0]["verdict"] == "PASS" else None
    return {
        "selected": selected,
        "policy": "PASS first, then Monte-Carlo p05, expectancy, fingerprint",
        "candidates": rows,
        "warning": (
            "le classement porte sur le meme echantillon de test : "
            "il ne remplace pas une validation independante"
        ),
    }
