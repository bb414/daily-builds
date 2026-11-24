"""Command line: python -m stairstep <command> ..."""

import argparse
import json
import sys

from . import data as datafile
from . import model, report


def _add_settings(p, world=True):
    defaults = {k: v[0] for k, v in model.SETTINGS.items()}
    if world:
        p.add_argument("--seed", type=int, default=defaults["seed"], help="world number (default %(default)s)")
        p.add_argument("--holidays", type=float, default=defaults["holidays"], help="festival strength, 0 to 2 (default %(default)s)")
        p.add_argument("--promo-lift", dest="promoLift", type=float, default=defaults["promoLift"],
                       help="extra sales in a promotion week, 0 to 1.5 (default %(default)s)")
        p.add_argument("--noise", type=float, default=defaults["noise"], help="random noise, 0 to 0.6 (default %(default)s)")
        p.add_argument("--growth", type=float, default=defaults["growth"], help="growth per year, -0.2 to 0.3 (default %(default)s)")
    p.add_argument("--horizon", type=int, default=defaults["horizon"], help="weeks ahead, 1 to 4 (default %(default)s)")
    p.add_argument("--override-rate", dest="overrideRate", type=float, default=defaults["overrideRate"],
                   help="share of AI forecasts planners change, 0 to 1 (default %(default)s)")
    p.add_argument("--optimism", type=float, default=defaults["optimism"],
                   help="average upward push of an override, -0.3 to 0.3 (default %(default)s)")
    p.add_argument("--insight", type=float, default=defaults["insight"],
                   help="share of the AI's error planners can see, 0 to 1 (default %(default)s)")
    p.add_argument("--buffer", type=float, default=defaults["buffer"], help="safety stock, 0 to 0.5 (default %(default)s)")
    p.add_argument("--threshold", type=float, default=defaults["threshold"],
                   help="gain the AI needs over simple methods, 0 to 0.1 (default %(default)s)")


def _settings(args):
    return {k: getattr(args, k) for k in model.SETTINGS if hasattr(args, k)}


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
