"""Command-line interface: python -m rangefinder <command> ..."""

import argparse
import csv
import json
import os
import sys

from .deep import sobol, stability
from .model import TEMPLATES, analyse, drivers_of, format_value, simulate, validate_model
from .report import text_report


def load_model(path):
    try:
        with open(path, encoding="utf-8") as f:
            model = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError("%s is not valid JSON: %s" % (path, exc)) from None
    problems = validate_model(model)
    if problems:
        raise ValueError("%s: %s" % (path, "; ".join(problems[:5])))
    return model


def cmd_run(args):
    model = load_model(args.model)
    if args.threshold is not None:
        model["threshold"] = args.threshold
    res = analyse(model, args.samples, args.seed)
    print(text_report(model, res))
    if args.csv:
        values, columns = simulate(model, args.samples, args.seed)
        names = [d["name"] for _, _, d in drivers_of(model)]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(names + [model["outputName"] or "estimate"])
            for k in range(len(values)):
                w.writerow([repr(col[k]) for col in columns] + [repr(values[k])])
        print("\nWrote %d samples to %s" % (len(values), args.csv))
    return 0


def cmd_deep(args):
    model = load_model(args.model)
    res = analyse(model)
    names = [d["name"] for _, _, d in drivers_of(model)]
    width = max(len(n) for n in names)
    print("%s: heavier checks" % (model["title"] or "Untitled estimate"))
    print("")
    print("Sobol indices from %s pick-and-freeze runs (first-order checks the app's shares;" % "{:,}".format(
        args.samples * (len(names) + 2)))
    print("total-effect adds each driver's interactions)")
    print("  %-*s  %9s  %11s  %12s" % (width, "Driver", "App share", "First-order", "Total-effect"))
    for r, s in zip(res["drivers"], sobol(model, args.samples, args.seed)):
        print("  %-*s  %8d%%  %10d%%  %11d%%" % (width, r["name"], round(r["varShare"] * 100),
                                                 round(s["first"] * 100), round(s["total"] * 100)))

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
        print("  %-16s %9.1f%%  (spread %.1f%% to %.1f%%)" % ("Chance of clearing", x["mean"] * 100, x["min"] * 100,
                                                            x["max"] * 100))
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
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("deep", help="Sobol indices and seed stability (slower checks)")
    d.add_argument("model")
    d.add_argument("--samples", type=int, default=20000, help="base samples for the Sobol indices")
    d.add_argument("--seeds", type=int, default=20, help="how many seeds for the stability check")
    d.add_argument("--seed", type=int, default=11)
    d.set_defaults(func=cmd_deep)

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
