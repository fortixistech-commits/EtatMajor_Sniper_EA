"""Data validation tests (mandatory assertion 3)."""

from __future__ import annotations

import pytest

from etatmajor.core.errors import DataValidationError
from etatmajor.data.loader import load_csv

TIMEFRAME_NS = 60_000_000_000
HEADER = "timestamp,open,high,low,close,volume\n"


def write_csv(tmp_path, rows: str, name: str = "data.csv"):
    path = tmp_path / name
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def load(path):
    return load_csv(
        path, symbol="EURUSD", timeframe="1m", timeframe_ns=TIMEFRAME_NS
    )


def test_valid_file_is_accepted(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:01:00Z,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    dataset = load(path)
    assert len(dataset) == 2
    assert dataset.quality.ok
    assert dataset.quality.errors == []
    assert dataset.bars[0].ts_close_ns - dataset.bars[0].ts_open_ns == TIMEFRAME_NS


def test_missing_column_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "timestamp,open,high,close\n2026-01-05T00:00:00Z,1.1,1.2,1.15\n",
        encoding="utf-8",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    assert "missing required column" in str(excinfo.value)
    assert "'low'" in str(excinfo.value)


def test_duplicate_timestamp_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:00:00Z,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "duplicated timestamp" in issues
    assert "line 3" in issues


def test_out_of_order_timestamp_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:02:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:01:00Z,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "out-of-order" in issues
    assert "line 3" in issues


def test_inconsistent_ohlc_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:01:00Z,1.1005,1.1010,1.1000,1.1020,11\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "inconsistent OHLC" in issues
    assert "line 3" in issues


def test_high_below_low_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.0990,1.1010,1.1005,10\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "lower than low" in issues


def test_non_positive_price_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,0.0,10\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "strictly positive" in issues
    assert "line 2" in issues


def test_non_numeric_price_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,not-a-number,10\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "not numeric" in issues


def test_unparsable_timestamp_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "not-a-date,1.1000,1.1010,1.0990,1.1005,10\n",
    )
    with pytest.raises(DataValidationError) as excinfo:
        load(path)
    issues = " ".join(excinfo.value.issues)
    assert "unparsable timestamp" in issues


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DataValidationError):
        load(path)


def test_missing_bars_are_reported_as_a_warning(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:05:00Z,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    dataset = load(path)
    assert dataset.quality.ok
    assert dataset.quality.missing_bars == 4
    assert dataset.quality.warnings


def test_epoch_timestamps_are_supported(tmp_path):
    path = write_csv(
        tmp_path,
        "1767571200,1.1000,1.1010,1.0990,1.1005,10\n"
        "1767571260,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    dataset = load(path)
    assert len(dataset) == 2
    assert dataset.bars[0].ts_open_ns == 1_767_571_200_000_000_000


def test_strict_false_collects_errors_without_raising(tmp_path):
    path = write_csv(
        tmp_path,
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,10\n"
        "2026-01-05T00:00:00Z,1.1005,1.1020,1.1000,1.1015,11\n",
    )
    dataset = load_csv(
        path,
        symbol="EURUSD",
        timeframe="1m",
        timeframe_ns=TIMEFRAME_NS,
        strict=False,
    )
    assert not dataset.quality.ok
    assert dataset.quality.duplicate_timestamps == 1
    assert len(dataset) == 1
