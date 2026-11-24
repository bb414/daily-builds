"""An AI register: classify many systems from a CSV file and plan the compliance work by date.

Simplified and illustrative, not legal advice.
"""

import csv
import io
import json
import re

from . import model

BOOL_FIELDS = ["takeover", "eu", "annex1", "profiling", "interacts", "generates", "generatedBefore", "emotionBiocat",
               "deepfake", "gpaiBefore", "gpaiOpen", "workplace", "sme"]
CHOICE_FIELDS = {
    "role": model.ROLES,
    "excluded": model.EXCLUSIONS,
    "annex3": [x["id"] for x in model.RULES["annex3"]],
    "derogation": [x["id"] for x in model.RULES["derogations"]],
    "gpai": model.GPAI,
    "deployerType": model.DEPLOYER_TYPES,
}
COLUMNS = ["name"] + list(CHOICE_FIELDS) + BOOL_FIELDS + ["prohibited", "turnover"]
TRUE, FALSE = ("yes", "y", "true", "1"), ("no", "n", "false", "0", "")
BLANK = {"excluded": "none", "gpai": "none", "deployerType": "private", "annex3": "", "derogation": ""}


def _trim(s):
    return s.strip(" \t\r\n")


def _cell(s):
    return '"' + s.replace('"', '""') + '"' if re.search(r'[",\r\n]', s) else s


def to_csv(answers_list):
    """A register as CSV text, one system per row: the same text the browser app downloads."""
    lines = [",".join(COLUMNS)]
    for raw in answers_list:
        a = model.normalise(raw)
        cells = []
        for k in COLUMNS:
            v = a[k]
            if k == "eu":
                cells.append("" if v else "no")
            elif v is True or v is False:
                cells.append("yes" if v else "")
            elif k == "prohibited":
                cells.append(";".join(v))
            elif k == "turnover":
                cells.append(model.js_number_string(v) if v else "")
            elif k in BLANK and v == BLANK[k]:
                cells.append("")
            else:
                cells.append(_cell(v))
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def parse_row(cells):
    """Turn one row (cells by column name) into answers. Returns (answers, notes about anything not understood)."""
    answers, notes = {"name": cells.get("name", "")}, []
    for k in BOOL_FIELDS:
        if k not in cells:
            continue
        v = cells[k].lower()
        if v in TRUE:
            answers[k] = True
        elif v in FALSE:
            answers[k] = False
        else:
            notes.append('%s "%s" is not yes or no, so it was treated as no' % (k, cells[k]))
            answers[k] = False
    if cells.get("eu") == "":
        answers.pop("eu", None)  # blank means the usual answer: yes, it is used in the EU
    for k, allowed in CHOICE_FIELDS.items():
        if cells.get(k):
            if cells[k] in allowed:
                answers[k] = cells[k]
            else:
                notes.append('%s "%s" is not one of: %s' % (k, cells[k], ", ".join(allowed)))
    known = [x["id"] for x in model.RULES["prohibitions"]]
    bans = [b for b in (_trim(b) for b in cells.get("prohibited", "").replace(",", ";").split(";")) if b]
    notes += ['prohibited "%s" is not a known banned practice' % b for b in bans if b not in known]
    answers["prohibited"] = [b for b in bans if b in known]
    if cells.get("turnover"):
        t = model.js_number(cells["turnover"])
        if t != t or t < 0:
            notes.append('turnover "%s" is not a number of euro millions, so 0 was used' % cells["turnover"])
        answers["turnover"] = cells["turnover"]
    return answers, notes


def read_csv_text(text):
    """Read a register CSV. Returns {"rows": [{"answers", "notes"}], "warnings": [...], "error": message or None}."""
    out = {"rows": [], "warnings": [], "error": None}
    if text.startswith("\ufeff"):
        text = text[1:]
    if csv.field_size_limit() < 2 ** 31 - 1:
        csv.field_size_limit(2 ** 31 - 1)  # the browser app has no limit on the length of a cell
    rows = [r for r in csv.reader(io.StringIO(text, newline="")) if any(_trim(c) for c in r)]
    if not rows:
        out["error"] = "it is empty"
        return out
    canonical = {c.lower(): c for c in COLUMNS}
    headers = [canonical.get(_trim(h).lower(), _trim(h)) for h in rows[0]]
    if "name" not in headers:
        out["error"] = 'it needs a "name" column'
        return out
    unknown = []
    for h in headers:
        if h and h not in COLUMNS and h not in unknown:
            unknown.append(h)
    if unknown:
        out["warnings"].append("ignored unknown column(s): %s" % ", ".join(unknown))
    for r in rows[1:]:
        cells = {}
        for j, h in enumerate(headers):
            if h:
                cells[h] = _trim(r[j]) if j < len(r) else ""
        answers, notes = parse_row(cells)
        out["rows"].append({"answers": answers, "notes": notes})
    if not out["rows"]:
        out["error"] = "it lists no systems"
    return out


