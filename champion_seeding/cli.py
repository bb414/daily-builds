"""Command-line interface: python -m champion_seeding <command> [options]."""

import argparse
import csv
import json
import math
import os
import re
import sys

from . import model
from .network_io import export_network, load_network


def pct(x):
    # Same rounding as the explanations and the browser app (halves round up).
    return "n/a" if x is None else model.whole_pct(x)


def parse_sets(pairs):
    """Reads --set key=value pairs, rejecting unknown keys and values the model would ignore."""
    out = {}
    numeric = [name for name, *_rest in model.PARAMS]
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("--set expects key=value, got %r" % pair)
        key, value = pair.split("=", 1)
        if key == "strategy":
            if value not in model.STRATEGY_KEYS:
                raise SystemExit("--set strategy must be one of: %s" % ", ".join(model.STRATEGY_KEYS))
        elif key not in numeric:
            raise SystemExit("Unknown setting %r. Known settings: %s" % (key, ", ".join(numeric + ["strategy"])))
        elif not math.isfinite(model.to_number(value)):
            raise SystemExit("--set %s needs a number, got %r" % (key, value))
        out[key] = value
    return out


def load_config(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return model.read_settings_file(json.load(fh))
    except OSError as err:
        raise SystemExit("Could not read %s: %s" % (path, err.strerror))
    except (json.JSONDecodeError, RecursionError):
        raise SystemExit("%s is not valid JSON" % path)
    except ValueError as err:
        raise SystemExit("%s: %s" % (path, err))


def build_params(args):
    if getattr(args, "config", None):
        params = load_config(args.config)
    elif args.preset not in model.PRESETS:
        raise SystemExit("Unknown preset %r. Choose from: %s" % (args.preset, ", ".join(model.PRESETS)))
    else:
        params = model.preset_params(args.preset)
    params.update(parse_sets(args.set))
    return model.normalise_params(params)


def apply_picks(params, picks, ids):
    """Turns --picks (person ids such as P007, or numbers counting from 1) into your own champions."""
    if not picks:
        return params
    index = {pid: i for i, pid in enumerate(ids)}
    chosen = []
    for item in (x.strip() for x in picks.split(",")):
        if not item:
            continue
        if item in index:
            chosen.append(index[item])
        elif re.fullmatch(r"[0-9]+", item) and 1 <= int(item) <= len(ids):
            chosen.append(int(item) - 1)
        else:
            raise SystemExit("--picks: no person called %r" % item)
    if len(set(chosen)) > params["champions"]:
        raise SystemExit("--picks names %d people but there are only %d champions (use --set champions=%d)"
                         % (len(set(chosen)), params["champions"], len(set(chosen))))
    return dict(params, custom=chosen, strategy="custom")


def format_comparison(cmp, ids=None, team_names=None, show_champions=False):
    p, net = cmp["params"], cmp["network"]
    lines = [
        "Champion Seeding: %d champions, %d weeks, %d rollouts per strategy" % (p["champions"], p["weeks"], p["runs"]),
        "Organisation: %d people in %d teams, %d working ties (%.1f each on average), %s of ties cross team lines"
        % (net["size"], net["teams"], net["edges"], net["meanDegree"], pct(net["outsideShare"])),
        "",
        "  %-16s %8s %8s %8s %8s %8s" % ("Strategy", "Using", "Tried", "Half?", "Weeks", "Teams"),
    ]
    by = {r["strategy"]: r for r in cmp["results"]}
    for key in cmp["ranking"]:
        r = by[key]
        lines.append("  %-16s %8s %8s %8s %8s %8.1f" % (
            model.STRATEGY_LABELS[key], pct(r["finalMean"]), pct(r["everMean"]), pct(r["reachShare"]),
            "-" if r["weeksToHalf"] is None else str(r["weeksToHalf"]), r["holdsMean"]))
    lines += ["", "  Using: share using it at the end. Tried: share who ever tried it. Half?: share of rollouts reaching",
              "  half the organisation. Weeks: median weeks to half. Teams: teams where at least half use it at the end.",
              "", "Why:"]
    lines += ["  - " + text for text in model.explain(cmp)]
    if show_champions:
        lines += ["", "Champions each strategy would pick (the random pick shown is the first rollout's):"]
        for key in [r["strategy"] for r in cmp["results"]]:
            names = [ids[v] if ids else "P%03d" % (v + 1) for v in by[key]["champions"]]
            lines.append("  %-16s %s" % (model.STRATEGY_LABELS[key], ", ".join(names)))
    return "\n".join(lines)


def fmt_value(key, v):
    if key in ("socialProof", "peerPull", "lapse", "fit", "spontaneous"):
        return "%g%%" % round(v * 100, 1)
    return "%g" % v


def format_sweep(sw):
    key = sw["key"]
    lines = ["What if %s changes? Share using the tool at the end, by strategy (* marks the best)" % model.PARAM_LABELS[key].lower(), "",
             "  %-10s" % "Value" + "".join("%16s" % model.STRATEGY_LABELS[s] for s in model.STRATEGY_KEYS)]
    for pt in sw["points"]:
        cells = []
        for r in pt["results"]:
            mark = "*" if r["strategy"] == pt["best"] else " "
            cells.append("%15s%s" % (pct(r["finalMean"]), mark))
        lines.append("  %-10s" % fmt_value(key, pt["value"]) + "".join(cells))
    lines.append("")
    for span in model.winner_spans(sw):
        rng = ("at %s" % fmt_value(key, span["from"]) if span["from"] == span["to"]
               else "from %s to %s" % (fmt_value(key, span["from"]), fmt_value(key, span["to"])))
        lines.append("  %s wins %s" % (model.STRATEGY_LABELS[span["strategy"]], rng))
    return "\n".join(lines)


def write_sweep_csv(sw, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([sw["key"], "strategy", "share_using_at_end", "share_ever_tried", "share_of_rollouts_reaching_half", "best"])
        for pt in sw["points"]:
            for r in pt["results"]:
                w.writerow([pt["value"], r["strategy"], "%.4f" % r["finalMean"], "%.4f" % r["everMean"],
                            "%.4f" % r["reachShare"], int(r["strategy"] == pt["best"])])


def format_robustness(rb, params):
    lines = ["Does the ranking hold in other organisations of the same shape? (%d organisations, %d rollouts each)"
             % (model.ROBUST_COUNT, min(params["runs"], model.ROBUST_RUNS)), "",
             "  %-16s %6s %10s %16s" % ("Strategy", "Wins", "Average", "Lowest-highest")]
    for row in sorted(rb["summary"], key=lambda r: (-r["wins"], -r["mean"])):
        lines.append("  %-16s %6d %10s %16s" % (model.STRATEGY_LABELS[row["strategy"]], row["wins"], pct(row["mean"]),
                                                "%s-%s" % (pct(row["low"]), pct(row["high"]))))
    top = max(rb["summary"], key=lambda r: (r["wins"], r["mean"]))
    lines += ["", "  %s was best in %d of %d organisations." % (model.STRATEGY_LABELS[top["strategy"]], top["wins"], model.ROBUST_COUNT)]
    return "\n".join(lines)


def write_csv(cmp, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["strategy", "week", "mean_share_using", "p10", "p90"])
        for r in cmp["results"]:
            for week, (m, lo, hi) in enumerate(zip(r["curveMean"], r["curveLow"], r["curveHigh"])):
                w.writerow([r["strategy"], week, "%.4f" % m, "%.4f" % lo, "%.4f" % hi])


def summary_json(cmp):
    return {"params": cmp["params"], "network": cmp["network"], "ranking": cmp["ranking"],
            "results": [{k: v for k, v in r.items() if not k.startswith("curve")} for r in cmp["results"]],
            "why": model.explain(cmp)}


def make_parser():
    parser = argparse.ArgumentParser(prog="python -m champion_seeding",
                                     description="Champion Seeding: where should champions for a new tool sit?")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--preset", default="assistant", help="Starting scenario: " + ", ".join(model.PRESETS))
        sp.add_argument("--set", action="append", metavar="KEY=VALUE", help="Override one setting (repeatable)")
        sp.add_argument("--config", help="Settings file downloaded from the browser app (replaces --preset)")
        sp.add_argument("--picks", help="Your own champions: ids such as P007,P019 or numbers counting from 1")
        sp.add_argument("--json", action="store_true", help="Print a JSON summary instead of text")
        sp.add_argument("--csv", help="Write the weekly adoption curves to this CSV file")
        sp.add_argument("--champions-list", action="store_true", help="List who each strategy would pick")

    sp = sub.add_parser("compare", help="Compare the five strategies on a synthetic organisation")
    common(sp)

    sp = sub.add_parser("load", help="Compare the strategies on your own network, read from CSV files")
    common(sp)
    sp.add_argument("--edges", required=True, help="CSV file with source,target columns")
    sp.add_argument("--teams", help="CSV file with id,team columns (needed for the team-based strategies)")

    sp = sub.add_parser("robustness", help="Does the ranking hold in other organisations of the same shape?")
    sp.add_argument("--preset", default="assistant")
    sp.add_argument("--set", action="append", metavar="KEY=VALUE")
    sp.add_argument("--config")

    sp = sub.add_parser("sweep", help="Which strategy wins as one setting changes?")
    sp.add_argument("--preset", default="assistant")
    sp.add_argument("--set", action="append", metavar="KEY=VALUE")
    sp.add_argument("--config")
    sp.add_argument("--param", default="socialProof", choices=model.SWEEP_KEYS)
    sp.add_argument("--csv", help="Write the results to this CSV file")

    sp = sub.add_parser("export-network", help="Write the synthetic organisation as CSV files")
    sp.add_argument("--preset", default="assistant")
    sp.add_argument("--set", action="append", metavar="KEY=VALUE")
    sp.add_argument("--edges", required=True)
    sp.add_argument("--teams", required=True)
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    params = build_params(args)
    try:
        if args.command == "export-network":
            net = model.build_network(params)
            export_network(net, args.edges, args.teams)
            print("Wrote %s and %s (%d people, %d ties)" % (args.edges, args.teams, net["size"], net["edges"]))
            return 0
        if args.command == "robustness":
            print(format_robustness(model.robustness(params), params))
            return 0
        if args.command == "sweep":
            sw = model.sweep(params, args.param)
            print(format_sweep(sw))
            if args.csv:
                write_sweep_csv(sw, args.csv)
                print("\nWrote %s" % args.csv)
            return 0
        if args.command == "load":
            net, ids, team_names = load_network(args.edges, args.teams, params["seed"])
            if not args.teams:
                print("Note: no teams file, so everyone counts as one team. One team first and one per team need teams.\n")
            params = apply_picks(dict(params, custom=[]), args.picks, ids)
            cmp = model.compare_strategies(params, net)
        else:
            net = model.build_network(params)
            ids = ["P%03d" % (i + 1) for i in range(net["size"])]
            params = apply_picks(params, args.picks, ids)
            cmp = model.compare_strategies(params, net)
        if args.json:
            print(json.dumps(summary_json(cmp), indent=2))
        else:
            print(format_comparison(cmp, ids, None, args.champions_list))
        if args.csv:
            write_csv(cmp, args.csv)
            print("\nWrote %s" % args.csv)
    except ValueError as err:
        raise SystemExit("Error: %s" % err)
    except BrokenPipeError:
        # Output piped into something like head, which stopped reading: finish quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except OSError as err:
        raise SystemExit("Could not write %s: %s" % (err.filename, err.strerror))
    return 0


if __name__ == "__main__":
    sys.exit(main())
