"""Structured event journal.

The journal is the audit trail of a run: it records signals, risk decisions,
orders, fills, position updates and errors with their simulated timestamps.
It is the single source of truth used to rebuild the report of a run.
"""

from __future__ import annotations

import json
from pathlib import Path

from .events import JournalEntry


class Journal:
    """Append-only, deterministic event log."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    def append(self, ts_ns: int, type: str, payload: dict | None = None) -> JournalEntry:
        """Append an entry and return it."""
        entry = JournalEntry(
            seq=len(self._entries), ts_ns=ts_ns, type=type, payload=payload or {}
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def of_type(self, type: str) -> list[JournalEntry]:
        """All entries of a given type, in insertion order."""
        return [e for e in self._entries if e.type == type]

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self._entries]

    def write_jsonl(self, path: str | Path) -> Path:
        """Write the journal as newline-delimited JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for entry in self._entries:
                handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
        return target

    def __len__(self) -> int:
        return len(self._entries)
