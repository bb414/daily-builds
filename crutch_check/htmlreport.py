"""A self-contained HTML study report with inline SVG charts (no external files)."""

import html
import random

from .model import PROFILES, points
from .study import PROFILE_ORDER

CHECKER = "#eb6834"
CONTROL = "#2a78d6"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
MUTED = "#6b6964"


def _e(s):
    return html.escape(str(s))


def _pct(x):
    return "n/a" if x is None else "%d%%" % points(x)


def _pts(x):
    return "n/a" if x is None else "%+.1f pts" % (x * 100)


def _pval(p):
    return "n/a" if p is None else ("&lt; 0.001" if p < 0.001 else "%.3f" % p)


def _rounds_chart(an):
    w, h, left, right, top, bottom = 560, 280, 48, 150, 16, 36
    pw, ph = w - left - right, h - top - bottom
    xs = [left + pw * i / 2 for i in range(3)]

    def y(v):
        return top + ph * (1 - v)

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-labelledby="c1t">' % (w, h),
           '<title id="c1t">Share judged correctly in each round, by group</title>']
    for v in (0, 0.25, 0.5, 0.75, 1):
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (
            left, left + pw, y(v), y(v), AXIS if v == 0 else GRID))
        out.append('<text x="%d" y="%.1f" text-anchor="end" font-size="12" fill="%s">%d%%</text>' % (
            left - 8, y(v) + 4, MUTED, v * 100))
    for i, label in enumerate(("Round 1 (before)", "Round 2", "Round 3 (after)")):
        out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="12" fill="%s">%s</text>' % (
            xs[i], h - 12, MUTED, label))
    labels = []
    for arm, colour, name in (("checker", CHECKER, "With the checker"), ("control", CONTROL, "Without")):
        st = an["arms"][arm]
        vals = [st["pre"]["mean"], st["during"]["mean"], st["post"]["mean"]]
        if any(v is None for v in vals):
            continue
        pts = " ".join("%.1f,%.1f" % (xs[i], y(v)) for i, v in enumerate(vals))
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' % (pts, colour))
        for i, v in enumerate(vals):
            out.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="#fff" stroke-width="2">'
                       '<title>%s, round %d: %s</title></circle>' % (xs[i], y(v), colour, name, i + 1, _pct(v)))
        labels.append([y(vals[2]) + 4, "%s %s" % (name, _pct(vals[2]))])
    if len(labels) == 2 and abs(labels[0][0] - labels[1][0]) < 16:
        upper, lower = sorted(labels, key=lambda item: item[0])
        mid = (upper[0] + lower[0]) / 2
        upper[0], lower[0] = mid - 8, mid + 8
    for ly, text in labels:
        out.append('<text x="%.1f" y="%.1f" font-size="13" fill="#0b0b0b">%s</text>' % (xs[2] + 12, ly, _e(text)))
    out.append("</svg>")
    return "".join(out)


def _gain_chart(an):
    w, h, left, top, bottom = 560, 240, 140, 12, 34
    pw = w - left - 20
    rows = [("checker", CHECKER, "With the checker"), ("control", CONTROL, "Without")]
    lo, hi = -0.75, 0.75

    def x(v):
        return left + pw * (max(lo, min(hi, v)) - lo) / (hi - lo)

    band = (h - top - bottom) / 2
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-labelledby="c2t">' % (w, h),
           '<title id="c2t">Each person\'s change in accuracy from round 1 to round 3</title>']
    for v in (-0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75):
        out.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="%s" stroke-width="1"/>' % (
            x(v), x(v), top, h - bottom, AXIS if v == 0 else GRID))
        out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="12" fill="%s">%+d</text>' % (
            x(v), h - 12, MUTED, round(v * 100)))
    rng = random.Random(3)
    for k, (arm, colour, name) in enumerate(rows):
        cy = top + band * (k + 0.5)
        out.append('<text x="%d" y="%.1f" text-anchor="end" font-size="13" fill="#0b0b0b">%s</text>' % (
            left - 12, cy + 4, name))
        gains = [p["gain"] for p in an["participants"] if p["arm"] == arm and p["gain"] is not None]
        for g in gains:
            out.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" fill-opacity="0.45"/>' % (
                x(g), cy + rng.uniform(-band * 0.3, band * 0.3), colour))
        m = an["arms"][arm]["gain"]["mean"]
        if m is not None:
            out.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="#0b0b0b" stroke-width="3">'
                       '<title>%s: average change %s</title></line>' % (
                           x(m), x(m), cy - band * 0.38, cy + band * 0.38, name, _pts(m)))
    out.append("</svg>")
    return "".join(out)


