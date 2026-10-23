"""Operator cockpit for replay evidence.

The cockpit is a **read-only** view over a report and its journal. It never
runs a strategy, never reaches a broker and never reads the wall clock: two
identical evidence files always produce byte-identical cockpit outputs.

It answers three operator questions:

* what did the run produce (account, orders, challenge, data quality) ?
* can the evidence be trusted (report fingerprint, journal sequence, final
  event, session identity, reconciliation, challenge verdict) ?
* what should be inspected next (findings ordered by severity) ?

The HTML output is standalone: inline CSS, no script, no external asset.
"""

from __future__ import annotations

import html as html_module
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.clock import ns_to_iso
from ..core.errors import CockpitError
from ..core.session import build_session_identity
from .report import report_fingerprint

COCKPIT_VERSION = "1.0"
SUPPORTED_SCHEMA = "1.4"
MAX_TABLE_ROWS = 100
MAX_EVENT_ROWS = 40

REQUIRED_REPORT_KEYS = (
    "schema_version",
    "project",
    "phase",
    "mode",
    "simulation_only",
    "strategy",
    "dataset",
    "account",
    "orders",
    "executions",
    "rejections",
    "reconciliation",
    "end_of_replay_policy",
    "report_fingerprint",
)

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Finding:
    """One integrity or observability finding."""

    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class CockpitView:
    """Normalised operator view built from a report and an optional journal."""

    report: dict[str, Any]
    entries: list[dict[str, Any]] = field(default_factory=list)
    journal_provided: bool = False
    title: str = "ETAT-MAJOR cockpit"
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def strict_ok(self) -> bool:
        return not self.errors and not self.warnings

    @property
    def ordering(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda item: (SEVERITY_ORDER.get(item.severity, 9), item.code),
        )

    @property
    def event_counts(self) -> dict[str, int]:
        counts = Counter(
            str(entry.get("type", ""))
            for entry in self.entries
            if isinstance(entry, dict) and entry.get("type")
        )
        return dict(sorted(counts.items()))

    def metrics(self) -> dict[str, Any]:
        return _metrics(self.report, self.entries)

    def to_dict(self) -> dict[str, Any]:
        report = self.report
        session = report.get("session") if isinstance(report, dict) else {}
        return {
            "cockpit_version": COCKPIT_VERSION,
            "title": self.title,
            "ok": self.ok,
            "strict_ok": self.strict_ok,
            "findings": [item.to_dict() for item in self.ordering],
            "metrics": self.metrics(),
            "event_counts": self.event_counts,
            "journal_provided": self.journal_provided,
            "session_id": (session or {}).get("session_id")
            if isinstance(session, dict)
            else None,
            "report_fingerprint": report.get("report_fingerprint")
            if isinstance(report, dict)
            else None,
        }


def load_report(path: str | Path) -> dict[str, Any]:
    """Load a JSON report and refuse anything that is not an object."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CockpitError(f"cannot read report {source}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CockpitError(f"invalid JSON report {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CockpitError(f"report {source} must be a JSON object")
    return payload


def load_journal(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSONL journal, reporting the exact offending line."""
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CockpitError(f"cannot read journal {source}: {exc}") from exc

    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CockpitError(
                f"invalid JSON in journal {source} at line {line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CockpitError(
                f"journal {source} line {line_number} must be a JSON object"
            )
        entries.append(payload)
    return entries


def build_cockpit(
    report: dict[str, Any],
    entries: list[dict[str, Any]] | None = None,
    *,
    title: str = "ETAT-MAJOR cockpit",
) -> CockpitView:
    """Build a deterministic cockpit view and collect every finding."""
    if not isinstance(report, dict):
        raise CockpitError("report must be a dictionary")
    if entries is not None:
        if not isinstance(entries, list):
            raise CockpitError("journal entries must be a list")
        if any(not isinstance(item, dict) for item in entries):
            raise CockpitError("each journal entry must be a dictionary")

    view = CockpitView(
        report=report,
        entries=list(entries or []),
        journal_provided=entries is not None,
        title=str(title),
    )
    _check_report(view)
    if view.journal_provided:
        _check_journal(view)
        _cross_check(view)
    else:
        view.findings.append(
            Finding(
                "warning",
                "JOURNAL_NOT_PROVIDED",
                "journal absent : la chaine d'audit ne peut pas etre verifiee",
            )
        )
    return view


