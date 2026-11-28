"""The checking model, line for line the same as the browser app's MODEL block.

Every function here mirrors one in src/model.js and gives the same answer on
the same input (tests/test_agreement.py proves it). The rules that keep the two
in step: dates are whole day numbers, shares use floor(x + 0.5), strings are
compared by code point, regular expressions are compiled with re.ASCII (so
\\b and case-insensitive matching behave as in JavaScript) and end-of-text is
written \\Z, and all text is cleaned first so only spaces and newlines remain.
"""

import json
import math
import re
import unicodedata

VERSION = 1
FORMAT = "checked-by-me project"
MIN_RUN = 4
KEPT_SHARE = 85
EDITED_SHARE = 30
PAIR_DICE = 30
REWORD_DICE = 50
NOTE_COMPARE = 2
NOTE_CONFLICT = 3
HIGH = 6
MEDIUM = 3

A = re.ASCII
AI = re.ASCII | re.IGNORECASE


# ---------------------------------------------------------------- basics

def fnv(s):
    h = 0x811C9DC5
    for b in s.encode("utf-8", "surrogatepass"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return "%08x" % h


def pct(part, whole):
    return math.floor(part * 100 / whole + 0.5) if whole > 0 else 0


def plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def list_and(items):
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def trim(s):
    return s.strip(" ")


def collapse(s):
    return trim(re.sub(r" {2,}", " ", s))


# ---------------------------------------------------------------- dates

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
MONTH_KEYS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
              "nov": 11, "dec": 12}


def days_from_civil(y, m, d):
    y -= 1 if m <= 2 else 0
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (1 if m <= 2 else 0), m, d)


def iso_day(day):
    y, m, d = civil_from_days(day)
    return "%04d-%02d-%02d" % (y, m, d)


def long_day(day):
    y, m, d = civil_from_days(day)
    return "%d %s %d" % (d, MONTHS[m - 1], y)


def valid_day(y, m, d):
    if m < 1 or m > 12 or d < 1 or y < 1000 or y > 2999:
        return None
    feb = 29 if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0 else 28
    dim = [31, feb, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if d > dim[m - 1]:
        return None
    return days_from_civil(y, m, d)


def month_from(word):
    w = word.lower()
    if len(w) < 3:
        return 0
    key = w[:3]
    if key not in MONTH_KEYS:
        return 0
    full = MONTHS[MONTH_KEYS[key] - 1].lower()
    if w != key and w != "sept" and not full.startswith(w):
        return 0
    return MONTH_KEYS[key]


_D_ISO = re.compile(r"^([0-9]{4})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})(?:[T ].*)?\Z", A)
_D_UK = re.compile(r"^([0-9]{1,2})[/.-]([0-9]{1,2})[/.-]([0-9]{4}|[0-9]{2})(?:[T ,].*)?\Z", A)
_D_TEXT = re.compile(r"^(?:[A-Za-z]+,? )?([0-9]{1,2})(?:st|nd|rd|th)? ([A-Za-z]+)\.?,? ([0-9]{4})\Z", A)
_D_US = re.compile(r"^(?:[A-Za-z]+,? )?([A-Za-z]+)\.? ([0-9]{1,2})(?:st|nd|rd|th)?,? ([0-9]{4})\Z", A)


def parse_date(text):
    s = trim(re.sub(r" {2,}", " ", re.sub(r"[\n\r\t]", " ", str(text or "")).replace(",", ", ")))
    if s == "":
        return {"day": None, "note": None}
    m = _D_ISO.match(s)
    if m:
        d0 = valid_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return {"day": None, "note": "no such date"} if d0 is None else {"day": d0, "note": None}
    m = _D_UK.match(s)
    if m:
        a, b, y, note = int(m.group(1)), int(m.group(2)), int(m.group(3)), None
        if len(m.group(3)) == 2:
            y = 1900 + y if y >= 70 else 2000 + y
        if b > 12 and a <= 12:
            a, b, note = b, a, "read as month first"
        d1 = valid_day(y, b, a)
        return {"day": None, "note": "no such date"} if d1 is None else {"day": d1, "note": note}
    m = _D_TEXT.match(s)
    if m and month_from(m.group(2)):
        d2 = valid_day(int(m.group(3)), month_from(m.group(2)), int(m.group(1)))
        return {"day": None, "note": "no such date"} if d2 is None else {"day": d2, "note": None}
    m = _D_US.match(s)
    if m and month_from(m.group(1)):
        d3 = valid_day(int(m.group(3)), month_from(m.group(1)), int(m.group(2)))
        return {"day": None, "note": "no such date"} if d3 is None else {"day": d3, "note": None}
    return {"day": None, "note": "not a date I can read"}


# ---------------------------------------------------------------- CSV

def sniff_delimiter(text):
    line = ""
    for ln in text.split("\n"):
        if trim(ln) != "":
            line = ln
            break
    counts = {",": 0, ";": 0, "\t": 0}
    quoted = False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in counts:
            counts[ch] += 1
    best = ","
    if counts[";"] > counts[best]:
        best = ";"
    if counts["\t"] > counts[best]:
        best = "\t"
    return best


def parse_csv(text):
    s = str(text or "")
    if s[:1] == "\ufeff":
        s = s[1:]
    s = re.sub(r"\r\n?", "\n", s)
    delim = sniff_delimiter(s)
    rows, row, cell, quoted, i, n = [], [], "", False, 0, len(s)
    while i < n:
        ch = s[i]
        if quoted:
            if ch == '"':
                if s[i + 1:i + 2] == '"':
                    cell += '"'
                    i += 2
                    continue
                quoted = False
                i += 1
                continue
            cell += ch
            i += 1
            continue
        if ch == '"' and trim(cell) == "":
            cell = ""
            quoted = True
            i += 1
            continue
        if ch == delim:
            row.append(cell)
            cell = ""
            i += 1
            continue
        if ch == "\n":
            row.append(cell)
            rows.append(row)
            row, cell = [], ""
            i += 1
            continue
        cell += ch
        i += 1
    if cell != "" or row:
        row.append(cell)
        rows.append(row)
    return {"rows": rows, "delimiter": delim}


def csv_cell(v):
    s = "" if v is None else str(v)
    if re.match(r"[=+@]", s) or re.match(r"-[^0-9]", s):
        s = "'" + s
    if re.search(r'[",\r\n]', s) or s != trim(s):
        s = '"' + s.replace('"', '""') + '"'
    return s


def csv_text(header, rows):
    lines = [",".join(csv_cell(c) for c in header)]
    for r in rows:
        lines.append(",".join(csv_cell(c) for c in r))
    return "\ufeff" + "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- cleaning pasted text

def clean_chars(raw, counts):
    s = "" if raw is None else str(raw)

    def count(pattern, key, repl):
        nonlocal s
        s, n = re.subn(pattern, repl, s)
        if n:
            counts[key] = counts.get(key, 0) + n

    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub("[\u2028\u2029]", "\n", s)
    count("[\U00010000-\U0010ffff\ud800-\udfff]", "symbols", "")
    count("[\u200b\u200c\u200d\u2060\u00ad\ufeff]", "invisible", "")
    count("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", "spaces", " ")
    s = re.sub("[\t\u000b\u000c]", " ", s)
    s = re.sub("[\u0000-\u0008\u000e-\u001f\u007f-\u009f]", "", s)
    count("[\u2018\u2019\u201a\u201b\u2032]", "quotes", "'")
    count("[\u201c\u201d\u201e\u201f\u2033]", "quotes", '"')
    s = s.replace("\u2026", "...").replace("\u2212", "-")
    count("\ufb01", "ligatures", "fi")
    count("\ufb02", "ligatures", "fl")
    return s


SUPERSCRIPTS = {"\u00b9": "1", "\u00b2": "2", "\u00b3": "3", "\u2070": "0", "\u2074": "4", "\u2075": "5",
                "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9"}

_HTML_TEST = re.compile(r"<(?:p|div|br|li|h[1-6]|span|em|strong|b|i|ul|ol|table|tr|td|blockquote|a)(?:[ >/])", AI)


def html_to_text(s, counts):
    if not _HTML_TEST.search(s):
        return s
    counts["html"] = counts.get("html", 0) + 1
    s = re.sub(r"<(?:script|style)[^>]*>[\s\S]*?</(?:script|style)>", "", s, flags=AI)
    s = re.sub(r"<br */?>", "\n", s, flags=AI)
    s = re.sub(r"</?(?:p|div|li|h[1-6]|ul|ol|table|tr|blockquote)(?: [^>]*)?>", "\n\n", s, flags=AI)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    s = re.sub(r"&#39;|&apos;", "'", s).replace("&amp;", "&")
    return re.sub(r"\n{3,}", "\n\n", s)


def inline_clean(text, counts):
    s = text

    def count(pattern, repl):
        nonlocal s
        s, n = re.subn(pattern, repl, s, flags=A)
        if n:
            counts["markdown"] = counts.get("markdown", 0) + n

    count(r"!\[([^\]]*)\]\([^)]*\)", r"\1")
    count(r"\[([^\]^][^\]]*)\]\(([^)\s]+)\)", r"\1 (\2)")
    s, n = re.subn(r"\[\^([0-9]+)\]", r"[\1]", s)
    if n:
        counts["footnotes"] = counts.get("footnotes", 0) + n
    count(r"\*\*([^*\n]+)\*\*", r"\1")
    count(r"__([^_\n]+)__", r"\1")
    count(r"(^|[^A-Za-z0-9*])\*([^*\n]+?)\*(?![A-Za-z0-9*])", r"\1\2")
    count(r"(^|[^A-Za-z0-9_])_([^_\n]+?)_(?![A-Za-z0-9_])", r"\1\2")
    count(r"`([^`\n]+)`", r"\1")
    count(r"~~([^~\n]+)~~", r"\1")
    count(r"</?[A-Za-z][^>]*>", "")
    return collapse(s)


REF_HEADINGS = ["references", "reference list", "bibliography", "works cited", "sources", "sources cited",
                "citations", "further reading", "literature cited", "endnotes", "footnotes", "notes and references"]


def is_ref_heading(text):
    t = trim(re.sub(r" {2,}", " ", re.sub(r"[*_#:]", "", text))).lower()
    return t in REF_HEADINGS


_SUP_RE = re.compile("([A-Za-z]{3}|[.,;:)\\]'\"%]|\\b(?:1[5-9]|20)[0-9]{2})([\u00b9\u00b2\u00b3\u2070\u2074-\u2079]+)", A)
_FOOT_RE = re.compile(r"^\[\^?([0-9]+)\]: *(.*)\Z", A)
_H_RE = re.compile(r"^(#{1,6}) +(.*?)(?: +#+)? *\Z", A)
_B_RE = re.compile(r"^(?:\*\*([^*]+)\*\*|__([^_]+)__):?\Z", A)
_RULE_RE = re.compile(r"^([-*_])(?: *\1){2,}\Z", A)
_ITEM_RE = re.compile("^(?:[-*+\u2022]|[0-9]{1,3}[.)]) +(.*)\\Z", A)


def read_document(raw):
    counts = {}
    s = clean_chars(raw, counts)
    s = html_to_text(s, counts)

    def sup(m):
        counts["footnotes"] = counts.get("footnotes", 0) + 1
        return m.group(1) + "[" + "".join(SUPERSCRIPTS[c] for c in m.group(2)) + "]"

    s = _SUP_RE.sub(sup, s)
    lines = s.split("\n")
    blocks, ref_lines, footnotes = [], [], []
    current = None
    in_refs = False
    ref_heading = ""
    for raw_line in lines:
        line = trim(raw_line)
        fm = _FOOT_RE.match(line)
        if fm:
            footnotes.append({"label": fm.group(1), "text": fm.group(2)})
            counts["footnotes"] = counts.get("footnotes", 0) + 1
            current = None
            continue
        if in_refs:
            ref_lines.append(line)
            continue
        if line == "":
            current = None
            continue
        hm = _H_RE.match(line)
        bm = _B_RE.match(line)
        heading_text, level = None, 0
        if hm:
            heading_text, level = hm.group(2), len(hm.group(1))
            counts["markdown"] = counts.get("markdown", 0) + 1
        elif bm:
            heading_text = bm.group(1) if bm.group(1) is not None else bm.group(2)
            level = 9
            counts["markdown"] = counts.get("markdown", 0) + 1
        elif is_ref_heading(line):
            heading_text, level = line, 9
        if heading_text is not None:
            if is_ref_heading(heading_text):
                in_refs = True
                ref_heading = trim(re.sub(r"[*_:]", "", heading_text))
                current = None
                continue
            blocks.append({"kind": "heading", "level": level, "text": inline_clean(heading_text, counts)})
            current = None
            continue
        if _RULE_RE.match(line):
            counts["markdown"] = counts.get("markdown", 0) + 1
            current = None
            continue
        quoted = False
        while re.match(r"> ?", line):
            line = re.sub(r"^> ?", "", line, count=1)
            quoted = True
        if quoted:
            counts["markdown"] = counts.get("markdown", 0) + 1
        if re.match(r"\|? *:?-{3,}", line) and re.match(r"[|:\- ]+\Z", line):
            counts["markdown"] = counts.get("markdown", 0) + 1
            continue
        if re.match(r"\|.*\|\Z", line):
            line = "; ".join(c for c in (trim(x) for x in line[1:-1].split("|")) if c != "")
            counts["markdown"] = counts.get("markdown", 0) + 1
        im = _ITEM_RE.match(line)
        if im:
            current = {"kind": "item", "level": 0, "text": im.group(1)}
            blocks.append(current)
            counts["markdown"] = counts.get("markdown", 0) + 1
            continue
        if trim(line) == "":
            current = None
            continue
        if current is not None:
            current["text"] += " " + line
        else:
            current = {"kind": "para", "level": 0, "text": line}
            blocks.append(current)
    out = []
    for b in blocks:
        text = b["text"] if b["kind"] == "heading" else inline_clean(b["text"], counts)
        if text != "":
            out.append({"kind": b["kind"], "level": b["level"], "text": text})
    return {"blocks": out, "refLines": ref_lines, "footnotes": footnotes, "refHeading": ref_heading, "cleaning": counts}


# ---------------------------------------------------------------- sentences and words

ABBREV = set(("eg ie etc al dr prof mr mrs ms mx st no nos vol vols pp p fig figs cf vs approx ltd inc co jan feb mar "
              "apr jun jul aug sep sept oct nov dec ed eds rev op cit ibid ch sec para est dept univ assn bros jr sr mt "
              "ave rd ca c viz resp repr trans govt corp intl natl").split(" "))
_STARTER = re.compile("[A-Z\u00c0-\u00d6\u00d8-\u00de0-9\"'(\\[]", A)
_WORDCH = re.compile("[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f.]", A)


def split_sentences(text):
    out = []
    start, i, n = 0, 0, len(text)

    def push(a, b):
        piece = trim(text[a:b])
        if piece != "":
            out.append(piece)

    while i < n:
        ch = text[i]
        if ch in ".!?":
            j = i
            while j < n and text[j] in ".!?":
                j += 1
            k = j
            while k < n and text[k] in "\"')]":
                k += 1
            if k < n and text[k] == " ":
                m = k
                while m < n and text[m] == " ":
                    m += 1
                if m < n and _STARTER.match(text[m]):
                    ok = True
                    if j - i == 1 and ch == ".":
                        b = i
                        while b > 0 and _WORDCH.match(text[b - 1]):
                            b -= 1
                        word = text[b:i].replace(".", "").lower()
                        if len(word) == 1 or word in ABBREV:
                            ok = False
                    if ok:
                        push(start, k)
                        start = m
                        i = m
                        continue
            i = k if k > i else i + 1
            continue
        i += 1
    push(start, n)
    return out


WORD_RE = re.compile("[0-9]+(?:[.,][0-9]+)*|[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f]+"
                     "(?:'[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f]+)*", A)


def words(text):
    return [m.group(0).lower() for m in WORD_RE.finditer(text)]


def strip_accents(s):
    return re.sub("[\u0300-\u036f]", "", unicodedata.normalize("NFD", s))


STOP = set(("a an the and or but if of to in on at by for with from as is are was were be been being it its this that "
            "these those there their they them then than so such not no nor can could would should will shall may "
            "might must do does did has have had having which who whom whose what when where why how all any each few "
            "more most other some own same too very just also into over under about after before between through "
            "during while because until again further once here both only our ours your yours his her hers him she he "
            "we you i me my us one per via up down out off above below said says").split(" "))


def stem(w):
    if len(w) > 2 and w[-2:] == "'s":
        w = w[:-2]
    if len(w) > 4 and w[-3:] == "ies":
        return w[:-3] + "y"
    if len(w) > 4 and (w[-4:] in ("ches", "shes") or w[-3:] in ("ses", "xes", "zes")):
        return w[:-2]
    if len(w) > 3 and w[-1:] == "s" and w[-2:] not in ("ss", "us", "is"):
        return w[:-1]
    return w


def content_words(text):
    seen, out = set(), []
    for w in words(strip_accents(text)):
        if re.match(r"[0-9]", w) or len(w) < 3 or w in STOP:
            continue
        w = stem(w)
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


# ---------------------------------------------------------------- spans: citations, links, figures

YEAR = "(?:1[5-9][0-9]{2}|20[0-9]{2})"
CAP = "A-Z\u00c0-\u00d6\u00d8-\u00de"
LET = "A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff"
PAREN_RE = re.compile(r"\(([^()]*)\)", A)
PIECE_YEAR_RE = re.compile("(?:^|[ ,])(" + YEAR + "[a-z]?|n\\.d\\.)(?=\\Z|[ ,;:])", A)
NARR_RE = re.compile("([" + CAP + "][" + LET + "'\\-]+(?: (?:et al\\.?|and [" + CAP + "][" + LET + "'\\-]+|& [" + CAP
                     + "][" + LET + "'\\-]+))?) \\((" + YEAR + "[a-z]?|n\\.d\\.)(?:, (pp?\\. ?[0-9]+(?:[-\u2013][0-9]+)?))?\\)", A)
NUM_CIT_RE = re.compile("\\[([0-9]{1,3}(?: *[-\u2013,] *[0-9]{1,3})*)\\]", A)
PANDOC_RE = re.compile(r"\[(-?@[A-Za-z0-9_][^\]]*)\]", A)
LATEX_CITE_RE = re.compile(r"\\(?:cite|citep|citet|parencite|textcite|autocite)\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}", A)
_KEY_RES = [(PANDOC_RE, ";", re.compile(r"^ *-?@([A-Za-z0-9_:.\-]*[A-Za-z0-9_])", A)), (LATEX_CITE_RE, ",", re.compile(r"^ *([A-Za-z0-9_:.\-]+)", A))]
NOT_AUTHOR = {"in", "since", "from", "by", "until", "before", "after", "see", "circa", "around"}
_CAP_START = re.compile("^[" + CAP + "]", A)
_PIECE_PREFIX = re.compile(r"^(?:see also|see|e\.g\.,?|cf\.|as cited in) +", AI)
_PAGE_RE = re.compile("^(?:pp?\\.|page|pages) ?[0-9]+(?: ?[-\u2013] ?[0-9]+)?\\Z", A)


def citation_piece(piece):
    p = trim(_PIECE_PREFIX.sub("", piece, count=1))
    m = PIECE_YEAR_RE.search(p)
    if not m:
        return None
    year_start = m.start(1)
    authors = trim(re.sub(r"[ ,]+\Z", "", p[:year_start]))
    rest = trim(re.sub(r"^[ ,]+", "", p[year_start + len(m.group(1)):]))
    if authors == "" or not _CAP_START.match(authors):
        return None
    if len(authors.split(" ")) > 9:
        return None
    if authors.split(" ")[0].lower() in NOT_AUTHOR:
        return None
    page = rest if _PAGE_RE.match(rest) else ""
    return {"authors": authors, "year": m.group(1), "page": page}


def find_citations(text):
    out = []
    for m in PAREN_RE.finditer(text):
        found = [c for c in (citation_piece(x) for x in m.group(1).split(";")) if c]
        for f in found:
            out.append({"kind": "author-year", "text": m.group(0), "start": m.start(), "end": m.end(),
                        "authors": f["authors"], "year": f["year"], "page": f["page"], "labels": []})
    for m in NARR_RE.finditer(text):
        if m.group(1).split(" ")[0].lower() in NOT_AUTHOR:
            continue
        if any(m.start() < o["end"] and m.end() > o["start"] for o in out):
            continue
        out.append({"kind": "author-year", "text": m.group(0), "start": m.start(), "end": m.end(),
                    "authors": m.group(1), "year": m.group(2), "page": m.group(3) or "", "labels": []})
    for m in NUM_CIT_RE.finditer(text):
        labels = []
        for part in m.group(1).replace(" ", "").split(","):
            r = re.match("^([0-9]+)[-\u2013]([0-9]+)\\Z", part, A)
            if r and int(r.group(2)) >= int(r.group(1)) and int(r.group(2)) - int(r.group(1)) <= 50:
                labels.extend(str(x) for x in range(int(r.group(1)), int(r.group(2)) + 1))
            elif re.match(r"^[0-9]+\Z", part, A):
                labels.append(str(int(part)))
        if labels:
            out.append({"kind": "numeric", "text": m.group(0), "start": m.start(), "end": m.end(), "authors": "",
                        "year": "", "page": "", "labels": labels})
    # citation keys from Pandoc Markdown ([@key; @other, p. 4]) and LaTeX (\cite{key,other})
    for regex, sep, piece_re in _KEY_RES:
        for m in regex.finditer(text):
            keys = []
            for piece in m.group(1).split(sep):
                km = piece_re.match(piece)
                if km and km.group(1) not in keys:
                    keys.append(km.group(1))
            if keys:
                out.append({"kind": "key", "text": m.group(0), "start": m.start(), "end": m.end(), "authors": "", "year": "",
                            "page": "", "labels": keys})
    out.sort(key=lambda c: (c["start"], c["end"]))
    return out


URL_RE = re.compile(r"\b(?:https?|htps?|hhtps?|http)(?::\/\/|:\/|\/\/)[^ <>\"()]+|\bwww\.[^ <>\"()]+|\b10\.[0-9]{4,9}\/"
                    r"[^ <>\"()]+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|org|net|gov|edu|ac|io|co|uk|info)"
                    r"(?:\.[a-z]{2})?\/[^ <>\"()]*", AI)


def find_urls(text):
    out = []
    for m in URL_RE.finditer(text):
        t = re.sub(r"[.,;:!?']+\Z", "", m.group(0))
        out.append({"start": m.start(), "end": m.start() + len(t), "text": t})
    return out


def inside(spans, a, b):
    return any(a < s["end"] and b > s["start"] for s in spans)


MONEY_RE = re.compile("([\u00a3$\u20ac]) ?([0-9]+(?:,[0-9]{3})*(?:\\.[0-9]+)?)(?: ?(k|m|bn|million|billion|thousand)\\b)?", A)
PCT_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?) ?(%|per ?cent\b)", A)
YEAR_RE = re.compile("\\b(" + YEAR + ")\\b(?![%,.]?[0-9])", A)
NUM_RE = re.compile(r"\b([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\b", A)
UNIT_RE = re.compile("^[ -]*([A-Za-z\u00c0-\u00ff]+)", A)


