"""Text and HTML reports for one session or a whole cohort."""

import html
import random

from .cohort import MEASURES, rule_label

PROFILE_ORDER = ["calibrated", "takes-advice", "holds-firm", "over", "under", "misplaced", "untested"]
PROFILE_LABELS = {
    "calibrated": "Calibrated partner", "takes-advice": "Open to good advice", "holds-firm": "Holds firm",
    "over": "Over-reliant", "under": "Under-reliant", "misplaced": "Second-guesser",
    "untested": "Not enough disagreements",
}
GROUP_COLOURS = ["#2b55c9", "#c2571a", "#1d7349", "#6a3db3", "#a3204f", "#3f6f7d"]


def pct(x):
    return "n/a" if x is None else "%d%%" % round(x * 100)


def signed_points(x):
    if x is None:
        return "n/a"
    v = round(x * 100)
    if v == 0:
        return "0 points"
    return "%+d %s" % (v, "point" if abs(v) == 1 else "points")


def session_text(session, result):
    """A plain-text summary of one scored session."""
    c = result["reliance"]["cells"]
    a = result["accuracy"]
    k = result["correct"]
    n = result["n"]
    cond = session.get("condition") or {}
    lines = [
        "Second opinion: session %s (advice: %s, feedback %s)" % (
            session.get("id", "unnamed"), cond.get("advice", "reason"), "on" if cond.get("feedback") else "off"),
        "",
        "Profile: %s%s" % (result["profile"]["label"], " (tentative)" if result["profile"]["tentative"] else ""),
        "  " + result["profile"]["summary"],
        "",
        "Accuracy",
    ]
    rows = [
        ("Part 1, on your own", k["before"], n["before"], a["before"]),
        ("Part 2, first answers", k["withInitial"], n["with"], a["withInitial"]),
        ("Part 2, checker alone", k["checker"], n["with"], a["checker"]),
        ("Part 2, final answers", k["withFinal"], n["with"], a["withFinal"]),
        ("Part 3, on your own", k["after"], n["after"], a["after"]),
    ]
    for label, right, total, acc in rows:
        lines.append("  %-24s %2d of %-2d  %s" % (label, right, total, pct(acc)))
    r = result["reliance"]
    lines += [
        "",
        "The moments that mattered",
        "  Checker right, you wrong:  switched %d of %d  (took good advice: %s)" % (
            c["checkerRight"]["corrected"], c["checkerRight"]["n"], pct(r["rair"])),
        "  You right, checker wrong:  held firm %d of %d  (resisted bad advice: %s)" % (
            c["checkerWrong"]["heldFirm"], c["checkerWrong"]["n"], pct(r["rsr"])),
        "  Both right: %d   Both wrong: %d" % (c["bothRight"]["n"], c["bothWrong"]["n"]),
        "  Gain over the better of you or the checker: %s" % signed_points(result["complementarity"]),
        "",
        "Confidence (share right against average confidence)",
    ]
    for label, key in [("Part 1", "before"), ("Part 2, first", "withInitial"),
                       ("Part 2, final", "withFinal"), ("Part 3", "after")]:
        cs = result["confidence"][key]
        if cs["n"]:
            lines.append("  %-14s %s right, %s sure, Brier %.3f" % (
                label, pct(cs["accuracy"]), pct(cs["meanConfidence"]), cs["brier"]))
    rp = result["replay"]
    if rp["n"]:
        lines += ["", "What if you had used a simple rule? (%d of %d right in fact)" % (rp["actual"]["correct"], rp["n"])]
        for rule in rp["rules"]:
            lines.append("  %2d of %d  %s%s" % (rule["correct"], rp["n"], rule_label(rule),
                                                "  <- best in hindsight" if rule is rp["best"] else ""))
    t = result["trust"]
    if t["firstErrorAt"] is not None:
        b, a = t["beforeFirstError"], t["afterFirstError"]
        lines += ["", "Trust over time: the checker's first mistake was its message %d." % t["firstErrorAt"],
                  "  Switched after disagreeing: %d of %d before it, %d of %d after it." % (
                      b["switched"], b["disagreements"], a["switched"], a["disagreements"])]
    lines += ["", "Solo change, part 3 minus part 1: %s" % signed_points(result["change"])]
    if not result["complete"]:
        lines.append("Note: the session is unfinished; only answered messages are counted.")
    return "\n".join(lines) + "\n"


