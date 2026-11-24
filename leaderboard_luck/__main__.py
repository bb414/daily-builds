"""Command-line entry point: ``python -m leaderboard_luck <command>``."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

from .design import design_csv, design_html, design_report
from .model import DEFAULTS, RANGES, RULES, clamp, normalise, simulate, skill_by_length
from .report import sample_report, simulate_report

FLAGS = {
    "teams": ("--teams", int, "teams in the challenge, including yours"),
    "days": ("--days", int, "length of the challenge in trading days (5 a week, 250 a year)"),
    "skillSpread": ("--skill-spread", float, "spread of rivals' true Sharpe ratios around zero"),
    "fieldVol": ("--field-vol", float, "typical rival volatility as a fraction, 0.2 meaning 20 per cent a year"),
    "gamblers": ("--gamblers", float, "share of rivals who are gamblers, as a fraction"),
    "gamblerMultiple": ("--gambler-multiple", float, "how many times the typical risk a gambler runs"),
    "correlation": ("--correlation", float, "correlation of daily returns between teams"),
    "drawdownLimit": ("--drawdown-limit", float, "fall from a peak that knocks a team out under the drawdown rule"),
    "yourSharpe": ("--your-sharpe", float, "your team's true Sharpe ratio"),
    "yourVol": ("--your-vol", float, "your team's volatility, as a fraction"),
    "catchUpVol": ("--catch-up-vol", float, "your volatility after going for broke, as a fraction"),
    "checkpoint": ("--checkpoint", float, "how far through the challenge the checkpoint falls, as a fraction"),
    "rivalsCatchUp": ("--rivals-catch-up", float, "share of steady rivals who go for broke when behind"),
    "sims": ("--sims", int, "how many challenges to simulate"),
    "seed": ("--seed", int, "luck number: the same number always gives the same results"),
}

# Settings that a command does not use, so it does not offer them.
UNUSED = {"simulate": set(), "sample": {"sims"}, "design": {"sims", "days", "rule"}}


def num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def add_settings(parser: argparse.ArgumentParser, command: str) -> None:
    for key, (flag, kind, text) in FLAGS.items():
        if key in UNUSED[command]:
            continue
        lo, hi, _ = RANGES[key]
        parser.add_argument(flag, dest=key, type=kind, default=DEFAULTS[key], metavar="N",
                            help=f"{text} ({num(lo)} to {num(hi)}; default {num(DEFAULTS[key])})")
    if "rule" not in UNUSED[command]:
        parser.add_argument("--rule", choices=RULES, default=DEFAULTS["rule"],
                            help="how teams are ranked (default return)")
    parser.add_argument("--fat-tails", dest="fatTails", action="store_true", help="add occasional big-move days")
    parser.add_argument("--catch-up", dest="catchUp", action="store_true",
                        help="your team goes for broke if outside the top 3 at the checkpoint")


def settings(args: argparse.Namespace) -> dict:
    p = {key: getattr(args, key, DEFAULTS[key]) for key in FLAGS}
    p["rule"] = getattr(args, "rule", DEFAULTS["rule"])
    p["fatTails"] = args.fatTails
    p["catchUp"] = args.catchUp
    return p


def warn_if_clamped(p: dict) -> None:
    """Out-of-range settings are pulled back to the nearest allowed value, as the app's sliders are."""
    for key, (flag, _, _) in FLAGS.items():
        lo, hi, _ = RANGES[key]
        v = p[key]
        if isinstance(v, (int, float)) and math.isfinite(v) and not lo <= v <= hi:
            print(f"note: {flag} {num(v)} is outside {num(lo)} to {num(hi)}, so {num(clamp(v, lo, hi))} was used",
                  file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m leaderboard_luck",
                                     description="How much of a trading-challenge leaderboard is skill?")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("simulate", help="simulate many challenges and report your team's chances")
    add_settings(s, "simulate")
    s.add_argument("--json", action="store_true", help="print the full result as JSON")
    c = sub.add_parser("sample", help="show one simulated challenge, place by place")
    add_settings(c, "sample")
    c.add_argument("--index", type=int, default=0, metavar="N", help="which challenge, counting from 0 (default 0)")
    c.add_argument("--top", type=int, default=10, metavar="N", help="how many places to show, plus your team; 0 shows every team (default 10)")
    d = sub.add_parser("design", help="compare scoring rules and challenge lengths (the organiser's view)")
    add_settings(d, "design")
    d.add_argument("--sims-each", type=int, default=400, metavar="N", help="challenges per rule and length (default 400)")
    d.add_argument("--workers", type=int, default=os.cpu_count() or 1, metavar="N",
                   help="parallel processes (default: one per CPU); the answer does not change")
    d.add_argument("--csv", metavar="PATH", help="also write the table to a CSV file")
    d.add_argument("--html", metavar="PATH", help="also write a self-contained HTML report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        p = settings(args)
        warn_if_clamped(p)
        if args.command == "simulate":
            r = simulate(p)
            print(json.dumps(r, indent=2) if args.json else simulate_report(r))
        elif args.command == "sample":
            if args.index < 0 or args.top < 0:
                raise ValueError("--index and --top cannot be negative")
            print(sample_report(p, args.index, args.top))
        elif args.command == "design":
            if args.sims_each < 1 or args.workers < 1:
                raise ValueError("--sims-each and --workers must be at least 1")
            params = normalise(p)
            rows = skill_by_length(params, args.sims_each, args.workers)
            print(design_report(params, rows, args.sims_each))
            if args.csv:
                Path(args.csv).write_text(design_csv(rows), encoding="utf-8")
                print(f"Wrote {args.csv}")
            if args.html:
                Path(args.html).write_text(design_html(params, rows, args.sims_each), encoding="utf-8")
                print(f"Wrote {args.html}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