def norm_number(v):
    s = v.replace(",", "")
    if "." in s:
        s = re.sub(r"0+\Z", "", s)
        s = re.sub(r"\.\Z", "", s)
    return s


def find_facts(text, skip):
    taken = list(skip)
    out = []

    def add(cls, start, end, value, unit):
        if inside(taken, start, end):
            return
        taken.append({"start": start, "end": end})
        out.append({"cls": cls, "start": start, "end": end, "text": text[start:end], "value": value, "unit": unit})

    for m in MONEY_RE.finditer(text):
        add("money", m.start(), m.end(), m.group(1) + norm_number(m.group(2)) + (m.group(3).lower() if m.group(3) else ""), "")
    for m in PCT_RE.finditer(text):
        add("pct", m.start(), m.end(), norm_number(m.group(1)), "")
    for m in YEAR_RE.finditer(text):
        before = text[max(0, m.start() - 1):m.start()]
        if re.search("[\u00a3$\u20ac.,]", before):
            continue
        add("year", m.start(), m.end(), m.group(1), "")
    for m in NUM_RE.finditer(text):
        prev = text[max(0, m.start() - 1):m.start()]
        if re.search("[A-Za-z\u00a3$\u20ac]", prev):
            continue
        um = UNIT_RE.match(text[m.end():])
        unit = stem(strip_accents(um.group(1).lower())) if um else ""
        end = m.end()
        if unit in STOP:
            um2 = UNIT_RE.match(text[m.end() + len(um.group(0)):])
            unit = stem(strip_accents(um2.group(1).lower())) if um2 else ""
        elif um:
            end += len(um.group(0))
        add("num", m.start(), end, norm_number(m.group(1)), unit)
    out.sort(key=lambda f: f["start"])
    return out


QUOTE_D_RE = re.compile(r'"([^"\n]{3,}?)"', A)
QUOTE_S_RE = re.compile(r"(^|[ (\[])'([^'\n]{3,}?)'(?=\Z|[ .,;:!?)\]])", A)


def find_quotes(text):
    out = []
    for m in QUOTE_D_RE.finditer(text):
        if len(re.split(" +", trim(m.group(1)))) >= 4:
            out.append({"start": m.start(), "end": m.end(), "text": m.group(1)})
    for m in QUOTE_S_RE.finditer(text):
        s = m.start() + len(m.group(1))
        if len(re.split(" +", trim(m.group(2)))) >= 4 and not inside(out, s, s + len(m.group(2)) + 2):
            out.append({"start": s, "end": s + len(m.group(2)) + 2, "text": m.group(2)})
    out.sort(key=lambda q: q["start"])
    return out


# ---------------------------------------------------------------- what makes a sentence worth checking

LEFTOVER_RES = [re.compile(p, AI) for p in [
    r"\bas an ai\b",
    r"\bas a(?:n ai)? language model\b",
    r"\bas of my (?:last|latest|most recent) (?:update|training|knowledge)\b",
    r"\bknowledge cut-?off\b",
    r"\bi (?:hope|trust) (?:this|that) helps\b",
    r"\blet me know if\b",
    r"^(?:sure|certainly|of course|absolutely|great question)!",
    r"^(?:sure|certainly|absolutely|of course)[,.]? (?:here|i can|i'll|i will|let me|below)\b",
    r"\bhere(?:'s| is) (?:a|an|the|your) (?:[a-z-]+ ){0,3}(?:version|draft|rewrite|revision|summary|essay|section|paragraph|outline)\b",
    r"\[(?:insert|add|citation needed|source|sources|author|year|reference|ref|todo|tbc|tbd|name|date)\b[^\]]*\]",
    r"\((?:author|source),? (?:year|date)\)",
    r"\bxx+(?:\.x+)? ?%",
    r"\blorem ipsum\b",
    r"\bregenerate(?: response)?\b",
    r"\bi (?:cannot|can't|am unable to|don't have the ability to) (?:browse|access|search)\b",
    r"\bi don't have access to (?:real-time|current|the internet)\b",
    r"\bfeel free to\b",
    r"\b(?:do you want|would you like) me to\b",
]]
ABSOLUTE_RE = re.compile(r"\b(?:always|never|every|everyone|everybody|nobody|no one|entirely|completely|totally|"
                         r"undoubtedly|unquestionably|definitely|certainly|clearly|obviously|proven|proves|prove|"
                         r"guarantees?|guaranteed|without exception|universally|unprecedented|beyond doubt|the (?:first|"
                         r"only|single most|most|best|worst|largest|biggest|smallest|highest|lowest|greatest|fastest|"
                         r"leading))\b", AI)
VAGUE_RE = re.compile(r"\b(?:studies|research|evidence|data|surveys|experts|scientists|researchers|economists|analysts)"
                      r"(?: (?:have|has))? (?:show|shows|shown|suggest|suggests|suggested|prove|proves|proven|agree|"
                      r"agrees|indicate|indicates|confirm|confirms|say|says|believe|believes|found)\b|\bit is (?:widely|"
                      r"generally|commonly|well) (?:known|accepted|believed|agreed|established)\b|\b(?:many|most|some) "
                      r"(?:studies|experts|researchers|scientists|people) (?:say|believe|agree|argue|suggest|have found)"
                      r"\b|\baccording to (?:experts|research|studies|many|some|scientists)\b", AI)
STUDY_NOUN_RE = re.compile(r"\b(?:study|studies|survey|surveys|report|reports|trial|trials|experiment|experiments|"
                           r"meta-analysis|poll|census|paper|research|review|analysis|evaluation)\b", AI)
STUDY_VERB_RE = re.compile(r"\b(?:found|finds|find|showed|shows|show|concluded|concludes|reported|reports|revealed|"
                           r"reveals|estimated|estimates|according to|suggests|suggested|predicts|predicted|argues|"
                           r"argued|recorded|records|measured)\b", AI)
PERSON_TITLE_RE = re.compile("\\b(?:Dr|Prof|Professor|Sir|Dame|Lord|Lady|Mr|Mrs|Ms|Mx|Baroness|Judge|Justice)\\.? ["
                             + CAP + "][a-z\u00e0-\u00ff'\\-]+(?: [" + CAP + "][a-z\u00e0-\u00ff'\\-]+)?", A)
PERSON_SAID_RE = re.compile("\\b([" + CAP + "][a-z\u00e0-\u00ff'\\-]+ [" + CAP + "][a-z\u00e0-\u00ff'\\-]+),? (?:said|says|"
                            "argued|argues|wrote|writes|claimed|claims|noted|notes|observed|observes|stated|states|told|"
                            "explained|explains|warned|warns|added|put it)\\b", A)
CAPRUN_RE = re.compile("[" + CAP + "][" + LET + "'&\\-]*(?:(?: (?:of|for|and|the|on|&))* [" + CAP + "][" + LET
                       + "'&\\-]*)*", A)
ORG_WORDS = set(("University Institute Council Agency Department Ministry Office Commission Foundation Trust Society "
                 "Association Network Group Bank Board Authority Centre Center College School Hospital Committee "
                 "Federation Union Partnership Corporation Company Ltd plc Inc LLP Organisation Organization Service "
                 "Services Unit Lab Laboratory Forum Alliance Coalition Press Party Fund Bureau Court Parliament "
                 "Government Observatory Consortium Collective").split(" "))
ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}s?\b", A)
ACRONYM_STOP = set(("UK US USA EU AI OK TV PC CEO GB NB AM PM ID HR PR UN IT FAQ PDF CV MSc BSc BA MA PhD GCSE OR AND "
                    "THE PS LGBT DIY USB UKs").split(" "))
DATE_RES = [
    re.compile(r"\b(?:1[5-9]|20)[0-9]0s\b", A),
    re.compile(r"\b(?:1[5-9]|2[01])(?:st|nd|rd|th) century\b", AI),
    re.compile(r"\b[0-9]{1,2}(?:st|nd|rd|th)? (?:January|February|March|April|May|June|July|August|September|October|"
               r"November|December) (?:1[5-9]|20)[0-9]{2}\b", A),
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December) "
               r"(?:1[5-9]|20)[0-9]{2}\b", A),
    re.compile(r"\b(?:recently|currently|nowadays|at present|to date|this year|last year|next year|in recent years|"
               r"as of (?:now|today)|the latest|so far)\b", AI),
]
STAT_WORDS_RE = re.compile(r"\b(?:twice|double|doubled|doubling|triple|tripled|halved|quadrupled|(?:one|two|three|four|"
                           r"five|six|seven|eight|nine|ten) in (?:two|three|four|five|six|seven|eight|nine|ten|[0-9]+)|"
                           r"[0-9]+(?:\.[0-9]+)? ?(?:times|-fold|fold)|the majority|a minority|(?:half|a third|a quarter|"
                           r"two thirds|three quarters) of)\b", AI)
