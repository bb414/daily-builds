"""Command-line interface: python -m crutch_check <command> ..."""

import argparse
import json
import sys

from .model import PERSONAS, build_session, simulate_responses
from .report import session_report
from .sessions import load_sessions, write_csv


def cmd_score(args):
    for s in load_sessions(args.files):
        print(session_report(s))
        print()
    return 0


def cmd_csv(args):
    sessions = load_sessions(args.files)
    write_csv(sessions, args.out)
    print("Wrote %d sessions (%d rows) to %s" % (
        len(sessions), sum(len(s["trials"]) for s in sessions), args.out))
    return 0


def cmd_demo(args):
    session = build_session(args.seed, "checker")
    filled = simulate_responses(session, PERSONAS[args.persona], args.seed + 1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(filled, f, indent=2)
        print("Wrote a simulated session to %s" % args.out)
    print(session_report(filled))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m crutch_check",
                                description="Score and analyse Crutch check sessions.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("score", help="print a report for each session file")
    s.add_argument("files", nargs="+", help="session JSON files, bundles or folders")
    s.set_defaults(func=cmd_score)

    c = sub.add_parser("csv", help="flatten sessions into one CSV (one row per message)")
    c.add_argument("files", nargs="+")
    c.add_argument("-o", "--out", default="answers.csv")
    c.set_defaults(func=cmd_csv)

    d = sub.add_parser("demo", help="simulate one participant and print their report")
    d.add_argument("--persona", choices=sorted(PERSONAS), default="calibrated")
    d.add_argument("--seed", type=int, default=2026)
    d.add_argument("--out", help="also save the simulated session as JSON")
    d.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
