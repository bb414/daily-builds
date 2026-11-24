"""Command-line entry point: ``python -m reliance_lab <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .html_report import sweep_html
from .model import DEFAULTS, POLICIES, analyse, per_100
from .report import model_report
from .sweep import run_sweep, summarise, sweep_csv, sweep_report

PARAM_FLAGS = {
    "human": "--human", "ai": "--ai", "overlap": "--overlap", "aiSignal": "--ai-signal",
    "humanSignal": "--human-signal", "aiBias": "--ai-bias", "humanBias": "--human-bias",
    "threshold": "--threshold", "deferRate": "--defer-rate",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reliance_lab",
        description="When can a person reviewing an AI's work beat both of them alone?")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("model", help="evaluate every reliance rule for one set of assumptions")
    for key, flag in PARAM_FLAGS.items():
        m.add_argument(flag, dest=key, type=float, default=DEFAULTS[key],
                       help=f"default {DEFAULTS[key]}")
    m.add_argument("--rule", choices=POLICIES, default="surer",
                   help="rule for the 'out of every 100 cases' breakdown (default surer)")
    m.add_argument("--json", action="store_true", help="print the full result as JSON")

    w = sub.add_parser("sweep", help="run the model over a grid of assumptions and summarise where pairing pays")
    w.add_argument("--margin", type=float, default=0.5,
                   help="points above the better solo that count as beating both (default 0.5)")
    w.add_argument("--csv", metavar="PATH", help="also write every combination to a CSV file")
    w.add_argument("--html", metavar="PATH", help="also write a self-contained HTML report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "model":
        params = {key: getattr(args, key) for key in PARAM_FLAGS}
        try:
            if args.json:
                result = analyse(params)
                result["per100"] = {rule: per_100(params, rule)["counts"] for rule in POLICIES}
                print(json.dumps(result, indent=2))
            else:
                print(model_report(params, args.rule))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "sweep":
        if args.margin < 0:
            print("error: --margin cannot be negative", file=sys.stderr)
            return 2
        rows = run_sweep()
        summary = summarise(rows, args.margin / 100)
        print(sweep_report(summary))
        if args.csv:
            Path(args.csv).write_text(sweep_csv(rows), encoding="utf-8")
            print(f"\nWrote {len(rows)} rows to {args.csv}")
        if args.html:
            Path(args.html).write_text(sweep_html(summary), encoding="utf-8")
            print(f"\nWrote {args.html}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