LEGAL_RE = re.compile(r"\b(?:law|laws|legal|legally|illegal|illegally|unlawful|lawful|liable|liability|regulations?|"
                      r"statute|statutory|courts?|tribunal|contracts?|contractual|gdpr|copyright|trademarks?|patents?|"
                      r"licen[cs]es?|lawsuits?|sued?|prosecut[a-z]*|criminal|offences?|offenses?|obliged|obligations?|"
                      r"compliance|comply|complies|data controller|data protection|rights|required by law)\b", AI)
ACT_RE = re.compile(r"\b[A-Z][a-z]+ Act\b", A)
MEDICAL_RE = re.compile(r"\b(?:health|healthy|unhealthy|disease|diseases|illness|symptoms?|diagnos[a-z]*|treatments?|"
                        r"cures?|cured|therapy|therapies|medication|medicines?|medical|doses?|dosage|mg|vaccines?|"
                        r"harmless|toxic|toxins?|carcinogen[a-z]*|side effects?|clinical|patients?|mental health|"
                        r"anxiety|depression|cancer|lungs?|injur[a-z]*|allerg[a-z]*|fumes|poison[a-z]*|infection|"
                        r"safe to (?:eat|drink|use|take|breathe))\b", AI)
FINANCE_RE = re.compile(r"\b(?:tax|taxes|vat|interest rates?|apr|investments?|invest|investing|investors?|returns|"
                        r"pensions?|mortgages?|loans?|credit|debts?|inflation|salary|salaries|wages?|income|profits?|"
                        r"revenues?|dividends?|shares|stock market|stocks|savings|insurance|premiums?|fees?|tariffs?|"
                        r"budgets?)\b", AI)
HEDGE_RE = re.compile(r"\b(?:may|might|could|possibly|perhaps|suggests?|appears?|likely|around|about|approximately|"
                      r"roughly|estimated|up to|nearly|almost)\b", AI)


def all_matches(regex, text):
    return [{"start": m.start(), "end": m.end(), "text": m.group(0)} for m in regex.finditer(text)]


_CAPWORD = re.compile("^[A-Z\u00c0-\u00de]", A)


def find_orgs(text):
    out = []
    for m in CAPRUN_RE.finditer(text):
        toks = m.group(0).split(" ")
        offs, pos = [], m.start()
        for t in toks:
            offs.append(pos)
            pos += len(t) + 1
        k = 0
        while k < len(toks):
            if toks[k] not in ORG_WORDS:
                k += 1
                continue
            a = k
            while a > 0 and _CAPWORD.match(toks[a - 1]) and toks[a - 1] != "The" and toks[a - 1] != "&":
                a -= 1
            if a < k and toks[a] in ("In", "As", "At", "According", "By", "From"):
                a += 1
            b = k
            while b + 2 < len(toks) and toks[b + 1] in ("of", "for") and _CAPWORD.match(toks[b + 2]):
                b += 2
                while b + 1 < len(toks) and _CAPWORD.match(toks[b + 1]):
                    b += 1
            start, end = offs[a], offs[b] + len(toks[b])
            if not inside(out, start, end):
                out.append({"start": start, "end": end, "text": text[start:end]})
            k = b + 1
    for m in ACRONYM_RE.finditer(text):
        if m.group(0) in ACRONYM_STOP or inside(out, m.start(), m.end()):
            continue
        out.append({"start": m.start(), "end": m.end(), "text": m.group(0)})
    out.sort(key=lambda o: o["start"])
    return out


def uniq_texts(spans):
    seen, out = set(), []
    for s in spans:
        k = s["text"].lower()
        if k not in seen:
            seen.add(k)
            out.append(s["text"])
    return out


def quote_list(items, mx=4):
    shown = ['"' + t + '"' for t in items[:mx]]
    if len(items) > mx:
        shown.append("and %d more" % (len(items) - mx))
    return list_and(shown)


KIND_LABELS = {
    "leftover": "AI leftover", "statistic": "Statistic", "date": "Date", "study": "Study or report",
    "vague": "Vague source", "person": "Person", "org": "Organisation", "quote": "Quotation", "citation": "Citation",
    "url": "Link or DOI", "absolute": "Absolute wording", "legal": "Legal", "medical": "Health", "financial": "Money",
}
KIND_ORDER = ["leftover", "statistic", "quote", "citation", "study", "vague", "person", "org", "date", "url",
              "absolute", "legal", "medical", "financial"]


def _by_start(lst):
    return sorted(lst, key=lambda x: x["start"])


def scan_sentence(text):
    citations = find_citations(text)
    urls = find_urls(text)
    skip = citations + urls
    facts = find_facts(text, skip)
    spans, kinds = [], {}

    def mark(kind, lst):
        for x in lst:
            spans.append({"start": x["start"], "end": x["end"], "kind": kind, "text": x["text"]})
        if lst:
            kinds[kind] = lst

    leftovers = []
    for r in LEFTOVER_RES:
        leftovers += all_matches(r, text)
    leftovers.sort(key=lambda x: (x["start"], x["end"]))
    mark("leftover", leftovers)
    stats = [f for f in facts if f["cls"] != "year"]
    stat_words = [s for s in all_matches(STAT_WORDS_RE, text)
                  if not inside(skip, s["start"], s["end"]) and not inside(stats, s["start"], s["end"])]
    mark("statistic", _by_start(stats + stat_words))
    dates = [f for f in facts if f["cls"] == "year"]
    for regex in DATE_RES:
        for e in all_matches(regex, text):
            if not inside(skip, e["start"], e["end"]) and not inside(dates, e["start"], e["end"]):
                dates.append(e)

    def keep_date(i, x):
        for j, y in enumerate(dates):
            if j != i and y["start"] <= x["start"] and y["end"] >= x["end"] and (y["end"] - y["start"]) > (x["end"] - x["start"]):
                return False
        return True

    mark("date", _by_start([x for i, x in enumerate(dates) if keep_date(i, x)]))
    vague = all_matches(VAGUE_RE, text)
    mark("vague", vague)
    if not vague and STUDY_VERB_RE.search(text):
        mark("study", [s for s in all_matches(STUDY_NOUN_RE, text) if not inside(skip, s["start"], s["end"])][:1])
    people = all_matches(PERSON_TITLE_RE, text)
    said = []
    for m in PERSON_SAID_RE.finditer(text):
        if any(w in ORG_WORDS for w in m.group(1).split(" ")):
            continue
        if not inside(people, m.start(), m.start() + len(m.group(1))):
            said.append({"start": m.start(), "end": m.start() + len(m.group(1)), "text": m.group(1)})
    mark("person", _by_start(people + said))
    person_spans = [s for s in spans if s["kind"] == "person"]
    mark("org", [o for o in find_orgs(text) if not inside(skip, o["start"], o["end"])
                 and not inside(person_spans, o["start"], o["end"])])
    mark("quote", find_quotes(text))
    mark("citation", citations)
    mark("url", urls)
    mark("absolute", [s for s in all_matches(ABSOLUTE_RE, text) if not inside(leftovers, s["start"], s["end"])])
    mark("legal", _by_start(all_matches(LEGAL_RE, text) + all_matches(ACT_RE, text)))
    mark("medical", all_matches(MEDICAL_RE, text))
    money = [f for f in facts if f["cls"] == "money"]
    fin = all_matches(FINANCE_RE, text)
    mark("financial", _by_start(fin + [x for x in money if not inside(fin, x["start"], x["end"])]) if (fin or money) else [])
    spans.sort(key=lambda s: (s["start"], -s["end"], s["kind"]))
    return {"spans": spans, "kinds": kinds, "facts": facts, "citations": citations, "urls": urls,
            "quotes": kinds.get("quote", []), "hedges": all_matches(HEDGE_RE, text)}


# ---------------------------------------------------------------- your notes

def notes_index(text):
    doc = read_document(text or "")
    out, heading = [], []
    for block in doc["blocks"]:
        if block["kind"] == "heading":
            heading = content_words(block["text"])
        parts = [block["text"]] if block["kind"] == "heading" else split_sentences(block["text"])
        for p in parts:
            out.append({"text": p, "words": content_words(p), "heading": [] if block["kind"] == "heading" else list(heading),
                        "facts": find_facts(p, find_urls(p)), "quotes": find_quotes(p), "citations": find_citations(p)})
    return out


def overlap(claim_words, note):
    have = set(note["words"]) | set(note["heading"])
    return sum(1 for w in claim_words if w in have)


def quote_words(text):
    return [stem(w) for w in words(strip_accents(text))]


def dice_of(a, b):
    counts = {}
    for x in a:
        counts[x] = counts.get(x, 0) + 1
    inter = 0
    for y in b:
        if counts.get(y, 0) > 0:
            counts[y] -= 1
            inter += 1
    return {"inter": inter, "total": len(a) + len(b)}


def compare_notes(sentence, scan, notes):
    result = {"status": "none", "items": [], "related": ""}
    if not notes:
        return result
    cw = content_words(sentence)
    for fact in scan["facts"]:
        match, match_ov, best, best_fact, best_ov = None, -1, None, None, -1
        for note in notes:
            for nf in note["facts"]:
                if nf["cls"] != fact["cls"] or (fact["cls"] == "num" and nf["unit"] != fact["unit"]):
                    continue
                ov = overlap(cw, note)
                if ov < NOTE_COMPARE:
                    continue
                if nf["value"] == fact["value"]:
                    if ov > match_ov:
                        match, match_ov = note, ov
                elif ov > best_ov:
                    best, best_fact, best_ov = note, nf, ov
        if match:
            result["items"].append({"what": fact["text"], "result": "match", "note": match["text"], "noted": ""})
        elif best and best_ov >= NOTE_CONFLICT:
            result["items"].append({"what": fact["text"], "result": "conflict", "note": best["text"], "noted": best_fact["text"]})
        else:
            result["items"].append({"what": fact["text"], "result": "missing", "note": "", "noted": ""})
    for q in scan["quotes"]:
        qw = quote_words(q["text"])
        same, near, near_score = None, None, None
        for note in notes:
            for nq in note["quotes"]:
                nw = quote_words(nq["text"])
                if " ".join(nw) == " ".join(qw):
                    if not same:
                        same = note
                    continue
                dc = dice_of(qw, nw)
                if dc["inter"] * 2 * 10 >= 4 * dc["total"] and (
                        not near_score or dc["inter"] * near_score["total"] > near_score["inter"] * dc["total"]):
                    near, near_score = nq, dc
        if same:
            result["items"].append({"what": "the quotation", "result": "match", "note": same["text"], "noted": ""})
        elif near:
            result["items"].append({"what": "the quotation", "result": "conflict", "note": near["text"], "noted": '"' + near["text"] + '"'})
        else:
            result["items"].append({"what": "the quotation", "result": "missing", "note": "", "noted": ""})
    counts = {"match": 0, "conflict": 0, "missing": 0}
    for it in result["items"]:
        counts[it["result"]] += 1
    if counts["conflict"]:
        result["status"] = "conflict"
    elif counts["match"] and not counts["missing"]:
        result["status"] = "match"
    elif counts["match"]:
        result["status"] = "partial"
    elif counts["missing"]:
        result["status"] = "missing"
    if result["status"] in ("none", "missing"):
        best_rel, rel_ov = None, 2
        for note in notes:
            o = overlap(cw, note)
            if o > rel_ov:
                best_rel, rel_ov = note, o
        if best_rel:
            result["related"] = best_rel["text"]
            if result["status"] == "none":
                result["status"] = "related"
    return result


# ---------------------------------------------------------------- the claims checklist

PROMPT_SOURCES_RE = re.compile(r"\b(?:references?|citations?|cite|sources?|bibliography|harvard|apa|mla|footnotes?)\b", AI)
PROMPT_STATS_RE = re.compile(r"\b(?:statistics?|stats|figures|numbers|data|percentages?)\b", AI)
PROMPT_QUOTES_RE = re.compile(r"\b(?:quotes?|quotations?|quoting)\b", AI)


def read_prompt(text):
    doc = read_document(text or "")
    whole = " ".join(b["text"] for b in doc["blocks"])
    ws = [w for w in re.split(" +", trim(whole)) if w != ""]
    summary = " ".join(ws[:30]) + (" ..." if len(ws) > 30 else "")
    return {"given": len(ws) > 0, "words": len(ws), "summary": summary,
            "asksSources": bool(PROMPT_SOURCES_RE.search(whole)), "asksStats": bool(PROMPT_STATS_RE.search(whole)),
            "asksQuotes": bool(PROMPT_QUOTES_RE.search(whole))}


def sentence_key(text):
    return "q" + fnv(" ".join(words(text)))


def level_of(score):
    return "high" if score >= HIGH else ("medium" if score >= MEDIUM else "low")


def checks_for(kinds, scan):
    out = []

    def texts(k):
        return uniq_texts(kinds.get(k, []))

    if "leftover" in kinds:
        out.append("Delete or replace " + quote_list(texts("leftover"), 2) + ": it is the AI tool talking, not part of your work.")
    if "statistic" in kinds:
        out.append("Find where " + quote_list(texts("statistic")) + (" comes" if len(texts("statistic")) == 1 else " come")
                   + " from and check the number, the unit, the year and who it covers.")
    if "quote" in kinds:
        out.append("Find the exact quotation in the original, with its page number.")
    if "citation" in kinds:
        out.append("Open " + quote_list(texts("citation"), 3) + (" and check it really supports" if len(texts("citation")) == 1
                                                                 else " and check they really support") + " this sentence.")
    if "study" in kinds:
        out.append("Find the study or report itself, not a summary of it, and check it says this.")
    if "vague" in kinds:
        out.append("Name the source behind " + quote_list(texts("vague"), 2) + ", or cut the appeal to it.")
    if "person" in kinds:
        out.append("Check " + quote_list(texts("person"), 3) + (" exists, holds that role and said or wrote this." if len(texts("person")) == 1
                                                               else " exist, hold those roles and said or wrote this."))
    if "org" in kinds:
        out.append("Check the exact name of " + quote_list(texts("org"), 3) + ".")
    if "date" in kinds:
        out.append("Check the date" + ("s " if len(texts("date")) > 1 else " ") + quote_list(texts("date")) + ".")
    if "url" in kinds:
        out.append("Open " + quote_list(texts("url"), 2) + " yourself and check it loads and says this.")
    if "absolute" in kinds:
        out.append("Soften " + quote_list(texts("absolute"), 3) + " or find a source strong enough to back it.")
    if "legal" in kinds:
        out.append("Check the legal point against an authoritative source for the right country, and take advice where it matters.")
    if "medical" in kinds:
        out.append("Check the health or safety point against an authoritative clinical or safety source.")
    if "financial" in kinds:
        out.append("Check the money figures and rules against an authoritative source for the right year.")
    return out


# Points each reason adds to a statement's risk score (High from 6, Medium from 3).
W = {
    "leftover": 6,
    "statistic": 3,
    "quote": 3,
    "vague": 3,
    "legal": 3,
    "medical": 3,
    "financial": 3,
    "study": 2,
    "person": 2,
    "url": 2,
    "absolute": 2,
    "org": 1,
    "date": 1,
    "citation": 1,
    "unsourced": 2,
    "missing-ref": 3,
    "prompt-sources": 1,
    "prompt-stats": 1,
    "prompt-quotes": 1,
    "notes-conflict": 4,
    "notes-match": -2,
    "notes-partial": -1,
    "notes-missing": 1,
    "origin-kept": 1,
    "origin-yours": -1,
    "hedge": -1,
}
WEIGHTS = W


