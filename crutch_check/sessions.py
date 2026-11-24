"""Reading and writing session files exported by the browser app."""

import csv
import json
from pathlib import Path

from .model import CSV_COLUMNS, session_rows, validate_session

BUNDLE_FORMAT = "crutch-check-bundle"


def _sessions_in(data, source):
    if isinstance(data, dict) and data.get("format") == BUNDLE_FORMAT:
        items = data.get("sessions")
        if not isinstance(items, list):
            items = []
    elif isinstance(data, list):
        items = data
    else:
        items = [data]
    if not items:
        raise ValueError("%s: the file has no sessions in it" % source)
    out = []
    for i, s in enumerate(items):
        try:
            validate_session(s)
        except ValueError as exc:
            raise ValueError("%s (session %d): %s" % (source, i + 1, exc)) from None
        out.append(_whole_numbers(s))
    return out


def _whole_numbers(session):
    """Turn whole-number floats (1.0) back into ints after validation."""
    session["seed"] = int(session["seed"])
    for t in session["trials"]:
        for key in ("round", "position", "difficulty"):
            t[key] = int(t[key])
    return session


def load_sessions(paths):
    """Load sessions from JSON files, bundles or folders of JSON files."""
    sessions = []
    for p in paths:
        p = Path(p)
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
        if p.is_dir() and not files:
            raise ValueError("%s has no .json files in it" % p)
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("%s is not valid JSON: %s" % (f, exc)) from None
            sessions.extend(_sessions_in(data, f))
    return sessions


def bundle(sessions):
    return {"format": BUNDLE_FORMAT, "version": 1, "sessions": sessions}


def write_bundle(sessions, path):
    Path(path).write_text(json.dumps(bundle(sessions), separators=(",", ":")), encoding="utf-8")


def write_csv(sessions, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for s in sessions:
            for row in session_rows(s):
                w.writerow(row)
