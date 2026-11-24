"""Command-line interface: python -m second_opinion <command> ..."""

import argparse
import json
import os
import sys

from . import cohort, report, synth
from .design import ADVICE_STYLES
from .metrics import score


def _cmd_score(args):
    sessions = cohort.load_sessions(args.files)
    for i, session in enumerate(sessions):
        if i:
            print()
        result = score(session)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            sys.stdout.write(report.session_text(session, result))
    return 0


def _cmd_synth(args):
    os.makedirs(args.out, exist_ok=True)
    styles = args.advice or ["reason"]
    written = 0
    for k, style in enumerate(styles):
        condition = {"advice": style, "feedback": args.feedback}
        sessions = synth.simulate_cohort(args.n, seed=args.seed + 1000 * k, condition=condition, crutch=args.crutch)
        for session in sessions:
            path = os.path.join(args.out, "%s.json" % session["id"])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=1)
                f.write("\n")
            written += 1
    print("Wrote %d synthetic sessions to %s" % (written, args.out))
    return 0


def _cmd_cohort(args):
    sessions = cohort.load_sessions(args.paths)
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return 1
    summary = cohort.summarise(sessions, by=args.by, resamples=args.resamples)
    comparisons = []
    for key in ("rair", "rsr", "withFinal", "complementarity"):
        comparisons.extend(cohort.compare_groups(summary, key, permutations=args.permutations))
    sys.stdout.write(report.cohort_text(summary, comparisons))
    if args.html:
        synthetic = all(s.get("synthetic") for s in sessions)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(report.cohort_html(summary, comparisons, synthetic=synthetic))
        print("HTML report written to %s" % args.html)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m second_opinion",
        description="Score and pool results from the Second opinion scam-spotting test.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("score", help="score one or more saved sessions (.json or .csv)")
    p.add_argument("files", nargs="+", help="results files downloaded from the app")
    p.add_argument("--json", action="store_true", help="print the full scores as JSON")
    p.set_defaults(func=_cmd_score)

    p = sub.add_parser("synth", help="generate synthetic sessions to try the analysis")
    p.add_argument("--n", type=int, default=40, help="people per condition (default 40)")
    p.add_argument("--advice", choices=ADVICE_STYLES, action="append",
                   help="how the checker shows advice; repeat to make several groups (default: reason)")
    p.add_argument("--feedback", action="store_true", help="people see the right answer after each message")
    p.add_argument("--crutch", type=float, default=0.0,
                   help="assumed loss of solo skill after using the checker, in log-odds (default 0)")
    p.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    p.add_argument("--out", required=True, help="folder to write the sessions into")
    p.set_defaults(func=_cmd_synth)

    p = sub.add_parser("cohort", help="pool many sessions and compare groups")
    p.add_argument("paths", nargs="+", help="results files or folders of them")
    p.add_argument("--by", choices=["condition", "advice", "feedback"], default="condition",
                   help="how to group people (default: full condition)")
    p.add_argument("--html", help="also write a self-contained HTML report to this file")
    p.add_argument("--resamples", type=int, default=2000, help="bootstrap resamples (default 2000)")
    p.add_argument("--permutations", type=int, default=5000, help="permutation test shuffles (default 5000)")
    p.set_defaults(func=_cmd_cohort)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "n", 1) is not None and args.command == "synth" and args.n < 1:
        parser.error("--n must be at least 1")
    try:
        return args.func(args)
    except (cohort.SessionFileError, OSError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