# -- report checks ------------------------------------------------------
def _check_report(view: CockpitView) -> None:
    report = view.report
    for key in REQUIRED_REPORT_KEYS:
        if key not in report:
            _add(view, "error", "REPORT_FIELD_MISSING", f"champ absent: {key}")

    if report.get("simulation_only") is not True:
        _add(
            view,
            "error",
            "NOT_SIMULATION_ONLY",
            "le rapport ne declare pas simulation_only = true",
        )
    if report.get("mode") not in {"LABORATORY", "CHALLENGE_SIM"}:
        _add(
            view,
            "error",
            "UNEXPECTED_MODE",
            f"mode non supporte par le cockpit: {report.get('mode')!r}",
        )

    schema = str(report.get("schema_version", ""))
    if schema != SUPPORTED_SCHEMA:
        _add(
            view,
            "warning",
            "SCHEMA_VERSION",
            f"schema {schema or 'absent'} ; cockpit attendu {SUPPORTED_SCHEMA}",
        )
    if str(report.get("phase")) != "9":
        _add(
            view,
            "warning",
            "PHASE_NOT_CURRENT",
            f"rapport produit par la phase {report.get('phase')!r}",
        )

    fingerprint = report.get("report_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 16:
        _add(view, "error", "REPORT_FINGERPRINT_INVALID", "empreinte de rapport absente")
    elif report_fingerprint(report) != fingerprint:
        _add(
            view,
            "error",
            "REPORT_FINGERPRINT_MISMATCH",
            "le contenu du rapport ne correspond plus a son empreinte",
        )

    dataset = report.get("dataset")
    if not isinstance(dataset, dict):
        _add(view, "error", "DATASET_INVALID", "section dataset invalide")
    else:
        content = dataset.get("content_fingerprint")
        if content and content != report.get("dataset_fingerprint"):
            _add(
                view,
                "error",
                "DATASET_FINGERPRINT_MISMATCH",
                "empreinte dataset incoherente avec le contenu",
            )

    account = report.get("account")
    if not isinstance(account, dict):
        _add(view, "error", "ACCOUNT_INVALID", "section account invalide")
    else:
        for key in ("initial_capital", "final_equity", "net_pnl", "fees"):
            if not _is_number(account.get(key)):
                _add(view, "error", "ACCOUNT_VALUE_INVALID", f"account.{key} non numerique")

    session = report.get("session")
    if not isinstance(session, dict) or not session:
        _add(view, "warning", "SESSION_MISSING", "identite de session absente")
    else:
        _check_session_identity(view, session, report)

    reconciliation = report.get("reconciliation")
    if not isinstance(reconciliation, dict):
        _add(view, "error", "RECONCILIATION_INVALID", "section reconciliation invalide")
    elif reconciliation.get("enabled", True) is False:
        _add(view, "warning", "RECONCILIATION_NOT_RUN", "reconciliation non executee")
    elif reconciliation.get("reconciled") is not True:
        _add(view, "error", "RECONCILIATION_NOT_OK", "reconciliation non conforme")


def _check_session_identity(
    view: CockpitView, session: dict[str, Any], report: dict[str, Any]
) -> None:
    for key in (
        "session_id",
        "strategy_id",
        "strategy_version",
        "config_fingerprint",
        "dataset_fingerprint",
        "created_ts_ns",
    ):
        if key not in session:
            _add(view, "error", "SESSION_FIELD_MISSING", f"session.{key} absent")
            return
    if session["config_fingerprint"] != report.get("config_fingerprint"):
        _add(view, "error", "CONFIG_FINGERPRINT_MISMATCH", "session/config incoherents")
    if session["dataset_fingerprint"] != report.get("dataset_fingerprint"):
        _add(view, "error", "SESSION_DATASET_MISMATCH", "session/dataset incoherents")
    try:
        expected = build_session_identity(
            strategy_id=str(session["strategy_id"]),
            strategy_version=str(session["strategy_version"]),
            config_fingerprint=str(session["config_fingerprint"]),
            dataset_fingerprint=str(session["dataset_fingerprint"]),
            created_ts_ns=int(session["created_ts_ns"]),
            code_version=str(session.get("code_version", "unknown")),
        )
    except (TypeError, ValueError) as exc:
        _add(view, "error", "SESSION_INVALID", f"session illisible: {exc}")
        return
    if expected.session_id != session["session_id"]:
        _add(
            view,
            "error",
            "SESSION_ID_MISMATCH",
            "l'identifiant de session ne correspond pas a ses composants",
        )


# -- journal checks -----------------------------------------------------
def _check_journal(view: CockpitView) -> None:
    entries = view.entries
    if not entries:
        _add(view, "error", "JOURNAL_EMPTY", "journal vide")
        return

    previous_ts: int | None = None
    for position, entry in enumerate(entries):
        prefix = f"evenement {position}"
        if not isinstance(entry, dict):
            _add(view, "error", "EVENT_INVALID", f"{prefix}: objet attendu")
            continue
        seq = entry.get("seq")
        if not _is_int(seq) or int(seq) != position:
            _add(
                view,
                "error",
                "JOURNAL_SEQUENCE_GAP",
                f"{prefix}: seq {seq!r} au lieu de {position}",
            )
        ts_ns = entry.get("ts_ns")
        if not _is_int(ts_ns):
            _add(view, "error", "EVENT_TS_INVALID", f"{prefix}: ts_ns invalide")
        else:
            if previous_ts is not None and int(ts_ns) < previous_ts:
                _add(
                    view,
                    "error",
                    "JOURNAL_TIME_REVERSED",
                    f"{prefix}: horodatage en recul",
                )
            previous_ts = int(ts_ns)
        if not isinstance(entry.get("type"), str) or not entry.get("type"):
            _add(view, "error", "EVENT_TYPE_INVALID", f"{prefix}: type invalide")
        if not isinstance(entry.get("payload"), dict):
            _add(view, "error", "EVENT_PAYLOAD_INVALID", f"{prefix}: payload invalide")

    types = [entry.get("type") for entry in entries if isinstance(entry, dict)]
    if not types:
        return
    if types[0] != "REPLAY_STARTED":
        _add(view, "error", "JOURNAL_START_MISSING", "le journal ne commence pas par REPLAY_STARTED")
    if types.count("REPLAY_STARTED") == 0:
        _add(view, "error", "JOURNAL_START_MISSING", "aucun evenement REPLAY_STARTED")
    finished = types.count("REPLAY_FINISHED")
    if finished != 1:
        _add(
            view,
            "error",
            "JOURNAL_FINISH_COUNT",
            f"{finished} evenement(s) REPLAY_FINISHED au lieu de 1",
        )
    if types[-1] != "REPLAY_FINISHED":
        _add(
            view,
            "error",
            "JOURNAL_FINISH_NOT_LAST",
            "REPLAY_FINISHED n'est pas le dernier evenement",
        )

    session_ids = {
        str(entry.get("payload", {}).get("session_id"))
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("payload"), dict)
        and entry["payload"].get("session_id")
    }
    if len(session_ids) > 1:
        _add(
            view,
            "error",
            "JOURNAL_MULTIPLE_SESSIONS",
            f"plusieurs sessions dans un journal: {sorted(session_ids)}",
        )


