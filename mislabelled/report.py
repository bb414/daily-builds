"""Self-contained HTML reports with inline SVG charts (standard library only)."""

import html

from . import model as M

COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
DASHES = ["", "7 4", "2 3", "10 3 2 3", "4 4"]

STYLE = """
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #16150f;
       background: #f6f5f1; margin: 0; padding: 24px; }
main { max-width: 980px; margin: 0 auto; }
h1 { font-size: 1.8rem; margin: 0 0 6px; } h2 { font-size: 1.2rem; margin: 28px 0 6px; }
p { color: #4d4b45; max-width: 75ch; }
.card { background: #fcfcfb; border: 1px solid #dcdad3; border-radius: 12px; padding: 18px; margin-top: 16px; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; margin-top: 10px; }
th, td { padding: 6px 8px; border-top: 1px solid #e6e4dd; text-align: right; }
th:first-child, td:first-child { text-align: left; }
thead th { background: #f0efea; border-top: 0; }
svg text { fill: #4d4b45; font-size: 12px; font-family: inherit; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.85rem; color: #4d4b45; padding: 0; list-style: none; }
.note { font-size: 0.85rem; color: #6b6961; }
"""


def _swatch(i):
    dash = ' stroke-dasharray="%s"' % DASHES[i] if DASHES[i] else ""
    return ('<svg width="24" height="10" aria-hidden="true"><line x1="1" y1="5" x2="23" y2="5" stroke="%s" '
            'stroke-width="2.5"%s/></svg>' % (COLOURS[i], dash))


def _nice_max(v):
    steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]
    mag = 1.0
    while mag * 10 < v:
        mag *= 10
    while mag > v and mag > 1e-9:
        mag /= 10
    for s in steps:
        if s * mag >= v:
            return s * mag
    return 10 * mag


def line_chart(series, target, title, bands=None, width=760, height=320):
    """series: list of lists of y values (index = checks). bands: optional list of (lo, hi) lists."""
    L, R, T, B = 52, 16, 14, 40
    K = max(1, max(len(s) for s in series) - 1)
    ymax = max([target] + [v for s in series for v in s] + ([hi for b in (bands or []) for _, hi in b]))
    ymax = _nice_max(ymax if ymax > 0 else 1)

    def x(k):
        return L + (width - L - R) * k / K

    def y(v):
        return T + (height - T - B) * (1 - v / ymax)

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s" style="width:100%%;height:auto">' % (
        width, height, html.escape(title))]
    for i in range(6):
        v = ymax * i / 5
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e4dd"/>' % (L, width - R, y(v), y(v)))
        out.append('<text x="%d" y="%.1f" text-anchor="end">%s%%</text>' % (L - 8, y(v) + 4, ("%.1f" % v).rstrip("0").rstrip(".")))
    step = 5 if K <= 20 else 10 if K <= 60 else 20 if K <= 100 else 50
    for k in range(0, K + 1, step):
        out.append('<text x="%.1f" y="%d" text-anchor="middle">%d</text>' % (x(k), height - B + 18, k))
    out.append('<text x="%.1f" y="%d" text-anchor="middle">Checks answered</text>' % (L + (width - L - R) / 2, height - 4))
    if bands:
        for i, band in enumerate(bands):
            pts = ["%.1f,%.1f" % (x(k), y(hi)) for k, (_, hi) in enumerate(band)]
            pts += ["%.1f,%.1f" % (x(k), y(lo)) for k, (lo, _) in reversed(list(enumerate(band)))]
            out.append('<polygon points="%s" fill="%s" fill-opacity="0.10"/>' % (" ".join(pts), COLOURS[i]))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#4d4b45" stroke-dasharray="2 4" stroke-width="1.5"/>' % (
        L, width - R, y(target), y(target)))
    out.append('<text x="%d" y="%.1f" text-anchor="end">Target %g%%</text>' % (width - R, y(target) - 6, target))
    for i, s in enumerate(series):
        d = " ".join(("M" if k == 0 else "L") + "%.1f %.1f" % (x(k), y(v)) for k, v in enumerate(s))
        dash = ' stroke-dasharray="%s"' % DASHES[i] if DASHES[i] else ""
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round"%s/>' % (
            d, COLOURS[i], dash))
    out.append("</svg>")
    return "\n".join(out)


