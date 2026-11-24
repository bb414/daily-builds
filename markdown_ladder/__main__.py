"""Command-line interface.

    python -m markdown_ladder plan --preset truffles          # best plan for one product
    python -m markdown_ladder plan --stock 80 --days 5        # ...or your own numbers
    python -m markdown_ladder robust --preset truffles        # what if the forecast is wrong?
    python -m markdown_ladder range examples/range.csv        # plan a whole product range
"""

import argparse
import math
import sys

from . import model, report


def text_table(headers, rows):
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def money(x):
    return ("-" if x < 0 else "") + "£%.2f" % abs(x)


def step_label(j):
    return "full" if model.LADDER[j] == 0 else "-%d%%" % model.LADDER[j]


def config_from_args(args):
    """Settings from a preset and/or flags. Prints a note for any value that had to be adjusted."""
    cfg = dict(model.PRESETS[args.preset]) if args.preset else {}
    given = {}
    for name in model.FIELDS:
        value = getattr(args, name)
        if value is not None:
            cfg[name] = given[name] = value
    if args.pattern:
        cfg["pattern"] = args.pattern
    if args.allow_price_rises:
        cfg["monotone"] = False
    used = model.normalise(cfg)
    for name, value in given.items():
        if not math.isfinite(value) or abs(value - used[name]) > 1e-9:
            f = model.FIELDS[name]
            print("Note: %s %s changed to %s (allowed %s to %s%s)." % (
                name, value, used[name], f["min"], f["max"], ", whole numbers" if f["step"] == 1 else ""), file=sys.stderr)
    return cfg


def ladder_rows(sol, bands=8):
    """Best first-day-of-markdown step for a few stock levels and every day."""
    S, T = sol["cfg"]["stock"], sol["cfg"]["days"]
    levels = sorted({max(1, model.js_round(S * (b + 1) / bands)) for b in range(bands)}, reverse=True)
    rows = []
    for s in levels:
        rows.append([str(s)] + [step_label(sol["policy"][t][0][s]) for t in range(T)])
    return rows


def cmd_plan(args):
    cfg = model.normalise(config_from_args(args))
    rule_days = min(max(1, args.rule_days), cfg["days"])
    if rule_days != args.rule_days:
        print("Note: --rule-days %d changed to %d (between 1 and the days until the sell-by date)." % (args.rule_days, rule_days), file=sys.stderr)
    cmp = model.compare_policies(cfg, {"pct": args.rule_pct, "daysLeft": rule_days})
    sol = cmp["solution"]
    pattern_names = {"flat": "same every day", "highStreet": "busy weekends", "office": "quiet weekends"}
    print("%d %s, %d selling %s from %s, full price %s, demand %.1f a day at full price (%s)" % (
        cfg["stock"], "unit" if cfg["stock"] == 1 else "units", cfg["days"], "day" if cfg["days"] == 1 else "days",
        model.DAY_NAMES[cfg["startDay"]], money(cfg["price"]), cfg["demand"], pattern_names[cfg["pattern"]]))
    print("Price sensitivity %.1f, appeal lost per day %d%%" % (cfg["elasticity"], cfg["freshness"]))
    print("Disposal %s a unit, stock cost %s a unit%s" % (money(cfg["wasteCost"]), money(cfg["unitCost"]),
                                                          "" if cfg["monotone"] else ", prices may go back up"))
    print()
    rows = []
    for r in cmp["rows"]:
        x = r["result"]
        rows.append([r["name"], money(x["profit"]), "%.1f" % x["sold"], "%.1f" % x["waste"], "%d%%" % model.js_round(x["sellOut"] * 100)])
    print(text_table(["Plan", "Profit", "Sold", "Left over", "Sell out"], rows))
    print()
    S = cfg["stock"]
    print("Today, with %d units, each price is worth (expected takings less disposal, to the sell-by date):" % S)
    pick = sol["policy"][0][0][S]
    for j, d in enumerate(model.LADDER):
        print("  %-10s %s%s" % ("full price" if d == 0 else "%d%% off" % d, money(sol["Q"][0][j][S]), "   <- best" if j == pick else ""))
    print()
    best = cmp["rows"][0]["result"]
    print("Following the best plan, units left at the start of each day (middle outcome, and the range 8 times in 10):")
    path = ["%s %d (%d-%d)" % (model.DAY_NAMES[(cfg["startDay"] + t) % 7], d["p50"], d["p10"], d["p90"]) for t, d in enumerate(best["days"])]
    path.append("end %d (%d-%d)" % (best["leftoverP50"], best["leftoverP10"], best["leftoverP90"]))
    print("  " + ", ".join(path))
    print()
    print("The ladder: best discount by units left (rows) and day (columns), before any markdown")
    days = [model.DAY_NAMES[(cfg["startDay"] + t) % 7] for t in range(cfg["days"])]
    print(text_table(["Units"] + days, ladder_rows(sol)))
    print()
    card = model.shelf_card(sol)
    print("Shelf card: each morning, take the deepest discount whose stock threshold you reach")
    print(text_table(["Day"] + ["%d%% off at" % d for d in model.LADDER[1:]], report.card_rows(cfg, card)))
    print(report.card_note(card))
    return 0


