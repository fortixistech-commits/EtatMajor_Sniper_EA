"""Phase 8 integration: cockpit over a complete challenge campaign."""

from __future__ import annotations

import copy

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.reporting.cockpit import build_cockpit, render_dashboard
from tests.integration.test_phase7_pipeline import (
    build_demo,
    challenge_profile,
    winning_prices,
)


def campaign():
    profile = challenge_profile(steps=1, target=5.0, initial=1000.0)
    challenge = ChallengeEngine(profile, initial_capital=1000.0)
    return build_demo(winning_prices(), capital=1000.0, challenge=challenge)


def test_the_cockpit_exposes_a_conclusive_challenge_and_a_valid_journal():
    result = campaign()
    view = build_cockpit(result.report, result.journal.to_list())

    assert view.ok is True
    assert view.strict_ok is True
    metrics = view.metrics()
    assert metrics["challenge_enabled"] is True
    assert metrics["challenge_state"] == "PASSED"
    assert view.event_counts["CHALLENGE_FINALIZED"] == 1
    assert view.event_counts["REPLAY_FINISHED"] == 1

    dashboard = render_dashboard(view)
    assert "PASSED" in dashboard
    assert "Challenge" in dashboard


def test_a_challenge_verdict_mismatch_is_refused():
    result = campaign()
    entries = copy.deepcopy(result.journal.to_list())
    for entry in entries:
        if entry["type"] == "CHALLENGE_FINALIZED":
            entry["payload"]["verdict"]["state"] = "FAILED"
    view = build_cockpit(result.report, entries)

    assert view.ok is False
    assert "CHALLENGE_VERDICT_MISMATCH" in {
        finding.code for finding in view.findings
    }


def test_the_cockpit_is_byte_deterministic_for_a_challenge_run():
    result = campaign()
    first = build_cockpit(result.report, result.journal.to_list())
    second = build_cockpit(result.report, result.journal.to_list())
    assert render_dashboard(first) == render_dashboard(second)
    assert first.to_dict() == second.to_dict()
