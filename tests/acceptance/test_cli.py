"""Acceptance test: complete laboratory run through the command line.

This is the scenario presented in the Phase 2 deliverable: a reproducible
command producing a machine readable report and an auditable journal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from etatmajor.core.config import load_config
from etatmajor.data.loader import load_csv
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.acceptance


def test_full_run_produces_a_report_and_a_journal(tmp_path):
    data_path = REPO_ROOT / "data" / "sample_eurusd_1m.csv"
    config_path = REPO_ROOT / "configs" / "simulation.toml"
    report_path = tmp_path / "report.json"
    journal_path = tmp_path / "journal.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "etatmajor.cli",
            "replay",
            "--data",
            str(data_path),
            "--config",
            str(config_path),
            "--report",
            str(report_path),
            "--journal",
            str(journal_path),
            "--pending-limit",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ETAT-MAJOR SNIPER EA" in completed.stdout
    assert "simulation" in completed.stdout

    report = json.loads(report_path.read_text(encoding="utf-8"))
    for key in (
        "symbol",
        "period",
        "bars",
        "orders",
        "executions",
        "transactions",
        "fees",
        "account",
        "rejections",
        "end_of_replay_policy",
    ):
        assert key in report, key

    assert report["symbol"] == "EURUSD"
    assert report["bars"] == 240
    assert report["account"]["initial_capital"] == 100000.0
    assert report["simulation_only"] is True
    assert report["mode"] == "LABORATORY"

    account = report["account"]
    assert account["net_pnl"] == pytest.approx(
        account["realized_pnl"] + account["unrealized_pnl"] - account["fees"]
    )
    assert account["final_equity"] == pytest.approx(
        account["cash"] + account["unrealized_pnl"]
    )

    lines = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    types = {line["type"] for line in lines}
    assert {"SIGNAL", "RISK_DECISION", "ORDER_SUBMITTED", "ORDER_FILLED"} <= types
    assert lines[0]["seq"] == 0
    assert [line["seq"] for line in lines] == list(range(len(lines)))


def test_validate_command_reports_the_quality_of_the_dataset(tmp_path):
    data_path = REPO_ROOT / "data" / "sample_eurusd_1m.csv"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "etatmajor.cli",
            "validate",
            "--data",
            str(data_path),
            "--config",
            str(REPO_ROOT / "configs" / "simulation.toml"),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.split("Dataset OK")[0])
    assert payload["ok"] is True
    assert payload["rows_accepted"] == 240


def test_the_cli_refuses_a_malformed_dataset(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "timestamp,open,high,low,close\n"
        "2026-01-05T00:00:00Z,1.1,1.2,1.0,1.15\n"
        "2026-01-05T00:00:00Z,1.15,1.2,1.1,1.18\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "etatmajor.cli",
            "validate",
            "--data",
            str(bad),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert completed.returncode == 2
    assert "duplicated timestamp" in completed.stderr


def test_the_repository_shipped_example_report_is_consistent():
    """The committed example report matches a fresh run of the same command."""
    example = REPO_ROOT / "artifacts" / "example_report.json"
    if not example.exists():  # pragma: no cover
        pytest.skip("example report not generated yet")

    committed = json.loads(example.read_text(encoding="utf-8"))
    config = load_config(REPO_ROOT / "configs" / "simulation.toml")
    dataset = load_csv(
        REPO_ROOT / "data" / "sample_eurusd_1m.csv",
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        timeframe_ns=config.simulation.timeframe_ns,
    )

    from etatmajor.replay.engine import ReplayEngine
    from etatmajor.strategies.demo import DemoLifecycleStrategy

    strategy = DemoLifecycleStrategy(
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        quantity=10_000.0,
        entry_index=2,
        exit_index=6,
    )
    result = ReplayEngine(dataset=dataset, config=config, strategy=strategy).run()

    assert result.report["account"] == committed["account"]
    assert result.report["report_fingerprint"] == committed["report_fingerprint"]
