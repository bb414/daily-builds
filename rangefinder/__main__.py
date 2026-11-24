"""Command-line interface: python -m rangefinder <command> ..."""

import argparse
import csv
import json
import os
import sys

from .model import TEMPLATES, analyse, drivers_of, simulate, validate_model
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
