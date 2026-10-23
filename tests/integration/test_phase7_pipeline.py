"""Phase 7 integration: end-to-end replay, challenge and traceability.

The suite verifies the complete pipeline (data -> intelligence -> strategy ->
risk -> execution -> accounting -> challenge -> report) and the guarantees
that matter for a challenge campaign:

* no transaction is invented when the strategy abstains;
* a winning trajectory passes a verified profile, a losing one fails it;
* challenge transitions and the final verdict are journaled, in order;
* a kill switch survives a restart and blocks new risk;
* the same inputs produce the same report (reproducibility);
* account, challenge and reconciliation metrics agree.

No real order is ever sent: everything runs in the simulated broker.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.challenge.profile import ChallengeProfile
from etatmajor.core.errors import ConfigurationError
from etatmajor.core.models import ChallengeState
from etatmajor.core.types import EventType
from etatmajor.data.models import Bar
from etatmajor.data.loader import Dataset
from etatmajor.replay.engine import ReplayEngine
from etatmajor.risk.governor import MinimalRiskGovernor
from etatmajor.risk.killswitch import KillSwitch
from etatmajor.sniper.planner import MissionPlanner
from etatmajor.sniper.settings import build_engine
from etatmajor.sniper.strategy import SniperStrategy
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import REPO_ROOT, make_config, make_dataset

LONDON_BASE_NS = 1_767_571_200_000_000_000 + 8 * 3_600_000_000_000
TIMEFRAME_NS = 60_000_000_000


def make_london_dataset(closes: list[float]) -> Dataset:
    bars = []
    for index, close in enumerate(closes):
        open_ = closes[index - 1] if index else close
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        bars.append(
            Bar(
                ts_open_ns=LONDON_BASE_NS + index * TIMEFRAME_NS,
                ts_close_ns=LONDON_BASE_NS + (index + 1) * TIMEFRAME_NS,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
            )
        )
    return Dataset(symbol="EURUSD", timeframe="1m", bars=tuple(bars))


def trending_with_pullback() -> list[float]:
    closes = [1.10000 + 0.00005 * i for i in range(60)]
    closes.append(1.10248)
    closes.append(1.10258)
    return closes


def ranging() -> list[float]:
    return [
        1.10000 + (0.00020 if (index // 5) % 2 == 0 else -0.00020)
        for index in range(120)
    ]


def sniper_strategy(data_quality: object | None = None) -> SniperStrategy:
    engine = build_engine(
        "EURUSD",
        "1m",
        make_config().sniper,
        data_quality=data_quality,
    )
    engine.planner = MissionPlanner(risk_amount=20.0, min_quantity=0.01)
    return SniperStrategy(symbol="EURUSD", timeframe="1m", engine=engine)


def challenge_profile(
    *, steps: int = 1, target: float = 5.0, initial: float = 1000.0
) -> ChallengeProfile:
    return ChallengeProfile.from_dict(
        {
            "profile_status": "VERIFIED",
            "profile_id": "phase7-test",
            "profile_version": "1.0.0",
            "verified_on": "2026-10-22",
            "verified_by": "tests",
            "sources": ["https://example.invalid/rules"],
            "program": {"name": "Test", "variant": "New", "platform": "MT5"},
            "account": {
                "initial_capital": initial,
                "reference_capital": initial,
            },
            "steps": [
                {
                    "index": index + 1,
                    "profit_target_percent": 100.0 * target / initial,
                    "profit_target_amount": target,
                    "min_profitable_days": 0,
                }
                for index in range(steps)
            ],
            "limits": {
                "max_daily_loss_percent": 5.0,
                "max_daily_loss_amount": 50.0,
                "max_total_loss_percent": 10.0,
                "max_total_loss_amount": 100.0,
                "drawdown_type": "static",
                "drawdown_basis": "balance",
                "daily_reset_time": "00:00",
                "daily_reset_timezone": "UTC",
            },
            "trading_days": {
                "min_profitable_days_per_step": 0,
                "profitable_day_definition": "realised net pnl > 0",
            },
            "evaluation": {"policy": "most_restrictive_interpretation"},
            "ambiguous_rules": [],
        }
    )


def winning_prices() -> list[float]:
    return [1.10000] * 4 + [1.12000] * 16


def losing_prices() -> list[float]:
    return [1.10000] * 4 + [0.98000] * 16


def build_demo(
    prices: list[float],
    capital: float = 1000.0,
    challenge=None,
    quantity: float = 500.0,
):
    config = make_config(initial_capital=capital)
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD",
        timeframe="1m",
        quantity=quantity,
        entry_index=2,
        exit_index=10,
    )
    engine = ReplayEngine(
        dataset=make_dataset(prices),
        config=config,
        strategy=strategy,
        challenge=challenge,
    )
    return engine.run()


# -- the Sniper pipeline reaches the broker ---------------------------------
def test_the_sniper_pipeline_can_engage_through_risk_and_execution():
    closes = trending_with_pullback() + [1.10258, 1.10260]
    result = ReplayEngine(
        dataset=make_london_dataset(closes),
        config=make_config(),
        strategy=sniper_strategy(),
    ).run()

    assert result.report["strategy"]["engagements"] > 0
    assert result.report["orders"]["total"] > 0
    assert result.report["executions"]["total"] > 0
    types = {entry.type for entry in result.journal.entries}
    assert {
        EventType.SIGNAL.value,
        EventType.RISK_DECISION.value,
        EventType.ORDER_SUBMITTED.value,
        EventType.ORDER_FILLED.value,
    } <= types
    # The report exposes the decision counters (traceability, not just orders).
    assert result.report["strategy"]["abstentions"] >= 0
    assert (
        result.report["strategy"]["abstentions"]
        + result.report["strategy"]["engagements"]
        == 64
    )


def test_an_abstaining_series_never_produces_a_transaction():
    result = ReplayEngine(
        dataset=make_london_dataset(ranging()),
        config=make_config(),
        strategy=sniper_strategy(),
    ).run()

    assert result.report["strategy"]["engagements"] == 0
    assert result.report["strategy"]["abstentions"] > 0
    assert result.report["orders"]["total"] == 0
    assert result.report["executions"]["total"] == 0
    assert result.report["transactions"] == 0
    assert result.report["account"]["net_pnl"] == 0.0


def test_degraded_data_is_refused_by_the_sniper_pipeline():
    quality = {
        "bar_count": 62,
        "missing_bars": 31,
        "expected_bars": 62,
        "errors": 0,
        "warnings": 1,
    }
    result = ReplayEngine(
        dataset=make_london_dataset(trending_with_pullback()),
        config=make_config(),
        strategy=sniper_strategy(data_quality=quality),
    ).run()

    assert result.report["orders"]["total"] == 0
    assert result.report["strategy"]["engagements"] == 0
    assert result.report["strategy"]["abstentions"] == 62


def test_the_cli_can_run_the_sniper_strategy(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "etatmajor.cli",
            "replay",
            "--strategy",
            "sniper",
            "--data",
            str(REPO_ROOT / "data" / "sample_eurusd_1m.csv"),
            "--config",
            str(REPO_ROOT / "configs" / "simulation.toml"),
            "--instrument-catalog",
            str(REPO_ROOT / "configs" / "instruments.toml"),
            "--broker-id",
            "mt5_demo",
            "--report",
            str(tmp_path / "report.json"),
            "--journal",
            str(tmp_path / "journal.jsonl"),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["strategy"]["id"] == "sniper-engine"
    assert report["strategy"]["abstentions"] + report["strategy"]["engagements"] == 240
    lines = [
        json.loads(line)
        for line in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[-1]["type"] == EventType.REPLAY_FINISHED.value


# -- challenge scenarios -----------------------------------------------------
def test_a_winning_trajectory_passes_a_verified_profile_and_is_journaled():
    challenge = ChallengeEngine(challenge_profile(target=5.0), initial_capital=1000.0)
    result = build_demo(winning_prices(), challenge=challenge)

    section = result.report["challenge"]
    assert section["verdict"]["state"] == ChallengeState.PASSED.value
    assert section["verdict"]["steps_completed"] == 1
    assert section["verdict"]["total_pnl"] > 0

    entries = result.journal.entries
    types = [entry.type for entry in entries]
    assert EventType.CHALLENGE_EVENT.value in types
    assert EventType.CHALLENGE_FINALIZED.value in types
    assert types[-1] == EventType.REPLAY_FINISHED.value
    passed = [
        entry
        for entry in result.journal.of_type(EventType.CHALLENGE_EVENT.value)
        if entry.payload["kind"] == "passed"
    ]
    assert passed
    assert passed[-1].payload["steps_completed"] == 1


def test_a_losing_trajectory_fails_the_profile_terminally():
    challenge = ChallengeEngine(challenge_profile(target=5.0), initial_capital=1000.0)
    result = build_demo(losing_prices(), challenge=challenge)

    verdict = result.report["challenge"]["verdict"]
    assert verdict["state"] == ChallengeState.FAILED.value
    assert verdict["failures"]
    assert verdict["is_conclusive"] is True
    assert challenge.blocks_new_risk()[0] is True
    assert result.report["account"]["net_pnl"] == pytest.approx(
        verdict["total_pnl"]
    )


def test_a_multi_step_profile_records_each_advance():
    challenge = ChallengeEngine(
        challenge_profile(steps=2, target=5.0), initial_capital=1000.0
    )
    result = build_demo(winning_prices(), challenge=challenge)

    advances = [
        entry
        for entry in result.journal.of_type(EventType.CHALLENGE_EVENT.value)
        if entry.payload["kind"] == "step_advanced"
    ]
    assert len(advances) == 1
    assert advances[0].payload["steps_completed"] == 1
    # The same favourable equity validates the last step: the profile is
    # passed, and the report counts both steps as completed.
    assert result.report["challenge"]["verdict"]["state"] == (
        ChallengeState.PASSED.value
    )
    assert result.report["challenge"]["verdict"]["steps_completed"] == 2


def test_repeated_observations_do_not_duplicate_the_verdict_events():
    challenge = ChallengeEngine(challenge_profile(target=5.0), initial_capital=1000.0)
    result = build_demo(winning_prices(), challenge=challenge)
    events = result.journal.of_type(EventType.CHALLENGE_FINALIZED.value)
    assert len(events) == 1
    # The final event carries the frozen verdict.
    assert events[0].payload["verdict"]["state"] == ChallengeState.PASSED.value


# -- safety, reproducibility, metric agreement ------------------------------
def test_the_kill_switch_survives_a_restart_and_blocks_new_risk(tmp_path):
    path = tmp_path / "killswitch.json"
    KillSwitch(path).engage("phase7 restart test", ts_ns=1)
    restarted = KillSwitch(path)
    assert restarted.engaged is True

    config = make_config(initial_capital=1000.0)
    governor = MinimalRiskGovernor(config.risk, kill_switch=restarted)
    result = ReplayEngine(
        dataset=make_dataset(winning_prices()),
        config=config,
        strategy=DemoLifecycleStrategy(
            symbol="EURUSD",
            timeframe="1m",
            quantity=500.0,
            entry_index=2,
            exit_index=10,
        ),
        risk_governor=governor,
    ).run()
    assert result.report["orders"]["total"] == 0
    assert result.report["rejections"]["risk_count"] >= 1
    assert "kill switch engaged" in str(result.report["rejections"]["risk"])
    assert restarted.to_dict()["engagement_count"] >= 1


def test_a_kill_switch_can_only_be_rearmed_with_a_reason(tmp_path):
    path = tmp_path / "killswitch.json"
    switch = KillSwitch(path)
    switch.engage("test")
    with pytest.raises(ConfigurationError):
        switch.reset("")
    switch.reset("manual rearm after incident", ts_ns=2, operator="tester")
    assert KillSwitch(path).engaged is False
    assert KillSwitch(path).state.last_reset_reason.startswith("manual rearm")


def test_two_identical_runs_produce_identical_reports_and_journals():
    def run() -> tuple[dict, list[dict]]:
        challenge = ChallengeEngine(
            challenge_profile(target=5.0), initial_capital=1000.0
        )
        result = build_demo(winning_prices(), challenge=challenge)
        return result.report, result.journal.to_list()

    first_report, first_journal = run()
    second_report, second_journal = run()
    assert first_report == second_report
    assert first_journal == second_journal


def test_account_challenge_and_reconciliation_metrics_agree():
    challenge = ChallengeEngine(challenge_profile(target=5.0), initial_capital=1000.0)
    result = build_demo(winning_prices(), challenge=challenge)
    report = result.report

    account = report["account"]
    verdict = report["challenge"]["verdict"]
    reconciliation = report["reconciliation"]
    assert account["net_pnl"] == pytest.approx(verdict["total_pnl"])
    assert verdict["total_pnl"] == pytest.approx(
        account["realized_pnl"] + account["unrealized_pnl"] - account["fees"]
    )
    assert reconciliation["reconciled"] is True
    assert reconciliation["fills"] == report["executions"]["total"]
    assert report["transactions"] == report["executions"]["total"]