def score_claim(kinds, scan, ctx):
    reasons = []

    def add(code, points, text):
        reasons.append({"code": code, "points": points, "text": text})

    def texts(k):
        return uniq_texts(kinds.get(k, []))

    if "leftover" in kinds:
        add("leftover", W["leftover"], "Text from the AI tool itself (" + quote_list(texts("leftover"), 2) + "), not part of your work.")
    if "statistic" in kinds:
        add("statistic", W["statistic"], "Figures to check: " + quote_list(texts("statistic")) + ". Numbers are where AI drafts most often go wrong.")
    if "quote" in kinds:
        add("quote", W["quote"], "Direct quotation: AI tools often reword or invent quotes.")
    if "vague" in kinds:
        add("vague", W["vague"], "Vague appeal to authority (" + quote_list(texts("vague"), 2) + ") with no named source.")
    if "legal" in kinds:
        add("legal", W["legal"], "Legal statement (" + quote_list(texts("legal"), 3) + ").")
    if "medical" in kinds:
        add("medical", W["medical"], "Health or safety statement (" + quote_list(texts("medical"), 3) + ").")
    if "financial" in kinds:
        add("financial", W["financial"], "Money or financial statement (" + quote_list(texts("financial"), 3) + ").")
    if "study" in kinds:
        add("study", W["study"], "Refers to a study or report: check the original says this.")
    if "person" in kinds:
        add("person", W["person"], "Names a person (" + quote_list(texts("person"), 3) + ").")
    if "url" in kinds:
        add("url", W["url"], "Web address or DOI (" + quote_list(texts("url"), 2) + ").")
    if "absolute" in kinds:
        add("absolute", W["absolute"], "Absolute or superlative wording (" + quote_list(texts("absolute"), 3) + ").")
    if "org" in kinds:
        add("org", W["org"], "Names an organisation (" + quote_list(texts("org"), 3) + ").")
    if "date" in kinds:
        add("date", W["date"], "Dates or times: " + quote_list(texts("date")) + ".")
    if "citation" in kinds:
        add("citation", W["citation"], "Cites " + quote_list(texts("citation"), 3) + ": check the source supports the sentence.")
    if ("statistic" in kinds or "quote" in kinds or "study" in kinds) and "citation" not in kinds and "url" not in kinds:
        add("unsourced", W["unsourced"], "No source given in the sentence.")
    if ctx["missing"]:
        add("missing-ref", W["missing-ref"], "Cites " + quote_list(ctx["missing"], 3) + ", which " + ("is" if len(ctx["missing"]) == 1 else "are")
            + " not in your reference list.")
    if ctx["prompt"]["asksSources"] and "citation" in kinds:
        add("prompt-sources", W["prompt-sources"], "You asked the AI for references, and AI tools often invent plausible ones.")
    if ctx["prompt"]["asksStats"] and "statistic" in kinds:
        add("prompt-stats", W["prompt-stats"], "You asked the AI for statistics, and AI tools often invent plausible figures.")
    if ctx["prompt"]["asksQuotes"] and "quote" in kinds:
        add("prompt-quotes", W["prompt-quotes"], "You asked the AI for a quotation, and AI tools often invent them.")
    nt = ctx["notes"]
    if nt["status"] == "conflict":
        bits = [("your notes give the quotation as " + it["noted"]) if it["what"] == "the quotation"
                else ("your notes say " + it["noted"] + " where the text says " + it["what"])
                for it in nt["items"] if it["result"] == "conflict"]
        add("notes-conflict", W["notes-conflict"], "Your notes disagree: " + list_and(bits) + ".")
    elif nt["status"] == "match":
        add("notes-match", W["notes-match"], "Your notes give the same " + ("figure" if len(nt["items"]) == 1 else "figures") + ".")
    elif nt["status"] == "partial":
        add("notes-partial", W["notes-partial"], "Your notes back " + list_and(['"' + it["what"] + '"' for it in nt["items"] if it["result"] == "match"])
            + " but not " + list_and(['"' + it["what"] + '"' for it in nt["items"] if it["result"] != "match"]) + ".")
    elif nt["status"] == "missing":
        add("notes-missing", W["notes-missing"], "Not in your notes, so you have no record of where it came from.")
    if ctx["origin"] == "kept":
        add("origin-kept", W["origin-kept"], "Kept word for word from the AI draft.")
    elif ctx["origin"] == "yours":
        add("origin-yours", W["origin-yours"], "Written in your own words.")
    if "statistic" in kinds and "leftover" not in kinds and scan["hedges"]:
        add("hedge", W["hedge"], "Hedged wording (" + quote_list(uniq_texts(scan["hedges"]), 2) + ").")
    return {"score": sum(r["points"] for r in reasons), "reasons": reasons}


# ---------------------------------------------------------------- what changed between the AI draft and your final version

def without_citations(text):
    """Citations are left out of the wording comparison: "(Hartwell et al., 2019)" is the same whoever writes it."""
    out, at = "", 0
    for c in find_citations(text):
        if c["start"] < at:
            continue
        out += text[at:c["start"]] + " "
        at = c["end"]
    return out + text[at:]


def body_sentences(doc):
    out, para = [], 0
    for b, block in enumerate(doc["blocks"]):
        if block["kind"] == "heading":
            continue
        for p in split_sentences(block["text"]):
            out.append({"text": p, "para": para, "block": b, "toks": words(without_citations(p))})
        para += 1
    return out


def gram_set(sents, n):
    flat = [t for s in sents for t in s["toks"]]
    grams = set(" ".join(flat[i:i + n]) for i in range(0, len(flat) - n + 1))
    whole = set(" ".join(s["toks"]) for s in sents if s["toks"])
    return {"grams": grams, "whole": whole}


def mark_kept(sents, other, n):
    flat = [t for s in sents for t in s["toks"]]
    kept = [False] * len(flat)
    for i in range(0, len(flat) - n + 1):
        if " ".join(flat[i:i + n]) in other["grams"]:
            for j in range(i, i + n):
                kept[j] = True
    per, idx = [], 0
    for s in sents:
        ln = len(s["toks"])
        c = sum(1 for b in range(ln) if kept[idx + b])
        if 0 < ln < n and " ".join(s["toks"]) in other["whole"]:
            c = ln
        per.append(c)
        idx += ln
    return per


def lcs_ops(a, b):
    ka = [" ".join(words(t)) for t in a]
    kb = [" ".join(words(t)) for t in b]
    n, m = len(a), len(b)
    if n * m > 40000:
        return None
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for x in range(n - 1, -1, -1):
        row, nxt = dp[x], dp[x + 1]
        for y in range(m - 1, -1, -1):
            row[y] = nxt[y + 1] + 1 if ka[x] == kb[y] else max(nxt[y], row[y + 1])
    ops = []

    def push(t, text):
        if ops and ops[-1][0] == t:
            ops[-1][1] += " " + text
        else:
            ops.append([t, text])

    p = q = 0
    while p < n and q < m:
        if ka[p] == kb[q]:
            push("=", b[q])
            p += 1
            q += 1
        elif dp[p + 1][q] >= dp[p][q + 1]:
            push("-", a[p])
            p += 1
        else:
            push("+", b[q])
            q += 1
    while p < n:
        push("-", a[p])
        p += 1
    while q < m:
        push("+", b[q])
        q += 1
    return ops


def candidates(index, toks):
    seen = set()
    for t in toks:
        for d in index.get(t, ()):
            seen.add(d)
    return sorted(seen)


def _split_tokens(text):
    return [t for t in text.split(" ") if t != ""]


def analyse_changes(draft_sents, final_sents):
    n = MIN_RUN
    kept_final = mark_kept(final_sents, gram_set(draft_sents, n), n)
    kept_draft = mark_kept(draft_sents, gram_set(final_sents, n), n)
    counts = {"kept": 0, "edited": 0, "reworded": 0, "yours": 0, "dropped": 0}
    final_words = kept_words = draft_words = survived = 0
    paired, sentences = set(), []
    index = {}
    for di, ds in enumerate(draft_sents):
        for tok in ds["toks"]:
            if tok in STOP or re.match(r"[0-9]", tok):
                continue
            lst = index.setdefault(tok, [])
            if not lst or lst[-1] != di:
                lst.append(di)
    for f, fs in enumerate(final_sents):
        ln, k = len(fs["toks"]), kept_final[f]
        final_words += ln
        kept_words += k
        best, best_d = -1, None
        for d in candidates(index, fs["toks"]):
            dc = dice_of(fs["toks"], draft_sents[d]["toks"])
            if dc["total"] == 0:
                continue
            if best_d is None or dc["inter"] * best_d["total"] > best_d["inter"] * dc["total"]:
                best, best_d = d, dc
        pair_ok = best_d is not None and best_d["inter"] * 2 * 100 >= PAIR_DICE * best_d["total"]
        if ln > 0 and k * 100 >= KEPT_SHARE * ln:
            cls = "kept"
        elif ln > 0 and k * 100 >= EDITED_SHARE * ln:
            cls = "edited"
        elif best_d is not None and best_d["inter"] * 2 * 100 >= REWORD_DICE * best_d["total"]:
            cls = "reworded"
        else:
            cls = "yours"
        counts[cls] += 1
        pair = best if pair_ok and cls != "yours" else -1
        if pair >= 0:
            paired.add(pair)
        ops = None
        if pair >= 0 and cls != "kept":
            ops = lcs_ops(_split_tokens(draft_sents[pair]["text"]), _split_tokens(fs["text"]))
        elif pair >= 0 and " ".join(draft_sents[pair]["toks"]) != " ".join(fs["toks"]):
            ops = lcs_ops(_split_tokens(draft_sents[pair]["text"]), _split_tokens(fs["text"]))
        sentences.append({"text": fs["text"], "para": fs["para"], "cls": cls, "words": ln, "kept": k, "pair": pair, "ops": ops})
    dropped = []
    for a, ds in enumerate(draft_sents):
        dl = len(ds["toks"])
        draft_words += dl
        survived += kept_draft[a]
        if dl > 0 and kept_draft[a] * 100 < EDITED_SHARE * dl and a not in paired:
            dropped.append({"index": a, "text": ds["text"], "words": dl, "survived": kept_draft[a]})
    counts["dropped"] = len(dropped)
    paras = []
    for s in sentences:
        while len(paras) <= s["para"]:
            paras.append({"words": 0, "kept": 0, "sentences": 0})
        pa = paras[s["para"]]
        pa["words"] += s["words"]
        pa["kept"] += s["kept"]
        pa["sentences"] += 1
    return {
        "finalWords": final_words, "keptWords": kept_words, "keptShare": pct(kept_words, final_words),
        "draftWords": draft_words, "survivedWords": survived, "survivedShare": pct(survived, draft_words),
        "counts": counts, "finalSentences": len(final_sents), "draftSentences": len(draft_sents),
        "sentences": sentences, "dropped": dropped, "paragraphs": paras,
    }


# ---------------------------------------------------------------- reference lists

ENTRY_START_RE = re.compile("^(?:[" + CAP + "][" + LET + "'\\-]+(?: [" + CAP + "][" + LET + "'\\-]+)*, ?(?:[" + CAP
                            + "]\\.|[" + CAP + "][a-z]+)|[" + CAP + "][^()]{0,120}\\((?:" + YEAR + "[a-z]?|n\\.d\\.)\\)|["
                            + CAP + "].{0,100}\\b" + YEAR + "\\b)", A)
MERGED_RE = re.compile("\\. (?=[" + CAP + "][" + LET + "'\\-]+, (?:[" + CAP + "]\\. ?){1,3}(?:(?:,|and|&) [^()]{0,80})?\\((?:"
                       + YEAR + "[a-z]?|n\\.d\\.)\\))", A)
LABEL_RE = re.compile("^(?:\\[([0-9]{1,3})\\]|([0-9]{1,3})[.)]|[-*+\u2022]) +", A)


def split_entries(lines):
    entries, current = [], None
    any_label = any(LABEL_RE.match(trim(x)) for x in lines)
    for raw in lines:
        line = trim(raw)
        if line == "" or _RULE_RE.match(line):
            if not any_label:
                current = None
            continue
        lm = LABEL_RE.match(line)
        if lm:
            current = {"label": lm.group(1) or lm.group(2) or "", "text": line[lm.end():]}
            entries.append(current)
            continue
        starts = (not any_label) and bool(ENTRY_START_RE.match(line))
        if current is not None and not starts:
            join_tight = current["text"].endswith("-") and bool(re.search(r"(?:https?:|www\.|doi|/)[^ ]*-\Z", current["text"], A))
            current["text"] += ("" if join_tight else " ") + line
        else:
            current = {"label": "", "text": line}
            entries.append(current)
    out = []
    for e in entries:
        parts = MERGED_RE.split(e["text"])
        for p, part in enumerate(parts):
            t = collapse(part)
            if p < len(parts) - 1:
                t += "."
            if t != "":
                out.append({"label": e["label"] if p == 0 else "", "text": t, "merged": len(parts) > 1})
    return out


DOI_MARK_RE = re.compile(r"(?:https?:\/\/(?:dx\.)?doi\.org\/|\bdoi:? ?|\bDOI:? ?)", AI)
BARE_DOI_RE = re.compile(r"\b10\.[0-9]{1,9}\/[^ ]+", A)
REF_URL_RE = re.compile(r"\b(?:https?|htps?|hhtps?|http)(?::\/\/|:\/|\/\/)[^ ]+|\bwww\.[^ ]+", AI)
GENERIC_WORDS = set(("journal international research studies study review science sciences advanced global modern "
                     "contemporary applied academic annals quarterly bulletin of and the in for on new open general current "
                     "trends perspectives letters reports report proceedings transactions world european american british "
                     "issues insights frontiers horizons progress innovative innovation multidisciplinary "
                     "interdisciplinary").split(" "))
PLACEHOLDER_HOSTS = ["example.com", "example.org", "example.net", "localhost"]


def strip_marks(s):
    return collapse(re.sub(r"[*_]", "", s))


def _search_pos(pattern, s, flags=A):
    m = re.search(pattern, s, flags)
    return m.start() if m else -1


