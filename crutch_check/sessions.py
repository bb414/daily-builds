"""Reading and writing session files exported by the browser app."""

import csv
import json
from pathlib import Path

from .model import CSV_COLUMNS, session_rows, validate_session

BUNDLE_FORMAT = "crutch-check-bundle"


def _sessions_in(data, source):
    if isinstance(data, dict) and data.get("format") == BUNDLE_FORMAT:
        items = data.get("sessions", [])
    elif isinstance(data, list):
        items = data
    else:
        items = [data]
    out = []
    for i, s in enumerate(items):
        try:
            out.append(validate_session(s))
        except ValueError as exc:
            raise ValueError("%s (item %d): %s" % (source, i + 1, exc)) from None
    return out


def load_sessions(paths):
    """Load sessions from JSON files, bundles or folders of JSON files."""
    sessions = []
    for p in paths:
        p = Path(p)
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
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
    Path(path).write_text(json.dumps(bundle(sessions), indent=1), encoding="utf-8")


def write_csv(sessions, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for s in sessions:
            for row in session_rows(s):
                w.writerow(row)
