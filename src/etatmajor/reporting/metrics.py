"""Deterministic performance metrics for replay evidence.

The module reconstructs closed round trips from the recorded fills, then
derives the metrics used by the validation dossier: win rate, profit factor,
expectancy, drawdown, exposure and per-side/per-symbol breakdowns.

It never reads the wall clock, never uses floating randomness and accepts both
domain objects (during a replay) and plain dictionaries (when a report is
loaded from disk). Missing or ambiguous information is reported explicitly in
``assumptions`` rather than silently guessed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

MAX_CURVE_POINTS = 500


@dataclass(frozen=True)
class Trade:
    """A closed round trip reconstructed from netted fills."""

    trade_id: str
    symbol: str
    side: str
    quantity: float
    entry_ts_ns: int
    exit_ts_ns: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    entry_order_id: str
    exit_order_id: str
    exit_reason: str

    @property
    def duration_ns(self) -> int:
        return max(0, self.exit_ts_ns - self.entry_ts_ns)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["duration_ns"] = self.duration_ns
        return payload


@dataclass
class _OpenPosition:
    quantity: float
    average_price: float
    entry_ts_ns: int
    entry_order_id: str
    entry_side: str
    entry_fees: float


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def reconstruct_trades(
    fills: Iterable[Any], orders: Iterable[Any] | None = None
) -> list[Trade]:
    """Reconstruct closed trades from netted fills.

    A reduction or a flip closes the corresponding quantity. Entry fees are
    allocated proportionally to the closed quantity so that every trade carries
    its own share of the round-trip cost.
    """
    reasons: dict[str, str] = {}
    for order in orders or ():
        payload = _as_dict(order)
        order_id = str(payload.get("order_id", ""))
        if order_id:
            reasons[order_id] = str(payload.get("reason", "") or "")

    trades: list[Trade] = []
    position: _OpenPosition | None = None
    for raw_fill in fills:
        fill = _as_dict(raw_fill)
        side = str(fill.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            continue
        quantity = _number(fill.get("quantity"))
        price = _number(fill.get("price"))
        fee = _number(fill.get("commission"))
        ts_ns = fill.get("ts_ns")
        if quantity <= 0 or price <= 0 or not _is_int(ts_ns):
            continue
        signed = quantity if side == "BUY" else -quantity
        order_id = str(fill.get("order_id", ""))

        if position is None or position.quantity == 0.0:
            position = _OpenPosition(
                quantity=signed,
                average_price=price,
                entry_ts_ns=int(ts_ns),
                entry_order_id=order_id,
                entry_side=side,
                entry_fees=fee,
            )
            continue

        same_direction = (position.quantity > 0) == (signed > 0)
        if same_direction:
            total = position.quantity + signed
            position.average_price = (
                abs(position.quantity) * position.average_price + quantity * price
            ) / abs(total)
            position.quantity = total
            position.entry_fees += fee
            continue

        direction = 1.0 if position.quantity > 0 else -1.0
        close_quantity = min(quantity, abs(position.quantity))
        entry_fee_share = (
            position.entry_fees * close_quantity / abs(position.quantity)
            if position.quantity
            else 0.0
        )
        exit_fee_share = fee * close_quantity / quantity if quantity else 0.0
        gross = close_quantity * (price - position.average_price) * direction
        trades.append(
            Trade(
                trade_id=f"T{len(trades) + 1}",
                symbol=str(fill.get("symbol", "")),
                side=position.entry_side,
                quantity=close_quantity,
                entry_ts_ns=position.entry_ts_ns,
                exit_ts_ns=int(ts_ns),
                entry_price=position.average_price,
                exit_price=price,
                gross_pnl=gross,
                fees=entry_fee_share + exit_fee_share,
                net_pnl=gross - entry_fee_share - exit_fee_share,
                entry_order_id=position.entry_order_id,
                exit_order_id=order_id,
                exit_reason=reasons.get(order_id, "") or "not recorded",
            )
        )

        position.entry_fees -= entry_fee_share
        remaining = quantity - close_quantity
        if remaining <= 1e-12:
            position.quantity += signed
            if abs(position.quantity) < 1e-12:
                position = None
            continue

        # The fill flips the position: the residual opens in the other direction.
        position = _OpenPosition(
            quantity=remaining * (1.0 if signed > 0 else -1.0),
            average_price=price,
            entry_ts_ns=int(ts_ns),
            entry_order_id=order_id,
            entry_side=side,
            entry_fees=fee - exit_fee_share,
        )
    return trades


def trades_from_report(report: dict[str, Any]) -> list[Trade]:
    """Reconstruct trades from a serialized report."""
    executions = report.get("executions")
    orders = report.get("orders")
    return reconstruct_trades(
        executions.get("details", []) if isinstance(executions, dict) else [],
        orders.get("details", []) if isinstance(orders, dict) else [],
    )


def trade_statistics(trades: Iterable[Trade]) -> dict[str, Any]:
    """Aggregate statistics over closed trades only."""
    items = list(trades)
    winning = [trade for trade in items if trade.net_pnl > 0]
    losing = [trade for trade in items if trade.net_pnl < 0]
    gross_profit = sum(trade.net_pnl for trade in winning)
    gross_loss = abs(sum(trade.net_pnl for trade in losing))
    total = sum(trade.net_pnl for trade in items)
    count = len(items)
    average_win = gross_profit / len(winning) if winning else 0.0
    average_loss = -gross_loss / len(losing) if losing else 0.0
    return {
        "trades": count,
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "breakeven_trades": count - len(winning) - len(losing),
        "win_rate_percent": 100.0 * len(winning) / count if count else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": total,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "expectancy": total / count if count else 0.0,
        "average_win": average_win,
        "average_loss": average_loss,
        "payoff_ratio": (
            average_win / abs(average_loss) if average_loss < 0 else None
        ),
        "largest_win": max((trade.net_pnl for trade in winning), default=0.0),
        "largest_loss": min((trade.net_pnl for trade in losing), default=0.0),
        "average_duration_ns": (
            sum(trade.duration_ns for trade in items) / count if count else 0.0
        ),
    }


def drawdown_statistics(
    equity_curve: Iterable[tuple[int, float]],
) -> dict[str, Any]:
    """Maximum drawdown and underwater duration from an equity curve."""
    points = [(int(ts), float(value)) for ts, value in equity_curve]
    if not points:
        return {
            "max_drawdown": 0.0,
            "max_drawdown_percent": 0.0,
            "max_drawdown_peak_ts_ns": None,
            "max_drawdown_trough_ts_ns": None,
            "max_drawdown_duration_ns": 0,
            "max_drawdown_points": 0,
        }
    peak_value = points[0][1]
    peak_ts = points[0][0]
    worst = 0.0
    worst_percent = 0.0
    worst_peak_ts = points[0][0]
    worst_trough_ts = points[0][0]
    worst_points = 0
    underwater_start = points[0][0]
    underwater_points = 0
    for ts, value in points:
        if value >= peak_value:
            peak_value = value
            peak_ts = ts
            underwater_start = ts
            underwater_points = 0
            continue
        underwater_points += 1
        drawdown = peak_value - value
        if drawdown > worst:
            worst = drawdown
            worst_percent = 100.0 * drawdown / peak_value if peak_value else 0.0
            worst_peak_ts = peak_ts
            worst_trough_ts = ts
            worst_points = underwater_points
    return {
        "max_drawdown": worst,
        "max_drawdown_percent": worst_percent,
        "max_drawdown_peak_ts_ns": worst_peak_ts,
        "max_drawdown_trough_ts_ns": worst_trough_ts,
        "max_drawdown_duration_ns": max(0, worst_trough_ts - worst_peak_ts),
        "max_drawdown_points": worst_points,
        "underwater_at_end": points[-1][1] < peak_value,
        "underwater_start_ts_ns": underwater_start,
    }


def sample_curve(
    equity_curve: Iterable[tuple[int, float]], limit: int = MAX_CURVE_POINTS
) -> dict[str, Any]:
    """Down-sample the curve for the report without losing its endpoints."""
    points = [(int(ts), float(value)) for ts, value in equity_curve]
    if limit < 2:
        raise ValueError("curve limit must be >= 2")
    if len(points) <= limit:
        sampled = points
    else:
        indexes = sorted(
            {round(index * (len(points) - 1) / (limit - 1)) for index in range(limit)}
        )
        sampled = [points[index] for index in indexes]
    return {
        "equity_curve": [[ts, value] for ts, value in sampled],
        "equity_curve_points": len(points),
        "equity_curve_sampled": len(sampled) < len(points),
    }


def performance_section(
    *,
    fills: Iterable[Any],
    orders: Iterable[Any] | None,
    initial_capital: float,
    net_pnl: float,
    fees: float,
    equity_curve: Iterable[tuple[int, float]] | None,
) -> dict[str, Any]:
    """Build the ``performance`` section of a report."""
    fill_list = list(fills)
    trades = reconstruct_trades(fill_list, orders)
    stats = trade_statistics(trades)
    curve = list(equity_curve or [])
    drawdown = drawdown_statistics(curve)
    turnover = sum(
        abs(
            _number(_as_dict(fill).get("quantity"))
            * _number(_as_dict(fill).get("price"))
        )
        for fill in fill_list
    )
    by_side: dict[str, dict[str, Any]] = {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for trade in trades:
        for key, bucket in (
            (trade.side, by_side),
            (trade.symbol or "unknown", by_symbol),
        ):
            entry = bucket.setdefault(key, {"trades": 0, "net_pnl": 0.0, "wins": 0})
            entry["trades"] += 1
            entry["net_pnl"] += trade.net_pnl
            entry["wins"] += 1 if trade.net_pnl > 0 else 0
    for bucket in (by_side, by_symbol):
        for entry in bucket.values():
            entry["win_rate_percent"] = (
                100.0 * entry["wins"] / entry["trades"] if entry["trades"] else 0.0
            )
            entry.pop("wins", None)
    open_position_pnl = net_pnl - stats["net_pnl"]
    if abs(open_position_pnl) < 1e-9:
        open_position_pnl = 0.0
    return {
        **stats,
        **drawdown,
        **sample_curve(curve),
        "initial_capital": initial_capital,
        "account_net_pnl": net_pnl,
        "open_position_pnl": open_position_pnl,
        "return_percent": 100.0 * net_pnl / initial_capital if initial_capital else 0.0,
        "fees": fees,
        "fee_ratio_percent": (
            100.0 * fees / abs(stats["gross_profit"]) if stats["gross_profit"] else None
        ),
        "turnover": turnover,
        "turnover_ratio": turnover / initial_capital if initial_capital else 0.0,
        "by_side": dict(sorted(by_side.items())),
        "by_symbol": dict(sorted(by_symbol.items())),
        "assumptions": [
            "netting FIFO par instrument, frais d'entree repartis au prorata",
            "les statistiques de trades ne portent que sur les positions closes",
            "le drawdown est calcule sur l'equity mark-to-market en cloture de bougie",
            "aucune hypothese de reinvestissement ni de levier supplementaire",
        ],
    }


def performance_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return the stored performance section, or rebuild a conservative view."""
    section = report.get("performance")
    if isinstance(section, dict):
        return section
    account = report.get("account") if isinstance(report.get("account"), dict) else {}
    trades = trades_from_report(report)
    stats = trade_statistics(trades)
    initial = _number(account.get("initial_capital"))
    net_pnl = _number(account.get("net_pnl"))
    open_position_pnl = net_pnl - stats["net_pnl"]
    if abs(open_position_pnl) < 1e-9:
        open_position_pnl = 0.0
    return {
        **stats,
        **drawdown_statistics([]),
        **sample_curve([]),
        "initial_capital": initial,
        "account_net_pnl": net_pnl,
        "open_position_pnl": open_position_pnl,
        "return_percent": 100.0 * net_pnl / initial if initial else 0.0,
        "fees": _number(account.get("fees")),
        "fee_ratio_percent": None,
        "turnover": 0.0,
        "turnover_ratio": 0.0,
        "by_side": {},
        "by_symbol": {},
        "assumptions": ["section performance absente : reconstruction partielle"],
    }
