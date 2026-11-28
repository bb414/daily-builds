"""One HTML proof report for a whole folder of drafts, in the app's galley style.

The page is self-contained (no fonts, scripts or images fetched), prints well
and can be emailed or put on a shared drive.
"""

import html

from . import model as M

CSS = """
:root{--paper:#f7f1e2;--paper2:#efe6d0;--rule:#d6c8a8;--ink:#1f1b16;--ink2:#4b443a;--ink3:#776d5e;--red:#b8322a;
--redw:#f5dcd3;--blue:#285a9c;--bluew:#dbe6f3;--green:#2c7149;--greenw:#d8eadc;--amber:#a86d17;--desk:#2b221d}
*{box-sizing:border-box}
body{margin:0;background:var(--desk);color:var(--ink);font:15px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 40px}
header{color:#f3ead6;padding:6px 0 18px}
.slug{font:12px/1.4 ui-monospace,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;color:#c9b99c;border-bottom:1px solid rgba(243,234,214,.25);padding-bottom:8px;margin:0}
h1{font:400 54px/1 Georgia,'Times New Roman',serif;margin:16px 0 8px}
header p{margin:6px 0;max-width:60em}
.labels span{display:inline-block;margin:6px 8px 0 0;border:2px solid #ff8c73;color:#ffb3a3;border-radius:999px;padding:4px 10px;font:600 11px/1 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase}
.sheet{background:var(--paper);padding:20px 24px 26px;margin:0 0 18px;box-shadow:0 14px 30px -16px rgba(0,0,0,.7)}
.sheet h2{font:400 28px/1.15 Georgia,serif;margin:0 0 4px}
.sub{font:12px/1.4 ui-monospace,Menlo,monospace;color:var(--ink3);letter-spacing:.06em;text-transform:uppercase;margin:0 0 12px;border-bottom:1.5px solid var(--ink);padding-bottom:8px}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;font:600 11px/1.2 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);background:var(--paper2);padding:7px;border-bottom:1.5px solid var(--rule)}
td{padding:7px;border-bottom:1px solid var(--rule);vertical-align:top}
td.n{font-family:ui-monospace,Menlo,monospace;text-align:right;white-space:nowrap}
td.hot{color:var(--red);font-weight:700}
.q{display:grid;grid-template-columns:64px 1fr;gap:12px;padding:12px 0;border-top:1px solid var(--rule)}
.qy{width:50px;height:50px;border:2.5px solid var(--red);border-radius:50%;display:grid;place-items:center;color:var(--red);font:600 12px/1.1 ui-monospace,Menlo,monospace;text-align:center;transform:rotate(-8deg)}
.medium .qy{border-color:var(--amber);color:var(--amber)}
.qt{font:19px/1.45 Georgia,serif;margin:0}
mark{background:none;text-decoration:underline wavy var(--red);text-underline-offset:4px}
mark.leftover{background:var(--redw);text-decoration:line-through var(--red)}
mark.quote{background:var(--bluew);text-decoration:none}
mark.soft{text-decoration:underline dotted var(--ink3)}
ul.why{margin:6px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink2)}
ul.todo{margin:6px 0 0;padding-left:18px;font-size:13.5px}
.conflict{margin:8px 0 0;padding:7px 10px;border-left:4px solid var(--red);background:#fbe9e3;font-size:14px}
.refs li{margin:4px 0}
.prob{color:var(--red)} .warn{color:var(--amber)} .ok{color:var(--green)}
.empty{color:var(--ink3);font-style:italic}
.foot{color:#c9b99c;font-size:13px}
@media print{body{background:#fff}.sheet{box-shadow:none;border:1px solid #999;break-inside:avoid-page}header{color:#000}.slug,.foot{color:#444}}
"""

SOFT = {"date", "org", "person", "study", "url", "citation"}


def esc(s):
    return html.escape(str(s), quote=True)


def marked(text, spans):
    cuts = sorted(set([0, len(text)] + [s["start"] for s in spans] + [s["end"] for s in spans]))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        kinds = [s["kind"] for s in spans if s["start"] <= a and s["end"] >= b]
        piece = esc(text[a:b])
        if not kinds:
            out.append(piece)
            continue
        k = "leftover" if "leftover" in kinds else ("quote" if "quote" in kinds else ("soft" if all(x in SOFT for x in kinds) else "hard"))
        out.append('<mark class="%s" title="%s">%s</mark>' % (k, esc(", ".join(M.KIND_LABELS[x] for x in kinds)), piece))
    return "".join(out)


def claim_block(c):
    reasons = "".join("<li>%+d %s</li>" % (r["points"], esc(r["text"])) for r in c["reasons"])
    todo = "".join("<li>%s</li>" % esc(t) for t in c["checks"])
    conflict = ""
    if c["notes"]["status"] == "conflict":
        bits = ["Your note: \u201c%s\u201d" % esc(it["note"]) for it in c["notes"]["items"] if it["result"] == "conflict"]
        conflict = '<div class="conflict"><strong>Your notes disagree.</strong> %s</div>' % " ".join(bits)
    return ('<div class="q %s"><div class="qy">Qy<br>%d</div><div><p class="qt">%s</p>%s<ul class="todo">%s</ul>'
            '<ul class="why">%s</ul></div></div>') % (c["level"], c["q"], marked(c["text"], c["spans"]), conflict, todo, reasons)