def cohort_text(summary, comparisons=None):
    lines = ["Second opinion: cohort of %d people, grouped by %s" % (summary["people"], summary["by"]), ""]
    for g in summary["groups"]:
        lines.append("%s  (%d people)" % (g["name"], g["people"]))
        for key, label, _ in MEASURES:
            st = g["stats"][key]
            if st["mean"] is None:
                lines.append("  %-44s n/a" % label)
                continue
            interval = ""
            if st["low"] is not None:
                interval = "  [%s to %s]" % (_fmt(key, st["low"]), _fmt(key, st["high"]))
            lines.append("  %-44s %s%s  (n=%d)" % (label, _fmt(key, st["mean"]), interval, st["n"]))
        profile_bits = ["%s %d" % (PROFILE_LABELS[p], g["profiles"][p]) for p in PROFILE_ORDER if p in g["profiles"]]
        lines.append("  Profiles: " + ", ".join(profile_bits))
        rules = g["rules"]
        if rules["rules"]:
            lines.append("  Simple rules on the checker messages (average share right; people actually got %s):" % pct(rules["actual"]))
            for rule in rules["rules"][:3]:
                lines.append("    %s  %s" % (pct(rule["accuracy"]), rule["label"]))
        lines.append("")
    if comparisons:
        lines.append("Differences from %s (permutation tests)" % comparisons[0]["reference"])
        for c in comparisons:
            label = dict((k, l) for k, l, _ in MEASURES)[c["measure"]]
            if c["difference"] is None:
                lines.append("  %s, %s: not enough people" % (c["group"], label))
            else:
                lines.append("  %s, %s: %s (p = %.3f)" % (c["group"], label, signed_points(c["difference"]), c["p"]))
        lines.append("")
    return "\n".join(lines)


def _fmt(key, value):
    if key == "brierFinal":
        return "%.3f" % value
    if key in ("complementarity", "change"):
        return "%+.0f pts" % (value * 100)
    return pct(value)


def _forest(summary, key, label, colours):
    groups = summary["groups"]
    signed = key in ("complementarity", "change")
    lo_axis, hi_axis = (-0.5, 0.5) if signed else (0.0, 1.0)
    if key == "brierFinal":
        lo_axis, hi_axis = 0.0, 0.5
    width, left, right = 560, 190, 70
    row_h = 30
    height = 36 + row_h * len(groups)
    inner = width - left - right

    def x(v):
        v = max(lo_axis, min(hi_axis, v))
        return left + (v - lo_axis) / (hi_axis - lo_axis) * inner

    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s by group">' % (width, height, html.escape(label))]
    for tick in [lo_axis, (lo_axis + hi_axis) / 2, hi_axis]:
        parts.append('<line x1="%.1f" x2="%.1f" y1="8" y2="%d" class="grid"/>' % (x(tick), x(tick), height - 22))
        parts.append('<text x="%.1f" y="%d" text-anchor="middle" class="tick">%s</text>' % (
            x(tick), height - 6, html.escape(_fmt(key, tick))))
    for i, g in enumerate(groups):
        st = g["stats"][key]
        y = 22 + i * row_h
        parts.append('<text x="%d" y="%d" text-anchor="end" class="label">%s</text>' % (
            left - 10, y + 4, html.escape(g["name"])))
        if st["mean"] is None:
            parts.append('<text x="%d" y="%d" class="tick">no data</text>' % (left, y + 4))
            continue
        colour = colours[i % len(colours)]
        if st["low"] is not None:
            parts.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % (
                x(st["low"]), x(st["high"]), y, y, colour))
        parts.append('<circle cx="%.1f" cy="%d" r="6" fill="%s"/>' % (x(st["mean"]), y, colour))
        parts.append('<text x="%d" y="%d" class="value">%s</text>' % (width - right + 8, y + 4, html.escape(_fmt(key, st["mean"]))))
    parts.append("</svg>")
    return "".join(parts)


