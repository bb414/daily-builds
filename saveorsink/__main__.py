"""Command-line interface: python -m saveorsink <command> ..."""

import argparse
import csv
import json
import os
import sys

from .model import (PRESETS, RULES, default_settings, generate_year, simulate, stress_test, validate_settings,
                    year_seed)
from .report import summary_report, year_report


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