def _scatter(an):
    pts = [(p["switchRate"], p["gain"]) for p in an["participants"]
           if p["arm"] == "checker" and p["switchRate"] is not None and p["gain"] is not None]
    if len(pts) < 3:
        return "<p>Not enough participants in the checker group who disagreed with it.</p>"
    w, h, left, top, bottom, right = 560, 280, 52, 14, 40, 16
    pw, ph = w - left - right, h - top - bottom

    def x(v):
        return left + pw * v

    def y(v):
        return top + ph * (0.75 - max(-0.75, min(0.75, v))) / 1.5

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-labelledby="c3t">' % (w, h),
           '<title id="c3t">How often each person switched to the checker, against their change in accuracy</title>']
    for v in (-0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75):
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/>' % (
            left, left + pw, y(v), y(v), AXIS if v == 0 else GRID))
        out.append('<text x="%d" y="%.1f" text-anchor="end" font-size="12" fill="%s">%+d</text>' % (
            left - 8, y(v) + 4, MUTED, round(v * 100)))
    for v in (0, 0.25, 0.5, 0.75, 1):
        out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="12" fill="%s">%d%%</text>' % (
            x(v), h - 22, MUTED, v * 100))
    out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="12" fill="%s">'
               'Share of disagreements where they switched to the checker</text>' % (left + pw / 2, h - 4, MUTED))
    for sx, gy in pts:
        out.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" fill-opacity="0.6" stroke="#fff" stroke-width="1">'
                   '<title>Switched on %s of disagreements, change %s</title></circle>' % (
                       x(sx), y(gy), CHECKER, _pct(sx), _pts(gy)))
    out.append("</svg>")
    return "".join(out)