def _cross_check(view: CockpitView) -> None:
    report = view.report
    entries = view.entries
    if not entries:
        return

    expected_count = report.get("journal_events")
    if expected_count != len(entries):
        _add(
            view,
            "error",
            "JOURNAL_COUNT_MISMATCH",
            f"rapport {expected_count!r} evenements, journal {len(entries)}",
        )

    observability = report.get("observability")
    if not isinstance(observability, dict):
        _add(
            view,
            "warning",
            "OBSERVABILITY_MISSING",
            "section observability absente (schema anterieur)",
        )
    else:
        if observability.get("journal_events") != len(entries):
            _add(
                view,
                "error",
                "OBSERVABILITY_COUNT_MISMATCH",
                "compteur global observability incoherent",
            )
        actual = view.event_counts
        if observability.get("event_counts") != actual:
            _add(
                view,
                "error",
                "OBSERVABILITY_COUNTS_MISMATCH",
                "repartition observability incoherente avec le journal",
            )
        if observability.get("replay_finished_events") != actual.get("REPLAY_FINISHED"):
            _add(
                view,
                "error",
                "OBSERVABILITY_FINISH_MISMATCH",
                "compteur REPLAY_FINISHED incoherent",
            )
        if observability.get("chronological") is not True:
            _add(view, "error", "OBSERVABILITY_TIME_REVERSED", "journal non chronologique")

    session = report.get("session") if isinstance(report.get("session"), dict) else {}
    start_entries = [
        entry
        for entry in entries
        if entry.get("type") == "REPLAY_STARTED"
        and isinstance(entry.get("payload"), dict)
    ]
    journal_session_ids = [
        entry["payload"].get("session_id")
        for entry in start_entries
        if entry["payload"].get("session_id")
    ]
    if session.get("session_id") and journal_session_ids:
        if session["session_id"] not in journal_session_ids:
            _add(
                view,
                "error",
                "SESSION_ID_MISMATCH",
                "session du rapport absente du journal",
            )
    elif not journal_session_ids:
        _add(view, "warning", "JOURNAL_SESSION_MISSING", "aucun session_id journalise")

    for entry in start_entries:
        payload = entry["payload"]
        for key in ("config_fingerprint", "dataset_fingerprint"):
            if payload.get(key) and payload[key] != report.get(key):
                _add(
                    view,
                    "error",
                    "START_FINGERPRINT_MISMATCH",
                    f"REPLAY_STARTED.{key} incoherent avec le rapport",
                )

    _cross_check_finish(view)
    _cross_check_reconciliation(view)
    _cross_check_challenge(view)


