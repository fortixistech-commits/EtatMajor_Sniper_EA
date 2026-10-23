"""Phase 5 / G5 : contraintes instrument et broker dans le planificateur."""

from __future__ import annotations

import pytest

from etatmajor.core.types import OrderSide
from etatmajor.data.instruments import BrokerSymbolSpec, InstrumentSpec
from etatmajor.sniper.planner import MissionPlanner, PlanningError
from etatmajor.sniper.setup import SetupDetection


def _setup(entry: float = 1.10000, stop: float = 1.09800) -> SetupDetection:
    return SetupDetection(
        direction=OrderSide.BUY,
        reference_price=entry,
        invalidation_price=stop,
        target_price=None,
        pullback_low=stop,
        pullback_high=entry,
        distance_to_ema=0.0001,
        bars_in_pullback=5,
        quality=1.0,
    )


def _instrument(**overrides) -> InstrumentSpec:
    payload = {
        "instrument_id": "TEST",
        "symbol": "TEST",
        "asset_class": "forex",
        "quote_currency": "USD",
        "base_currency": None,
        "price_precision": 5,
        "tick_size": 0.00001,
        "min_quantity": 0.01,
        "quantity_step": 0.01,
        "source": "test",
        "version": "1",
    }
    payload.update(overrides)
    spec = InstrumentSpec(**payload)
    spec.validate()
    return spec


def test_broker_constraints_override_planner_defaults():
    planner = MissionPlanner(
        risk_amount=100.0, volume_step=0.01, min_quantity=0.01
    )
    instrument = _instrument(quantity_step=1.0, min_quantity=100.0)
    broker = BrokerSymbolSpec(
        broker_id="b",
        symbol="TEST",
        instrument_id="TEST",
        min_quantity=10.0,
        quantity_step=0.5,
    )
    plan = planner.plan(
        _setup(entry=1.10300, stop=1.10000),
        symbol="TEST",
        timeframe="M5",
        strategy_id="s",
        strategy_version="1",
        created_ts_ns=0,
        plan_id="p",
        instrument=instrument,
        broker_spec=broker,
    )
    assert plan.quantity == pytest.approx(33333.0)
    assert instrument.is_quantity_aligned(plan.quantity)
    assert plan.risk_amount <= 100.0 + 1e-6


def test_max_quantity_is_clamped_and_aligned():
    planner = MissionPlanner(risk_amount=1000.0)
    instrument = _instrument(
        quantity_step=0.5, min_quantity=1.0, max_quantity=100.0
    )
    plan = planner.plan(
        _setup(entry=1.11000, stop=1.10000),
        symbol="TEST",
        timeframe="M5",
        strategy_id="s",
        strategy_version="1",
        created_ts_ns=0,
        plan_id="p",
        instrument=instrument,
    )
    assert plan.quantity == pytest.approx(100.0)
    assert plan.risk_amount == pytest.approx(1.0)


def test_tick_value_and_contract_size_value_the_risk():
    instrument = _instrument(
        tick_size=0.01,
        tick_value=1.0,
        tick_value_currency="USD",
        contract_size=10.0,
        price_precision=2,
        min_quantity=0.01,
        quantity_step=0.01,
    )
    planner = MissionPlanner(risk_amount=100.0)
    plan = planner.plan(
        _setup(entry=1.50, stop=1.00),
        symbol="TEST",
        timeframe="M5",
        strategy_id="s",
        strategy_version="1",
        created_ts_ns=0,
        plan_id="p",
        instrument=instrument,
        account_currency="USD",
    )
    assert plan.quantity == pytest.approx(20.0)
    assert plan.risk_amount == pytest.approx(100.0)
    assert plan.entry_price == pytest.approx(1.50)
    assert plan.target_price == pytest.approx(2.50)


def test_currency_mismatch_is_refused_without_conversion():
    instrument = _instrument(
        tick_size=0.01,
        tick_value=1.0,
        tick_value_currency="EUR",
        contract_size=10.0,
        price_precision=2,
    )
    planner = MissionPlanner(risk_amount=100.0)
    with pytest.raises(PlanningError, match="no conversion"):
        planner.plan(
            _setup(entry=1.50, stop=1.00),
            symbol="TEST",
            timeframe="M5",
            strategy_id="s",
            strategy_version="1",
            created_ts_ns=0,
            plan_id="p",
            instrument=instrument,
            account_currency="USD",
        )


def test_quote_currency_mismatch_without_tick_value_is_refused():
    instrument = _instrument(price_precision=2, quote_currency="EUR")
    planner = MissionPlanner(risk_amount=100.0)
    with pytest.raises(PlanningError, match="no conversion"):
        planner.plan(
            _setup(entry=1.50, stop=1.00),
            symbol="TEST",
            timeframe="M5",
            strategy_id="s",
            strategy_version="1",
            created_ts_ns=0,
            plan_id="p",
            instrument=instrument,
            account_currency="USD",
        )


def test_same_quote_currency_uses_raw_price_risk():
    instrument = _instrument(price_precision=2)
    planner = MissionPlanner(risk_amount=100.0)
    plan = planner.plan(
        _setup(entry=1.50, stop=1.00),
        symbol="TEST",
        timeframe="M5",
        strategy_id="s",
        strategy_version="1",
        created_ts_ns=0,
        plan_id="p",
        instrument=instrument,
        account_currency="USD",
    )
    assert plan.quantity == pytest.approx(200.0)


