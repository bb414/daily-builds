"""Text, CSV and HTML reports of a forecast value added run."""

import html

from .model import METHOD_IDS, METHODS

NAMES = {m["id"]: m["name"] for m in METHODS}
SHORT = {"naive": "Naive", "average": "Mov avg", "seasonal": "Last yr", "smoothing": "Smooth", "ai": "AI", "planner": "AI+plan"}
COLOURS = {"naive": "#8d939c", "average": "#5f7590", "seasonal": "#b08a4f",
           "smoothing": "#2f8f86", "ai": "#4b46c8", "planner": "#d0662a"}
MINUS = "−"


def pct1(x):
    return "n/a" if x is None else "%.1f%%" % (x * 100)


def signed(x, digits=1, unit=""):
    if x is None:
        return "n/a"
    if abs(x) < 10 ** (-digits) / 2:
        x = 0
    text = ("%." + str(digits) + "f") % abs(x) + unit
    return "+" + text if x > 0 else (MINUS + text if x < 0 else text)


def times100(x):
    return None if x is None else x * 100


def best_simple(methods):
    """The simple method with the lowest error (the first wins a tie), as in the app."""
    best = methods[0]
    for m in methods[:4]:
        if m["wape"] is not None and (best["wape"] is None or m["wape"] < best["wape"]):
            best = m
    return best


def headline(results):
    m = results["methods"]
    simple, ai, planner = best_simple(m), m[4], m[5]
    if ai["wape"] is None or simple["wape"] is None:
        return "There are no sales in the test year to compare the forecasts with."
    if ai["wape"] < simple["wape"]:
        text = "The AI model cuts forecast error from %s with the best simple method (%s) to %s." % (
            pct1(simple["wape"]), simple["name"].lower(), pct1(ai["wape"]))
    else:
        text = "The AI model does not beat the best simple method: %s error against %s for %s." % (
            pct1(ai["wape"]), pct1(simple["wape"]), simple["name"].lower())
    change = planner["fvaPrevious"] or 0
    if change < -0.0005:
        text += " Planners' overrides then give back %.1f points." % (-change * 100)
    elif change > 0.0005:
        text += " Planners' overrides take off another %.1f points." % (change * 100)
    else:
        text += " Planners' overrides make almost no difference."
    return text


def text_report(results, source="synthetic chain"):
    s = results["settings"]
    lines = ["Stairstep: forecast value added for the %s" % source, "", headline(results),
             "Worth using the AI on %d of %d products (it must beat the best simple method by %.1f points)."
             % (results["deployOn"], len(results["bySku"]), s["threshold"] * 100), "",
             "  %-20s %7s %7s %10s %10s %10s %8s" % ("Step", "Error", "Bias", "vs naive", "Unsold", "Lost", "Met")]
    for m in results["methods"]:
        lines.append("  %-20s %7s %7s %10s %10s %10s %8s" % (
            m["name"], pct1(m["wape"]), signed(times100(m["bias"]), 1, "%"), signed(times100(m["fvaNaive"])),
            "{:,}".format(m["waste"]), "{:,}".format(m["lost"]), pct1(m["fillRate"])))
    lines += ["", "By product (error; * marks the best simple method)",
              "  Columns: naive, moving average, same week last year, seasonal smoothing, AI model, AI plus planners."]
    lines.append("  %-20s" % "Product" + "".join("%9s" % SHORT[i] for i in METHOD_IDS) + "  Verdict with hindsight; chosen in advance")
    for sku in sorted(results["bySku"], key=lambda x: -(x["aiGain"] if x["aiGain"] is not None else -1)):
        cells = ""
        for i in METHOD_IDS:
            mark = "*" if i == sku["bestSimpler"] else " "
            cells += "%8s%s" % (pct1(sku["methods"][i]["wape"]), mark)
        if sku["verdict"] == "ai":
            verdict = "use the AI (%.1f points better)" % (sku["aiGain"] * 100)
        else:
            verdict = "keep %s" % NAMES[sku["bestSimpler"]].lower()
        chosen = "the AI model" if sku["chosen"] == "ai" else NAMES[sku["chosen"]].lower()
        lines.append("  %-20s%s  %s; %s" % (sku["name"][:20], cells, verdict, chosen))
    lines += ["", "Chosen in advance on the %d weeks before the test year: the AI for %d of %d products." % (
        results["validationWeeks"], results["chosenAi"], len(results["bySku"])),
        "  That mix scores %s, against %s for the AI everywhere and %s for the best simple method everywhere." % (
            pct1(results["mix"]["wape"]), pct1(results["methods"][4]["wape"]), pct1(best_simple(results["methods"])["wape"]))]
    lines += ["", "By kind of week (error)",
              "  %-18s %9s" % ("Week", "Forecasts") + "".join("%9s" % SHORT[i] for i in METHOD_IDS)]
    for kind, label in (("festival", "Festival weeks"), ("promo", "Promotion weeks"), ("ordinary", "Ordinary weeks")):
        row = results["byWeekType"][kind]
        lines.append("  %-18s %9s" % (label, "{:,}".format(row["naive"]["n"]))
                     + "".join("%9s" % pct1(row[i]["wape"]) for i in METHOD_IDS))
    lines += ["", "Planner overrides (change in error on the forecasts they touched; negative is better)"]
    labels = {"up": "Pushed up", "down": "Pushed down", "small": "Small (under 20%)", "large": "Large (20% or more)"}
    for k in ("up", "down", "small", "large"):
        g = results["overrides"][k]
        if g["n"]:
            lines.append("  %-20s %6s overrides  %s points  (%s before, %s after)" % (
                labels[k], "{:,}".format(g["n"]), signed(None if g["improved"] is None else -g["improved"] * 100),
                pct1(g["wapeBefore"]), pct1(g["wapeAfter"])))
        else:
            lines.append("  %-20s none" % labels[k])
    lines.append("  Keeping only downward overrides: %s (AI alone %s, every override %s)" % (
        pct1(results["downOnly"]["wape"]), pct1(results["methods"][4]["wape"]), pct1(results["methods"][5]["wape"])))
    return "\n".join(lines) + "\n"


