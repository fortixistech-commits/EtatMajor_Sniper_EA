"""Data provenance record attached to every loaded dataset.

A backtest is only reproducible when the origin of its data is known. The
provenance record captures the source, the retrieval timestamp, the timezone,
the granularity and any known limitation. It deliberately does not infer
missing information.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import ConfigurationError

_TIMEZONE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*$")


@dataclass(frozen=True)
class DataProvenance:
    """Where a dataset comes from and how it was obtained.

    ``timezone`` is the timezone declared by the source. The loader stores
    every timestamp in UTC; no implicit conversion is applied, so the source
    must document whether its timestamps were already UTC.
    """

    source_name: str
    timezone: str
    granularity: str
    version: str
    retrieved_at_utc: str
    source_uri: str | None = None
    adjustments: str = "none"
    checksum_sha256: str | None = None
    is_synthetic: bool = False
    limitations: tuple[str, ...] = ()

    def validate(self) -> None:
        for name in ("source_name", "timezone", "granularity", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationError(f"provenance.{name} must not be empty")
        if not _TIMEZONE_PATTERN.match(self.timezone):
            raise ConfigurationError(
                f"provenance.timezone {self.timezone!r} is not a valid timezone name"
            )
        try:
            moment = datetime.fromisoformat(
                self.retrieved_at_utc.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ConfigurationError(
                "provenance.retrieved_at_utc must be an ISO-8601 timestamp"
            ) from exc
        if moment.tzinfo is None:
            raise ConfigurationError(
                "provenance.retrieved_at_utc must include a timezone offset"
            )
        if self.checksum_sha256 is not None:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", self.checksum_sha256):
                raise ConfigurationError(
                    "provenance.checksum_sha256 must be a 64-character hex digest"
                )
        if not isinstance(self.limitations, tuple):
            raise ConfigurationError("provenance.limitations must be a tuple")
        if any(not str(item).strip() for item in self.limitations):
            raise ConfigurationError(
                "provenance.limitations must not contain empty strings"
            )

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_uri": self.source_uri,
            "retrieved_at_utc": self.retrieved_at_utc,
            "timezone": self.timezone,
            "granularity": self.granularity,
            "version": self.version,
            "adjustments": self.adjustments,
            "checksum_sha256": self.checksum_sha256,
            "is_synthetic": self.is_synthetic,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "DataProvenance":
        if not isinstance(payload, dict):
            raise ConfigurationError("provenance must be a table")
        limitations = payload.get("limitations", [])
        if not isinstance(limitations, list):
            raise ConfigurationError("provenance.limitations must be a list")
        provenance = cls(
            source_name=payload.get("source_name"),
            source_uri=payload.get("source_uri"),
            retrieved_at_utc=payload.get("retrieved_at_utc"),
            timezone=payload.get("timezone"),
            granularity=payload.get("granularity"),
            version=payload.get("version"),
            adjustments=payload.get("adjustments", "none"),
            checksum_sha256=payload.get("checksum_sha256"),
            is_synthetic=bool(payload.get("is_synthetic", False)),
            limitations=tuple(str(item) for item in limitations),
        )
        provenance.validate()
        return provenance


def load_provenance(path: str | Path) -> DataProvenance:
    """Load a provenance record from a TOML file.

    The file may contain the fields at top level or under a ``[provenance]``
    table.
    """
    source = Path(path)
    if not source.exists():
        raise ConfigurationError(f"provenance file not found: {source}")
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"invalid provenance file {source}: {exc}") from exc
    if "provenance" in payload:
        payload = payload["provenance"]
    return DataProvenance.from_dict(payload)


def utc_now_iso() -> str:
    """Current UTC timestamp, used by data ingestion tools."""
    return datetime.now(timezone.utc).isoformat()
