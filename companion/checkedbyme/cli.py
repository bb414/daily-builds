"""Command line for the Checked by me companion.

    check     one draft (and optionally your final version): the ranked checklist
    batch     every draft in a folder, written up as one HTML proof report
    gate      exits non-zero while high-risk claims are unchecked (for a team's workflow)
    merge     several people's session logs into one log and a team declaration
    declare   the declaration from a saved project, as text or Markdown
    recheck   a new version of a saved project: what is new or edited since the last check
    diff      how much of a final version is still the AI draft's wording
    project   builds a project file the browser app can open

Run any command with --help for its options.
"""

import argparse
import datetime
import json
import os
import re
import sys
import textwrap

from . import model as M
from .files import DRAFT_SUFFIXES, ReadError, final_pairs, read_text, write_text
from .report import batch_report

LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def today():
    d = datetime.date.today()
    return M.days_from_civil(d.year, d.month, d.day)


def as_of_arg(value):
    if not value:
        return today()
    day = M.parse_date(value)["day"]
    if day is None:
        raise SystemExit('Could not read the date "%s". Use a form like 2026-11-28.' % value)
    return day


def wrap(text, indent=6, width=96):
    return textwrap.fill(text, width=width, initial_indent=" " * indent, subsequent_indent=" " * indent)


def load(path, label):
    if not path:
        return ""
    try:
        return read_text(path)
    except ReadError as err:
        raise SystemExit("%s: %s" % (label, err))


def print_checklist(a, show_all=False, out=None):
    out = out or sys.stdout
    s = M.summarise(a, {}, {})
    out.write("Checked the %s: %s, %s worth checking (%d high, %d medium, %d low).\n" % (
        "final version" if a["hasFinal"] else "draft", M.plural(a["words"], "word"), M.plural(s["claims"], "statement"),
        s["high"], s["medium"], s["low"]))
    for m in a["messages"]:
        out.write(wrap(m, 2) + "\n")
    for q in a["ranked"]:
        c = a["claims"][q - 1]
        if c["level"] == "low" and not show_all:
            continue
        out.write("\nQy %-3d %-6s score %d   %s\n" % (c["q"], c["level"].upper(), c["score"], ", ".join(M.KIND_LABELS[k] for k in c["kinds"])))
        out.write(wrap(c["text"]) + "\n")
        for it in c["notes"]["items"]:
            if it["result"] == "conflict":
                out.write(wrap("! Your notes: " + it["note"]) + "\n")
        for t in c["checks"]:
            out.write(wrap("- " + t, 6) + "\n")
    hidden = sum(1 for c in a["claims"] if c["level"] == "low")
    if hidden and not show_all:
        out.write("\n%s at low risk not shown (use --all).\n" % M.plural(hidden, "statement"))
    refs = a["refs"]
    if refs["entries"] or refs["missing"]:
        out.write("\nReferences: %s, %d flagged, %d look made up, %d cited but not listed.\n" % (
            M.plural(len(refs["entries"]), "entry", "entries"), refs["flagged"], refs["suspect"], len(refs["missing"])))
        for r in refs["entries"]:
            if r["verdict"] != "ok":
                out.write("  #%d %s: %s\n" % (r["number"], r["verdict"], M.clip(r["entry"]["text"], 80)))
                for x in r["issues"]:
                    out.write(wrap(x["text"], 8) + "\n")
        for m in refs["missing"]:
            out.write("  Cited but not listed: %s\n" % m["text"])
    if a["changes"]:
        ch = a["changes"]
        out.write("\nAI wording kept: %d%% of your final text word for word; %d sentences kept, %d edited, %d reworded, %d your own; %d AI sentences cut.\n" % (
            ch["keptShare"], ch["counts"]["kept"], ch["counts"]["edited"], ch["counts"]["reworded"], ch["counts"]["yours"], ch["counts"]["dropped"]))
    out.write("\nNothing was checked online. This is not a plagiarism detector.\n")


def analyse_paths(draft, final=None, notes=None, references=None, prompt=None, as_of=None):
    return M.analyse({"draft": load(draft, "Draft"), "final": load(final, "Final version"), "notes": load(notes, "Notes"),
                      "references": load(references, "Reference list"), "prompt": load(prompt, "Prompt"), "asOf": as_of})


