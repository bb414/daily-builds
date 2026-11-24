"""Command-line interface: python -m crutch_check <command> ..."""

import argparse
import json
import sys

from .cohort import SCENARIOS, simulate_cohort
from .htmlreport import study_html
from .model import DEMO_SEEDS, PERSONAS, build_session, simulate_responses
from .power import power_curve, power_report
from .report import session_report
from .sessions import load_sessions, write_bundle, write_csv
from .study import analyse, study_report


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
    filled = simulate_responses(session, PERSONAS[args.persona], args.response_seed)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(filled, f, indent=2)
        print("Wrote a simulated session to %s" % args.out)
    print(session_report(filled))
    return 0


def cmd_simulate(args):
    sessions = simulate_cohort(args.n, args.scenario, seed=args.seed, study=args.study,
                               design={"checkerWrong": args.checker_wrong})
    write_bundle(sessions, args.out)
    print("Simulated %d participants (%d per group, scenario '%s') and saved them to %s" % (
        len(sessions), args.n, args.scenario, args.out))
    print("Scenario: %s" % SCENARIOS[args.scenario]["about"])
    return 0


def cmd_analyse(args):
    sessions = load_sessions(args.files)
    if not sessions:
        raise ValueError("no sessions found")
    an = analyse(sessions, n_perm=args.permutations, n_boot=args.bootstrap, seed=args.seed)
    print(study_report(an))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(study_html(an, title=args.title))
        print("\nWrote the HTML report to %s" % args.html)
    return 0


def cmd_power(args):
    def progress(n):
        print("  ...finished %d per group" % n, file=sys.stderr)
    result = power_curve(args.scenario, sizes=args.sizes, sims=args.sims, alpha=args.alpha, seed=args.seed,
                         design={"checkerWrong": args.checker_wrong}, progress=progress)
    print(power_report(result))
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
    d.add_argument("--seed", type=int, default=DEMO_SEEDS["session"],
                   help="which messages (the default matches the app's example result)")
    d.add_argument("--response-seed", type=int, default=DEMO_SEEDS["responses"],
                   help="which simulated answers (the default matches the app's example result)")
    d.add_argument("--out", help="also save the simulated session as JSON")
    d.set_defaults(func=cmd_demo)

    m = sub.add_parser("simulate", help="simulate a whole study (both groups) and save it as a bundle")
    m.add_argument("--n", type=int, default=60, help="participants per group (default 60)")
    m.add_argument("--scenario", choices=sorted(SCENARIOS), default="mixed")
    m.add_argument("--checker-wrong", type=int, default=3, help="messages the checker gets wrong, of 12")
    m.add_argument("--study", default="simulated-study")
    m.add_argument("--seed", type=int, default=1)
    m.add_argument("-o", "--out", default="simulated-study.json")
    m.set_defaults(func=cmd_simulate)

    a = sub.add_parser("analyse", help="compare the groups in a study and describe reliance")
    a.add_argument("files", nargs="+", help="session files, bundles or folders exported from the app")
    a.add_argument("--html", help="also write a self-contained HTML report")
    a.add_argument("--title", default="Crutch check: study report")
    a.add_argument("--permutations", type=int, default=5000)
    a.add_argument("--bootstrap", type=int, default=2000)
    a.add_argument("--seed", type=int, default=1)
    a.set_defaults(func=cmd_analyse)

    w = sub.add_parser("power", help="how many participants a study needs, by simulation")
    w.add_argument("--scenario", choices=sorted(SCENARIOS), default="crutch")
    w.add_argument("--sizes", type=int, nargs="+", default=[20, 40, 80, 160], help="participants per group")
    w.add_argument("--sims", type=int, default=100, help="simulated studies per group size")
    w.add_argument("--alpha", type=float, default=0.05)
    w.add_argument("--checker-wrong", type=int, default=3)
    w.add_argument("--seed", type=int, default=1)
    w.set_defaults(func=cmd_power)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
