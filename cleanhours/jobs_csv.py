"""Read and write a fleet of compute jobs as CSV (the same columns the app exports)."""

import csv
import io

from . import model

COLUMNS = ["name", "mw", "hours", "every_days", "first_day", "release_hour", "window", "pausable"]
_KEYS = {"every_days": "everyDays", "first_day": "firstDay", "release_hour": "releaseHour"}
_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0", ""}


class JobsError(ValueError):
    """Raised when a jobs file cannot be read or fails validation."""


def _number(text, column, line):
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise JobsError("line %d: %s must be a number, not %r" % (line, column, text))
    return int(value) if value.is_integer() and column != "mw" else value


def parse_jobs(text):
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        raise JobsError("the jobs file is empty")
    header = [h.strip().lower() for h in reader.fieldnames]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise JobsError("missing column(s): " + ", ".join(missing))
    jobs = []
    for line, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        job = {"name": row["name"] or "Job %d" % (len(jobs) + 1)}
        for col in COLUMNS[1:-1]:
            job[_KEYS.get(col, col)] = _number(row[col], col, line)
        flag = row["pausable"].lower()
        if flag not in _TRUE | _FALSE:
            raise JobsError("line %d: pausable must be yes or no, not %r" % (line, row["pausable"]))
        job["pausable"] = flag in _TRUE
        jobs.append(job)
    errors = model.validate_jobs(jobs)
    if errors:
        raise JobsError("; ".join(errors))
    return jobs


def read_jobs(path):
    with open(path, encoding="utf-8") as fh:
        return parse_jobs(fh.read())


def format_jobs(jobs):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for j in jobs:
        w.writerow([j["name"], _fmt(j["mw"]), j["hours"], j["everyDays"], j["firstDay"],
                    j["releaseHour"], j["window"], "yes" if j["pausable"] else "no"])
    return out.getvalue()


def _fmt(x):
    return str(int(x)) if float(x).is_integer() else repr(float(x))