def parse_entry(text, label=""):
    e = {"label": label or "", "text": strip_marks(text), "raw": text, "authors": "", "year": "", "title": "",
         "container": "", "volume": "", "issue": "", "pages": "", "doi": "", "doiMarked": False, "url": "",
         "urlTail": "", "accessed": "", "publisher": "", "type": "other", "citeKey": ""}
    s = text
    am = re.search(r"\(?(?:accessed|retrieved|viewed)(?: on)?:? ([^)\]]+)[)\]]?", s, AI)
    if am:
        e["accessed"] = trim(re.sub(r"[.]\Z", "", am.group(1)))
        s = s[:am.start()] + s[am.end():]
    dm = DOI_MARK_RE.search(s)
    if dm:
        after = s[dm.end():]
        stop = _search_pos(r" (?:\(|\[|Available|Accessed|Retrieved)", after, AI)
        doi = re.sub(r"[.,;]+\Z", "", trim(after[:stop] if stop >= 0 else after))
        e["doi"], e["doiMarked"] = doi, True
        s = s[:dm.start()] + (after[stop:] if stop >= 0 else "")
    else:
        bm = BARE_DOI_RE.search(s)
        if bm:
            e["doi"] = re.sub(r"[.,;]+\Z", "", bm.group(0))
            s = s[:bm.start()] + s[bm.end():]
    um = REF_URL_RE.search(s)
    if um:
        e["url"] = re.sub(r"[.,;]+\Z", "", um.group(0))
        tail = trim(s[um.end():])
        tail = trim(re.sub(r"[ .,;]+\Z", "", tail))
        if tail != "" and re.match(r"^[a-z0-9][^ ]*(?: [a-z0-9][^ ]*){0,2}\Z", tail, A) and not re.match(
                r"(?:accessed|viewed|retrieved|available)", tail, AI):
            e["urlTail"] = tail
        s = s[:um.start()] + ("" if e["urlTail"] else s[um.end():])
        s = re.sub(r"\bAvailable (?:at|from):? *\Z", "", s, flags=AI)
        s = re.sub(r"\bRetrieved from:? *\Z", "", s, flags=AI)
    body = trim(s)
    lm = re.match(r"(?:\[([0-9]{1,3})\]|([0-9]{1,3})[.)]) +", body, A)
    if lm:
        if not e["label"]:
            e["label"] = lm.group(1) or lm.group(2)
        body = body[lm.end():]
    ym = re.search("\\((" + YEAR + "[a-z]?|n\\.d\\.|[0-9]{4}[a-z]?)\\)", body, A)
    year_end = -1
    if ym:
        e["year"] = ym.group(1)
        e["authors"] = re.sub(r"[,.]\Z", "", trim(body[:ym.start()]))
        year_end = ym.end()
    else:
        ym = re.search("(?:^|[ ,.])(" + YEAR + "[a-z]?|[0-9]{4}[a-z]?|n\\.d\\.)(?=[.,;:]|\\Z| )", body, A)
        if ym:
            e["year"] = ym.group(1)
            ys = ym.start(1)
            e["authors"] = re.sub(r"[,.]\Z", "", trim(body[:ys]))
            year_end = ys + len(ym.group(1))
    e["authors"] = strip_marks(e["authors"])
    rest = body[year_end:] if year_end >= 0 else body
    rest = re.sub(r"^[).,: ]+", "", rest)
    tm = re.match(r"'([^']+)'|\"([^\"]+)\"", rest, A)
    italic_title = False
    if tm:
        e["title"] = tm.group(1) or tm.group(2)
        after2 = rest[tm.end():]
    else:
        im = re.match(r"\*([^*]+)\*", rest, A)
        if im:
            e["title"] = im.group(1)
            after2 = rest[im.end():]
            e["container"] = ""
            italic_title = True
        else:
            dot = _search_pos(r"[.?!] ", rest)
            if dot >= 0:
                e["title"], after2 = rest[:dot], rest[dot + 1:]
            else:
                e["title"], after2 = rest, ""
    e["title"] = trim(re.sub(r"[.,]\Z", "", strip_marks(e["title"])))
    after2 = re.sub(r"^[.,: ]+", "", after2)
    cm = re.match(r"(?:[Ii]n:? )?\*([^*]+)\*", after2, A)
    if cm:
        e["container"] = trim(re.sub(r"[.,]\Z", "", cm.group(1)))
    elif tm:
        cut = _search_pos(r", ?(?:vol|[0-9]|pp?\.)|\. |\.\Z|\Z", after2, AI)
        e["container"] = trim(re.sub(r"[.,]\Z", "", strip_marks(after2[:len(after2) if cut < 0 else cut])))
    plain = strip_marks(after2)
    vm = re.search("\\b([0-9]{1,4}) ?\\(([0-9]{1,4}(?:[-\u2013][0-9]{1,4})?)\\)", plain, A) or re.search(
        r"\bvol(?:ume)?\.? ?([0-9]{1,4})(?:,? (?:no|issue|iss)\.? ?([0-9]{1,4}))?", plain, AI)
    if vm:
        e["volume"], e["issue"] = vm.group(1), vm.group(2) or ""
    else:
        vm2 = re.search(r", ([0-9]{1,4}),", plain, A)
        if vm2 and e["container"]:
            e["volume"] = vm2.group(1)
    pm = (re.search("\\bpp?\\.? ?([0-9]+) ?[-\u2013] ?([0-9]+)", plain, A)
          or re.search("\\), ?([0-9]+) ?[-\u2013] ?([0-9]+)", plain, A)
          or re.search(", ([0-9]+) ?[-\u2013] ?([0-9]+)\\.?\\Z", plain, A))
    if pm:
        e["pages"] = pm.group(1) + "-" + pm.group(2)
    else:
        pm2 = re.search(r"\b(?:p\.|article|art\.) ?(e?[0-9]+)", plain, AI)
        if pm2:
            e["pages"] = pm2.group(1)
    if not e["container"] and not tm and not italic_title and (e["volume"] or "-" in e["pages"]):
        cut2 = _search_pos(r", ?(?:vol|[0-9]|pp?\.)|\. |\.\Z|\Z", plain, AI)
        e["container"] = trim(re.sub(r"[.,]\Z", "", plain[:len(plain) if cut2 < 0 else cut2]))
    pubm = re.search(r"(?:^|\. )([A-Z][A-Za-z .'\-]{1,40}): ([A-Z][^.:]{1,80})\.?", plain, A)
    if pubm and not e["volume"]:
        e["publisher"] = trim(pubm.group(2))
    if e["volume"] or (e["pages"] and e["container"] and "-" in e["pages"]):
        e["type"] = "journal"
    elif tm and e["container"] and not e["publisher"]:
        e["type"] = "journal"
    elif e["publisher"] or re.search(r"\b(?:ed\.|edn|edition)\b", plain, AI):
        e["type"] = "book"
    elif e["url"]:
        e["type"] = "web"
    elif re.search(r"\breport\b|working paper", e["title"] + " " + plain, AI):
        e["type"] = "report"
    if italic_title:
        e["italicTitle"] = True
    e["key"] = "r" + fnv(" ".join(words(e["text"])))
    return e


# ---------------------------------------------------------------- reference manager exports (RIS and BibTeX)

def list_names(names):
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def first_year(s):
    m = re.search(r"(?:^|[^0-9])([0-9]{4})(?![0-9])", s or "", A)
    return m.group(1) if m else ""


def structured_entry(f, fmt, raw):
    """Builds an entry, in the same shape parse_entry gives, from the fields of a reference manager record."""
    e = {"label": "", "text": "", "raw": raw, "authors": list_names(f["authors"]), "year": f["year"], "title": f["title"],
         "container": f["container"], "volume": f["volume"], "issue": f["issue"], "pages": f["pages"], "doi": f["doi"],
         "doiMarked": f["doi"] != "", "url": f["url"], "urlTail": "", "accessed": f["accessed"], "publisher": f["publisher"],
         "type": f["type"], "citeKey": f["citeKey"], "structured": fmt}
    t = (e["authors"] + " " if e["authors"] else "") + "(" + (e["year"] or "no year") + ") "
    if e["type"] == "journal":
        t += "'" + e["title"] + "', " + e["container"] + ((", " + e["volume"] + ("(" + e["issue"] + ")" if e["issue"] else "")) if e["volume"] else "") \
            + (", pp. " + e["pages"] if e["pages"] else "") + "."
    elif e["type"] in ("book", "report"):
        t += e["title"] + "." + (" In: " + e["container"] + "." if e["container"] else "") + (" " + e["publisher"] + "." if e["publisher"] else "")
    else:
        t += e["title"] + "." + (" " + e["container"] + "." if e["container"] else "")
    if e["doi"]:
        t += " doi:" + e["doi"]
    if e["url"]:
        t += " Available at: " + e["url"] + (" (Accessed: " + e["accessed"] + ")" if e["accessed"] else "")
    e["text"] = collapse(t.replace(" ,", ","))
    e["key"] = "r" + fnv(" ".join(words(e["text"])))
    return e


RIS_TYPES = {"JOUR": "journal", "JFULL": "journal", "EJOUR": "journal", "MGZN": "journal", "NEWS": "journal", "BOOK": "book",
             "EBOOK": "book", "CHAP": "book", "ECHAP": "book", "EDBOOK": "book", "ELEC": "web", "WEB": "web", "BLOG": "web",
             "RPRT": "report", "GOVDOC": "report", "THES": "report"}
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9]) {1,2}-(?: (.*))?\Z", A)
_DOI_PREFIX = re.compile(r"^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi: ?)", AI)


def looks_ris(text):
    return bool(re.search(r"(?:^|\n)TY {1,2}- ?[A-Z]", text or "", A))


def looks_bibtex(text):
    return bool(re.search(r"(?:^|\n) *@[A-Za-z]+ *[{(]", text or "", A))


def parse_ris(text):
    """Reads a RIS export (Zotero, Mendeley, EndNote, library databases): one record from TY to ER."""
    lines = clean_chars(text, {}).split("\n")
    recs, cur, last = [], None, ""
    for line in lines:
        ln = trim(line)
        m = _RIS_LINE.match(ln)
        if m:
            tag, val = m.group(1), trim(m.group(2) or "")
            if tag == "TY":
                cur = {"type": val, "fields": {}, "raw": [ln]}
                recs.append(cur)
                last = ""
                continue
            if cur is None:
                continue
            cur["raw"].append(ln)
            if tag == "ER":
                cur = None
                continue
            cur["fields"].setdefault(tag, []).append(val)
            last = tag
        elif cur is not None and last and ln != "":
            arr = cur["fields"][last]
            arr[-1] = collapse(arr[-1] + " " + ln)
            cur["raw"].append(ln)
    out = []
    for r in recs:
        f = r["fields"]

        def one(*tags):
            for t in tags:
                if t in f and f[t][0] != "":
                    return f[t][0]
            return ""

        authors = []
        for t in ("AU", "A1", "A2"):
            if t in f and not authors:
                authors = [x for x in f[t] if x != ""]
        sp, ep = one("SP"), one("EP")
        out.append(structured_entry({
            "authors": authors, "year": first_year(one("PY", "Y1", "DA")), "title": one("TI", "T1", "CT"),
            "container": one("T2", "JO", "JF", "JA", "BT"), "volume": one("VL"), "issue": one("IS"),
            "pages": sp + "-" + ep if (sp and ep and ep != sp) else sp, "doi": _DOI_PREFIX.sub("", one("DO"), count=1),
            "url": one("UR", "L2"), "accessed": one("Y2"), "publisher": one("PB"),
            "type": RIS_TYPES.get(r["type"], "web" if one("UR") else "other"), "citeKey": one("ID")}, "ris", "\n".join(r["raw"])))
    return out


TEX_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304", ".": "\u0307"}


def tex_text(s):
    """Turns BibTeX's TeX markup into plain text: accents, escaped characters, commands and braces."""
    t = re.sub(r"\\([&%$#_])", r"\1", s)
    t = re.sub(r"\{?\\(['`^\"~=.])\{?\\?([A-Za-z])\}?\}?", lambda m: m.group(2) + TEX_ACCENTS[m.group(1)], t)
    t = re.sub(r"\{?\\c\{?([A-Za-z])\}?\}?", lambda m: m.group(1) + "\u0327", t)
    t = re.sub(r"\\(?:ss)\b", "\u00df", t, flags=A)
    t = re.sub(r"\\[A-Za-z]+\*? ?", "", t)
    t = re.sub(r"[{}]", "", t).replace("~", " ").replace("--", "-")
    return collapse(unicodedata.normalize("NFC", t).replace("\n", " "))


def bib_name(name):
    n = trim(name)
    if re.match(r"^\{.*\}\Z", n, A):
        return tex_text(n)
    plain = tex_text(n)
    if "," in plain or " " not in plain:
        return plain
    parts = plain.split(" ")
    return parts[-1] + ", " + " ".join(parts[:-1])


BIB_TYPES = {"article": "journal", "book": "book", "inbook": "book", "incollection": "book", "booklet": "book",
             "proceedings": "book", "inproceedings": "book", "conference": "book", "techreport": "report", "report": "report",
             "phdthesis": "report", "mastersthesis": "report", "thesis": "report", "online": "web", "electronic": "web",
             "www": "web", "webpage": "web"}
_BIB_HEAD = re.compile(r"^@([A-Za-z]+) *([{(])", A)
_BIB_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_\-]*) *= *", A)


def parse_bibtex(text):
    """Reads a BibTeX export: @type{key, field = {value} or "value" or bare, ...}."""
    s = clean_chars(text, {})
    out, i, n = [], 0, len(s)
    while i < n:
        at = s.find("@", i)
        if at < 0:
            break
        hm = _BIB_HEAD.match(s[at:at + 60])
        if not hm:
            i = at + 1
            continue
        typ, opener = hm.group(1).lower(), hm.group(2)
        close = "}" if opener == "{" else ")"
        i = at + len(hm.group(0))
        if typ in ("comment", "string", "preamble"):
            depth = 1
            while i < n and depth > 0:
                if s[i] == opener:
                    depth += 1
                elif s[i] == close:
                    depth -= 1
                i += 1
            continue
        comma, shut = s.find(",", i), s.find(close, i)
        if comma < 0 or (0 <= shut < comma):
            i = n if shut < 0 else shut + 1
            continue
        key = trim(s[i:comma].replace("\n", " "))
        i = comma + 1
        fields = {}
        while i < n:
            while i < n and s[i] in " \n,":
                i += 1
            if i >= n or s[i] == close:
                i += 1
                break
            nm = _BIB_FIELD.match(s[i:i + 80])
            if not nm:
                while i < n and s[i] != "," and s[i] != close:
                    i += 1
                continue
            i += len(nm.group(0))
            value = ""
            if s[i:i + 1] == "{":
                d2, st = 0, i
                while i < n:
                    if s[i] == "{":
                        d2 += 1
                    elif s[i] == "}":
                        d2 -= 1
                        if d2 == 0:
                            break
                    i += 1
                value = s[st + 1:i]
                i += 1
            elif s[i:i + 1] == '"':
                i += 1
                st2, d3 = i, 0
                while i < n and not (s[i] == '"' and d3 == 0):
                    if s[i] == "{":
                        d3 += 1
                    elif s[i] == "}":
                        d3 -= 1
                    i += 1
                value = s[st2:i]
                i += 1
            else:
                st3 = i
                while i < n and s[i] != "," and s[i] != close and s[i] != "\n":
                    i += 1
                value = trim(s[st3:i])
            fields[nm.group(1).lower()] = value

        def get(k):
            return tex_text(fields[k]) if k in fields else ""

        authors_raw = fields["author"] if "author" in fields else (fields["editor"] if "editor" in fields else "")
        authors = [] if trim(authors_raw) == "" else [x for x in (bib_name(a) for a in re.split(r" +and +", authors_raw.replace("\n", " "))) if x != ""]
        url, doi = get("url"), _DOI_PREFIX.sub("", get("doi"), count=1)
        raw = s[at:i]
        out.append(structured_entry({
            "authors": authors, "year": (first_year(get("year")) or get("year")) if get("year") else first_year(get("date")),
            "title": get("title"), "container": get("journal") or get("journaltitle") or get("booktitle"), "volume": get("volume"),
            "issue": get("number") or get("issue"), "pages": re.sub(" *[-\u2013]+ *", "-", get("pages")), "doi": doi, "url": url,
            "accessed": get("urldate"), "publisher": get("publisher") or get("institution") or get("organization") or get("school"),
            "type": BIB_TYPES.get(typ, "web" if url else "other"), "citeKey": key}, "bibtex", trim(raw)))
    return out


def norm_authors(s):
    return collapse(re.sub(r"[^a-z0-9 ]", " ", strip_accents(s).lower()))


def first_surname(authors):
    a = norm_authors(re.sub(r"\bet al\.?", "", authors, flags=A))
    return a.split(" ")[0] or ""


