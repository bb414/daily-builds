"""Text, Markdown and CSV output, and planning a whole product range from a CSV file."""

import csv
import io
import math

from . import model

RANGE_COLUMNS = ["name"] + list(model.FIELDS) + ["pattern"]
REQUIRED = ["name", "stock", "days", "price", "demand"]


def money(x):
    return ("-" if x < 0 else "") + "£%.2f" % abs(x)


def text_table(headers, rows):
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def day_name(cfg, t):
    return model.DAY_NAMES[(cfg["startDay"] + t) % 7]


def card_rows(cfg, card):
    return [[day_name(cfg, r["day"]) + (" (today)" if r["day"] == 0 else "")] +
            ["-" if v is None else "%d+" % v for v in r["from"][1:]] for r in card["rows"]]


def card_note(card):
    if abs(card["gap"]) < 0.005:
        note = "Following the card earns exactly what the full plan earns (%s)." % money(card["profit"])
    else:
        note = "Following the card earns %s, %s less than the full plan." % (money(card["profit"]), money(card["gap"]))
    if not card["exact"]:
        note += " For these numbers more stock does not always mean a deeper discount, so the card simplifies the plan."
    return note


def robust_table(cells):
    headers = ["Price sensitivity"] + ["demand " + ("as planned" if f == 1 else "%d%%" % model.js_round(f * 100)) for f in model.ROBUST_DEMAND]
    rows = []
    for g in model.ROBUST_ELASTICITY:
        row = ["as planned" if g == 1 else "%d%%" % model.js_round(g * 100)]
        for f in model.ROBUST_DEMAND:
            c = next(x for x in cells if x["demandFactor"] == f and x["elasticityFactor"] == g)
            share = c["planned"] / c["ideal"] if c["ideal"] > 0 else (1.0 if c["planned"] >= c["ideal"] - 1e-9 else 0.0)
            row.append("%d%%%s" % (model.js_round(share * 100), " *" if c["planned"] < c["never"] - 0.005 else ""))
        rows.append(row)
    return headers, rows


