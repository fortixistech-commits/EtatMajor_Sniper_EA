"""Generate the synthetic sample dataset shipped with the repository.

The dataset is fully synthetic: no broker export, no third-party data, no
licence constraint. It is generated from a fixed seed so that the file can be
reproduced byte for byte.

Usage::

    python scripts/generate_sample_data.py --output data/sample_eurusd_1m.csv
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_BARS = 240
DEFAULT_SEED = 20260105
START = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def generate(bars: int, seed: int, start: datetime, price: float) -> list[dict]:
    """Build a deterministic OHLC series with trends and ranges."""
    rng = random.Random(seed)
    rows: list[dict] = []
    current = price
    for index in range(bars):
        # Regime alternation: drift, then range, then drift. Deterministic.
        phase = (index // 40) % 3
        if phase == 0:
            drift = 0.00012
        elif phase == 1:
            drift = 0.0
        else:
            drift = -0.00009
        open_ = current
        close = open_ + drift + rng.uniform(-0.00035, 0.00035)
        high = max(open_, close) + rng.uniform(0.00005, 0.00040)
        low = min(open_, close) - rng.uniform(0.00005, 0.00040)
        rows.append(
            {
                "timestamp": (start + timedelta(minutes=index)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "open": round(open_, 5),
                "high": round(high, 5),
                "low": round(low, 5),
                "close": round(close, 5),
                "volume": float(100 + rng.randint(0, 900)),
            }
        )
        current = close
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="data/sample_eurusd_1m.csv",
        help="path of the generated CSV file",
    )
    parser.add_argument("--bars", type=int, default=DEFAULT_BARS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--start-price", type=float, default=1.10000)
    args = parser.parse_args()

    rows = generate(args.bars, args.seed, START, args.start_price)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for row in rows:
            writer.writerow(
                [
                    row["timestamp"],
                    f"{row['open']:.5f}",
                    f"{row['high']:.5f}",
                    f"{row['low']:.5f}",
                    f"{row['close']:.5f}",
                    f"{row['volume']:.0f}",
                ]
            )
    print(f"{len(rows)} bars written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
