"""A self-contained HTML report for a sweep of one habit (no scripts, works offline)."""

import html

from . import model
from .report import f2, signed

SERIES = [
    ("backtest", "Pilot back-test", "#7b4fc9", ""),
    ("live", "Live after go-live", "#d9480f", ""),
    ("repaired_backtest", "Back-test after repairs", "#7b4fc9", "5 4"),
    ("repaired_live", "Live, repaired model", "#d9480f", "5 4"),
    ("ceiling", "Clean-data ceiling", "#1c7c74", "2 3"),
]


def _line_chart(means, label):
    w, h, l, r, t, b = 680, 320, 52, 20, 16, 46
    vals = [m[k] for m in means for k, *_ in SERIES if m[k] is not None]
    lo = int(min(vals) * 20) / 20.0
    hi = int(max(vals) * 20 + 0.9999) / 20.0
    if hi - lo < 0.1:
        hi = lo + 0.1
    xs = [m["level"] for m in means]
    x0, x1 = xs[0], xs[-1] if xs[-1] > xs[0] else xs[0] + 1

    def X(v):
        return l + (v - x0) / (x1 - x0) * (w - l - r)

    def Y(v):
        return t + (hi - v) / (hi - lo) * (h - t - b)

    parts = []
    g = lo
    while g <= hi + 1e-9:
        parts.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="#d9dce3" stroke-dasharray="2 3"/>' % (l, w - r, Y(g), Y(g)))
        parts.append('<text x="%.1f" y="%.1f" text-anchor="end">%.2f</text>' % (l - 6, Y(g) + 4, g))
        g += 0.05
    for v in xs:
        parts.append('<text x="%.1f" y="%.1f" text-anchor="middle">%d%%</text>' % (X(v), h - b + 18, round(v * 100)))
    parts.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % ((l + w - r) / 2, h - 6, html.escape(label)))
    for key, name, colour, dash in SERIES:
        pts = " ".join("%.1f,%.1f" % (X(m["level"]), Y(m[key])) for m in means if m[key] is not None)
        parts.append('<polyline fill="none" stroke="%s" stroke-width="2.5" stroke-dasharray="%s" points="%s"/>' % (colour, dash, pts))
        for m in means:
            if m[key] is not None:
                parts.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>' % (X(m["level"]), Y(m[key]), colour))
    desc = "; ".join("%s at %d%%: back-test %.2f, live %.2f, repaired back-test %.2f, repaired live %.2f" % (
        label, round(m["level"] * 100), m["backtest"], m["live"], m["repaired_backtest"], m["repaired_live"]) for m in means)
    return ('<svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s</svg>' % (w, h, html.escape(desc), "".join(parts)))


def sweep_html(result):
    d = [x for x in model.DEFECTS if x["key"] == result["habit"]][0]
    label = d["label"]
    s = result["settings"]
    others = ", ".join("%s %d%%" % (x["label"].lower(), round(s[x["key"]] * 100)) for x in model.DEFECTS if x["key"] != result["habit"])
    legend = "".join('<span><svg width="26" height="10" aria-hidden="true"><line x1="0" x2="26" y1="5" y2="5" stroke="%s" stroke-width="3" stroke-dasharray="%s"/></svg>%s</span>' % (c, dash, html.escape(n)) for _, n, c, dash in SERIES)
    rows = "".join(
        "<tr><td>%d%%</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s pts</td><td>%s pts</td></tr>" % (
            round(m["level"] * 100), f2(m["backtest"]), f2(m["live"]), signed(m["illusion"]), f2(m["repaired_backtest"]),
            f2(m["repaired_live"]), f2(m["ceiling"]), signed(m["bias"] * 100, 0), signed(m["repaired_bias"] * 100, 0))
        for m in result["means"])
    return """<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fit to train: sweep of %(label)s</title>
<style>
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #1b2130; background: #f4f5f8; margin: 0; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 40px; }
section { background: #fff; border: 1px solid #e1e4ea; border-radius: 12px; padding: 18px; margin-top: 16px; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 0 0 8px; }
p { color: #5a6273; margin: 0 0 8px; }
svg text { font-size: 12px; fill: #5a6273; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; color: #5a6273; }
.legend span { display: inline-flex; gap: 6px; align-items: center; }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%%; font-size: 14px; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; border-bottom: 1px solid #e1e4ea; text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: #5a6273; }
@media (prefers-color-scheme: dark) {
  body { background: #11141b; color: #e7eaf0; } section { background: #1a1f29; border-color: #2e3544; }
  p, th, .legend, svg text { color: #a3abba; fill: #a3abba; } th, td { border-color: #2e3544; }
}
</style></head>
<body><main>
<h1>Fit to train: %(label)s</h1>
<p>%(what)s Swept from 0%% to %(top)d%% on %(worlds)d synthetic worlds each (worlds %(first)d onwards, %(deals)s deals), with %(others)s. Numbers are averages across worlds.</p>
<section><h2>Ranking score (AUC) as the habit grows</h2>
%(chart)s
<div class="legend">%(legend)s</div></section>
<section><h2>The numbers</h2><div class="wrap"><table>
<thead><tr><th>Level</th><th>Back-test</th><th>Live</th><th>Illusion</th><th>Repaired back-test</th><th>Repaired live</th><th>Ceiling</th><th>Win-rate bias</th><th>Repaired bias</th></tr></thead>
<tbody>%(rows)s</tbody></table></div>
<p>Win-rate bias is the live predicted win rate minus the actual one. How to fix this habit: %(fix)s</p></section>
<p>Synthetic data only. Simplified and illustrative.</p>
</main></body></html>
""" % {"label": html.escape(label), "what": html.escape(d["what"]), "top": round(result["levels"][-1] * 100),
       "worlds": result["worlds"], "first": (s["seed"] + 1) % 4294967296, "deals": "{:,}".format(s["deals"]),
       "others": html.escape(others), "chart": _line_chart(result["means"], label), "legend": legend, "rows": rows,
       "fix": html.escape(d["fix"])}

