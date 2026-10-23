"""Phase 8 cockpit: integrity checks, deterministic rendering and safety."""

from __future__ import annotations

import copy
import json

import pytest

from etatmajor.core.errors import CockpitError
from etatmajor.replay.engine import ReplayEngine
from etatmajor.reporting.cockpit import (
    build_cockpit,
    load_journal,
    render_console,
    render_dashboard,
)
from etatmajor.reporting.report import report_fingerprint
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset

PRICES = [1.10000 + 0.00020 * index for index in range(12)]


def build_result():
    return ReplayEngine(
        dataset=make_dataset(PRICES),
        config=make_config(),
        strategy=DemoLifecycleStrategy(
            symbol="EURUSD",
            timeframe="1m",
            quantity=1_000.0,
            entry_index=2,
            exit_index=6,
        ),
    ).run()


def valid_view():
    result = build_result()
    return result, build_cockpit(result.report, result.journal.to_list())


def reseal(report: dict) -> dict:
    report["report_fingerprint"] = report_fingerprint(report)
    return report


def codes(view) -> set[str]:
    return {finding.code for finding in view.findings}


def test_a_valid_run_has_no_finding():
    _, view = valid_view()
    assert view.ok is True
    assert view.strict_ok is True
    assert view.errors == []
    assert view.warnings == []
    assert view.metrics()["challenge_enabled"] is False


def test_a_tampered_report_is_refused():
    result, _ = valid_view()
    report = copy.deepcopy(result.report)
    report["account"]["net_pnl"] += 1.0
    view = build_cockpit(report, result.journal.to_list())
    assert view.ok is False
    assert "REPORT_FINGERPRINT_MISMATCH" in codes(view)


def test_a_journal_sequence_gap_is_refused():
    result, _ = valid_view()
    entries = result.journal.to_list()
    entries[3]["seq"] = 9
    view = build_cockpit(result.report, entries)
    assert view.ok is False
    assert "JOURNAL_SEQUENCE_GAP" in codes(view)


def test_a_missing_replay_finished_is_refused():
    result, _ = valid_view()
    view = build_cockpit(result.report, result.journal.to_list()[:-1])
    assert view.ok is False
    assert "JOURNAL_FINISH_COUNT" in codes(view)
    assert "JOURNAL_FINISH_NOT_LAST" in codes(view)
    assert "JOURNAL_COUNT_MISMATCH" in codes(view)


def test_a_failed_reconciliation_event_is_refused():
    result, _ = valid_view()
    entries = result.journal.to_list()
    for entry in entries:
        if entry["type"] == "RECONCILIATION":
            entry["payload"]["reconciled"] = False
    view = build_cockpit(result.report, entries)
    assert view.ok is False
    assert "RECONCILIATION_EVENT_FAILED" in codes(view)


def test_a_missing_observability_section_is_a_warning():
    result, _ = valid_view()
    report = copy.deepcopy(result.report)
    report.pop("observability")
    reseal(report)
    view = build_cockpit(report, result.journal.to_list())
    assert view.ok is True
    assert "OBSERVABILITY_MISSING" in codes(view)


def test_html_is_standalone_and_escapes_untrusted_values():
    result, view = valid_view()
    report = copy.deepcopy(result.report)
    report["strategy"]["id"] = "<img src=x onerror=alert(1)>"
    reseal(report)
    dirty = build_cockpit(report, result.journal.to_list())
    dashboard = render_dashboard(dirty)

    assert dashboard == render_dashboard(dirty)
    assert "<script" not in dashboard.lower()
    assert "<img" not in dashboard.lower()
    assert "&lt;img" in dashboard
    assert "http://" not in dashboard
    assert "https://" not in dashboard
    assert dashboard.startswith("<!doctype html>")


def test_console_states_the_verdict_and_the_simulation_warning():
    _, view = valid_view()
    text = render_console(view)
    assert "Status        : PASS" in text
    assert "simulation evidence only" in text


def test_console_reports_a_broken_journal():
    result, _ = valid_view()
    entries = result.journal.to_list()[:-1]
    view = build_cockpit(result.report, entries)
    text = render_console(view)
    assert "Status        : FAIL" in text
    assert "JOURNAL_FINISH" in text


def test_a_malformed_journal_line_is_reported(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('{"seq": 0}\nnot-json\n', encoding="utf-8")
    with pytest.raises(CockpitError, match="line 2"):
        load_journal(path)


def test_cockpit_snapshot_is_deterministic_and_serialisable():
    _, view = valid_view()
    first = json.dumps(view.to_dict(), sort_keys=True)
    second = json.dumps(view.to_dict(), sort_keys=True)
    assert first == second
    payload = json.loads(first)
    assert payload["ok"] is True
    assert payload["journal_provided"] is True
    assert payload["metrics"]["orders"] == 2
    assert payload["event_counts"]["REPLAY_FINISHED"] == 1