def _scatter(summary, colours):
    size, pad = 340, 44
    inner = size - pad - 14
    rng = random.Random(3)

    def x(v):
        return pad + v * inner

    def y(v):
        return 14 + (1 - v) * inner

    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Each person: took good advice against resisted bad advice">' % (size, size)]
    parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="frame"/>' % (x(0), y(1), inner, inner))
    parts.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" class="grid"/>' % (x(0.5), x(0.5), y(0), y(1)))
    parts.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" class="grid"/>' % (x(0), x(1), y(0.5), y(0.5)))
    for label, (qx, qy) in [("Calibrated", (0.75, 0.96)), ("Under-reliant", (0.25, 0.96)),
                            ("Over-reliant", (0.75, 0.03)), ("Second-guesser", (0.25, 0.03))]:
        parts.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="tick">%s</text>' % (x(qx), y(qy), label))
    for i, g in enumerate(summary["groups"]):
        colour = colours[i % len(colours)]
        for r in g["rows"]:
            if r["rair"] is None or r["rsr"] is None:
                continue
            jx = (rng.random() - 0.5) * 0.05
            jy = (rng.random() - 0.5) * 0.05
            parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" fill-opacity="0.55"/>' % (
                x(min(1, max(0, r["rair"] + jx))), y(min(1, max(0, r["rsr"] + jy))), colour))
    parts.append('<text x="%.1f" y="%d" text-anchor="middle" class="label">Took good advice</text>' % (x(0.5), size - 4))
    parts.append('<text transform="translate(14 %.1f) rotate(-90)" text-anchor="middle" class="label">Resisted bad advice</text>' % y(0.5))
    parts.append("</svg>")
    return "".join(parts)