def _cross_check_finish(view: CockpitView) -> None:
    report = view.report
    finish = [
        entry
        for entry in view.entries
        if entry.get("type") == "REPLAY_FINISHED"
        and isinstance(entry.get("payload"), dict)
    ]
    if len(finish) != 1:
        return
    payload = finish[0]["payload"]
    account = report.get("account") if isinstance(report.get("account"), dict) else {}

    for key in ("equity", "net_pnl"):
        left = payload.get(key)
        right = account.get("final_equity" if key == "equity" else "net_pnl")
        if not _is_number(left) or not _is_number(right):
            _add(view, "error", "FINISH_VALUE_MISSING", f"REPLAY_FINISHED.{key} absent")
        elif not _close(float(left), float(right)):
            _add(
                view,
                "error",
                "FINISH_ACCOUNT_MISMATCH",
                f"REPLAY_FINISHED.{key}={left} et rapport={right}",
            )

    if payload.get("end_of_replay_policy") != report.get("end_of_replay_policy"):
        _add(
            view,
            "error",
            "FINISH_POLICY_MISMATCH",
            "politique de fin incoherente avec le rapport",
        )

    executions = report.get("executions")
    total = executions.get("total") if isinstance(executions, dict) else None
    details = payload.get("executions")
    if isinstance(details, list) and total is not None and len(details) != total:
        _add(
            view,
            "error",
            "FINISH_EXECUTIONS_MISMATCH",
            f"{len(details)} executions journalisees, {total} dans le rapport",
        )


def _cross_check_reconciliation(view: CockpitView) -> None:
    events = [
        entry
        for entry in view.entries
        if entry.get("type") == "RECONCILIATION"
        and isinstance(entry.get("payload"), dict)
    ]
    if len(events) != 1:
        _add(
            view,
            "error",
            "RECONCILIATION_EVENT_COUNT",
            f"{len(events)} evenement(s) RECONCILIATION au lieu de 1",
        )
        return
    if events[0]["payload"].get("reconciled") is not True:
        _add(
            view,
            "error",
            "RECONCILIATION_EVENT_FAILED",
            "l'evenement de reconciliation n'est pas conforme",
        )


def _cross_check_challenge(view: CockpitView) -> None:
    challenge = view.report.get("challenge")
    if not isinstance(challenge, dict) or challenge.get("enabled") is not True:
        return
    verdict = challenge.get("verdict") if isinstance(challenge.get("verdict"), dict) else {}
    events = [
        entry
        for entry in view.entries
        if entry.get("type") == "CHALLENGE_FINALIZED"
        and isinstance(entry.get("payload"), dict)
    ]
    if len(events) != 1:
        _add(
            view,
            "error",
            "CHALLENGE_FINAL_COUNT",
            f"{len(events)} evenement(s) CHALLENGE_FINALIZED au lieu de 1",
        )
        return
    journal_verdict = events[0]["payload"].get("verdict")
    if not isinstance(journal_verdict, dict):
        _add(view, "error", "CHALLENGE_FINAL_INVALID", "verdict final illisible")
    elif journal_verdict.get("state") != verdict.get("state"):
        _add(
            view,
            "error",
            "CHALLENGE_VERDICT_MISMATCH",
            "verdict du rapport different du verdict journalise",
        )


