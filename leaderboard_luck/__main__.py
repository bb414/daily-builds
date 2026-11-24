"""Command-line entry point: ``python -m leaderboard_luck <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .design import design_csv, design_html, design_report
from .model import DEFAULTS, RULES, simulate, skill_by_length
from .report import sample_report, simulate_report

FLAGS = {
    "teams": ("--teams", int), "days": ("--days", int), "skillSpread": ("--skill-spread", float),
    "fieldVol": ("--field-vol", float), "gamblers": ("--gamblers", float),
    "gamblerMultiple": ("--gambler-multiple", float), "correlation": ("--correlation", float),
    "drawdownLimit": ("--drawdown-limit", float), "yourSharpe": ("--your-sharpe", float),
    "yourVol": ("--your-vol", float), "catchUpVol": ("--catch-up-vol", float),
    "checkpoint": ("--checkpoint", float), "rivalsCatchUp": ("--rivals-catch-up", float),
    "sims": ("--sims", int), "seed": ("--seed", int),
}


def add_settings(parser: argparse.ArgumentParser) -> None:
    for key, (flag, kind) in FLAGS.items():
        parser.add_argument(flag, dest=key, type=kind, default=DEFAULTS[key], help=f"default {DEFAULTS[key]}")
    parser.add_argument("--rule", choices=RULES, default=DEFAULTS["rule"], help="how teams are ranked")
    parser.add_argument("--fat-tails", dest="fatTails", action="store_true", help="add occasional big-move days")
    parser.add_argument("--catch-up", dest="catchUp", action="store_true",
                        help="your team goes for broke if outside the top 3 at the checkpoint")


def settings(args: argparse.Namespace) -> dict:
    p = {key: getattr(args, key) for key in FLAGS}
    p["rule"] = args.rule
    p["fatTails"] = args.fatTails
    p["catchUp"] = args.catchUp
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m leaderboard_luck",
                                     description="How much of a trading-challenge leaderboard is skill?")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("simulate", help="simulate many challenges and report your team's chances")
    add_settings(s)
    s.add_argument("--json", action="store_true", help="print the full result as JSON")
    c = sub.add_parser("sample", help="show one simulated challenge in full")
    add_settings(c)
    c.add_argument("--index", type=int, default=0, help="which challenge, counting from 0 (default 0)")
    d = sub.add_parser("design", help="compare scoring rules and challenge lengths (the organiser's view)")
    add_settings(d)
    d.add_argument("--sims-each", type=int, default=400, help="challenges per rule and length (default 400)")
    d.add_argument("--workers", type=int, default=os.cpu_count() or 1,
                   help="parallel processes (default: one per CPU); the answer does not change")
    d.add_argument("--csv", metavar="PATH", help="also write the table to a CSV file")
    d.add_argument("--html", metavar="PATH", help="also write a self-contained HTML report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        p = settings(args)
        if args.command == "simulate":
            r = simulate(p)
            print(json.dumps(r, indent=2) if args.json else simulate_report(r))
        elif args.command == "sample":
            if args.index < 0:
                raise ValueError("--index cannot be negative")
            print(sample_report(p, args.index))
        elif args.command == "design":
            if args.sims_each < 1 or args.workers < 1:
                raise ValueError("--sims-each and --workers must be at least 1")
            from .model import normalise
            params = normalise(p)
            rows = skill_by_length(params, args.sims_each, args.workers)
            print(design_report(params, rows, args.sims_each))
            if args.csv:
                Path(args.csv).write_text(design_csv(rows), encoding="utf-8")
                print(f"\nWrote {args.csv}")
            if args.html:
                Path(args.html).write_text(design_html(params, rows, args.sims_each), encoding="utf-8")
                print(f"\nWrote {args.html}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
