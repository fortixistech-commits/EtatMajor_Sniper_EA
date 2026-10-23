"""Mesure de performance du moteur de replay (MISSION 0 - preuve de langage).

Objectif : documenter, par la mesure, si un langage natif (Rust, Numba) ou
un composant MQL5 serait justifié. Le cahier des routes impose de ne
recourir à une optimisation qu'après **mesure** d'un goulot d'étranglement
réel.

La mesure porte sur quatre profils :

1. le dataset d'exemple (240 bougies) ;
2. un volume de travail (5 000 bougies) ;
3. un volume important (20 000 bougies) ;
4. un volume de campagne (100 000 bougies).

Le coût par bougie du moteur de replay est linéaire depuis la mise en cache
des instantanés d'un portefeuille à plat (Phase 7). Le Sniper Engine n'est
pas inclus dans ce profil : son Market Intelligence recalcule ses indicateurs
sur tout l'historique visible à chaque bougie, ce qui reste quadratique et
doit être optimisé avant un benchmark de campagne (limite documentée).

Pour chaque profil : temps d'exécution, débit (bougies/s), temps de
chargement des données, mémoire maximale (RSS).

Usage::

    python scripts/benchmark_replay.py --output docs/audit/evidence
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
try:
    import resource
except ImportError:  # Windows
    resource = None
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


def rss_mb() -> float | None:
    """Pic de memoire residente (portable Linux/macOS/Windows)."""
    if resource is not None:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel32.GetCurrentProcess()
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
    return None


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
    rss = rss_mb()
    return {
        "bars": bars,
        "build_seconds": round(build_seconds, 4),
        "replay_seconds": round(elapsed, 4),
        "bars_per_second": int(bars / elapsed) if elapsed else None,
        "microseconds_per_bar": round(elapsed / bars * 1e6, 3),
        "orders": result.report["orders"]["total"],
        "executions": result.report["executions"]["total"],
        "max_rss_mb": round(rss, 1) if rss is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/audit/evidence")
    parser.add_argument(
        "--profiles",
        default="240,5000,20000,100000",
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
            + (
                f"rss {profile['max_rss_mb']:>7.1f} MB"
                if profile["max_rss_mb"] is not None
                else "rss      n/a"
            )
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "profiles": results,
    }
    (output_dir / "benchmark.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"evidence written: {output_dir / 'benchmark.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
