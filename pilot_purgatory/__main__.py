"""Command line entry point: python -m pilot_purgatory"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .analysis import lever_effects
from .model import simulate
from .report import html_report, text_report
from .strategies import GOVERNANCE, MOMENTUM


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pilot_purgatory",
        description="Simulate why AI pilots stall before scaling, comparing pilots-first and strategy-first organisations.",
    )
    p.add_argument("--runs", type=int, default=500, help="portfolios simulated per strategy (default 500)")
    p.add_argument("--quarters", type=int, default=12, help="time horizon in quarters (default 12)")
    p.add_argument("--seed", type=int, default=42, help="random seed for reproducible results (default 42)")
    p.add_argument("--html", metavar="PATH", help="also write a self-contained HTML report to PATH")
    p.add_argument("--no-levers", action="store_true", help="skip the single-fix analysis (faster)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.runs < 1 or args.quarters < 1:
        print("--runs and --quarters must both be at least 1", file=sys.stderr)
        return 2

    summaries = [simulate(s, args.runs, args.quarters, args.seed) for s in (MOMENTUM, GOVERNANCE)]
    effects = [] if args.no_levers else lever_effects(MOMENTUM, args.runs, args.quarters, args.seed)[1]

    print(text_report(summaries, effects, args.seed))
    if args.html:
        path = Path(args.html)
        path.write_text(html_report(summaries, effects, args.seed), encoding="utf-8")
        print(f"\nHTML report written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
