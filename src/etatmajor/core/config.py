"""Configuration objects and their validation.

The configuration is the contract between the operator and the engine: every
value used by a replay is declared, validated at start-up and hashed into the
run report. A configuration that cannot be validated stops the run before any
market data is read.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .types import EndOfReplayPolicy, OperatingMode

TIMEFRAME_UNITS_NS = {
    "s": 1_000_000_000,
    "m": 60 * 1_000_000_000,
    "h": 3_600 * 1_000_000_000,
    "d": 86_400 * 1_000_000_000,
}


def timeframe_to_ns(timeframe: str) -> int:
    """Convert a timeframe such as ``1m`` or ``4h`` into nanoseconds."""
    text = str(timeframe).strip().lower()
    if len(text) < 2 or not text[:-1].isdigit() or text[-1] not in TIMEFRAME_UNITS_NS:
        raise ConfigurationError(
            f"invalid timeframe {timeframe!r}: expected an integer followed by one of "
            f"{sorted(TIMEFRAME_UNITS_NS)} (example: '1m', '5m', '1h', '1d')"
        )
    value = int(text[:-1])
    if value <= 0:
        raise ConfigurationError(f"invalid timeframe {timeframe!r}: multiplier must be > 0")
    return value * TIMEFRAME_UNITS_NS[text[-1]]


@dataclass(frozen=True)
class SimulationConfig:
    """Parameters describing a single replay run."""

    symbol: str = "EURUSD"
    timeframe: str = "1m"
    initial_capital: float = 100_000.0
    currency: str = "USD"
    end_of_replay_policy: EndOfReplayPolicy = EndOfReplayPolicy.CLOSE_AT_LAST_PRICE
    mode: OperatingMode = OperatingMode.LAB
    seed: int = 0

    @property
    def timeframe_ns(self) -> int:
        return timeframe_to_ns(self.timeframe)

    def validate(self) -> None:
        if not self.symbol.strip():
            raise ConfigurationError("simulation.symbol must not be empty")
        if self.initial_capital <= 0:
            raise ConfigurationError(
                f"simulation.initial_capital must be > 0 (got {self.initial_capital})"
            )
        if not self.currency.strip():
            raise ConfigurationError("simulation.currency must not be empty")
        timeframe_to_ns(self.timeframe)
        self._validate_mode()

    def _validate_mode(self) -> None:
        """Refuse les modes dont les capacites ne sont pas implementees.

        Le passage a un mode donne n'est jamais implicite : un mode non
        autorise arrete le programme au demarrage, avec un message explicite.
        """
        if self.mode is OperatingMode.LAB:
            return
        if self.mode is OperatingMode.CHALLENGE_SIM:
            return
        if self.mode is OperatingMode.PAPER:
            raise ConfigurationError(
                "simulation.mode = PAPER is refused: no live market data adapter "
                "exists in this build (Mission 8). Data freshness and paper "
                "execution cannot be guaranteed without it."
            )
        raise ConfigurationError(
            "simulation.mode = PRODUCTION is refused: production requires an "
            "explicit human authorisation and a validated challenge profile "
            "(Mission 10). It is never enabled by default."
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["end_of_replay_policy"] = self.end_of_replay_policy.value
        payload["mode"] = self.mode.value
        return payload


@dataclass(frozen=True)
class ExecutionConfig:
    """Parameters of the simulated broker (spread, slippage, costs, rejects).

    Units
    -----
    * ``spread_price``: absolute price distance between bid and ask
      (e.g. ``0.00010`` for a 1.0 pip spread on EURUSD).
    * ``slippage_price``: absolute adverse price movement applied on every fill.
    * ``slippage_random_max``: upper bound of the uniform random slippage
      component, in the same absolute price unit.
    * ``commission_per_lot_per_side``: commission in account currency, charged
      per lot and per side (entry and exit are charged separately).
    * ``commission_fixed_per_order``: flat commission charged per filled order.
    * ``lot_size``: number of instrument units making one lot, used to convert
      a quantity into lots for the commission computation (100000 for a
      standard FX contract, 1 for a unit-based instrument).
    """

    spread_price: float = 0.0
    slippage_price: float = 0.0
    slippage_random_max: float = 0.0
    commission_per_lot_per_side: float = 0.0
    commission_fixed_per_order: float = 0.0
    reject_probability: float = 0.0
    lot_size: float = 1.0
    min_quantity: float = 0.01
    max_quantity: float = 1_000_000.0
    quantity_step: float = 0.01
    allow_short: bool = True

    def validate(self) -> None:
        for name in (
            "spread_price",
            "slippage_price",
            "slippage_random_max",
            "commission_per_lot_per_side",
            "commission_fixed_per_order",
        ):
            if getattr(self, name) < 0:
                raise ConfigurationError(f"execution.{name} must be >= 0")
        if not 0.0 <= self.reject_probability <= 1.0:
            raise ConfigurationError(
                "execution.reject_probability must be within [0.0, 1.0]"
            )
        if self.min_quantity <= 0:
            raise ConfigurationError("execution.min_quantity must be > 0")
        if self.max_quantity < self.min_quantity:
            raise ConfigurationError(
                "execution.max_quantity must be >= execution.min_quantity"
            )
        if self.quantity_step <= 0:
            raise ConfigurationError("execution.quantity_step must be > 0")
        if self.lot_size <= 0:
            raise ConfigurationError("execution.lot_size must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskConfig:
    """Limits enforced by the risk authority.

    The Phase 2 governor implements the contract only. The advanced limits
    (daily loss, global drawdown, correlated exposure, challenge profiles)
    belong to Phase 5.
    """

    max_position_quantity: float = 1.0
    max_order_notional: float = 100_000.0
    max_open_positions: int = 1
    trading_halted: bool = False
    max_risk_per_trade: float = 0.0
    require_stop_loss: bool = False
    max_leverage: float = 1.0
    kill_switch_path: str | None = None

    def validate(self) -> None:
        if self.max_position_quantity <= 0:
            raise ConfigurationError("risk.max_position_quantity must be > 0")
        if self.max_order_notional <= 0:
            raise ConfigurationError("risk.max_order_notional must be > 0")
        if self.max_open_positions < 0:
            raise ConfigurationError("risk.max_open_positions must be >= 0")
        if self.max_risk_per_trade < 0:
            raise ConfigurationError("risk.max_risk_per_trade must be >= 0")
        if self.max_leverage <= 0:
            raise ConfigurationError("risk.max_leverage must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AppConfig:
    """Aggregate configuration of a replay run."""

    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    source_path: str | None = None

    def validate(self) -> None:
        self.simulation.validate()
        self.execution.validate()
        self.risk.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation": self.simulation.to_dict(),
            "execution": self.execution.to_dict(),
            "risk": self.risk.to_dict(),
        }

    def fingerprint(self) -> str:
        """Stable hash of the effective configuration, embedded in every report."""
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _build(cls, payload: dict[str, Any], section: str) -> Any:
    known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    unknown = set(payload) - known
    if unknown:
        raise ConfigurationError(
            f"unknown key(s) in section [{section}]: {sorted(unknown)}; allowed: {sorted(known)}"
        )
    if cls is SimulationConfig:
        if "end_of_replay_policy" in payload:
            value = payload["end_of_replay_policy"]
            try:
                payload["end_of_replay_policy"] = EndOfReplayPolicy(value)
            except ValueError as exc:
                allowed = [p.value for p in EndOfReplayPolicy]
                raise ConfigurationError(
                    f"simulation.end_of_replay_policy must be one of {allowed} "
                    f"(got {value!r})"
                ) from exc
        if "mode" in payload:
            value = payload["mode"]
            try:
                payload["mode"] = OperatingMode(value)
            except ValueError as exc:
                allowed = [m.value for m in OperatingMode]
                raise ConfigurationError(
                    f"simulation.mode must be one of {allowed} (got {value!r})"
                ) from exc
    try:
        return cls(**payload)
    except TypeError as exc:
        raise ConfigurationError(f"invalid section [{section}]: {exc}") from exc


def load_config(path: str | Path) -> AppConfig:
    """Load and validate a TOML configuration file."""
    source = Path(path)
    if not source.exists():
        raise ConfigurationError(f"configuration file not found: {source}")
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid TOML in {source}: {exc}") from exc

    known_sections = {"simulation", "execution", "risk"}
    unknown = set(payload) - known_sections
    if unknown:
        raise ConfigurationError(
            f"unknown configuration section(s) in {source}: {sorted(unknown)}; "
            f"allowed: {sorted(known_sections)}"
        )

    config = AppConfig(
        simulation=_build(
            SimulationConfig, payload.get("simulation", {}), "simulation"
        ),
        execution=_build(
            ExecutionConfig, payload.get("execution", {}), "execution"
        ),
        risk=_build(RiskConfig, payload.get("risk", {}), "risk"),
        source_path=str(source),
    )
    config.validate()
    return config
