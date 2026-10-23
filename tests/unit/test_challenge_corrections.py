"""Tests des corrections de la phase C (C1, C2, C6).

Ces tests ciblent des defauts precis : progression non idempotente, echec non
terminal, pertes maximales jamais mises a jour, observations dupliquees ou
desordonnees, et coherence documentaire du profil The5ers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.challenge.profile import ChallengeProfile
from etatmajor.core.errors import ConfigurationError
from etatmajor.core.models import AccountState, ChallengeState

DAY_NS = 86_400_000_000_000
BASE_NS = 1_767_571_200_000_000_000

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = (
    REPO_ROOT / "configs" / "prop_firms" / "the5ers_high_stakes_new_2500.draft.toml"
)
REFERENCE_DOC = REPO_ROOT / "docs" / "propfirm" / "THE5ERS_REFERENCE.md"


def profile_payload(
    steps: list[dict] | None = None,
    *,
    reference_capital: float = 1000.0,
    daily_percent: float = 5.0,
    total_percent: float = 10.0,
    extra_rules: list[dict] | None = None,
) -> dict:
    return {
        "profile_status": "VERIFIED",
        "profile_id": "test-profile",
        "profile_version": "1.0.0",
        "verified_on": "2026-10-22",
        "verified_by": "tests",
        "sources": ["https://example.invalid/rules"],
        "program": {"name": "Test", "variant": "New", "platform": "MT5"},
        "account": {
            "initial_capital": reference_capital,
            "reference_capital": reference_capital,
        },
        "steps": steps
        or [
            {
                "index": 1,
                "profit_target_percent": 10.0,
                "profit_target_amount": reference_capital * 0.10,
                "min_profitable_days": 0,
            }
        ],
        "limits": {
            "max_daily_loss_percent": daily_percent,
            "max_daily_loss_amount": reference_capital * daily_percent / 100.0,
            "max_total_loss_percent": total_percent,
            "max_total_loss_amount": reference_capital * total_percent / 100.0,
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
        "ambiguous_rules": extra_rules or [],
    }


def make_profile(**kwargs) -> ChallengeProfile:
    return ChallengeProfile.from_dict(profile_payload(**kwargs))


def two_step_profile() -> ChallengeProfile:
    return make_profile(
        steps=[
            {
                "index": 1,
                "profit_target_percent": 10.0,
                "profit_target_amount": 100.0,
                "min_profitable_days": 0,
                "reference_capital": 1000.0,
            },
            {
                "index": 2,
                "profit_target_percent": 5.0,
                "profit_target_amount": 50.0,
                "min_profitable_days": 0,
                "reference_capital": 1000.0,
            },
        ]
    )


def account(equity: float, ts_ns: int = BASE_NS, balance: float | None = None):
    return AccountState(
        account_id="ACC",
        currency="USD",
        balance=equity if balance is None else balance,
        equity=equity,
        ts_ns=ts_ns,
    )


# --- C1 : determinisme et idempotence ------------------------------------
def test_evaluate_does_not_mutate_the_challenge_state():
    engine = ChallengeEngine(two_step_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(1200.0))

    first = engine.evaluate()
    step_after_first = engine.step_index
    second = engine.evaluate()
    third = engine.evaluate()

    assert step_after_first == 1
    assert engine.step_index == 1
    assert first.state is ChallengeState.RUNNING
    assert first.step_index == 2
    assert second.to_dict() == first.to_dict()
    assert third.to_dict() == first.to_dict()


def test_two_targets_crossed_in_one_observation_validate_only_one_step():
    engine = ChallengeEngine(two_step_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(1200.0))  # cible 1 et cible 2 franchies

    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.RUNNING
    assert verdict.step_index == 2
    assert verdict.steps_completed == 1

    # Une nouvelle observation est necessaire pour valider la deuxieme etape.
    engine.observe(BASE_NS + 2, account(1200.0))
    assert engine.evaluate().state is ChallengeState.PASSED


def test_a_duplicate_observation_does_not_advance_another_step():
    engine = ChallengeEngine(two_step_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(1200.0))
    engine.observe(BASE_NS + 1, account(1200.0))  # doublon exact

    assert engine.step_index == 1
    assert engine.evaluate().step_index == 2


def test_stale_and_conflicting_observations_are_ignored():
    engine = ChallengeEngine(two_step_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 10, account(1010.0))

    engine.observe(BASE_NS + 5, account(1200.0))  # en retard
    engine.observe(BASE_NS + 10, account(900.0))  # contradiction au meme instant

    verdict = engine.evaluate()
    assert engine.ignored_observations == 2
    assert verdict.total_pnl == pytest.approx(10.0)
    assert verdict.state is ChallengeState.RUNNING


def test_step_days_are_required_per_step():
    profile = make_profile(
        steps=[
            {
                "index": 1,
                "profit_target_percent": 10.0,
                "profit_target_amount": 100.0,
                "min_profitable_days": 0,
                "reference_capital": 1000.0,
            },
            {
                "index": 2,
                "profit_target_percent": 5.0,
                "profit_target_amount": 50.0,
                "min_profitable_days": 2,
                "reference_capital": 1000.0,
            },
        ]
    )
    engine = ChallengeEngine(profile)
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(1200.0))
    engine.observe(BASE_NS + 2, account(1200.0))
    # L'etape 2 exige 2 jours profitables : aucune observation ne les fournit.
    assert engine.evaluate().state is ChallengeState.RUNNING
    assert engine.evaluate().step_index == 2


# --- C2 : pertes maximales et echec terminal ------------------------------
def test_a_daily_loss_breach_is_terminal_even_after_recovery():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(940.0))  # 60 > limite 50
    assert engine.evaluate().state is ChallengeState.FAILED

    engine.observe(BASE_NS + 2, account(1000.0))  # recuperation totale
    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.FAILED
    assert verdict.indicative_state is ChallengeState.FAILED
    assert len(verdict.failures) >= 1
    assert verdict.max_daily_loss >= 60.0
    assert any("cannot be cleared" in reason for reason in verdict.reasons)


def test_a_daily_reset_does_not_clear_a_terminal_failure():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(940.0))
    engine.observe(BASE_NS + DAY_NS, account(1000.0))  # lendemain, compte intact

    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.FAILED
    assert verdict.trading_days == 1
    assert verdict.max_daily_loss >= 60.0


def test_a_total_loss_breach_is_terminal():
    profile = make_profile(daily_percent=20.0, total_percent=10.0)
    engine = ChallengeEngine(profile)
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(899.0))  # 101 > limite totale 100

    verdict = engine.evaluate()
    assert verdict.state is ChallengeState.FAILED
    assert any(failure.kind == "total_loss" for failure in verdict.failures)
    assert verdict.max_total_loss >= 101.0

    engine.observe(BASE_NS + 2, account(1000.0))
    assert engine.evaluate().state is ChallengeState.FAILED


def test_balance_equity_and_floating_losses_are_distinguished():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(940.0, balance=1000.0))

    verdict = engine.evaluate()
    states = {i.interpretation_id: i.state for i in verdict.interpretations}
    assert states["balance_static"] is ChallengeState.RUNNING
    assert states["equity_trailing"] is ChallengeState.FAILED
    assert verdict.state is ChallengeState.FAILED
    # La perte flottante est visible dans la lecture equity, pas dans le solde.
    assert verdict.max_daily_loss >= 60.0
    assert verdict.interpretations[0].daily_loss == 0.0
    assert verdict.interpretations[1].daily_loss == pytest.approx(60.0)


def test_max_losses_are_updated_at_every_observation():
    engine = ChallengeEngine(make_profile(daily_percent=20.0, total_percent=50.0))
    engine.observe(BASE_NS, account(1000.0))
    engine.observe(BASE_NS + 1, account(970.0))
    engine.observe(BASE_NS + 2, account(950.0))
    engine.observe(BASE_NS + 3, account(980.0))

    verdict = engine.evaluate()
    assert verdict.max_daily_loss == pytest.approx(50.0)
    assert verdict.max_total_loss == pytest.approx(50.0)
    assert verdict.state is ChallengeState.RUNNING


def test_the_model_limits_are_explicit_in_the_verdict():
    engine = ChallengeEngine(make_profile())
    engine.observe(BASE_NS, account(1000.0))
    verdict = engine.evaluate()
    assert verdict.model_limits
    assert "intrabar" in verdict.model_limits[0]


# --- C6 : profil The5ers coherent et generique ----------------------------
def test_the_reference_document_points_to_the_existing_toml_profile():
    assert PROFILE_PATH.exists()
    text = REFERENCE_DOC.read_text(encoding="utf-8")
    assert PROFILE_PATH.name in text
    assert ".draft.yaml" not in text


def test_the_shipped_profile_is_internally_consistent():
    profile = ChallengeProfile.from_toml(PROFILE_PATH)
    assert profile.reference_capital == 2500.0
    assert profile.limits.max_daily_loss_amount == 125.0
    assert profile.limits.max_total_loss_amount == 250.0
    assert [step.profit_target_amount for step in profile.steps] == [250.0, 125.0]
    # Les frais ne sont pas supposes deduits : V4 reste non resolu.
    v4 = next(rule for rule in profile.ambiguous_rules if rule.id == "V4")
    assert not v4.is_resolved


def test_an_inconsistent_loss_percentage_is_refused():
    payload = profile_payload()
    payload["limits"]["max_daily_loss_amount"] = 10.0  # 1 % au lieu de 5 %
    with pytest.raises(ConfigurationError) as excinfo:
        ChallengeProfile.from_dict(payload)
    assert "inconsistent" in str(excinfo.value)


def test_a_second_prop_firm_profile_is_supported_without_code_change():
    other = profile_payload()
    other["profile_id"] = "other-firm"
    other["program"]["name"] = "Other Firm"
    profile = ChallengeProfile.from_dict(other)
    engine = ChallengeEngine(profile)
    engine.observe(BASE_NS, account(1000.0))
    assert engine.evaluate().state is ChallengeState.RUNNING
