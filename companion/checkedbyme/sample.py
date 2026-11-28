"""Builds data/sample-project.json, the partly checked project the app opens with.

The student has worked through some of the checklist already: four statements
are verified against sources and one reference has been looked up. Marks are
matched to statements by a phrase in them, so they survive a new seed.
"""

import os

from . import model as M

PROJECT = {
    "title": "Repair caf\u00e9s and the circular high street",
    "assignment": "MGT2207 Essay 2",
    "course": "MGT2207 Operations and the Circular Economy",
    "institution": "University of Eastmoor",
    "person": "Rowan Tilsley",
    "date": "",
    "level": "assisted",
    "template": "statement",
}

# (phrase in the statement, status, note)
MARKS = [
    ("tonnes of electrical waste", "verified", "Kestleford Repair Network, Annual report 2023, p. 4 (matches my notes)"),
    ("opened in Brinmouth", "verified", "Annual report 2023, 'Our history' box"),
    ("Footfall on Market Street", "verified", "Brinmouth footfall monitor 2022, table 2"),
    ("runs three monthly repair", "verified", "Network's 'Where we meet' page, read 20 November"),
]
REF_MARKS = [
    ("Journal of Household Material Flows, 14(2), pp.", "checked", "Found in the library search: vol. 14, issue 2, pp. 113-129"),
]
AS_OF = M.days_from_civil(2026, 11, 28)


def read(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8") as fh:
        return fh.read()


def build(folder):
    texts = {
        "draft": read(folder, "ai-draft.md"),
        "final": read(folder, "final-version.md"),
        "prompt": read(folder, "prompt.txt"),
        "references": "",
        "notes": read(folder, "notes.md"),
    }
    sessions = M.parse_sessions(read(folder, "session-log.csv"))["sessions"]
    analysis = M.analyse(dict(texts, asOf=AS_OF))
    checks = {}
    for phrase, status, note in MARKS:
        for c in analysis["claims"]:
            if phrase in c["text"]:
                checks[c["key"]] = {"status": status, "note": note, "on": "2026-11-20", "text": c["text"]}
    ref_checks = {}
    for phrase, status, note in REF_MARKS:
        for r in analysis["refs"]["entries"]:
            if phrase in r["entry"]["text"]:
                ref_checks[r["entry"]["key"]] = {"status": status, "note": note, "on": "2026-11-21"}
                break
    state = {"project": PROJECT, "texts": texts, "sessions": sessions, "checks": checks, "refChecks": ref_checks, "asOf": AS_OF}
    return M.project_file(state)
