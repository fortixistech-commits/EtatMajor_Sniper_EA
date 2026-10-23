"""Tests du catalogue d'instruments versionne (phase 2).

Le point central : un instrument inconnu ne recoit jamais de parametres
arbitraires, et les proprietes de l'instrument sont distinctes des
contraintes du broker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etatmajor.core.errors import ConfigurationError
from etatmajor.data.instruments import (
    BrokerSymbolSpec,
    InstrumentCatalog,
    InstrumentSpec,
    UnknownInstrumentError,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs" / "instruments.toml"


def test_the_repository_catalogue_loads_with_its_version():
    catalog = InstrumentCatalog.load(CATALOG)
    assert catalog.version == "1.0.0"
    assert catalog.sha256
    assert catalog.source_path == str(CATALOG)
    assert catalog.fingerprint().startswith("1.0.0:")


def test_eurusd_properties_are_explicit():
    catalog = InstrumentCatalog.load(CATALOG)
    spec = catalog.require("EURUSD")
    assert spec.instrument_id == "EURUSD"
    assert spec.asset_class == "forex"
    assert spec.quote_currency == "USD"
    assert spec.price_precision == 5
    assert spec.tick_size == 0.00001
    assert spec.tick_value == 1.0
    assert spec.min_quantity == 1000.0
    assert spec.quantity_step == 1000.0


def test_an_unknown_instrument_is_refused_without_defaults():
    catalog = InstrumentCatalog.load(CATALOG)
    with pytest.raises(UnknownInstrumentError):
        catalog.require("NOT_A_SYMBOL")
    with pytest.raises(UnknownInstrumentError):
        catalog.broker_symbol("mt5_demo", "NOT_A_SYMBOL")
    with pytest.raises(UnknownInstrumentError):
        catalog.require("EURUSD", broker_id="no-such-broker")


def test_a_broker_mapping_resolves_to_the_instrument():
    catalog = InstrumentCatalog.load(CATALOG)
    spec = catalog.require("EURUSD", broker_id="mt5_demo")
    broker = catalog.broker_symbol("mt5_demo", "EURUSD")
    assert spec.instrument_id == "EURUSD"
    assert broker.instrument_id == "EURUSD"
    assert broker.min_quantity == 1000.0


def test_quantity_and_price_alignment():
    catalog = InstrumentCatalog.load(CATALOG)
    spec = catalog.require("EURUSD")
    assert spec.is_quantity_aligned(5000.0)
    assert not spec.is_quantity_aligned(5500.0)
    assert spec.is_price_aligned(1.10001)
    assert not spec.is_price_aligned(1.100015)


def write_catalog(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "catalog.toml"
    path.write_text(body, encoding="utf-8")
    return path


def minimal_catalog(instrument_extra: str = "") -> str:
    return f"""
version = "1.0.0"

[instruments.TEST]
symbol = "TEST"
asset_class = "forex"
quote_currency = "USD"
price_precision = 5
tick_size = 0.00001
min_quantity = 1.0
quantity_step = 1.0
source = "tests"
version = "1.0.0"
{instrument_extra}
"""


def test_a_zero_tick_size_is_refused_at_load(tmp_path):
    body = minimal_catalog().replace("tick_size = 0.00001", "tick_size = 0.0")
    with pytest.raises(ConfigurationError):
        InstrumentCatalog.load(write_catalog(tmp_path, body))


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_precision": 99},
        {"min_quantity": -1.0},
        {"quantity_step": 0.0},
        {"max_quantity": 0.5},
        {"tick_value": 1.0},  # sans devise
        {"tick_size": float("nan")},
    ],
)
def test_invalid_instrument_properties_are_refused(overrides):
    values = dict(
        instrument_id="X",
        symbol="X",
        asset_class="forex",
        quote_currency="USD",
        base_currency=None,
        price_precision=5,
        tick_size=0.00001,
        min_quantity=1.0,
        quantity_step=1.0,
    )
    values.update(overrides)
    with pytest.raises(ConfigurationError):
        InstrumentSpec(**values).validate()


def test_a_broker_cannot_reference_an_unknown_instrument(tmp_path):
    body = minimal_catalog() + """
[brokers.b]
[brokers.b.symbols.TEST]
instrument_id = "MISSING"
min_quantity = 1.0
quantity_step = 1.0
"""
    with pytest.raises(ConfigurationError) as excinfo:
        InstrumentCatalog.load(write_catalog(tmp_path, body))
    assert "unknown instrument" in str(excinfo.value)


def test_the_catalogue_requires_a_version(tmp_path):
    body = minimal_catalog().replace('version = "1.0.0"', "", 1)
    with pytest.raises(ConfigurationError):
        InstrumentCatalog.load(write_catalog(tmp_path, body))


def test_the_catalogue_requires_at_least_one_instrument(tmp_path):
    with pytest.raises(ConfigurationError):
        InstrumentCatalog.load(write_catalog(tmp_path, 'version = "1.0.0"\n'))


def test_instrument_spec_rejects_max_below_min():
    spec = InstrumentSpec(
        instrument_id="X",
        symbol="X",
        asset_class="forex",
        quote_currency="USD",
        base_currency=None,
        price_precision=5,
        tick_size=0.00001,
        min_quantity=10.0,
        quantity_step=1.0,
        max_quantity=5.0,
    )
    with pytest.raises(ConfigurationError):
        spec.validate()


def test_broker_spec_rejects_invalid_limits():
    spec = BrokerSymbolSpec(
        broker_id="b",
        symbol="X",
        instrument_id="X",
        min_quantity=0.0,
        quantity_step=1.0,
    )
    with pytest.raises(ConfigurationError):
        spec.validate()
