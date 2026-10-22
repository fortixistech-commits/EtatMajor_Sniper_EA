"""Reproducibility tests (mandatory assertion 1)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import REPO_ROOT, make_config, make_dataset

PRICES = [1.10000 + 0.00020 * i for i in range(12)]


def build(dataset, config):
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=1_000.0,
        entry_index=2,
        exit_index=6,
        place_pending_limit=True,
    )
    return ReplayEngine(dataset=dataset, config=config, strategy=strategy).run()


def test_two_identical_replays_produce_identical_reports():
    dataset = make_dataset(PRICES)
    config = make_config()
    first = build(dataset, config)
    second = build(dataset, config)

    assert first.report == second.report
    assert first.report["report_fingerprint"] == second.report["report_fingerprint"]


def test_two_identical_replays_produce_identical_journals():
    dataset = make_dataset(PRICES)
    config = make_config()
    first = build(dataset, config)
    second = build(dataset, config)

    assert first.journal.to_list() == second.journal.to_list()


def test_the_report_contains_no_wall_clock_information():
    dataset = make_dataset(PRICES)
    result = build(dataset, make_config())
    blob = json.dumps(result.report, default=str)
    assert "generated_at" not in blob
    assert "timestamp_now" not in blob


def test_replay_is_stable_across_processes(tmp_path):
    """The same command twice produces byte-identical reports."""
    from etatmajor.data.loader import load_csv

    data_path = REPO_ROOT / "data" / "sample_eurusd_1m.csv"
    if not data_path.exists():  # pragma: no cover
        import pytest

        pytest.skip("sample dataset missing")

    outputs = []
    for index in range(2):
        report_path = tmp_path / f"report_{index}.json"
        command = [
            sys.executable,
            "-m",
            "etatmajor.cli",
            "replay",
            "--data",
            str(data_path),
            "--config",
            str(REPO_ROOT / "configs" / "simulation.toml"),
            "--report",
            str(report_path),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, cwd=str(REPO_ROOT), check=False
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(report_path.read_text(encoding="utf-8"))

    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["simulation_only"] is True


def test_a_different_seed_changes_the_random_slippage_only():
    dataset = make_dataset(PRICES)
    first = build(dataset, make_config(seed=1))
    second = build(dataset, make_config(seed=2))
    assert first.report["dataset_fingerprint"] == second.report["dataset_fingerprint"]
    assert first.report["config_fingerprint"] != second.report["config_fingerprint"]