def check_url(url, tail):
    issues = []
    if (re.match(r"(?:htps?|hhtps?)[:/]", url, AI) or re.match(r"https?:\/(?!\/)", url, AI)
            or re.match(r"https?\/\/", url, AI) or re.match(r"http\/\/", url, AI)):
        issues.append({"code": "url-scheme", "severity": "problem",
                       "text": 'The web address starts "' + url[:url.find("/") + 2] + '": it should start https:// or http://.'})
    if tail:
        issues.append({"code": "url-space", "severity": "problem",
                       "text": 'The web address seems to contain a space ("' + url + " " + tail + '"), so it will not open as written.'})
    elif " " in url:
        issues.append({"code": "url-space", "severity": "problem", "text": 'The web address contains a space ("' + url + '"), so it will not open as written.'})
    hm = re.match(r"(?:[a-z]+:?\/*)?([^/?#]+)", url, AI)
    host = hm.group(1).lower() if hm else ""
    if host and ("." not in host or re.search(r"[^a-z0-9.\-:]", host) or re.search(r"\.\.|^-|-\.|\.-", host)):
        issues.append({"code": "url-host", "severity": "problem", "text": 'The site name "' + host + '" is not a well-formed address.'})
    bare = re.sub(r"^www\.", "", host)
    if bare in PLACEHOLDER_HOSTS or re.search(r"\.(?:example|invalid|test)\Z", bare):
        issues.append({"code": "url-placeholder", "severity": "problem",
                       "text": "The web address points to a placeholder site (" + bare + "), not a real source."})
    return issues


def check_entry(e, as_of):
    issues, signals = [], 0
    this_year = civil_from_days(as_of)[0]
    if not e["year"]:
        issues.append({"code": "no-year", "severity": "problem", "text": "No year found."})
    elif e["year"] != "n.d.":
        y = int(e["year"][:4])
        if y > this_year:
            issues.append({"code": "future-year", "severity": "problem", "text": "The year %d is after %s." % (y, long_day(as_of))})
            signals += 1
        elif y < 1800:
            issues.append({"code": "old-year", "severity": "warning", "text": "The year %d is unusually early: check it." % y})
    else:
        issues.append({"code": "no-date", "severity": "note", "text": "No date (n.d.): check whether the source gives one."})
    if not e["authors"]:
        issues.append({"code": "no-author", "severity": "warning", "text": "No author found."})
    elif re.match(r"(?:anon|anonymous|author|unknown|et al)\b", e["authors"], AI):
        issues.append({"code": "placeholder-author", "severity": "warning",
                       "text": 'The author looks like a placeholder ("' + e["authors"] + '").'})
        signals += 1
    if e["authors"] and re.search(r"\bet al\b", e["authors"], AI):
        issues.append({"code": "et-al", "severity": "warning",
                       "text": 'Uses "et al." in the reference list, where Harvard and APA name the authors in full.'})
        signals += 1
    if re.search(r"\[(?:author|year|title|insert|source)[^\]]*\]", e["raw"], AI) or re.match(r"title of\b", e["title"], AI):
        issues.append({"code": "placeholder", "severity": "problem", "text": "Contains placeholder text from the AI tool."})
        signals += 1
    if e["doi"]:
        d = e["doi"]
        if " " in d:
            issues.append({"code": "doi-space", "severity": "problem", "text": 'The DOI "' + d + '" contains a space.'})
        elif not re.match(r"10\.[0-9]{4,9}\/[^ ]+\Z", d, A):
            issues.append({"code": "doi-form", "severity": "problem",
                           "text": 'The DOI "' + d + '" does not have the shape 10.NNNN/something.'})
        if re.match(r"10\.(?:1234|0000|9999|xxxx)\b", d, AI) or re.search(r"x{3,}", d, AI):
            issues.append({"code": "doi-placeholder", "severity": "problem", "text": 'The DOI "' + d + '" looks like a placeholder.'})
            signals += 1
    if e["url"]:
        issues += check_url(e["url"], e["urlTail"])
    if e["type"] == "web" and not e["accessed"]:
        issues.append({"code": "web-no-date", "severity": "note", "text": "Web source with no date you accessed it."})
    looks_article = e["type"] == "journal" or (e["container"] and re.search(
        r"\b(?:journal|review|quarterly|bulletin|annals|letters|proceedings|transactions)\b", e["container"], AI))
    if looks_article and not e["volume"] and not e["pages"]:
        issues.append({"code": "journal-incomplete", "severity": "warning", "text": "Journal article with no volume or page numbers."})
        signals += 1
    if e["container"]:
        cws = [w for w in norm_authors(e["container"]).split(" ") if w != ""]
        specific = [w for w in cws if w not in GENERIC_WORDS]
        if len(cws) >= 2 and len(specific) <= 1 and re.search(r"\b(?:journal|review|annals|bulletin|quarterly)\b", e["container"], AI):
            issues.append({"code": "generic-journal", "severity": "warning",
                           "text": 'The journal name "' + e["container"] + '" is very generic.'})
            signals += 1
    if e["pages"] and re.match(r"([0-9]+)-([0-9]+)\Z", e["pages"], A):
        pr = re.match(r"([0-9]+)-([0-9]+)\Z", e["pages"], A)
        if int(pr.group(2)) < int(pr.group(1)):
            issues.append({"code": "pages-reversed", "severity": "problem",
                           "text": "The page range " + pr.group(1) + "-" + pr.group(2) + " runs backwards."})
    if not e["title"] or len(e["title"]) < 3:
        issues.append({"code": "no-title", "severity": "warning", "text": "No title found."})
    return {"issues": issues, "signals": signals}


def title_key(t):
    return [w for w in norm_authors(t).split(" ") if w != "" and w not in STOP]


def check_references(entries, citations, as_of):
    out = []
    for i, e in enumerate(entries):
        c = check_entry(e, as_of)
        out.append({"index": i, "number": i + 1, "entry": e, "issues": c["issues"], "signals": c["signals"], "cited": 0,
                    "duplicateOf": -1})
    for a in range(len(out)):
        for b in range(a):
            ea, eb = out[a]["entry"], out[b]["entry"]
            dup = False
            if ea["doi"] and eb["doi"] and ea["doi"].lower() == eb["doi"].lower():
                dup = True
            if not dup and first_surname(ea["authors"]) and first_surname(ea["authors"]) == first_surname(eb["authors"]) \
                    and ea["year"] == eb["year"]:
                dc = dice_of(title_key(ea["title"]), title_key(eb["title"]))
                if dc["total"] > 0 and dc["inter"] * 2 * 10 >= 8 * dc["total"]:
                    dup = True
            if not dup and ea["text"].lower() == eb["text"].lower():
                dup = True
            if dup:
                out[a]["duplicateOf"] = b
                out[a]["issues"].append({"code": "duplicate", "severity": "problem", "text": "Looks like a duplicate of entry %d." % (b + 1)})
                break
    missing, matched = [], []
    any_label = any(o["entry"]["label"] for o in out)
    for cit in citations:
        hits = []
        if cit["kind"] == "key":
            for lab in cit["labels"]:
                fk = -1
                for r2, o in enumerate(out):
                    if o["entry"]["citeKey"] and o["entry"]["citeKey"].lower() == lab.lower():
                        fk = r2
                        break
                if fk >= 0:
                    hits.append(fk)
                else:
                    missing.append({"text": "@" + lab, "sentence": cit["sentence"], "near": ""})
        elif cit["kind"] == "numeric":
            for lab in cit["labels"]:
                found = -1
                for r0, o in enumerate(out):
                    if o["entry"].get("footnote") and o["entry"]["label"] == lab:
                        found = r0
                        break
                if found < 0:
                    for r, o in enumerate(out):
                        if o["entry"]["label"] == lab:
                            found = r
                            break
                if found < 0 and not any_label and 1 <= int(lab) <= len(out):
                    found = int(lab) - 1
                if found >= 0:
                    hits.append(found)
                else:
                    missing.append({"text": "[" + lab + "]", "sentence": cit["sentence"], "near": ""})
        else:
            sur, near = first_surname(cit["authors"]), ""
            for t, o in enumerate(out):
                en = o["entry"]
                ea2 = norm_authors(en["authors"])
                c_auth = norm_authors(re.sub(r"\bet al\.?", "", cit["authors"], flags=A))
                name_ok = sur != "" and (ea2.startswith(c_auth) or ea2.split(" ")[0] == sur)
                if not name_ok:
                    continue
                ey, cy = en["year"].lower(), cit["year"].lower()
                if ey == cy or (ey[:4] == cy and re.match(r"[0-9]{4}[a-z]\Z", ey, A)):
                    hits.append(t)
                elif not near:
                    near = en["authors"] + " (" + en["year"] + ")"
            if not hits:
                missing.append({"text": (cit["authors"] + ", " + cit["year"]) if cit["text"][:1] == "(" else cit["text"],
                                "sentence": cit["sentence"], "near": near})
        for h in hits:
            out[h]["cited"] += 1
            matched.append({"citation": cit["text"], "entry": h})
    uncited = problems = suspect = 0
    for row in out:
        if citations and row["cited"] == 0:
            row["issues"].append({"code": "uncited", "severity": "warning", "text": "Never cited in the text."})
            uncited += 1
        if row["signals"] >= 2 or (row["signals"] >= 1 and any(x["code"] == "journal-incomplete" for x in row["issues"])):
            row["verdict"] = "suspect"
        elif any(x["severity"] == "problem" for x in row["issues"]):
            row["verdict"] = "fix"
        elif any(x["severity"] == "warning" for x in row["issues"]):
            row["verdict"] = "warn"
        else:
            row["verdict"] = "ok"
        if row["verdict"] == "suspect":
            suspect += 1
        if row["verdict"] in ("suspect", "fix"):
            problems += 1
    return {"entries": out, "missing": missing, "matched": matched, "uncited": uncited, "problems": problems,
            "suspect": suspect, "flagged": sum(1 for o in out if o["verdict"] != "ok")}


# ---------------------------------------------------------------- the whole analysis

def analyse(inp):
    as_of = inp.get("asOf")
    if not isinstance(as_of, int):
        as_of = days_from_civil(2026, 11, 28)
    draft_doc = read_document(inp.get("draft") or "")
    final_doc = read_document(inp.get("final") or "")
    has_final = len(final_doc["blocks"]) > 0
    checked_doc = final_doc if has_final else draft_doc
    prompt = read_prompt(inp.get("prompt") or "")
    notes = notes_index(inp.get("notes") or "")
    draft_sents = body_sentences(draft_doc)
    final_sents = body_sentences(final_doc) if has_final else []
    sents = final_sents if has_final else draft_sents
    changes = analyse_changes(draft_sents, final_sents) if (has_final and draft_sents) else None
    messages = []

    ref_source, ref_lines, footnotes = "none", [], checked_doc["footnotes"]
    ref_input = trim(clean_chars(inp.get("references") or "", {}).replace("\n", " "))
    if ref_input != "":
        rd = clean_chars(inp.get("references"), {}).split("\n")
        ref_lines, started = [], False
        for line in rd:
            if not started and is_ref_heading(re.sub(r"^#+ *", "", trim(line))):
                started = True
                continue
            if trim(line) != "":
                started = True
            ref_lines.append(line)
        ref_source = "list"
        if checked_doc["refLines"]:
            messages.append("Your text has its own reference list too; the separate list you gave is the one checked.")
    elif checked_doc["refLines"] or footnotes:
        ref_lines = checked_doc["refLines"]
        ref_source = "final" if has_final else "draft"
    ref_format, structured = "text", []
    if ref_source == "list" and looks_ris(inp.get("references")):
        ref_format, structured, ref_lines = "ris", parse_ris(inp.get("references")), []
    elif ref_source == "list" and looks_bibtex(inp.get("references")):
        ref_format, structured, ref_lines = "bibtex", parse_bibtex(inp.get("references")), []
    if ref_format != "text" and not structured:
        messages.append("The reference list looks like a " + ("RIS" if ref_format == "ris" else "BibTeX")
                        + " export but no records could be read from it.")
    split = split_entries(ref_lines)
    for fn in footnotes:
        split.append({"label": fn["label"], "text": fn["text"], "merged": False, "footnote": True})
    for se in structured:
        se["footnote"] = False
    entries = list(structured)
    for x in split:
        e = parse_entry(x["text"], x["label"])
        e["footnote"] = bool(x.get("footnote"))
        entries.append(e)
    merged_count = sum(1 for x in split if x["merged"])

    citations, scans = [], []
    for s, sent in enumerate(sents):
        scan = scan_sentence(sent["text"])
        scans.append(scan)
        for cc in scan["citations"]:
            citations.append({"kind": cc["kind"], "text": cc["text"], "authors": cc["authors"], "year": cc["year"],
                              "page": cc["page"], "labels": cc["labels"], "sentence": s})
    refs = check_references(entries, citations, as_of)
    refs["source"] = ref_source
    refs["format"] = ref_format
    refs["citations"] = len(citations)
    refs["mergedSplit"] = merged_count

    claims = []
    for i, sent in enumerate(sents):
        sc = scans[i]
        kind_names = [k for k in KIND_ORDER if k in sc["kinds"]]
        if not kind_names:
            continue
        missing_here = [mm["text"] for mm in refs["missing"] if mm["sentence"] == i] if (entries or ref_source != "none") else []
        origin = changes["sentences"][i]["cls"] if changes else ""
        nt = compare_notes(sent["text"], sc, notes)
        scored = score_claim(sc["kinds"], sc, {"missing": missing_here, "prompt": prompt, "notes": nt, "origin": origin})
        claims.append({
            "q": len(claims) + 1, "key": sentence_key(sent["text"]), "sentence": i, "para": sent["para"], "text": sent["text"],
            "kinds": kind_names, "spans": sc["spans"], "score": scored["score"], "level": level_of(scored["score"]),
            "reasons": scored["reasons"], "checks": checks_for(sc["kinds"], sc), "origin": origin, "notes": nt,
        })
    ranked = sorted(claims, key=lambda c: (-c["score"], c["q"]))
    if not sents:
        messages.append("There is no text to check yet: paste the AI draft (and your final version, if you have one).")
    if citations and not entries:
        messages.append("The text cites sources but no reference list was found, so citations could not be matched. "
                        "Paste the list or add a \"References\" heading above it.")
    if has_final and not draft_sents:
        messages.append("There is a final version but no AI draft, so nothing can be compared.")
    if merged_count:
        messages.append(plural(merged_count, "reference entry was", "reference entries were") + " run together with another and have been split.")
    return {
        "asOf": as_of, "checked": "final" if has_final else "draft", "hasFinal": has_final, "hasDraft": len(draft_sents) > 0,
        "sentences": [{"text": x["text"], "para": x["para"]} for x in sents],
        "headings": [b["text"] for b in checked_doc["blocks"] if b["kind"] == "heading"],
        "claims": claims, "ranked": [c["q"] for c in ranked], "refs": refs, "changes": changes,
        "prompt": prompt, "notesGiven": len(notes) > 0, "notesSentences": len(notes),
        "cleaning": {"draft": draft_doc["cleaning"], "final": final_doc["cleaning"]}, "messages": messages,
        "words": sum(len(x["toks"]) for x in sents),
    }


# ---------------------------------------------------------------- statuses and the summary

STATUSES = ["unchecked", "verified", "corrected", "removed"]
REF_STATUSES = ["unchecked", "checked", "fixed", "removed"]


def status_of(checks, key):
    c = checks.get(key) if isinstance(checks, dict) else None
    return c["status"] if isinstance(c, dict) and c.get("status") in STATUSES[1:] else "unchecked"


def ref_status_of(ref_checks, key):
    c = ref_checks.get(key) if isinstance(ref_checks, dict) else None
    return c["status"] if isinstance(c, dict) and c.get("status") in REF_STATUSES[1:] else "unchecked"


def count_resolved(a, checks, kind):
    return sum(1 for c in a["claims"] if kind in c["kinds"] and status_of(checks, c["key"]) != "unchecked")


