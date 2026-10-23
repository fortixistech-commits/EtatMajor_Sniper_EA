"""Integration du catalogue et de la provenance dans un replay (phase 2)."""

from __future__ import annotations

from pathlib import Path

from etatmajor.core.config import load_config
from etatmajor.data.instruments import InstrumentCatalog
from etatmajor.data.loader import load_csv
from etatmajor.data.provenance import load_provenance
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy

ROOT = Path(__file__).resolve().parents[2]


def run():
    config = load_config(ROOT / "configs" / "simulation.toml")
    dataset = load_csv(
        ROOT / "data" / "sample_eurusd_1m.csv",
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        timeframe_ns=config.simulation.timeframe_ns,
        catalog=InstrumentCatalog.load(ROOT / "configs" / "instruments.toml"),
        broker_id="mt5_demo",
        provenance=load_provenance(
            ROOT / "configs" / "data_provenance.sample.toml"
        ),
    )
    strategy = DemoLifecycleStrategy(
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        quantity=10_000.0,
        entry_index=2,
        exit_index=6,
    )
    return ReplayEngine(dataset=dataset, config=config, strategy=strategy).run()


def test_the_report_exposes_the_instrument_and_the_data_provenance():
    result = run()
    dataset = result.report["dataset"]
    assert dataset["instrument"]["instrument_id"] == "EURUSD"
    assert dataset["catalog_version"] == "1.0.0"
    assert dataset["provenance"]["is_synthetic"] is True
    assert dataset["provenance"]["checksum_sha256"] == dataset["sha256"]
    assert dataset["quality"]["instrument_id"] == "EURUSD"
    assert dataset["quality"]["catalog_version"] == "1.0.0"


def test_the_run_is_reproducible_with_catalogue_and_provenance():
    first = run()
    second = run()
    assert first.report["report_fingerprint"] == second.report["report_fingerprint"]
    assert (
        first.report["dataset"]["content_fingerprint"]
        == second.report["dataset"]["content_fingerprint"]
    )
