"""Command line: python -m stairstep <command> ..."""

import argparse
import json
import sys

from . import data as datafile
from . import model, report, sweep

# (option, settings key, type, help). Defaults come from model.SETTINGS.
OPTIONS = [
    ("--seed", "seed", int, "world number"),
    ("--holidays", "holidays", float, "festival strength, 0 to 2"),
    ("--promo-lift", "promoLift", float, "extra sales in a promotion week, 0 to 1.5"),
    ("--noise", "noise", float, "random noise, 0 to 0.6"),
    ("--growth", "growth", float, "growth per year, -0.2 to 0.3"),
    ("--horizon", "horizon", int, "weeks ahead, 1 to 4"),
    ("--override-rate", "overrideRate", float, "share of AI forecasts planners change, 0 to 1"),
    ("--optimism", "optimism", float, "average upward push of an override, -0.3 to 0.3"),
    ("--insight", "insight", float, "share of the AI's error planners can see, 0 to 1"),
    ("--buffer", "buffer", float, "safety stock, 0 to 0.5"),
    ("--threshold", "threshold", float, "gain the AI needs over simple methods, 0 to 0.1"),
]

def _add_settings(p, skip=()):
    p.add_argument("--settings", help="start from the settings in a JSON file, such as a results file from the app")
    for flag, key, kind, text in OPTIONS:
        if key in skip:
            continue
        # The default is None so that options only override what --settings loaded
        # when they are given; the model fills in anything still missing.
        p.add_argument(flag, dest=key, type=kind, default=None,
                       help="%s (default %s)" % (text, model.SETTINGS[key][0]))


def _settings(args):
    """Settings from the command line, on top of any loaded with --settings."""
    base = {}
    if getattr(args, "settings", None):
        try:
            with open(args.settings, encoding="utf-8") as f:
                loaded = json.load(f)
        except json.JSONDecodeError:
            raise datafile.DataError("%s is not valid JSON." % args.settings) from None
        if isinstance(loaded, dict) and isinstance(loaded.get("settings"), dict):
            loaded = loaded["settings"]
        if not isinstance(loaded, dict) or not any(k in model.SETTINGS for k in loaded):
            raise datafile.DataError("No Stairstep settings found in %s." % args.settings)
        base = {k: v for k, v in loaded.items() if k in model.SETTINGS}
    for _, key, _, _ in OPTIONS:
        value = getattr(args, key, None)
        if value is not None:
            base[key] = value
    return base


def _cmd_run(args):
    settings = _settings(args)
    if args.data:
        data = datafile.read_csv(args.data)
        source = "data in %s" % args.data
    else:
        data = model.simulate(settings)
        source = "synthetic chain (world %d)" % model.normalise_settings(settings)["seed"]
    fc = model.forecast_all(data, settings)
    results = model.evaluate(data, fc)
    sys.stdout.write(report.text_report(results, source))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(report.html_report(results, source))
        print("HTML report written to %s" % args.html)
    if args.csv:
        report.forecasts_csv(data, fc, args.csv)
        print("Forecasts written to %s" % args.csv)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
            f.write("\n")
        print("Results written to %s" % args.json)
    return 0


def _cmd_simulate(args):
    data = model.simulate(_settings(args))
    datafile.write_csv(data, args.out)
    print("Wrote %d weeks of sales for %d products in %d stores to %s" % (
        data["weeks"], len(data["skus"]), len(data["stores"]), args.out))
    return 0


def _cmd_sweep(args):
    if args.worlds < 1:
        raise datafile.DataError("--worlds must be at least 1.")
    settings = _settings(args)

    def progress(done, total):
        print("  world %d of %d" % (done, total), file=sys.stderr, end="\r" if done < total else "\n")

    rows = sweep.sweep(settings, worlds=args.worlds, first_seed=args.first_seed, progress=None if args.quiet else progress)
    sys.stdout.write(sweep.summary_text(rows))
    if args.csv:
        sweep.write_csv(rows, args.csv)
        print("One row per world written to %s" % args.csv)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m stairstep",
                                     description="Forecast value added: does each forecasting step, AI included, earn its place?")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run every forecasting step and report the value each adds")
    p.add_argument("--data", help="your own weekly sales as CSV (see stairstep/data.py); otherwise a synthetic chain")
    p.add_argument("--html", help="also write a self-contained HTML report")
    p.add_argument("--csv", help="also write every test-year forecast as CSV")
    p.add_argument("--json", help="also write the full results as JSON")
    _add_settings(p)
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("simulate", help="write a synthetic chain's weekly sales as CSV")
    p.add_argument("--out", required=True, help="CSV file to write")
    _add_settings(p)
    p.set_defaults(func=_cmd_simulate)

    p = sub.add_parser("sweep", help="check how often the conclusions hold across many synthetic worlds")
    p.add_argument("--worlds", type=int, default=20, help="how many worlds (seeds) to run (default 20)")
    p.add_argument("--first-seed", dest="first_seed", type=int, default=1, help="first seed (default 1)")
    p.add_argument("--csv", help="also write one row per world as CSV")
    p.add_argument("--quiet", action="store_true", help="do not show progress")
    _add_settings(p, skip=("seed",))
    p.set_defaults(func=_cmd_sweep)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (datafile.DataError, OSError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
