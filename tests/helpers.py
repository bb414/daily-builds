"""Shared helpers for the Python tests: paths, the sample data and the Node bridge."""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.join(ROOT, "companion"))

from checkedbyme import model as M  # noqa: E402

NODE = shutil.which("node")
AS_OF = M.days_from_civil(2026, 11, 28)

PY_NAMES = {
    "analyse": M.analyse, "summarise": M.summarise, "parseDate": M.parse_date, "splitSentences": M.split_sentences,
    "parseSessions": M.parse_sessions, "readProject": M.read_project, "docxText": M.docx_text, "parseCsv": M.parse_csv,
    "readDocument": M.read_document, "scanSentence": M.scan_sentence, "findCitations": M.find_citations,
    "splitEntries": M.split_entries, "parseEntry": M.parse_entry, "words": M.words, "contentWords": M.content_words,
    "sentenceKey": M.sentence_key, "fnv": M.fnv, "cleanChars": M.clean_chars, "notesIndex": M.notes_index,
    "projectFile": M.project_file, "sessionsCsv": M.sessions_csv, "lcsOps": M.lcs_ops,
    "parseRis": M.parse_ris, "parseBibtex": M.parse_bibtex, "texText": M.tex_text,
}


def sample(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return fh.read()


def sample_input(final=True, notes=True, prompt=True):
    return {"draft": sample("ai-draft.md"), "final": sample("final-version.md") if final else "",
            "notes": sample("notes.md") if notes else "", "prompt": sample("prompt.txt") if prompt else "",
            "references": "", "asOf": AS_OF}


def py_outputs(inp, state=None):
    st = dict(state or {})
    st.setdefault("asOf", inp.get("asOf"))
    a = M.analyse(inp)
    sessions = [M.clean_session(s) for s in st.get("sessions", [])]
    out = {"summary": M.summarise(a, st.get("checks") or {}, st.get("refChecks") or {}),
           "claimsCsv": M.claims_csv(a, st.get("checks") or {}), "refsCsv": M.refs_csv(a, st.get("refChecks") or {}),
           "sessionsCsv": M.sessions_csv(sessions), "declarations": {}}
    for t in M.TEMPLATES:
        s2 = dict(st, project=dict(st.get("project") or {}, template=t["id"]), sessions=sessions)
        d = M.declaration(a, s2)
        out["declarations"][t["id"]] = {"text": M.declaration_text(d), "markdown": M.declaration_markdown(d), "warnings": d["warnings"]}
    out["projectFile"] = M.project_file(dict(st, texts={k: inp.get(k) for k in ("draft", "final", "prompt", "references", "notes")}))
    return out


def run_python(jobs):
    out = []
    for job in jobs:
        if job["fn"] == "outputs":
            out.append({"ok": py_outputs(*job["args"])})
        else:
            out.append({"ok": PY_NAMES[job["fn"]](*job["args"])})
    return json.loads(json.dumps(out))


def run_bridge(jobs):
    """Runs the jobs through the browser model under Node and returns its results."""
    proc = subprocess.run([NODE, os.path.join(ROOT, "tests", "js_bridge.js")], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8", timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


def first_difference(a, b, path=""):
    """Describes the first place two JSON values differ, or returns None when they are equal."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return "%s.%s missing on one side" % (path, k)
            d = first_difference(a[k], b[k], path + "." + k)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, "%s[%d]" % (path, i))
            if d:
                return d
        if len(a) != len(b):
            return "%s: lengths %d and %d" % (path, len(a), len(b))
        return None
    if isinstance(a, bool) or isinstance(b, bool):
        return None if a is b else "%s: %r != %r" % (path, a, b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if a == b else "%s: %r != %r" % (path, a, b)
    return None if a == b else "%s: %r != %r" % (path, str(a)[:200], str(b)[:200])