# ---------------------------------------------------------------- commands

def cmd_check(args):
    as_of = as_of_arg(args.as_of)
    a = analyse_paths(args.draft, args.final, args.notes, args.references, args.prompt, as_of)
    print_checklist(a, args.all)
    if args.csv:
        write_text(args.csv, M.claims_csv(a, {}))
        print("Wrote the checklist to %s" % args.csv)
    if args.refs_csv:
        write_text(args.refs_csv, M.refs_csv(a, {}))
        print("Wrote the reference report to %s" % args.refs_csv)
    if args.json:
        write_text(args.json, json.dumps(a, indent=1, ensure_ascii=False) + "\n")
        print("Wrote the full analysis to %s" % args.json)
    return 0


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "file"


def cmd_batch(args):
    as_of = as_of_arg(args.as_of)
    if not os.path.isdir(args.folder):
        raise SystemExit("%s is not a folder." % args.folder)
    notes = load(args.notes, "Notes")
    pairs = final_pairs(args.folder)
    if not pairs:
        raise SystemExit("No drafts (%s) found in %s." % (", ".join(DRAFT_SUFFIXES), args.folder))
    items, csv_rows = [], []
    for name, draft, final in pairs:
        item = {"name": name + (" + " + os.path.basename(final) if final else ""), "anchor": slug(name)}
        try:
            item["analysis"] = M.analyse({"draft": read_text(draft), "final": read_text(final) if final else "", "notes": notes, "asOf": as_of})
        except ReadError as err:
            item["error"] = str(err)
            items.append(item)
            csv_rows.append([item["name"], "", "", "", "", "", "", "", str(err)])
            continue
        items.append(item)
        a = item["analysis"]
        s = M.summarise(a, {}, {})
        csv_rows.append([item["name"], str(a["words"]), str(s["claims"]), str(s["high"]), str(s["leftovers"]), str(s["conflicts"]),
                         str(s["refFlagged"] + s["refMissing"]), str(a["changes"]["keptShare"]) if a["changes"] else "", ""])
    write_text(args.out, batch_report(items, os.path.basename(os.path.abspath(args.folder)), as_of))
    print("Checked %s; the report is in %s" % (M.plural(len(items), "file"), args.out))
    for it, row in zip(items, csv_rows):
        print("  %-48s %s" % (M.clip(it["name"], 48), row[8] if row[8] else "%s flagged, %s high, %s references to look at" % (row[2], row[3], row[6])))
    if args.csv:
        write_text(args.csv, M.csv_text(["File", "Words", "Flagged", "High risk", "AI leftovers", "Notes disagree",
                                         "References to look at", "AI wording kept (%)", "Problem"], csv_rows))
        print("Wrote the summary to %s" % args.csv)
    return 0


def checklist_statuses(path, a):
    """Reads a checklist CSV (from the app or the check command) and matches its marks to sentences."""
    rows = M.parse_csv(M.clean_chars(load(path, "Checklist"), {}))["rows"]
    if not rows:
        return {}, 0
    header = [M.header_key(h) for h in rows[0]]
    if "sentence" not in header or "status" not in header:
        raise SystemExit('%s: needs "Sentence" and "Status" columns, as in the checklist the app downloads.' % path)
    si, ti = header.index("sentence"), header.index("status")
    ni = header.index("source or note") if "source or note" in header else -1
    by_text = {}
    for r in rows[1:]:
        if len(r) > max(si, ti):
            by_text[" ".join(M.words(r[si]))] = (r[ti].strip().lower(), r[ni] if 0 <= ni < len(r) else "")
    checks, matched = {}, 0
    for c in a["claims"]:
        hit = by_text.get(" ".join(M.words(c["text"])))
        if hit and hit[0] in M.STATUSES:
            matched += 1
            if hit[0] != "unchecked":
                checks[c["key"]] = {"status": hit[0], "note": hit[1]}
    return checks, matched


