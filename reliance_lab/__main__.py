"""Command-line entry point: ``python -m reliance_lab <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model import DEFAULTS, analyse
from .html_report import class_html
from .report import class_csv, class_report, model_report, session_report
from .sessions import SessionError, load_session
from .sweep import run_sweep, summarise, sweep_csv, sweep_report
from .synthetic import MISTAKES, write_class

PARAM_FLAGS = {
    "human": "--human", "ai": "--ai", "overlap": "--overlap", "aiSignal": "--ai-signal",
    "humanSignal": "--human-signal", "aiBias": "--ai-bias", "humanBias": "--human-bias",
    "threshold": "--threshold", "deferRate": "--defer-rate",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reliance_lab",
        description="When does a person reviewing AI advice beat both of them alone?")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("model", help="evaluate every reliance rule for one set of assumptions")
    for key, flag in PARAM_FLAGS.items():
        m.add_argument(flag, dest=key, type=float, default=DEFAULTS[key],
                       help=f"default {DEFAULTS[key]}")
    m.add_argument("--json", action="store_true", help="print the full result as JSON")

    s = sub.add_parser("score", help="score session files downloaded from the browser app")
    s.add_argument("files", nargs="+", help="one or more session .json files")
    s.add_argument("--threshold", type=float, default=0.8,
                   help="confidence bar for the 'follow when sure' replay (default 0.8)")
    s.add_argument("--csv", metavar="PATH", help="also write one row per session to a CSV file")
    s.add_argument("--html", metavar="PATH", help="also write a self-contained HTML class report")

    w = sub.add_parser("sweep", help="run the model over a grid of assumptions and summarise where pairing pays")
    w.add_argument("--margin", type=float, default=0.5,
                   help="points above the better solo that count as beating both (default 0.5)")
    w.add_argument("--csv", metavar="PATH", help="also write every combination to a CSV file")

    d = sub.add_parser("demo-class", help="write a synthetic class of session files")
    d.add_argument("--out", default="examples/sessions", help="folder to write to")
    d.add_argument("--participants", type=int, default=24)
    d.add_argument("--cases", type=int, default=20)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--mistakes", choices=MISTAKES, default="random",
                   help="where the advisor's mistakes fall (default random)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "model":
        params = {key: getattr(args, key) for key in PARAM_FLAGS}
        try:
            if args.json:
                print(json.dumps(analyse(params), indent=2))
            else:
                print(model_report(params))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "score":
        try:
            sessions = [load_session(f) for f in args.files]
        except (OSError, SessionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        for session in sessions:
            print(session_report(session, args.threshold))
            print()
        if len(sessions) > 1:
            print(class_report(sessions))
        if args.csv:
            Path(args.csv).write_text(class_csv(sessions), encoding="utf-8")
            print(f"\nWrote {args.csv}")
        if args.html:
            Path(args.html).write_text(class_html(sessions), encoding="utf-8")
            print(f"\nWrote {args.html}")
        return 0
    if args.command == "sweep":
        rows = run_sweep()
        print(sweep_report(summarise(rows, args.margin / 100)))
        if args.csv:
            Path(args.csv).write_text(sweep_csv(rows), encoding="utf-8")
            print(f"\nWrote {len(rows)} rows to {args.csv}")
        return 0
    if args.command == "demo-class":
        if args.participants < 1 or args.cases < 2:
            print("error: need at least 1 participant and 2 cases", file=sys.stderr)
            return 2
        paths = write_class(args.out, args.participants, args.seed, args.cases, args.mistakes)
        print(f"Wrote {len(paths)} synthetic sessions to {args.out}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