# -- metrics ------------------------------------------------------------
def _metrics(report: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    account = report.get("account") if isinstance(report.get("account"), dict) else {}
    initial = _number(account.get("initial_capital"))
    net_pnl = _number(account.get("net_pnl"))
    orders = report.get("orders") if isinstance(report.get("orders"), dict) else {}
    executions = (
        report.get("executions") if isinstance(report.get("executions"), dict) else {}
    )
    rejections = (
        report.get("rejections") if isinstance(report.get("rejections"), dict) else {}
    )
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    quality = dataset.get("quality") if isinstance(dataset.get("quality"), dict) else {}
    challenge = (
        report.get("challenge") if isinstance(report.get("challenge"), dict) else {}
    )
    verdict = challenge.get("verdict") if isinstance(challenge.get("verdict"), dict) else {}

    order_total = _number(orders.get("total"))
    fill_total = _number(executions.get("total"))
    fill_rate = (fill_total / order_total * 100.0) if order_total else 0.0
    return_pct = (net_pnl / initial * 100.0) if initial else 0.0
    first_ts = (report.get("period") or {}).get("first_ts_ns") if isinstance(report.get("period"), dict) else None
    last_ts = (report.get("period") or {}).get("last_ts_ns") if isinstance(report.get("period"), dict) else None

    return {
        "initial_capital": initial,
        "final_equity": _number(account.get("final_equity")),
        "net_pnl": net_pnl,
        "return_percent": return_pct,
        "fees": _number(account.get("fees")),
        "currency": account.get("currency"),
        "orders": int(order_total),
        "executions": int(fill_total),
        "fill_rate_percent": fill_rate,
        "risk_rejections": int(_number(rejections.get("risk_count"))),
        "broker_rejections": int(_number(rejections.get("broker_count"))),
        "journal_events": len(entries),
        "bars": int(_number(report.get("bars"))),
        "dataset_quality_ok": quality.get("ok"),
        "data_gaps": int(_number(quality.get("gap_count"))),
        "missing_bars": int(_number(quality.get("missing_bars"))),
        "simulated_span_ns": (
            int(last_ts) - int(first_ts)
            if _is_int(first_ts) and _is_int(last_ts)
            else None
        ),
        "challenge_enabled": challenge.get("enabled") is True,
        "challenge_state": verdict.get("state"),
        "challenge_step": verdict.get("step_index"),
        "challenge_steps_completed": verdict.get("steps_completed"),
        "challenge_total_pnl": verdict.get("total_pnl"),
        "challenge_max_drawdown": verdict.get("max_drawdown"),
    }


# -- rendering ----------------------------------------------------------
def render_console(view: CockpitView) -> str:
    """Compact operator summary for the terminal."""
    metrics = view.metrics()
    status = "PASS" if view.ok else "FAIL"
    if view.ok and view.warnings:
        status = "WARN"
    currency = metrics.get("currency") or ""
    challenge = metrics.get("challenge_state") or "not enabled"
    session = view.report.get("session")
    session_id = session.get("session_id", "unknown") if isinstance(session, dict) else "unknown"
    lines = [
        "=" * 72,
        "ETAT-MAJOR SNIPER EA - operator cockpit (simulation only)",
        "=" * 72,
        f"Status        : {status}",
        f"Session       : {session_id}",
        f"Instrument    : {view.report.get('symbol')} ({view.report.get('timeframe')})",
        f"Bars / events : {metrics['bars']} / {metrics['journal_events']}",
        f"Equity        : {metrics['final_equity']:.2f} {currency}",
        f"Net PnL       : {metrics['net_pnl']:+.2f} ({metrics['return_percent']:+.4f}%)",
        f"Orders / fills: {metrics['orders']} / {metrics['executions']}",
        f"Rejections    : risk {metrics['risk_rejections']}, broker {metrics['broker_rejections']}",
        f"Challenge     : {challenge}",
        f"Fingerprint   : {view.report.get('report_fingerprint', 'missing')}",
        "-" * 72,
    ]
    if view.ordering:
        for finding in view.ordering:
            lines.append(
                f"[{finding.severity.upper():7}] {finding.code}: {finding.message}"
            )
    else:
        lines.append("No finding: report and journal are consistent.")
    lines.extend(
        [
            "=" * 72,
            "Reminder: simulation evidence only. No real order was sent.",
        ]
    )
    return "\n".join(lines)


def render_dashboard(view: CockpitView) -> str:
    """Render a standalone, deterministic HTML cockpit."""
    metrics = view.metrics()
    status_class = "ok" if view.ok and not view.warnings else "warn" if view.ok else "fail"
    status_label = "CONFORME" if view.ok and not view.warnings else "AVERTISSEMENT" if view.ok else "NON CONFORME"
    session = view.report.get("session") if isinstance(view.report.get("session"), dict) else {}
    strategy = view.report.get("strategy") if isinstance(view.report.get("strategy"), dict) else {}
    period = view.report.get("period") if isinstance(view.report.get("period"), dict) else {}
    account = view.report.get("account") if isinstance(view.report.get("account"), dict) else {}
    quality = (
        view.report.get("dataset", {}).get("quality")
        if isinstance(view.report.get("dataset"), dict)
        else {}
    ) or {}

    kpis = [
        ("Equity finale", f"{metrics['final_equity']:.2f} {metrics.get('currency') or ''}"),
        ("PnL net", f"{metrics['net_pnl']:+.2f}"),
        ("Rendement", f"{metrics['return_percent']:+.4f}%"),
        ("Ordres / fills", f"{metrics['orders']} / {metrics['executions']}"),
        ("Frais", f"{metrics['fees']:.2f}"),
        ("Evenements", str(metrics['journal_events'])),
    ]

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="fr">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<meta name="generator" content="ETAT-MAJOR cockpit">',
            f"<title>{_e(view.title)}</title>",
            f"<style>{_CSS}</style>",
            "</head>",
            "<body>",
            "<main>",
            '<header class="hero">',
            '<p class="eyebrow">ETAT-MAJOR SNIPER EA / PHASE 9</p>',
            f"<h1>{_e(view.title)}</h1>",
            f'<p><span class="badge {status_class}">{status_label}</span> '
            '<span class="muted">Simulation uniquement. Aucun ordre reel.</span></p>',
            "</header>",
            _section_kpis(kpis),
            _section_identity(view, session, strategy, period),
            _section_findings(view),
            _section_challenge(view.report.get("challenge")),
            _section_quality(quality, metrics),
            _section_orders(view.report.get("orders")),
            _section_executions(view.report.get("executions")),
            _section_events(view),
            _section_observability(view.report.get("observability")),
            "<footer>",
            f"<p>Rapport <code>{_e(view.report.get('report_fingerprint', 'missing'))}</code>"
            f" - dataset <code>{_e(view.report.get('dataset_fingerprint', 'missing'))}</code>"
            f" - cockpit {_e(COCKPIT_VERSION)}</p>",
            "<p class=\"muted\">Les resultats proviennent d'une simulation et ne "
            "constituent pas une garantie de performance.</p>",
            "</footer>",
            "</main>",
            "</body>",
            "</html>",
        ]
    ) + "\n"


