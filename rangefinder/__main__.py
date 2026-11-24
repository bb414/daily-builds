"""Command-line interface: python -m rangefinder <command> ..."""

import argparse
import csv
import json
import os
import sys

from .deep import sobol, stability
from .model import (MAX_SAMPLES, MIN_SAMPLES, TEMPLATES, analyse, drivers_of, format_value, narrow_driver, percent,
                    simulate, validate_model)
from .report import text_report


def load_model(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            model = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("%s is not valid JSON: %s" % (path, exc)) from None
    problems = validate_model(model)
    if problems:
        raise ValueError("%s: %s" % (path, "; ".join(problems[:5])))
    return model


def check_samples(n):
    if n is not None and not MIN_SAMPLES <= n <= MAX_SAMPLES:
        raise ValueError("--samples must be from %d to %d" % (MIN_SAMPLES, MAX_SAMPLES))


def cmd_run(args):
    check_samples(args.samples)
    model = load_model(args.model)
    if args.threshold is not None:
        model["threshold"] = args.threshold
        problems = validate_model(model)
        if problems:
            raise ValueError(problems[0])
    res = analyse(model, args.samples, args.seed)
    print(text_report(model, res))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        print("\nWrote the full analysis to %s" % args.json)
    if args.csv:
        values, columns = simulate(model, args.samples, args.seed)
        names = [d["name"] for _, _, d in drivers_of(model)]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(names + [model["outputName"] or "estimate"])
            for k in range(len(values)):
                w.writerow([repr(col[k]) for col in columns] + [repr(values[k])])
        print("\nWrote {:,} samples to {}".format(len(values), args.csv))
    return 0


def cmd_deep(args):
    if args.samples < 2 or args.seeds < 1:
        raise ValueError("--samples must be at least 2 and --seeds at least 1")
    model = load_model(args.model)
    res = analyse(model)
    names = [d["name"] for _, _, d in drivers_of(model)]
    varying = sum(1 for _, _, d in drivers_of(model) if d["dist"] != "fixed")
    width = max([len(n) for n in names] + [len("Drivers combining"), len("Driver")])
    print("%s: heavier checks" % (model["title"] or "Untitled estimate"))
    print("")
    print("Sobol indices from %s pick-and-freeze runs (first-order checks the app's shares;" % "{:,}".format(
        args.samples * (varying + 2)))
    print("total-effect adds each driver's interactions)")
    print("  %-*s  %9s  %11s  %12s" % (width, "Driver", "App share", "First-order", "Total-effect"))
    sobol_rows = sobol(model, args.samples, args.seed)
    for r, s in zip(res["drivers"], sobol_rows):
        print("  %-*s  %8d%%  %10d%%  %11d%%" % (width, r["name"], percent(r["varShare"]),
                                                 percent(s["first"]), percent(s["total"])))
    combined = max(0.0, 1 - sum(s["first"] for s in sobol_rows)) if res["sd"] > 0 else 0.0
    print("  %-*s  %8d%%  %10d%%" % (width, "Drivers combining", percent(res["interaction"]), percent(combined)))

    def fv(x):
        return format_value(x, model["unit"], model["unitPosition"])

    st = stability(model, args.seeds)
    print("")
    print("Seed stability: the headline numbers under %d different seeds (%s samples each)" % (
        args.seeds, "{:,}".format(res["n"])))
    labels = {"p10": "10th percentile", "p50": "Median", "p90": "90th percentile", "mean": "Average"}
    for k, label in labels.items():
        x = st[k]
        print("  %-16s %10s  (spread %s to %s, sd %s)" % (label, fv(x["mean"]), fv(x["min"]), fv(x["max"]), fv(x["sd"])))
    if "probAbove" in st:
        x = st["probAbove"]
        print("  %-16s %10s  (spread %.1f%% to %.1f%%)" % ("Chance of clearing", "%.1f%%" % (x["mean"] * 100),
                                                            x["min"] * 100, x["max"] * 100))
    return 0


def pilot_plan(model, factor):
    """For every driver: what narrowing its range would do to the range and to the decision."""
    base = analyse(model)
    base_width = base["p90"] - base["p10"]
    rows = []
    for i, (ti, di, d) in enumerate(drivers_of(model)):
        if d["dist"] == "fixed":
            continue
        r = analyse(narrow_driver(model, ti, di, factor))
        rows.append({
            "name": d["name"],
            "width": r["p90"] - r["p10"],
            "widthChange": ((r["p90"] - r["p10"]) / base_width - 1) if base_width > 0 else None,
            "wrong": r["voi"]["wrongChance"] if r["voi"] else None,
            "evppi": base["voi"]["drivers"][i]["evppi"] if base["voi"] else None,
        })
    rows.sort(key=lambda x: (x["widthChange"] is None, x["widthChange"] or 0))
    return base, rows


def cmd_plan(args):
    model = load_model(args.model)

    def fv(x):
        return format_value(x, model["unit"], model["unitPosition"])

    base, rows = pilot_plan(model, args.factor)
    if not rows:
        print("Every driver is known exactly, so there is no range to narrow.")
        return 0
    what = "pinning down" if args.factor <= 0 else "narrowing to %d%% of its width" % percent(args.factor)
    print("%s: what %s each range would do" % (model["title"] or "Untitled estimate", what))
    print("")
    print("Now: most likely %s to %s" % (fv(base["p10"]), fv(base["p90"])) + (
        ", %d%% chance the call is wrong" % percent(base["voi"]["wrongChance"]) if base["voi"] else ""))
    print("")
    width = max(len(r["name"]) for r in rows)
    head = "  %-*s  %18s" % (width, "Driver", "80% range width")
    if base["voi"]:
        head += "  %16s  %12s" % ("Wrong call after", "Worth up to")
    print(head)
    for r in rows:
        change = "  n/a" if r["widthChange"] is None else "%+4d%%" % percent(r["widthChange"])
        line = "  %-*s  %10s (%s)" % (width, r["name"], fv(r["width"]), change)
        if r["wrong"] is not None:
            line += "  %15d%%  %12s" % (percent(r["wrong"]), fv(r["evppi"]))
        print(line)
    print("")
    print("Each row narrows one range around today's median and reruns everything else unchanged: a scenario in")
    print("which the truth sits in the middle of today's range. 'Worth up to' averages over everything you might learn.")
    print("Use it to decide what a pilot or a piece of research should measure.")
    return 0


def cmd_template(args):
    if args.key is None:
        for t in TEMPLATES:
            print("%-14s %s" % (t["key"], t["about"]))
        return 0
    match = [t for t in TEMPLATES if t["key"] == args.key]
    if not match:
        raise ValueError("no template called %r (choose from %s)" % (args.key, ", ".join(t["key"] for t in TEMPLATES)))
    text = json.dumps(match[0], indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("Wrote the %s template to %s" % (args.key, args.out))
    else:
        print(text)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m rangefinder",
                                description="Run Range finder models from the command line.")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="analyse a model file and print a report")
    r.add_argument("model", help="a model JSON file (saved from the app or from 'template')")
    r.add_argument("--samples", type=int, help="number of samples (default: the model's, or 10,000)")
    r.add_argument("--seed", type=int, help="random seed (default: the model's, or 1)")
    r.add_argument("--threshold", type=float, help="override the decision threshold")
    r.add_argument("--csv", help="also write every sample to a CSV file")
    r.add_argument("--json", help="also write the full analysis (every number the app shows) to a JSON file")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("deep", help="Sobol indices and seed stability (slower checks)")
    d.add_argument("model")
    d.add_argument("--samples", type=int, default=20000, help="base samples for the Sobol indices")
    d.add_argument("--seeds", type=int, default=20, help="how many seeds for the stability check")
    d.add_argument("--seed", type=int, default=11)
    d.set_defaults(func=cmd_deep)

    n = sub.add_parser("plan", help="what narrowing each range would do: a guide to what a pilot should measure")
    n.add_argument("model")
    n.add_argument("--factor", type=float, default=0.5, help="new width as a share of the old (0 pins it down)")
    n.set_defaults(func=cmd_plan)

    t = sub.add_parser("template", help="list the examples, or write one out as a model file")
    t.add_argument("key", nargs="?")
    t.add_argument("-o", "--out")
    t.set_defaults(func=cmd_template)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
