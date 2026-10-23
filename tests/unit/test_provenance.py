"""Tests de la provenance des donnees (phase 2)."""

from __future__ import annotations

import pytest

from etatmajor.core.errors import ConfigurationError
from etatmajor.data.provenance import DataProvenance, load_provenance, utc_now_iso


def payload(**overrides) -> dict:
    values = dict(
        source_name="broker export",
        source_uri="https://example.invalid/export.csv",
        retrieved_at_utc="2026-10-22T12:00:00Z",
        timezone="UTC",
        granularity="1m",
        version="2026-10-22",
        adjustments="none",
        is_synthetic=False,
        limitations=["weekends are absent"],
    )
    values.update(overrides)
    return values


def test_a_complete_provenance_record_is_accepted():
    provenance = DataProvenance.from_dict(payload())
    assert provenance.timezone == "UTC"
    assert provenance.to_dict()["limitations"] == ["weekends are absent"]
    provenance.validate()


def test_retrieval_timestamp_requires_a_timezone():
    with pytest.raises(ConfigurationError):
        DataProvenance.from_dict(
            payload(retrieved_at_utc="2026-10-22T12:00:00")
        )


def test_an_invalid_retrieval_timestamp_is_refused():
    with pytest.raises(ConfigurationError):
        DataProvenance.from_dict(payload(retrieved_at_utc="yesterday"))


@pytest.mark.parametrize("timezone", ["", "not a timezone", "UTC/Paris/Extra!"])
def test_an_invalid_timezone_is_refused(timezone):
    with pytest.raises(ConfigurationError):
        DataProvenance.from_dict(payload(timezone=timezone))


def test_a_checksum_must_be_a_sha256_hex_digest():
    with pytest.raises(ConfigurationError):
        DataProvenance.from_dict(payload(checksum_sha256="abc"))
    accepted = DataProvenance.from_dict(payload(checksum_sha256="a" * 64))
    assert accepted.checksum_sha256 == "a" * 64


def test_empty_limitations_are_refused():
    with pytest.raises(ConfigurationError):
        DataProvenance.from_dict(payload(limitations=["ok", "  "]))


def test_a_provenance_file_can_be_loaded(tmp_path):
    path = tmp_path / "provenance.toml"
    path.write_text(
        "\n".join(
            [
                'source_name = "fixture"',
                'retrieved_at_utc = "2026-10-22T00:00:00Z"',
                'timezone = "UTC"',
                'granularity = "1m"',
                'version = "1"',
                "is_synthetic = true",
            ]
        ),
        encoding="utf-8",
    )
    provenance = load_provenance(path)
    assert provenance.source_name == "fixture"
    assert provenance.is_synthetic is True


def test_utc_now_iso_is_parseable():
    moment = utc_now_iso()
    assert moment.endswith("+00:00")
