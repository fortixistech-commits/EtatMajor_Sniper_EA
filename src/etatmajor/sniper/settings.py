"""Build Sniper runtime objects from the validated ``[sniper]`` config."""

from __future__ import annotations

from ..core.config import SniperConfig
from ..data.instruments import BrokerSymbolSpec, InstrumentSpec
from .engine import DoctrinePolicy, SniperEngine
from .planner import MissionPlanner


def build_policy(settings: SniperConfig) -> DoctrinePolicy:
    settings.validate()
    return DoctrinePolicy(
        min_confidence=settings.min_confidence,
        min_setup_quality=settings.min_setup_quality,
        require_structure_alignment=settings.require_structure_alignment,
        require_htf_alignment=settings.require_htf_alignment,
        block_extreme_volatility=settings.block_extreme_volatility,
        max_open_positions=settings.max_open_positions,
    )


def build_planner(settings: SniperConfig) -> MissionPlanner:
    settings.validate()
    return MissionPlanner(
        risk_amount=settings.risk_amount,
        reward_risk_multiple=settings.reward_risk_multiple,
        volume_step=settings.volume_step,
        min_quantity=settings.min_quantity,
        estimated_cost_per_unit=settings.estimated_cost_per_unit,
        validity_ns=settings.validity_ns,
        max_duration_ns=settings.max_duration_ns,
    )


def build_engine(
    symbol: str,
    timeframe: str,
    settings: SniperConfig,
    *,
    instrument: InstrumentSpec | None = None,
    broker_spec: BrokerSymbolSpec | None = None,
    account_currency: str | None = None,
    data_quality: object | None = None,
) -> SniperEngine:
    return SniperEngine(
        symbol=symbol,
        timeframe=timeframe,
        planner=build_planner(settings),
        policy=build_policy(settings),
        higher_timeframe_factor=settings.higher_timeframe_factor,
        max_missing_ratio=settings.max_missing_ratio,
        instrument=instrument,
        broker_spec=broker_spec,
        account_currency=account_currency,
        data_quality=data_quality,
    )
