"""Command line interface of the ETAT-MAJOR platform.

The CLI is intentionally thin: it wires the configuration, the data loader, the
strategy and the replay engine, and prints the resulting report. It contains no
trading logic and cannot reach a broker.

Examples
--------
::

    python -m etatmajor.cli validate --data data/sample_eurusd_1m.csv
    python -m etatmajor.cli replay --data data/sample_eurusd_1m.csv \\
        --config configs/simulation.toml --report artifacts/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.config import AppConfig, SimulationConfig, load_config
from .core.errors import EtatMajorError
from .data.loader import load_csv
from .replay.engine import ReplayEngine
from .reporting.report import render_summary, write_report
from .strategies.demo import DemoLifecycleStrategy


def _build_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        config = load_config(args.config)
        if args.symbol:
            config = AppConfig(
                simulation=SimulationConfig(
                    symbol=args.symbol,
                    timeframe=config.simulation.timeframe,
                    initial_capital=config.simulation.initial_capital,
                    currency=config.simulation.currency,
                    end_of_replay_policy=config.simulation.end_of_replay_policy,
                    seed=config.simulation.seed,
                ),
                execution=config.execution,
                risk=config.risk,
                source_path=config.source_path,
            )
        return config
    return AppConfig()


def _load_dataset(args: argparse.Namespace, config: AppConfig):
    return load_csv(
        path=args.data,
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        timeframe_ns=config.simulation.timeframe_ns,
        timestamp_unit=args.timestamp_unit,
    )


def cmd_validate(args: argparse.Namespace) -> int:
    config = _build_config(args)
    dataset = _load_dataset(args, config)
    print(json.dumps(dataset.quality.to_dict(), indent=2))
    print(f"Dataset OK: {len(dataset)} bar(s), fingerprint {dataset.fingerprint()}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    config = _build_config(args)
    dataset = _load_dataset(args, config)
    strategy = DemoLifecycleStrategy(
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        quantity=args.quantity,
        entry_index=args.entry_index,
        exit_index=args.exit_index,
        place_pending_limit=args.pending_limit,
    )
    engine = ReplayEngine(dataset=dataset, config=config, strategy=strategy)
    result = engine.run()

    if args.report:
        write_report(result.report, args.report)
        print(f"Report written to {args.report}")
    if args.journal:
        result.journal.write_jsonl(args.journal)
        print(f"Journal written to {args.journal}")

    print(render_summary(result.report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="etatmajor",
        description=(
            "ETAT-MAJOR SNIPER EA - market simulation laboratory. "
            "This tool never sends a real order."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--data", required=True, help="path to the OHLC CSV file")
        sp.add_argument("--config", default=None, help="path to the TOML configuration")
        sp.add_argument("--symbol", default=None, help="override the instrument symbol")
        sp.add_argument(
            "--timestamp-unit",
            default="s",
            choices=["s", "ms", "us", "ns"],
            help="unit of numeric timestamps in the CSV (default: s)",
        )

    validate = sub.add_parser("validate", help="validate a market data file")
    add_common(validate)
    validate.set_defaults(func=cmd_validate)

    replay = sub.add_parser("replay", help="run a deterministic historical replay")
    add_common(replay)
    replay.add_argument("--report", default=None, help="path of the JSON report")
    replay.add_argument("--journal", default=None, help="path of the JSONL journal")
    replay.add_argument("--quantity", type=float, default=10_000.0)
    replay.add_argument("--entry-index", type=int, default=2)
    replay.add_argument("--exit-index", type=int, default=6)
    replay.add_argument(
        "--pending-limit",
        action="store_true",
        help="submit an extra unfillable limit order (pending policy test)",
    )
    replay.set_defaults(func=cmd_replay)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except EtatMajorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        issues = getattr(exc, "issues", None)
        if issues:
            print("issues:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