def summarise(a, checks, ref_checks):
    s = {"claims": len(a["claims"]), "high": 0, "medium": 0, "low": 0, "verified": 0, "corrected": 0, "removed": 0,
         "unchecked": 0, "highUnchecked": 0, "leftovers": 0, "conflicts": 0, "resolved": 0}
    for c in a["claims"]:
        st = status_of(checks, c["key"])
        s[c["level"]] += 1
        s[st] += 1
        if st == "unchecked" and c["level"] == "high":
            s["highUnchecked"] += 1
        if "leftover" in c["kinds"]:
            s["leftovers"] += 1
        if c["notes"]["status"] == "conflict":
            s["conflicts"] += 1
    s["resolved"] = s["claims"] - s["unchecked"]
    flagged = [e for e in a["refs"]["entries"] if e["verdict"] != "ok"]
    s["refs"] = len(a["refs"]["entries"])
    s["refFlagged"] = len(flagged)
    s["refProblems"] = a["refs"]["problems"]
    s["refSuspect"] = a["refs"]["suspect"]
    s["refMissing"] = len(a["refs"]["missing"])
    s["refResolved"] = sum(1 for e in flagged if ref_status_of(ref_checks, e["entry"]["key"]) != "unchecked")
    s["refUnresolved"] = s["refFlagged"] - s["refResolved"]
    s["complete"] = s["claims"] > 0 and s["unchecked"] == 0 and s["refUnresolved"] == 0
    s["ready"] = s["highUnchecked"] == 0 and s["leftovers"] - count_resolved(a, checks, "leftover") == 0
    return s


# ---------------------------------------------------------------- re-checking a new version

def compare_versions(baseline_text, a, checks):
    """Compares the claims now with those in the version recorded as checked: new, edited (with the old mark),
    unchanged (marks carry over, because a mark belongs to the exact sentence) and gone."""
    out = {"newClaims": [], "changed": [], "unchanged": [], "gone": []}
    prev = analyse({"draft": baseline_text or "", "asOf": a["asOf"]})
    cur = set(c["key"] for c in a["claims"])
    before = set(p["key"] for p in prev["claims"])
    loose = [p for p in prev["claims"] if p["key"] not in cur]
    used = [False] * len(loose)

    def note_of(key):
        c = checks.get(key) if isinstance(checks, dict) else None
        return c["note"] if isinstance(c, dict) and isinstance(c.get("note"), str) else ""

    for c in a["claims"]:
        if c["key"] in before:
            out["unchanged"].append(c["q"])
            continue
        cw = words(c["text"])
        best, best_d = -1, None
        for l, p in enumerate(loose):
            if used[l]:
                continue
            d = dice_of(cw, words(p["text"]))
            if d["inter"] * 2 * 100 >= REWORD_DICE * d["total"] and (best_d is None or d["inter"] * best_d["total"] > best_d["inter"] * d["total"]):
                best, best_d = l, d
        if best >= 0:
            used[best] = True
            p = loose[best]
            out["changed"].append({"q": c["q"], "before": p["text"], "key": p["key"], "status": status_of(checks, p["key"]),
                                   "note": note_of(p["key"]), "ops": lcs_ops(_split_tokens(p["text"]), _split_tokens(c["text"]))})
        else:
            out["newClaims"].append(c["q"])
    for g, p in enumerate(loose):
        if not used[g]:
            out["gone"].append({"text": p["text"], "key": p["key"], "status": status_of(checks, p["key"]), "note": note_of(p["key"])})
    return out


# ---------------------------------------------------------------- the session log

SESSION_FIELDS = ["date", "assignment", "tool", "purpose", "prompt", "used", "changed", "checked", "minutes", "person"]
SESSION_HEADER = ["Date", "Assignment", "Tool", "Purpose", "Prompt summary", "What I used", "What I changed",
                  "What I checked", "Minutes", "Person"]
SESSION_ALIASES = {
    "date": ["date", "day", "when", "session date", "timestamp", "date used", "on"],
    "assignment": ["assignment", "project", "module", "deliverable", "piece of work", "document", "course", "task name", "work"],
    "tool": ["tool", "ai tool", "assistant", "ai assistant", "model", "service", "ai used", "app", "tool used", "ai"],
    "purpose": ["purpose", "task", "use", "what for", "used for", "activity", "reason", "why"],
    "prompt": ["prompt summary", "prompt", "prompts", "what i asked", "question", "request", "asked"],
    "used": ["what i used", "used", "kept", "output used", "what i kept", "output"],
    "changed": ["what i changed", "changed", "changes", "edits", "my changes", "what i edited"],
    "checked": ["what i checked", "checked", "verification", "verified", "checks"],
    "minutes": ["minutes", "mins", "duration", "time", "time spent", "time (min)", "time (mins)", "length"],
    "person": ["person", "name", "author", "who", "student", "contributor", "team member", "by"],
}


def header_key(h):
    return collapse(re.sub(r"[^a-z0-9() ]", " ", str(h).lower()))


def map_session_header(header):
    mapping, used = {}, set()
    for field in SESSION_FIELDS:
        for alias in SESSION_ALIASES[field]:
            if field in mapping:
                break
            for i, h in enumerate(header):
                if i not in used and header_key(h) == alias:
                    mapping[field] = i
                    used.add(i)
                    break
    return mapping


def parse_sessions(text):
    clean = clean_chars(text, {})
    rows = parse_csv(clean)["rows"]
    messages, sessions = [], []
    h = 0
    while h < len(rows) and all(trim(c) == "" for c in rows[h]):
        h += 1
    if h >= len(rows):
        return {"sessions": [], "messages": ["The file is empty."], "columns": {}}
    mapping = map_session_header(rows[h])
    if "date" not in mapping and "tool" not in mapping:
        return {"sessions": [], "messages": ['No "Date" or "Tool" column found in the first row, so this does not look like a '
                                             "session log. Download the template to see the columns."], "columns": mapping}
    used_cols = set(mapping.values())
    ignored = [c for i, c in enumerate(rows[h]) if trim(c) != "" and i not in used_cols]
    if ignored:
        messages.append("Columns not used: " + ", ".join('"' + trim(c) + '"' for c in ignored) + ".")
    for r in range(h + 1, len(rows)):
        row = rows[r]
        if all(trim(c) == "" for c in row):
            continue

        def get(field):
            if field in mapping and mapping[field] < len(row):
                return collapse(row[mapping[field]].replace("\n", " "))
            return ""

        s = {"date": "", "day": None, "assignment": get("assignment"), "tool": get("tool"), "purpose": get("purpose"),
             "prompt": get("prompt"), "used": get("used"), "changed": get("changed"), "checked": get("checked"),
             "minutes": "", "person": get("person")}
        raw_date = get("date")
        pd = parse_date(raw_date)
        if pd["day"] is not None:
            s["day"], s["date"] = pd["day"], iso_day(pd["day"])
            if pd["note"]:
                messages.append('Row %d: the date "%s" was %s.' % (r + 1, raw_date, pd["note"]))
        elif raw_date != "":
            s["date"] = raw_date
            messages.append('Row %d: could not read the date "%s" (%s); kept as typed.' % (r + 1, raw_date, pd["note"]))
        raw_min = get("minutes")
        if raw_min != "":
            mm = re.match(r"([0-9]{1,4})(?: ?(?:min|mins|minutes|m))?\Z", raw_min, AI)
            hm = re.match(r"([0-9]{1,2}):([0-9]{2})\Z", raw_min, A)
            if mm:
                s["minutes"] = str(int(mm.group(1)))
            elif hm:
                s["minutes"] = str(int(hm.group(1)) * 60 + int(hm.group(2)))
            else:
                messages.append('Row %d: "%s" is not a number of minutes; left blank.' % (r + 1, raw_min))
        if not s["tool"] and not s["purpose"] and not s["date"]:
            messages.append("Row %d: no date, tool or purpose, so it was skipped." % (r + 1))
            continue
        if not s["tool"]:
            messages.append("Row %d: no tool named." % (r + 1))
        sessions.append(s)
    return {"sessions": sessions, "messages": messages, "columns": mapping}


def sort_sessions(lst):
    def key(s):
        d = s.get("day")
        return (1e9 if d is None else d, s.get("person") or "", s.get("tool") or "", s.get("purpose") or "")
    return sorted(lst, key=key)


def sessions_for(sessions, assignment):
    a = collapse(str(assignment or "").lower())
    if a == "":
        return list(sessions)
    if not any(trim(s.get("assignment") or "") != "" for s in sessions):
        return list(sessions)
    out = []
    for s in sessions:
        x = collapse(str(s.get("assignment") or "").lower())
        if x == "" or x == a or a in x or x in a:
            out.append(s)
    return out


def sessions_csv(sessions):
    return csv_text(SESSION_HEADER, [[s["date"], s["assignment"], s["tool"], s["purpose"], s["prompt"], s["used"],
                                      s["changed"], s["checked"], s["minutes"], s["person"]] for s in sort_sessions(sessions)])


# ---------------------------------------------------------------- the declaration

TEMPLATES = [
    {"id": "statement", "name": "Statement for a university submission"},
    {"id": "appendix", "name": "Full log for an appendix"},
    {"id": "short", "name": "Short statement for a submission box"},
    {"id": "work", "name": "Note for a manager or client"},
]
LEVELS = [
    {"id": "none", "text": "I did not use AI tools for this work."},
    {"id": "planning", "text": "I used AI tools for ideas and planning only; none of the AI's wording is in the final text."},
    {"id": "assisted", "text": "I used AI tools to help draft and edit parts of this work, and I reviewed and changed what they produced."},
    {"id": "integrated", "text": "AI-generated text forms part of this work, as described below, and I have checked it."},
]


def level_text(level_id):
    for lv in LEVELS:
        if lv["id"] == level_id:
            return lv["text"]
    return LEVELS[2]["text"]


def tools_used(sessions):
    seen, out = set(), []
    for s in sessions:
        t = trim(s.get("tool") or "")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def session_date(s):
    return long_day(s["day"]) if s.get("day") is not None else (s.get("date") or "undated")


def session_line(s):
    bits = [session_date(s) + ", " + (s.get("tool") or "unnamed tool") + ": " + (s.get("purpose") or "no purpose given") + "."]
    if s.get("prompt"):
        bits.append('Prompt in brief: "' + s["prompt"].replace('"', "'") + '".')
    if s.get("used"):
        bits.append("What I used: " + re.sub(r"\.\Z", "", s["used"]) + ".")
    if s.get("changed"):
        bits.append("What I changed: " + re.sub(r"\.\Z", "", s["changed"]) + ".")
    if s.get("checked"):
        bits.append("What I checked: " + re.sub(r"\.\Z", "", s["checked"]) + ".")
    return " ".join(bits)


def change_sentence(a, who):
    ch = a["changes"]
    if not ch:
        return ""
    c = ch["counts"]
    mine = "my" if who is None else "the"
    return ("About %d%% of the words in %s final text appear word for word in the AI draft (in runs of %d or more words). "
            "Of %s %s, %d %s kept from the AI draft, %d edited, %d reworded and %d written by %s; %s of the AI draft %s left out."
            % (ch["keptShare"], mine, MIN_RUN, mine, plural(ch["finalSentences"], "sentence"), c["kept"],
               "is" if c["kept"] == 1 else "are", c["edited"], c["reworded"], c["yours"], "me" if who is None else who,
               plural(c["dropped"], "sentence"), "was" if c["dropped"] == 1 else "were"))


def check_sentence(s, who):
    if not s["claims"]:
        return "The checker found no statements in the text that needed checking."
    parts = []
    if s["verified"]:
        parts.append("%d verified against a source" % s["verified"])
    if s["corrected"]:
        parts.append("%d corrected" % s["corrected"])
    if s["removed"]:
        parts.append("%d removed" % s["removed"])
    out = ("I" if who is None else who) + " went through " + plural(s["claims"], "statement") + \
        " flagged for checking (%d high risk, %d medium, %d low)" % (s["high"], s["medium"], s["low"])
    out += (": " + list_and(parts) + ".") if parts else "."
    if s["unchecked"]:
        out += " " + plural(s["unchecked"], "statement is", "statements are") + " not yet marked as checked" + \
            ((", including %d high risk." % s["highUnchecked"]) if s["highUnchecked"] else ".")
    else:
        out += " None is left unchecked."
    return out


def ref_sentence(s, who):
    if not s["refs"]:
        return ""
    out = ("I checked my reference list (" if who is None else "The reference list (") + plural(s["refs"], "entry", "entries") + \
        (") by hand" if who is None else ") was checked by hand")
    if s["refFlagged"]:
        out += ": %d flagged for attention, %d dealt with" % (s["refFlagged"], s["refResolved"])
    return out + "."


def uniq_lower(lst):
    seen, out = set(), []
    for x in lst:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x[:1].lower() + x[1:])
    return out


def clip(s, n):
    return trim(s[:n - 3]) + "..." if len(s) > n else s


def declaration(a, state):
    p = state.get("project") or {}
    tpl = p.get("template") or "statement"
    sessions = sort_sessions(sessions_for(state.get("sessions") or [], p.get("assignment")))
    checks = state.get("checks") or {}
    s = summarise(a, checks, state.get("refChecks") or {})
    as_of = state["asOf"] if isinstance(state.get("asOf"), int) else a["asOf"]
    if p.get("date"):
        pdd = parse_date(p["date"])["day"]
        date_text = long_day(pdd) if pdd is not None else p["date"]
    else:
        date_text = long_day(as_of)
    tools = tools_used(sessions)
    name = trim(p.get("person") or "")
    title = trim(p.get("title") or "") or "this work"
    assignment = trim(p.get("assignment") or "")
    warnings = []
    if not sessions:
        warnings.append("No sessions in the log for this assignment: add at least the session that produced the AI draft.")
    if s["highUnchecked"]:
        warnings.append(plural(s["highUnchecked"], "high-risk statement is", "high-risk statements are") + " still unchecked. The declaration says so.")
    if not name:
        warnings.append("Add your name so the declaration can be signed.")
    if p.get("level") == "none" and sessions:
        warnings.append('You chose "I did not use AI tools", but your log has ' + plural(len(sessions), "session") + " for this work.")
    if a["changes"] and p.get("level") in ("none", "planning") and a["changes"]["keptShare"] >= 10:
        warnings.append('You chose "' + ("I did not use AI tools" if p.get("level") == "none" else "ideas and planning only")
                        + '", but %d%% of your final text is the AI draft\'s wording, word for word. Choose the description that fits.'
                        % a["changes"]["keptShare"])
    blocks = []

    def para(text):
        blocks.append({"type": "p", "text": text})

    def heading(text):
        blocks.append({"type": "h", "text": text})

    def item(text):
        blocks.append({"type": "li", "text": text})

    def fields(lst):
        blocks.append({"type": "fields", "items": [x for x in lst if x[1]]})

    if tpl == "work":
        heading("Note on AI use")
        fields([["Document", title], ["Prepared by", name], ["Date", date_text]])
        if tools:
            para("This document was prepared with help from " + list_and(tools) + ", used for "
                 + list_and(uniq_lower([x["purpose"] for x in sessions if x.get("purpose")])) + ".")
        else:
            para("No AI tools were used to prepare this document.")
        if a["changes"]:
            para(change_sentence(a, name or "the author"))
        para(check_sentence(s, name or "The author"))
        if s["refs"]:
            para(ref_sentence(s, name or "the author"))
        para("Nothing in this note was checked online by the checking tool; the checks above were done by " + (name or "the author") + ".")
    elif tpl == "short":
        bits = [level_text(p.get("level"))]
        if tools:
            span = (session_date(sessions[0]) + (" to " + session_date(sessions[-1]) if len(sessions) > 1 else "")) if sessions else ""
            bits.append("Tools: " + list_and(tools) + " (" + plural(len(sessions), "session") + ", " + span + ").")
        if a["changes"]:
            bits.append("%d%% of my final wording appears word for word in the AI draft." % a["changes"]["keptShare"])
        bits.append(("I checked %d of %s" % (s["resolved"], plural(s["claims"], "flagged statement"))
                     + (" (%d not yet checked)." % s["unchecked"] if s["unchecked"] else ".")) if s["claims"] else "")
        bits.append("I take responsibility for the content.")
        para(" ".join(b for b in bits if b))
    else:
        heading("Declaration of AI use")
        fields([["Title", title], ["Assignment", assignment], ["Module or course", trim(p.get("course") or "")],
                ["Institution", trim(p.get("institution") or "")], ["Name", name], ["Date", date_text]])
        para(level_text(p.get("level")))
        if sessions:
            para("I used " + list_and(tools if tools else ["AI tools"]) + " in " + plural(len(sessions), "session") + ":")
            for x in sessions:
                item(session_line(x))
        if a["changes"]:
            heading("How much of the final text is the AI's")
            para(change_sentence(a, None))
        heading("What I checked")
        para(check_sentence(s, None))
        if s["refs"]:
            para(ref_sentence(s, None))
        if tpl == "appendix" and a["claims"]:
            heading("Checking log")
            for c in sorted(a["claims"], key=lambda x: (-x["score"], x["q"])):
                st = status_of(checks, c["key"])
                note = trim(checks[c["key"]].get("note") or "") if isinstance(checks.get(c["key"]), dict) else ""
                item("Q%d (%s risk) \"%s\": %s" % (c["q"], c["level"], clip(c["text"], 90), st)
                     + (". " + re.sub(r"\.\Z", "", note) + "." if note else "."))
        para("The checking tool flags statements by simple rules on my own device; it does not check anything online and "
             "is not a plagiarism detector. I take full responsibility for the content of this work, including anything "
             "produced with AI help.")
        blocks.append({"type": "sign", "text": "Signed: " + (name or "____________________") + "    Date: " + date_text})
    return {"template": tpl, "blocks": blocks, "warnings": warnings, "sessions": len(sessions), "summary": s}


