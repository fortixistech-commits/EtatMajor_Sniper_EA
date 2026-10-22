"""Validation du profil de challenge The5ers (lecture seule).

Ce test ne declare pas le profil utilisable : il verifie que le fichier est
lisible par la bibliotheque standard, que les valeurs relevees sont
coherentes entre elles, et que le profil reste explicitement marque DRAFT
tant que les verrous documentes ne sont pas leves.

Reference : docs/propfirm/THE5ERS_REFERENCE.md
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "prop_firms"
    / "the5ers_high_stakes_new_2500.draft.toml"
)


@pytest.fixture(scope="module")
def profile() -> dict:
    assert PROFILE_PATH.exists(), f"profil absent : {PROFILE_PATH}"
    return tomllib.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_profile_is_readable_and_identified(profile):
    assert profile["profile_id"] == "the5ers-high-stakes-new-2500"
    assert profile["profile_version"] == "0.1.0-draft"
    assert profile["verified_on"] == "2026-10-22"
    assert profile["sources"], "les sources officielles doivent etre referencees"


def test_profile_is_still_a_draft_and_cannot_conclude(profile):
    """Tant que les verrous sont ouverts, le profil ne peut pas statuer."""
    assert profile["profile_status"] == "DRAFT"
    assert profile["evaluation"]["inconclusive_status"] == "INVALID"
    assert profile["evaluation"]["pass_requires_all_interpretations"] is True
    assert profile["evaluation"]["policy"] == "most_restrictive_interpretation"


def test_recorded_values_match_the_official_display(profile):
    program = profile["program"]
    assert program["name"] == "High Stakes"
    assert program["variant"] == "New"
    assert program["platform"] == "MT5 Hedge"
    assert program["fee_displayed"] == 19.0

    account = profile["account"]
    assert account["initial_capital"] == 2500.0

    limits = profile["limits"]
    assert limits["max_daily_loss_percent"] == 5.0
    assert limits["max_total_loss_percent"] == 10.0
    assert limits["max_daily_loss_amount"] == 125.0
    assert limits["max_total_loss_amount"] == 250.0

    steps = profile["steps"]
    assert len(steps) == 2
    assert steps[0]["profit_target_percent"] == 10.0
    assert steps[0]["profit_target_amount"] == 250.0
    assert steps[1]["profit_target_percent"] == 5.0
    assert steps[1]["profit_target_amount"] == 125.0
    assert all(step["min_profitable_days"] == 3 for step in steps)


def test_percentages_are_consistent_with_the_account(profile):
    capital = profile["account"]["initial_capital"]
    for step in profile["steps"]:
        expected = capital * step["profit_target_percent"] / 100.0
        assert step["profit_target_amount"] == pytest.approx(expected)
    limits = profile["limits"]
    assert limits["max_daily_loss_amount"] == pytest.approx(
        capital * limits["max_daily_loss_percent"] / 100.0
    )
    assert limits["max_total_loss_amount"] == pytest.approx(
        capital * limits["max_total_loss_percent"] / 100.0
    )


def test_every_unresolved_rule_is_declared(profile):
    """Aucune regle inconnue ne doit disparaitre du profil."""
    ids = {rule["id"] for rule in profile["ambiguous_rules"]}
    assert ids == {"V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"}
    for rule in profile["ambiguous_rules"]:
        assert rule["status"] == "UNRESOLVED"
        assert rule["description"].strip()
        assert rule["evaluation_policy"] in {
            "most_restrictive",
            "report_explicitly",
            "blocking_for_real_evaluation",
        }


def test_the_unresolved_drawdown_and_reset_are_explicit(profile):
    limits = profile["limits"]
    assert limits["drawdown_type"] == "UNRESOLVED"
    assert limits["drawdown_basis"] == "UNRESOLVED"
    assert limits["daily_reset_time"] == "UNRESOLVED"
    assert limits["daily_reset_timezone"] == "UNRESOLVED"


def test_written_authorization_blocks_real_evaluation(profile):
    rule = next(r for r in profile["ambiguous_rules"] if r["id"] == "V8")
    assert rule["evaluation_policy"] == "blocking_for_real_evaluation"
    assert rule["blocking_scope"] == "mission_14"


def test_allowed_states_cover_the_documented_machine(profile):
    assert profile["evaluation"]["allowed_states"] == [
        "READY",
        "RUNNING",
        "PASSED",
        "FAILED",
        "INVALID",
        "REVIEW_REQUIRED",
    ]