def read_json(data):
    """A register saved by the browser app as JSON: a list of systems, or {"systems": [...]}."""
    if isinstance(data, dict) and isinstance(data.get("systems"), list):
        data = data["systems"]
    if not isinstance(data, list):
        raise ValueError("a JSON register must be a list of systems")
    rows = [{"answers": a, "notes": model.input_notes(a)} for a in data]
    if not rows:
        raise ValueError("it lists no systems")
    return rows


def load(path):
    """Read a register from a CSV or JSON file. Returns (rows, warnings); raises ValueError if it cannot be used."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    if str(path).lower().endswith(".json"):
        return read_json(json.loads(text)), []
    out = read_csv_text(text)
    if out["error"]:
        raise ValueError(out["error"])
    return out["rows"], out["warnings"]


euros = model.euros


def text_table(headers, rows):
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def summary_rows(results):
    rows = []
    for r in results:
        now = sum(1 for o in r["obligations"] if o["status"] == "applies")
        nd = r["nextDeadline"]
        rows.append([r["answers"]["name"] or "(unnamed)", r["tierLabel"], str(len(r["obligations"])), str(now),
                     model.long_date(nd["date"]) if nd else "-", euros(r["penalty"]["max"]) if r["penalty"] else "-"])
    return rows


SUMMARY_HEADERS = ["System", "Classification", "Duties", "Apply now", "Next deadline", "Maximum fine"]


def roadmap_rows(results):
    return [[model.long_date(m["date"]), "; ".join(m["labels"]), str(len(m["systems"])), str(m["duties"]),
             "in force" if m["status"] == "applies" else "in %d days" % model.days_between(results[0]["asOf"], m["date"])]
            for m in model.roadmap(results)]


ROADMAP_HEADERS = ["Date", "What starts", "Systems", "Duties", "Status"]


def render_text(results, warnings=(), notes=()):
    out = ["AI register: %d systems, dates as of %s. Simplified and illustrative, not legal advice." % (
        len(results), model.long_date(results[0]["asOf"])), "", text_table(SUMMARY_HEADERS, summary_rows(results)), "",
        "Roadmap", "", text_table(ROADMAP_HEADERS, roadmap_rows(results))]
    gained = [(r["answers"]["name"], c) for r in results for c in r["omnibus"] if c["daysGained"]]
    if gained:
        out += ["", "What the Digital Omnibus moved:"]
        out += ["  %s: %s, %s to %s (%d more days)" % (name, c["label"], model.long_date(c["original"]),
                                                       model.long_date(c["amended"]), c["daysGained"]) for name, c in gained]
    extra = list(warnings) + list(notes)
    if extra:
        out += ["", "Notes on the input:"] + ["  " + n for n in extra]
    return "\n".join(out)


def _md(text):
    return str(text).replace("|", "\\|")


def render_markdown(results):
    out = ["# AI register: compliance roadmap", "",
           "Dates as of %s, under the EU AI Act as amended by the Digital Omnibus on AI. Simplified and illustrative, not legal advice." % model.long_date(results[0]["asOf"]),
           "", "## Systems", "", "| " + " | ".join(SUMMARY_HEADERS) + " |", "|" + "---|" * len(SUMMARY_HEADERS)]
    out += ["| " + " | ".join(_md(c) for c in row) + " |" for row in summary_rows(results)]
    out += ["", "## Roadmap", "", "| " + " | ".join(ROADMAP_HEADERS) + " |", "|" + "---|" * len(ROADMAP_HEADERS)]
    out += ["| " + " | ".join(_md(c) for c in row) + " |" for row in roadmap_rows(results)]
    out += ["", "## Duties by system", ""]
    for r in results:
        out += ["### " + _md(r["answers"]["name"] or "(unnamed)"), "", "%s, as %s." % (r["tierLabel"], " and ".join(r["roles"])), ""]
        out += ["- %s (%s), from %s" % (o["text"], o["article"], model.long_date(o["date"])) for o in r["obligations"]] or ["- No duties under the AI Act."]
        out.append("")
    return "\n".join(out)


def duties_csv(results):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["system", "classification", "duty", "who", "article", "applies_from", "original_date", "status", "days_until"])
    for r in results:
        for o in r["obligations"]:
            w.writerow([r["answers"]["name"], r["tierLabel"], o["text"], o["role"], o["article"], o["date"], o["originalDate"] or "",
                        o["status"], o["daysUntil"]])
    return buf.getvalue()
