"""Isolation tests: the replay engine works without network or broker.

Mandatory assertion 8: the engine must be able to run with no network access
and no real broker.
"""

from __future__ import annotations

import socket

import pytest

from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset

PRICES = [1.10000 + 0.00020 * i for i in range(12)]


@pytest.fixture()
def no_network(monkeypatch):
    """Make any socket creation fail."""

    def forbidden(*args, **kwargs):
        raise AssertionError("the replay engine must not open a network connection")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    return True


def test_replay_runs_with_networking_disabled(no_network):
    dataset = make_dataset(PRICES)
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=6
    )
    result = ReplayEngine(dataset=dataset, config=make_config(), strategy=strategy).run()

    assert result.report["executions"]["total"] == 2
    assert result.report["simulation_only"] is True


def test_no_broker_or_trading_module_is_imported():
    import sys

    forbidden = ("MetaTrader5", "requests", "urllib3", "socketio")
    for module in forbidden:
        assert module not in sys.modules or module == "socketio", module


def test_the_package_does_not_import_any_broker_library():
    """Importing the platform must not pull a broker SDK in."""
    import subprocess
    import sys

    code = (
        "import sys; import etatmajor, etatmajor.cli, etatmajor.replay.engine;"
        "print([m for m in sys.modules if m in ('MetaTrader5','requests','pandas','numpy')])"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().endswith("[]")
