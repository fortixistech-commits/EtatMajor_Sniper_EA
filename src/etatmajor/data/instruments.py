"""Versioned instrument catalogue and broker symbol mapping.

The catalogue is the only source of truth for instrument properties (tick
size, precision, contract size, quantity constraints). An unknown symbol is
**never** given arbitrary defaults: it is rejected with
:class:`UnknownInstrumentError`.

Instrument properties and broker-specific constraints are deliberately
separate:

* :class:`InstrumentSpec` describes the instrument itself;
* :class:`BrokerSymbolSpec` describes how one broker exposes that instrument
  (its own symbol name, quantity limits and step).

The catalogue is loaded from TOML and keeps the source path and a SHA-256 of
the file, so a run can reference the exact catalogue version it used.
"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import ConfigurationError


class UnknownInstrumentError(ConfigurationError):
    """Raised when a symbol is absent from the catalogue."""


def _require_text(payload: dict, key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _optional_text(payload: dict, key: str, context: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _positive_number(payload: dict, key: str, context: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{context}.{key} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ConfigurationError(f"{context}.{key} must be finite and > 0")
    return number


def _optional_positive_number(
    payload: dict, key: str, context: str
) -> float | None:
    if key not in payload or payload[key] is None:
        return None
    return _positive_number(payload, key, context)


@dataclass(frozen=True)
class InstrumentSpec:
    """Intrinsic properties of a tradable instrument.

    ``tick_value``, when available, is the value of one tick for one lot in
    ``tick_value_currency``. It is optional because not every source provides
    it; a missing value is *not* replaced by a guess.
    """

    instrument_id: str
    symbol: str
    asset_class: str
    quote_currency: str
    base_currency: str | None
    price_precision: int
    tick_size: float
    min_quantity: float
    quantity_step: float
    max_quantity: float | None = None
    tick_value: float | None = None
    tick_value_currency: str | None = None
    contract_size: float | None = None
    source: str = "unspecified"
    version: str = "0"

    def validate(self) -> None:
        if not self.instrument_id.strip():
            raise ConfigurationError("instrument_id must not be empty")
        if not self.symbol.strip():
            raise ConfigurationError(f"{self.instrument_id}.symbol must not be empty")
        if not self.asset_class.strip():
            raise ConfigurationError(
                f"{self.instrument_id}.asset_class must not be empty"
            )
        if not self.quote_currency.strip():
            raise ConfigurationError(
                f"{self.instrument_id}.quote_currency must not be empty"
            )
        if isinstance(self.price_precision, bool) or not isinstance(
            self.price_precision, int
        ):
            raise ConfigurationError(
                f"{self.instrument_id}.price_precision must be an integer"
            )
        if not 0 <= self.price_precision <= 10:
            raise ConfigurationError(
                f"{self.instrument_id}.price_precision must be between 0 and 10"
            )
        for name in ("tick_size", "min_quantity", "quantity_step"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ConfigurationError(f"{self.instrument_id}.{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ConfigurationError(
                    f"{self.instrument_id}.{name} must be finite and > 0"
                )
        if self.max_quantity is not None:
            if not math.isfinite(self.max_quantity) or self.max_quantity <= 0.0:
                raise ConfigurationError(
                    f"{self.instrument_id}.max_quantity must be finite and > 0"
                )
            if self.max_quantity < self.min_quantity:
                raise ConfigurationError(
                    f"{self.instrument_id}.max_quantity must be >= min_quantity"
                )
        if self.tick_value is not None:
            if not math.isfinite(self.tick_value) or self.tick_value <= 0.0:
                raise ConfigurationError(
                    f"{self.instrument_id}.tick_value must be finite and > 0"
                )
            if not self.tick_value_currency:
                raise ConfigurationError(
                    f"{self.instrument_id}.tick_value requires tick_value_currency"
                )
        if self.contract_size is not None:
            if not math.isfinite(self.contract_size) or self.contract_size <= 0.0:
                raise ConfigurationError(
                    f"{self.instrument_id}.contract_size must be finite and > 0"
                )

    def price_to_ticks(self, price: float) -> float:
        return price / self.tick_size

    def is_price_aligned(self, price: float, tolerance: float = 1e-6) -> bool:
        ticks = self.price_to_ticks(price)
        return abs(ticks - round(ticks)) <= tolerance

    def is_quantity_aligned(self, quantity: float, tolerance: float = 1e-9) -> bool:
        steps = quantity / self.quantity_step
        return abs(steps - round(steps)) <= tolerance

    def to_dict(self) -> dict:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "price_precision": self.price_precision,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "tick_value_currency": self.tick_value_currency,
            "min_quantity": self.min_quantity,
            "quantity_step": self.quantity_step,
            "max_quantity": self.max_quantity,
            "contract_size": self.contract_size,
            "source": self.source,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, instrument_id: str, payload: dict) -> "InstrumentSpec":
        if not isinstance(payload, dict):
            raise ConfigurationError(f"instruments.{instrument_id} must be a table")
        context = f"instruments.{instrument_id}"
        spec = cls(
            instrument_id=instrument_id,
            symbol=_require_text(payload, "symbol", context),
            asset_class=_require_text(payload, "asset_class", context),
            quote_currency=_require_text(payload, "quote_currency", context),
            base_currency=_optional_text(payload, "base_currency", context),
            price_precision=payload.get("price_precision"),
            tick_size=_positive_number(payload, "tick_size", context),
            min_quantity=_positive_number(payload, "min_quantity", context),
            quantity_step=_positive_number(payload, "quantity_step", context),
            max_quantity=_optional_positive_number(payload, "max_quantity", context),
            tick_value=_optional_positive_number(payload, "tick_value", context),
            tick_value_currency=_optional_text(
                payload, "tick_value_currency", context
            ),
            contract_size=_optional_positive_number(
                payload, "contract_size", context
            ),
            source=_require_text(payload, "source", context),
            version=_require_text(payload, "version", context),
        )
        spec.validate()
        return spec


@dataclass(frozen=True)
class BrokerSymbolSpec:
    """How a specific broker exposes an instrument."""

    broker_id: str
    symbol: str
    instrument_id: str
    min_quantity: float
    quantity_step: float
    max_quantity: float | None = None

    def validate(self) -> None:
        if not self.broker_id.strip():
            raise ConfigurationError("broker_id must not be empty")
        if not self.symbol.strip():
            raise ConfigurationError(f"broker {self.broker_id}: symbol must not be empty")
        if not self.instrument_id.strip():
            raise ConfigurationError(
                f"broker {self.broker_id}/{self.symbol}: instrument_id must not be empty"
            )
        for name in ("min_quantity", "quantity_step"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ConfigurationError(
                    f"broker {self.broker_id}/{self.symbol}.{name} must be numeric"
                )
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ConfigurationError(
                    f"broker {self.broker_id}/{self.symbol}.{name} must be finite and > 0"
                )
        if self.max_quantity is not None:
            if not math.isfinite(self.max_quantity) or self.max_quantity <= 0.0:
                raise ConfigurationError(
                    f"broker {self.broker_id}/{self.symbol}.max_quantity must be > 0"
                )
            if self.max_quantity < self.min_quantity:
                raise ConfigurationError(
                    f"broker {self.broker_id}/{self.symbol}.max_quantity must be >= min_quantity"
                )

    def to_dict(self) -> dict:
        return {
            "broker_id": self.broker_id,
            "symbol": self.symbol,
            "instrument_id": self.instrument_id,
            "min_quantity": self.min_quantity,
            "quantity_step": self.quantity_step,
            "max_quantity": self.max_quantity,
        }


@dataclass(frozen=True)
class InstrumentCatalog:
    """Immutable catalogue loaded from a versioned TOML file."""

    version: str
    instruments: dict[str, InstrumentSpec]
    brokers: dict[str, dict[str, BrokerSymbolSpec]]
    source_path: str | None = None
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ConfigurationError("catalogue version must not be empty")
        for spec in self.instruments.values():
            spec.validate()
        for broker_id, symbols in self.brokers.items():
            if not broker_id.strip():
                raise ConfigurationError("broker id must not be empty")
            for symbol, broker_spec in symbols.items():
                broker_spec.validate()
                if broker_spec.instrument_id not in self.instruments:
                    raise ConfigurationError(
                        f"broker {broker_id}/{symbol} references unknown instrument "
                        f"{broker_spec.instrument_id!r}"
                    )

    def require(
        self, symbol: str, broker_id: str | None = None
    ) -> InstrumentSpec:
        """Return the instrument for ``symbol`` or raise.

        With ``broker_id``, the lookup goes through that broker's symbol
        mapping (which may rename the instrument). Without it, the symbol is
        matched against instrument ids first, then against instrument symbols.
        """
        if broker_id is not None:
            broker_symbols = self.brokers.get(broker_id)
            if broker_symbols is None:
                raise UnknownInstrumentError(
                    f"unknown broker {broker_id!r}; available: "
                    f"{sorted(self.brokers)}"
                )
            broker_spec = broker_symbols.get(symbol)
            if broker_spec is None:
                raise UnknownInstrumentError(
                    f"symbol {symbol!r} is not mapped for broker {broker_id!r}; "
                    f"available: {sorted(broker_symbols)}"
                )
            return self.instruments[broker_spec.instrument_id]

        if symbol in self.instruments:
            return self.instruments[symbol]

        matches = [
            spec
            for spec in self.instruments.values()
            if spec.symbol == symbol
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ConfigurationError(
                f"symbol {symbol!r} is ambiguous in the catalogue"
            )
        raise UnknownInstrumentError(
            f"unknown instrument {symbol!r}; available: "
            f"{sorted(self.instruments)}"
        )

    def broker_symbol(
        self, broker_id: str, symbol: str
    ) -> BrokerSymbolSpec:
        broker_symbols = self.brokers.get(broker_id)
        if broker_symbols is None:
            raise UnknownInstrumentError(f"unknown broker {broker_id!r}")
        spec = broker_symbols.get(symbol)
        if spec is None:
            raise UnknownInstrumentError(
                f"symbol {symbol!r} is not mapped for broker {broker_id!r}"
            )
        return spec

    def fingerprint(self) -> str:
        return f"{self.version}:{self.sha256[:16] if self.sha256 else 'nohash'}"

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "sha256": self.sha256,
            "source_path": self.source_path,
            "instruments": {
                key: spec.to_dict() for key, spec in sorted(self.instruments.items())
            },
            "brokers": {
                broker_id: {
                    symbol: spec.to_dict()
                    for symbol, spec in sorted(symbols.items())
                }
                for broker_id, symbols in sorted(self.brokers.items())
            },
        }

    @classmethod
    def load(cls, path: str | Path) -> "InstrumentCatalog":
        source = Path(path)
        if not source.exists():
            raise ConfigurationError(f"instrument catalogue not found: {source}")
        raw = source.read_bytes()
        try:
            payload = tomllib.loads(raw.decode("utf-8-sig"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise ConfigurationError(
                f"invalid instrument catalogue {source}: {exc}"
            ) from exc

        version = _require_text(payload, "version", "catalogue")
        raw_instruments = payload.get("instruments")
        if not isinstance(raw_instruments, dict) or not raw_instruments:
            raise ConfigurationError("catalogue.instruments must be a non-empty table")

        instruments = {
            key: InstrumentSpec.from_dict(key, value)
            for key, value in raw_instruments.items()
        }

        brokers: dict[str, dict[str, BrokerSymbolSpec]] = {}
        raw_brokers = payload.get("brokers", {})
        if not isinstance(raw_brokers, dict):
            raise ConfigurationError("catalogue.brokers must be a table")
        for broker_id, broker_payload in raw_brokers.items():
            if not isinstance(broker_payload, dict):
                raise ConfigurationError(f"brokers.{broker_id} must be a table")
            raw_symbols = broker_payload.get("symbols", {})
            if not isinstance(raw_symbols, dict):
                raise ConfigurationError(
                    f"brokers.{broker_id}.symbols must be a table"
                )
            symbols: dict[str, BrokerSymbolSpec] = {}
            for symbol, symbol_payload in raw_symbols.items():
                if not isinstance(symbol_payload, dict):
                    raise ConfigurationError(
                        f"brokers.{broker_id}.symbols.{symbol} must be a table"
                    )
                context = f"brokers.{broker_id}.symbols.{symbol}"
                spec = BrokerSymbolSpec(
                    broker_id=broker_id,
                    symbol=symbol,
                    instrument_id=_require_text(
                        symbol_payload, "instrument_id", context
                    ),
                    min_quantity=_positive_number(
                        symbol_payload, "min_quantity", context
                    ),
                    quantity_step=_positive_number(
                        symbol_payload, "quantity_step", context
                    ),
                    max_quantity=_optional_positive_number(
                        symbol_payload, "max_quantity", context
                    ),
                )
                spec.validate()
                symbols[symbol] = spec
            brokers[broker_id] = symbols

        return cls(
            version=version,
            instruments=instruments,
            brokers=brokers,
            source_path=str(source),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
