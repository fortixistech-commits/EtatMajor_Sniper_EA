"""Tests d'integration du Challenge Engine dans le rejeu (Mission 7).

La question centrale du produit est verifiee ici : le rejeu produit-il un
verdict de challenge, ce verdict est-il explicite, et le risque est-il
refuse quand le challenge l'interdit ?
"""

from __future__ import annotations

import pytest

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.challenge.profile import ChallengeProfile
from etatmajor.core.models import ChallengeState
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset

PROFILE_PATH = (
    "configs/prop_firms/the5ers_high_stakes_new_2500.draft.toml"
)

PRICES = [1.10000 + 0.00020 * i for i in range(20)]


def build(profile_path: str | None = None, capital: float = 2_500.0):
    dataset = make_dataset(PRICES)
    config = make_config(initial_capital=capital)
    config = type(config)(
        simulation=type(config.simulation)(
            symbol=config.simulation.symbol,
            timeframe=config.simulation.timeframe,
            initial_capital=capital,
            currency=config.simulation.currency,
            end_of_replay_policy=config.simulation.end_of_replay_policy,
            mode=config.simulation.mode,
            seed=config.simulation.seed,
        ),
        execution=config.execution,
        risk=config.risk,
    )
    challenge = None
    if profile_path:
        profile = ChallengeProfile.from_toml(profile_path)
        challenge = ChallengeEngine(profile, initial_capital=capital)
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=2_000.0, entry_index=2, exit_index=6
    )
    engine = ReplayEngine(
        dataset=dataset, config=config, strategy=strategy, challenge=challenge
    )
    return engine.run()


def test_the_report_contains_no_challenge_section_without_a_profile():
    result = build()
    assert result.report["challenge"] == {"enabled": False}


def test_the_report_contains_the_profile_and_the_verdict():
    result = build(PROFILE_PATH)
    section = result.report["challenge"]
    assert section["enabled"] is True
    assert section["profile"]["profile_id"] == "the5ers-high-stakes-new-2500"
    assert section["profile"]["profile_status"] == "DRAFT"
    assert section["verdict"]["state"] == ChallengeState.INVALID.value
    assert section["verdict"]["is_conclusive"] is False


def test_a_draft_profile_never_declares_a_conformance():
    result = build(PROFILE_PATH)
    verdict = result.report["challenge"]["verdict"]
    assert verdict["state"] == "INVALID"
    assert any("no conformance verdict" in r for r in verdict["reasons"])
    # L'etat indicatif reste disponible : la simulation reste exploitable.
    assert verdict["indicative_state"] in {"RUNNING", "PASSED", "FAILED"}


def test_the_challenge_tracks_the_pnl_of_the_campaign():
    result = build(PROFILE_PATH)
    verdict = result.report["challenge"]["verdict"]
    account = result.report["account"]
    assert verdict["total_pnl"] == pytest.approx(account["net_pnl"])
    assert verdict["distance_to_daily_limit"] == pytest.approx(
        125.0 - verdict["max_daily_loss"]
    ) or verdict["distance_to_daily_limit"] >= 0


def test_the_simulation_runs_on_the_challenge_account():
    result = build(PROFILE_PATH, capital=2_500.0)
    assert result.report["account"]["initial_capital"] == 2_500.0


def test_the_risk_governor_refuses_new_risk_when_the_challenge_failed():
    """Un challenge en echec ferme la porte a toute nouvelle exposition."""
    dataset = make_dataset(PRICES)
    config = make_config(initial_capital=1_000.0)
    profile = ChallengeProfile.from_toml(PROFILE_PATH)
    challenge = ChallengeEngine(profile, initial_capital=1_000.0)

    from etatmajor.core.models import AccountState

    challenge.observe(1, AccountState("ACC", "USD", 1_000.0, 1_000.0, 1))
    # Equity effondree : la limite de perte totale (250) est franchie.
    challenge.observe(2, AccountState("ACC", "USD", 700.0, 700.0, 2))
    verdict = challenge.evaluate()
    # Le profil etant DRAFT, l'etat officiel est INVALID, mais l'etat
    # indicatif est FAILED : le risque doit etre bloque dans les deux cas.
    assert verdict.state is ChallengeState.INVALID
    assert verdict.indicative_state is ChallengeState.FAILED
    assert challenge.blocks_new_risk()[0] is True

    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=6
    )
    engine = ReplayEngine(
        dataset=dataset, config=config, strategy=strategy, challenge=challenge
    )
    result = engine.run()

    assert result.report["rejections"]["risk_count"] >= 1
    assert "FAILED" in str(result.report["rejections"]["risk"])
    assert result.report["executions"]["total"] == 0
