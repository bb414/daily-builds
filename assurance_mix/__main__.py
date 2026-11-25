"""Command line for Assurance mix. Run `python -m assurance_mix --help`."""

import argparse
import csv
import json
import sys
from pathlib import Path

from . import model, portfolio, report


def _load_system(args):
    if args.example:
        ex = next((e for e in model.DATA["examples"] if e["id"] == args.example), None)
        if ex is None:
            raise SystemExit("Unknown example %r. Choose from: %s" % (
                args.example, ", ".join(e["id"] for e in model.DATA["examples"])))
        return {"answers": dict(ex["answers"])}, ex["name"]
    if not args.file:
        raise SystemExit("Give a system file (JSON) or --example NAME.")
    path = Path(args.file)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise SystemExit("Could not read %s: %s" % (path, e))
    if not isinstance(raw, dict):
        raise SystemExit("%s should contain a JSON object." % path)
    return raw, raw.get("name") or path.stem


def _apply_overrides(raw, args):
    raw = dict(raw)
    for key in ("appetite", "budget", "weeks"):
        v = getattr(args, key, None)
        if v is not None:
            raw[key] = v
    return raw


def cmd_plan(args):
    raw, name = _load_system(args)
    raw = _apply_overrides(raw, args)
    res = model.analyse(raw)
    lad = None if args.no_ladder else model.ladder(raw)
    rob = None if args.draws == 0 else model.robustness(raw, draws=args.draws, seed=args.seed, confidence=args.confidence)
    if args.json:
        if lad is not None:
            res["ladder"] = lad
        if rob is not None:
            res["robustness"] = rob
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    title = "Assurance mix: " + name
    print(report.plan_report(res, title, ladder=lad, robust=rob))
    if args.markdown:
        Path(args.markdown).write_text(report.plan_report(res, title, markdown=True, ladder=lad, robust=rob),
                                       encoding="utf-8")
        print("Wrote %s" % args.markdown)
    return 0


def cmd_portfolio(args):
    systems, notes = portfolio.read_inventory(args.inventory)
    alloc = portfolio.allocate(systems, args.budget, args.appetite, weeks=args.weeks)
    alloc["notes"] = notes + alloc["notes"]
    print(report.portfolio_report(alloc))
    if args.markdown:
        Path(args.markdown).write_text(report.portfolio_report(alloc, markdown=True), encoding="utf-8")
        print("Wrote %s" % args.markdown)
    if args.csv:
        header, rows = report.portfolio_csv_rows(alloc)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        print("Wrote %s" % args.csv)
    return 0


def cmd_techniques(args):
    rows = []
    for t in model.DATA["techniques"]:
        rows.append([t["name"], t["source"], report.STAGE[t["stage"]], report.money(t["cost"]),
                     "ongoing" if t["stage"] == "live" else str(t["weeks"])] +
                    ["%d" % round(t["coverage"][p] * 100) for p in model.PRINCIPLES])
    heads = ["Technique", "Source", "Stage", "Cost", "Weeks"] + [p["short"][:5] + "." for p in model.DATA["principles"]]
    print(report._table(heads, rows, False, ["l", "l", "l", "r", "r"] + ["r"] * 5))
    print("\nCoverage (%) is the chance the technique catches a material problem of that kind, before any")
    print("adjustment for access to the system or the kind of model.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m assurance_mix",
                                description="Find the cheapest mix of AI assurance techniques that brings risk on each "
                                            "of the UK's five AI principles within your appetite. Simplified and "
                                            "illustrative, not legal advice.")
    sub = p.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("plan", help="plan assurance for one system")
    pp.add_argument("file", nargs="?", help="system file (JSON), as saved by the app")
    pp.add_argument("--example", help="use a built-in example instead: " + ", ".join(e["id"] for e in model.DATA["examples"]))
    pp.add_argument("--appetite", type=float, help="highest risk score accepted on any principle (0.5 to 25)")
    pp.add_argument("--budget", type=float, help="budget in £ thousands")
    pp.add_argument("--weeks", type=float, help="weeks until go-live")
    pp.add_argument("--markdown", help="also write a Markdown report to this file")
    pp.add_argument("--json", action="store_true", help="print the full analysis as JSON")
    pp.add_argument("--no-ladder", action="store_true", help="skip the pilot-to-scale comparison")
    pp.add_argument("--draws", type=int, default=400, help="draws for the robustness check (0 to skip; default 400)")
    pp.add_argument("--confidence", type=float, default=0.8,
                    help="share of draws a robust plan must stay within appetite in (default 0.8)")
    pp.add_argument("--seed", type=int, default=2026, help="random seed for the draws (default 2026, as in the app)")
    pp.set_defaults(func=cmd_plan)

    pf = sub.add_parser("portfolio", help="share one budget across an inventory of systems")
    pf.add_argument("inventory", help="inventory CSV, one system per row")
    pf.add_argument("--budget", type=float, required=True, help="total budget in £ thousands")
    pf.add_argument("--appetite", type=float, default=model.DATA["defaults"]["appetite"], help="risk appetite (default 8)")
    pf.add_argument("--weeks", type=float, help="weeks until go-live for systems without their own weeks column")
    pf.add_argument("--markdown", help="also write a Markdown report to this file")
    pf.add_argument("--csv", help="also write the allocation to this CSV file")
    pf.set_defaults(func=cmd_portfolio)

    pt = sub.add_parser("techniques", help="list the assurance techniques and their coverage")
    pt.set_defaults(func=cmd_techniques)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
