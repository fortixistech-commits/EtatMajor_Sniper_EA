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
    duplicate_timestamps: int = 0
    out_of_order_timestamps: int = 0

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
            "duplicate_timestamps": self.duplicate_timestamps,
            "out_of_order_timestamps": self.out_of_order_timestamps,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }
