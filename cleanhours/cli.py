"""Command-line interface: python -m cleanhours {run,curves,sweep,template}."""

import argparse
import os
import statistics
import sys
import time

from . import jobs_csv, model, report


def _floats(text):
    try:
        return [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("expected comma-separated numbers, got %r" % text)


def _seeds(text):
    """'1-5' or '1,4,9'."""
    try:
        if "-" in text:
            a, b = text.split("-", 1)
            out = list(range(int(a), int(b) + 1))
        else:
            out = [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("expected seeds like 1-5 or 1,4,9, got %r" % text)
    if not out or min(out) < 1:
        raise argparse.ArgumentTypeError("seeds must be whole numbers from 1")
    return out


def _presets(text):
    out = [x.strip() for x in text.split(",") if x.strip()]
    bad = [x for x in out if x not in model.PRESETS]
    if bad or not out:
        raise argparse.ArgumentTypeError("unknown grid(s): %s (choose from %s)" % (", ".join(bad) or "none", ", ".join(model.PRESETS)))
    return out


def _range_check(name, values, lo, hi):
    for v in values:
        if not lo <= v <= hi:
            raise SystemExit("error: %s must be between %g and %g (got %g)" % (name, lo, hi, v))


def _load_jobs(path):
    if not path:
        return model.DEFAULT_JOBS
    try:
        return jobs_csv.read_jobs(path)
    except OSError as e:
        raise SystemExit("error: cannot read %s: %s" % (path, e.strerror))
    except jobs_csv.JobsError as e:
        raise SystemExit("error: %s: %s" % (path, e))


def cmd_run(args):
    _range_check("--wind", [args.wind], 0, 5)
    _range_check("--solar", [args.solar], 0, 5)
    _range_check("--forecast-error", [args.forecast_error], 0, 5)
    _range_check("--slack", [args.slack], 0, 5)
    cfg = {"preset": args.preset, "seed": args.seed, "windScale": args.wind, "solarScale": args.solar,
           "forecastError": args.forecast_error, "slack": args.slack, "jobs": _load_jobs(args.jobs)}
    result = model.run(cfg)
    print("Clean hours: " + report.describe_config(cfg))
    print()
    print(report.text_table(result))
    print()
    print(report.headline(result, args.highlight))
    if args.out:
        files = report.write_run(result, args.out)
        print()
        print("Wrote " + ", ".join(os.path.join(args.out, f) for f in files))
    return 0


def cmd_sweep(args):
    _range_check("--wind", args.wind, 0, 5)
    _range_check("--solar", args.solar, 0, 5)
    _range_check("--forecast-error", args.forecast_error, 0, 5)
    _range_check("--slack", args.slack, 0, 5)
    jobs = _load_jobs(args.jobs)
    total = len(args.presets) * len(args.seeds) * len(args.wind) * len(args.solar) * len(args.forecast_error) * len(args.slack)
    rows, done, t0 = [], 0, time.time()
    for preset in args.presets:
        for seed in args.seeds:
            for wind in args.wind:
                for solar in args.solar:
                    base = {"preset": preset, "seed": seed, "windScale": wind, "solarScale": solar,
                            "forecastError": 1, "slack": 1, "jobs": jobs}
                    grid = model.simulate_grid(base)  # the grid does not depend on forecasts or slack
                    for fe in args.forecast_error:
                        for slack in args.slack:
                            cfg = dict(base, forecastError=fe, slack=slack)
                            res = model.run(cfg, grid)
                            for p in model.POLICIES:
                                if p["key"] == "now":
                                    continue
                                R = res["policies"][p["key"]]
                                rows.append({"grid": preset, "seed": seed, "wind_scale": wind, "solar_scale": solar,
                                             "forecast_error": fe, "slack": slack, "scheduler": p["key"],
                                             "reported_saved_t": R["reportedSavedT"], "real_saved_t": R["realSavedT"],
                                             "reported_saving": R["reportedSaving"], "real_saving": R["realSaving"],
                                             "gap_t": R["reportedSavedT"] - R["realSavedT"],
                                             "mean_wait_h": R["meanDelay"], "verdict": R["verdict"]})
                            done += 1
                            if not args.quiet and sys.stderr.isatty():
                                print("\r%d/%d runs" % (done, total), end="", file=sys.stderr, flush=True)
    if not args.quiet:
        print("\r%d runs in %.1fs" % (total, time.time() - t0), file=sys.stderr)
    os.makedirs(args.out, exist_ok=True)
    cols = list(rows[0].keys())
    report.write_csv(os.path.join(args.out, "sweep.csv"), rows, cols)
    summary = sweep_summary(rows)
    with open(os.path.join(args.out, "sweep.md"), "w", encoding="utf-8") as fh:
        fh.write(summary)
    print(summary)
    print("Wrote %s and %s" % (os.path.join(args.out, "sweep.csv"), os.path.join(args.out, "sweep.md")))
    return 0


def sweep_summary(rows):
    out = ["# Clean hours sweep", "",
           "Medians across every combination run. The gap is reported tonnes saved minus real tonnes saved: "
           "positive means a carbon report would overstate the benefit, negative that it would understate it.", "",
           "| Grid | Scheduler | Runs | Median reported saved | Median real saved | Median gap | Real saving below zero | Report overstates |",
           "|---|---|---:|---:|---:|---:|---:|---:|"]
    keys = []
    for r in rows:
        k = (r["grid"], r["scheduler"])
        if k not in keys:
            keys.append(k)
    for grid, sched in keys:
        sub = [r for r in rows if r["grid"] == grid and r["scheduler"] == sched]
        label = next(p["label"] for p in model.POLICIES if p["key"] == sched)
        neg = sum(1 for r in sub if r["real_saved_t"] < 0) / len(sub)
        over = sum(1 for r in sub if r["gap_t"] > 0) / len(sub)
        out.append("| %s | %s | %d | %s | %s | %s | %.0f%% | %.0f%% |" % (
            model.PRESETS[grid]["label"], label, len(sub),
            report.tonnes(statistics.median(r["reported_saved_t"] for r in sub)),
            report.tonnes(statistics.median(r["real_saved_t"] for r in sub)),
            report.tonnes(statistics.median(r["gap_t"] for r in sub)), 100 * neg, 100 * over))
    out.append("")
    return "\n".join(out)


CURVE_FIELDS = {
    "wind": ("windScale", [0.5, 0.75, 1, 1.5, 2, 2.5, 3], "Wind fleet", lambda v: "%d%%" % round(v * 100)),
    "slack": ("slack", [0, 0.25, 0.5, 1, 1.5, 2, 3], "Flexibility", lambda v: "%gx" % v),
    "forecast": ("forecastError", [0, 0.5, 1, 1.5, 2, 3], "Forecast error", lambda v: "%gx" % v),
    "solar": ("solarScale", [0.5, 1, 1.5, 2, 3], "Solar fleet", lambda v: "%d%%" % round(v * 100)),
}


def cmd_curves(args):
    cfg = {"preset": args.preset, "seed": args.seed, "windScale": 1, "solarScale": 1,
           "forecastError": 1, "slack": 1, "jobs": _load_jobs(args.jobs)}
    label = next(p["label"] for p in model.POLICIES if p["key"] == args.scheduler)
    print("Clean hours: %s, weather year %d. Tonnes of CO2 saved in a year by: %s"
          % (model.PRESETS[args.preset]["label"], args.seed, label))
    for name in args.fields:
        field, values, title, fmt = CURVE_FIELDS[name]
        print()
        head = "%-20s %14s %14s %14s %12s %8s" % (title, "Reported", "Real", "Best possible", "Spare hours", "Wait")
        print(head)
        print("-" * len(head))
        for pt in model.curve(cfg, field, values):
            P = pt["policies"][args.scheduler]
            print("%-20s %14s %14s %14s %11.0f%% %7.1fh" % (
                fmt(pt["value"]), report.tonnes(P["reportedSavedT"]), report.tonnes(P["realSavedT"]),
                report.tonnes(pt["policies"]["oracle"]["realSavedT"]), 100 * pt["curtailShare"], P["meanDelay"]))
    return 0


def _fields(text):
    out = [x.strip() for x in text.split(",") if x.strip()]
    bad = [x for x in out if x not in CURVE_FIELDS]
    if bad or not out:
        raise argparse.ArgumentTypeError("choose from %s" % ", ".join(CURVE_FIELDS))
    return out


def cmd_template(args):
    text = jobs_csv.format_jobs(model.DEFAULT_JOBS)
    if args.out == "-":
        sys.stdout.write(text)
    else:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print("Wrote the example fleet to %s; edit it and pass it with --jobs." % args.out)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m cleanhours",
                                 description="Carbon-aware scheduling of AI compute jobs on an invented grid: "
                                             "reported (average) against real (marginal) savings.")
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run one year and print (or write) the results")
    r.add_argument("--preset", choices=sorted(model.PRESETS), default="windy", help="which invented grid (default windy)")
    r.add_argument("--jobs", help="jobs CSV (default: the example fleet; see the template command)")
    r.add_argument("--seed", type=int, default=1, help="weather year, a whole number from 1 (default 1)")
    r.add_argument("--wind", type=float, default=1, help="wind fleet size as a multiple of normal (default 1)")
    r.add_argument("--solar", type=float, default=1, help="solar fleet size as a multiple of normal (default 1)")
    r.add_argument("--forecast-error", type=float, default=1, help="forecast error, 0 = perfect, 1 = typical (default 1)")
    r.add_argument("--slack", type=float, default=1, help="multiply every job's slack (default 1)")
    r.add_argument("--highlight", choices=[p["key"] for p in model.POLICIES if p["key"] != "now"], default="avg",
                   help="scheduler for the one-line verdict (default avg)")
    r.add_argument("--out", help="folder to write summary.md, schedulers.csv, jobs.csv and grid_hours.csv")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("sweep", help="batch runs across grids, weather years and settings")
    s.add_argument("--presets", type=_presets, default=list(model.PRESETS), help="comma-separated grids (default all three)")
    s.add_argument("--seeds", type=_seeds, default=[1, 2, 3, 4, 5], help="weather years, e.g. 1-5 (default 1-5)")
    s.add_argument("--wind", type=_floats, default=[1.0], help="wind fleet multiples, e.g. 0.5,1,2")
    s.add_argument("--solar", type=_floats, default=[1.0], help="solar fleet multiples")
    s.add_argument("--forecast-error", type=_floats, default=[1.0], help="forecast error multiples")
    s.add_argument("--slack", type=_floats, default=[1.0], help="flexibility multiples")
    s.add_argument("--jobs", help="jobs CSV (default: the example fleet)")
    s.add_argument("--out", default="sweep-output", help="output folder (default sweep-output)")
    s.add_argument("--quiet", action="store_true", help="no progress counter")
    s.set_defaults(func=cmd_sweep)

    c = sub.add_parser("curves", help="how the savings change with wind fleet, flexibility, forecast error or solar")
    c.add_argument("--preset", choices=sorted(model.PRESETS), default="windy", help="which invented grid (default windy)")
    c.add_argument("--seed", type=int, default=1, help="weather year (default 1)")
    c.add_argument("--scheduler", choices=[p["key"] for p in model.POLICIES if p["key"] != "now"], default="avg",
                   help="scheduler to report (default avg)")
    c.add_argument("--fields", type=_fields, default=["wind", "slack"], help="comma-separated: wind, slack, forecast, solar (default wind,slack)")
    c.add_argument("--jobs", help="jobs CSV (default: the example fleet)")
    c.set_defaults(func=cmd_curves)

    t = sub.add_parser("template", help="write the example fleet as a jobs CSV to edit")
    t.add_argument("--out", default="jobs.csv", help="file to write, or - for the screen (default jobs.csv)")
    t.set_defaults(func=cmd_template)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if hasattr(args, "seed") and args.seed < 1:
        raise SystemExit("error: --seed must be a whole number from 1")
    return args.func(args)