def study_html(an, title="Crutch check: study report"):
    a, c = an["arms"]["checker"], an["arms"]["control"]
    r = an["reliance"]

    def effect(cmp):
        if cmp is None:
            return "<td colspan=4>Needs at least two complete sessions in each group</td>"
        lo, hi = cmp["ci"]
        return "<td>%s</td><td>%s to %s</td><td>%s</td><td>%s</td>" % (
            _pts(cmp["difference"]), _pts(lo), _pts(hi), _pval(cmp["p"]),
            "n/a" if cmp["g"] is None else "%.2f" % cmp["g"])

    rows_html = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (label, _pct(a[k]["mean"]), _pct(c[k]["mean"]))
        for k, label in (("pre", "Round 1 (before)"), ("during", "Round 2"), ("post", "Round 3 (after)")))
    rows_html += "<tr><td>Change, round 1 to round 3</td><td>%s</td><td>%s</td></tr>" % (
        _pts(a["gain"]["mean"]), _pts(c["gain"]["mean"]))

    def pair(arm, k1, k2):
        x, y = arm[k1]["mean"], arm[k2]["mean"]
        return "n/a" if x is None or y is None else "%.2f to %.2f" % (x, y)

    rows_html += "<tr><td>Sensitivity d&#8242;, round 1 to round 3</td><td>%s</td><td>%s</td></tr>" % (
        pair(a, "dPre", "dPost"), pair(c, "dPre", "dPost"))
    rows_html += "<tr><td>Leaning c, round 1 to round 3 (above 0 is trusting)</td><td>%s</td><td>%s</td></tr>" % (
        pair(a, "cPre", "cPost"), pair(c, "cPre", "cPost"))

    rel = ""
    if r:
        prof = "".join("<li>%s: %d</li>" % (_e(PROFILES[k]), r["profiles"][k]) for k in PROFILE_ORDER)
        corr = "" if r["switchGainR"] is None else (
            "<p>Correlation between how often people switched to the checker and their change from round 1 "
            "to round 3: <strong>r = %.2f</strong> (n = %d).</p>" % (r["switchGainR"], r["switchGainN"]))
        rel = """<section><h2>How the checker group used it</h2>
<div class="tiles">
<div class="tile"><span>Took good advice when they were wrong</span><b>%s</b></div>
<div class="tile"><span>Held firm when the checker was wrong</span><b>%s</b></div>
<div class="tile"><span>Followed the checker when it was wrong</span><b>%s</b></div>
<div class="tile"><span>Beat the checker on its own</span><b>%d of %d</b></div>
</div>
<p>Accuracy in round 2: first answers %s, the checker alone %s, final answers %s.</p>
<ul class="cols">%s</ul>
<h3>What if everyone had used one simple rule?</h3>
<p class="muted">Average accuracy on the round 2 messages under each rule, worked out from people's own first answers and the checker's advice.</p>
<table><tr><th>Rule</th><th>Average accuracy</th></tr>%s</table>
<h3>Reliance and learning</h3>%s%s</section>""" % (
            _pct(r["rair"]["mean"]), _pct(r["rsr"]["mean"]), _pct(r["overReliance"]["mean"]),
            r["beatChecker"], a["n"], _pct(r["initial"]["mean"]), _pct(r["checker"]["mean"]),
            _pct(r["final"]["mean"]), prof,
            "".join("<tr><td>%s</td><td>%s</td></tr>" % (_e(x["label"]), _pct(x["mean"])) for x in r["strategies"]),
            corr, _scatter(an))

    items = "".join(
        "<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _e(i["messageId"]), _e(i["truth"]), i["difficulty"], _e(i["label"]),
            "%s (n=%d)" % (_pct(i["aloneAccuracy"]), i["aloneN"]) if i["aloneN"] else "n/a",
            "%s (n=%d)" % (_pct(i["assistedAccuracy"]), i["assistedN"]) if i["assistedN"] else "n/a",
            "%d of %d" % (i["followedWrong"], i["checkerWrongN"]) if i["checkerWrongN"] else "n/a")
        for i in an["items"])

    return """<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
body{margin:0;background:#f9f9f7;color:#0b0b0b;font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:28px 0 10px}h3{font-size:16px;margin:18px 0 6px}
section{background:#fff;border:1px solid #e1e0d9;border-radius:14px;padding:18px 20px;margin-top:16px}
section>h2:first-child{margin-top:0}
table{border-collapse:collapse;width:100%%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #e1e0d9;vertical-align:top}
th{color:#52514e;font-weight:600}td{font-variant-numeric:tabular-nums}
svg{width:100%%;height:auto;max-width:600px;display:block;margin:8px 0}
.legend{display:flex;gap:16px;font-size:13px;color:#52514e}.legend i{display:inline-block;width:12px;height:12px;border-radius:50%%;margin-right:6px;vertical-align:-1px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.tile{border:1px solid #e1e0d9;border-radius:10px;padding:10px 12px}.tile span{display:block;font-size:13px;color:#52514e}.tile b{font-size:24px}
.muted{color:#6b6964}.cols{columns:2;font-size:14px}.wide{overflow-x:auto}
</style></head><body><main>
<h1>%(title)s</h1>
<p class="muted">%(complete)d complete sessions: %(nc)d with the checker, %(nk)d without. Left out: %(inc)d incomplete, %(dup)d duplicate.</p>
<section><h2>Accuracy before, during and after</h2>
<div class="legend"><span><i style="background:%(ck)s"></i>With the checker</span><span><i style="background:%(ct)s"></i>Without</span></div>
%(chart1)s
<table><tr><th>Share judged correctly</th><th>With the checker</th><th>Without</th></tr>%(rows)s</table>
<h3>Differences between the groups (with the checker minus without)</h3>
<div class="wide"><table><tr><th></th><th>Difference</th><th>95%% interval</th><th>Permutation p</th><th>Hedges' g</th></tr>
<tr><td>While using it (round 2)</td>%(during)s</tr>
<tr><td>Afterwards (change from round 1 to 3)</td>%(gain)s</tr></table></div>
<h3>Each person's change from round 1 to round 3</h3>
<p class="muted">Dots are people; the black line is the group average. Units are percentage points.</p>
%(chart2)s
</section>
%(rel)s
<section><h2>Message by message</h2><p class="muted">Sorted from hardest to easiest without the checker.</p>
<div class="wide"><table><tr><th>ID</th><th>Answer</th><th>Difficulty</th><th>Message</th><th>Right without checker</th><th>Right with checker</th><th>Followed the checker when wrong</th></tr>%(items)s</table></div>
</section>
<p class="muted">Intervals are percentile bootstrap intervals; p-values come from a permutation test on the group labels.</p>
</main></body></html>
""" % {
        "title": _e(title), "complete": an["complete"], "nc": a["n"], "nk": c["n"], "inc": an["incomplete"],
        "dup": an["duplicates"], "ck": CHECKER, "ct": CONTROL, "chart1": _rounds_chart(an), "rows": rows_html,
        "during": effect(an["during"]), "gain": effect(an["gain"]), "chart2": _gain_chart(an), "rel": rel,
        "items": items,
    }
