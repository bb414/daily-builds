"""Command-line interface: python -m saveorsink <command> ..."""

import argparse
import csv
import json
import os
import sys

from .model import (PRESETS, RULES, SWEEP_DEFAULTS, default_settings, generate_year, simulate, stress_test, sweep,
                    validate_settings, year_seed)
from .report import summary_report, sweep_report, year_report


def load_settings(args):
    if args.settings:
        try:
            with open(args.settings, encoding="utf-8-sig") as f:
                s = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("%s is not valid JSON: %s" % (args.settings, exc)) from None
    else:
        s = default_settings(args.preset)
    if getattr(args, "rescue", None):
        s["rescue"] = args.rescue
    if getattr(args, "seed", None) is not None:
        s["seed"] = args.seed
    problems = validate_settings(s)
    if problems:
        raise ValueError("; ".join(problems[:4]))
    return s


def cmd_run(args):
    s = load_settings(args)
    summary = stress_test(s, args.years)
    print(summary_report(s, summary, args.years))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print("\nWrote the full summary (amounts in pennies) to %s" % args.json)
    return 0


def cmd_year(args):
    s = load_settings(args)
    if args.rule not in RULES:
        raise ValueError("rule must be one of: %s" % ", ".join(RULES))
    if not 1 <= args.year <= 20000:
        raise ValueError("--year must be from 1 to 20000")
    days = generate_year(s, year_seed(s["seed"], args.year - 1))
    res = simulate(s, days, args.rule, trace=True)
    print(year_report(s, days, res, args.rule))
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["day", "money_in", "money_out", "moved_to_savings", "moved_back", "balance", "savings"])
            for d, row in enumerate(res["daily"]):
                w.writerow([d + 1, "%.2f" % (sum(a for _, a in days[d]["in"]) / 100),
                            "%.2f" % (sum(a for _, a, _ in days[d]["out"]) / 100), "%.2f" % (row["moved"] / 100),
                            "%.2f" % (row["rescued"] / 100), "%.2f" % (row["balance"] / 100), "%.2f" % (row["pot"] / 100)])
        print("\nWrote 365 days to %s" % args.csv)
    return 0


def parse_dial(text):
    """'horizon=7,14,28' -> ('horizon', [7.0, 14.0, 28.0])"""
    name, sep, values = text.partition("=")
    if not sep or not name.strip() or not values.strip():
        raise ValueError("--dial must look like name=1,2,3 (got %r)" % text)
    try:
        nums = [float(v) for v in values.split(",") if v.strip()]
    except ValueError:
        raise ValueError("--dial %s has a value that is not a number" % name.strip()) from None
    return name.strip(), [int(v) if v == int(v) else v for v in nums]


def cmd_sweep(args):
    s = load_settings(args)
    dials = None
    if args.dial:
        dials = dict(parse_dial(d) for d in args.dial)
        if len(dials) != len(args.dial):
            raise ValueError("each --dial must name a different setting")
    result = sweep(s, args.rule, dials, args.years)
    print(sweep_report(s, result))
    if args.csv:
        ka, kb = result["dials"]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow([ka, kb, "set_aside_median", "moved_in_median", "better_off_median", "chance_past_limit",
                        "raids_per_year", "came_back", "frontier"])
            for r in result["rows"]:
                w.writerow([r[ka], r[kb], "%.2f" % (r["endPot"] / 100), "%.2f" % (r["savedIn"] / 100),
                            "%.2f" % (r["net"] / 100), "%.4f" % r["beyondChance"], "%.2f" % r["meanRescues"],
                            "%.4f" % r["cameBack"], "yes" if r["frontier"] else "no"])
        print("\nWrote %d rows to %s" % (len(result["rows"]), args.csv))
    return 0


def cmd_settings(args):
    text = json.dumps(default_settings(args.preset), indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("Wrote the %s settings to %s" % (args.preset, args.out))
    else:
        print(text)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m saveorsink", description="Stress-test automatic saving rules.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--preset", choices=sorted(PRESETS), default="steady", help="a built-in situation")
        sp.add_argument("--settings", help="a settings JSON file (from the app or 'settings')")
        sp.add_argument("--rescue", choices=["overdrawn", "near-limit", "never"], help="override the rescue habit")
        sp.add_argument("--seed", type=int, help="override the random seed")

    r = sub.add_parser("run", help="compare every rule over many simulated years")
    common(r)
    r.add_argument("--years", type=int, default=1000)
    r.add_argument("--json", help="also write the full summary to a JSON file")
    r.set_defaults(func=cmd_run)

    y = sub.add_parser("year", help="one simulated year, month by month, under one rule")
    common(y)
    y.add_argument("--rule", default="smart")
    y.add_argument("--year", type=int, default=1, help="which simulated year (1 is the app's first)")
    y.add_argument("--csv", help="also write every day to a CSV file")
    y.set_defaults(func=cmd_year)

    w = sub.add_parser("sweep", help="try many settings of the smart saver or term planner and find the frontier")
    common(w)
    w.add_argument("--rule", choices=sorted(SWEEP_DEFAULTS), default="smart")
    w.add_argument("--dial", action="append", metavar="NAME=V1,V2,...",
                   help="a setting to vary and the values to try; give two (default: smart horizon and buffer, "
                        "planner buffer and aggressiveness)")
    w.add_argument("--years", type=int, default=200)
    w.add_argument("--csv", help="also write every row to a CSV file")
    w.set_defaults(func=cmd_sweep)

    t = sub.add_parser("settings", help="write a preset's settings to a file you can edit")
    t.add_argument("preset", choices=sorted(PRESETS))
    t.add_argument("-o", "--out")
    t.set_defaults(func=cmd_settings)

    args = p.parse_args(argv)
    try:
        if getattr(args, "years", 1) < 1 or getattr(args, "years", 1) > 20000:
            raise ValueError("--years must be from 1 to 20000")
        return args.func(args)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