def declaration_text(d):
    out = []
    bl = d["blocks"]
    for i, b in enumerate(bl):
        if b["type"] == "h":
            out.append(b["text"].upper())
        elif b["type"] == "fields":
            out.append("\n".join(x[0] + ": " + x[1] for x in b["items"]))
        elif b["type"] == "li":
            out.append("- " + b["text"])
        else:
            out.append(b["text"])
        nxt = bl[i + 1] if i + 1 < len(bl) else None
        out.append("\n" if b["type"] == "li" and nxt and nxt["type"] == "li" else "\n\n")
    return re.sub(r"\n+\Z", "", "".join(out)) + "\n"


def md_escape(s):
    return re.sub(r"([\\`*_\[\]#|])", r"\\\1", s)


def declaration_markdown(d):
    out = []
    bl = d["blocks"]
    for i, b in enumerate(bl):
        if b["type"] == "h":
            out.append(("# " if i == 0 else "## ") + md_escape(b["text"]))
        elif b["type"] == "fields":
            out.append("  \n".join("**" + x[0] + ":** " + md_escape(x[1]) for x in b["items"]))
        elif b["type"] == "li":
            out.append("- " + md_escape(b["text"]))
        elif b["type"] == "sign":
            out.append("*" + md_escape(b["text"]) + "*")
        else:
            out.append(md_escape(b["text"]))
        nxt = bl[i + 1] if i + 1 < len(bl) else None
        out.append("\n" if b["type"] == "li" and nxt and nxt["type"] == "li" else "\n\n")
    return re.sub(r"\n+\Z", "", "".join(out)) + "\n"


# ---------------------------------------------------------------- other files to take away

def claims_csv(a, checks):
    rows = []
    for q in a["ranked"]:
        c = a["claims"][q - 1]
        ck = checks.get(c["key"]) if isinstance(checks, dict) and isinstance(checks.get(c["key"]), dict) else {}
        rows.append(["Q%d" % c["q"], c["level"], str(c["score"]), "; ".join(KIND_LABELS[k] for k in c["kinds"]), c["text"],
                     " ".join(c["checks"]), c["origin"], "" if c["notes"]["status"] == "none" else c["notes"]["status"],
                     status_of(checks, c["key"]), ck.get("note") or ""])
    return csv_text(["Query", "Risk", "Score", "What it is", "Sentence", "What to check", "Where it came from",
                     "Against your notes", "Status", "Source or note"], rows)


def refs_csv(a, ref_checks):
    rows = []
    for r in a["refs"]["entries"]:
        ck = ref_checks.get(r["entry"]["key"]) if isinstance(ref_checks, dict) and isinstance(ref_checks.get(r["entry"]["key"]), dict) else {}
        rows.append([str(r["number"]), r["entry"]["text"], r["entry"]["type"], r["entry"]["year"], r["verdict"],
                     " ".join(x["text"] for x in r["issues"]), str(r["cited"]), ref_status_of(ref_checks, r["entry"]["key"]),
                     ck.get("note") or ""])
    for m in a["refs"]["missing"]:
        rows.append(["", m["text"], "citation", "", "missing", "Cited in the text but not in the reference list."
                     + (" Closest entry: " + m["near"] + "." if m["near"] else ""), "", "", ""])
    return csv_text(["Entry", "Reference", "Type", "Year", "Verdict", "Issues", "Times cited", "Status", "Note"], rows)


def annotated_markdown(a, checks, ref_checks, title, as_of=None):
    """The checked text with a query number after every flagged sentence, then the queries in full."""
    checks = checks if isinstance(checks, dict) else {}
    by_index = {c["sentence"]: c for c in a["claims"]}
    out = ["# Proof copy: " + md_escape(trim(title or "") or "your text"), "",
           "Checked by me, " + long_day(as_of if isinstance(as_of, int) else a["asOf"]) + ". Each flagged statement in the "
           + ("final version" if a["hasFinal"] else "draft") + " is followed by its query number; the queries are listed after the text, "
           "highest risk first. Nothing was checked online and this is not a plagiarism check.", ""]
    para, cur = [], -1

    def flush():
        if para:
            out.append(" ".join(para))
            out.append("")
        del para[:]

    for s, sent in enumerate(a["sentences"]):
        if sent["para"] != cur:
            flush()
            cur = sent["para"]
        c = by_index.get(s)
        text = md_escape(sent["text"])
        if c:
            st = status_of(checks, c["key"])
            text += " **[Qy %d: %s, %s]**" % (c["q"], c["level"], "open" if st == "unchecked" else st)
        para.append(text)
    flush()
    if a["claims"]:
        s0 = summarise(a, checks, ref_checks)
        out += ["## Queries", "", "%s flagged: %d high risk, %d medium, %d low; %d still open." % (
            plural(s0["claims"], "statement"), s0["high"], s0["medium"], s0["low"], s0["unchecked"]), ""]
        origin_words = {"kept": "kept word for word from the AI draft", "edited": "edited from the AI draft",
                        "reworded": "reworded from the AI draft", "yours": "your own words"}
        for qn in a["ranked"]:
            q = a["claims"][qn - 1]
            status = status_of(checks, q["key"])
            ck = checks.get(q["key"])
            note = trim(ck["note"]) if isinstance(ck, dict) and isinstance(ck.get("note"), str) else ""
            out.append("### Qy %d (%s risk, score %d, %s)" % (q["q"], q["level"], q["score"], "open" if status == "unchecked" else status))
            out.append("")
            out.append("> " + md_escape(q["text"]))
            out.append("")
            out.append("- **What it is:** " + ", ".join(KIND_LABELS[k] for k in q["kinds"]))
            if q["origin"]:
                out.append("- **Where it came from:** " + origin_words[q["origin"]])
            for it in q["notes"]["items"]:
                if it["result"] == "conflict":
                    out.append("- **Your notes disagree:** " + md_escape(it["note"]))
            out.append("- **Why it is flagged:** " + " ".join(("+" if x["points"] > 0 else "") + str(x["points"]) + " " + md_escape(x["text"]) for x in q["reasons"]))
            out.append("- **What to check:**")
            for t in q["checks"]:
                out.append("  - " + md_escape(t))
            out.append("- **Status:** " + ("open" if status == "unchecked" else status) + (" (" + md_escape(note) + ")" if note else ""))
            out.append("")
    flagged = [e for e in a["refs"]["entries"] if e["verdict"] != "ok"]
    if flagged or a["refs"]["missing"]:
        out += ["## References to look at", ""]
        words_for = {"suspect": "look it up by hand", "fix": "needs fixing", "warn": "worth a look"}
        for e in flagged:
            rs = ref_status_of(ref_checks, e["entry"]["key"])
            out.append("- " + md_escape(e["entry"]["text"]) + " **(" + words_for[e["verdict"]] + (", " + rs if rs != "unchecked" else "") + ")** "
                       + md_escape(" ".join(x["text"] for x in e["issues"])))
        for m in a["refs"]["missing"]:
            out.append("- Cited in the text but not in the list: " + md_escape(m["text"]))
        out.append("")
    return re.sub(r"\n+\Z", "", "\n".join(out)) + "\n"


def clean_checks(checks, allowed):
    out = {}
    if not isinstance(checks, dict):
        return out
    for k in sorted(checks):
        c = checks[k]
        if not isinstance(c, dict) or c.get("status") not in allowed or not re.match(r"[qr][0-9a-f]{8}\Z", k, A):
            continue
        if c["status"] == allowed[0] and not (isinstance(c.get("note"), str) and c.get("note")):
            continue
        e = {"status": c["status"]}
        for f in ("note", "on", "text"):
            v = c.get(f)
            if isinstance(v, str) and v:
                e[f] = v
        out[k] = e
    return out


def field_text(v):
    """Only text and whole numbers are kept from a session; anything else becomes blank."""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and math.floor(v) == v and abs(v) < 1e15:
        return str(int(v))
    return ""


def clean_session(s):
    out = {}
    for f in SESSION_FIELDS:
        out[f] = field_text(s.get(f)) if isinstance(s, dict) else ""
    pd = parse_date(out["date"])
    out["day"] = pd["day"]
    if pd["day"] is not None:
        out["date"] = iso_day(pd["day"])
    return out


PROJECT_FIELDS = ["title", "assignment", "course", "institution", "person", "date", "level", "template"]


def project_file(state):
    p = state.get("project") or {}
    proj = {f: str(p.get(f) or "") for f in PROJECT_FIELDS}
    texts = state.get("texts") or {}
    as_of = state["asOf"] if isinstance(state.get("asOf"), int) else days_from_civil(2026, 11, 28)
    sessions = sort_sessions([clean_session(x) for x in (state.get("sessions") or [])])
    b = state.get("baseline")
    doc = {
        "format": FORMAT, "version": VERSION, "saved": iso_day(as_of),
        "project": proj,
        "texts": {k: str(texts.get(k) or "") for k in ("draft", "final", "prompt", "references", "notes")},
        "sessions": [{f: x[f] for f in SESSION_FIELDS} for x in sessions],
        "checks": clean_checks(state.get("checks"), STATUSES),
        "refChecks": clean_checks(state.get("refChecks"), REF_STATUSES),
        "baseline": {"text": b["text"] if isinstance(b, dict) and isinstance(b.get("text"), str) else "",
                     "on": b["on"] if isinstance(b, dict) and isinstance(b.get("on"), str) else ""},
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def read_project(text):
    try:
        data = json.loads(re.sub("^\ufeff", "", str(text)))
    except ValueError:
        return {"ok": False, "message": "This is not a project file: it is not valid JSON."}
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return {"ok": False, "message": 'This JSON file is not a Checked by me project (its "format" is missing or different).'}
    if not isinstance(data.get("version"), (int, float)) or isinstance(data.get("version"), bool) or data["version"] > VERSION:
        return {"ok": False, "message": "This project was saved by a newer version (%s)." % data.get("version")}
    p = data.get("project") if isinstance(data.get("project"), dict) else {}
    project = {f: p[f] if isinstance(p.get(f), str) else "" for f in PROJECT_FIELDS}
    t = data.get("texts") if isinstance(data.get("texts"), dict) else {}
    texts = {k: t[k] if isinstance(t.get(k), str) else "" for k in ("draft", "final", "prompt", "references", "notes")}
    sessions = [clean_session(x) for x in data.get("sessions", []) if isinstance(x, dict)] if isinstance(data.get("sessions"), list) else []
    b = data.get("baseline") if isinstance(data.get("baseline"), dict) else None
    return {"ok": True, "project": project, "texts": texts, "sessions": sessions,
            "checks": clean_checks(data.get("checks") if isinstance(data.get("checks"), dict) else {}, STATUSES),
            "refChecks": clean_checks(data.get("refChecks") if isinstance(data.get("refChecks"), dict) else {}, REF_STATUSES),
            "saved": data["saved"] if isinstance(data.get("saved"), str) else "",
            "baseline": {"text": b["text"] if isinstance(b, dict) and isinstance(b.get("text"), str) else "",
                         "on": b["on"] if isinstance(b, dict) and isinstance(b.get("on"), str) else ""}}


# ---------------------------------------------------------------- Word files

def _xml_entity(m):
    e = m.group(1)
    named = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}
    if e in named:
        return named[e]
    code = int(e[2:], 16) if e[1:2] == "x" else int(e[1:], 10)
    if 0 < code < 0xD800 or 0xE000 <= code < 0x10000:
        return chr(code)
    return ""


def xml_decode(s):
    return re.sub(r"&(lt|gt|amp|quot|apos|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});", _xml_entity, s)


DOCX_P_RE = re.compile(r"<w:p(?: [^>]*)?>([\s\S]*?)</w:p>", A)
DOCX_TOKEN_RE = re.compile(r"<w:t(?: [^>]*)?>([^<]*)</w:t>|<w:(?:tab|br|cr)(?: [^>]*)?/>|<w:footnoteReference [^>]*?w:id=\"(-?[0-9]+)\"[^>]*/>", A)


def docx_paragraphs(xml):
    out = []
    for m in DOCX_P_RE.finditer(xml):
        body = m.group(1)
        text = ""
        for t in DOCX_TOKEN_RE.finditer(body):
            if t.group(1) is not None:
                text += xml_decode(t.group(1))
            elif t.group(2) is not None:
                text += "[^" + t.group(2) + "]"
            else:
                text += " "
        text = collapse(text.replace("\n", " "))
        if text == "":
            out.append("")
            continue
        st = re.search(r'<w:pStyle w:val="([^"]*)"', body, A)
        style = st.group(1).lower().replace(" ", "") if st else ""
        hm = re.match(r"heading([1-6])\Z", style, A)
        if hm:
            text = "######"[:int(hm.group(1))] + " " + text
        elif style == "title":
            text = "# " + text
        elif "<w:numPr>" in body or re.match(r"listparagraph|listbullet|listnumber", style, A):
            text = "- " + text
        out.append(text)
    return out


def docx_text(document_xml, footnotes_xml=""):
    """Turns the XML inside a .docx (the document and, if any, its footnotes) into Markdown-like text."""
    paras = [p for p in docx_paragraphs(str(document_xml or "")) if p != ""]
    notes = []
    for m in re.finditer(r"<w:footnote (?:[^>]*? )?w:id=\"(-?[0-9]+)\"[^>]*>([\s\S]*?)</w:footnote>", str(footnotes_xml or ""), A):
        if int(m.group(1)) <= 0:
            continue
        body = " ".join(p for p in docx_paragraphs(m.group(2)) if p != "")
        if body != "":
            notes.append("[^" + m.group(1) + "]: " + body)
    return "\n\n".join(paras) + ("\n\n" + "\n".join(notes) if notes else "") + "\n"


SESSION_TEMPLATE = csv_text(SESSION_HEADER, [["2026-11-02", "Module code and assignment", "The AI tool you used",
                                              "What you used it for", "Your prompt in one line",
                                              "What you kept from its answer", "What you changed",
                                              "What you checked, and against what", "15", "Your name"]])
