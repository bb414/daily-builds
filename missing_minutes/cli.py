"""Command-line interface: python -m missing_minutes <command> ..."""

import argparse
import csv
import json
import sys

from . import model
from .report import comparison_text

SWEEP_PARAMS = {
    "saving": ("ai", "saving"),
    "adoption": ("ai", "adoption"),
    "checkMinutes": ("ai", "checkMinutes"),
    "errorRate": ("ai", "errorRate"),
    "catchRate": ("ai", "catchRate"),
    "arrivalsPerDay": (None, "arrivalsPerDay"),
    "step": ("ai", "step"),
}


def _load(args):
    if getattr(args, "config", None):
        cfg = model.load_config(args.config)
    else:
        cfg = model.preset_config(args.preset)
    errs = model.validate(cfg)
    if errs:
        raise SystemExit("The configuration has problems:\n  " + "\n  ".join(errs))
    return cfg


def _add_source(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--preset", default="claims", choices=sorted(model.PRESETS), help="one of the example processes (default: claims)")
    g.add_argument("--config", help="a JSON file saved from the app or written by 'export'")
    p.add_argument("--seed", type=int, default=42, help="random seed (default: 42, as in the app)")


def _parse_values(text):
    """'0,0.1,0.2' or '0:0.6:0.1' (start:stop:step, inclusive)."""
    if ":" in text:
        start, stop, step = (float(x) for x in text.split(":"))
        if step <= 0:
            raise SystemExit("The step in start:stop:step must be positive.")
        out, i = [], 0
        while True:
            v = round(start + i * step, 10)
            if v > stop + 1e-9:
                break
            out.append(v)
            i += 1
        return out
    return [float(x) for x in text.split(",") if x.strip()]


def cmd_run(args):
    cfg = _load(args)
    r = model.compare(cfg, args.seed)
    if args.json:
        json.dump(r, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(comparison_text(r))


def cmd_sweep(args):
    cfg = _load(args)
    where, key = SWEEP_PARAMS[args.param]
    values = _parse_values(args.values)
    if not values:
        raise SystemExit("Give at least one value to sweep.")
    rows = []
    for v in values:
        c = model.normalise(cfg)
        target = c["ai"] if where == "ai" else c
        target[key] = int(v) if key == "step" else v
        errs = model.validate(c)
        if errs:
            raise SystemExit("%s = %s is not valid: %s" % (args.param, v, errs[0]))
        r = model.compare(c, args.seed)
        rows.append({
            args.param: v,
            "pilot_claim_min": round(r["pilotClaim"], 3),
            "saved_if_all_use_min": round(-r["parts"][0]["value"], 3),
            "lead_without_ai_days": round(r["base"]["leadMean"] / model.DAY, 4),
            "lead_with_ai_days": round(r["ai"]["leadMean"] / model.DAY, 4),
            "change_min": round(r["total"], 3),
            "leverage": round(r["leverage"], 4),
            "p85_with_ai_days": round(r["ai"]["leadP85"] / model.DAY, 4),
            "within_target_with_ai": round(r["ai"]["withinSla"], 4),
            "fte_freed": round(r["fteFreed"], 3),
            "sent_back_per_100": round(r["ai"]["aiSendBacksPer100"] + r["ai"]["baseSendBacksPer100"], 3),
            "errors_reaching_customers_per_100": round(r["ai"]["escapedPer100"], 3),
            "busiest_step_with_ai": c["steps"][r["bottleneckAfter"]]["name"] if r["bottleneckAfter"] >= 0 else "",
            "all_cases_finished": r["complete"],
        })
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    finally:
        if args.out:
            out.close()
            print("Wrote %d rows to %s" % (len(rows), args.out))


def cmd_export(args):
    cfg = model.preset_config(args.preset)
    text = json.dumps(cfg, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("Wrote " + args.out)
    else:
        print(text)


def build_parser():
    p = argparse.ArgumentParser(prog="python -m missing_minutes",
                                description="Where do the minutes an AI saves at one desk go once the whole process runs?")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="compare the process without and with the AI")
    _add_source(r)
    r.add_argument("--json", action="store_true", help="print the full result as JSON")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("sweep", help="vary one setting and write a CSV row for each value")
    _add_source(s)
    s.add_argument("--param", required=True, choices=sorted(SWEEP_PARAMS), help="the setting to vary")
    s.add_argument("--values", required=True, help="comma-separated values, or start:stop:step")
    s.add_argument("--out", help="CSV file to write (default: print to the screen)")
    s.set_defaults(func=cmd_sweep)

    e = sub.add_parser("export", help="write an example process as JSON to edit and load with --config")
    e.add_argument("--preset", default="claims", choices=sorted(model.PRESETS))
    e.add_argument("--out", help="file to write (default: print to the screen)")
    e.set_defaults(func=cmd_export)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0
