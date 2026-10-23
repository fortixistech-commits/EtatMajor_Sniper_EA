"""Phase 7 targeted corrections: challenge config, quality mapping, snapshots."""

from __future__ import annotations

import pytest

from etatmajor.challenge.engine import ChallengeEngine
from etatmajor.challenge.profile import ChallengeProfile
from etatmajor.core.errors import ConfigurationError
from etatmajor.core.events import Fill
from etatmajor.core.types import OrderSide
from etatmajor.execution.accounting import Portfolio
from etatmajor.sniper.market_intelligence import DataQualityAssessment
from etatmajor.sniper.settings import build_engine
from tests.conftest import make_config

PROFILE = {
    "profile_status": "VERIFIED",
    "profile_id": "phase7-unit",
    "profile_version": "1.0.0",
    "verified_on": "2026-10-22",
    "verified_by": "tests",
    "sources": ["https://example.invalid/rules"],
    "program": {"name": "Test", "variant": "New", "platform": "MT5"},
    "account": {"initial_capital": 1000.0, "reference_capital": 1000.0},
    "steps": [
        {
            "index": 1,
            "profit_target_percent": 10.0,
            "profit_target_amount": 100.0,
            "min_profitable_days": 0,
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
        "min_profitable_days_per_step": 0,
        "profitable_day_definition": "realised net pnl > 0",
    },
    "evaluation": {"policy": "most_restrictive_interpretation"},
    "ambiguous_rules": [],
}


def test_the_reset_hour_is_validated():
    profile = ChallengeProfile.from_dict(PROFILE)
    assert ChallengeEngine(profile, reset_hour_utc=23).reset_hour_utc == 23
    for invalid in (-1, 24, 1.5, True, "1"):
        with pytest.raises(ConfigurationError):
            ChallengeEngine(profile, reset_hour_utc=invalid)


def test_quality_reports_accept_both_objects_and_mappings():
    from etatmajor.data.validation import DataQualityReport

    report = DataQualityReport(
        rows_accepted=100,
        missing_bars=25,
        expected_bars=100,
        warnings=["gap"],
    )
    from_object = DataQualityAssessment.from_report(report)
    from_mapping = DataQualityAssessment.from_report(
        {
            "bar_count": 100,
            "missing_bars": 25,
            "expected_bars": 100,
            "warnings": 1,
        }
    )
    assert from_object.missing_ratio == pytest.approx(0.25)
    assert from_mapping.missing_ratio == pytest.approx(0.25)
    assert from_mapping.warnings == 1
    assert from_mapping.errors == 0


def test_the_sniper_engine_receives_the_quality_report():
    quality = {"bar_count": 10, "missing_bars": 5, "expected_bars": 10}
    engine = build_engine("EURUSD", "1m", make_config().sniper, data_quality=quality)
    assert engine.data_quality == quality


def test_a_flat_snapshot_is_shared_until_a_fill():
    portfolio = Portfolio(1000.0, currency="USD")
    first = portfolio.snapshot()
    second = portfolio.snapshot()
    assert first is second
    assert first.positions == ()

    portfolio.apply_fill(
        Fill(
            order_id="O-1",
            symbol="EURUSD",
            side=OrderSide.BUY,
            quantity=1000.0,
            price=1.1,
            commission=0.0,
            ts_ns=1,
        )
    )
    assert portfolio.snapshot() is not first
    assert portfolio.snapshot().positions != ()
