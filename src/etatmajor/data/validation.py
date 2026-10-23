"""Data quality assessment for OHLC datasets."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataQualityReport:
    """Quantified quality assessment of a dataset.

    ``errors`` are fatal (the dataset cannot be used), ``warnings`` are
    reported but do not prevent a run unless the configuration demands it.
    """

    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_bars: int = 0
    gap_count: int = 0
    expected_bars: int = 0
    coverage_ratio: float | None = None
    duplicate_timestamps: int = 0
    out_of_order_timestamps: int = 0
    unaligned_timestamps: int = 0
    invalid_ohlc: int = 0
    non_positive_prices: int = 0
    negative_volume: int = 0
    invalid_numbers: int = 0
    tick_misaligned_prices: int = 0
    instrument_id: str | None = None
    catalog_version: str | None = None

    @property
    def ok(self) -> bool:
        """``True`` when the dataset is usable."""
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
            "missing_bars": self.missing_bars,
            "gap_count": self.gap_count,
            "expected_bars": self.expected_bars,
            "coverage_ratio": self.coverage_ratio,
            "duplicate_timestamps": self.duplicate_timestamps,
            "out_of_order_timestamps": self.out_of_order_timestamps,
            "unaligned_timestamps": self.unaligned_timestamps,
            "invalid_ohlc": self.invalid_ohlc,
            "non_positive_prices": self.non_positive_prices,
            "negative_volume": self.negative_volume,
            "invalid_numbers": self.invalid_numbers,
            "tick_misaligned_prices": self.tick_misaligned_prices,
            "instrument_id": self.instrument_id,
            "catalog_version": self.catalog_version,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }
