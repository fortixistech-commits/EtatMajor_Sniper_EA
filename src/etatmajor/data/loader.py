"""CSV loader and validator for historical OHLC data.

Canonical CSV format
--------------------
``timestamp`` (ISO-8601 UTC or epoch), ``open``, ``high``, ``low``, ``close``
and optionally ``volume``. Column names are case-insensitive.

Every problem is reported with the line number of the offending row so that a
dataset can be corrected without a second pass. The loader is strict by
default: a malformed dataset raises :class:`DataValidationError` instead of
being silently repaired.
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..core.errors import DataValidationError
from .instruments import InstrumentCatalog, InstrumentSpec
from .models import Bar
from .provenance import DataProvenance
from .validation import DataQualityReport

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")
OPTIONAL_COLUMNS = ("volume",)
EPOCH_UNITS_NS = {
    "s": 1_000_000_000,
    "ms": 1_000_000,
    "us": 1_000,
    "ns": 1,
}


def parse_timestamp(raw: str, timestamp_unit: str = "s") -> int:
    """Parse a timestamp into nanoseconds since the Unix epoch (UTC).

    ISO-8601 strings (``2026-01-05T00:00:00Z``) and epoch numbers are
    supported. Naive ISO strings are assumed to be UTC.
    """
    text = str(raw).strip()
    if not text:
        raise ValueError("empty timestamp")
    try:
        return int(float(text) * EPOCH_UNITS_NS[timestamp_unit])
    except ValueError:
        pass
    iso = text.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(f"unparsable timestamp {raw!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.astimezone(timezone.utc).timestamp() * 1_000_000_000)


def _to_float(raw: Any, column: str, line_no: int, issues: list[str]) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        issues.append(f"line {line_no}: column {column!r} is not numeric ({raw!r})")
        return None
    if math.isnan(value) or math.isinf(value):
        issues.append(f"line {line_no}: column {column!r} is not a finite number ({raw!r})")
        return None
    return value


@dataclass
class Dataset:
    """A validated, immutable-in-practice collection of bars."""

    symbol: str
    timeframe: str
    bars: list[Bar]
    source_path: str | None = None
    sha256: str = ""
    timeframe_ns: int = 0
    quality: DataQualityReport = field(default_factory=DataQualityReport)
    instrument: InstrumentSpec | None = None
    catalog_version: str | None = None
    provenance: DataProvenance | None = None
    _fingerprint: str | None = field(default=None, repr=False, compare=False)

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def first_ts_ns(self) -> int | None:
        return self.bars[0].ts_open_ns if self.bars else None

    @property
    def last_ts_ns(self) -> int | None:
        return self.bars[-1].ts_open_ns if self.bars else None

    def fingerprint(self) -> str:
        """Hash of the dataset content, independent of its file location.

        The value is computed once and cached: it is requested by the report,
        by the journal and by the run header.
        """
        if self._fingerprint is not None:
            return self._fingerprint
        digest = hashlib.sha256()
        for bar in self.bars:
            digest.update(
                f"{bar.ts_open_ns}|{bar.open}|{bar.high}|{bar.low}|{bar.close}|"
                f"{bar.volume}\n".encode("utf-8")
            )
        self._fingerprint = digest.hexdigest()[:16]
        return self._fingerprint

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": len(self.bars),
            "source_path": self.source_path,
            "sha256": self.sha256,
            "content_fingerprint": self.fingerprint(),
            "first_ts_ns": self.first_ts_ns,
            "last_ts_ns": self.last_ts_ns,
            "quality": self.quality.to_dict(),
            "instrument": self.instrument.to_dict() if self.instrument else None,
            "catalog_version": self.catalog_version,
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }


def _normalise_header(header: Iterable[str]) -> list[str]:
    return [str(name).strip().lower() for name in header]


def load_csv(
    path: str | Path,
    symbol: str,
    timeframe: str,
    timeframe_ns: int,
    timestamp_unit: str = "s",
    strict: bool = True,
    catalog: InstrumentCatalog | None = None,
    broker_id: str | None = None,
    provenance: DataProvenance | None = None,
) -> Dataset:
    """Load and validate an OHLC CSV file.

    Parameters
    ----------
    path:
        Path of the CSV file.
    symbol, timeframe:
        Instrument identity attached to the dataset.
    timeframe_ns:
        Duration of a bar in nanoseconds, used for gap detection.
    timestamp_unit:
        Unit of numeric timestamps (``s``, ``ms``, ``us``, ``ns``).
    strict:
        When ``True`` (default) any error aborts the load with
        :class:`DataValidationError`.
    """
    source = Path(path)
    if not source.exists():
        raise DataValidationError(f"market data file not found: {source}")
    if timestamp_unit not in EPOCH_UNITS_NS:
        raise DataValidationError(
            f"unsupported timestamp_unit {timestamp_unit!r}; "
            f"expected one of {sorted(EPOCH_UNITS_NS)}"
        )

    instrument = catalog.require(symbol, broker_id) if catalog is not None else None
    if provenance is not None:
        provenance.validate()

    report = DataQualityReport()
    issues: list[str] = []
    bars: list[Bar] = []
    seen_ts: dict[int, int] = {}
    if instrument is not None:
        report.instrument_id = instrument.instrument_id
    if catalog is not None:
        report.catalog_version = catalog.version

    raw_bytes = source.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    if provenance is not None:
        if provenance.checksum_sha256 is None:
            # Le fichier lui-meme devient la reference verifiable de la
            # provenance : aucune valeur n'est inventee, le hash est mesure.
            provenance = replace(provenance, checksum_sha256=sha256)
        elif provenance.checksum_sha256.lower() != sha256:
            report.add_error(
                "provenance checksum does not match the data file "
                f"({provenance.checksum_sha256} != {sha256})"
            )
        if provenance.granularity != timeframe:
            report.add_warning(
                f"provenance granularity {provenance.granularity!r} differs from "
                f"the dataset timeframe {timeframe!r}"
            )

    text = raw_bytes.decode("utf-8-sig")
    reader = csv.reader(text.splitlines())
    try:
        header = _normalise_header(next(reader))
    except StopIteration:
        raise DataValidationError(f"market data file is empty: {source}") from None

    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise DataValidationError(
            f"{source}: missing required column(s) {missing}; found {header}"
        )
    index = {name: header.index(name) for name in header}
    volume_present = "volume" in index

    previous_ts: int | None = None
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not str(cell).strip() for cell in row):
            continue
        report.rows_read += 1
        if len(row) < len(header):
            issues.append(
                f"line {line_no}: expected {len(header)} columns, found {len(row)}"
            )
            report.rows_rejected += 1
            continue

        try:
            ts_open_ns = parse_timestamp(row[index["timestamp"]], timestamp_unit)
        except ValueError as exc:
            issues.append(f"line {line_no}: {exc}")
            report.rows_rejected += 1
            continue

        values: dict[str, float] = {}
        broken = False
        for column in ("open", "high", "low", "close"):
            value = _to_float(row[index[column]], column, line_no, issues)
            if value is None:
                report.invalid_numbers += 1
                broken = True
                continue
            values[column] = value
        volume = 0.0
        if volume_present:
            volume_value = _to_float(row[index["volume"]], "volume", line_no, issues)
            if volume_value is None:
                report.invalid_numbers += 1
                broken = True
            else:
                volume = volume_value
        if broken:
            report.rows_rejected += 1
            continue

        for column in ("open", "high", "low", "close"):
            if values[column] <= 0.0:
                report.non_positive_prices += 1
                issues.append(
                    f"line {line_no}: column {column!r} must be strictly positive "
                    f"(got {values[column]})"
                )
                broken = True
        if volume < 0.0:
            report.negative_volume += 1
            issues.append(f"line {line_no}: column 'volume' must be >= 0 (got {volume})")
            broken = True
        if broken:
            report.rows_rejected += 1
            continue

        open_, high, low, close = (
            values["open"],
            values["high"],
            values["low"],
            values["close"],
        )
        ohlc_problems: list[str] = []
        if high < low:
            ohlc_problems.append(f"high ({high}) is lower than low ({low})")
        if high < max(open_, close):
            ohlc_problems.append(
                f"high ({high}) is below open/close ({max(open_, close)})"
            )
        if low > min(open_, close):
            ohlc_problems.append(
                f"low ({low}) is above open/close ({min(open_, close)})"
            )
        if ohlc_problems:
            report.invalid_ohlc += 1
            issues.append(f"line {line_no}: inconsistent OHLC: " + "; ".join(ohlc_problems))
            report.rows_rejected += 1
            continue

        if ts_open_ns in seen_ts:
            report.duplicate_timestamps += 1
            issues.append(
                f"line {line_no}: duplicated timestamp "
                f"(first seen on line {seen_ts[ts_open_ns]})"
            )
            report.rows_rejected += 1
            continue

        if previous_ts is not None and ts_open_ns < previous_ts:
            report.out_of_order_timestamps += 1
            issues.append(
                f"line {line_no}: timestamp is earlier than the previous row "
                f"({ts_open_ns} < {previous_ts}): out-of-order data"
            )
            report.rows_rejected += 1
            continue

        if (
            timeframe_ns > 0
            and bars
            and (ts_open_ns - bars[0].ts_open_ns) % timeframe_ns != 0
        ):
            report.unaligned_timestamps += 1

        if instrument is not None and not all(
            instrument.is_price_aligned(price)
            for price in (open_, high, low, close)
        ):
            report.tick_misaligned_prices += 1

        seen_ts[ts_open_ns] = line_no
        previous_ts = ts_open_ns
        bars.append(
            Bar(
                ts_open_ns=ts_open_ns,
                ts_close_ns=ts_open_ns + timeframe_ns,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
        report.rows_accepted += 1

    if not bars:
        issues.append("no valid bar could be read from the dataset")

    # Gap detection (reported as a warning: missing bars do not corrupt the
    # dataset but must be visible in the quality report).
    if timeframe_ns > 0 and bars:
        expected = (bars[-1].ts_open_ns - bars[0].ts_open_ns) // timeframe_ns + 1
        report.expected_bars = int(expected)
        report.missing_bars = int(max(0, expected - len(bars)))
        report.coverage_ratio = (
            round(len(bars) / expected, 6) if expected > 0 else None
        )
        for previous, current in zip(bars, bars[1:]):
            if current.ts_open_ns - previous.ts_open_ns > timeframe_ns:
                report.gap_count += 1
        if report.missing_bars > 0:
            report.add_warning(
                f"{report.missing_bars} bar(s) missing across "
                f"{report.gap_count} gap(s) in the dataset "
                f"(expected {expected} slots, got {len(bars)}, "
                f"coverage {report.coverage_ratio:.4f})"
            )

    if report.unaligned_timestamps:
        report.add_warning(
            f"{report.unaligned_timestamps} timestamp(s) are not aligned to the "
            f"declared timeframe ({timeframe})"
        )
    if report.tick_misaligned_prices:
        report.add_warning(
            f"{report.tick_misaligned_prices} bar(s) contain a price that is not "
            f"aligned to the instrument tick size"
        )

    for issue in issues:
        report.add_error(issue)
    if report.errors and strict:
        raise DataValidationError(
            f"market data validation failed for {source} "
            f"({len(report.errors)} problem(s))",
            issues=report.errors,
        )

    return Dataset(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        source_path=str(source),
        sha256=sha256,
        timeframe_ns=timeframe_ns,
        quality=report,
        instrument=instrument,
        catalog_version=catalog.version if catalog is not None else None,
        provenance=provenance,
    )
