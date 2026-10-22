"""Configuration validation tests."""

from __future__ import annotations

import pytest

from etatmajor.core.config import (
    AppConfig,
    ExecutionConfig,
    RiskConfig,
    SimulationConfig,
    load_config,
    timeframe_to_ns,
)
from etatmajor.core.errors import ConfigurationError
from etatmajor.core.types import EndOfReplayPolicy


def test_valid_configuration_is_accepted():
    config = AppConfig(
        simulation=SimulationConfig(symbol="EURUSD", initial_capital=10_000.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    config.validate()


@pytest.mark.parametrize(
    "simulation",
    [
        SimulationConfig(symbol=""),
        SimulationConfig(initial_capital=0.0),
        SimulationConfig(initial_capital=-1.0),
        SimulationConfig(currency=""),
        SimulationConfig(timeframe="1x"),
        SimulationConfig(timeframe="m"),
        SimulationConfig(timeframe="0m"),
    ],
)
def test_invalid_simulation_configuration_is_refused(simulation):
    with pytest.raises(ConfigurationError):
        simulation.validate()


@pytest.mark.parametrize(
    "execution",
    [
        ExecutionConfig(spread_price=-1.0),
        ExecutionConfig(slippage_price=-0.1),
        ExecutionConfig(commission_per_lot_per_side=-1.0),
        ExecutionConfig(reject_probability=1.5),
        ExecutionConfig(reject_probability=-0.1),
        ExecutionConfig(min_quantity=0.0),
        ExecutionConfig(max_quantity=0.0),
        ExecutionConfig(quantity_step=0.0),
        ExecutionConfig(lot_size=0.0),
    ],
)
def test_invalid_execution_configuration_is_refused(execution):
    with pytest.raises(ConfigurationError):
        execution.validate()


@pytest.mark.parametrize(
    "risk",
    [
        RiskConfig(max_position_quantity=0.0),
        RiskConfig(max_order_notional=0.0),
        RiskConfig(max_open_positions=-1),
    ],
)
def test_invalid_risk_configuration_is_refused(risk):
    with pytest.raises(ConfigurationError):
        risk.validate()


def test_timeframe_conversion():
    assert timeframe_to_ns("1m") == 60_000_000_000
    assert timeframe_to_ns("5m") == 300_000_000_000
    assert timeframe_to_ns("1h") == 3_600_000_000_000
    assert timeframe_to_ns("1d") == 86_400_000_000_000


def test_repository_configuration_files_are_valid():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for name in ("simulation.toml", "risk.toml"):
        config = load_config(root / "configs" / name)
        config.validate()
        assert config.fingerprint()


def test_unknown_section_is_refused(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[unknown]\nvalue = 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(path)
    assert "unknown configuration section" in str(excinfo.value)


def test_unknown_key_is_refused(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[simulation]\nnot_a_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(path)
    assert "unknown key" in str(excinfo.value)


def test_invalid_end_of_replay_policy_is_refused(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text(
        '[simulation]\nend_of_replay_policy = "SOMETHING"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(path)
    assert "end_of_replay_policy" in str(excinfo.value)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml_is_refused(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[simulation\nsymbol = ", encoding="utf-8")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(path)
    assert "invalid TOML" in str(excinfo.value)


def test_fingerprint_is_stable_and_sensitive():
    first = AppConfig(
        simulation=SimulationConfig(symbol="EURUSD", initial_capital=10_000.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    second = AppConfig(
        simulation=SimulationConfig(symbol="EURUSD", initial_capital=10_000.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    third = AppConfig(
        simulation=SimulationConfig(symbol="EURUSD", initial_capital=20_000.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != third.fingerprint()


def test_end_of_replay_policy_values():
    assert EndOfReplayPolicy("CLOSE_AT_LAST_PRICE") is EndOfReplayPolicy.CLOSE_AT_LAST_PRICE
    assert EndOfReplayPolicy("MARK_TO_MARKET") is EndOfReplayPolicy.MARK_TO_MARKET