def cohort_html(summary, comparisons=None, synthetic=False, title="Second opinion: cohort report"):
    colours = GROUP_COLOURS
    legend = "".join('<span><span class="sw" style="background:%s"></span>%s (%d)</span>' % (
        colours[i % len(colours)], html.escape(g["name"]), g["people"]) for i, g in enumerate(summary["groups"]))
    forests = "".join('<section class="card"><h3>%s</h3>%s</section>' % (html.escape(label), _forest(summary, key, label, colours))
                      for key, label, _ in MEASURES)
    profile_rows = []
    for g in summary["groups"]:
        cells = "".join("<td>%d</td>" % g["profiles"].get(p, 0) for p in PROFILE_ORDER)
        profile_rows.append("<tr><th scope=\"row\">%s</th>%s</tr>" % (html.escape(g["name"]), cells))
    profile_head = "".join("<th scope=\"col\">%s</th>" % html.escape(PROFILE_LABELS[p]) for p in PROFILE_ORDER)
    rules_html = ""
    rule_cards = []
    for i, g in enumerate(summary["groups"]):
        rules = g["rules"]
        if not rules["rules"]:
            continue
        items = "".join("<tr><td>%s</td><td>%s</td></tr>" % (html.escape(r["label"]), pct(r["accuracy"]))
                        for r in rules["rules"][:5])
        rule_cards.append('<div><h3><span class="sw" style="background:%s"></span>%s</h3>'
                          '<p class="muted">What people actually did: %s right on the checker messages.</p>'
                          '<div class="scroll"><table><thead><tr><th>Best simple rules</th><th>Right</th></tr></thead>'
                          '<tbody>%s</tbody></table></div></div>' % (
                              colours[i % len(colours)], html.escape(g["name"]), pct(rules["actual"]), items))
    if rule_cards:
        rules_html = ('<section class="card"><h2>Which simple rule would have served each group best?</h2>'
                      '<p class="muted">Each rule is replayed on every person\'s own first answers. A rule that wins on '
                      'average across a group is a fairer candidate for advice than one person\'s hindsight.</p>'
                      '<div class="forests">%s</div></section>') % "".join(rule_cards)
    comp_html = ""
    if comparisons:
        labels = dict((k, l) for k, l, _ in MEASURES)
        rows = []
        for c in comparisons:
            if c["difference"] is None:
                rows.append("<tr><td>%s</td><td>%s</td><td colspan=\"2\">not enough people</td></tr>" % (
                    html.escape(c["group"]), html.escape(labels[c["measure"]])))
            else:
                rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%.3f</td></tr>" % (
                    html.escape(c["group"]), html.escape(labels[c["measure"]]),
                    signed_points(c["difference"]), c["p"]))
        comp_html = ('<section class="card"><h2>Differences from %s</h2><p class="muted">Permutation tests on the '
                     'difference in group means. With several measures, expect some small p-values by chance.</p>'
                     '<div class="scroll"><table><thead><tr><th>Group</th><th>Measure</th><th>Difference</th><th>p</th></tr>'
                     '</thead><tbody>%s</tbody></table></div></section>') % (html.escape(comparisons[0]["reference"]), "".join(rows))
    banner = ""
    if synthetic:
        banner = ('<p class="banner">These sessions are synthetic: made-up people generated by the toolkit to show '
                  'how the analysis works. They are not evidence about real behaviour.</p>')
    return """<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
:root { --bg:#f5f4ef; --card:#fff; --ink:#1c222b; --muted:#586271; --line:#dedbd1; }
@media (prefers-color-scheme: dark) { :root { --bg:#14171c; --card:#1d2128; --ink:#eceef2; --muted:#a3acba; --line:#343a45; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { margin: 0 0 6px; } h2 { margin: 0 0 8px; font-size: 1.2rem; } h3 { margin: 0 0 6px; font-size: 1rem; }
.muted { color: var(--muted); }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-top:16px; }
.grid { stroke: var(--line); } .frame { fill: none; stroke: var(--line); }
svg { width:100%%; height:auto; display:block; } svg text { fill: var(--ink); font-size: 12px; }
svg .tick { fill: var(--muted); font-size: 10.5px; } svg .value { font-weight: 700; }
.forests { display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 0 16px; }
.legend { display:flex; flex-wrap:wrap; gap:14px; } .sw { display:inline-block; width:12px; height:12px; border-radius:50%%; margin-right:6px; vertical-align:-1px; }
table { border-collapse: collapse; width: 100%%; font-size: 0.9rem; } th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
.scroll { overflow-x: auto; }
.banner { background:#fbf1d9; color:#5c4100; border-radius:10px; padding:10px 14px; }
.scatter { max-width: 420px; }
</style></head><body><main>
<h1>%(title)s</h1>
<p class="muted">%(people)d people, grouped by %(by)s. Dots are group means; lines are 95%% bootstrap intervals.</p>
%(banner)s
<div class="card"><div class="legend">%(legend)s</div></div>
<div class="forests">%(forests)s</div>
<div class="card"><h2>Where each person sits</h2><p class="muted">Each dot is one person (slightly jittered so overlapping people stay visible). People with no disagreements of one kind are left out.</p><div class="scatter">%(scatter)s</div></div>
<div class="card"><h2>Profiles</h2><div class="scroll"><table><thead><tr><th>Group</th>%(profile_head)s</tr></thead><tbody>%(profile_rows)s</tbody></table></div></div>
%(rules)s
%(comparisons)s
<p class="muted">Made with the Second opinion toolkit. RAIR is the share of correctable mistakes a person corrected after seeing the checker; RSR is the share of right answers they kept when the checker was wrong.</p>
</main></body></html>
""" % {
        "title": html.escape(title), "people": summary["people"], "by": html.escape(summary["by"]),
        "banner": banner, "legend": legend, "forests": forests, "scatter": _scatter(summary, colours),
        "profile_head": profile_head, "profile_rows": "".join(profile_rows), "comparisons": comp_html,
        "rules": rules_html,
    }
