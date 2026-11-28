"""A class or team overview built from several people's saved project files.

For a teacher or team lead who has collected project files with their
owners' permission: how AI was used across the group, how much AI wording
ended up in the work, how much was checked, what was left open, and where a
declared level of AI use does not match the comparison. It shows counts, not
anyone's text, and names can be replaced by numbers.
"""

import os

from . import model as M
from .report import CSS, esc

LEVEL_WORDS = {"none": "No AI", "planning": "Ideas and planning only", "assisted": "AI-assisted drafting", "integrated": "AI text included"}


def median_share(values):
    if not values:
        return None
    v = sorted(values)
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else int((v[mid - 1] + v[mid]) / 2.0 + 0.5)


def project_row(path, as_of):
    """Reads one project file and works out the figures for its row; returns (row, None) or (None, problem)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            p = M.read_project(fh.read())
    except (OSError, UnicodeDecodeError) as err:
        return None, "could not read: %s" % err
    if not p["ok"]:
        return None, p["message"]
    a = M.analyse(dict(p["texts"], asOf=as_of))
    state = {"project": p["project"], "sessions": p["sessions"], "checks": p["checks"], "refChecks": p["refChecks"], "asOf": as_of}
    s = M.summarise(a, p["checks"], p["refChecks"])
    d = M.declaration(a, state)
    sessions = M.sessions_for(p["sessions"], p["project"]["assignment"])
    minutes = sum(int(x["minutes"]) for x in sessions if x["minutes"].isdigit())
    open_kinds = {}
    for c in a["claims"]:
        if M.status_of(p["checks"], c["key"]) == "unchecked":
            for k in c["kinds"]:
                open_kinds[k] = open_kinds.get(k, 0) + 1
    leftovers_open = s["leftovers"] - M.count_resolved(a, p["checks"], "leftover")
    suspect_open = sum(1 for r in a["refs"]["entries"] if r["verdict"] == "suspect" and M.ref_status_of(p["refChecks"], r["entry"]["key"]) == "unchecked")
    mismatch = [w for w in d["warnings"] if w.startswith("You chose")]
    return {
        "file": os.path.basename(path), "name": p["project"]["person"] or os.path.basename(path).split(".")[0],
        "title": p["project"]["title"], "level": p["project"]["level"] or "assisted", "sessions": len(sessions),
        "tools": M.tools_used(sessions), "purposes": [x["purpose"] for x in sessions if x["purpose"]], "minutes": minutes,
        "kept": a["changes"]["keptShare"] if a["changes"] else None, "words": a["words"], "claims": s["claims"], "resolved": s["resolved"],
        "high": s["high"], "highOpen": s["highUnchecked"], "leftoversOpen": leftovers_open, "conflicts": s["conflicts"],
        "refs": s["refs"], "refFlagged": s["refFlagged"], "refSuspect": s["refSuspect"], "suspectOpen": suspect_open, "refMissing": s["refMissing"],
        "refOpen": s["refUnresolved"], "ready": s["highUnchecked"] == 0 and leftovers_open == 0, "mismatch": mismatch,
        "openKinds": open_kinds,
    }, None


def collect(paths, as_of, anonymise=False):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".json"))
        else:
            files.append(p)
    rows, problems = [], []
    for f in files:
        row, problem = project_row(f, as_of)
        if problem:
            problems.append("%s: %s" % (os.path.basename(f), problem))
        else:
            rows.append(row)
    if anonymise:
        for i, r in enumerate(rows):
            r["name"] = "Person %d" % (i + 1)
            r["file"] = ""
    return rows, problems


def tally(items):
    counts, order = {}, []
    for x in items:
        k = x.strip()
        low = k.lower()
        if not low:
            continue
        if low not in counts:
            counts[low] = [k, 0]
            order.append(low)
        counts[low][1] += 1
    return sorted((counts[k] for k in order), key=lambda c: (-c[1], c[0].lower()))


def verb(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def observations(rows):
    n = len(rows)
    out = []
    if not n:
        return out
    ready = sum(1 for r in rows if r["ready"])
    out.append("%d of %d would pass the pre-submission gate: no high-risk statement or chat leftover left unchecked." % (ready, n))
    left = [r for r in rows if r["leftoversOpen"]]
    if left:
        out.append("%s text from the chat window (such as \"As of my last update\"). Worth showing how to spot and cut it."
                   % verb(len(left), "still contains", "still contain"))
    kinds = {}
    for r in rows:
        for k, v in r["openKinds"].items():
            kinds[k] = kinds.get(k, 0) + v
    if kinds:
        top = sorted(kinds.items(), key=lambda kv: (-kv[1], M.KIND_ORDER.index(kv[0])))[0]
        out.append("The kind of statement most often left unchecked: %s (%d open across the group)." % (M.KIND_LABELS[top[0]].lower(), top[1]))
    mism = [r for r in rows if r["mismatch"]]
    if mism:
        out.append("%d declared less AI use than the comparison with their AI draft shows (%s). A conversation, not an accusation: "
                   "the word-for-word share also counts common phrases." % (len(mism), ", ".join(r["name"] for r in mism)))
    sus = [r for r in rows if r["suspectOpen"]]
    if sus:
        out.append("%s references that look made up and that nobody has looked up yet. Practise finding a reference in the library catalogue."
                   % verb(len(sus), "has", "have"))
    conf = [r for r in rows if r["conflicts"]]
    if conf:
        out.append("%s figures or quotations that their own notes contradict." % verb(len(conf), "has", "have"))
    return out


def bars(items, total, cls=""):
    if not items:
        return '<p class="empty">None logged.</p>'
    rows = []
    for label, count in items:
        w = int(count * 100.0 / total + 0.5) if total else 0
        rows.append('<div class="bar-row"><span class="bl">%s</span><span class="bt"><i class="%s" style="width:%d%%"></i></span><span class="bn">%d</span></div>'
                    % (esc(label), cls, w, count))
    return "".join(rows)


EXTRA_CSS = """
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 6px}
.tile{border:1.5px solid var(--ink);padding:10px 12px;background:#fffaf0}
.tile b{display:block;font:400 38px/1 Georgia,serif}
.tile span{font:600 11px/1.3 ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3)}
.grid2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px}
.bar-row{display:grid;grid-template-columns:minmax(0,11em) minmax(0,1fr) 2.5em;gap:8px;align-items:center;margin:4px 0;font-size:14px}
.bt{height:14px;background:var(--paper2);border:1px solid var(--rule)}
.bt i{display:block;height:100%;background:var(--blue)}
.bt i.ai{background:#8f8676}
.bn{font-family:ui-monospace,Menlo,monospace;text-align:right}
ol.obs li{margin:6px 0}
td.ok{color:var(--green);font-weight:700}
@media (max-width:700px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.grid2{grid-template-columns:minmax(0,1fr)}.wrap{overflow-x:hidden}table{display:block;overflow-x:auto}}
"""


def cohort_report(rows, problems, label, as_of):
    n = len(rows)
    shares = [r["kept"] for r in rows if r["kept"] is not None]
    med = median_share(shares)
    tiles = [(str(n), "projects"), ("%s" % ("%d%%" % med if med is not None else "-"), "median AI wording kept"),
             ("%d of %d" % (sum(1 for r in rows if r["ready"]), n), "ready to submit"),
             (str(sum(r["highOpen"] for r in rows)), "high-risk statements open")]
    bins = []
    for lo in range(0, 100, 10):
        hi = lo + 9 if lo < 90 else 100
        bins.append(("%d-%d%%" % (lo, hi), sum(1 for x in shares if lo <= x <= hi)))
    tools = tally(t for r in rows for t in r["tools"])
    purposes = tally(p for r in rows for p in r["purposes"])[:8]
    levels = tally(LEVEL_WORDS.get(r["level"], r["level"]) for r in rows)
    trs = []
    for r in rows:
        trs.append(("<tr><td>%s</td><td>%s</td><td class=\"n\">%d</td><td>%s</td><td class=\"n\">%s</td><td class=\"n\">%d of %d</td>"
                    "<td class=\"n%s\">%d</td><td class=\"n%s\">%d</td><td class=\"n%s\">%d</td><td class=\"%s\">%s</td></tr>") % (
            esc(r["name"]), esc(LEVEL_WORDS.get(r["level"], r["level"])), r["sessions"], esc(", ".join(r["tools"]) or "-"),
            "%d%%" % r["kept"] if r["kept"] is not None else "-", r["resolved"], r["claims"], " hot" if r["highOpen"] else "", r["highOpen"],
            " hot" if r["leftoversOpen"] else "", r["leftoversOpen"], " hot" if r["refOpen"] + r["refMissing"] else "", r["refOpen"] + r["refMissing"],
            "ok" if r["ready"] and not r["mismatch"] else "hot", "Ready" if r["ready"] and not r["mismatch"] else
            ("Level does not match" if r["mismatch"] and r["ready"] else "Not yet")))
    table = ("<table><thead><tr><th>Who</th><th>Declared use</th><th>Sessions</th><th>Tools</th><th>AI wording kept</th><th>Statements checked</th>"
             "<th>High risk open</th><th>Chat leftovers</th><th>References to look at</th><th>Status</th></tr></thead><tbody>%s</tbody></table>") % "".join(trs)
    obs = "".join("<li>%s</li>" % esc(o) for o in observations(rows))
    probs = ("<p class=\"prob\">Not read: %s</p>" % esc("; ".join(problems))) if problems else ""
    return ("<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Checked by me: group overview</title><style>%s%s</style></head><body><div class=\"wrap\"><header><p class=\"slug\">Checked by me \u00b7 group overview \u00b7 %s \u00b7 %s</p>"
            "<h1>%s</h1><p>How AI was used across the group's saved projects, how much was checked, and what is still open. Counts only: nobody's text is shown.</p>"
            "<div class=\"labels\"><span>Checks nothing online</span><span>Not a plagiarism detector</span></div></header>"
            "<section class=\"sheet\"><h2>At a glance</h2><p class=\"sub\">%s</p><div class=\"tiles\">%s</div>%s</section>"
            "<section class=\"sheet\"><h2>Where to focus next</h2><p class=\"sub\">Worked out from the figures below</p><ol class=\"obs\">%s</ol></section>"
            "<section class=\"sheet\"><h2>How AI was used</h2><p class=\"sub\">From the session logs and declared levels</p><div class=\"grid2\"><div><h3>Tools (projects using each)</h3>%s"
            "<h3>Declared use</h3>%s</div><div><h3>Most common purposes (sessions)</h3>%s</div></div></section>"
            "<section class=\"sheet\"><h2>AI wording in the final text</h2><p class=\"sub\">Share of each final version found word for word in its AI draft (runs of %d words or more, citations left out)</p>%s</section>"
            "<section class=\"sheet\"><h2>Each project</h2><p class=\"sub\">One row per saved project</p>%s</section>"
            "<p class=\"foot\">Made by the Checked by me companion from saved project files. The checking itself was done, or not yet done, by each person.</p></div></body></html>\n") % (
        CSS, EXTRA_CSS, esc(label), esc(M.long_day(as_of)), esc(M.plural(n, "project") + " checked"), esc(label), "".join(
            "<div class=\"tile\"><b>%s</b><span>%s</span></div>" % (esc(v), esc(k)) for v, k in tiles), probs, obs,
        bars([(t[0], t[1]) for t in tools], n), bars([(t[0], t[1]) for t in levels], n),
        bars([(t[0], t[1]) for t in purposes], max([t[1] for t in purposes] or [1])), M.MIN_RUN, bars(bins, max(1, len(shares)), "ai"), table)


CSV_HEADER = ["Who", "File", "Title", "Declared use", "Sessions", "Tools", "Minutes", "AI wording kept (%)", "Words checked", "Statements",
              "Checked", "High risk", "High risk open", "Chat leftovers open", "Notes disagree", "References", "References to look at",
              "Look made up", "Look made up, not looked up", "Cited but not listed", "Ready", "Declared level does not match"]


def cohort_csv(rows):
    return M.csv_text(CSV_HEADER, [[r["name"], r["file"], r["title"], LEVEL_WORDS.get(r["level"], r["level"]), str(r["sessions"]),
                                    "; ".join(r["tools"]), str(r["minutes"]), "" if r["kept"] is None else str(r["kept"]), str(r["words"]),
                                    str(r["claims"]), str(r["resolved"]), str(r["high"]), str(r["highOpen"]), str(r["leftoversOpen"]),
                                    str(r["conflicts"]), str(r["refs"]), str(r["refOpen"] + r["refMissing"]), str(r["refSuspect"]), str(r["suspectOpen"]),
                                    str(r["refMissing"]), "yes" if r["ready"] else "no", "yes" if r["mismatch"] else "no"] for r in rows])