def _legend():
    return '<ul class="legend">%s</ul>' % "".join(
        "<li>%s %s</li>" % (_swatch(i), html.escape(s["label"])) for i, s in enumerate(M.STRATEGIES))


def _page(title, body):
    return ("<!DOCTYPE html>\n<html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>%s</title>"
            "<style>%s</style></head><body><main>%s</main></body></html>\n" % (html.escape(title), STYLE, body))


def write_compare_report(path, summary, meta):
    parts = ["<h1>Mislabelled: which checks fix a budgeting app fastest?</h1>",
             "<p>Five ways for a budgeting app to choose which payments to ask about, replayed on %d invented "
             "statement(s) per person (%d weeks each, up to %d checks, correction weight %d, slips %g%%). Lines are "
             "medians; shaded bands run from the 10th to the 90th percentile.</p>" % (
                 len(meta["seeds"]), meta["weeks"], meta["checks"], meta["weight"], meta["slip"]),
             '<p class="note">Invented people, shops and amounts. Educational, not financial advice.</p>']
    personas = []
    for s in summary:
        if s["persona"] not in personas:
            personas.append(s["persona"])
    for pid in personas:
        mine = [s for s in summary if s["persona"] == pid]
        parts.append('<section class="card"><h2>%s</h2>' % html.escape(M.PERSONAS[pid]["label"]))
        parts.append("<p>Median share of spending in the wrong pot on day one: <strong>%.1f%%</strong>.</p>" % mine[0]["dayOne"])
        parts.append(_legend())
        parts.append(line_chart([[c[1] for c in s["curve"]] for s in mine], meta["target"],
                                "Wrong pot after each check for " + M.PERSONAS[pid]["label"],
                                bands=[[(c[0], c[2]) for c in s["curve"]] for s in mine]))
        parts.append("<table><thead><tr><th>Strategy</th><th>Median checks to %g%%</th><th>Runs reaching it</th>"
                     "<th>Median after 10</th><th>Median at the end</th></tr></thead><tbody>" % meta["target"])
        for s in mine:
            med = "not reached" if s["medianChecks"] is None else "%g" % s["medianChecks"]
            parts.append("<tr><td>%s</td><td>%s</td><td>%.0f%%</td><td>%.1f%%</td><td>%.1f%%</td></tr>" % (
                html.escape(s["label"]), med, s["reachedShare"] * 100,
                s["curve"][min(10, len(s["curve"]) - 1)][1], s["curve"][-1][1]))
        parts.append("</tbody></table></section>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_page("Mislabelled strategy report", "\n".join(parts)))


def write_replay_report(path, results, meta):
    parts = ["<h1>Mislabelled: replay on %s</h1>" % html.escape(meta["file"]),
             "<p>%d payments. Day one, before any checks, %.1f%% of spending is in the wrong pot. Each line shows "
             "how fast one way of choosing checks brings that down.</p>" % (meta["n"], results[0]["points"][0]["misPct"]),
             '<p class="note">Educational, not financial advice.</p>', '<section class="card">', _legend(),
             line_chart([[p["misPct"] for p in r["points"]] for r in results], meta["target"], "Wrong pot after each check"),
             "<table><thead><tr><th>Strategy</th><th>Checks to %g%%</th><th>At the end</th></tr></thead><tbody>" % meta["target"]]
    for r in results:
        to = "not reached" if r["toTarget"] is None else str(r["toTarget"])
        parts.append("<tr><td>%s</td><td>%s</td><td>%.1f%%</td></tr>" % (html.escape(r["label"]), to, r["points"][-1]["misPct"]))
    parts.append("</tbody></table></section>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_page("Mislabelled replay report", "\n".join(parts)))
