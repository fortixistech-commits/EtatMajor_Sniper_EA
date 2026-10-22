"""Tests du Challenge Engine (Mission 7).

Le moteur doit repondre a la question centrale du produit : « aurions-nous
respecte les regles du challenge jusqu'a sa validation ? ».

Ces tests verifient des **verdicts**, pas seulement l'absence d'exception :
frontieres exactes (juste avant / au seuil / juste apres), transitions
d'etape, lecture la plus restrictive, et interdiction de conclure sur un
profil incomplet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.challenge.profile import ChallengeProfile, ProfileStatus
from etatmajor.core.errors import ConfigurationError
from etatmajor.core.models import AccountState, ChallengeState

DAY_NS = 86_400_000_000_000
BASE_NS = 1_767_571_200_000_000_000  # 2026-01-05T00:00:00Z

PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "prop_firms"
    / "the5ers_high_stakes_new_2500.draft.toml"
)


def _profile_payload() -> dict:
    """Charge utile d'un profil de test complet et verifiable."""
    return {
        "profile_status": "VERIFIED",
        "profile_id": "test-profile",
        "profile_version": "1.0.0",
        "verified_on": "2026-10-22",
        "verified_by": "tests",
        "sources": ["https://example.invalid/rules"],
        "program": {
            "name": "Test",
            "variant": "New",
            "platform": "MT5 Hedge",
            "fee_displayed": 0.0,
            "currency": "USD",
            "max_duration_days": 0,
        },
        "account": {"initial_capital": 1000.0, "reference_capital": 1000.0},
        "steps": [
            {
                "index": 1,
                "profit_target_percent": 10.0,
                "profit_target_amount": 100.0,
                "min_profitable_days": 1,
                "reference_capital": 1000.0,
            }
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
            "min_profitable_days_per_step": 1,
            "profitable_day_definition": "realised net pnl > 0",
        },
        "evaluation": {
            "policy": "most_restrictive_interpretation",
            "pass_requires_all_interpretations": True,
            "inconclusive_status": "INVALID",
            "allowed_states": [
                "READY",
                "RUNNING",
                "PASSED",
                "FAILED",
                "INVALID",
                "REVIEW_REQUIRED",
            ],
        },
        "ambiguous_rules": [],
    }


def make_profile(**overrides) -> ChallengeProfile:
    """Profil de test complet et verifiable, construit en memoire."""
    payload = _profile_payload()
    payload.update(overrides)
    return ChallengeProfile.from_dict(payload)


def account(equity: float, ts_ns: int = BASE_NS, balance: float | None = None) -> AccountState:
    return AccountState(
        account_id="ACC",
        currency="USD",
        balance=equity if balance is None else balance,
        equity=equity,
        ts_ns=ts_ns,
    )


# --- profil ---------------------------------------------------------------
def test_the_shipped_the5ers_profile_is_a_draft():
    profile = ChallengeProfile.from_toml(PROFILE_PATH)
    assert profile.profile_id == "the5ers-high-stakes-new-2500"
    assert profile.profile_status is ProfileStatus.DRAFT
    assert profile.allows_conclusion is False
    assert len(profile.unresolved_rules) == 8
    assert {rule.id for rule in profile.blocking_rules} == {"V8"}


def test_an_inconsistent_profile_is_refused():
    payload = {
        "profile_status": "VERIFIED",
        "profile_id": "broken",
        "steps": [
            {
                "index": 1,
                "profit_target_percent": 10.0,
                "profit_target_amount": 999.0,
                "min_profitable_days": 1,
            }
        ],
        "account": {"initial_capital": 1000.0, "reference_capital": 1000.0},
        "limits": {"max_daily_loss_amount": 50.0, "max_total_loss_amount": 100.0},
    }
    with pytest.raises(ConfigurationError) as excinfo:
        ChallengeProfile.from_dict(payload)
    assert "inconsistent" in str(excinfo.value)


def test_a_profile_without_step_is_refused():
    with pytest.raises(ConfigurationError):
        ChallengeProfile.from_dict(
            {
                "profile_status": "VERIFIED",
                "profile_id": "empty",
                "account": {"initial_capital": 1000.0, "reference_capital": 1000.0},
                "limits": {"max_daily_loss_amount": 50.0, "max_total_loss_amount": 100.0},
            }
        )