def gate_one(path, args, as_of):
    """Returns (label, blocking claims, unresolved references, problem text)."""
    if path.lower().endswith(".json"):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                p = M.read_project(fh.read())
        except OSError as err:
            return path, [], [], "could not open: %s" % (err.strerror or err)
        if not p["ok"]:
            return path, [], [], p["message"]
        a = M.analyse(dict(p["texts"], asOf=as_of))
        checks, ref_checks = p["checks"], p["refChecks"]
    else:
        try:
            a = M.analyse({"draft": read_text(path), "asOf": as_of})
        except ReadError as err:
            return path, [], [], str(err)
        checks, ref_checks = {}, {}
        if args.checklist:
            checks, _ = checklist_statuses(args.checklist, a)
    need = LEVEL_RANK[args.level]
    blocking = [c for c in a["claims"] if M.status_of(checks, c["key"]) == "unchecked"
                and (LEVEL_RANK[c["level"]] >= need or "leftover" in c["kinds"])]
    blocking.sort(key=lambda c: (-c["score"], c["q"]))
    refs = []
    if args.refs:
        refs = [r for r in a["refs"]["entries"] if r["verdict"] in ("fix", "suspect") and M.ref_status_of(ref_checks, r["entry"]["key"]) == "unchecked"]
    return path, blocking, refs, ""


def cmd_gate(args):
    as_of = as_of_arg(args.as_of)
    paths = []
    for p in args.paths:
        if os.path.isdir(p):
            found = sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".json"))
            if not found:
                print("%s: no project files (.json) in this folder" % p)
            paths.extend(found)
        else:
            paths.append(p)
    if not paths:
        print("Nothing to check.")
        return 2
    failed = errors = 0
    for path in paths:
        label, blocking, refs, problem = gate_one(path, args, as_of)
        if problem:
            errors += 1
            print("ERROR  %s: %s" % (label, problem))
            continue
        if blocking or refs:
            failed += 1
            print("HOLD   %s: %s unchecked at %s risk or above%s" % (
                label, M.plural(len(blocking), "statement"), args.level, ", %s to look at" % M.plural(len(refs), "reference") if args.refs else ""))
            for c in blocking[:args.show]:
                print(wrap("Qy %d (%s %d): %s" % (c["q"], c["level"], c["score"], M.clip(c["text"], 110)), 7))
            if len(blocking) > args.show:
                print("       ... and %d more" % (len(blocking) - args.show))
            for r in refs[:args.show]:
                print(wrap("Reference #%d (%s): %s" % (r["number"], r["verdict"], M.clip(r["entry"]["text"], 100)), 7))
        else:
            print("PASS   %s" % label)
    print("%s passed, %d held, %d could not be read." % (M.plural(len(paths) - failed - errors, "file"), failed, errors))
    if errors:
        return 2
    return 1 if failed else 0


def person_from_file(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"^(?:team[-_ ]?)?(?:session[-_ ]?)?(?:log[-_ ]?)", "", stem, flags=re.I)
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else os.path.basename(path)


def merge_logs(paths, assignment=""):
    """Reads several people's logs; returns (sessions, messages). Identical sessions logged by two people become one."""
    merged, index, messages = [], {}, []
    for path in paths:
        try:
            text = read_text(path)
        except ReadError as err:
            messages.append(str(err))
            continue
        r = M.parse_sessions(text)
        for m in r["messages"]:
            messages.append("%s: %s" % (os.path.basename(path), m))
        who = person_from_file(path)
        for s in M.sessions_for(r["sessions"], assignment):
            s = dict(s)
            if not s["person"]:
                s["person"] = who
            key = (s["date"], s["tool"].lower(), s["purpose"].lower(), s["prompt"].lower())
            if key in index:
                prev = index[key]
                names = [n.strip() for n in prev["person"].split(",")]
                if s["person"] not in names:
                    prev["person"] = ", ".join(names + [s["person"]])
                continue
            index[key] = s
            merged.append(s)
    return M.sort_sessions(merged), messages


