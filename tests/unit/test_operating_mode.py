"""Tests du mode de fonctionnement (correction C3).

Le mode n'est plus une constante codee en dur dans le rapport : il est
parametre, valide au demarrage, et les modes dont les capacites n'existent
pas encore sont refuses avec un message explicite.
"""

from __future__ import annotations

import pytest

from etatmajor.core.config import AppConfig, ExecutionConfig, RiskConfig, SimulationConfig
from etatmajor.core.errors import ConfigurationError
from etatmajor.core.types import OperatingMode
from tests.conftest import make_config, make_dataset


def test_lab_is_the_default_mode():
    config = make_config()
    assert config.simulation.mode is OperatingMode.LAB


def test_lab_and_challenge_sim_are_accepted():
    for mode in (OperatingMode.LAB, OperatingMode.CHALLENGE_SIM):
        config = SimulationConfig(symbol="EURUSD", mode=mode)
        config.validate()


def test_paper_is_refused_without_a_live_data_adapter():
    config = SimulationConfig(symbol="EURUSD", mode=OperatingMode.PAPER)
    with pytest.raises(ConfigurationError) as excinfo:
        config.validate()
    assert "PAPER" in str(excinfo.value)
    assert "live market data adapter" in str(excinfo.value)


def test_production_is_refused_and_never_implicit():
    config = SimulationConfig(symbol="EURUSD", mode=OperatingMode.PRODUCTION)
    with pytest.raises(ConfigurationError) as excinfo:
        config.validate()
    assert "PRODUCTION" in str(excinfo.value)
    assert "human authorisation" in str(excinfo.value)


def test_the_report_label_keeps_the_laboratory_vocabulary():
    assert OperatingMode.LAB.report_label == "LABORATORY"
    assert OperatingMode.CHALLENGE_SIM.report_label == "CHALLENGE_SIM"


def test_the_mode_appears_in_the_report():
    from etatmajor.replay.engine import ReplayEngine
    from etatmajor.strategies.demo import DemoLifecycleStrategy

    config = make_config()
    dataset = make_dataset([1.1, 1.1002, 1.1004, 1.1006, 1.1008])
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=1, exit_index=3
    )
    result = ReplayEngine(dataset=dataset, config=config, strategy=strategy).run()
    assert result.report["mode"] == "LABORATORY"
    assert result.report["config"]["simulation"]["mode"] == "LAB"


def test_the_mode_is_part_of_the_configuration_fingerprint():
    lab = make_config()
    challenge = AppConfig(
        simulation=SimulationConfig(
            symbol="EURUSD",
            timeframe="1m",
            initial_capital=100_000.0,
            mode=OperatingMode.CHALLENGE_SIM,
        ),
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    assert lab.fingerprint() != challenge.fingerprint()


def test_an_invalid_mode_value_is_refused(tmp_path):
    from etatmajor.core.config import load_config

    path = tmp_path / "bad.toml"
    path.write_text('[simulation]\nmode = "LIVE_TRADING"\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(path)
    assert "simulation.mode" in str(excinfo.value)
