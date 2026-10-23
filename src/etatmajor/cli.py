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

from .challenge.engine import ChallengeEngine
from .challenge.profile import ChallengeProfile
from .core.config import AppConfig, SimulationConfig, load_config
from .core.errors import ConfigurationError, EtatMajorError
from .data.instruments import InstrumentCatalog
from .data.loader import load_csv
from .data.provenance import load_provenance
from .evaluation.robustness import build_robustness
from .evaluation.selection import rank_candidates
from .evaluation.validation import (
    evaluate_validation,
    load_criteria,
    render_dossier,
)
from .replay.engine import ReplayEngine
from .reporting.cockpit import (
    build_cockpit,
    load_journal,
    load_report,
    render_console,
    write_dashboard,
    write_snapshot,
)
from .reporting.metrics import trades_from_report
from .reporting.report import render_summary, write_report
from .sniper.settings import build_engine
from .sniper.strategy import SniperStrategy
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
                    mode=config.simulation.mode,
                    seed=config.simulation.seed,
                ),
                execution=config.execution,
                risk=config.risk,
                sniper=config.sniper,
                source_path=config.source_path,
            )
        return config
    return AppConfig()


def _load_dataset(args: argparse.Namespace, config: AppConfig):
    catalog = (
        InstrumentCatalog.load(args.instrument_catalog)
        if args.instrument_catalog
        else None
    )
    provenance = (
        load_provenance(args.provenance) if args.provenance else None
    )
    return load_csv(
        path=args.data,
        symbol=config.simulation.symbol,
        timeframe=config.simulation.timeframe,
        timeframe_ns=config.simulation.timeframe_ns,
        timestamp_unit=args.timestamp_unit,
        catalog=catalog,
        broker_id=args.broker_id,
        provenance=provenance,
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

    instrument = None
    broker_spec = None
    if args.instrument_catalog:
        catalog = InstrumentCatalog.load(args.instrument_catalog)
        instrument = catalog.require(config.simulation.symbol, args.broker_id)
        if args.broker_id:
            broker_spec = catalog.broker_symbol(
                args.broker_id, config.simulation.symbol
            )

    challenge = None
    if args.challenge_profile:
        profile = ChallengeProfile.from_toml(args.challenge_profile)
        # Une simulation de challenge se fait sur le compte du challenge :
        # le capital simule est celui du profil, sauf override explicite.
        capital = (
            args.capital
            if args.capital is not None
            else profile.initial_capital
        )
        if args.capital is None and abs(
            capital - config.simulation.initial_capital
        ) > 1e-9:
            print(
                f"note: simulation capital set to {capital:.2f} "
                f"(challenge profile reference capital), overriding "
                f"{config.simulation.initial_capital:.2f}"
            )
        config = AppConfig(
            simulation=SimulationConfig(
                symbol=config.simulation.symbol,
                timeframe=config.simulation.timeframe,
                initial_capital=capital,
                currency=config.simulation.currency,
                end_of_replay_policy=config.simulation.end_of_replay_policy,
                mode=config.simulation.mode,
                seed=config.simulation.seed,
            ),
            execution=config.execution,
            risk=config.risk,
            sniper=config.sniper,
            source_path=config.source_path,
        )
        challenge = ChallengeEngine(
            profile,
            initial_capital=capital,
            reset_hour_utc=args.challenge_reset_hour,
        )
    if args.strategy == "sniper":
        sniper = build_engine(
            config.simulation.symbol,
            config.simulation.timeframe,
            config.sniper,
            instrument=instrument,
            broker_spec=broker_spec,
            account_currency=config.simulation.currency,
            data_quality=dataset.quality,
        )
        strategy = SniperStrategy(
            symbol=config.simulation.symbol,
            timeframe=config.simulation.timeframe,
            engine=sniper,
        )
    else:
        strategy = DemoLifecycleStrategy(
            symbol=config.simulation.symbol,
            timeframe=config.simulation.timeframe,
            quantity=args.quantity,
            entry_index=args.entry_index,
            exit_index=args.exit_index,
            place_pending_limit=args.pending_limit,
        )
    engine = ReplayEngine(
        dataset=dataset,
        config=config,
        strategy=strategy,
        challenge=challenge,
        instrument=instrument,
        broker_spec=broker_spec,
    )
    result = engine.run()

    if args.report:
        write_report(result.report, args.report)
        print(f"Report written to {args.report}")
    if args.journal:
        result.journal.write_jsonl(args.journal)
        print(f"Journal written to {args.journal}")

    print(render_summary(result.report))
    return 0


def cmd_cockpit(args: argparse.Namespace) -> int:
    """Build an offline operator view from a report and its journal."""
    report = load_report(args.report)
    entries = load_journal(args.journal) if args.journal else None
    view = build_cockpit(report, entries, title=args.title)

    if args.html:
        write_dashboard(view, args.html)
        print(f"Cockpit written to {args.html}")
    if args.json:
        write_snapshot(view, args.json)
        print(f"Cockpit snapshot written to {args.json}")

    print(render_console(view))
    if not view.ok:
        return 3
    if args.strict and view.warnings:
        return 3
    return 0


def _write_json(payload: dict, path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Build a validation dossier from a report and explicit criteria."""
    report = load_report(args.report)
    trades = trades_from_report(report)
    robustness = build_robustness(
        trades,
        iterations=args.iterations,
        seed=args.seed,
        train_ratio=args.train_ratio,
        validation_ratio=args.validation_ratio,
    )
    criteria = load_criteria(args.criteria) if args.criteria else None
    dossier = evaluate_validation(report, robustness, criteria)
    if args.json:
        _write_json(dossier, args.json)
        print(f"Dossier written to {args.json}")
    print(render_dossier(dossier))
    if dossier["verdict"] == "PASS":
        return 0
    if dossier["verdict"] == "FAIL":
        return 4
    return 5


def _parse_candidate(value: str) -> tuple[str, str]:
    if "=" in value:
        label, path = value.split("=", 1)
        if label.strip() and path.strip():
            return label.strip(), path.strip()
    raise argparse.ArgumentTypeError(
        "candidate must use LABEL=PATH, for example demo=artifacts/report.json"
    )


def render_selection(selection: dict) -> str:
    lines = [
        "=" * 72,
        "ETAT-MAJOR SNIPER EA - candidate selection (simulation only)",
        "=" * 72,
        f"Selected     : {selection['selected'] or 'none'}",
        f"Policy       : {selection['policy']}",
        "-" * 72,
    ]
    for row in selection["candidates"]:
        lines.append(
            f"{row['rank']}. {row['label']:<20} {row['verdict']:<10} "
            f"p05={row['p05_net_pnl']:+.4f} expectancy={row['expectancy']:+.4f}"
        )
    lines.extend(["=" * 72, "Attention : " + selection["warning"]])
    return "\n".join(lines)


def cmd_select(args: argparse.Namespace) -> int:
    """Rank candidate reports after the same validation protocol."""
    criteria = load_criteria(args.criteria)
    candidates = []
    labels: set[str] = set()
    for raw in args.report:
        label, path = raw
        if label in labels:
            raise ConfigurationError(f"duplicate candidate label: {label}")
        labels.add(label)
        report = load_report(path)
        trades = trades_from_report(report)
        robustness = build_robustness(
            trades,
            iterations=args.iterations,
            seed=args.seed,
            train_ratio=args.train_ratio,
            validation_ratio=args.validation_ratio,
        )
        dossier = evaluate_validation(report, robustness, criteria)
        candidates.append(
            {"label": label, "dossier": dossier, "robustness": robustness}
        )
    selection = rank_candidates(candidates)
    if args.json:
        _write_json(selection, args.json)
        print(f"Selection written to {args.json}")
    print(render_selection(selection))
    return 0 if selection["selected"] else 4


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
        sp.add_argument(
            "--instrument-catalog",
            default=None,
            help="path to the versioned instrument catalogue (TOML)",
        )
        sp.add_argument(
            "--broker-id",
            default=None,
            help="broker mapping to use from the instrument catalogue",
        )
        sp.add_argument(
            "--provenance",
            default=None,
            help="path to a data provenance file (TOML)",
        )

    validate = sub.add_parser("validate", help="validate a market data file")
    add_common(validate)
    validate.set_defaults(func=cmd_validate)

    replay = sub.add_parser("replay", help="run a deterministic historical replay")
    add_common(replay)
    replay.add_argument("--report", default=None, help="path of the JSON report")
    replay.add_argument("--journal", default=None, help="path of the JSONL journal")
    replay.add_argument(
        "--strategy",
        choices=["demo", "sniper"],
        default="demo",
        help=(
            "strategy to replay: demo lifecycle (default) or the Sniper Engine "
            "pipeline (data, regime, doctrine, planner)"
        ),
    )
    replay.add_argument("--quantity", type=float, default=10_000.0)
    replay.add_argument("--entry-index", type=int, default=2)
    replay.add_argument("--exit-index", type=int, default=6)
    replay.add_argument(
        "--challenge-profile",
        default=None,
        help="path of a challenge profile (TOML) to simulate against",
    )
    replay.add_argument(
        "--capital",
        type=float,
        default=None,
        help="override the simulated capital (default: the challenge profile capital)",
    )
    replay.add_argument(
        "--challenge-reset-hour",
        type=int,
        default=0,
        help="hour of the daily reset (UTC) used when the profile does not document it",
    )
    replay.add_argument(
        "--pending-limit",
        action="store_true",
        help="submit an extra unfillable limit order (pending policy test)",
    )
    replay.set_defaults(func=cmd_replay)

    cockpit = sub.add_parser(
        "cockpit",
        help="build an offline operator view from a report and its journal",
    )
    cockpit.add_argument("--report", required=True, help="path of the JSON report")
    cockpit.add_argument(
        "--journal",
        default=None,
        help="path of the JSONL journal (strongly recommended)",
    )
    cockpit.add_argument(
        "--html",
        default=None,
        help="write the standalone HTML cockpit to this path",
    )
    cockpit.add_argument(
        "--json",
        default=None,
        help="write the machine-readable cockpit snapshot to this path",
    )
    cockpit.add_argument(
        "--title",
        default="ETAT-MAJOR cockpit",
        help="dashboard title (default: ETAT-MAJOR cockpit)",
    )
    cockpit.add_argument(
        "--strict",
        action="store_true",
        help="return a non-zero status when a warning is present",
    )
    cockpit.set_defaults(func=cmd_cockpit)

    def add_analysis(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--criteria",
            default=None,
            help="TOML file declaring the acceptance criteria before the test",
        )
        sp.add_argument(
            "--iterations",
            type=int,
            default=1_000,
            help="Monte-Carlo bootstrap iterations (default: 1000)",
        )
        sp.add_argument(
            "--seed",
            type=int,
            default=42,
            help="deterministic Monte-Carlo seed (default: 42)",
        )
        sp.add_argument(
            "--train-ratio",
            type=float,
            default=0.60,
            help="chronological training share (default: 0.60)",
        )
        sp.add_argument(
            "--validation-ratio",
            type=float,
            default=0.20,
            help="chronological validation share (default: 0.20)",
        )
        sp.add_argument("--json", default=None, help="write the JSON result here")

    evaluate = sub.add_parser(
        "evaluate",
        help="build a validation dossier with robustness diagnostics",
    )
    evaluate.add_argument("--report", required=True, help="path of the JSON report")
    add_analysis(evaluate)
    evaluate.set_defaults(func=cmd_evaluate)

    select = sub.add_parser(
        "select",
        help="rank candidate reports under one validation protocol",
    )
    select.add_argument(
        "--report",
        action="append",
        required=True,
        type=_parse_candidate,
        metavar="LABEL=PATH",
        help="candidate report (repeat for each candidate)",
    )
    add_analysis(select)
    select.set_defaults(func=cmd_select)

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
