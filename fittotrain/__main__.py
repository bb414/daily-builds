"""Command-line interface: python -m fittotrain <command> ..."""

import argparse
import json
import os
import sys
from datetime import date

from . import audit, batch, crmcsv, htmlreport, model, report


def load_settings_file(path):
    """Read settings saved by the browser app ({"settings": {...}}) or a flat JSON object."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit("Could not read settings from %s: %s" % (path, exc))
    src = data.get("settings") if isinstance(data, dict) and isinstance(data.get("settings"), dict) else data
    keys = ["seed", "deals"] + model.DEFECT_KEYS
    if not isinstance(src, dict) or not any(k in src for k in keys):
        raise SystemExit("%s is not a Fit to train settings file" % path)
    return {k: src[k] for k in keys if k in src}


def _settings(args):
    s = dict(model.DEFAULTS)
    if args.preset:
        s.update({k: v for k, v in model.PRESETS[args.preset].items() if k != "label"})
    if getattr(args, "settings", None):
        s.update(load_settings_file(args.settings))
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit("--set needs key=value, for example --set zombies=0.5")
        key, value = item.split("=", 1)
        if key not in model.DEFECT_KEYS:
            raise SystemExit("unknown defect %r; choose from %s" % (key, ", ".join(model.DEFECT_KEYS)))
        try:
            s[key] = float(value)
        except ValueError:
            raise SystemExit("--set %s needs a number between 0 and 1" % key)
    if args.seed is not None:
        s["seed"] = args.seed
    if args.deals is not None:
        s["deals"] = args.deals
    return model.normalise_settings(s)


def _strip(result):
    """A JSON-friendly copy of a lab result without the raw records."""
    return {k: v for k, v in result.items() if k != "crm"}


def cmd_lab(args):
    s = _settings(args)
    if args.worlds:
        rb = batch.robust(s, args.worlds, quiet=args.json)
        if args.json:
            json.dump(rb, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(report.robust_text(rb))
        return
    r = model.run_lab(s)
    if args.json:
        json.dump(_strip(r), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(report.lab_text(r))


def cmd_sweep(args):
    s = _settings(args)
    res = batch.sweep(s, args.habit, args.levels, args.worlds, quiet=False)
    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "sweep_%s.csv" % args.habit)
    html_path = os.path.join(args.out, "sweep_%s.html" % args.habit)
    crmcsv.write_csv(csv_path, batch.SWEEP_COLUMNS, [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()} for r in res["rows"]])
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(htmlreport.sweep_html(res))
    print(report.sweep_text(res))
    print("\nWrote %s and %s" % (csv_path, html_path))


def cmd_generate(args):
    s = _settings(args)
    crm = model.build_crm(model.generate_world(s))
    crmcsv.write_csv(args.output, crmcsv.COLUMNS, crmcsv.export_rows(crm))
    msg = "Wrote %d records (the CRM as exported on go-live day, %s) to %s" % (
        len(crm["history"]), model.day_to_iso(model.GO_LIVE), args.output)
    if args.truth:
        crmcsv.write_csv(args.truth, crmcsv.TRUTH_COLUMNS, crmcsv.truth_rows(crm))
        msg += ", and what really happened to %s" % args.truth
    print(msg)


def cmd_audit(args):
    try:
        records, info = crmcsv.read_export(args.csv)
    except (OSError, crmcsv.CsvProblem) as exc:
        raise SystemExit("Could not read %s: %s" % (args.csv, exc))
    as_of = None
    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            raise SystemExit("--as-of must be a date in YYYY-MM-DD form")
    a = audit.audit_export(records, info, as_of=as_of, seed=args.seed if args.seed is not None else 2026)
    if args.json:
        json.dump(a, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(report.export_audit_text(a, args.csv))


def build_parser():
    p = argparse.ArgumentParser(prog="python -m fittotrain",
                                description="Is your CRM fit to train an AI win-probability model? (synthetic lab and export audit)")
    sub = p.add_subparsers(dest="command", required=True)

    def world_options(sp):
        sp.add_argument("--preset", choices=sorted(model.PRESETS), help="start from a preset (default: typical settings)")
        sp.add_argument("--set", action="append", metavar="KEY=VALUE",
                        help="set one defect, e.g. --set zombies=0.5 (keys: %s)" % ", ".join(model.DEFECT_KEYS))
        sp.add_argument("--seed", type=int, help="world number (default 2026)")
        sp.add_argument("--deals", type=int, help="deals over two years, 1000 to 8000 (default 4000)")
        sp.add_argument("--settings", metavar="JSON", help="settings file saved from the browser app")

    lab = sub.add_parser("lab", help="run the synthetic lab once and print the results")
    world_options(lab)
    lab.add_argument("--json", action="store_true", help="print the full result as JSON")
    lab.add_argument("--worlds", type=int, metavar="N",
                     help="instead, run the settings on N other worlds (1 to 60) and report what holds")
    lab.set_defaults(func=cmd_lab)

    sw = sub.add_parser("sweep", help="sweep one habit from zero to its maximum and write CSV and HTML reports")
    sw.add_argument("habit", choices=model.DEFECT_KEYS, help="the habit to sweep")
    world_options(sw)
    sw.add_argument("--levels", type=int, default=6, help="number of levels from zero to the maximum (default 6)")
    sw.add_argument("--worlds", type=int, default=5, help="worlds per level (default 5)")
    sw.add_argument("--out", default="out", help="folder for the reports (default out)")
    sw.set_defaults(func=cmd_sweep)

    gen = sub.add_parser("generate", help="write a synthetic CRM export to try the audit on")
    world_options(gen)
    gen.add_argument("-o", "--output", default="synthetic_crm.csv", help="CSV to write (default synthetic_crm.csv)")
    gen.add_argument("--truth", metavar="CSV", help="also write what really happened to each record")
    gen.set_defaults(func=cmd_generate)

    aud = sub.add_parser("audit", help="audit your own anonymised CRM export (CSV)")
    aud.add_argument("csv", help="opportunity export; see the README for the columns")
    aud.add_argument("--as-of", help="extract date, YYYY-MM-DD (default: the day after the latest date in the file)")
    aud.add_argument("--seed", type=int, help="seed for the random hold-out (default 2026)")
    aud.add_argument("--json", action="store_true", help="print the full audit as JSON")
    aud.set_defaults(func=cmd_audit)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