def test_broker_mapping_must_match_instrument():
    planner = MissionPlanner(risk_amount=100.0)
    broker = BrokerSymbolSpec(
        broker_id="b",
        symbol="TEST",
        instrument_id="OTHER",
        min_quantity=0.01,
        quantity_step=0.01,
    )
    with pytest.raises(PlanningError, match="maps to"):
        planner.plan(
            _setup(),
            symbol="TEST",
            timeframe="M5",
            strategy_id="s",
            strategy_version="1",
            created_ts_ns=0,
            plan_id="p",
            instrument=_instrument(),
            broker_spec=broker,
        )


def test_prices_are_rounded_to_instrument_precision():
    instrument = _instrument(price_precision=2, tick_size=0.01)
    planner = MissionPlanner(risk_amount=100.0, volume_step=0.01)
    plan = planner.plan(
        _setup(entry=1.106, stop=1.096),
        symbol="TEST",
        timeframe="M5",
        strategy_id="s",
        strategy_version="1",
        created_ts_ns=0,
        plan_id="p",
        instrument=instrument,
    )
    assert plan.entry_price == pytest.approx(1.11)
    assert plan.stop_price == pytest.approx(1.10)
    assert plan.target_price == pytest.approx(1.13)


def test_quantity_below_broker_minimum_is_refused():
    broker = BrokerSymbolSpec(
        broker_id="b",
        symbol="TEST",
        instrument_id="TEST",
        min_quantity=10.0,
        quantity_step=0.01,
    )
    planner = MissionPlanner(risk_amount=1.0)
    with pytest.raises(PlanningError, match="minimum"):
        planner.plan(
            _setup(entry=2.00000, stop=1.00000),
            symbol="TEST",
            timeframe="M5",
            strategy_id="s",
            strategy_version="1",
            created_ts_ns=0,
            plan_id="p",
            instrument=_instrument(),
            broker_spec=broker,
        )


def test_without_instrument_behaviour_is_unchanged():
    planner = MissionPlanner(
        risk_amount=100.0, volume_step=0.01, min_quantity=0.01
    )
    plan = planner.plan(
        _setup(entry=1.10200, stop=1.10000),
        symbol="TEST",
        timeframe="M5",
        strategy_id="s",
        strategy_version="1",
        created_ts_ns=0,
        plan_id="p",
    )
    assert plan.quantity == pytest.approx(50000.0)
    assert plan.risk_amount == pytest.approx(100.0)


def test_sniper_config_validates_and_builds_runtime_objects():
    from etatmajor.core.config import SniperConfig
    from etatmajor.sniper.engine import DoctrinePolicy
    from etatmajor.sniper.settings import build_planner, build_policy

    settings = SniperConfig(
        risk_amount=25.0,
        reward_risk_multiple=3.0,
        volume_step=0.1,
        min_quantity=1.0,
        validity_ns=60_000_000_000,
        max_open_positions=2,
        min_confidence=0.4,
        require_htf_alignment=True,
    )
    settings.validate()
    planner = build_planner(settings)
    policy = build_policy(settings)
    assert isinstance(policy, DoctrinePolicy)
    assert planner.risk_amount == 25.0
    assert planner.reward_risk_multiple == 3.0
    assert planner.volume_step == 0.1
    assert planner.min_quantity == 1.0
    assert policy.max_open_positions == 2
    assert policy.min_confidence == 0.4
    assert policy.require_htf_alignment is True


def test_sniper_config_refuses_invalid_values():
    from etatmajor.core.config import SniperConfig

    for kwargs in (
        {"risk_amount": 0.0},
        {"reward_risk_multiple": -1.0},
        {"volume_step": 0.0},
        {"max_open_positions": 0},
        {"min_confidence": 1.5},
        {"max_missing_ratio": -0.1},
        {"higher_timeframe_factor": 0},
        {"validity_ns": 0},
    ):
        with pytest.raises(Exception):
            SniperConfig(**kwargs).validate()


def test_sniper_section_is_loaded_from_toml(tmp_path):
    from etatmajor.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        "[sniper]\nrisk_amount = 42.0\nmin_setup_quality = 0.25\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.sniper.risk_amount == 42.0
    assert config.sniper.min_setup_quality == 0.25
    assert config.to_dict()["sniper"]["risk_amount"] == 42.0


def test_settings_build_an_engine_with_the_configured_limits():
    from etatmajor.core.config import SniperConfig
    from etatmajor.sniper.settings import build_engine

    settings = SniperConfig(
        max_open_positions=3,
        higher_timeframe_factor=6,
        max_missing_ratio=0.2,
        min_confidence=0.5,
    )
    engine = build_engine(
        "EURUSD",
        "5m",
        settings,
        instrument=_instrument(),
        account_currency="USD",
    )
    assert engine.policy.max_open_positions == 3
    assert engine.policy.min_confidence == 0.5
    assert engine.higher_timeframe_factor == 6
    assert engine.max_missing_ratio == 0.2
    assert engine.planner.risk_amount == settings.risk_amount
    assert engine.instrument is not None
    assert engine.account_currency == "USD"
