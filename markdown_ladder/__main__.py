"""Command-line interface.

    python -m markdown_ladder plan --preset truffles      # best plan for one product
    python -m markdown_ladder plan --stock 80 --days 5    # ...or your own numbers
"""

import argparse
import sys

from . import model


def text_table(headers, rows):
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def money(x):
    return ("-" if x < 0 else "") + "£%.2f" % abs(x)


def step_label(j):
    return "full" if model.LADDER[j] == 0 else "-%d%%" % model.LADDER[j]


def config_from_args(args):
    cfg = dict(model.PRESETS[args.preset]) if args.preset else {}
    for name in model.FIELDS:
        value = getattr(args, name)
        if value is not None:
            cfg[name] = value
    if args.pattern:
        cfg["pattern"] = args.pattern
    if args.allow_price_rises:
        cfg["monotone"] = False
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
    cmp = model.compare_policies(cfg, {"pct": args.rule_pct, "daysLeft": args.rule_days})
    sol = cmp["solution"]
    pattern_names = {"flat": "same every day", "highStreet": "busy weekends", "office": "quiet weekends"}
    print("%d units, %d selling days from %s, full price %s, demand %.1f a day at full price (%s), price sensitivity %.1f" % (
        cfg["stock"], cfg["days"], model.DAY_NAMES[cfg["startDay"]], money(cfg["price"]), cfg["demand"],
        pattern_names[cfg["pattern"]], cfg["elasticity"]))
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
    print("The ladder: best discount by units left (rows) and day (columns), before any markdown")
    days = [model.DAY_NAMES[(cfg["startDay"] + t) % 7] for t in range(cfg["days"])]
    print(text_table(["Units"] + days, ladder_rows(sol)))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="python -m markdown_ladder", description="Plan the best markdowns for stock with a sell-by date.")
    sub = p.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="the best plan for one product, against simple rules")
    plan.add_argument("--preset", choices=list(model.PRESETS), help="start from an example product")
    plan.add_argument("--stock", type=int)
    plan.add_argument("--days", type=int, help="selling days until the sell-by date")
    plan.add_argument("--price", type=float, help="full price")
    plan.add_argument("--unit-cost", dest="unitCost", type=float)
    plan.add_argument("--waste-cost", dest="wasteCost", type=float, help="cost of throwing one away (negative if leftovers can be sold on)")
    plan.add_argument("--demand", type=float, help="average units a day at full price")
    plan.add_argument("--elasticity", type=float, help="price sensitivity")
    plan.add_argument("--start-day", dest="startDay", type=int, choices=range(7), help="0 = Monday")
    plan.add_argument("--pattern", choices=list(model.WEEK_PATTERNS))
    plan.add_argument("--allow-price-rises", action="store_true", help="let the price go back up after a markdown")
    plan.add_argument("--rule-pct", type=int, choices=model.LADDER[1:], default=30, help="discount for the simple rule")
    plan.add_argument("--rule-days", type=int, default=2, help="days left when the simple rule kicks in")
    plan.set_defaults(func=cmd_plan)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