def cmd_robust(args):
    cfg = model.normalise(config_from_args(args))
    cells = model.robustness(cfg)
    print("The plan is made with demand %.1f a day and price sensitivity %.1f." % (cfg["demand"], cfg["elasticity"]))
    print("Each cell: profit the plan loses when the truth is different, against the best plan with perfect knowledge.")
    print("'*' marks cases where the plan does worse than never discounting.")
    print()
    print(text_table(*report.robust_table(cells)))
    return 0


def cmd_range(args):
    try:
        products, warnings = report.load_range(args.file)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print("Could not read the range: %s" % exc, file=sys.stderr)
        return 2
    results = [report.plan_product(p) for p in products]
    print(report.range_text(results, warnings))
    try:
        if args.markdown:
            with open(args.markdown, "w", encoding="utf-8") as f:
                f.write(report.range_markdown(results))
            print("\nWrote %s" % args.markdown)
        if args.csv:
            with open(args.csv, "w", encoding="utf-8", newline="") as f:
                f.write(report.cards_csv(results))
            print("Wrote %s" % args.csv)
    except OSError as exc:
        print("Could not write the report: %s" % exc, file=sys.stderr)
        return 2
    return 0


def add_product_args(plan):
    """The settings that describe one product, shared by the plan and robust commands."""
    plan.add_argument("--preset", choices=list(model.PRESETS), help="start from an example product")
    plan.add_argument("--stock", type=int)
    plan.add_argument("--days", type=int, help="selling days until the sell-by date")
    plan.add_argument("--price", type=float, help="full price")
    plan.add_argument("--unit-cost", dest="unitCost", type=float)
    plan.add_argument("--waste-cost", dest="wasteCost", type=float, help="cost of throwing one away (negative if leftovers can be sold on)")
    plan.add_argument("--demand", type=float, help="average units a day at full price")
    plan.add_argument("--elasticity", type=float, help="price sensitivity")
    plan.add_argument("--freshness", type=float, help="%% of appeal lost per day as the stock ages")
    plan.add_argument("--start-day", dest="startDay", type=int, choices=range(7), help="0 = Monday")
    plan.add_argument("--pattern", choices=list(model.WEEK_PATTERNS))
    plan.add_argument("--allow-price-rises", action="store_true", help="let the price go back up after a markdown")


def build_parser():
    p = argparse.ArgumentParser(prog="python -m markdown_ladder", description="Plan the best markdowns for stock with a sell-by date.")
    sub = p.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="the best plan for one product, against simple rules")
    add_product_args(plan)
    plan.add_argument("--rule-pct", type=int, choices=model.LADDER[1:], default=30, help="discount for the simple rule")
    plan.add_argument("--rule-days", type=int, default=2, help="days left when the simple rule kicks in")
    plan.set_defaults(func=cmd_plan)

    robust = sub.add_parser("robust", help="score the plan when demand or price sensitivity differ from the forecast")
    add_product_args(robust)
    robust.set_defaults(func=cmd_robust)

    rng = sub.add_parser("range", help="plan every product in a CSV file (see examples/range.csv)")
    rng.add_argument("file")
    rng.add_argument("--markdown", help="also write a Markdown report to this file")
    rng.add_argument("--csv", help="also write every product's shelf card to this CSV file")
    rng.set_defaults(func=cmd_range)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
