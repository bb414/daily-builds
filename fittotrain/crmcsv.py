"""Reading and writing CRM opportunity exports as CSV.

The column layout is documented in the README. Only six columns are required;
every scoring field is optional, and blanks are allowed anywhere.
"""

import csv
import math
from datetime import date

from . import model

COLUMNS = ["opportunity_id", "account_name", "owner", "segment", "source", "created_date", "close_date",
           "status", "amount", "stakeholders", "meetings_first_3_weeks", "champion", "competitor",
           "discount_pct", "days_to_first_meeting", "edited_after_close"]
REQUIRED = ["opportunity_id", "account_name", "created_date", "close_date", "status", "amount"]
FIELD_COLUMNS = {
    "stakeholders": "stakeholders",
    "meetings": "meetings_first_3_weeks",
    "champion": "champion",
    "competitor": "competitor",
    "discount": "discount_pct",
    "daysToFirst": "days_to_first_meeting",
}
BINARY_FIELDS = ("champion", "competitor")
TRUTH_COLUMNS = ["opportunity_id", "true_outcome", "true_amount", "true_stakeholders", "true_meetings",
                 "true_champion", "true_competitor", "zombie", "recreated_copy", "placeholder_amount"]


class CsvProblem(ValueError):
    """Raised when a CSV cannot be read as a CRM export."""


def _yes_no(v):
    return "" if v is None else ("yes" if v else "no")


def _blank(v):
    return "" if v is None else str(v)


def export_rows(crm):
    """The CRM history as the pilot team would export it on go-live day."""
    rows = []
    for r in crm["history"]:
        rows.append({
            "opportunity_id": ("R-" if r["twin"] else "D-") + str(r["dealId"]),
            "account_name": r["account"],
            "owner": "Rep %02d" % (r["rep"] + 1),
            "segment": model.SEGMENTS[r["seg"]],
            "source": model.SOURCES[r["src"]],
            "created_date": model.day_to_iso(r["created"]),
            "close_date": model.day_to_iso(r["close"]),
            "status": r["status"],
            "amount": str(r["amount"]),
            "stakeholders": _blank(r["stakeholders"]),
            "meetings_first_3_weeks": _blank(r["meetings"]),
            "champion": _yes_no(r["champion"]),
            "competitor": _yes_no(r["competitor"]),
            "discount_pct": _blank(r["discount"]),
            "days_to_first_meeting": _blank(r["daysToFirst"]),
            "edited_after_close": "yes" if r["editedAfterClose"] else "no",
        })
    return rows


def truth_rows(crm):
    """What really happened to every exported record (only a simulation can know this)."""
    rows = []
    for r in crm["history"]:
        t = r["truth"]
        outcome = "won" if t["won"] else ("lost" if t["close"] < model.GO_LIVE else "still open")
        rows.append({
            "opportunity_id": ("R-" if r["twin"] else "D-") + str(r["dealId"]),
            "true_outcome": outcome,
            "true_amount": str(t["amount"]),
            "true_stakeholders": str(t["stakeholders"]),
            "true_meetings": str(t["meetings"]),
            "true_champion": _yes_no(t["champion"]),
            "true_competitor": _yes_no(t["competitor"]),
            "zombie": "yes" if r["zombie"] else "no",
            "recreated_copy": "yes" if r["twin"] else "no",
            "placeholder_amount": "yes" if (r["placeholder"] and r["amount"] != t["amount"]) else "no",
        })
    return rows


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


# ---- Reading a user's export -----------------------------------------------------
def _parse_date(text, line, col):
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise CsvProblem("line %d: %s %r is not a date in YYYY-MM-DD form" % (line, col, text))


def _parse_number(text):
    t = (text or "").strip().replace(",", "").replace("£", "").replace("$", "").replace("€", "")
    if t == "":
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _parse_flag(text):
    t = (text or "").strip().lower()
    if t in ("yes", "y", "true", "1"):
        return 1
    if t in ("no", "n", "false", "0"):
        return 0
    return None


def _parse_status(text, line):
    t = (text or "").strip().lower().replace("_", " ")
    if t in ("won", "closed won", "win"):
        return "won"
    if t in ("lost", "closed lost", "loss"):
        return "lost"
    if t in ("open", "in progress", "active"):
        return "open"
    raise CsvProblem("line %d: status %r should be won, lost or open" % (line, text))


def _index(options, text):
    t = (text or "").strip().lower()
    for i, o in enumerate(options):
        if t == o.lower() or (len(t) >= 3 and o.lower().startswith(t)):
            return i
    return None


def read_export(path):
    """Read a CRM export into the internal record format used by the audit.

    Returns (records, info). Dates become day numbers counted from the earliest
    created date. Amounts that are missing or not positive are noted in `info`
    and stand in at the median positive amount so the model can still run.
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise CsvProblem("the file is empty")
        header = [h.strip() for h in reader.fieldnames]
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise CsvProblem("missing required column(s): " + ", ".join(missing))
        raw = []
        for line, row in enumerate(reader, start=2):
            row = {(k or "").strip(): (v if v is not None else "") for k, v in row.items()}
            if not any(str(v).strip() for v in row.values()):
                continue
            raw.append((line, row))
    if not raw:
        raise CsvProblem("the file has a header but no rows")

    created = [_parse_date(r["created_date"], line, "created_date") for line, r in raw]
    closes = [_parse_date(r["close_date"], line, "close_date") for line, r in raw]
    origin = min(created)
    amounts = [_parse_number(r["amount"]) for _, r in raw]
    positive = sorted(a for a in amounts if a is not None and a > 0)
    median = positive[len(positive) // 2] if positive else 10000.0
    bad_amounts = 0
    records = []
    present = {f: (col in header) for f, col in FIELD_COLUMNS.items()}
    for i, (line, r) in enumerate(raw):
        amt = amounts[i]
        if amt is None or amt <= 0:
            bad_amounts += 1
            amt = median
        rec = {
            "id": i, "dealId": i, "label": r["opportunity_id"].strip() or ("row %d" % line),
            "account": r["account_name"].strip(), "rep": r.get("owner", "").strip(),
            "seg": _index(model.SEGMENTS, r.get("segment")), "src": _index(model.SOURCES, r.get("source")),
            "created": (created[i] - origin).days, "close": (closes[i] - origin).days,
            "status": _parse_status(r["status"], line), "amount": amt,
            "editedAfterClose": _parse_flag(r.get("edited_after_close")) == 1,
            "twin": False, "live": False,
        }
        for f, col in FIELD_COLUMNS.items():
            text = r.get(col, "")
            rec[f] = _parse_flag(text) if f in BINARY_FIELDS else _parse_number(text)
        records.append(rec)
    closed_dates = [c for c, rec in zip(closes, records) if rec["status"] != "open"]
    info = {
        "rows": len(records), "origin": origin, "bad_amounts": bad_amounts, "fields_present": present,
        "has_edit_flag": "edited_after_close" in header, "latest": max(created + closed_dates),
    }
    return records, info