def forecasts_csv(data, fc, path):
    """Every test-year forecast, in the same format as the app's download."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("product,store,week,actual," + ",".join(METHOD_IDS) + ",overridden\n")
        for p, rows in enumerate(data["sales"]):
            for s, y in enumerate(rows):
                for t in range(data["testStart"], data["weeks"]):
                    values = ["%.3f" % fc["forecasts"][m][p][s][t] for m in METHOD_IDS]
                    f.write(",".join([data["skus"][p]["id"], data["stores"][s]["id"], str(t + 1), str(y[t])]
                                     + values + ["1" if fc["overridden"][p][s][t] else "0"]) + "\n")


def _stairs_svg(methods):
    width, height, left, bottom, top = 640, 300, 10, 46, 30
    n = len(methods)
    slot = (width - 2 * left) / n
    top_value = max(m["wape"] or 0 for m in methods) * 1.1 or 1
    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">' % (
        width, height, html.escape(", ".join("%s %s" % (m["name"], pct1(m["wape"])) for m in methods)))]
    for i, m in enumerate(methods):
        h = (height - top - bottom) * (m["wape"] or 0) / top_value
        x = left + i * slot + 8
        y = height - bottom - h
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="%s"/>' % (
            x, y, slot - 16, h, COLOURS[m["id"]]))
        parts.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="v">%s</text>' % (x + (slot - 16) / 2, y - 8, pct1(m["wape"])))
        if i and m["fvaPrevious"] is not None:
            delta = -m["fvaPrevious"] * 100
            cls = "good" if delta < -0.05 else ("bad" if delta > 0.05 else "flat")
            parts.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="%s">%s</text>' % (
                x + (slot - 16) / 2, y - 24, cls, signed(delta)))
        words = m["name"].split(" ")
        cut = len(words) - 1 if len(m["name"]) > 10 else len(words)
        for k, line in enumerate([" ".join(words[:cut]), " ".join(words[cut:])]):
            if line:
                parts.append('<text x="%.1f" y="%d" text-anchor="middle" class="n">%s</text>' % (
                    x + (slot - 16) / 2, height - bottom + 18 + 15 * k, html.escape(line)))
    parts.append("</svg>")
    return "".join(parts)


def html_report(results, source="synthetic chain"):
    methods = results["methods"]
    rows = "".join(
        "<tr><th scope='row'><span class='sw' style='background:%s'></span>%s</th><td>%s</td><td>%s</td><td>%s</td>"
        "<td>%s</td><td>%s</td><td>%s</td></tr>" % (
            COLOURS[m["id"]], html.escape(m["name"]), pct1(m["wape"]), signed(times100(m["bias"]), 1, "%"),
            signed(times100(m["fvaNaive"])), "{:,}".format(m["waste"]), "{:,}".format(m["lost"]), pct1(m["fillRate"]))
        for m in methods)
    sku_rows = []
    for sku in sorted(results["bySku"], key=lambda x: -(x["aiGain"] if x["aiGain"] is not None else -1)):
        cells = ""
        for i in METHOD_IDS:
            cls = "best" if i == sku["bestSimpler"] else ("win" if i == "ai" and sku["verdict"] == "ai" else "")
            cells += "<td class='%s'>%s</td>" % (cls, pct1(sku["methods"][i]["wape"]))
        verdict = ("Use the AI (%.1f points better)" % (sku["aiGain"] * 100) if sku["verdict"] == "ai"
                   else "Keep %s" % NAMES[sku["bestSimpler"]].lower())
        chosen = "AI model" if sku["chosen"] == "ai" else NAMES[sku["chosen"]]
        sku_rows.append("<tr><th scope='row'>%s</th>%s<td class='verdict'>%s</td><td class='verdict'>%s</td></tr>" % (
            html.escape(sku["name"]), cells, html.escape(verdict), html.escape(chosen)))
    labels = {"up": "Pushed up", "down": "Pushed down", "small": "Small (under 20%)", "large": "Large (20% or more)"}
    ov_rows = "".join(
        "<tr><th scope='row'>%s</th><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            labels[k], "{:,}".format(g["n"]), pct1(g["wapeBefore"]), pct1(g["wapeAfter"]),
            signed(None if g["improved"] is None else -g["improved"] * 100) if g["n"] else "")
        for k, g in ((k, results["overrides"][k]) for k in ("up", "down", "small", "large")))
    s = results["settings"]
    settings_text = ", ".join("%s %s" % (k, v) for k, v in s.items())
    return """<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stairstep report</title>