def write_dashboard(view: CockpitView, path: str | Path) -> Path:
    """Write the standalone HTML cockpit."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_dashboard(view), encoding="utf-8")
    return target


def write_snapshot(view: CockpitView, path: str | Path) -> Path:
    """Write the machine-readable cockpit snapshot as JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(view.to_dict(), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def _section_kpis(kpis: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="kpi"><span>{_e(label)}</span><strong>{_e(value)}</strong></div>'
        for label, value in kpis
    )
    return f'<section class="kpis">{cells}</section>'


def _section_identity(
    view: CockpitView,
    session: dict[str, Any],
    strategy: dict[str, Any],
    period: dict[str, Any],
) -> str:
    report = view.report
    rows = [
        ("Session", session.get("session_id", "absent")),
        ("Strategie", f"{strategy.get('id', '?')} v{strategy.get('version', '?')}"),
        ("Instrument", f"{report.get('symbol')} / {report.get('timeframe')}"),
        ("Periode", f"{period.get('first_ts_iso')} -> {period.get('last_ts_iso')}"),
        ("Schema / phase", f"{report.get('schema_version')} / {report.get('phase')}"),
        ("Mode", report.get("mode")),
        ("Code", session.get("code_version", "absent")),
        ("Config", report.get("config_fingerprint")),
        ("Dataset", report.get("dataset_fingerprint")),
        ("Politique de fin", report.get("end_of_replay_policy")),
    ]
    return _section_table("Identite de l'execution", ("Champ", "Valeur"), rows)


def _section_findings(view: CockpitView) -> str:
    rows = [
        (finding.severity.upper(), finding.code, finding.message)
        for finding in view.ordering
    ]
    if not rows:
        body = '<p class="empty">Aucun ecart detecte entre le rapport et le journal.</p>'
    else:
        body = _table(("Severite", "Code", "Message"), rows)
    return (
        "<section>"
        f"<h2>Integrite <span class=\"count\">{len(rows)}</span></h2>"
        f"{body}"
        "</section>"
    )


def _section_challenge(challenge: Any) -> str:
    if not isinstance(challenge, dict) or challenge.get("enabled") is not True:
        return (
            "<section><h2>Challenge</h2>"
            '<p class="empty">Aucun challenge simule pour cette execution.</p></section>'
        )
    verdict = challenge.get("verdict") if isinstance(challenge.get("verdict"), dict) else {}
    rows = [
        ("Etat", verdict.get("state")),
        ("Etat indicatif", verdict.get("indicative_state")),
        ("Etape", f"{verdict.get('step_index')} ({verdict.get('steps_completed')} validee(s))"),
        ("PnL total", verdict.get("total_pnl")),
        ("PnL journalier", verdict.get("daily_pnl")),
        ("Drawdown max", verdict.get("max_drawdown")),
        ("Jours profitables", f"{verdict.get('profitable_days')} / {verdict.get('trading_days')}"),
        ("Distance cible", verdict.get("distance_to_target")),
        ("Distance limite jour", verdict.get("distance_to_daily_limit")),
        ("Distance limite totale", verdict.get("distance_to_total_limit")),
    ]
    parts = [
        "<section><h2>Challenge</h2>",
        _table(("Metrique", "Valeur"), rows),
    ]
    reasons = verdict.get("reasons")
    if isinstance(reasons, list) and reasons:
        parts.append("<h3>Motifs</h3><ul>")
        parts.extend(f"<li>{_e(item)}</li>" for item in reasons)
        parts.append("</ul>")
    parts.append("</section>")
    return "".join(parts)


def _section_quality(quality: dict[str, Any], metrics: dict[str, Any]) -> str:
    rows = [
        ("Qualite OK", quality.get("ok")),
        ("Lignes acceptees", quality.get("rows_accepted")),
        ("Lignes rejetees", quality.get("rows_rejected")),
        ("Trous", metrics.get("data_gaps")),
        ("Barres manquantes", metrics.get("missing_bars")),
        ("Couverture", quality.get("coverage_ratio")),
    ]
    warnings = quality.get("warnings")
    parts = ["<section><h2>Donnees</h2>", _table(("Controle", "Valeur"), rows)]
    if isinstance(warnings, list) and warnings:
        parts.append("<h3>Avertissements</h3><ul>")
        parts.extend(f"<li>{_e(item)}</li>" for item in warnings)
        parts.append("</ul>")
    parts.append("</section>")
    return "".join(parts)


def _section_orders(orders: Any) -> str:
    if not isinstance(orders, dict) or not isinstance(orders.get("details"), list):
        return "<section><h2>Ordres</h2><p class=\"empty\">Aucun detail d'ordre.</p></section>"
    details = orders["details"]
    rows = [
        (
            order.get("order_id"),
            order.get("side"),
            order.get("order_type"),
            order.get("status"),
            order.get("quantity"),
            order.get("average_fill_price"),
        )
        for order in details[:MAX_TABLE_ROWS]
        if isinstance(order, dict)
    ]
    note = _truncation_note(len(details), len(rows))
    return (
        "<section><h2>Ordres</h2>"
        + _table(("ID", "Sens", "Type", "Statut", "Quantite", "Prix moyen"), rows)
        + note
        + "</section>"
    )


def _section_executions(executions: Any) -> str:
    if not isinstance(executions, dict) or not isinstance(executions.get("details"), list):
        return "<section><h2>Executions</h2><p class=\"empty\">Aucune execution.</p></section>"
    details = executions["details"]
    rows = [
        (
            fill.get("order_id"),
            fill.get("side"),
            fill.get("quantity"),
            fill.get("price"),
            fill.get("commission"),
            ns_to_iso(int(fill["ts_ns"])) if _is_int(fill.get("ts_ns")) else None,
        )
        for fill in details[:MAX_TABLE_ROWS]
        if isinstance(fill, dict)
    ]
    note = _truncation_note(len(details), len(rows))
    return (
        "<section><h2>Executions</h2>"
        + _table(("Ordre", "Sens", "Quantite", "Prix", "Frais", "Horodatage simule"), rows)
        + note
        + "</section>"
    )


def _section_events(view: CockpitView) -> str:
    if not view.entries:
        return (
            "<section><h2>Journal</h2>"
            '<p class="empty">Journal non fourni : la chronologie ne peut pas etre affichee.</p>'
            "</section>"
        )
    selected = view.entries[-MAX_EVENT_ROWS:]
    rows = [
        (
            entry.get("seq"),
            ns_to_iso(int(entry["ts_ns"])) if _is_int(entry.get("ts_ns")) else None,
            entry.get("type"),
            (entry.get("payload") or {}).get("reason", "")
            if isinstance(entry.get("payload"), dict)
            else "",
        )
        for entry in selected
        if isinstance(entry, dict)
    ]
    note = _truncation_note(len(view.entries), len(rows))
    return (
        "<section><h2>Journal</h2>"
        + _table(("Seq", "Horodatage simule", "Type", "Motif"), rows)
        + note
        + "</section>"
    )


def _section_observability(section: Any) -> str:
    if not isinstance(section, dict):
        return (
            "<section><h2>Observabilite</h2>"
            '<p class="empty">Section absente du rapport.</p></section>'
        )
    counts = section.get("event_counts")
    rows = (
        [(name, value) for name, value in sorted(counts.items())]
        if isinstance(counts, dict)
        else []
    )
    session_ids = section.get("session_ids")
    if isinstance(session_ids, list):
        sessions = ", ".join(str(item) for item in session_ids)
    else:
        sessions = str(session_ids)
    summary = (
        f"Dernier evenement: {_e(section.get('last_event_type'))} - "
        f"chronologique: {_e(section.get('chronological'))} - "
        f"sessions: {_e(sessions)}"
    )
    body = _table(("Type", "Nombre"), rows) if rows else ""
    return f"<section><h2>Observabilite</h2><p>{summary}</p>{body}</section>"


def _section_table(title: str, headers: tuple[str, ...], rows: list[tuple]) -> str:
    return f"<section><h2>{_e(title)}</h2>{_table(headers, rows)}</section>"


def _table(headers: tuple[str, ...], rows: list[tuple]) -> str:
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _truncation_note(total: int, shown: int) -> str:
    if total <= shown:
        return ""
    return f'<p class="muted">{total - shown} ligne(s) supplementaire(s) non affichee(s).</p>'


# -- helpers ------------------------------------------------------------
def _add(view: CockpitView, severity: str, code: str, message: str) -> None:
    view.findings.append(Finding(severity, code, message))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: Any) -> float:
    return float(value) if _is_number(value) else 0.0


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-9, abs(left) * 1e-9, abs(right) * 1e-9)


