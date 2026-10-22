"""Tests d'integration de la phase A (corrections C1, C2, C3).

Couvrent :
- le cycle de vie complet de la strategie (on_start, on_bar, on_stop) ;
- l'expiration des signaux (abstention, jamais une execution) ;
- les erreurs typees (contrat de strategie viole) ;
- l'application du pas de volume par le broker ;
- le mode de fonctionnement remonte dans le rapport.
"""

from __future__ import annotations

import pytest

from etatmajor.core.config import SimulationConfig
from etatmajor.core.errors import StrategyError
from etatmajor.core.events import Signal
from etatmajor.core.types import OrderStatus, SignalAction
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy
from tests.conftest import make_config, make_dataset

PRICES = [1.10000 + 0.00020 * i for i in range(10)]


class RecordingStrategy(DemoLifecycleStrategy):
    """Demo Lifecycle qui enregistre les appels du cycle de vie."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = 0
        self.stopped = 0
        self.stop_contexts = []

    def on_start(self, context):
        self.started += 1
        super().on_start(context)

    def on_stop(self, context):
        self.stopped += 1
        self.stop_contexts.append(context)


def run(dataset, config, strategy):
    return ReplayEngine(dataset=dataset, config=config, strategy=strategy).run()


# --- C2 : cycle de vie ----------------------------------------------------
def test_on_stop_is_called_exactly_once_with_a_final_context():
    dataset = make_dataset(PRICES)
    strategy = RecordingStrategy(symbol="EURUSD", timeframe="1m", quantity=1_000.0)
    result = run(dataset, make_config(), strategy)

    assert strategy.started == 1
    assert strategy.stopped == 1
    assert len(strategy.stop_contexts) == 1
    final_context = strategy.stop_contexts[0]
    assert final_context.final is True
    assert final_context.index == len(dataset) - 1
    # Le contexte final expose tout l'historique visible.
    assert len(final_context.visible_bars) == len(dataset)


def test_on_stop_sees_the_final_portfolio_state():
    dataset = make_dataset(PRICES)
    strategy = RecordingStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=6
    )
    result = run(dataset, make_config(), strategy)
    final_context = strategy.stop_contexts[0]
    assert final_context.portfolio.equity == pytest.approx(
        result.report["account"]["final_equity"]
    )


def test_a_strategy_violating_its_contract_raises_a_typed_error():
    dataset = make_dataset(PRICES)

    class BrokenStrategy(DemoLifecycleStrategy):
        def on_bar(self, context):
            raise ValueError("boom")

    strategy = BrokenStrategy(symbol="EURUSD", timeframe="1m")
    with pytest.raises(StrategyError) as excinfo:
        run(dataset, make_config(), strategy)
    assert "on_bar" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_a_strategy_error_in_on_stop_is_typed():
    dataset = make_dataset(PRICES)

    class BrokenStrategy(DemoLifecycleStrategy):
        def on_stop(self, context):
            raise ValueError("boom at the end")

    strategy = BrokenStrategy(symbol="EURUSD", timeframe="1m")
    with pytest.raises(StrategyError) as excinfo:
        run(dataset, make_config(), strategy)
    assert "on_stop" in str(excinfo.value)


# --- C2 : expiration des signaux -----------------------------------------
def test_an_expired_signal_is_not_executed_and_is_journalised_as_an_abstention():
    dataset = make_dataset(PRICES)

    class ExpiringStrategy(DemoLifecycleStrategy):
        def on_bar(self, context):
            if context.index == 1:
                return [
                    Signal(
                        strategy_id="expiring",
                        strategy_version="1.0.0",
                        symbol="EURUSD",
                        timeframe="1m",
                        decision_ts_ns=context.clock.now(),
                        action=SignalAction.BUY,
                        quantity=1_000.0,
                        expires_ts_ns=context.clock.now() - 1,  # deja expire
                        reason="demo: signal perime",
                    )
                ]
            return []

    strategy = ExpiringStrategy(symbol="EURUSD", timeframe="1m")
    result = run(dataset, make_config(), strategy)

    assert result.report["executions"]["total"] == 0
    assert result.report["orders"]["total"] == 0
    expired = result.journal.of_type("SIGNAL_EXPIRED")
    assert len(expired) == 1
    assert expired[0].payload["reason"] == "signal expired before submission"
    # Une expiration est une abstention, pas un refus du risque.
    assert result.report["rejections"]["risk_count"] == 0
    assert result.report["rejections"]["broker_count"] == 0
    assert result.portfolio.net_quantity("EURUSD") == 0.0


def test_a_valid_signal_is_not_expired():
    dataset = make_dataset(PRICES)

    class ValidStrategy(DemoLifecycleStrategy):
        def on_bar(self, context):
            if context.index == 1:
                return [
                    Signal(
                        strategy_id="valid",
                        strategy_version="1.0.0",
                        symbol="EURUSD",
                        timeframe="1m",
                        decision_ts_ns=context.clock.now(),
                        action=SignalAction.BUY,
                        quantity=1_000.0,
                        expires_ts_ns=context.clock.now() + 60_000_000_000,
                        reason="demo: signal valide",
                    )
                ]
            return []

    strategy = ValidStrategy(symbol="EURUSD", timeframe="1m")
    result = run(dataset, make_config(), strategy)
    assert len(result.journal.of_type("SIGNAL_EXPIRED")) == 0
    # Une execution d'entree, puis la fermeture de fin de replay.
    assert result.report["orders"]["total"] == 2
    assert result.report["executions"]["total"] == 2
    assert result.portfolio.net_quantity("EURUSD") == 0.0


# --- C3 : pas de volume ---------------------------------------------------
def test_the_broker_refuses_a_quantity_that_is_not_aligned_with_the_step():
    dataset = make_dataset(PRICES)
    config = make_config()
    config = type(config)(
        simulation=config.simulation,
        execution=type(config.execution)(quantity_step=0.01),
        risk=config.risk,
    )
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=0.015, entry_index=1, exit_index=99
    )
    result = run(dataset, config, strategy)

    assert result.report["executions"]["total"] == 0
    assert result.report["rejections"]["broker_count"] == 1
    assert "not aligned with the volume step" in str(
        result.report["rejections"]["broker"]
    )
    assert result.portfolio.net_quantity("EURUSD") == 0.0


def test_an_aligned_quantity_is_accepted():
    dataset = make_dataset(PRICES)
    config = make_config()
    config = type(config)(
        simulation=config.simulation,
        execution=type(config.execution)(quantity_step=0.01),
        risk=config.risk,
    )
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=0.02, entry_index=1, exit_index=3
    )
    result = run(dataset, config, strategy)
    assert result.report["executions"]["total"] == 2
    assert result.report["rejections"]["broker_count"] == 0
    assert result.portfolio.net_quantity("EURUSD") == 0.0


# --- C3 : mode ------------------------------------------------------------
def test_the_report_mode_follows_the_configuration():
    dataset = make_dataset(PRICES)
    config = make_config()
    config = type(config)(
        simulation=SimulationConfig(
            symbol="EURUSD",
            timeframe="1m",
            initial_capital=100_000.0,
            mode=config.simulation.mode.__class__("CHALLENGE_SIM"),
        ),
        execution=config.execution,
        risk=config.risk,
    )
    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=1, exit_index=3
    )
    result = run(dataset, config, strategy)
    assert result.report["mode"] == "CHALLENGE_SIM"


# --- C1 : le rejeu reste conforme -----------------------------------------
def test_the_replay_still_forbids_future_data():
    dataset = make_dataset(PRICES)
    seen = []

    class SpyStrategy(DemoLifecycleStrategy):
        def on_bar(self, context):
            seen.append(len(context.visible_bars))
            assert context.visible_bars[-1].ts_close_ns <= context.clock.now()
            return []

    run(dataset, make_config(), SpyStrategy(symbol="EURUSD", timeframe="1m"))
    assert seen == list(range(1, len(PRICES) + 1))


def test_orders_are_still_filled_on_the_next_bar():
    dataset = make_dataset(PRICES)
    result = run(
        dataset,
        make_config(),
        DemoLifecycleStrategy(
            symbol="EURUSD", timeframe="1m", quantity=1_000.0, entry_index=2, exit_index=6
        ),
    )
    signal = result.journal.of_type("SIGNAL")[0].payload
    fill = result.journal.of_type("ORDER_FILLED")[0].payload
    assert fill["execution_bar_index"] == signal["signal_bar_index"] + 1
    assert result.broker.orders[0].status is OrderStatus.FILLED
