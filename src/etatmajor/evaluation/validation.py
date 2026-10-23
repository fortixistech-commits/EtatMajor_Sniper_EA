"""Validation dossier with criteria declared before the test.

The dossier is deliberately unsigned: there is no secret key in the laboratory
build. It is a deterministic JSON document that makes the acceptance criteria,
the observed values and the verdict auditable. A criterion that cannot be
measured is a failure, never a silent pass.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, Callable

from ..core.errors import ConfigurationError
from ..reporting.metrics import performance_from_report
from ..reporting.report import report_fingerprint

ALLOWED_CRITERIA = {
    "min_trades": (int, float),
    "min_win_rate_percent": (int, float),
    "min_profit_factor": (int, float),
    "min_expectancy": (int, float),
    "min_return_percent": (int, float),
    "max_drawdown_percent": (int, float),
    "max_fee_ratio_percent": (int, float),
    "max_turnover_ratio": (int, float),
    "min_validation_trades": (int, float),
    "min_test_trades": (int, float),
    "max_holdout_degradation_percent": (int, float),
    "min_monte_carlo_probability_positive": (int, float),
    "require_reconciled": (bool,),
    "require_simulation_only": (bool,),
}


def load_criteria(path: str | Path) -> dict[str, Any]:
    """Load ``[validation]`` criteria from a TOML file, refusing typos."""
    source = Path(path)
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"cannot read validation criteria {source}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            f"invalid validation criteria TOML {source}: {exc}"
        ) from exc
    section = payload.get("validation", payload)
    if not isinstance(section, dict):
        raise ConfigurationError("validation criteria must be a TOML table")
    criteria = {key: value for key, value in section.items() if key != "description"}
    unknown = sorted(set(criteria) - set(ALLOWED_CRITERIA))
    if unknown:
        raise ConfigurationError(
            f"unknown validation criteria: {', '.join(unknown)}"
        )
    for key, value in criteria.items():
        expected = ALLOWED_CRITERIA[key]
        if isinstance(value, bool) and bool not in expected:
            raise ConfigurationError(f"validation.{key} must not be a boolean")
        if not isinstance(value, expected):
            raise ConfigurationError(
                f"validation.{key} has type {type(value).__name__}, "
                f"expected {expected}"
            )
    if not criteria:
        raise ConfigurationError("validation criteria must not be empty")
    return criteria


def criteria_fingerprint(criteria: dict[str, Any]) -> str:
    blob = json.dumps(criteria, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def dossier_fingerprint(dossier: dict[str, Any]) -> str:
    payload = {key: value for key, value in dossier.items() if key != "dossier_fingerprint"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _check(
    identifier: str,
    *,
    observed: Any,
    threshold: Any,
    passed: bool,
    comparison: str,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "observed": observed,
        "threshold": threshold,
        "comparison": comparison,
        "passed": bool(passed),
        "detail": detail,
    }


def _value_check(
    criteria: dict[str, Any],
    key: str,
    observed: Any,
    comparison: str,
    predicate: Callable[[float], bool],
    *,
    detail: str = "",
) -> dict[str, Any] | None:
    if key not in criteria:
        return None
    threshold = criteria[key]
    if observed is None:
        return _check(
            key,
            observed=None,
            threshold=threshold,
            passed=False,
            comparison=comparison,
            detail=detail or "valeur non mesurable",
        )
    return _check(
        key,
        observed=observed,
        threshold=threshold,
        passed=predicate(float(observed)),
        comparison=comparison,
        detail=detail,
    )


def partition_value(robustness: dict[str, Any], name: str, field: str) -> Any:
    partitions = robustness.get("partitions")
    if not isinstance(partitions, dict):
        return None
    partition = partitions.get(name)
    if not isinstance(partition, dict):
        return None
    return partition.get(field)


def evaluate_validation(
    report: dict[str, Any],
    robustness: dict[str, Any],
    criteria: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate a report against explicit criteria and build the dossier."""
    metrics = performance_from_report(report)
    checks: list[dict[str, Any]] = []
    if criteria:
        candidates = [
            _value_check(
                criteria,
                "min_trades",
                metrics.get("trades"),
                ">=",
                lambda value: value >= float(criteria["min_trades"]),
            ),
            _value_check(
                criteria,
                "min_win_rate_percent",
                metrics.get("win_rate_percent"),
                ">=",
                lambda value: value >= float(criteria["min_win_rate_percent"]),
            ),
            _value_check(
                criteria,
                "min_profit_factor",
                metrics.get("profit_factor"),
                ">=",
                lambda value: value >= float(criteria["min_profit_factor"]),
                detail="aucune perte mesuree : le profit factor n'est pas defini",
            ),
            _value_check(
                criteria,
                "min_expectancy",
                metrics.get("expectancy"),
                ">=",
                lambda value: value >= float(criteria["min_expectancy"]),
            ),
            _value_check(
                criteria,
                "min_return_percent",
                metrics.get("return_percent"),
                ">=",
                lambda value: value >= float(criteria["min_return_percent"]),
            ),
            _value_check(
                criteria,
                "max_drawdown_percent",
                metrics.get("max_drawdown_percent"),
                "<=",
                lambda value: value <= float(criteria["max_drawdown_percent"]),
            ),
            _value_check(
                criteria,
                "max_fee_ratio_percent",
                metrics.get("fee_ratio_percent"),
                "<=",
                lambda value: value <= float(criteria["max_fee_ratio_percent"]),
                detail="aucun profit brut mesure : le ratio de frais n'est pas defini",
            ),
            _value_check(
                criteria,
                "max_turnover_ratio",
                metrics.get("turnover_ratio"),
                "<=",
                lambda value: value <= float(criteria["max_turnover_ratio"]),
            ),
            _value_check(
                criteria,
                "min_validation_trades",
                partition_value(robustness, "validation", "trades"),
                ">=",
                lambda value: value >= float(criteria["min_validation_trades"]),
            ),
            _value_check(
                criteria,
                "min_test_trades",
                partition_value(robustness, "test", "trades"),
                ">=",
                lambda value: value >= float(criteria["min_test_trades"]),
            ),
            _value_check(
                criteria,
                "max_holdout_degradation_percent",
                robustness.get("holdout_degradation_percent"),
                "<=",
                lambda value: value <= float(criteria["max_holdout_degradation_percent"]),
                detail="degradation non mesurable avec moins de deux partitions",
            ),
            _value_check(
                criteria,
                "min_monte_carlo_probability_positive",
                (robustness.get("monte_carlo") or {}).get("probability_positive"),
                ">=",
                lambda value: value
                >= float(criteria["min_monte_carlo_probability_positive"]),
                detail="Monte-Carlo indisponible (moins de deux trades)",
            ),
        ]
        checks.extend(check for check in candidates if check is not None)

        if "require_simulation_only" in criteria:
            expected = bool(criteria["require_simulation_only"])
            observed = report.get("simulation_only") is True
            checks.append(
                _check(
                    "require_simulation_only",
                    observed=observed,
                    threshold=expected,
                    passed=observed == expected,
                    comparison="==",
                )
            )
        if "require_reconciled" in criteria:
            expected = bool(criteria["require_reconciled"])
            reconciliation = report.get("reconciliation")
            observed = (
                isinstance(reconciliation, dict)
                and reconciliation.get("enabled", True) is not False
                and reconciliation.get("reconciled") is True
            )
            checks.append(
                _check(
                    "require_reconciled",
                    observed=observed,
                    threshold=expected,
                    passed=observed == expected,
                    comparison="==",
                )
            )

    reported_fingerprint = report.get("report_fingerprint")
    fingerprint_ok = (
        isinstance(reported_fingerprint, str)
        and report_fingerprint(report) == reported_fingerprint
    )
    checks.append(
        _check(
            "report_fingerprint",
            observed=reported_fingerprint,
            threshold="matches report content",
            passed=fingerprint_ok,
            comparison="==",
            detail="" if fingerprint_ok else "empreinte absente ou incoherente",
        )
    )

    verdict = "INCOMPLETE"
    if criteria:
        verdict = "PASS" if all(check["passed"] for check in checks) else "FAIL"

    dossier: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "9",
        "project": "ETAT-MAJOR SNIPER EA",
        "simulation_only": report.get("simulation_only") is True,
        "report_fingerprint": reported_fingerprint,
        "criteria": criteria or {},
        "criteria_fingerprint": criteria_fingerprint(criteria) if criteria else None,
        "verdict": verdict,
        "checks": checks,
        "robustness": robustness,
        "summary": {
            "trades": metrics.get("trades"),
            "net_pnl": metrics.get("net_pnl"),
            "return_percent": metrics.get("return_percent"),
            "win_rate_percent": metrics.get("win_rate_percent"),
            "profit_factor": metrics.get("profit_factor"),
            "expectancy": metrics.get("expectancy"),
            "max_drawdown_percent": metrics.get("max_drawdown_percent"),
            "robustness_status": robustness.get("status"),
        },
        "signature": None,
        "signature_note": (
            "dossier non signe : la signature cryptographique n'est pas "
            "disponible dans le laboratoire"
        ),
    }
    dossier["dossier_fingerprint"] = dossier_fingerprint(dossier)
    return dossier


def render_dossier(dossier: dict[str, Any]) -> str:
    """Human readable dossier for the terminal."""
    lines = [
        "=" * 72,
        "ETAT-MAJOR SNIPER EA - validation dossier (simulation only)",
        "=" * 72,
        f"Verdict      : {dossier['verdict']}",
        f"Report       : {dossier.get('report_fingerprint')}",
        f"Criteria     : {dossier.get('criteria_fingerprint')}",
        f"Robustness   : {dossier.get('summary', {}).get('robustness_status')}",
        "-" * 72,
    ]
    for check in dossier.get("checks", []):
        marker = "PASS" if check["passed"] else "FAIL"
        lines.append(
            f"[{marker}] {check['id']}: observed={check['observed']} "
            f"{check['comparison']} {check['threshold']}"
        )
        if check.get("detail") and not check["passed"]:
            lines.append(f"       {check['detail']}")
    lines.extend(
        [
            "=" * 72,
            "Aucun ordre reel. Dossier non signe, a revoir par un humain.",
        ]
    )
    return "\n".join(lines)