def _e(value: Any) -> str:
    if value is None:
        return "-"
    return html_module.escape(str(value), quote=True)


_CSS = """
:root{color-scheme:dark;--bg:#0b1020;--panel:#131a2d;--line:#26314d;--text:#e8edf8;
--muted:#98a5bd;--accent:#5cc8ff;--ok:#44d492;--warn:#f0b84b;--fail:#ff6b7a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 "Segoe UI",system-ui,sans-serif}main{max-width:1180px;margin:0 auto;
padding:32px 20px 56px}h1{font-size:30px;line-height:1.2;margin:4px 0 10px}
h2{font-size:18px;margin:0 0 12px}h3{font-size:15px;margin:18px 0 6px}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:18px;margin:0 0 16px}.hero{background:radial-gradient(circle at 15% 0,#1c2c4b,var(--panel));
padding:26px}.eyebrow{letter-spacing:.16em;font-size:11px;color:var(--accent);margin:0}
.muted,.count{color:var(--muted)}.count{font-size:12px;font-weight:400}
.badge{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;
font-weight:700;margin-right:8px}.badge.ok{background:#103526;color:var(--ok)}
.badge.warn{background:#3a2c10;color:var(--warn)}.badge.fail{background:#3c1620;color:var(--fail)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
margin:0 0 16px}.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.kpi span{display:block;color:var(--muted);font-size:12px}.kpi strong{display:block;
font-size:20px;margin-top:5px;font-variant-numeric:tabular-nums}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px 10px;
border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);background:#101728;font-weight:600}tr:last-child td{border-bottom:0}
code{color:var(--accent);font-family:Consolas,monospace;font-size:12px}
.empty{margin:0;color:var(--muted)}ul{margin:6px 0 0;padding-left:20px}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:24px}
@media(max-width:640px){main{padding:18px 12px}h1{font-size:24px}}
"""