def load_range(path):
    """Read a product range. Each row is one product; missing optional columns use the defaults."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("%s is empty" % path)
        missing = [c for c in REQUIRED if c not in reader.fieldnames]
        if missing:
            raise ValueError("%s is missing the column(s): %s" % (path, ", ".join(missing)))
        products = []
        for n, row in enumerate(reader, 2):
            cells = {k: v.strip() for k, v in row.items() if isinstance(k, str) and isinstance(v, str)}
            if not any(cells.values()):
                continue
            raw = {k: cells[k] for k in RANGE_COLUMNS if cells.get(k)}
            notes = []
            cfg = model.normalise(raw)
            for k in model.FIELDS:
                if k in raw:
                    v = model.js_number(raw[k])
                    f = model.FIELDS[k]
                    if not math.isfinite(v):
                        notes.append("%s %r is not a number, used %s" % (k, raw[k], cfg[k]))
                    elif abs(v - cfg[k]) > 1e-9:
                        notes.append("%s %s changed to %s (allowed %s to %s%s)" % (
                            k, raw[k], cfg[k], f["min"], f["max"], ", whole numbers" if f["step"] == 1 else ""))
            if "pattern" in raw and raw["pattern"] != cfg["pattern"]:
                notes.append("pattern %r is unknown, used flat" % raw["pattern"])
            products.append({"name": raw.get("name") or "row %d" % n, "cfg": cfg, "notes": notes})
        if not products:
            raise ValueError("%s has no products" % path)
        return products


def plan_product(product):
    cmp = model.compare_policies(product["cfg"])
    sol = cmp["solution"]
    rows = {r["key"]: r for r in cmp["rows"]}
    rules = [rows["never"], rows["lastDay"], rows["rule"]]
    best_rule = max(rules, key=lambda r: r["result"]["profit"])
    j = sol["policy"][0][0][sol["cfg"]["stock"]]
    return {
        "name": product["name"], "notes": product.get("notes", []), "cfg": sol["cfg"],
        "best": rows["optimal"]["result"], "never": rows["never"]["result"], "bestRule": best_rule,
        "card": model.shelf_card(sol), "firstMove": "full price" if j == 0 else "%d%% off" % model.LADDER[j],
    }


def _summary_rows(results):
    rows = []
    for r in results:
        rows.append([r["name"], str(r["cfg"]["stock"]), str(r["cfg"]["days"]), money(r["best"]["profit"]),
                     money(r["best"]["profit"] - r["never"]["profit"]), money(r["best"]["profit"] - r["bestRule"]["result"]["profit"]),
                     "%.1f" % r["never"]["waste"], "%.1f" % r["best"]["waste"], r["firstMove"]])
    return rows


SUMMARY_HEADERS = ["Product", "Stock", "Days", "Best plan", "vs never", "vs best rule", "Left (never)", "Left (plan)", "Today"]


def _totals(results):
    uplift = sum(r["best"]["profit"] - r["never"]["profit"] for r in results)
    rule_uplift = sum(r["best"]["profit"] - r["bestRule"]["result"]["profit"] for r in results)
    saved = sum(r["never"]["waste"] - r["best"]["waste"] for r in results)
    wasted = sum(r["never"]["waste"] for r in results)
    return uplift, rule_uplift, saved, wasted


def range_text(results):
    uplift, rule_uplift, saved, wasted = _totals(results)
    out = [text_table(SUMMARY_HEADERS, _summary_rows(results)), ""]
    out.append("Across the range, the plans add %s of expected profit over never discounting and %s over the best simple rule for each product." % (
        money(uplift), money(rule_uplift)))
    if wasted > 0:
        out.append("They cut expected leftovers from %.1f to %.1f units (%d%% fewer)." % (wasted, wasted - saved, model.js_round(saved / wasted * 100)))
    notes = [(r["name"], n) for r in results for n in r["notes"]]
    if notes:
        out.append("")
        out.append("Adjusted inputs:")
        out.extend("  %s: %s" % (name, n) for name, n in notes)
    return "\n".join(out)


def _md(text):
    return str(text).replace("|", "\\|")


def range_markdown(results):
    uplift, rule_uplift, saved, wasted = _totals(results)
    out = ["# Markdown plans for the range", "",
           "Expected figures under the demand model. Profit is takings less disposal; stock costs are the same whichever plan is used.", "",
           "| " + " | ".join(SUMMARY_HEADERS) + " |", "|" + "---|" * len(SUMMARY_HEADERS)]
    out += ["| " + " | ".join(_md(c) for c in row) + " |" for row in _summary_rows(results)]
    out += ["", "Together the plans add %s over never discounting and %s over the best simple rule for each product." % (money(uplift), money(rule_uplift))]
    if wasted > 0:
        out.append("Expected leftovers fall from %.1f to %.1f units." % (wasted, wasted - saved))
    out += ["", "## Shelf cards", "", "Each morning, count the stock and take the deepest discount whose threshold it reaches. Never move back up the ladder.", ""]
    for r in results:
        out += ["### " + _md(r["name"]), "", "| Day | " + " | ".join("%d%% off at" % d for d in model.LADDER[1:]) + " |", "|---|" + "---|" * (len(model.LADDER) - 1)]
        out += ["| " + " | ".join(row) + " |" for row in card_rows(r["cfg"], r["card"])]
        out += ["", card_note(r["card"]), ""]
    return "\n".join(out)


def cards_csv(results):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["product", "day", "weekday"] + ["pct%d_from_units" % d for d in model.LADDER[1:]])
    for r in results:
        for row in r["card"]["rows"]:
            w.writerow([r["name"], row["day"] + 1, day_name(r["cfg"], row["day"])] + ["" if v is None else v for v in row["from"][1:]])
    return buf.getvalue()