def file_section(item):
    name, a = item["name"], item.get("analysis")
    if item.get("error"):
        return '<section class="sheet"><h2>%s</h2><p class="sub">Not read</p><p class="prob">%s</p></section>' % (esc(name), esc(item["error"]))
    s = M.summarise(a, {}, {})
    parts = ['<section class="sheet" id="%s"><h2>%s</h2><p class="sub">%s checked \u00b7 %s \u00b7 %d high, %d medium, %d low</p>' % (
        esc(item["anchor"]), esc(name), "final version" if a["hasFinal"] else "draft", M.plural(a["words"], "word"), s["high"], s["medium"], s["low"])]
    if a["messages"]:
        parts.append("<p>%s</p>" % esc(" ".join(a["messages"])))
    if a["changes"]:
        ch = a["changes"]
        parts.append("<p><strong>%d%%</strong> of the final text is the AI draft's wording, word for word; %d of %d sentences kept, %d your own, %d AI sentences cut.</p>"
                     % (ch["keptShare"], ch["counts"]["kept"], ch["finalSentences"], ch["counts"]["yours"], ch["counts"]["dropped"]))
    shown = [a["claims"][q - 1] for q in a["ranked"] if a["claims"][q - 1]["level"] != "low"]
    if shown:
        parts.append("".join(claim_block(c) for c in shown))
    else:
        parts.append('<p class="empty">No high or medium risk statements.</p>')
    low = [a["claims"][q - 1] for q in a["ranked"] if a["claims"][q - 1]["level"] == "low"]
    if low:
        parts.append("<p>%s also flagged at low risk: %s.</p>" % (M.plural(len(low), "statement"), esc(", ".join("Qy %d" % c["q"] for c in low))))
    refs = a["refs"]
    if refs["entries"] or refs["missing"]:
        items = []
        for r in refs["entries"]:
            if r["verdict"] == "ok":
                continue
            cls = "prob" if r["verdict"] in ("fix", "suspect") else "warn"
            label = {"suspect": "Look it up by hand", "fix": "Needs fixing", "warn": "Worth a look"}[r["verdict"]]
            items.append('<li><span class="%s"><strong>%s:</strong></span> %s <br><small>%s</small></li>' % (
                cls, label, esc(r["entry"]["text"]), esc(" ".join(x["text"] for x in r["issues"]))))
        for m in refs["missing"]:
            items.append('<li><span class="prob"><strong>Cited but not listed:</strong></span> %s</li>' % esc(m["text"]))
        parts.append("<h3>References (%s, %d to look at)</h3><ul class=\"refs\">%s</ul>" % (
            M.plural(len(refs["entries"]), "entry", "entries"), refs["flagged"] + len(refs["missing"]), "".join(items) or '<li class="ok">Nothing flagged.</li>'))
    parts.append("</section>")
    return "".join(parts)


def batch_report(items, folder, as_of):
    rows = []
    for it in items:
        if it.get("error"):
            rows.append('<tr><td><a href="#%s">%s</a></td><td colspan="7" class="hot">%s</td></tr>' % (esc(it["anchor"]), esc(it["name"]), esc(it["error"])))
            continue
        a = it["analysis"]
        s = M.summarise(a, {}, {})
        share = "%d%%" % a["changes"]["keptShare"] if a["changes"] else "\u2013"
        rows.append(('<tr><td><a href="#%s">%s</a></td><td class="n">%d</td><td class="n">%d</td><td class="n%s">%d</td><td class="n%s">%d</td>'
                     '<td class="n%s">%d</td><td class="n%s">%d</td><td class="n">%s</td></tr>') % (
            esc(it["anchor"]), esc(it["name"]), a["words"], s["claims"], " hot" if s["high"] else "", s["high"], " hot" if s["leftovers"] else "",
            s["leftovers"], " hot" if s["conflicts"] else "", s["conflicts"], " hot" if s["refFlagged"] + s["refMissing"] else "",
            s["refFlagged"] + s["refMissing"], share))
    table = ('<table><thead><tr><th>File</th><th>Words</th><th>Flagged</th><th>High risk</th><th>AI leftovers</th><th>Notes disagree</th>'
             '<th>References to look at</th><th>AI wording kept</th></tr></thead><tbody>%s</tbody></table>') % "".join(rows)
    return ("<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Checked by me: batch report</title><style>%s</style></head><body><div class=\"wrap\"><header><p class=\"slug\">Checked by me \u00b7 batch proof report \u00b7 %s \u00b7 %s</p>"
            "<h1>%s checked</h1><p>Every statement worth checking in each file, ranked by risk, with why it was flagged and what to look up. "
            "The rules are the same as the browser app's.</p><div class=\"labels\"><span>Checks nothing online</span><span>Not a plagiarism detector</span></div></header>"
            "<section class=\"sheet\"><h2>Summary</h2><p class=\"sub\">%s</p>%s</section>%s<p class=\"foot\">Made by the Checked by me companion. Marking a statement verified "
            "is for you to do, against the original source.</p></div></body></html>\n") % (
        CSS, esc(folder), esc(M.long_day(as_of)), esc(M.plural(len(items), "file")), esc(M.plural(len(items), "file")), table,
        "".join(file_section(it) for it in items))