def team_markdown(sessions, title, assignment, as_of):
    people = []
    for s in sessions:
        for n in s["person"].split(","):
            n = n.strip()
            if n and n not in people:
                people.append(n)
    tools = M.tools_used(sessions)
    lines = ["# Team declaration of AI use", ""]
    if title:
        lines.append("**Work:** " + M.md_escape(title) + "  ")
    if assignment:
        lines.append("**Assignment:** " + M.md_escape(assignment) + "  ")
    lines.append("**Team:** " + M.md_escape(M.list_and(people) if people else "not named") + "  ")
    lines.append("**Date:** " + M.long_day(as_of))
    lines.append("")
    if not sessions:
        lines.append("The team logged no use of AI tools for this work.")
    else:
        minutes = sum(int(s["minutes"]) for s in sessions if s["minutes"].isdigit())
        lines.append("The team used %s in %s%s. Each session is listed below, with what was kept, changed and checked." % (
            M.list_and(tools) if tools else "AI tools", M.plural(len(sessions), "session"), ", about %d minutes in all" % minutes if minutes else ""))
        lines.append("")
        lines.append("## Sessions")
        lines.append("")
        lines.append("| Date | Who | Tool | Purpose | What was used | What was changed | What was checked |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in sessions:
            cells = [M.long_day(s["day"]) if s.get("day") is not None else (s["date"] or "undated"), s["person"], s["tool"], s["purpose"],
                     s["used"], s["changed"], s["checked"]]
            lines.append("| " + " | ".join(M.md_escape(c) if c else "-" for c in cells) + " |")
        lines.append("")
        lines.append("## By person")
        lines.append("")
        for n in people:
            mine = [s for s in sessions if n in [x.strip() for x in s["person"].split(",")]]
            lines.append("- **%s:** %s (%s)" % (M.md_escape(n), M.plural(len(mine), "session"), M.md_escape(M.list_and(M.tools_used(mine)) or "no tool named")))
        lines.append("")
    lines.append("We each checked the parts we were responsible for and take joint responsibility for the content of this work, "
                 "including anything produced with AI help.")
    return "\n".join(lines) + "\n"


def cmd_merge(args):
    as_of = as_of_arg(args.as_of)
    sessions, messages = merge_logs(args.logs, args.assignment or "")
    for m in messages:
        print("  " + m)
    print("Merged %s from %s." % (M.plural(len(sessions), "session"), M.plural(len(args.logs), "log")))
    for s in sessions:
        print("  %-10s  %-18s  %-12s  %s" % (s["date"] or "undated", M.clip(s["person"], 18), M.clip(s["tool"], 12), M.clip(s["purpose"], 50)))
    if args.out_csv:
        write_text(args.out_csv, M.sessions_csv(sessions))
        print("Wrote the merged log to %s (the app can import it)" % args.out_csv)
    if args.out_md:
        write_text(args.out_md, team_markdown(sessions, args.title or "", args.assignment or "", as_of))
        print("Wrote the team declaration to %s" % args.out_md)
    return 0


def read_project_file(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            p = M.read_project(fh.read())
    except OSError as err:
        raise SystemExit("Could not open %s: %s" % (path, err.strerror or err))
    if not p["ok"]:
        raise SystemExit("%s: %s" % (path, p["message"]))
    return p


def cmd_declare(args):
    as_of = as_of_arg(args.as_of)
    p = read_project_file(args.project)
    if args.template:
        p["project"]["template"] = args.template
    a = M.analyse(dict(p["texts"], asOf=as_of))
    d = M.declaration(a, {"project": p["project"], "sessions": p["sessions"], "checks": p["checks"], "refChecks": p["refChecks"], "asOf": as_of})
    for w in d["warnings"]:
        print("Note: " + w, file=sys.stderr)
    text = M.declaration_text(d)
    if args.md:
        write_text(args.md, M.declaration_markdown(d))
        print("Wrote %s" % args.md, file=sys.stderr)
    if args.txt:
        write_text(args.txt, text)
        print("Wrote %s" % args.txt, file=sys.stderr)
    if not args.md and not args.txt:
        sys.stdout.write(text)
    return 0


def cmd_recheck(args):
    as_of = as_of_arg(args.as_of)
    p = read_project_file(args.project)
    texts = dict(p["texts"])
    field = "draft" if args.draft or not texts["final"].strip() else "final"
    old_text = texts[field]
    texts[field] = load(args.text, "New version")
    a = M.analyse(dict(texts, asOf=as_of))
    base = p["baseline"]["text"] or old_text
    when = p["baseline"]["on"] or "your last save"
    v = M.compare_versions(base, a, p["checks"])
    s = M.summarise(a, p["checks"], p["refChecks"])
    print("Compared with the version checked on %s: %s, %s, %s gone; %s unchanged (their marks still apply)." % (
        when, M.plural(len(v["newClaims"]), "new statement"), M.plural(len(v["changed"]), "edited statement"),
        M.plural(len(v["gone"]), "statement"), M.plural(len(v["unchanged"]), "statement")))
    for q in v["newClaims"]:
        c = a["claims"][q - 1]
        print("\nNEW     Qy %d (%s %d)" % (q, c["level"], c["score"]))
        print(wrap(c["text"]))
    for ch in v["changed"]:
        c = a["claims"][ch["q"] - 1]
        print("\nEDITED  Qy %d (%s %d)%s" % (ch["q"], c["level"], c["score"],
                                          ": was %s, check it again" % ch["status"] if ch["status"] != "unchecked" else ""))
        print(wrap(" ".join(("[-%s-]" % t) if op == "-" else (("{+%s+}" % t) if op == "+" else t) for op, t in ch["ops"])))
    for g in v["gone"]:
        print("\nGONE    " + ("(was %s) " % g["status"] if g["status"] != "unchecked" else ""))
        print(wrap(g["text"]))
    print("\n%s still unchecked, %d of them high risk." % (M.plural(s["unchecked"], "statement"), s["highUnchecked"]))
    if args.out:
        baseline = {"text": M.trim(texts["final"]) and texts["final"] or texts["draft"], "on": M.iso_day(as_of)} if args.record else p["baseline"]
        write_text(args.out, M.project_file({"project": p["project"], "texts": texts, "sessions": p["sessions"], "checks": p["checks"],
                                             "refChecks": p["refChecks"], "baseline": baseline, "asOf": as_of}))
        print("Wrote the updated project to %s%s" % (args.out, " and recorded this version as checked" if args.record else ""))
    return 0


def cmd_diff(args):
    as_of = as_of_arg(args.as_of)
    a = analyse_paths(args.draft, args.final, as_of=as_of)
    ch = a["changes"]
    if not ch:
        raise SystemExit("Both files need some text to compare.")
    print("%d%% of the %d words in the final text appear word for word in the AI draft (runs of %d or more words)." % (
        ch["keptShare"], ch["finalWords"], M.MIN_RUN))
    print("Sentences: %d kept, %d edited, %d reworded, %d your own; %d of the AI draft's cut." % (
        ch["counts"]["kept"], ch["counts"]["edited"], ch["counts"]["reworded"], ch["counts"]["yours"], ch["counts"]["dropped"]))
    marks = {"kept": "AI  ", "edited": "EDIT", "reworded": "REW ", "yours": "YOU "}
    for s in ch["sentences"]:
        print("  %s %3d%%  %s" % (marks[s["cls"]], M.pct(s["kept"], s["words"]), M.clip(s["text"], 84)))
    for d in ch["dropped"]:
        print("  CUT        %s" % M.clip(d["text"], 84))
    return 0


def cmd_project(args):
    as_of = as_of_arg(args.as_of)
    texts = {"draft": load(args.draft, "Draft"), "final": load(args.final, "Final version"), "notes": load(args.notes, "Notes"),
             "references": load(args.references, "Reference list"), "prompt": load(args.prompt, "Prompt")}
    sessions = []
    if args.sessions:
        r = M.parse_sessions(load(args.sessions, "Session log"))
        sessions = r["sessions"]
        for m in r["messages"]:
            print("  " + m)
    project = {"title": args.title or "", "assignment": args.assignment or "", "course": args.course or "", "institution": args.institution or "",
               "person": args.person or "", "date": "", "level": args.level, "template": args.template}
    write_text(args.out, M.project_file({"project": project, "texts": texts, "sessions": sessions, "checks": {}, "refChecks": {}, "asOf": as_of}))
    print("Wrote %s: open it in the app with Open project." % args.out)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="checked_by_me.py", description="Check AI-assisted writing before you hand it in: "
                                "claims to check, references, how much is still the AI's, and the declaration. Checks nothing online.")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="the ranked checklist for one draft")
    c.add_argument("draft", help="the AI's draft (.txt, .md, .html or .docx)")
    c.add_argument("--final", help="your final version, to check instead and compare with the draft")
    c.add_argument("--notes", help="your notes or sources, to compare figures and quotes against")
    c.add_argument("--references", help="a reference list, if it is not in the text")
    c.add_argument("--prompt", help="the prompt you gave the AI")
    c.add_argument("--all", action="store_true", help="also list low-risk statements")
    c.add_argument("--csv", help="write the checklist as CSV")
    c.add_argument("--refs-csv", help="write the reference report as CSV")
    c.add_argument("--json", help="write the full analysis as JSON")
    c.add_argument("--as-of", help="today's date for the year checks (default: today)")
    c.set_defaults(func=cmd_check)

    b = sub.add_parser("batch", help="check every draft in a folder into one HTML report")
    b.add_argument("folder")
    b.add_argument("--out", default="checked-by-me-report.html", help="the HTML report to write")
    b.add_argument("--csv", help="also write a one-line-per-file summary CSV")
    b.add_argument("--notes", help="notes to compare every draft against")
    b.add_argument("--as-of")
    b.set_defaults(func=cmd_batch)

    g = sub.add_parser("gate", help="exit 1 while high-risk claims are unchecked")
    g.add_argument("paths", nargs="+", help="project files (.json), folders of them, or drafts with --checklist")
    g.add_argument("--checklist", help="for a draft: the checklist CSV holding your marks")
    g.add_argument("--level", choices=["high", "medium", "low"], default="high", help="lowest risk that must be checked (default high)")
    g.add_argument("--refs", action="store_true", help="also hold while references that need fixing or look made up are unmarked")
    g.add_argument("--show", type=int, default=5, help="how many open statements to list per file")
    g.add_argument("--as-of")
    g.set_defaults(func=cmd_gate)

    m = sub.add_parser("merge", help="merge several people's session logs")
    m.add_argument("logs", nargs="+", help="session log CSVs, one per person")
    m.add_argument("--assignment", help="keep only sessions for this assignment")
    m.add_argument("--title", help="title of the joint work, for the team declaration")
    m.add_argument("--out-csv", help="write the merged log as CSV")
    m.add_argument("--out-md", help="write a team declaration in Markdown")
    m.add_argument("--as-of")
    m.set_defaults(func=cmd_merge)

    d = sub.add_parser("declare", help="the declaration from a saved project")
    d.add_argument("project", help="a project file saved by the app (.json)")
    d.add_argument("--template", choices=[t["id"] for t in M.TEMPLATES])
    d.add_argument("--md", help="write Markdown here")
    d.add_argument("--txt", help="write plain text here")
    d.add_argument("--as-of")
    d.set_defaults(func=cmd_declare)

    r = sub.add_parser("recheck", help="what is new or edited in a new version of a saved project")
    r.add_argument("project", help="a project file saved by the app (.json)")
    r.add_argument("text", help="the new version (.txt, .md, .html or .docx)")
    r.add_argument("--draft", action="store_true", help="the new text replaces the AI draft rather than the final version")
    r.add_argument("--out", help="write the project with the new version here")
    r.add_argument("--record", action="store_true", help="with --out: record the new version as checked")
    r.add_argument("--as-of")
    r.set_defaults(func=cmd_recheck)

    f = sub.add_parser("diff", help="how much of a final version is the AI draft's wording")
    f.add_argument("draft")
    f.add_argument("final")
    f.add_argument("--as-of")
    f.set_defaults(func=cmd_diff)

    j = sub.add_parser("project", help="build a project file the app can open")
    j.add_argument("--draft", required=True)
    for name in ("final", "notes", "references", "prompt", "sessions", "title", "assignment", "course", "institution", "person"):
        j.add_argument("--" + name)
    j.add_argument("--level", choices=[lv["id"] for lv in M.LEVELS], default="assisted")
    j.add_argument("--template", choices=[t["id"] for t in M.TEMPLATES], default="statement")
    j.add_argument("--out", required=True)
    j.add_argument("--as-of")
    j.set_defaults(func=cmd_project)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
