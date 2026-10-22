"""Shared fixtures for the ETAT-MAJOR test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from etatmajor.core.config import (
    AppConfig,
    ExecutionConfig,
    RiskConfig,
    SimulationConfig,
)
from etatmajor.core.types import EndOfReplayPolicy
from etatmajor.data.loader import Dataset, load_csv
from etatmajor.data.models import Bar

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = REPO_ROOT / "data" / "sample_eurusd_1m.csv"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_config(
    initial_capital: float = 100_000.0,
    spread_price: float = 0.0,
    slippage_price: float = 0.0,
    slippage_random_max: float = 0.0,
    commission_per_lot_per_side: float = 0.0,
    commission_fixed_per_order: float = 0.0,
    reject_probability: float = 0.0,
    lot_size: float = 1.0,
    end_of_replay_policy: EndOfReplayPolicy = EndOfReplayPolicy.CLOSE_AT_LAST_PRICE,
    max_position_quantity: float = 1_000_000.0,
    max_order_notional: float = 10_000_000.0,
    max_open_positions: int = 1,
    trading_halted: bool = False,
    seed: int = 42,
) -> AppConfig:
    """Build a fully explicit configuration (no file, no hidden default)."""
    config = AppConfig(
        simulation=SimulationConfig(
            symbol="EURUSD",
            timeframe="1m",
            initial_capital=initial_capital,
            currency="USD",
            end_of_replay_policy=end_of_replay_policy,
            seed=seed,
        ),
        execution=ExecutionConfig(
            spread_price=spread_price,
            slippage_price=slippage_price,
            slippage_random_max=slippage_random_max,
            commission_per_lot_per_side=commission_per_lot_per_side,
            commission_fixed_per_order=commission_fixed_per_order,
            reject_probability=reject_probability,
            lot_size=lot_size,
        ),
        risk=RiskConfig(
            max_position_quantity=max_position_quantity,
            max_order_notional=max_order_notional,
            max_open_positions=max_open_positions,
            trading_halted=trading_halted,
        ),
    )
    config.validate()
    return config


def make_dataset(
    closes: list[float],
    timeframe_ns: int = 60_000_000_000,
    opens: list[float] | None = None,
) -> Dataset:
    """Build a dataset from a list of close prices (deterministic OHLC).

    ``opens`` allows building a series with gaps, which is required to prove
    that an execution uses the open of the *next* bar and not the close of the
    signal bar.
    """
    bars = []
    base_ns = 1_767_571_200_000_000_000  # 2026-01-05T00:00:00Z
    for index, close in enumerate(closes):
        if opens is not None:
            open_ = opens[index]
        else:
            open_ = closes[index - 1] if index else close
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        bars.append(
            Bar(
                ts_open_ns=base_ns + index * timeframe_ns,
                ts_close_ns=base_ns + (index + 1) * timeframe_ns,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
            )
        )
    return Dataset(
        symbol="EURUSD",
        timeframe="1m",
        bars=bars,
        source_path="<memory>",
        timeframe_ns=timeframe_ns,
    )


@pytest.fixture()
def sample_csv_path() -> Path:
    assert SAMPLE_CSV.exists(), "sample dataset missing: run scripts/generate_sample_data.py"
    return SAMPLE_CSV


@pytest.fixture()
def sample_dataset(sample_csv_path: Path) -> Dataset:
    return load_csv(
        sample_csv_path,
        symbol="EURUSD",
        timeframe="1m",
        timeframe_ns=60_000_000_000,
    )


@pytest.fixture()
def config() -> AppConfig:
    return make_config()