# --- verdict --------------------------------------------------------------
def test_a_running_challenge_is_reported_as_running():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.RUNNING
    assert verdict.is_conclusive is False
    assert verdict.distance_to_target == pytest.approx(100.0)
    assert verdict.distance_to_daily_limit == pytest.approx(50.0)


def test_reaching_the_target_without_enough_profitable_days_stays_running():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    # Objectif atteint, mais aucun jour profitable compte.
    engine.observe(BASE_NS + 1000, account(1100.0))
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.RUNNING
    assert any("profitable day" in reason for reason in verdict.reasons)


def test_reaching_the_target_with_the_required_days_passes():
    engine = ChallengeEngine(make_profile())
    hour = 3_600_000_000_000
    # Jour 1 : le solde monte de 10 dans la journee.
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + hour, account(1010.0))
    # Jour 2 : le solde gagne 100 (objectif de l'etape 1 atteint).
    engine.observe(BASE_NS + DAY_NS, account(1010.0))
    engine.observe(BASE_NS + DAY_NS + hour, account(1110.0))
    engine.finalize()
    verdict = engine.evaluate()
    assert verdict.profitable_days == 2
    assert verdict.trading_days == 2
    assert verdict.state is ChallengeState.PASSED
    assert verdict.is_conclusive is True


def test_a_daily_loss_breach_fails_the_challenge():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1000, account(949.0))  # 51 USD perdus, limite 50
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.FAILED
    assert any("daily loss" in reason for reason in verdict.reasons)


def test_a_loss_just_below_the_limit_does_not_fail():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1000, account(950.5))  # 49.5 USD perdus
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.RUNNING


def test_a_total_loss_breach_fails_the_challenge():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1000, account(899.0))  # 101 USD perdus, limite 100
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.FAILED


def test_the_most_restrictive_interpretation_wins():
    """Lecture statique conforme, lecture trailing en echec : le verdict est FAILED."""
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    # Equity chute sous le solde : seule la lecture equity la voit.
    engine.observe(BASE_NS + 1000, account(900.0, balance=1000.0))
    verdict = engine.evaluate()
    states = {i.interpretation_id: i.state for i in verdict.interpretations}
    assert states["balance_static"] is ChallengeState.RUNNING
    assert states["equity_trailing"] is ChallengeState.FAILED
    assert verdict.state is ChallengeState.FAILED
    assert verdict.indicative_state is ChallengeState.FAILED


def test_an_unverified_profile_never_concludes():
    profile = make_profile(profile_status="DRAFT")
    engine = ChallengeEngine(profile)
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1000, account(1100.0))
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.INVALID
    assert verdict.is_conclusive is False
    # L'etat indicatif reste disponible pour la recherche.
    assert verdict.indicative_state is not None
    assert any("no conformance verdict" in reason for reason in verdict.reasons)


def test_assumptions_are_explicitly_reported():
    payload = _profile_payload()
    payload["limits"] = {
        **payload["limits"],
        "daily_reset_time": "UNRESOLVED",
        "daily_reset_timezone": "UNRESOLVED",
        "drawdown_basis": "UNRESOLVED",
    }
    payload["trading_days"] = {
        "min_profitable_days_per_step": 1,
        "profitable_day_definition": "UNRESOLVED",
    }
    profile = ChallengeProfile.from_dict(payload)
    engine = ChallengeEngine(profile)
    engine.observe(BASE_NS, account(1000.0))
    verdict = engine.evaluate()
    assert len(verdict.assumptions) == 3
    assert any("V2" in a for a in verdict.assumptions)
    assert any("V1" in a for a in verdict.assumptions)
    assert any("V3" in a for a in verdict.assumptions)


def test_finalize_counts_the_last_day():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1000, account(1050.0))
    engine.finalize()
    verdict = engine.evaluate()
    assert verdict.trading_days == 1


# --- garde-fou pour le RiskGovernor ---------------------------------------
def test_a_failed_challenge_blocks_new_risk():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1000, account(899.0))
    blocked, reason = engine.blocks_new_risk()
    assert blocked is True
    assert "FAILED" in reason


def test_an_invalid_profile_does_not_block_research():
    engine = ChallengeEngine(make_profile(profile_status="DRAFT"))
    engine.observe(BASE_NS, account(1000.0))
    blocked, _ = engine.blocks_new_risk()
    assert blocked is False


def test_a_running_challenge_does_not_block_new_risk():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    blocked, _ = engine.blocks_new_risk()
    assert blocked is False
