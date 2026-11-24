"""Command-line interface: python -m second_opinion <command> ..."""

import argparse
import json
import os
import sys

from . import cohort, power, report, synth
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


def _parse_shifts(items):
    shifts = {}
    for item in items or []:
        style, _, value = item.partition("=")
        if style not in ADVICE_STYLES or not value:
            raise ValueError("--assume takes STYLE=NUMBER, for example reason=0.8, not %r" % item)
        shifts[style] = float(value)
    return shifts


def _cmd_power(args):
    arm_a, arm_b = power.parse_arm(args.a), power.parse_arm(args.b)
    sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
    if not sizes or min(sizes) < 2:
        raise ValueError("--sizes needs group sizes of at least 2, for example 25,50,100")
    shifts = _parse_shifts(args.assume)
    label = dict((k, l) for k, l, _ in cohort.MEASURES)[args.measure]
    print("Power to detect a difference in: %s" % label)
    print("Arm A: %s   Arm B: %s   (%d simulated studies per size, alpha %.2f)" % (args.a, args.b, args.reps, args.alpha))
    print("Assumed effect of each advice style on switching (log-odds): %s" % ", ".join(
        "%s %+.2f" % (k, v) for k, v in sorted(dict(synth.ADVICE_SHIFT, **shifts).items())))
    print()
    print("  People per arm   Power   Average difference (B minus A)")
    curve = power.power_curve(arm_a, arm_b, args.measure, sizes, reps=args.reps, alpha=args.alpha,
                              seed=args.seed, shifts=shifts, crutch=args.crutch)
    for row in curve:
        diff = "n/a" if row["difference"] is None else report.signed_points(row["difference"])
        if args.measure == "brierFinal" and row["difference"] is not None:
            diff = "%+.3f" % row["difference"]
        print("  %14d   %4d%%   %s" % (row["n"], round(row["power"] * 100), diff))
    n = power.smallest_adequate(curve, args.target)
    print()
    if n is None:
        print("None of these sizes reaches %d%% power. Try larger groups." % round(args.target * 100))
    else:
        print("Smallest size tried with at least %d%% power: %d people per arm (%d in total)." % (
            round(args.target * 100), n, 2 * n))
    print("These numbers depend entirely on the assumed effects; they are a planning aid, not a promise.")
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
    p.add_argument("--advice", choices=ADVICE_STYLES + ("random",), action="append",
                   help="how the checker shows advice; repeat to make several groups, or use random "
                        "to assign each person a style at random (default: reason)")
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

    p = sub.add_parser("power", help="estimate how many people a study comparing two arms needs")
    p.add_argument("--a", default="verdict", help="first arm, e.g. verdict or verdict+feedback (default verdict)")
    p.add_argument("--b", default="reason", help="second arm (default reason)")
    p.add_argument("--measure", default="followWhenWrong", choices=[k for k, _, _ in cohort.MEASURES],
                   help="what to compare (default followWhenWrong)")
    p.add_argument("--sizes", default="25,50,100,200", help="people per arm to try, comma separated")
    p.add_argument("--reps", type=int, default=100, help="simulated studies per size (default 100)")
    p.add_argument("--alpha", type=float, default=0.05, help="significance level (default 0.05)")
    p.add_argument("--target", type=float, default=0.8, help="power to aim for (default 0.8)")
    p.add_argument("--assume", action="append", metavar="STYLE=NUMBER",
                   help="override an assumed advice effect, e.g. reason=0.8 (repeatable)")
    p.add_argument("--crutch", type=float, default=0.0, help="assumed loss of solo skill, as in synth")
    p.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    p.set_defaults(func=_cmd_power)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "synth" and args.n < 1:
        parser.error("--n must be at least 1")
    if args.command == "power" and (args.reps < 1 or not 0 < args.alpha < 1 or not 0 < args.target <= 1):
        parser.error("--reps must be at least 1, and --alpha and --target must be between 0 and 1")
    try:
        return args.func(args)
    except (cohort.SessionFileError, OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