<style>
:root { --bg:#f4f3ee; --card:#fff; --ink:#1b2129; --muted:#5a6371; --line:#dcd9cf; --good:#1b7347; --good-soft:#def2e6; --bad:#b23a2c; }
@media (prefers-color-scheme: dark) { :root { --bg:#13161b; --card:#1c2027; --ink:#eceef2; --muted:#a2abb8; --line:#343a45; --good:#6fd19c; --good-soft:#1c3427; --bad:#f08a7b; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { margin: 0 0 6px; } h2 { font-size: 1.15rem; margin: 0 0 8px; }
.muted { color: var(--muted); } .lead { font-size: 1.2rem; font-weight: 700; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-top:16px; }
.scroll { overflow-x:auto; } table { border-collapse:collapse; width:100%%; font-variant-numeric: tabular-nums; font-size: 0.9rem; }
th, td { padding:6px 6px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; } th:first-child { text-align:left; }
thead th { white-space:normal; vertical-align:bottom; }
td.verdict { text-align:left; white-space:normal; min-width:130px; } td.best { outline:2px solid var(--muted); outline-offset:-3px; } td.win { background:var(--good-soft); color:var(--good); font-weight:700; }
.sw { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; }
svg { width:100%%; height:auto; display:block; } svg text { fill:var(--ink); font-size:13px; }
svg .v { font-weight:700; } svg .n { fill:var(--muted); font-size:12px; } svg .good { fill:var(--good); font-weight:700; } svg .bad { fill:var(--bad); font-weight:700; } svg .flat { fill:var(--muted); }
</style></head><body><main>
<h1>Stairstep report</h1>
<p class="muted">Forecast value added for the %(source)s, over the last 52 weeks.</p>
<div class="card"><p class="lead">%(headline)s</p><p>Worth using the AI on %(deploy)d of %(nsku)d products.</p></div>
<div class="card"><h2>The stairstep</h2><p class="muted">Each bar is a step's error (WAPE). The number above it is the change from the step to its left: negative is better.</p>%(svg)s
<div class="scroll"><table><thead><tr><th>Step</th><th>Error</th><th>Bias</th><th>vs naive (pts)</th><th>Unsold units</th><th>Lost sales</th><th>Sales met</th></tr></thead><tbody>%(rows)s</tbody></table></div></div>
<div class="card"><h2>By product</h2><p class="muted">Outlined: the best simple method. Green: the AI beats it by at least %(threshold).1f points.</p>
<div class="scroll"><table><thead><tr><th>Product</th>%(heads)s<th>Verdict with hindsight</th><th>Chosen in advance</th></tr></thead><tbody>%(sku_rows)s</tbody></table></div>
<p>Chosen in advance on the %(val)d weeks before the test year, the AI would be used for %(chosen)d products. That mix scores %(mix)s, against %(ai)s for the AI everywhere.</p></div>
<div class="card"><h2>Planner overrides</h2><div class="scroll"><table><thead><tr><th>Overrides</th><th>Count</th><th>Error before</th><th>Error after</th><th>Change (pts)</th></tr></thead><tbody>%(ov_rows)s</tbody></table></div>
<p>Keeping only downward overrides: %(down)s error, against %(ai)s for the AI alone and %(planner)s with every override.</p></div>
<p class="muted">Settings: %(settings)s.</p>
</main></body></html>
""" % {
        "source": html.escape(source), "headline": html.escape(headline(results)), "deploy": results["deployOn"],
        "nsku": len(results["bySku"]), "svg": _stairs_svg(methods), "rows": rows,
        "threshold": s["threshold"] * 100, "heads": "".join("<th>%s</th>" % html.escape(NAMES[i]) for i in METHOD_IDS),
        "sku_rows": "".join(sku_rows), "ov_rows": ov_rows, "settings": html.escape(settings_text),
        "val": results["validationWeeks"], "chosen": results["chosenAi"], "mix": pct1(results["mix"]["wape"]),
        "ai": pct1(methods[4]["wape"]), "down": pct1(results["downOnly"]["wape"]), "planner": pct1(methods[5]["wape"]),
    }
