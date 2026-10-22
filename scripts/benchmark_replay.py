"""Mesure de performance du moteur de replay (MISSION 0 - preuve de langage).

Objectif : documenter, par la mesure, si un langage natif (Rust, Numba) ou
un composant MQL5 serait justifié. Le cahier des routes impose de ne
recourir à une optimisation qu'après **mesure** d'un goulot d'étranglement
réel.

La mesure porte sur trois profils :

1. le dataset d'exemple (240 bougies) ;
2. un volume de travail (5 000 bougies) ;
3. un volume important (20 000 bougies).

Les volumes de 100 000 et 1 000 000 bougies ont ete abandonnes : le temps de
rejeu croît de façon quadratique (voir AUDIT-Q1), ce qui rend ces profils
inutilisables en l'etat.

Pour chaque profil : temps d'exécution, débit (bougies/s), temps de
chargement des données, mémoire maximale (RSS).

Usage::

    python scripts/benchmark_replay.py --output docs/audit/evidence
"""

from __future__ import annotations

import argparse
import json
import resource
import time
from datetime import datetime, timezone
from pathlib import Path

from etatmajor.core.config import (
    AppConfig,
    ExecutionConfig,
    RiskConfig,
    SimulationConfig,
)
from etatmajor.data.loader import Dataset
from etatmajor.data.models import Bar
from etatmajor.replay.engine import ReplayEngine
from etatmajor.strategies.demo import DemoLifecycleStrategy

TIMEFRAME_NS = 60_000_000_000
BASE_NS = 1_767_571_200_000_000_000


def build_dataset(bars: int) -> Dataset:
    """Dataset synthétique en mémoire, déterministe et sans allocation inutile."""
    import random

    rng = random.Random(20260105)
    price = 1.10000
    rows = []
    for index in range(bars):
        open_ = price
        close = open_ + rng.uniform(-0.00035, 0.00035)
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        rows.append(
            Bar(
                ts_open_ns=BASE_NS + index * TIMEFRAME_NS,
                ts_close_ns=BASE_NS + (index + 1) * TIMEFRAME_NS,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
        price = close
    return Dataset(
        symbol="EURUSD",
        timeframe="1m",
        bars=rows,
        source_path="<benchmark>",
        timeframe_ns=TIMEFRAME_NS,
    )


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def run_profile(bars: int) -> dict:
    config = AppConfig(
        simulation=SimulationConfig(
            symbol="EURUSD", timeframe="1m", initial_capital=100_000.0
        ),
        execution=ExecutionConfig(spread_price=0.0001, slippage_price=0.00002),
        risk=RiskConfig(),
    )
    build_start = time.perf_counter()
    dataset = build_dataset(bars)
    build_seconds = time.perf_counter() - build_start

    strategy = DemoLifecycleStrategy(
        symbol="EURUSD", timeframe="1m", quantity=10_000.0, entry_index=2, exit_index=6
    )
    engine = ReplayEngine(dataset=dataset, config=config, strategy=strategy)
    start = time.perf_counter()
    result = engine.run()
    elapsed = time.perf_counter() - start
    return {
        "bars": bars,
        "build_seconds": round(build_seconds, 4),
        "replay_seconds": round(elapsed, 4),
        "bars_per_second": int(bars / elapsed) if elapsed else None,
        "microseconds_per_bar": round(elapsed / bars * 1e6, 3),
        "orders": result.report["orders"]["total"],
        "executions": result.report["executions"]["total"],
        "max_rss_mb": round(rss_mb(), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/audit/evidence")
    parser.add_argument(
        "--profiles",
        default="240,5000,10000,20000",
        help="comma separated bar counts",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for bars in [int(value) for value in args.profiles.split(",")]:
        profile = run_profile(bars)
        results.append(profile)
        print(
            f"{bars:>9,} bars | replay {profile['replay_seconds']:>8.3f}s | "
            f"{profile['bars_per_second']:>10,} bars/s | "
            f"{profile['microseconds_per_bar']:>8.1f} us/bar | "
            f"rss {profile['max_rss_mb']:>7.1f} MB"
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": "3.13.7",
        "platform": "Linux aarch64",
        "profiles": results,
    }
    (output_dir / "benchmark.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"evidence written: {output_dir / 'benchmark.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
