"""Tests de qualite et de provenance du chargeur (phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from etatmajor.core.errors import ConfigurationError, DataValidationError
from etatmajor.data.instruments import InstrumentCatalog
from etatmajor.data.loader import load_csv
from etatmajor.data.provenance import DataProvenance

TIMEFRAME_NS = 60_000_000_000
HEADER = "timestamp,open,high,low,close,volume\n"
ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs" / "instruments.toml"


def write_csv(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def load(path, **kwargs):
    return load_csv(
        path,
        symbol=kwargs.pop("symbol", "EURUSD"),
        timeframe="1m",
        timeframe_ns=TIMEFRAME_NS,
        **kwargs,
    )


def provenance(**overrides) -> DataProvenance:
    values = dict(
        source_name="fixture",
        retrieved_at_utc="2026-10-22T00:00:00Z",
        timezone="UTC",
        granularity="1m",
        version="1",
    )
    values.update(overrides)
    return DataProvenance.from_dict(values)


def test_an_inconsistent_bar_is_counted_and_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:01:00Z,1.1005,1.1010,1.1000,1.1020,11\n",
    )
    with pytest.raises(DataValidationError):
        load(path)
    dataset = load(path, strict=False)
    assert len(dataset) == 1
    assert dataset.quality.invalid_ohlc == 1
    assert dataset.quality.rows_rejected == 1


def test_non_positive_prices_are_counted(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,0.0,10\n",
    )
    dataset = load(path, strict=False)
    assert dataset.quality.non_positive_prices == 1
    assert dataset.quality.ok is False


def test_negative_volume_is_counted(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,-1\n",
    )
    dataset = load(path, strict=False)
    assert dataset.quality.negative_volume == 1


def test_non_numeric_values_are_counted(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,oops,10\n",
    )
    dataset = load(path, strict=False)
    assert dataset.quality.invalid_numbers == 1


def test_gaps_are_quantified(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:05:00Z,1.1005,1.1020,1.1000,1.1015,11\n"
        "2026-01-05T00:06:00Z,1.1015,1.1030,1.1010,1.1025,12\n",
    )
    dataset = load(path)
    assert dataset.quality.missing_bars == 4
    assert dataset.quality.gap_count == 1
    assert dataset.quality.expected_bars == 7
    assert dataset.quality.coverage_ratio == pytest.approx(3 / 7, abs=1e-6)


def test_unaligned_timestamps_are_reported(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:01:30Z,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    dataset = load(path)
    assert dataset.quality.unaligned_timestamps == 1
    assert any("aligned" in warning for warning in dataset.quality.warnings)


def test_an_unknown_instrument_is_rejected_before_reading(tmp_path):
    catalog = InstrumentCatalog.load(CATALOG)
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        load(path, symbol="UNKNOWN", catalog=catalog)
    assert "unknown instrument" in str(excinfo.value)


def test_the_catalogue_attaches_the_instrument_to_the_dataset(tmp_path):
    catalog = InstrumentCatalog.load(CATALOG)
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.10000,1.10010,1.09990,1.10005,10\n",
    )
    dataset = load(path, catalog=catalog, broker_id="mt5_demo")
    assert dataset.instrument is not None
    assert dataset.instrument.instrument_id == "EURUSD"
    assert dataset.catalog_version == "1.0.0"
    assert dataset.quality.instrument_id == "EURUSD"
    assert dataset.quality.catalog_version == "1.0.0"
    assert dataset.to_dict()["instrument"]["tick_size"] == 0.00001


def test_a_tick_alignment_defect_is_visible(tmp_path):
    catalog = InstrumentCatalog.load(CATALOG)
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.100001,1.100011,1.099991,1.100005,10\n",
    )
    dataset = load(path, catalog=catalog)
    assert dataset.quality.tick_misaligned_prices == 1
    assert any("tick size" in warning for warning in dataset.quality.warnings)


def test_the_provenance_is_attached_and_reported(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n",
    )
    dataset = load(path, provenance=provenance())
    assert dataset.provenance is not None
    assert dataset.to_dict()["provenance"]["source_name"] == "fixture"


def test_a_provenance_checksum_mismatch_is_refused(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path, provenance=provenance(checksum_sha256="b" * 64))
    assert "checksum" in " ".join(excinfo.value.issues)


def test_a_granularity_mismatch_is_a_visible_warning(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n",
    )
    dataset = load(path, provenance=provenance(granularity="5m"))
    assert any("granularity" in warning for warning in dataset.quality.warnings)
