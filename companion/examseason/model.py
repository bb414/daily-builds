"""The planning model, mirrored function by function from src/model.js.

Reads exam timetables, topic lists, availability and calendars; builds the
deterministic day-by-day revision plan; tracks progress; writes CSV, .ics,
text and project files. The agreement tests run this and the browser model
on the same inputs and compare everything, including the bytes of every
exported file, so any change here must be made there too (and the other way
round).

Dates are whole day numbers (days since 1 January 1970), times are minutes
after midnight, and every sort has an explicit tie-break.
"""

import json
import re
from functools import cmp_to_key

VERSION = 1

A = re.ASCII
AI = re.ASCII | re.IGNORECASE

# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

SPACE_CHARS = ' \t\r\n\f\v\u00a0\ufeff'


def trim(s):
    if s is None:
        return ''
    return str(s).strip(SPACE_CHARS)


def squash(s):
    return trim(re.sub(r'[ \t]+', ' ', str(s).replace('\u00a0', ' ')))


def lower(s):
    return str(s).lower()


def cmp(a, b):
    return -1 if a < b else (1 if a > b else 0)


def ceil_div(a, b):
    return (a + b - 1) // b


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def scale_decimal(text, factor):
    """A plain decimal such as "2.5" times an integer factor, rounded half up, in integers."""
    m = re.match(r'^([0-9]+)(?:\.([0-9]{1,4}))?$', text, A)
    if not m:
        return None
    frac = m.group(2) or ''
    den = 10 ** len(frac)
    num = int(m.group(1)) * den + (int(frac) if frac else 0)
    return (num * factor * 2 + den) // (2 * den)


def slugify(s):
    out = re.sub(r'[^a-z0-9]+', '-', lower(s), flags=A).strip('-')
    out = out[:48].rstrip('-')
    return out or 'item'


def plural(n, one, many=None):
    return '%d %s' % (n, one if n == 1 else (many or one + 's'))


def sort_by(items, fn):
    return sorted(items, key=cmp_to_key(fn))


# ----------------------------------------------------------------------
# Dates and times
# ----------------------------------------------------------------------

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
MON3 = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
WD3 = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def day_from_ymd(y, m, d):
    y -= 1 if m <= 2 else 0
    era = y // 400
    yoe = y - era * 400
    mp = (m + 9) % 12
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def ymd_from_day(z):
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + 1 if m <= 2 else y, m, d)


def days_in_month(y, m):
    return day_from_ymd(y + 1 if m == 12 else y, 1 if m == 12 else m + 1, 1) - day_from_ymd(y, m, 1)


def weekday(day):
    return ((day % 7) + 7 + 3) % 7


def iso_day(day):
    t = ymd_from_day(day)
    return '%d-%02d-%02d' % t


def make_day(y, m, d):
    if m < 1 or m > 12 or d < 1 or y < 1900 or y > 2200:
        return None
    if d > days_in_month(y, m):
        return None
    return day_from_ymd(y, m, d)


def from_iso(s):
    m = re.match(r'^([0-9]{4})-([0-9]{2})-([0-9]{2})$', trim(s), A)
    if not m:
        return None
    return make_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def fmt_day(day):
    t = ymd_from_day(day)
    return '%s %d %s %d' % (WD3[weekday(day)], t[2], MONTHS[t[1] - 1][:3], t[0])


def fmt_short(day):
    t = ymd_from_day(day)
    return '%s %d %s' % (WD3[weekday(day)], t[2], MONTHS[t[1] - 1][:3])


def fmt_long(day):
    t = ymd_from_day(day)
    return '%s %d %s %d' % (WEEKDAYS[weekday(day)], t[2], MONTHS[t[1] - 1], t[0])


def fmt_time(minute):
    return '%02d:%02d' % (minute // 60, minute % 60)


def fmt_dur(minute):
    if minute < 60:
        return '%d min' % minute
    h, r = minute // 60, minute % 60
    return '%d h' % h + (' %d min' % r if r else '')


def fmt_hours(minute):
    neg = minute < 0
    tenths = (abs(minute) * 10 + 30) // 60
    txt = str(tenths // 10) + ('.%d' % (tenths % 10) if tenths % 10 else '')
    return ('-' if neg else '') + txt + ' h'


MONTH_RE = '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?'
WEEKDAY_RE = re.compile(r'^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?[ ]+', A)


def full_year(text):
    y = int(text)
    return 2000 + y if len(text) <= 2 else y


def guess_year(m, d, ref):
    y0 = ymd_from_day(ref)[0]
    for y in range(y0 - 1, y0 + 2):
        day = make_day(y, m, d)
        if day is not None and day >= ref - 60:
            return day
    return make_day(y0 + 1, m, d)


RE_ISO = re.compile(r'^([0-9]{4})[\-/.]([0-9]{1,2})[\-/.]([0-9]{1,2})(?:[t ].*)?$', A)
RE_COMPACT = re.compile(r'^([0-9]{4})([0-9]{2})([0-9]{2})(?:t[0-9]{4,6}z?)?$', A)
RE_NUMERIC = re.compile(r'^([0-9]{1,2})[/.\-]([0-9]{1,2})[/.\-]([0-9]{4}|[0-9]{2})(?: .*)?$', A)
RE_DAY_MONTH = re.compile('^([0-9]{1,2})[ \\-./]?' + MONTH_RE + '(?:[ \\-./]?([0-9]{4}|[0-9]{2}))?(?: .*)?$', A)
RE_MONTH_DAY = re.compile('^' + MONTH_RE + ' ([0-9]{1,2})(?: ([0-9]{4}))?(?: .*)?$', A)
DEFAULT_REF = day_from_ymd(2026, 9, 1)


def parse_date(text, order='DMY', ref=None):
    s = lower(squash(text)).replace(',', ' ')
    s = re.sub(r'[ ]+', ' ', s)
    s = trim(s)
    if not s:
        return None
    s = WEEKDAY_RE.sub('', s, count=1)
    s = re.sub(r'([0-9])(st|nd|rd|th)(?![a-z])', r'\1', s, flags=A)
    m = RE_ISO.match(s)
    if m:
        return make_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = RE_COMPACT.match(s)
    if m:
        return make_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = RE_NUMERIC.match(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), full_year(m.group(3))
        return make_day(y, a, b) if order == 'MDY' else make_day(y, b, a)
    m = RE_DAY_MONTH.match(s)
    if m:
        mon, dd = MON3.index(m.group(2)) + 1, int(m.group(1))
        if m.group(3):
            return make_day(full_year(m.group(3)), mon, dd)
        if dd < 1 or dd > 31:
            return None
        return guess_year(mon, dd, DEFAULT_REF if ref is None else ref)
    m = RE_MONTH_DAY.match(s)
    if m:
        mon2, d2 = MON3.index(m.group(1)) + 1, int(m.group(2))
        if m.group(3):
            return make_day(int(m.group(3)), mon2, d2)
        if d2 < 1 or d2 > 31:
            return None
        return guess_year(mon2, d2, DEFAULT_REF if ref is None else ref)
    return None


DATE_FINDERS = [
    re.compile(r'(^|[^0-9])([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})(?![0-9])', A),
    re.compile(r'(^|[^0-9])([0-9]{1,2}[/.\-][0-9]{1,2}[/.\-](?:[0-9]{4}|[0-9]{2}))(?![0-9])', A),
    re.compile('(^|[^a-z0-9])((?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\\.?,? )?[0-9]{1,2}(?:st|nd|rd|th)?[ \\-]' + MONTH_RE + '(?:,?[ \\-](?:[0-9]{4}|[0-9]{2}))?)(?![0-9a-z])', A),
    re.compile('(^|[^a-z0-9])((?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\\.?,? )?' + MONTH_RE + ' [0-9]{1,2}(?:st|nd|rd|th)?(?:,? [0-9]{4})?)(?![0-9a-z])', A),
]


def find_date(text, order='DMY', ref=None):
    s = lower(text)
    best = None
    for rx in DATE_FINDERS:
        m = rx.search(s)
        if not m:
            continue
        day = parse_date(m.group(2), order, ref)
        if day is None:
            continue
        idx = m.start() + len(m.group(1))
        if best is None or idx < best['index']:
            best = {'day': day, 'index': idx, 'length': len(m.group(2))}
    return best


def _dots_to_colons(s, require_before=True):
    out = []
    for i, c in enumerate(s):
        if c == '.':
            before = s[i - 1] if i > 0 else ''
            after = s[i + 1] if i + 1 < len(s) else ''
            ok = (i > 0 or not require_before) and before.isascii() and before.isdigit() and after.isascii() and after.isdigit()
            out.append(':' if ok else '')
        else:
            out.append(c)
    return ''.join(out)


RE_TIME = re.compile(r'^([0-9]{1,2})(?:[:h]([0-9]{2}))?(?::00)?(am|pm)?$', A)


def parse_time(text):
    s = re.sub(r'[ \t]+', '', lower(trim(text)))
    s = _dots_to_colons(s)
    if not s:
        return None
    if s in ('noon', 'midday', '12noon'):
        return 720
    m = RE_TIME.match(s)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if not m.group(2) and not m.group(3):
            return None
        if m.group(3):
            if h < 1 or h > 12:
                return None
            if m.group(3) == 'pm' and h < 12:
                h += 12
            if m.group(3) == 'am' and h == 12:
                h = 0
        elif 1 <= h <= 7:
            h += 12
    else:
        m = re.match(r'^([0-9]{2})([0-9]{2})$', s, A)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


TIME_FINDER = re.compile(r'(^|[^0-9:.])([0-9]{1,2}(?:[:.][0-9]{2})(?: ?[ap]\.?m\.?)?|[0-9]{1,2} ?[ap]\.?m\.?)(?![0-9a-z])', A)


def find_times(text):
    s = lower(text)
    out = []
    for m in TIME_FINDER.finditer(s):
        t = parse_time(_dots_to_colons(m.group(2), require_before=False))
        if t is not None:
            out.append({'min': t, 'index': m.start() + len(m.group(1)), 'length': len(m.group(2))})
    return out


def parse_duration(text, unit=''):
    s = re.sub(r'^\(|\)$', '', lower(trim(text)), flags=A)
    s = trim(s)
    if not s:
        return None
    m = re.match(r'^([0-9]{1,2}):([0-9]{2})(?::00)?$', s, A)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r'^([0-9]+(?:\.[0-9]+)?) ?(?:h|hr|hrs|hour|hours)\.?(?:,? ?(?:and )?([0-9]+) ?(?:m|min|mins|minute|minutes)?\.?)?$', s, A)
    if m:
        return scale_decimal(m.group(1), 60) + (int(m.group(2)) if m.group(2) else 0)
    m = re.match(r'^([0-9]+) ?(?:m|min|mins|minute|minutes)\.?$', s, A)
    if m:
        return int(m.group(1))
    m = re.match(r'^([0-9]+(?:\.[0-9]+)?)$', s, A)
    if m:
        if unit == 'min':
            return scale_decimal(m.group(1), 1)
        if unit == 'hour':
            return scale_decimal(m.group(1), 60)
        as_min = scale_decimal(m.group(1), 1)
        return scale_decimal(m.group(1), 60) if as_min <= 12 else as_min
    return None


def last_sunday(y, m):
    last = day_from_ymd(y, m, days_in_month(y, m))
    return last - ((weekday(last) + 1) % 7)


def utc_to_london(day, minute):
    y = ymd_from_day(day)[0]
    t = day * 1440 + minute
    start, end = last_sunday(y, 3) * 1440 + 60, last_sunday(y, 10) * 1440 + 60
    if start <= t < end:
        t += 60
    return (t // 1440, t - (t // 1440) * 1440)


# ----------------------------------------------------------------------
# Delimited text
# ----------------------------------------------------------------------

def strip_bom(text):
    text = str(text)
    return text[1:] if text[:1] == '\ufeff' else text


def split_lines(text):
    return re.split(r'\r\n|\n|\r', strip_bom(text))


def count_outside_quotes(line, ch):
    n, q = 0, False
    for c in line:
        if c == '"':
            q = not q
        elif c == ch and not q:
            n += 1
    return n


def sniff_delimiter(text):
    lines = [l for l in split_lines(text) if trim(l) != ''][:40]
    best, best_score = '', 0
    for cand in ['\t', ',', ';', '|']:
        score = sum(1 for l in lines if count_outside_quotes(l, cand) > 0)
        if score > best_score:
            best, best_score = cand, score
    return best


def parse_delimited(text, delim):
    text = strip_bom(text)
    rows = []
    state = {'cells': [], 'cell': '', 'line': 1, 'row_line': 1}
    q = False
    i, n = 0, len(text)

    def end_row():
        state['cells'].append(state['cell'])
        rows.append({'cells': state['cells'], 'line': state['row_line']})
        state['cells'] = []
        state['cell'] = ''

    while i < n:
        c = text[i]
        if q:
            if c == '"':
                if text[i + 1:i + 2] == '"':
                    state['cell'] += '"'
                    i += 2
                    continue
                q = False
                i += 1
                continue
            if c == '\n':
                state['line'] += 1
            state['cell'] += c
            i += 1
            continue
        if c == '"' and trim(state['cell']) == '':
            state['cell'] = ''
            q = True
            i += 1
            continue
        if delim and c == delim:
            state['cells'].append(state['cell'])
            state['cell'] = ''
            i += 1
            continue
        if c in '\r\n':
            end_row()
            if c == '\r' and text[i + 1:i + 2] == '\n':
                i += 1
            i += 1
            state['line'] += 1
            state['row_line'] = state['line']
            continue
        state['cell'] += c
        i += 1
    if state['cell'] != '' or state['cells']:
        end_row()
    return rows


def read_table(text):
    delim = sniff_delimiter(text)
    if delim:
        return {'delim': delim, 'rows': parse_delimited(text, delim)}
    lines = split_lines(text)
    spaced = nonblank = 0
    for l in lines:
        if trim(l) == '':
            continue
        nonblank += 1
        if re.search(r'[^ \t] {2,}[^ \t]', trim(l), A):
            spaced += 1
    use_spaces = nonblank > 0 and spaced * 2 >= nonblank
    rows = []
    for k, l in enumerate(lines):
        rows.append({'cells': re.split(r' {2,}', trim(l)) if use_spaces else [l], 'line': k + 1})
    return {'delim': '  ' if use_spaces else '', 'rows': rows}


ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", 'nbsp': ' ', 'ndash': '-', 'mdash': '-', 'hellip': '...', 'rsquo': "'", 'lsquo': "'", 'ldquo': '"', 'rdquo': '"', 'pound': '£'}


def decode_entities(s):
    def rep(m):
        k = m.group(1).lower()
        if k[0] == '#':
            n = int(k[2:], 16) if k[1] == 'x' else int(k[1:])
            return chr(n) if 0 < n < 0x110000 and (n < 0xd800 or n > 0xdfff) else ''
        return ENTITIES.get(k, m.group(0))
    return re.sub(r'&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);', rep, s)


def html_cell_text(s):
    s = re.sub(r'<[^>]*>', ' ', re.sub(r'<br\s*/?>', ' ', s, flags=AI))
    return squash(re.sub(r'[\t\r\n]+', ' ', decode_entities(s)))


def is_html_table(text):
    return bool(re.search(r'<tr[\s>]', text, AI)) and bool(re.search(r'<t[dh][\s>]', text, AI))


RE_TR = re.compile(r'<tr(?:\s[^>]*)?>', AI)
RE_CELL = re.compile(r'<t[dh](?:\s[^>]*)?>([\s\S]*?)(?:</t[dh]\s*>|(?=<t[dh][\s>])|$)', AI)


def html_rows(text):
    src = re.sub(r'<!--[\s\S]*?-->', lambda c: re.sub(r'[^\n]', ' ', c.group(0)), str(text))
    starts = [(m.start(), m.end()) for m in RE_TR.finditer(src)]
    rows, pos, line = [], 0, 1
    for i, (a, b) in enumerate(starts):
        line += src.count('\n', pos, a)
        pos = a
        end_at = starts[i + 1][0] if i + 1 < len(starts) else len(src)
        chunk = src[b:end_at]
        close = re.search(r'</tr\s*>', chunk, AI)
        if close:
            chunk = chunk[:close.start()]
        cells = [html_cell_text(cm.group(1)) for cm in RE_CELL.finditer(chunk)]
        rows.append({'cells': cells, 'line': line})
    return rows


RE_NUMERIC_DATE = re.compile(r'(^|[^0-9])([0-9]{1,2})[/.\-]([0-9]{1,2})[/.\-]([0-9]{4}|[0-9]{2})(?![0-9])', A)


def date_order_of(texts):
    dmy = mdy = either = 0
    for s in texts:
        m = RE_NUMERIC_DATE.search(str(s))
        if not m:
            continue
        a, b = int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            dmy += 1
        elif b > 12 and a <= 12:
            mdy += 1
        else:
            either += 1
    return {'order': 'MDY' if mdy > 0 and dmy == 0 else 'DMY', 'dmy': dmy, 'mdy': mdy, 'either': either}


def date_order_messages(info, out):
    if info['order'] == 'MDY':
        out['messages'].append({'level': 'info', 'text': 'Dates such as 01/13 show this file puts the month first, so every date was read that way.'})
    elif info['either'] > 0 and info['dmy'] == 0:
        out['messages'].append({'level': 'info', 'text': 'Every date could be read either way round, so day first (UK order) was assumed. Check the dates below.'})


def looks_binary(text):
    """Mostly control characters or undecodable bytes: a PDF, spreadsheet or image opened as text."""
    chars = str(text)[:4000]
    bad = sum(1 for ch in chars if ord(ch) < 9 or 13 < ord(ch) < 32 or ord(ch) == 0xfffd)
    return len(chars) > 0 and bad * 50 > len(chars)


BINARY_MESSAGE = 'This does not look like a text file (it may be a PDF, a spreadsheet or an image). Save or export it as CSV, or copy the table and paste it here.'


def parse_code_list(text):
    """A list of module codes typed by hand: "ECO3112, FIN 3020 law3207"."""
    out = []
    for piece in re.split(r'[,;\r\n]+', str(text or '')):
        rest = piece.upper()
        found = False
        f = find_code(rest)
        while f is not None:
            if f['code'] not in out:
                out.append(f['code'])
            rest = rest[f['index'] + f['length']:]
            found = True
            f = find_code(rest)
        if not found:
            for w in re.split(r'[ \t]+', piece):
                c = norm_code(w)
                if c and c not in out:
                    out.append(c)
    return out


def keep_modules(exams, codes):
    return [e for e in exams if e['code'] in codes]


def csv_cell(v):
    s = '' if v is None else str(v)
    if re.search(r'[",\r\n]', s) or re.search(r'^[ ]|[ ]$', s):
        return '"' + s.replace('"', '""') + '"'
    return s


def csv_text(rows):
    return '\ufeff' + '\r\n'.join(','.join(csv_cell(c) for c in r) for r in rows) + '\r\n'


def norm_header(s):
    return trim(re.sub(r'[^a-z0-9]+', ' ', lower(str(s)), flags=A))


def is_blank_row(cells):
    return all(trim(c) == '' for c in cells)


def map_columns(cells, synonyms, keywords):
    mp, used = {}, {}
    roles = list(synonyms.keys())
    for i, c in enumerate(cells):
        h = norm_header(c)
        if not h:
            continue
        for role in roles:
            if role not in mp and h in synonyms[role]:
                mp[role] = i
                used[i] = True
                break
    for j, c in enumerate(cells):
        if j in used:
            continue
        h2 = ' ' + norm_header(c) + ' '
        if h2 == '  ':
            continue
        for role, word in keywords:
            if role in mp:
                continue
            if (' ' + word + ' ') in h2:
                mp[role] = j
                used[j] = True
                break
    return mp


def cell(cells, idx):
    if idx is None or idx >= len(cells):
        return ''
    return trim(cells[idx])


# ----------------------------------------------------------------------
# Module codes
# ----------------------------------------------------------------------

CODE_RE = re.compile(r'(^|[^A-Za-z0-9])([A-Z]{2,5})[ \-]?([0-9]{3,5}[A-Z]?)(?=[^A-Za-z0-9]|$)', A)


def find_code(text):
    m = CODE_RE.search(str(text))
    if not m:
        return None
    return {'code': m.group(2) + m.group(3), 'index': m.start() + len(m.group(1)), 'length': len(m.group(0)) - len(m.group(1))}


def norm_code(text):
    f = find_code(str(text).upper())
    if f:
        return f['code']
    return re.sub(r'[^A-Z0-9]+', '', str(text).upper(), flags=A)


def strip_code(name, code):
    f = find_code(name)
    if not f or f['code'] != code:
        return squash(name)
    out = name[:f['index']] + ' ' + name[f['index'] + f['length']:]
    return trim(re.sub(r'^[\-:,|.\u2013 ]+|[\-:,|\u2013 ]+$', '', squash(out)))


# ----------------------------------------------------------------------
# Exam timetables
# ----------------------------------------------------------------------

EXAM_SYNONYMS = {
    'code': ['module code', 'module', 'course code', 'unit code', 'code', 'paper code', 'subject code', 'module id', 'exam code', 'component code', 'assessment code', 'module ref', 'module no'],
    'name': ['module title', 'module name', 'title', 'course title', 'course name', 'course', 'unit title', 'unit name', 'unit', 'paper', 'paper title', 'exam title', 'subject', 'module description', 'assessment title', 'examination', 'exam', 'exam name'],
    'date': ['date', 'exam date', 'day date', 'date of exam', 'examination date', 'day', 'exam day', 'date and time', 'date time', 'start date', 'when'],
    'start': ['start', 'start time', 'time', 'begins', 'from', 'exam start', 'starts', 'start at'],
    'end': ['end', 'end time', 'finish', 'finish time', 'to', 'until', 'ends', 'exam end'],
    'duration': ['duration', 'length', 'duration mins', 'duration minutes', 'duration hrs', 'duration hours', 'exam duration', 'mins', 'minutes', 'hours', 'hrs', 'length mins', 'length hours'],
    'room': ['venue', 'room', 'location', 'building', 'hall', 'exam venue', 'exam room', 'place', 'centre', 'campus'],
    'seat': ['seat', 'seat no', 'seat number', 'desk', 'desk number', 'desk no'],
    'type': ['type', 'assessment type', 'exam type', 'component', 'sitting', 'attempt', 'kind', 'format', 'mode', 'assessment', 'period'],
    'notes': ['notes', 'note', 'comments', 'comment', 'information', 'info', 'details', 'additional information', 'remarks'],
}

EXAM_KEYWORDS = [
    ('code', 'code'), ('name', 'title'), ('name', 'name'), ('date', 'date'), ('start', 'start'),
    ('end', 'finish'), ('end', 'end'), ('duration', 'duration'), ('duration', 'length'),
    ('room', 'venue'), ('room', 'room'), ('room', 'location'), ('seat', 'seat'), ('type', 'type'), ('notes', 'notes'),
]

TBC_RE = re.compile(r'^(tbc|tba|tbd|tbc\.|to be (confirmed|arranged|announced|decided|scheduled)|not yet (scheduled|published|known|confirmed|timetabled)|pending|unscheduled|awaiting confirmation|date tbc|n/a|na|\?+|-+)$', A)


def exam_header_score(mp):
    has_who = 'code' in mp or 'name' in mp
    has_when = 'date' in mp
    if not has_who or not has_when:
        return 0
    return len(mp)


def duration_unit(header):
    h = ' ' + norm_header(header) + ' '
    if re.search(r' (min|mins|minutes) ', h, A):
        return 'min'
    if re.search(r' (hr|hrs|hour|hours) ', h, A):
        return 'hour'
    return ''


def is_exam_header_row(cells):
    return len(map_columns(cells, EXAM_SYNONYMS, [])) >= 3


def read_exams(text, ref=None):
    ref = DEFAULT_REF if ref is None else ref
    text = '' if text is None else str(text)
    out = {'exams': [], 'messages': [], 'format': '', 'rows': 0, 'skipped': 0}
    if re.match(r'^\s*%PDF', text, A):
        out['format'] = 'pdf'
        out['messages'].append({'level': 'error', 'text': 'This is a PDF file. Open it, select the timetable table, copy it and paste it here, or download the CSV or calendar (.ics) version from your student portal.'})
        return out
    if re.match(r'^\s*PK', text, A) and '[Content_Types]' in text:
        out['format'] = 'xlsx'
        out['messages'].append({'level': 'error', 'text': 'This looks like an Excel workbook. Save it as CSV (File, Save as, CSV) and load that, or copy the rows and paste them here.'})
        return out
    if re.search(r'BEGIN:VCALENDAR', text, AI):
        return read_exams_ics(text, out)
    if looks_binary(text):
        out['format'] = 'binary'
        out['messages'].append({'level': 'error', 'text': BINARY_MESSAGE})
        return out
    if trim(text) == '':
        out['messages'].append({'level': 'error', 'text': 'There was nothing to read.'})
        return out
    table = {'delim': 'html', 'rows': html_rows(text)} if is_html_table(text) else read_table(text)
    rows = table['rows']
    header_at, mp = -1, None
    for i in range(min(len(rows), 30)):
        cand = map_columns(rows[i]['cells'], EXAM_SYNONYMS, EXAM_KEYWORDS)
        if exam_header_score(cand) >= 2:
            header_at, mp = i, cand
            break
    if header_at < 0:
        if table['delim'] == 'html':
            out['format'] = 'html'
            out['messages'].append({'level': 'error', 'text': 'This web page has a table, but no header row with a module and a date was found in it.'})
            return out
        return read_exam_lines(text, out, ref)
    out['format'] = 'html' if table['delim'] == 'html' else ('table' if table['delim'] == '\t' else ('spaced' if table['delim'] == '  ' else 'csv'))
    header = rows[header_at]['cells']
    unit = duration_unit(header[mp['duration']]) if 'duration' in mp else ''
    order_info = date_order_of([cell(r['cells'], mp.get('date')) for r in rows[header_at + 1:]])
    order = order_info['order']
    seen, blank = {}, 0
    for r in range(header_at + 1, len(rows)):
        cells, line = rows[r]['cells'], rows[r]['line']
        if is_blank_row(cells):
            blank += 1
            continue
        out['rows'] += 1
        if is_exam_header_row(cells):
            out['skipped'] += 1
            out['messages'].append({'level': 'info', 'line': line, 'text': 'Line %d repeats the header row, so it was skipped.' % line})
            continue
        ex = exam_from_cells(cells, mp, unit, ref, line, out['messages'], order)
        if not ex:
            out['skipped'] += 1
            continue
        key = '%s|%s|%s' % (ex['code'], 'tbc' if ex['day'] is None else ex['day'], ex['start'])
        if key in seen:
            out['skipped'] += 1
            out['messages'].append({'level': 'info', 'line': line, 'text': 'Line %d repeats %s%s, so it was skipped.' % (line, ex['code'], '' if ex['day'] is None else ' on ' + fmt_short(ex['day']))})
            continue
        seen[key] = True
        out['exams'].append(ex)
    trailing = 0
    t = len(rows) - 1
    while t > header_at and is_blank_row(rows[t]['cells']):
        trailing += 1
        t -= 1
    blank -= trailing
    if blank > 0:
        out['messages'].append({'level': 'info', 'text': plural(blank, 'blank row') + ' skipped.'})
    if header_at > 0:
        out['messages'].append({'level': 'info', 'text': 'The table starts at line %d; the %s above it were read as a title, not exams.' % (rows[header_at]['line'], plural(header_at, 'line'))})
    date_order_messages(order_info, out)
    finish_exams(out)
    return out


def exam_from_cells(cells, mp, unit, ref, line, messages, order='DMY'):
    code_cell, name_cell = cell(cells, mp.get('code')), cell(cells, mp.get('name'))
    code, name = '', ''
    if code_cell:
        f = find_code(code_cell.upper())
        code = f['code'] if f else re.sub(r'[^A-Z0-9]+', '', code_cell.upper(), flags=A)
        if f and not name_cell:
            name = strip_code(code_cell, f['code'])
    if name_cell:
        f2 = find_code(name_cell)
        if not code and f2:
            code = f2['code']
        name = strip_code(name_cell, code) if code else squash(name_cell)
    if not code and not name:
        messages.append({'level': 'warn', 'line': line, 'text': 'Line %d has no module code or title, so it was skipped.' % line})
        return None
    if not code:
        code = slugify(name).upper().replace('-', '')[:10]
    date_cell = cell(cells, mp.get('date'))
    day, tbc = None, False
    low_date = lower(squash(date_cell))
    start_from_date = end_from_date = None
    if date_cell == '' or TBC_RE.search(low_date) or re.search(r'\b(tbc|tba|tbd|to be confirmed)\b', low_date, A):
        tbc = True
        messages.append({'level': 'warn', 'line': line, 'text': 'Line %d: %s has no date yet (%s). It is listed but not planned until you add a date.' % (line, code, date_cell or 'blank')})
    else:
        day = parse_date(date_cell, order, ref)
        if day is None:
            found = find_date(date_cell, order, ref)
            if found:
                day = found['day']
        if day is None:
            tbc = True
            messages.append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the date "%s" for %s. It is listed without a date; type the date in to plan for it.' % (line, date_cell, code)})
        else:
            tms = find_times(re.sub(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}t', '', date_cell, count=1, flags=AI))
            if tms:
                start_from_date = tms[0]['min']
            if len(tms) > 1:
                end_from_date = tms[1]['min']
    start_cell, end_cell = cell(cells, mp.get('start')), cell(cells, mp.get('end'))
    start = end = None
    if start_cell:
        start = parse_time(start_cell)
        if start is None:
            ts = find_times(start_cell)
            if ts:
                start = ts[0]['min']
                if len(ts) > 1 and not end_cell:
                    end = ts[1]['min']
    if start is None:
        start = start_from_date
        if end is None:
            end = end_from_date
    if end_cell:
        end = parse_time(end_cell)
        if end is None:
            te = find_times(end_cell)
            if te:
                end = te[0]['min']
    duration = None
    dur_cell = cell(cells, mp.get('duration'))
    if dur_cell:
        duration = parse_duration(dur_cell, unit)
        if duration is None:
            messages.append({'level': 'info', 'line': line, 'text': 'Line %d: could not read the duration "%s" for %s.' % (line, dur_cell, code)})
    if duration is None and start is not None and end is not None and end > start:
        duration = end - start
    if not tbc and start is None:
        start = 570
        messages.append({'level': 'info', 'line': line, 'text': 'Line %d: no start time for %s, so 09:30 is assumed.' % (line, code)})
    if start is None:
        start = 570
    if duration is None or duration <= 0:
        duration = 120
        if not tbc:
            messages.append({'level': 'info', 'line': line, 'text': 'Line %d: no length given for %s, so 2 hours is assumed.' % (line, code)})
    duration = clamp(duration, 15, 1440)
    typ, notes = cell(cells, mp.get('type')), cell(cells, mp.get('notes'))
    resit = bool(re.search(r'\b(resit|re-sit|referral|reassessment|re-assessment|deferred|supplementary)\b', typ + ' ' + notes + ' ' + name_cell, AI))
    return {
        'id': '', 'code': code, 'name': name or code, 'day': day, 'start': start, 'duration': duration,
        'room': squash(cell(cells, mp.get('room'))), 'seat': squash(cell(cells, mp.get('seat'))), 'type': squash(typ),
        'resit': resit, 'tbc': tbc, 'note': squash(notes), 'line': line,
    }


RE_LINE_DURATION = re.compile(r'(?:^|[^0-9a-z])(\(?[0-9]+(?:\.[0-9]+)? ?(?:h|hr|hrs|hours?)\.?(?: ?[0-9]+ ?(?:m|min|mins|minutes?))?\)?|\(?[0-9]+ ?(?:min|mins|minutes)\)?)(?![a-z])', AI)


def read_exam_lines(text, out, ref):
    out['format'] = 'lines'
    lines = split_lines(text)
    seen = {}
    for i, l in enumerate(lines):
        raw, line = squash(l), i + 1
        if not raw:
            continue
        code = find_code(raw)
        date = find_date(raw, 'DMY', ref)
        if not code and not date:
            if not out['exams']:
                continue
            out['messages'].append({'level': 'info', 'line': line, 'text': 'Line %d was not read: no module code or date in "%s".' % (line, raw[:60])})
            continue
        out['rows'] += 1
        if not code:
            out['skipped'] += 1
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d has a date but no module code, so it was skipped.' % line})
            continue
        rest = raw[:code['index']] + ' ' + raw[code['index'] + code['length']:]
        tbc, day = False, None
        if date:
            day = date['day']
            di = rest.lower().find(raw.lower()[date['index']:date['index'] + date['length']])
            if di >= 0:
                rest = rest[:di] + ' ' + rest[di + date['length']:]
        else:
            tbc = True
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: %s has no date yet. It is listed but not planned until you add a date.' % (line, code['code'])})
        times = find_times(rest)
        start = times[0]['min'] if times else 570
        end = times[1]['min'] if len(times) > 1 else None
        k = len(times) - 1
        while k >= 0 and k >= len(times) - 2:
            rest = rest[:times[k]['index']] + ' ' + rest[times[k]['index'] + times[k]['length']:]
            k -= 1
        duration = None
        dm = RE_LINE_DURATION.search(rest)
        if dm:
            duration = parse_duration(re.sub(r'[()]', '', dm.group(1)), '')
            rest = rest.replace(dm.group(1), ' ', 1)
        if duration is None and end is not None and end > start:
            duration = end - start
        if duration is None:
            duration = 120
        name = re.sub(r'\b(tbc|tba|to be confirmed)\b', ' ', rest, flags=AI)
        name = re.sub(r'[\-\u2013|,;:]+( |$)', ' ', name)
        name = re.sub(r'[()]', ' ', name)
        name = trim(squash(name))
        resit = bool(re.search(r'\b(resit|re-sit|referral|reassessment)\b', raw, AI))
        ex = {'id': '', 'code': code['code'], 'name': name or code['code'], 'day': day, 'start': start, 'duration': clamp(duration, 15, 1440),
              'room': '', 'seat': '', 'type': 'Resit' if resit else '', 'resit': resit, 'tbc': tbc, 'note': '', 'line': line}
        key = '%s|%s|%s' % (ex['code'], 'tbc' if day is None else day, start)
        if key in seen:
            out['skipped'] += 1
            continue
        seen[key] = True
        out['exams'].append(ex)
    if not out['exams']:
        out['messages'].append({'level': 'error', 'text': 'No exams found. Paste the timetable with its header row (module, date, time), or use the template.'})
    else:
        out['messages'].append({'level': 'info', 'text': 'No header row was found, so each line was read by looking for a module code, a date and times.'})
    finish_exams(out)
    return out


EXAMISH = re.compile(r'\b(exam|examination|test|paper|assessment|quiz|viva|in-class|mcq)\b', AI)


def read_exams_ics(text, out):
    out['format'] = 'ics'
    cal = parse_ics(text)
    evs = []
    any_exam = any(EXAMISH.search(e['summary'] + ' ' + e['description'] + ' ' + e['categories']) for e in cal['events'])
    dropped = 0
    for e in cal['events']:
        if e['status'] == 'CANCELLED' or not e['start']:
            continue
        if any_exam and not EXAMISH.search(e['summary'] + ' ' + e['description'] + ' ' + e['categories']):
            dropped += 1
            continue
        evs.append(e)
    if dropped:
        out['messages'].append({'level': 'info', 'text': plural(dropped, 'event') + ' that did not mention an exam (lectures, seminars and so on) were left out. Load them under Your time instead.'})
    for e in evs:
        out['rows'] += 1
        f = find_code(e['summary']) or find_code(e['description'])
        code = f['code'] if f else slugify(e['summary']).upper().replace('-', '')[:10]
        name = strip_code(e['summary'], code) if (f and find_code(e['summary'])) else squash(e['summary'])
        name = trim(re.sub(r'[\-:\u2013 ]+$', '', re.sub(r'\b(examination|exam)\b\s*$', '', name, count=1, flags=AI), count=1)) or code
        dur = 120
        if e['end']:
            dur = (e['end']['day'] - e['start']['day']) * 1440 + e['end']['min'] - e['start']['min']
        elif e['durationMin'] is not None:
            dur = e['durationMin']
        if e['start']['allDay']:
            out['messages'].append({'level': 'info', 'text': '%s on %s is an all-day entry, so 09:30 is assumed for the start.' % (code, fmt_short(e['start']['day']))})
        resit = bool(re.search(r'\b(resit|re-sit|referral|reassessment)\b', e['summary'] + ' ' + e['description'], AI))
        out['exams'].append({
            'id': '', 'code': code, 'name': name, 'day': e['start']['day'], 'start': 570 if e['start']['allDay'] else e['start']['min'],
            'duration': clamp(120 if e['start']['allDay'] else dur, 15, 1440), 'room': squash(e['location']), 'seat': '', 'type': 'Resit' if resit else '',
            'resit': resit, 'tbc': False, 'note': '', 'line': e['line'],
        })
    out['messages'].extend(cal['messages'])
    if not out['exams']:
        out['messages'].append({'level': 'error', 'text': 'The calendar had no events that could be read as exams.'})
    finish_exams(out)
    return out


def finish_exams(out):
    out['exams'] = sort_by(out['exams'], exam_order)
    assign_exam_ids(out['exams'])


def exam_order(a, b):
    ad = 10 ** 9 if a['day'] is None else a['day']
    bd = 10 ** 9 if b['day'] is None else b['day']
    return cmp(ad, bd) or cmp(a['start'], b['start']) or cmp(a['code'], b['code']) or cmp(a['name'], b['name'])


def assign_exam_ids(exams):
    used = {}
    for e in exams:
        if e.get('id') and e['id'] not in used:
            used[e['id']] = True
            continue
        base = slugify(e['code'])
        ident, k = base, 2
        while ident in used:
            ident = '%s-%d' % (base, k)
            k += 1
        used[ident] = True
        e['id'] = ident


# ----------------------------------------------------------------------
# Topics
# ----------------------------------------------------------------------

SIZES = {'xs': 60, 's': 120, 'm': 180, 'l': 300, 'xl': 420}
SIZE_WORDS = {
    'xs': 'xs', 'x-small': 'xs', 'tiny': 'xs', 's': 's', 'sm': 's', 'small': 's', 'short': 's', 'light': 's',
    'm': 'm', 'med': 'm', 'medium': 'm', 'mid': 'm', 'average': 'm', 'normal': 'm',
    'l': 'l', 'lg': 'l', 'large': 'l', 'big': 'l', 'long': 'l', 'heavy': 'l',
    'xl': 'xl', 'x-large': 'xl', 'huge': 'xl', 'massive': 'xl', 'very large': 'xl',
}
CONF_WORDS = {
    'red': 1, 'very weak': 1, 'no idea': 1, 'not started': 1, 'weak': 2, 'shaky': 2, 'amber': 3, 'ok': 3, 'okay': 3, 'so-so': 3,
    'fine': 3, 'good': 4, 'strong': 4, 'green': 5, 'very good': 5, 'very strong': 5, 'solid': 5, 'confident': 5,
}


def size_label(minute):
    for k in ['xs', 's', 'm', 'l', 'xl']:
        if SIZES[k] == minute:
            return k.upper()
    return fmt_dur(minute)


def parse_confidence(text):
    s = re.sub(r'^(confidence|conf|rating|rag)[ :=]*', '', lower(trim(text)), count=1, flags=A)
    s = trim(s)
    if not s:
        return None
    m = re.match(r'^([1-5])(?:\.0)?(?: ?/ ?5| out of 5| of 5)?$', s, A)
    if m:
        return int(m.group(1))
    if re.match(r'^[\u2605*]{1,5}[\u2606]*$', s):
        return len(s.replace('\u2606', ''))
    m = re.match(r'^([0-9]{1,3}) ?%$', s, A)
    if m:
        p = clamp(int(m.group(1)), 0, 100)
        return 1 if p <= 20 else 2 if p <= 40 else 3 if p <= 60 else 4 if p <= 80 else 5
    if s in CONF_WORDS:
        return CONF_WORDS[s]
    return None


def parse_size(text, bare_is_hours=False):
    s = re.sub(r'^(size|effort|workload|hours|time)[ :=]*', '', lower(trim(text)), count=1, flags=A)
    s = trim(s)
    if not s:
        return None
    if s in SIZE_WORDS:
        return SIZES[SIZE_WORDS[s]]
    m = re.match(r'^([0-9]+(?:\.[0-9]+)?) ?(?:h|hr|hrs|hour|hours)$', s, A)
    if m:
        return clamp(scale_decimal(m.group(1), 60), 15, 6000)
    m = re.match(r'^([0-9]+) ?(?:m|min|mins|minutes)$', s, A)
    if m:
        return clamp(int(m.group(1)), 15, 6000)
    m = re.match(r'^([0-9]+(?:\.[0-9]+)?)$', s, A)
    if m and bare_is_hours:
        return clamp(scale_decimal(m.group(1), 60), 15, 6000)
    return None


STRICT_ATTR = re.compile(r'^([0-9]+(?:\.[0-9]+)? ?(?:h|hr|hrs|hours|m|min|mins)|[1-5] ?/ ?5|[\u2605*]{1,5}[\u2606]*|[0-9]{1,3}%)$', A)
RE_TAIL_PAREN = re.compile(r'\(([^()]*)\)$')
RE_TAIL_SQUARE = re.compile(r'\[([^\[\]]*)\]$')
RE_TAIL_CURLY = re.compile(r'\{([^{}]*)\}$')
RE_TAIL_SEP = re.compile(r'(?:^|[ ])(?:[\-\u2013|,;:]|--) *([^\-\u2013|,;:]*)$')
RE_TAIL_WORD = re.compile(r' ([^ ]+)$')


def split_topic_attrs(text):
    s = trim(text)
    state = {'conf': None, 'size': None}

    def try_attrs(seg):
        joined = trim(seg)
        if not joined:
            return None
        whole = parse_confidence(joined)
        if whole is not None and state['conf'] is None:
            return {'conf': whole, 'size': None}
        wsize = parse_size(joined, False)
        if wsize is not None and state['size'] is None:
            return {'conf': None, 'size': wsize}
        parts = re.split(r'[,;/|]+| (?=[^ ])', joined)
        c = z = None
        ok = 0
        for p in parts:
            p = trim(p)
            if not p:
                continue
            pc, ps = parse_confidence(p), parse_size(p, False)
            if pc is not None and c is None and state['conf'] is None:
                c = pc
                ok += 1
                continue
            if ps is not None and z is None and state['size'] is None:
                z = ps
                ok += 1
                continue
            return None
        return {'conf': c, 'size': z} if ok else None

    changed = True
    while changed and s:
        changed = False
        m = RE_TAIL_PAREN.search(s) or RE_TAIL_SQUARE.search(s) or RE_TAIL_CURLY.search(s)
        seg, cut_at = None, -1
        if m:
            seg, cut_at = m.group(1), m.start()
        else:
            m2 = RE_TAIL_SEP.search(s)
            if m2:
                seg, cut_at = m2.group(1), m2.start()
            else:
                m3 = RE_TAIL_WORD.search(s)
                if m3 and STRICT_ATTR.match(lower(m3.group(1))):
                    seg, cut_at = m3.group(1), m3.start()
        if seg is None:
            break
        got = try_attrs(seg)
        if not got:
            break
        if got['conf'] is not None:
            state['conf'] = got['conf']
        if got['size'] is not None:
            state['size'] = got['size']
        s = trim(s[:cut_at])
        changed = True
    s = trim(re.sub(r'[\-\u2013|,;:]+$', '', s))
    return {'name': s, 'conf': state['conf'], 'size': state['size']}


TOPIC_SYNONYMS = {
    'code': ['module code', 'module', 'code', 'course', 'course code', 'unit', 'unit code', 'subject', 'paper', 'exam', 'module title', 'module name'],
    'name': ['topic', 'topics', 'topic name', 'title', 'name', 'area', 'chapter', 'lecture', 'week', 'content', 'subtopic', 'sub topic', 'theme', 'section', 'item', 'what'],
    'conf': ['confidence', 'conf', 'how confident', 'rating', 'confidence 1 5', 'confidence 1 to 5', 'rag', 'feel', 'feeling', 'score', 'self rating', 'how well i know it', 'knowledge'],
    'size': ['size', 'hours', 'effort', 'weight', 'estimate', 'length', 'time needed', 'workload', 'how big', 'hours needed', 'time', 'study hours', 'est hours'],
    'mode': ['plan', 'mode', 'status', 'include'],
    'notes': ['notes', 'note', 'comments', 'comment'],
}
TOPIC_KEYWORDS = [('code', 'module'), ('code', 'code'), ('name', 'topic'), ('conf', 'confidence'), ('conf', 'confident'), ('size', 'size'), ('size', 'hours'), ('notes', 'notes')]

RE_BULLET = re.compile(r'^[ \t]*(?:[\-*\u2022\u00b7\u25aa\u25e6>+]|[0-9]{1,2}[.)]|[a-z][.)]|\[[ x]?\]|\u2610|\u2611)[ \t]+', AI)


def strip_bullet(s):
    return trim(RE_BULLET.sub('', s, count=1))


def match_module(text, exams):
    f = find_code(text) or find_code(str(text).upper())
    if f:
        return f['code']
    t = norm_header(text)
    if not t:
        return None
    best = None
    for e in exams:
        n = norm_header(e['name'])
        if not n:
            continue
        if t == n or (' ' + n + ' ') in (' ' + t + ' ') or (len(t) >= 6 and (' ' + t + ' ') in (' ' + n + ' ')):
            if best is None:
                best = e['code']
    return best


def read_topics(text, exams=None, code=''):
    exams = exams or []
    text = '' if text is None else str(text)
    out = {'topics': [], 'messages': [], 'format': '', 'rows': 0, 'skipped': 0}
    if re.match(r'^\s*%PDF', text, A):
        out['messages'].append({'level': 'error', 'text': 'This is a PDF file. Copy the list of topics out of it and paste it here instead.'})
        return out
    if looks_binary(text):
        out['messages'].append({'level': 'error', 'text': BINARY_MESSAGE})
        return out
    if trim(text) == '':
        out['messages'].append({'level': 'error', 'text': 'There was nothing to read.'})
        return out
    table = {'delim': 'html', 'rows': html_rows(text)} if is_html_table(text) else read_table(text)
    header_at, mp = -1, None
    if table['delim'] and table['delim'] != '  ':
        for i in range(min(len(table['rows']), 20)):
            cand = map_columns(table['rows'][i]['cells'], TOPIC_SYNONYMS, TOPIC_KEYWORDS)
            if 'name' in cand and len(cand) >= 2:
                header_at, mp = i, cand
                break
    counts = {'noConf': 0, 'noSize': 0}

    def add(code_, name, conf, size, mode, line, note):
        out['rows'] += 1
        if not name:
            out['skipped'] += 1
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d has no topic name, so it was skipped.' % line})
            return
        if not code_:
            out['skipped'] += 1
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d ("%s") is not under a module, so it was skipped. Put the module code before it or on a heading line.' % (line, name[:40])})
            return
        if conf is None:
            counts['noConf'] += 1
            conf = 3
        if size is None:
            counts['noSize'] += 1
            size = SIZES['m']
        out['topics'].append({'id': '', 'code': code_, 'name': name, 'conf': conf, 'size': size, 'mode': mode or 'full', 'note': note or '', 'line': line})

    if header_at >= 0:
        out['format'] = 'html' if table['delim'] == 'html' else 'csv'
        for r in range(header_at + 1, len(table['rows'])):
            cells, line = table['rows'][r]['cells'], table['rows'][r]['line']
            if is_blank_row(cells):
                continue
            hm = map_columns(cells, TOPIC_SYNONYMS, [])
            if 'name' in hm and len(hm) >= 2:
                out['messages'].append({'level': 'info', 'line': line, 'text': 'Line %d repeats the header row, so it was skipped.' % line})
                continue
            code_txt = cell(cells, mp.get('code'))
            code_ = (match_module(code_txt, exams) or norm_code(code_txt)) if code_txt else code
            raw_name = cell(cells, mp.get('name'))
            conf_txt, size_txt = cell(cells, mp.get('conf')), cell(cells, mp.get('size'))
            conf = parse_confidence(conf_txt) if conf_txt else None
            size = parse_size(size_txt, True) if size_txt else None
            if conf_txt and conf is None:
                out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the confidence "%s", so 3 is used. Use 1 (weak) to 5 (strong).' % (line, conf_txt)})
            if size_txt and size is None:
                out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the size "%s", so M is used. Use S, M, L or hours such as 3h.' % (line, size_txt)})
            name = raw_name
            if conf is None and size is None and raw_name:
                sp = split_topic_attrs(raw_name)
                if sp['conf'] is not None or sp['size'] is not None:
                    name, conf, size = sp['name'], sp['conf'], sp['size']
            mode_txt = lower(cell(cells, mp.get('mode')))
            if re.match(r'^(drop|dropped|skip|no|exclude|excluded)$', mode_txt, A):
                mode = 'drop'
            elif re.match(r'^(quick|skim|light|review only)$', mode_txt, A):
                mode = 'quick'
            else:
                mode = 'full'
            add(code_, squash(name), conf, size, mode, line, squash(cell(cells, mp.get('notes'))))
    else:
        out['format'] = 'list'
        lines = split_lines(text)
        current = code
        for k, l in enumerate(lines):
            raw, ln = squash(l), k + 1
            if not raw:
                continue
            bullet = strip_bullet(raw) != raw
            body = strip_bullet(raw)
            is_heading = False
            if not bullet:
                if re.match(r'^#+ ', body) or body.endswith(':'):
                    is_heading = True
                elif not re.search(r'[,;\t]', l):
                    sp2 = split_topic_attrs(body)
                    if sp2['conf'] is None and sp2['size'] is None:
                        cf = find_code(body)
                        next_bullet = False
                        for nb in range(k + 1, len(lines)):
                            nl = squash(lines[nb])
                            if not nl:
                                continue
                            next_bullet = strip_bullet(nl) != nl
                            break
                        if cf and cf['index'] == 0:
                            rest = trim(strip_code(body, cf['code']))
                            ex = None
                            for e in exams:
                                if e['code'] == cf['code']:
                                    ex = e
                                    break
                            is_heading = (not rest) or (ex is not None and norm_header(rest) == norm_header(ex['name'])) or next_bullet
                        elif not cf:
                            exact = any(norm_header(e['name']) == norm_header(body) for e in exams)
                            is_heading = exact or next_bullet
            if is_heading:
                htxt = trim(re.sub(r':$', '', re.sub(r'^#+ ', '', body, count=1), count=1))
                hc = find_code(htxt)
                matched = match_module(htxt, exams)
                current = matched or (hc['code'] if hc else norm_code(htxt))
                if not matched and not hc:
                    out['messages'].append({'level': 'warn', 'line': ln, 'text': 'Line %d: the heading "%s" has no module code and does not match an exam title, so its topics are filed under %s.' % (ln, htxt[:40], current)})
                continue
            code2 = current
            cells2 = parse_delimited(body, sniff_delimiter(body))[0]['cells'] if re.search(r'[,;\t]', body) else None
            conf2 = size2 = None
            if cells2 and len(cells2) >= 2:
                first = trim(cells2[0])
                fc = find_code(first)
                idx = 0
                if fc and trim(strip_code(first, fc['code'])) == '':
                    code2 = fc['code']
                    idx = 1
                name2 = trim(cells2[idx] if idx < len(cells2) else '')
                extras = []
                for q in range(idx + 1, len(cells2)):
                    tok = trim(cells2[q])
                    if not tok:
                        continue
                    pc, ps = parse_confidence(tok), parse_size(tok, conf2 is not None)
                    if pc is not None and conf2 is None:
                        conf2 = pc
                    elif ps is not None and size2 is None:
                        size2 = ps
                    else:
                        extras.append(tok)
                if extras and conf2 is None and size2 is None:
                    name2 = trim(', '.join(cells2[idx:]))
                if conf2 is None and size2 is None:
                    sp3 = split_topic_attrs(name2)
                    name2, conf2, size2 = sp3['name'], sp3['conf'], sp3['size']
            else:
                fc2 = find_code(body)
                b2 = body
                if fc2 and fc2['index'] == 0:
                    code2 = fc2['code']
                    b2 = trim(re.sub(r'^[ \t]*[\-:\u2013|.]+[ \t]*', '', body[fc2['length']:], count=1))
                sp4 = split_topic_attrs(b2)
                name2, conf2, size2 = sp4['name'], sp4['conf'], sp4['size']
            add(code2, squash(name2), conf2, size2, 'full', ln, '')
    seen, kept = {}, []
    for t in out['topics']:
        key = t['code'] + '|' + lower(t['name'])
        if key in seen:
            out['skipped'] += 1
            out['messages'].append({'level': 'info', 'line': t['line'], 'text': 'Line %d repeats "%s" for %s, so it was skipped.' % (t['line'], t['name'], t['code'])})
            continue
        seen[key] = True
        kept.append(t)
    out['topics'] = kept
    if counts['noConf']:
        out['messages'].append({'level': 'info', 'text': plural(counts['noConf'], 'topic') + ' had no confidence rating, so 3 (so-so) was used. Change it in the table.'})
    if counts['noSize']:
        out['messages'].append({'level': 'info', 'text': plural(counts['noSize'], 'topic') + ' had no size, so M (3 hours of first learning at confidence 3) was used.'})
    if exams:
        known = {e['code']: True for e in exams}
        orphan = {}
        for t in out['topics']:
            if t['code'] not in known:
                orphan[t['code']] = orphan.get(t['code'], 0) + 1
        for c in sort_by(list(orphan.keys()), cmp):
            out['messages'].append({'level': 'warn', 'text': '%s for %s, which is not in your exam timetable: kept, but not planned until an exam for %s is added.' % (plural(orphan[c], 'topic'), c, c)})
    if not out['topics'] and not any(m['level'] == 'error' for m in out['messages']):
        out['messages'].append({'level': 'error', 'text': 'No topics found. Use one line per topic under a module heading, or the CSV template (Module, Topic, Confidence, Size).'})
    return out


def assign_topic_ids(topics):
    used = {}
    for t in topics:
        if t.get('id') and t['id'] not in used:
            used[t['id']] = True
            continue
        base = slugify(t['code'] + '-' + t['name'])
        ident, k = base, 2
        while ident in used:
            ident = '%s-%d' % (base, k)
            k += 1
        used[ident] = True
        t['id'] = ident


# ----------------------------------------------------------------------
# Calendars (.ics)
# ----------------------------------------------------------------------

def ics_unescape(s):
    return re.sub(r'\\([nN,;\\])', lambda m: '\n' if m.group(1) in 'nN' else m.group(1), str(s))


def parse_ics_line(line):
    q, colon = False, -1
    for i, c in enumerate(line):
        if c == '"':
            q = not q
        elif c == ':' and not q:
            colon = i
            break
    if colon < 0:
        return None
    head, value = line[:colon], line[colon + 1:]
    parts = head.split(';')
    params = {}
    for part in parts[1:]:
        eq = part.find('=')
        if eq > 0:
            params[part[:eq].upper()] = re.sub(r'^"|"$', '', part[eq + 1:])
    return {'name': parts[0].upper(), 'params': params, 'value': value}


LONDONISH = ['europe/london', 'gmt standard time', 'gmt', 'europe/belfast', 'gb', 'europe/guernsey', 'europe/jersey', 'europe/isle_of_man', 'greenwich standard time']


def ics_time(value, params, zones):
    v = trim(value)
    m = re.match(r'^([0-9]{4})([0-9]{2})([0-9]{2})$', v, A)
    if m or (params.get('VALUE') and params['VALUE'].upper() == 'DATE'):
        if not m:
            m = re.match(r'^([0-9]{4})([0-9]{2})([0-9]{2})', v, A)
        if not m:
            return None
        dd = make_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None if dd is None else {'day': dd, 'min': 0, 'allDay': True}
    m = re.match(r'^([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})?(Z?)$', v, AI)
    if not m:
        return None
    day = make_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if day is None:
        return None
    minute = int(m.group(4)) * 60 + int(m.group(5))
    tz = lower(params['TZID']) if params.get('TZID') else ''
    if m.group(7) or tz in ('utc', 'etc/utc', 'z'):
        t = utc_to_london(day, minute)
        return {'day': t[0], 'min': t[1], 'allDay': False}
    if tz and tz not in LONDONISH and zones is not None:
        zones[params['TZID']] = True
    return {'day': day, 'min': minute, 'allDay': False}


def ics_duration(value):
    m = re.match(r'^([+\-])?P(?:([0-9]+)W)?(?:([0-9]+)D)?(?:T(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?)?$', trim(value), AI)
    if not m:
        return None
    mins = (int(m.group(2)) * 7 * 1440 if m.group(2) else 0) + (int(m.group(3)) * 1440 if m.group(3) else 0) + \
        (int(m.group(4)) * 60 if m.group(4) else 0) + (int(m.group(5)) if m.group(5) else 0)
    return -mins if m.group(1) == '-' else mins


def parse_ics(text):
    out = {'events': [], 'messages': []}
    raw = strip_bom(str(text))
    raw = re.sub(r'\r\n[ \t]', '', raw)
    raw = re.sub(r'\n[ \t]', '', raw)
    raw = re.sub(r'\r[ \t]', '', raw)
    lines = re.split(r'\r\n|\n|\r', raw)
    ev, depth, zones, bad = None, 0, {}, 0
    for i, l in enumerate(lines):
        if not trim(l):
            continue
        up = l.upper()
        if up == 'BEGIN:VEVENT':
            ev = {'summary': '', 'description': '', 'location': '', 'categories': '', 'status': '', 'transp': '', 'uid': '', 'start': None, 'end': None,
                  'durationMin': None, 'rrule': None, 'exdates': [], 'recurrenceId': None, 'line': i + 1}
            depth = 0
            continue
        if ev is None:
            continue
        if up.startswith('BEGIN:'):
            depth += 1
            continue
        if up.startswith('END:') and up != 'END:VEVENT':
            depth -= 1
            continue
        if up == 'END:VEVENT':
            if ev['start']:
                out['events'].append(ev)
            else:
                bad += 1
            ev = None
            continue
        if depth > 0:
            continue
        p = parse_ics_line(l)
        if not p:
            continue
        name, params, value = p['name'], p['params'], p['value']
        if name == 'SUMMARY':
            ev['summary'] = squash(ics_unescape(value))
        elif name == 'DESCRIPTION':
            ev['description'] = ics_unescape(value)
        elif name == 'LOCATION':
            ev['location'] = squash(ics_unescape(value))
        elif name == 'CATEGORIES':
            ev['categories'] = ics_unescape(value)
        elif name == 'STATUS':
            ev['status'] = trim(value).upper()
        elif name == 'TRANSP':
            ev['transp'] = trim(value).upper()
        elif name == 'UID':
            ev['uid'] = trim(value)
        elif name == 'DTSTART':
            ev['start'] = ics_time(value, params, zones)
        elif name == 'DTEND':
            ev['end'] = ics_time(value, params, zones)
        elif name == 'DURATION':
            ev['durationMin'] = ics_duration(value)
        elif name == 'RRULE':
            ev['rrule'] = parse_rrule(value, zones)
        elif name == 'EXDATE':
            for v in value.split(','):
                t = ics_time(v, params, zones)
                if t:
                    ev['exdates'].append(t)
        elif name == 'RECURRENCE-ID':
            ev['recurrenceId'] = ics_time(value, params, zones)
    if bad:
        out['messages'].append({'level': 'warn', 'text': plural(bad, 'event') + ' had no readable start time and were skipped.'})
    zn = sort_by(list(zones.keys()), cmp)
    if zn:
        out['messages'].append({'level': 'info', 'text': 'Times in ' + ', '.join(zn) + ' were read as UK clock times.'})
    return out


def parse_rrule(value, zones):
    r = {'freq': '', 'interval': 1, 'count': None, 'until': None, 'byday': [], 'bymonthday': None}
    for part in value.split(';'):
        eq = part.find('=')
        if eq < 0:
            continue
        k, v = part[:eq].upper(), part[eq + 1:]
        if k == 'FREQ':
            r['freq'] = v.upper()
        elif k == 'INTERVAL':
            r['interval'] = max(1, _js_int(v) or 1)
        elif k == 'COUNT':
            r['count'] = max(0, _js_int(v) or 0)
        elif k == 'UNTIL':
            r['until'] = ics_time(v, {}, zones)
        elif k == 'BYDAY':
            for d in v.split(','):
                mm = re.search(r'([+\-]?[0-9]*)(MO|TU|WE|TH|FR|SA|SU)$', trim(d), AI)
                if mm:
                    r['byday'].append(['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'].index(mm.group(2).upper()))
        elif k == 'BYMONTHDAY':
            r['bymonthday'] = _js_int(v) or None
    r['byday'].sort()
    return r


def _js_int(v):
    """parseInt: the leading integer of a string, or None."""
    m = re.match(r'^[ \t]*([+\-]?[0-9]+)', str(v), A)
    return int(m.group(1)) if m else None


def occurrence_days(ev, last_day, messages):
    r, start, out = ev['rrule'], ev['start']['day'], []
    if not r or not r['freq']:
        return [start]
    until_day = r['until']['day'] if r['until'] else None
    limit = 3000
    state = {'n': 0}

    def take(d):
        if until_day is not None and d > until_day:
            return False
        if r['count'] is not None and state['n'] >= r['count']:
            return False
        state['n'] += 1
        if d <= last_day:
            out.append(d)
        return d <= last_day

    if r['freq'] == 'DAILY':
        for k in range(limit):
            if not take(start + k * r['interval']):
                break
    elif r['freq'] == 'WEEKLY':
        days = r['byday'] if r['byday'] else [weekday(start)]
        week_start = start - weekday(start)
        go = True
        w = 0
        while w < limit and go:
            for wd in days:
                d = week_start + w * 7 * r['interval'] + wd
                if d < start:
                    continue
                if not take(d):
                    go = False
                    break
            w += 1
    elif r['freq'] == 'MONTHLY':
        t = ymd_from_day(start)
        dom = r['bymonthday'] or t[2]
        for mo in range(limit):
            total = t[1] - 1 + mo * r['interval']
            y, mth = t[0] + total // 12, total % 12 + 1
            dd = make_day(y, mth, dom)
            if dd is None:
                continue
            if dd < start:
                continue
            if not take(dd):
                break
    elif r['freq'] == 'YEARLY':
        ty = ymd_from_day(start)
        for yy in range(200):
            d3 = make_day(ty[0] + yy * r['interval'], ty[1], ty[2])
            if d3 is None:
                continue
            if not take(d3):
                break
    else:
        messages.append({'level': 'info', 'text': '"%s" repeats in a way this tool does not follow (%s), so only its first time was used.' % (ev['summary'] or 'An event', r['freq'])})
        return [start]
    return out


def read_calendar(text, from_day, to_day):
    cal = parse_ics(text)
    out = {'busy': [], 'allDay': [], 'messages': list(cal['messages']), 'events': 0, 'skipped': 0}
    if not re.search(r'BEGIN:VCALENDAR', str(text), AI):
        out['messages'].insert(0, {'level': 'error', 'text': 'This is not a calendar (.ics) file. Export your timetable or calendar as .ics (iCalendar) and load that.'})
        return out
    moved = {}
    for e in cal['events']:
        if e['recurrenceId'] and e['uid']:
            moved['%s|%d|%d' % (e['uid'], e['recurrenceId']['day'], 0 if e['recurrenceId']['allDay'] else e['recurrenceId']['min'])] = True
    cancelled = free = 0
    all_day_events = []
    for e in cal['events']:
        if e['status'] == 'CANCELLED':
            cancelled += 1
            continue
        if e['transp'] == 'TRANSPARENT':
            free += 1
            continue
        out['events'] += 1
        label = e['summary'] or 'Busy'
        if e['end']:
            length = (e['end']['day'] - e['start']['day']) * 1440 + (e['end']['min'] - e['start']['min'])
        elif e['durationMin'] is not None:
            length = e['durationMin']
        else:
            length = 1440 if e['start']['allDay'] else 60
        if length <= 0:
            length = 1440 if e['start']['allDay'] else 60
        days = [e['start']['day']] if e['recurrenceId'] else occurrence_days(e, to_day, out['messages'])
        for d in days:
            if not e['recurrenceId'] and e['uid'] and ('%s|%d|%d' % (e['uid'], d, 0 if e['start']['allDay'] else e['start']['min'])) in moved:
                continue
            skip = False
            for xd in e['exdates']:
                if xd['day'] == d and (xd['allDay'] or e['start']['allDay'] or xd['min'] == e['start']['min']):
                    skip = True
                    break
            if skip:
                continue
            if e['start']['allDay']:
                if label not in all_day_events:
                    all_day_events.append(label)
                n = max(1, (length + 1439) // 1440)
                for k in range(n):
                    if from_day <= d + k <= to_day:
                        out['allDay'].append({'day': d + k, 'label': label})
                continue
            t0 = d * 1440 + e['start']['min']
            t1 = t0 + length
            while t0 < t1:
                dd = t0 // 1440
                day_end = (dd + 1) * 1440
                piece = min(t1, day_end)
                if from_day <= dd <= to_day:
                    out['busy'].append({'day': dd, 'start': t0 - dd * 1440, 'end': piece - dd * 1440, 'label': label})
                t0 = piece
    out['busy'] = sort_by(out['busy'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['start'], b['start']) or cmp(a['end'], b['end']) or cmp(a['label'], b['label']))
    out['allDay'] = sort_by(out['allDay'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['label'], b['label']))
    if cancelled:
        out['messages'].append({'level': 'info', 'text': plural(cancelled, 'cancelled event') + ' left out.'})
    if free:
        out['messages'].append({'level': 'info', 'text': plural(free, 'event') + ' marked as free (not busy) left out.'})
    if out['allDay']:
        out['messages'].append({'level': 'info', 'text': plural(len(all_day_events), 'all-day entry', 'all-day entries') + ' (' + ', '.join(all_day_events[:3]) + (' and others' if len(all_day_events) > 3 else '') + ') ' + ('was' if len(all_day_events) == 1 else 'were') + ' not counted as busy. Block a day by hand if one means you cannot revise.'})
    if not out['events'] and not cal['messages']:
        out['messages'].append({'level': 'warn', 'text': 'The calendar had no events.'})
    return out


def busy_summary(busy):
    by, order = {}, []
    for b in busy:
        if b['label'] not in by:
            by[b['label']] = {'label': b['label'], 'count': 0, 'minutes': 0, 'first': b['day'], 'last': b['day']}
            order.append(b['label'])
        s = by[b['label']]
        s['count'] += 1
        s['minutes'] += b['end'] - b['start']
        if b['day'] > s['last']:
            s['last'] = b['day']
    return sort_by([by[k] for k in order], lambda a, b: cmp(b['minutes'], a['minutes']) or cmp(a['label'], b['label']))


BUSY_SYNONYMS = {
    'date': ['date', 'day', 'shift date', 'when', 'start date', 'date of shift', 'work date'],
    'start': ['start', 'start time', 'from', 'begins', 'time in', 'clock in', 'shift start', 'starts', 'time'],
    'end': ['end', 'end time', 'to', 'finish', 'finish time', 'until', 'time out', 'clock out', 'shift end', 'ends'],
    'duration': ['hours', 'duration', 'length', 'shift length', 'mins', 'minutes'],
    'label': ['role', 'shift', 'what', 'event', 'activity', 'description', 'title', 'subject', 'type', 'summary', 'location', 'site', 'job', 'name'],
}


def read_busy_table(text, from_day, to_day):
    """Busy times from a rota or spreadsheet: a date, a start and an end (or a length) on each row."""
    out = {'busy': [], 'allDay': [], 'messages': [], 'events': 0, 'skipped': 0}
    text = '' if text is None else str(text)
    if looks_binary(text):
        out['messages'].append({'level': 'error', 'text': BINARY_MESSAGE})
        return out
    table = {'delim': 'html', 'rows': html_rows(text)} if is_html_table(text) else read_table(text)
    header_at, mp = -1, None
    for i in range(min(len(table['rows']), 20)):
        cand = map_columns(table['rows'][i]['cells'], BUSY_SYNONYMS, [])
        if 'date' in cand and 'start' in cand and ('end' in cand or 'duration' in cand):
            header_at, mp = i, cand
            break
    if header_at < 0:
        out['messages'].append({'level': 'error', 'text': 'No header row with a date, a start and an end (or a length) was found. Export your rota with those columns, or load a calendar (.ics) instead.'})
        return out
    hcells = table['rows'][header_at]['cells']
    unit = duration_unit(hcells[mp['duration']]) if 'duration' in mp and mp['duration'] < len(hcells) else ''
    order_info = date_order_of([cell(r['cells'], mp.get('date')) for r in table['rows'][header_at + 1:]])
    for r in range(header_at + 1, len(table['rows'])):
        cells, line = table['rows'][r]['cells'], table['rows'][r]['line']
        if is_blank_row(cells):
            continue
        date_txt, start_txt, end_txt, dur_txt = cell(cells, mp.get('date')), cell(cells, mp.get('start')), cell(cells, mp.get('end')), cell(cells, mp.get('duration'))
        hm = map_columns(cells, BUSY_SYNONYMS, [])
        if 'date' in hm and 'start' in hm:
            continue
        day = parse_date(date_txt, order_info['order'], from_day)
        if day is None:
            out['skipped'] += 1
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the date "%s", so the row was skipped.' % (line, date_txt)})
            continue
        start = parse_clock(start_txt)
        if start is None:
            out['skipped'] += 1
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: no start time ("%s"), so the row was skipped.' % (line, start_txt)})
            continue
        length = None
        if end_txt:
            end = parse_clock(end_txt)
            if end is not None:
                length = end - start if end > start else end + 1440 - start
        if length is None and dur_txt:
            length = parse_duration(dur_txt, unit)
        if length is None or length <= 0:
            out['skipped'] += 1
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: no end time or length, so the row was skipped.' % line})
            continue
        out['events'] += 1
        label = squash(cell(cells, mp.get('label'))) or 'Busy'
        t0 = day * 1440 + start
        t1 = t0 + min(length, 2880)
        while t0 < t1:
            dd = t0 // 1440
            piece = min(t1, (dd + 1) * 1440)
            if from_day <= dd <= to_day:
                out['busy'].append({'day': dd, 'start': t0 - dd * 1440, 'end': piece - dd * 1440, 'label': label})
            t0 = piece
    out['busy'] = sort_by(out['busy'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['start'], b['start']) or cmp(a['end'], b['end']) or cmp(a['label'], b['label']))
    date_order_messages(order_info, out)
    if not out['events']:
        out['messages'].append({'level': 'error', 'text': 'No busy times could be read from this file.'})
    return out


def read_busy(text, from_day, to_day):
    """Busy times from either a calendar file or a rota table."""
    return read_calendar(text, from_day, to_day) if re.search(r'BEGIN:VCALENDAR', str(text), AI) else read_busy_table(text, from_day, to_day)


def import_summary(kind, res):
    """One line describing what an import read, kept with the project."""
    if kind == 'exams':
        dated = sum(1 for e in res['exams'] if e['day'] is not None)
        n = len(res['exams'])
        return plural(n, 'exam') + (' (%d without a date)' % (n - dated) if n > dated else '') + (', ' + plural(res['skipped'], 'row') + ' skipped' if res['skipped'] else '')
    if kind == 'topics':
        mods = {t['code'] for t in res['topics']}
        return plural(len(res['topics']), 'topic') + ' in ' + plural(len(mods), 'module') + (', ' + plural(res['skipped'], 'line') + ' skipped' if res['skipped'] else '')
    if kind == 'calendar':
        return plural(len(res['busy']), 'busy time') + ' from ' + plural(res['events'], 'event') + (', all-day entries on ' + plural(len(res['allDay']), 'day') + ' not counted' if res['allDay'] else '')
    if kind == 'availability':
        return plural(res['weekRows'], 'weekday row') + ' and ' + plural(len(res['overrides']), 'dated change')
    return ''


# ----------------------------------------------------------------------
# Projects: settings, availability and defaults
# ----------------------------------------------------------------------

DEFAULT_SETTINGS = {
    'learnMin': 50, 'reviewMin': 25, 'breakMin': 10, 'taperDays': 3, 'papers': 2, 'maxShare': 50,
    'reviewShare': 40, 'busyGap': 15, 'examGap': 45, 'examDay': 'after', 'paperMax': 180,
}
REVIEW_GAPS = [1, 3, 7, 14, 28]
CONF_PCT = [150, 125, 100, 75, 50]


def default_week():
    w = []
    for i in range(7):
        if i < 5:
            w.append({'from': 540, 'to': 1200, 'minutes': 300})
        elif i == 5:
            w.append({'from': 600, 'to': 1080, 'minutes': 240})
        else:
            w.append({'from': 660, 'to': 1080, 'minutes': 240})
    return w


def new_project(today):
    return {
        'app': 'exam-season', 'version': VERSION, 'name': 'My revision plan', 'student': '',
        'settings': copy_settings(DEFAULT_SETTINGS), 'exams': [], 'topics': [], 'week': default_week(),
        'overrides': [], 'busy': [], 'allDay': [], 'sources': [],
        'planFrom': today, 'planFromMin': 0, 'asOf': None, 'done': [], 'settled': [], 'missed': [],
    }


def copy_settings(s):
    return {k: (DEFAULT_SETTINGS[k] if s.get(k) is None else s[k]) for k in DEFAULT_SETTINGS}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float('inf'), float('-inf'))


def int_or(v, d):
    if _is_number(v):
        return int(v // 1)
    if isinstance(v, str) and re.match(r'^-?[0-9]+$', trim(v), A):
        return int(trim(v))
    return d


def str_or(v, d):
    return v if isinstance(v, str) else d


def day_or(v, d):
    if _is_number(v):
        return int(v // 1)
    if isinstance(v, str):
        x = from_iso(v)
        if x is not None:
            return x
    return d


def clean_settings(s):
    s = s if isinstance(s, dict) else {}
    o = copy_settings({})
    o['learnMin'] = clamp(int_or(s.get('learnMin'), o['learnMin']), 15, 180)
    o['reviewMin'] = clamp(int_or(s.get('reviewMin'), o['reviewMin']), 10, o['learnMin'])
    o['breakMin'] = clamp(int_or(s.get('breakMin'), o['breakMin']), 0, 60)
    o['taperDays'] = clamp(int_or(s.get('taperDays'), o['taperDays']), 1, 10)
    o['papers'] = clamp(int_or(s.get('papers'), o['papers']), 0, 6)
    o['maxShare'] = clamp(int_or(s.get('maxShare'), o['maxShare']), 25, 100)
    o['reviewShare'] = clamp(int_or(s.get('reviewShare'), o['reviewShare']), 10, 100)
    o['busyGap'] = clamp(int_or(s.get('busyGap'), o['busyGap']), 0, 120)
    o['examGap'] = clamp(int_or(s.get('examGap'), o['examGap']), 0, 180)
    o['examDay'] = s.get('examDay') if s.get('examDay') in ('after', 'off', 'normal') else o['examDay']
    o['paperMax'] = clamp(int_or(s.get('paperMax'), o['paperMax']), 30, 300)
    return o


def _dict(v):
    return v if isinstance(v, dict) else None


def clean_project(p, today):
    p = p if isinstance(p, dict) else {}
    base = new_project(today)
    as_of = p.get('asOf')
    o = {
        'app': 'exam-season', 'version': VERSION,
        'name': str_or(p.get('name'), base['name']), 'student': str_or(p.get('student'), ''),
        'settings': clean_settings(p.get('settings')),
        'exams': [], 'topics': [], 'week': [], 'overrides': [], 'busy': [], 'allDay': [], 'sources': [],
        'planFrom': day_or(p.get('planFrom'), today), 'planFromMin': clamp(int_or(p.get('planFromMin'), 0), 0, 1439),
        'asOf': None if as_of is None else day_or(as_of, None),
        'done': [], 'settled': [], 'missed': [],
    }
    for e in (p.get('exams') if isinstance(p.get('exams'), list) else []):
        if not _dict(e):
            continue
        code = norm_code(str_or(e.get('code'), ''))
        if not code:
            continue
        day = None if e.get('day') is None else day_or(e.get('day'), None)
        o['exams'].append({
            'id': str_or(e.get('id'), ''), 'code': code, 'name': squash(str_or(e.get('name'), code)) or code, 'day': day,
            'start': clamp(int_or(e.get('start'), 570), 0, 1439), 'duration': clamp(int_or(e.get('duration'), 120), 15, 1440),
            'room': squash(str_or(e.get('room'), '')), 'seat': squash(str_or(e.get('seat'), '')), 'type': squash(str_or(e.get('type'), '')),
            'resit': e.get('resit') is True, 'tbc': day is None, 'note': squash(str_or(e.get('note'), '')),
        })
    o['exams'] = sort_by(o['exams'], exam_order)
    assign_exam_ids(o['exams'])
    for t in (p.get('topics') if isinstance(p.get('topics'), list) else []):
        if not _dict(t):
            continue
        name = squash(str_or(t.get('name'), ''))
        code = norm_code(str_or(t.get('code'), ''))
        if not name or not code:
            continue
        o['topics'].append({
            'id': str_or(t.get('id'), ''), 'code': code, 'name': name, 'conf': clamp(int_or(t.get('conf'), 3), 1, 5),
            'size': clamp(int_or(t.get('size'), 180), 15, 6000), 'mode': t.get('mode') if t.get('mode') in ('full', 'quick', 'drop') else 'full',
            'note': squash(str_or(t.get('note'), '')),
        })
    assign_topic_ids(o['topics'])
    wk = p.get('week') if isinstance(p.get('week'), list) and len(p.get('week')) == 7 else base['week']
    for i in range(7):
        w = wk[i] if _dict(wk[i]) else base['week'][i]
        frm = clamp(int_or(w.get('from'), base['week'][i]['from']), 0, 1440)
        to = clamp(int_or(w.get('to'), base['week'][i]['to']), 0, 1440)
        if to < frm:
            to = frm
        o['week'].append({'from': frm, 'to': to, 'minutes': clamp(int_or(w.get('minutes'), 0), 0, to - frm)})
    for v in (p.get('overrides') if isinstance(p.get('overrides'), list) else []):
        if not _dict(v):
            continue
        day = day_or(v.get('day'), None)
        if day is None:
            continue
        ov = {'day': day, 'minutes': clamp(int_or(v.get('minutes'), 0), 0, 1440), 'label': squash(str_or(v.get('label'), ''))}
        if v.get('from') is not None:
            ov['from'] = clamp(int_or(v.get('from'), 0), 0, 1440)
        if v.get('to') is not None:
            ov['to'] = clamp(int_or(v.get('to'), 1440), 0, 1440)
        o['overrides'].append(ov)
    o['overrides'] = sort_by(o['overrides'], lambda a, b: cmp(a['day'], b['day']))
    dedup = []
    for v in o['overrides']:
        if dedup and dedup[-1]['day'] == v['day']:
            dedup[-1] = v
        else:
            dedup.append(v)
    o['overrides'] = dedup
    for b in (p.get('busy') if isinstance(p.get('busy'), list) else []):
        if not _dict(b):
            continue
        day = day_or(b.get('day'), None)
        if day is None:
            continue
        s, e = clamp(int_or(b.get('start'), 0), 0, 1440), clamp(int_or(b.get('end'), 0), 0, 1440)
        if e <= s:
            continue
        o['busy'].append({'day': day, 'start': s, 'end': e, 'label': squash(str_or(b.get('label'), 'Busy')) or 'Busy'})
    o['busy'] = sort_by(o['busy'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['start'], b['start']) or cmp(a['end'], b['end']) or cmp(a['label'], b['label']))
    for b in (p.get('allDay') if isinstance(p.get('allDay'), list) else []):
        if not _dict(b):
            continue
        day = day_or(b.get('day'), None)
        if day is not None:
            o['allDay'].append({'day': day, 'label': squash(str_or(b.get('label'), ''))})
    for s in (p.get('sources') if isinstance(p.get('sources'), list) else []):
        if not _dict(s):
            continue
        o['sources'].append({'kind': str_or(s.get('kind'), ''), 'name': str_or(s.get('name'), ''), 'summary': str_or(s.get('summary'), '')})
    seen_done = {}
    for d in (p.get('done') if isinstance(p.get('done'), list) else []):
        if not _dict(d) or not isinstance(d.get('id'), str) or d['id'] in seen_done:
            continue
        day = day_or(d.get('day'), None)
        if day is None:
            continue
        seen_done[d['id']] = True
        o['done'].append({'id': d['id'], 'day': day, 'min': clamp(int_or(d.get('min'), 0), 0, 1440), 'exam': str_or(d.get('exam'), ''), 'code': str_or(d.get('code'), ''), 'title': str_or(d.get('title'), ''),
                          'rating': clamp(int_or(d.get('rating'), 0), 0, 3)})
    o['done'] = sort_by(o['done'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['id'], b['id']))
    for ident in (p.get('settled') if isinstance(p.get('settled'), list) else []):
        if isinstance(ident, str) and ident in seen_done and ident not in o['settled']:
            o['settled'].append(ident)
    o['settled'] = sort_by(o['settled'], cmp)
    for d in (p.get('missed') if isinstance(p.get('missed'), list) else []):
        if not _dict(d) or not isinstance(d.get('id'), str):
            continue
        day = day_or(d.get('day'), None)
        if day is None:
            continue
        o['missed'].append({'id': d['id'], 'day': day, 'min': clamp(int_or(d.get('min'), 0), 0, 1440), 'exam': str_or(d.get('exam'), ''), 'code': str_or(d.get('code'), ''), 'title': str_or(d.get('title'), '')})
    o['missed'] = sort_by(o['missed'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['id'], b['id']))
    return o


# ----------------------------------------------------------------------
# Availability files: a weekly template plus dated changes
# ----------------------------------------------------------------------

_ALL = [0, 1, 2, 3, 4, 5, 6]
DAY_WORDS = {
    'mo': [0], 'mon': [0], 'monday': [0], 'mondays': [0], 'tu': [1], 'tue': [1], 'tues': [1], 'tuesday': [1], 'tuesdays': [1],
    'we': [2], 'wed': [2], 'weds': [2], 'wednesday': [2], 'wednesdays': [2], 'th': [3], 'thu': [3], 'thur': [3], 'thurs': [3], 'thursday': [3], 'thursdays': [3],
    'fr': [4], 'fri': [4], 'friday': [4], 'fridays': [4], 'sa': [5], 'sat': [5], 'saturday': [5], 'saturdays': [5], 'su': [6], 'sun': [6], 'sunday': [6], 'sundays': [6],
    'weekdays': [0, 1, 2, 3, 4], 'weekday': [0, 1, 2, 3, 4], 'mon-fri': [0, 1, 2, 3, 4], 'weekends': [5, 6], 'weekend': [5, 6], 'sat-sun': [5, 6],
    'daily': _ALL, 'every day': _ALL, 'everyday': _ALL, 'all': _ALL,
}


def parse_clock(text):
    s = lower(trim(text))
    if not s:
        return None
    if s in ('24:00', 'midnight'):
        return 1440
    m = re.match(r'^([0-9]{1,2})$', s, A)
    if m:
        h = int(m.group(1))
        return h * 60 if h <= 24 else None
    m2 = re.match(r'^([0-9]{1,2})[:.]([0-9]{2})$', s, A)
    if m2:
        hh, mm = int(m2.group(1)), int(m2.group(2))
        return hh * 60 + mm if hh <= 23 and mm <= 59 else None
    return parse_time(s)


def parse_hours(text):
    s = lower(trim(text))
    if not s:
        return None
    if re.match(r'^(off|none|no|blocked|busy|away|holiday|x|-+)$', s, A):
        return 0
    m = re.match(r'^([0-9]+(?:\.[0-9]+)?) ?(?:h|hr|hrs|hour|hours)?$', s, A)
    if m:
        return scale_decimal(m.group(1), 60)
    m = re.match(r'^([0-9]+) ?(?:m|min|mins|minutes)$', s, A)
    if m:
        return int(m.group(1))
    m = re.match(r'^([0-9]{1,2}):([0-9]{2})$', s, A)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


AVAIL_SYNONYMS = {
    'day': ['day', 'date', 'days', 'when', 'weekday', 'day or date'],
    'from': ['from', 'start', 'start time', 'earliest', 'begin', 'available from'],
    'to': ['to', 'end', 'end time', 'latest', 'until', 'finish', 'available until'],
    'hours': ['hours', 'hours to revise', 'revision hours', 'max hours', 'study hours', 'hrs', 'time', 'minutes'],
    'note': ['note', 'notes', 'why', 'reason', 'label', 'comment'],
}


def read_availability(text, base=None):
    out = {'week': [{'from': w['from'], 'to': w['to'], 'minutes': w['minutes']} for w in (base or default_week())],
           'overrides': [], 'messages': [], 'rows': 0, 'weekRows': 0}
    if looks_binary(text):
        out['messages'].append({'level': 'error', 'text': BINARY_MESSAGE})
        return out
    table = read_table(text)
    header_at, mp = -1, None
    for i in range(min(len(table['rows']), 10)):
        cand = map_columns(table['rows'][i]['cells'], AVAIL_SYNONYMS, [])
        if 'day' in cand and len(cand) >= 2:
            header_at, mp = i, cand
            break
    if header_at < 0:
        out['messages'].append({'level': 'error', 'text': 'No header row found. Use the columns Day, From, To, Hours (and Note): one row per weekday, plus a row for each date that is different.'})
        return out
    hcells = table['rows'][header_at]['cells']
    hours_hdr = hcells[mp['hours']] if 'hours' in mp and mp['hours'] < len(hcells) else ''
    hours_are_min = 'min' in norm_header(hours_hdr)
    for r in range(header_at + 1, len(table['rows'])):
        cells, line = table['rows'][r]['cells'], table['rows'][r]['line']
        if is_blank_row(cells):
            continue
        out['rows'] += 1
        day_txt, from_txt, to_txt = cell(cells, mp.get('day')), cell(cells, mp.get('from')), cell(cells, mp.get('to'))
        hours_txt, note = cell(cells, mp.get('hours')), squash(cell(cells, mp.get('note')))
        frm = parse_clock(from_txt) if from_txt else None
        to = parse_clock(to_txt) if to_txt else None
        if from_txt and frm is None:
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the time "%s".' % (line, from_txt)})
        if to_txt and to is None:
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the time "%s".' % (line, to_txt)})
        if hours_txt:
            minutes = int(trim(hours_txt)) if (hours_are_min and re.match(r'^[0-9]+$', trim(hours_txt), A)) else parse_hours(hours_txt)
        else:
            minutes = None
        if hours_txt and minutes is None:
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: could not read the hours "%s", so the row was skipped.' % (line, hours_txt)})
            continue
        key = lower(squash(day_txt))
        if key in DAY_WORDS:
            out['weekRows'] += 1
            for wd in DAY_WORDS[key]:
                w = out['week'][wd]
                if frm is not None:
                    w['from'] = min(frm, 1440)
                if to is not None:
                    w['to'] = min(to, 1440)
                if w['to'] < w['from']:
                    w['to'] = w['from']
                if minutes is not None:
                    w['minutes'] = minutes
                elif frm is not None or to is not None:
                    w['minutes'] = w['to'] - w['from']
                if w['minutes'] > w['to'] - w['from']:
                    w['minutes'] = w['to'] - w['from']
            continue
        rng = re.split(r' +(?:-|\u2013|to|until) +|\u2013', day_txt)
        d1 = parse_date(rng[0], 'DMY', None)
        d2 = parse_date(rng[1], 'DMY', None) if len(rng) > 1 else d1
        if d1 is None or d2 is None:
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: "%s" is not a weekday or a date, so the row was skipped.' % (line, day_txt)})
            continue
        if d2 < d1:
            d1, d2 = d2, d1
        if d2 - d1 > 366:
            out['messages'].append({'level': 'warn', 'line': line, 'text': 'Line %d: the date range is longer than a year, so it was skipped.' % line})
            continue
        if minutes is None:
            minutes = max(0, to - frm) if (frm is not None and to is not None) else 0
        for d in range(d1, d2 + 1):
            ov = {'day': d, 'minutes': minutes, 'label': note}
            if frm is not None:
                ov['from'] = frm
            if to is not None:
                ov['to'] = to
            out['overrides'].append(ov)
    out['overrides'] = sort_by(out['overrides'], lambda a, b: cmp(a['day'], b['day']))
    return out


def availability_csv(project):
    rows = [['Day', 'From', 'To', 'Hours', 'Note']]
    for i, w in enumerate(project['week']):
        rows.append([WD3[i], fmt_time(w['from']), fmt_time(w['to']), tenths(w['minutes']), ''])
    for v in project['overrides']:
        t = ymd_from_day(v['day'])
        rows.append(['%02d/%02d/%d' % (t[2], t[1], t[0]), '' if v.get('from') is None else fmt_time(v['from']),
                     '' if v.get('to') is None else fmt_time(v['to']), tenths(v['minutes']), v['label']])
    return csv_text(rows)


def day_window(project, day):
    w = project['week'][weekday(day)]
    o = {'from': w['from'], 'to': w['to'], 'cap': w['minutes'], 'blocked': w['minutes'] <= 0, 'label': ''}
    for v in project['overrides']:
        if v['day'] != day:
            continue
        if v.get('from') is not None:
            o['from'] = v['from']
        if v.get('to') is not None:
            o['to'] = v['to']
        o['cap'] = v['minutes']
        o['blocked'] = v['minutes'] <= 0
        o['label'] = v['label']
    if o['to'] < o['from']:
        o['to'] = o['from']
    return o


def cut(ivs, a, b):
    out = []
    for x in ivs:
        if b <= x[0] or a >= x[1]:
            out.append([x[0], x[1]])
            continue
        if a > x[0]:
            out.append([x[0], a])
        if b < x[1]:
            out.append([b, x[1]])
    return out


def round_up5(m):
    return (m + 4) // 5 * 5


def day_free(project, day, exams_by_day, busy_by_day, s):
    w = day_window(project, day)
    ivs = [] if w['blocked'] else [[w['from'], w['to']]]
    cap = 0 if w['blocked'] else w['cap']
    for b in busy_by_day.get(day, []):
        ivs = cut(ivs, b['start'] - s['busyGap'], b['end'] + s['busyGap'])
    exs = exams_by_day.get(day, [])
    if exs:
        first_start, last_end = 1440, 0
        for e in exs:
            ivs = cut(ivs, e['start'] - s['examGap'], e['start'] + e['duration'] + s['examGap'])
            if e['start'] < first_start:
                first_start = e['start']
            if e['start'] + e['duration'] > last_end:
                last_end = e['start'] + e['duration']
        if s['examDay'] == 'off':
            ivs, cap = [], 0
        elif s['examDay'] == 'after':
            ivs = cut(ivs, 0, last_end + s['examGap'])
            cap = cap // 2
    clean, total = [], 0
    for iv in ivs:
        a, b = round_up5(iv[0]), iv[1]
        if b - a >= 10:
            clean.append([a, b])
            total += b - a
    return {'window': w, 'intervals': clean, 'cap': min(cap, total), 'blocked': w['blocked'], 'label': w['label']}


# ----------------------------------------------------------------------
# The planner
# ----------------------------------------------------------------------

def learn_sessions(t, s):
    if t['mode'] == 'quick':
        return 1
    pct = CONF_PCT[clamp(t['conf'], 1, 5) - 1]
    return max(1, ceil_div(t['size'] * pct, 100 * s['learnMin']))


def learn_length(t, s):
    return s['reviewMin'] if t['mode'] == 'quick' else s['learnMin']


def review_max(t):
    return 1 if t['mode'] == 'quick' else len(REVIEW_GAPS)


def topic_need(t, s):
    return learn_sessions(t, s) * learn_length(t, s) + min(review_max(t), 3) * s['reviewMin'] + s['reviewMin']


def paper_length(e, s):
    return clamp(e['duration'], 30, s['paperMax'])


def topic_priority(a, b):
    return cmp(a['t']['conf'], b['t']['conf']) or cmp(b['t']['size'], a['t']['size']) or cmp(a['order'], b['order'])


def parse_id(ident):
    parts = str(ident).split(':')
    return {'kind': parts[0], 'a': parts[1] if len(parts) > 1 else '', 'b': parts[2] if len(parts) > 2 else ''}


def _int0(text):
    v = _js_int(text)
    return v if v is not None else 0


def build_plan(project):
    """Build the plan. It depends only on the inputs, the day and time it was
    planned from and the sessions already settled when it was planned."""
    s = project['settings']
    frm = project['planFrom']
    notes = []
    settled_set = set(project['settled'])
    history = [d for d in project['done'] if d['id'] in settled_set]

    dated = [e for e in project['exams'] if e['day'] is not None]
    upcoming = [e for e in dated if e['day'] >= frm]
    for e in project['exams']:
        if e['day'] is None:
            notes.append({'level': 'warn', 'exam': e['id'], 'text': '%s %s: date to be confirmed, so it is not planned yet. Add the date when it is published.' % (e['code'], e['name'])})
    for e in dated:
        if e['day'] < frm:
            notes.append({'level': 'info', 'exam': e['id'], 'text': '%s %s was on %s, before this plan starts, so it is not planned.' % (e['code'], e['name'], fmt_short(e['day']))})
    plan = {'from': frm, 'fromMin': project['planFromMin'], 'last': frm, 'settings': s, 'exams': [], 'days': [], 'sessions': [],
            'notes': notes, 'topics': [], 'byExam': {}, 'byId': {}}
    if not upcoming:
        if not project['exams']:
            notes.append({'level': 'info', 'text': 'No exams yet: load your exam timetable to make a plan.'})
        else:
            notes.append({'level': 'warn', 'text': 'None of your exams has a date on or after %s, so there is nothing to plan.' % fmt_short(frm)})
        return plan
    last = upcoming[-1]['day']
    plan['last'] = last
    n_days = last - frm + 1

    target = {}
    exams_by_day = {}
    for i, e in enumerate(upcoming):
        info = {
            'id': e['id'], 'code': e['code'], 'name': e['name'], 'day': e['day'], 'start': e['start'], 'duration': e['duration'],
            'room': e['room'], 'seat': e['seat'], 'resit': e['resit'], 'colour': i % 6, 'learnBy': e['day'] - s['taperDays'] - 1,
            'aimBy': e['day'] - s['taperDays'] - 8, 'taperFrom': e['day'] - s['taperDays'], 'finalDay': None,
            'topicIds': [], 'paperLen': paper_length(e, s), 'second': False,
        }
        if e['code'] in target:
            info['second'] = True
        else:
            target[e['code']] = info
        plan['exams'].append(info)
        plan['byExam'][e['id']] = info
        exams_by_day.setdefault(e['day'], []).append(e)
    dupes = {}
    for e in upcoming:
        dupes[e['code']] = dupes.get(e['code'], 0) + 1
    for c in sort_by(list(dupes.keys()), cmp):
        if dupes[c] > 1:
            notes.append({'level': 'info', 'text': '%s has %d exams. Its topics are learnt for the first one; the later ones get past papers and a final review.' % (c, dupes[c])})
    for di in range(1, len(upcoming)):
        if upcoming[di]['day'] == upcoming[di - 1]['day']:
            notes.append({'level': 'info', 'text': 'Two exams on %s (%s and %s): the day before is shared between them.' % (fmt_short(upcoming[di]['day']), upcoming[di - 1]['code'], upcoming[di]['code'])})

    orphan = {}
    states, st_by_id = [], {}
    order = 0
    for t in project['topics']:
        if t['mode'] == 'drop':
            continue
        ex = target.get(t['code'])
        if not ex:
            orphan[t['code']] = orphan.get(t['code'], 0) + 1
            continue
        st = {'t': t, 'exam': ex, 'order': order, 'len': learn_length(t, s), 'count': learn_sessions(t, s), 'done': 0, 'nextK': 1,
              'learnedDay': None, 'reviews': 0, 'step': 0, 'shaky': 0, 'nextR': 1, 'lastReview': None, 'due': None, 'rmax': review_max(t), 'lastDay': None,
              'planned': 0, 'plannedReviews': 0}
        order += 1
        states.append(st)
        st_by_id[t['id']] = st
        ex['topicIds'].append(t['id'])
    for c in sort_by(list(orphan.keys()), cmp):
        notes.append({'level': 'warn', 'text': '%s for %s %s not planned: there is no upcoming exam for %s.' % (plural(orphan[c], 'topic'), c, 'is' if orphan[c] == 1 else 'are', c)})
    for e in plan['exams']:
        if e['second']:
            e['topicIds'] = list(target[e['code']]['topicIds'])
        if not e['topicIds'] and not e['second']:
            notes.append({'level': 'warn', 'exam': e['id'], 'text': '%s %s has no topics yet, so it only gets past papers and a final review day. Add its topics to plan the revision.' % (e['code'], e['name'])})

    last_learn, used_today, papers_done, finals_done = {}, 0, {}, {}
    for h in sort_by(history, lambda a, b: cmp(a['day'], b['day']) or cmp(a['id'], b['id'])):
        p = parse_id(h['id'])
        if h['day'] == frm:
            used_today += h['min']
        if p['kind'] == 'learn' and p['a'] in st_by_id:
            st = st_by_id[p['a']]
            st['done'] += 1
            st['nextK'] = max(st['nextK'], _int0(p['b']) + 1)
            last_learn[p['a']] = max(h['day'] if p['a'] not in last_learn else last_learn[p['a']], h['day'])
            if h['day'] >= frm:
                st['lastDay'] = h['day']
        elif p['kind'] == 'review' and p['a'] in st_by_id:
            sr = st_by_id[p['a']]
            sr['reviews'] += 1
            # How the review went moves the topic along its ladder of gaps.
            if h.get('rating') == 1:
                sr['step'] = 0
                sr['shaky'] += 1
            else:
                sr['step'] += 2 if h.get('rating') == 3 else 1
            sr['nextR'] = max(sr['nextR'], _int0(p['b']) + 1)
            sr['lastReview'] = h['day'] if sr['lastReview'] is None else max(sr['lastReview'], h['day'])
            if h['day'] >= frm:
                sr['lastDay'] = h['day']
        elif p['kind'] == 'paper':
            pd = papers_done.setdefault(p['a'], {'n': 0, 'next': 1})
            pd['n'] += 1
            pd['next'] = max(pd['next'], _int0(p['b']) + 1)
        elif p['kind'] == 'final':
            finals_done[p['a'] + ':' + p['b']] = True
    for st in states:
        if st['done'] >= st['count']:
            st['learnedDay'] = frm - 1 if st['t']['id'] not in last_learn else last_learn[st['t']['id']]
            prev = st['learnedDay'] if st['reviews'] == 0 else max(st['lastReview'], st['learnedDay'])
            if st['step'] < st['rmax']:
                st['due'] = prev + REVIEW_GAPS[min(st['step'], len(REVIEW_GAPS) - 1)]

    busy_by_day = {}
    for b in project['busy']:
        busy_by_day.setdefault(b['day'], []).append(b)
    days = []
    for i in range(n_days):
        d = frm + i
        f = day_free(project, d, exams_by_day, busy_by_day, s)
        if i == 0 and project['planFromMin'] > 0:
            f['intervals'] = cut(f['intervals'], 0, round_up5(project['planFromMin']))
            tot = sum(iv[1] - iv[0] for iv in f['intervals'])
            f['cap'] = min(f['cap'], tot)
        if i == 0:
            f['cap'] = max(0, f['cap'] - used_today)
        days.append({'day': d, 'cap': f['cap'], 'fullCap': f['cap'], 'intervals': f['intervals'], 'blocked': f['blocked'], 'label': f['label'],
                     'examIds': [e['id'] for e in exams_by_day.get(d, [])], 'reserved': [], 'sessions': [], 'used': 0, 'paper': False})

    for e in plan['exams']:
        for back in range(1, 4):
            d = e['day'] - back
            if d < frm:
                break
            dd = days[d - frm]
            if dd['cap'] <= 0:
                continue
            if any(plan['byExam'][rid]['day'] != e['day'] for rid in dd['reserved']):
                continue
            dd['reserved'].append(e['id'])
            e['finalDay'] = d
            break
        if e['finalDay'] is None and e['day'] > frm:
            notes.append({'level': 'warn', 'exam': e['id'], 'text': 'No free day in the three days before %s (%s) to keep for a final review.' % (e['code'], fmt_short(e['day']))})

    sessions = []

    def add_session(se, day_obj):
        sessions.append(se)
        day_obj['sessions'].append(se)
        day_obj['used'] += se['min']
        plan['byId'][se['id']] = se

    for e in plan['exams']:
        pd = papers_done.get(e['id'], {'n': 0, 'next': 1})
        k = pd['next']
        ln = e['paperLen']
        for _n in range(pd['n'], s['papers']):
            booked = False
            d = e['day'] - 2
            while d >= max(frm, e['day'] - 15):
                dd = days[d - frm]
                if dd['reserved'] or dd['examIds'] or dd['paper'] or dd['cap'] - dd['used'] < ln:
                    d -= 1
                    continue
                for iv in dd['intervals']:
                    if iv[1] - iv[0] >= ln:
                        se = {'id': 'paper:%s:%d' % (e['id'], k), 'kind': 'paper', 'day': d, 'start': iv[0], 'end': iv[0] + ln, 'min': ln,
                              'exam': e['id'], 'code': e['code'], 'topic': '', 'title': 'Past paper %d' % k, 'detail': 'Timed, %s, then mark it' % fmt_dur(ln)}
                        dd['intervals'] = cut(dd['intervals'], iv[0], iv[0] + ln + s['breakMin'])
                        dd['paper'] = True
                        add_session(se, dd)
                        booked = True
                        break
                if booked:
                    break
                d -= 1
            if not booked:
                break
            k += 1
        e['papersPlanned'] = k - pd['next']
        e['papersDone'] = pd['n']

    prefix = [0]
    for pi in range(n_days):
        dp = days[pi]
        prefix.append(prefix[pi] + (0 if dp['reserved'] else max(0, dp['cap'] - dp['used'])))

    def cap_between(a, b):
        if b < a:
            return 0
        return prefix[b + 1] - prefix[a]

    remaining = {e['id']: 0 for e in plan['exams']}
    for st in states:
        if st['done'] < st['count']:
            remaining[st['exam']['id']] += (st['count'] - st['done']) * st['len']

    def fill_day(dd, x):
        d = dd['day']
        if dd['cap'] - dd['used'] < s['reviewMin'] and not dd['reserved']:
            return
        mod_min = {}
        for se in dd['sessions']:
            mod_min[se['code']] = mod_min.get(se['code'], 0) + se['min']
        mod_cap = max(s['learnMin'], dd['cap'] * s['maxShare'] // 100)
        rev_cap = max(s['reviewMin'], dd['cap'] * s['reviewShare'] // 100)
        reserved_exams = [plan['byExam'][i] for i in dd['reserved']]
        final_queues = []
        for e in reserved_exams:
            lst = [st_by_id[i] for i in e['topicIds'] if (e['id'] + ':' + st_by_id[i]['t']['id']) not in finals_done]
            final_queues.append({'exam': e, 'list': sort_by(lst, topic_priority), 'pos': 0})
        state = {'finalTurn': 0, 'reviewUsed': 0, 'lastCode': None, 'capCache': {}}

        def candidates():
            out = []
            if dd['reserved']:
                for q in range(len(final_queues)):
                    fq = final_queues[(state['finalTurn'] + q) % len(final_queues)]
                    if fq['pos'] < len(fq['list']):
                        out.append({'kind': 'final', 'st': fq['list'][fq['pos']], 'exam': fq['exam'], 'code': fq['exam']['code'], 'len': s['reviewMin'], 'rank': q, 'queue': fq})
                return out
            any_learn = False
            for st2 in states:
                e = st2['exam']
                if st2['done'] < st2['count']:
                    if d <= e['learnBy']:
                        any_learn = True
                        out.append({'kind': 'learn', 'st': st2, 'exam': e, 'code': e['code'], 'len': st2['len'], 'today': st2['lastDay'] == d})
                elif st2['due'] is not None and st2['due'] <= d <= e['day'] - 2:
                    out.append({'kind': 'review', 'st': st2, 'exam': e, 'code': e['code'], 'len': s['reviewMin'], 'today': st2['lastDay'] == d})
            if any_learn:
                out = [c for c in out if c['kind'] != 'review' or state['reviewUsed'] + c['len'] <= rev_cap]
            return out

        def kind_rank(c):
            if c['kind'] == 'review':
                return 1 if c['st']['step'] < 3 else 3
            return 0 if d >= c['exam']['learnBy'] - 2 else 2

        def cap_for(e):
            if e['id'] in state['capCache']:
                return state['capCache'][e['id']]
            end = e['aimBy'] - frm
            today = max(0, dd['cap'] - dd['used']) if d <= e['aimBy'] else 0
            c = today + cap_between(x + 1, min(end, n_days - 1))
            state['capCache'][e['id']] = c
            return c

        def better(a, b):
            ra, rb = kind_rank(a), kind_rank(b)
            if ra != rb:
                return ra < rb
            if a['kind'] == 'final':
                return a['rank'] < b['rank'] or (a['rank'] == b['rank'] and topic_priority(a['st'], b['st']) < 0)
            if a['kind'] == 'review' and b['kind'] == 'review':
                c = cmp(a['st']['due'], b['st']['due']) or cmp(a['exam']['day'], b['exam']['day']) or cmp(a['st']['t']['conf'], b['st']['t']['conf']) or cmp(a['st']['order'], b['st']['order'])
                return c < 0
            if a['exam'] is not b['exam']:
                sa = cap_for(a['exam']) - remaining[a['exam']['id']]
                sb = cap_for(b['exam']) - remaining[b['exam']['id']]
                if sa != sb:
                    return sa < sb
                c2 = cmp(a['exam']['day'], b['exam']['day']) or cmp(a['code'], b['code'])
                if c2:
                    return c2 < 0
            return topic_priority(a['st'], b['st']) < 0

        def choose(room):
            cands = candidates()
            if not cands:
                return None
            state['capCache'] = {}
            for level in range(4):
                best = None
                for c in cands:
                    if c['len'] > room:
                        continue
                    if level < 1 and c['code'] == state['lastCode']:
                        continue
                    if c['kind'] != 'final':
                        if level < 3 and c['today']:
                            continue
                        if level < 2 and mod_min.get(c['code'], 0) + c['len'] > mod_cap:
                            continue
                    if best is None or better(c, best):
                        best = c
                if best:
                    return best
            return None

        def place(c, start):
            st, e = c['st'], c['exam']
            if c['kind'] == 'learn':
                k = st['nextK']
                if st['t']['mode'] == 'quick':
                    detail = 'Quick look'
                elif st['count'] > 1:
                    detail = 'Learn, part %d of %d' % (st['done'] + 1, st['count'])
                else:
                    detail = 'Learn'
                se = {'id': 'learn:%s:%d' % (st['t']['id'], k), 'kind': 'learn', 'day': d, 'start': start, 'end': start + c['len'], 'min': c['len'],
                      'exam': e['id'], 'code': e['code'], 'topic': st['t']['id'], 'title': st['t']['name'], 'detail': detail}
                st['nextK'] += 1
                st['done'] += 1
                st['planned'] += 1
                remaining[e['id']] -= c['len']
                if st['done'] >= st['count']:
                    st['learnedDay'] = d
                    st['due'] = d + REVIEW_GAPS[min(st['step'], len(REVIEW_GAPS) - 1)] if st['step'] < st['rmax'] else None
            elif c['kind'] == 'review':
                n = st['nextR']
                se = {'id': 'review:%s:%d' % (st['t']['id'], n), 'kind': 'review', 'day': d, 'start': start, 'end': start + c['len'], 'min': c['len'],
                      'exam': e['id'], 'code': e['code'], 'topic': st['t']['id'], 'title': st['t']['name'],
                      'detail': 'Review %d: test yourself, then fill the gaps' % (st['reviews'] + 1)}
                st['nextR'] += 1
                st['reviews'] += 1
                st['step'] += 1
                st['plannedReviews'] += 1
                st['lastReview'] = d
                st['due'] = d + REVIEW_GAPS[min(st['step'], len(REVIEW_GAPS) - 1)] if st['step'] < st['rmax'] else None
                state['reviewUsed'] += c['len']
            else:
                se = {'id': 'final:%s:%s' % (e['id'], st['t']['id']), 'kind': 'final', 'day': d, 'start': start, 'end': start + c['len'], 'min': c['len'],
                      'exam': e['id'], 'code': e['code'], 'topic': st['t']['id'], 'title': st['t']['name'], 'detail': 'Final review before the exam'}
                c['queue']['pos'] += 1
                state['finalTurn'] = (state['finalTurn'] + 1) % len(final_queues)
            st['lastDay'] = d
            mod_min[c['code']] = mod_min.get(c['code'], 0) + c['len']
            state['lastCode'] = c['code']
            add_session(se, dd)

        for v in range(len(dd['intervals'])):
            cur = dd['intervals'][v][0]
            while True:
                cur = round_up5(cur)
                room = min(dd['intervals'][v][1] - cur, dd['cap'] - dd['used'])
                if room < min(s['reviewMin'], s['learnMin']):
                    break
                pick = choose(room)
                if not pick:
                    break
                place(pick, cur)
                cur += pick['len'] + s['breakMin']
            if dd['cap'] - dd['used'] < s['reviewMin']:
                break
        dd['sessions'] = sort_by(dd['sessions'], lambda a, b: cmp(a['start'], b['start']) or cmp(a['id'], b['id']))

    for x in range(n_days):
        fill_day(days[x], x)

    plan['sessions'] = sort_by(sessions, lambda a, b: cmp(a['day'], b['day']) or cmp(a['start'], b['start']) or cmp(a['id'], b['id']))
    plan['days'] = [{'day': dd['day'], 'cap': dd['fullCap'], 'used': dd['used'], 'spare': max(0, dd['cap'] - dd['used']), 'blocked': dd['blocked'],
                     'label': dd['label'], 'examIds': dd['examIds'], 'reserved': dd['reserved'], 'sessionIds': [se['id'] for se in dd['sessions']]}
                    for dd in days]

    for e in plan['exams']:
        sts = [st_by_id[i] for i in e['topicIds']]
        short_topics, short_min, thin, finals_planned = [], 0, [], 0
        need = 0
        if not e['second']:
            for st in sts:
                need += topic_need(st['t'], s)
                if st['done'] < st['count']:
                    short_topics.append(st['t']['id'])
                    short_min += (st['count'] - st['done']) * st['len']
                elif st['reviews'] < min(2, st['rmax']):
                    thin.append(st['t']['id'])
        else:
            need += len(sts) * s['reviewMin']
        for st in sts:
            if ('final:%s:%s' % (e['id'], st['t']['id'])) in plan['byId'] or (e['id'] + ':' + st['t']['id']) in finals_done:
                finals_planned += 1
        need += s['papers'] * e['paperLen']
        e['need'] = need
        e['shortTopics'] = short_topics
        e['shortMin'] = short_min
        e['thinTopics'] = thin
        e['finalsPlanned'] = finals_planned
        e['finalsMissing'] = len(sts) - finals_planned
        e['papersMissing'] = max(0, s['papers'] - e['papersDone'] - e['papersPlanned'])

    plan['topics'] = [{'id': st['t']['id'], 'code': st['t']['code'], 'exam': st['exam']['id'], 'name': st['t']['name'], 'conf': st['t']['conf'],
                       'size': st['t']['size'], 'mode': st['t']['mode'], 'sessions': st['count'], 'length': st['len'],
                       'learnt': st['done'] >= st['count'], 'learnedDay': st['learnedDay'], 'reviews': st['reviews'], 'step': st['step'], 'shaky': st['shaky']} for st in states]
    return plan


# ----------------------------------------------------------------------
# Progress: what is done, what was missed, and are you on track?
# ----------------------------------------------------------------------

def done_map(project):
    return {d['id']: d for d in project['done']}


def status(project, plan, today):
    s = project['settings']
    done = done_map(project)
    out = {'today': today, 'exams': [], 'todaySessions': [], 'missed': [], 'doneMin': 0, 'aheadMin': 0, 'missedMin': 0, 'needMin': 0, 'verdict': 'ok', 'shakyNew': 0}
    settled_set = set(project['settled'])
    for d in project['done']:
        if d.get('rating') == 1 and d['id'] not in settled_set:
            out['shakyNew'] += 1
    by_done, by_ahead, by_missed, by_missed_n = {}, {}, {}, {}
    for d in project['done']:
        by_done[d['exam']] = by_done.get(d['exam'], 0) + d['min']
    for se in plan['sessions']:
        if se['id'] in done:
            continue
        if se['day'] >= today:
            by_ahead[se['exam']] = by_ahead.get(se['exam'], 0) + se['min']
        else:
            by_missed[se['exam']] = by_missed.get(se['exam'], 0) + se['min']
            by_missed_n[se['exam']] = by_missed_n.get(se['exam'], 0) + 1
            out['missed'].append(se)
        if se['day'] == today:
            out['todaySessions'].append(se)
    for se in plan['sessions']:
        if se['id'] in done and se['day'] == today:
            out['todaySessions'].append(se)
    out['todaySessions'] = sort_by(out['todaySessions'], lambda a, b: cmp(a['start'], b['start']) or cmp(a['id'], b['id']))
    topics_by_id = {t['id']: t for t in project['topics']}
    for e in plan['exams']:
        r = {'id': e['id'], 'code': e['code'], 'name': e['name'], 'day': e['day'], 'start': e['start'], 'colour': e['colour'], 'daysLeft': e['day'] - today,
             'need': e['need'], 'done': by_done.get(e['id'], 0), 'ahead': by_ahead.get(e['id'], 0), 'missed': by_missed.get(e['id'], 0),
             'missedCount': by_missed_n.get(e['id'], 0), 'short': 0, 'verdict': 'ok', 'headline': '', 'reasons': [], 'quick': [], 'quickSaves': 0,
             'extraSessions': 0, 'extraDays': 0, 'topics': len(e['topicIds'])}
        if e['day'] < today:
            r['verdict'] = 'sat'
            r['headline'] = 'Exam done'
            out['exams'].append(r)
            continue
        if e['day'] == today:
            r['verdict'] = 'today'
            r['headline'] = 'Exam today'
            r['reasons'].append('Exam at ' + fmt_time(e['start']) + (', ' + e['room'] if e['room'] else '') + '. Good luck.')
            out['exams'].append(r)
            continue
        r['short'] = max(0, r['need'] - r['done'] - r['ahead'])
        if e['shortMin'] > 0:
            r['verdict'] = 'short'
            r['headline'] = 'Not enough time'
            r['reasons'].append('%s of first learning (%s) does not fit before %s, when new topics stop for this exam.' % (fmt_hours(e['shortMin']), plural(len(e['shortTopics']), 'topic'), fmt_short(e['learnBy'])))
            cands = [topics_by_id.get(i) for i in e['topicIds']]
            cands = [t for t in cands if t and t['mode'] == 'full']
            cands = sort_by(cands, lambda a, b: cmp(b['conf'], a['conf']) or cmp(a['size'], b['size']) or cmp(a['name'], b['name']))
            saved = 0
            for t in cands:
                if saved >= e['shortMin']:
                    break
                save = learn_sessions(t, s) * s['learnMin'] - s['reviewMin']
                if save <= 0:
                    continue
                r['quick'].append(t['id'])
                saved += save
            r['quickSaves'] = saved
            free = 0
            for d in range(max(today, plan['from']), e['learnBy'] + 1):
                idx = d - plan['from']
                dd = plan['days'][idx] if 0 <= idx < len(plan['days']) else None
                if dd and not dd['blocked'] and not dd['reserved'] and not dd['examIds']:
                    free += 1
            r['extraDays'] = free
            r['extraSessions'] = ceil_div(e['shortMin'], s['learnMin'])
        if r['missedCount'] > 0:
            if r['verdict'] == 'ok':
                r['verdict'] = 'behind'
                r['headline'] = 'Behind'
            one = r['missedCount'] == 1
            r['reasons'].append('%s (%s) planned before today %s not ticked off. Re-plan from today to fit %s back in.' % (plural(r['missedCount'], 'session'), fmt_hours(r['missed']), 'was' if one else 'were', 'it' if one else 'them'))
        if e['papersMissing'] > 0:
            if r['verdict'] == 'ok':
                r['verdict'] = 'tight'
                r['headline'] = 'Tight'
            r['reasons'].append('%s could not be fitted in the two weeks before the exam (no free stretch of %s).' % (plural(e['papersMissing'], 'past paper'), fmt_dur(e['paperLen'])))
        if e['finalDay'] is None and e['day'] > today:
            if r['verdict'] == 'ok':
                r['verdict'] = 'tight'
                r['headline'] = 'Tight'
            r['reasons'].append('There is no free day just before it for a final review.')
        elif e['finalDay'] is not None and e['finalsMissing'] > 0 and e['topicIds']:
            if r['verdict'] == 'ok':
                r['verdict'] = 'tight'
                r['headline'] = 'Tight'
            r['reasons'].append('%s%s a final review on %s (not enough time that day).' % (plural(e['finalsMissing'], 'topic'), ' misses' if e['finalsMissing'] == 1 else ' miss', fmt_short(e['finalDay'])))
        if e['thinTopics']:
            if r['verdict'] == 'ok':
                r['verdict'] = 'tight'
                r['headline'] = 'Tight'
            n = len(e['thinTopics'])
            r['reasons'].append('%s%s fewer than two spaced reviews before the exam, because %s learnt late.' % (plural(n, 'topic'), ' gets' if n == 1 else ' get', 'it is' if n == 1 else 'they are'))
        if r['verdict'] == 'ok':
            r['headline'] = 'On track'
            if not e['topicIds']:
                r['reasons'].append('No topics listed: only past papers and a final review are planned.')
            else:
                r['reasons'].append('Every topic is learnt by %s, with spaced reviews, %s and a final review on %s.' % (fmt_short(e['learnBy']), plural(s['papers'], 'past paper'), 'the day before' if e['finalDay'] is None else fmt_short(e['finalDay'])))
        out['exams'].append(r)
    rank = {'short': 4, 'behind': 3, 'tight': 2, 'ok': 1, 'today': 0, 'sat': 0}
    for r in out['exams']:
        if r['verdict'] == 'sat':
            continue
        out['needMin'] += r['need']
        out['doneMin'] += r['done']
        out['aheadMin'] += r['ahead']
        out['missedMin'] += r['missed']
        if rank[r['verdict']] > rank[out['verdict']]:
            out['verdict'] = r['verdict']
    return out


def tick(project, plan, ident, today, on=True):
    idx = -1
    for i, d in enumerate(project['done']):
        if d['id'] == ident:
            idx = i
            break
    if on is False:
        if idx >= 0:
            project['done'].pop(idx)
            if ident in project['settled']:
                project['settled'].remove(ident)
        return project
    if idx >= 0:
        return project
    se = plan['byId'].get(ident)
    if not se:
        return project
    project['done'].append({'id': ident, 'day': min(se['day'], today), 'min': se['min'], 'exam': se['exam'], 'code': se['code'], 'title': session_title(se), 'rating': 0})
    project['done'] = sort_by(project['done'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['id'], b['id']))
    return project


def rate(project, plan, ident, today, rating):
    """Say how a review went: 1 shaky, 2 OK, 3 solid (0 clears it). Ticks it off first if needed."""
    entry = next((d for d in project['done'] if d['id'] == ident), None)
    if entry is None:
        tick(project, plan, ident, today, True)
        entry = next((d for d in project['done'] if d['id'] == ident), None)
    if entry is not None:
        entry['rating'] = clamp(rating, 0, 3)
    return project


RATING_WORD = ['', 'shaky', 'OK', 'solid']


def topic_status(project, plan, today):
    """Where each topic stands today: learning, reviews (and how they went), the next session and a one-word state."""
    done = done_map(project)
    by_topic = {}
    for d in project['done']:
        p = parse_id(d['id'])
        tid = p['b'] if p['kind'] == 'final' else p['a']
        if p['kind'] == 'paper':
            continue
        x = by_topic.setdefault(tid, {'learn': 0, 'reviews': [], 'finals': 0, 'last': None})
        if p['kind'] == 'learn':
            x['learn'] += 1
        elif p['kind'] == 'review':
            x['reviews'].append(d.get('rating') or 0)
        else:
            x['finals'] += 1
        if x['last'] is None or d['day'] > x['last']:
            x['last'] = d['day']
    ahead = {}
    for se in plan['sessions']:
        if not se['topic'] or se['id'] in done:
            continue
        a = ahead.setdefault(se['topic'], {'learn': 0, 'reviews': 0, 'finals': 0, 'next': None, 'missed': 0, 'learnMissed': 0})
        if se['day'] < today:
            a['missed'] += 1
            if se['kind'] == 'learn':
                a['learnMissed'] += 1
            continue
        if se['kind'] == 'learn':
            a['learn'] += 1
        elif se['kind'] == 'review':
            a['reviews'] += 1
        elif se['kind'] == 'final':
            a['finals'] += 1
        if a['next'] is None or se['day'] < a['next']['day'] or (se['day'] == a['next']['day'] and se['start'] < a['next']['start']):
            a['next'] = {'day': se['day'], 'start': se['start'], 'kind': se['kind'], 'id': se['id']}
    plan_topic = {t['id']: t for t in plan['topics']}
    out = []
    for t in project['topics']:
        x = by_topic.get(t['id'], {'learn': 0, 'reviews': [], 'finals': 0, 'last': None})
        a = ahead.get(t['id'], {'learn': 0, 'reviews': 0, 'finals': 0, 'next': None, 'missed': 0, 'learnMissed': 0})
        total = 0 if t['mode'] == 'drop' else learn_sessions(t, project['settings'])
        shaky = sum(1 for r in x['reviews'] if r == 1)
        if t['mode'] == 'drop':
            state = 'dropped'
        elif t['id'] not in plan_topic:
            state = 'not planned'
        elif x['finals'] > 0:
            state = 'ready'
        elif x['learn'] == 0:
            state = 'not started'
        elif x['learn'] < total:
            state = 'learning'
        elif not x['reviews']:
            state = 'learnt'
        else:
            state = 'reviewing'
        out.append({'id': t['id'], 'code': t['code'], 'name': t['name'], 'conf': t['conf'], 'mode': t['mode'], 'learnDone': min(x['learn'], total),
                    'learnTotal': total, 'learnAhead': a['learn'], 'learnMissed': a['learnMissed'], 'reviewsDone': len(x['reviews']), 'ratings': x['reviews'], 'reviewsAhead': a['reviews'],
                    'finalAhead': a['finals'], 'finalDone': x['finals'] > 0, 'missed': a['missed'], 'last': x['last'], 'next': a['next'], 'shaky': shaky, 'state': state})
    return out


def replan(project, plan, today, now_min=0):
    done = done_map(project)
    for se in plan['sessions']:
        if se['day'] < today and se['id'] not in done:
            project['missed'].append({'id': se['id'], 'day': se['day'], 'min': se['min'], 'exam': se['exam'], 'code': se['code'], 'title': session_title(se)})
    project['missed'] = sort_by(project['missed'], lambda a, b: cmp(a['day'], b['day']) or cmp(a['id'], b['id']))
    project['settled'] = sort_by([d['id'] for d in project['done']], cmp)
    project['planFrom'] = today
    project['planFromMin'] = now_min or 0
    return project


def set_override(project, day, minutes, label='', frm=None, to=None):
    project['overrides'] = [v for v in project['overrides'] if v['day'] != day]
    ov = {'day': day, 'minutes': minutes, 'label': label or ''}
    if frm is not None:
        ov['from'] = frm
    if to is not None:
        ov['to'] = to
    project['overrides'].append(ov)
    project['overrides'] = sort_by(project['overrides'], lambda a, b: cmp(a['day'], b['day']))
    return project


# ----------------------------------------------------------------------
# Checks that catch slips before they become a bad plan
# ----------------------------------------------------------------------

def check_inputs(project, plan, today):
    out = []
    dated = [e for e in project['exams'] if e['day'] is not None]
    for e in dated:
        what = e['code'] + ' ' + e['name']
        if e['day'] > today + 240:
            out.append({'level': 'warn', 'text': '%s is on %s, more than eight months away. Check the year.' % (what, fmt_day(e['day']))})
        if e['start'] < 420 or e['start'] >= 1260:
            out.append({'level': 'warn', 'text': '%s starts at %s. Check it is not meant to be %s (am and pm are easy to mix up).' % (what, fmt_time(e['start']), fmt_time((e['start'] + 720) % 1440))})
        if 300 < e['duration'] < 1440:
            out.append({'level': 'warn', 'text': '%s lasts %s, which is long for an exam. Check the length.' % (what, fmt_dur(e['duration']))})
        if e['duration'] < 30:
            out.append({'level': 'warn', 'text': '%s lasts only %s, which is short for an exam. Check the length (the timetable may give it in hours).' % (what, fmt_dur(e['duration']))})
    for i in range(len(dated)):
        for j in range(i + 1, len(dated)):
            a, b = dated[i], dated[j]
            if a['day'] != b['day']:
                continue
            if a['start'] < b['start'] + b['duration'] and b['start'] < a['start'] + a['duration']:
                out.append({'level': 'error', 'text': '%s and %s overlap on %s. Ask your exams office about a clash arrangement, then set the times you are given.' % (a['code'], b['code'], fmt_short(a['day']))})
    codes = {}
    for t in project['topics']:
        codes.setdefault(t['code'], []).append(t)
    exam_codes = {}
    for e in plan['exams']:
        if e['second'] or e['code'] in exam_codes:
            continue
        exam_codes[e['code']] = True
        ts = codes.get(e['code'], [])
        if not ts:
            out.append({'level': 'warn', 'text': '%s %s has no topics, so only past papers and a final review are planned for it.' % (e['code'], e['name'])})
        elif len(ts) >= 5 and all(t['conf'] == 3 for t in ts):
            out.append({'level': 'info', 'text': 'Every %s topic is rated 3. Rating the weak ones lower and the strong ones higher puts the time where you need it.' % e['code']})
    for t in project['topics']:
        if t['mode'] != 'drop' and t['size'] > 1200:
            out.append({'level': 'warn', 'text': '"%s" (%s) is sized at %s of first learning. If that is a typo, pick S, M or L.' % (t['name'], t['code'], fmt_hours(t['size']))})
    week = sum(w['minutes'] for w in project['week'])
    for k, w in enumerate(project['week']):
        if w['minutes'] > 600:
            out.append({'level': 'warn', 'text': '%ss are set to %s of revision. More than about ten hours a day rarely sticks.' % (WEEKDAYS[k], fmt_hours(w['minutes']))})
    if week < 300 and plan['exams']:
        out.append({'level': 'warn', 'text': 'Your normal week has only %s of revision. Check the hours under Your time.' % fmt_hours(week)})
    if plan['exams']:
        need = sum(e['need'] for e in plan['exams'])
        cap = sum(d['cap'] for d in plan['days'] if d['day'] >= today)
        done_min = sum(d['min'] for d in project['done'])
        if need - done_min > cap:
            out.append({'level': 'error', 'text': 'The time is not there: the rules ask for %s more, and your week has %s between now and the last exam. See On track for what to drop or shorten.' % (fmt_hours(max(0, need - done_min)), fmt_hours(cap))})
    rank = {'error': 0, 'warn': 1, 'info': 2}
    indexed = sort_by(list(enumerate(out)), lambda x, y: cmp(rank[x[1]['level']], rank[y[1]['level']]) or cmp(x[0], y[0]))
    return [c for _k, c in indexed]


def adherence(project, plan, today):
    """How much of the planned time you actually do, by weekday, from ticks and missed sessions (days before today)."""
    done = done_map(project)
    by_day = {}

    def add(day, minute, is_done):
        if day >= today:
            return
        x = by_day.setdefault(day, {'planned': 0, 'done': 0})
        x['planned'] += minute
        if is_done:
            x['done'] += minute

    for d in project['done']:
        add(d['day'], d['min'], True)
    for d in project['missed']:
        add(d['day'], d['min'], False)
    for se in plan['sessions']:
        if se['id'] not in done:
            add(se['day'], se['min'], False)
    wd = [{'weekday': k, 'days': 0, 'planned': 0, 'done': 0, 'pct': None, 'suggest': None} for k in range(7)]
    for d in sorted(by_day):
        x, w = by_day[d], wd[weekday(d)]
        w['days'] += 1
        w['planned'] += x['planned']
        w['done'] += x['done']
    total_planned = total_done = 0
    for w in wd:
        total_planned += w['planned']
        total_done += w['done']
        if w['planned']:
            w['pct'] = (w['done'] * 100 + w['planned'] // 2) // w['planned']
        tmpl = project['week'][w['weekday']]['minutes']
        if w['days'] >= 2 and w['pct'] is not None and w['pct'] < 70 and tmpl > 0:
            per_day = w['done'] // w['days']
            to = per_day // 30 * 30
            if to < tmpl:
                w['suggest'] = to
    return {'weekdays': wd, 'planned': total_planned, 'done': total_done,
            'pct': (total_done * 100 + total_planned // 2) // total_planned if total_planned else None, 'days': len(by_day)}


# ----------------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------------

KIND_WORD = {'learn': 'Learn', 'review': 'Review', 'paper': 'Past paper', 'final': 'Final review'}


def session_title(se):
    if se['kind'] == 'paper':
        return se['code'] + ' ' + se['title']
    return '%s %s (%s)' % (se['code'], se['title'], se['detail'].lower() if se['kind'] == 'learn' else KIND_WORD[se['kind']].lower())


def sessions_csv(project, plan):
    done = done_map(project)
    rows = [['Date', 'Day', 'Start', 'End', 'Minutes', 'Module', 'Module title', 'Exam date', 'Kind', 'Topic', 'What to do', 'Done', 'Session id']]
    for se in plan['sessions']:
        e = plan['byExam'][se['exam']]
        rows.append([iso_day(se['day']), WD3[weekday(se['day'])], fmt_time(se['start']), fmt_time(se['end']), se['min'], se['code'], e['name'], iso_day(e['day']),
                     KIND_WORD[se['kind']], '' if se['kind'] == 'paper' else se['title'], se['detail'], 'yes' if se['id'] in done else '', se['id']])
    return csv_text(rows)


def status_csv(st):
    rows = [['Module', 'Title', 'Exam date', 'Days left', 'Hours needed', 'Hours done', 'Hours still planned', 'Hours missed', 'Verdict', 'Reasons']]
    for r in st['exams']:
        rows.append([r['code'], r['name'], iso_day(r['day']), r['daysLeft'], tenths(r['need']), tenths(r['done']), tenths(r['ahead']), tenths(r['missed']), r['headline'], ' '.join(r['reasons'])])
    return csv_text(rows)


def tenths(minute):
    t = (minute * 10 + 30) // 60
    return '%d.%d' % (t // 10, t % 10)


def utf8_len(ch):
    c = ord(ch)
    return 1 if c < 0x80 else 2 if c < 0x800 else 3 if c < 0x10000 else 4


def ics_fold(line):
    out, ln = [], 0
    for ch in line:
        n = utf8_len(ch)
        if ln + n > 75:
            out.append('\r\n ')
            ln = 1
        out.append(ch)
        ln += n
    return ''.join(out)


def ics_escape(s):
    s = str(s).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
    return re.sub(r'\r\n|\n|\r', '\\\\n', s)


def ics_stamp(day, minute):
    t = ymd_from_day(day)
    return '%d%02d%02dT%02d%02d00' % (t[0], t[1], t[2], minute // 60, minute % 60)


VTIMEZONE = [
    'BEGIN:VTIMEZONE', 'TZID:Europe/London',
    'BEGIN:DAYLIGHT', 'TZOFFSETFROM:+0000', 'TZOFFSETTO:+0100', 'TZNAME:BST', 'DTSTART:19810329T010000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU', 'END:DAYLIGHT',
    'BEGIN:STANDARD', 'TZOFFSETFROM:+0100', 'TZOFFSETTO:+0000', 'TZNAME:GMT', 'DTSTART:19961027T020000', 'RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU', 'END:STANDARD',
    'END:VTIMEZONE',
]


def sessions_ics(project, plan, from_day=None, to_day=None, name=None, skip_done=False, exams=True, alarm=0):
    from_day = plan['from'] if from_day is None else from_day
    to_day = plan['last'] if to_day is None else to_day
    done = done_map(project)
    stamp = ics_stamp(project['planFrom'], 0) + 'Z'
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Exam season//Revision plan//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             'X-WR-CALNAME:' + ics_escape(name or 'Revision plan'), 'X-WR-TIMEZONE:Europe/London']
    lines.extend(VTIMEZONE)
    for se in plan['sessions']:
        if se['day'] < from_day or se['day'] > to_day:
            continue
        if skip_done and se['id'] in done:
            continue
        e = plan['byExam'][se['exam']]
        lines += ['BEGIN:VEVENT', 'UID:' + se['id'].replace(':', '-') + '@exam-season', 'DTSTAMP:' + stamp,
                  'DTSTART;TZID=Europe/London:' + ics_stamp(se['day'], se['start']), 'DTEND;TZID=Europe/London:' + ics_stamp(se['day'], se['end']),
                  'SUMMARY:' + ics_escape(session_title(se)),
                  'DESCRIPTION:' + ics_escape('%s. %s %s exam: %s at %s.' % (se['detail'], e['code'], e['name'], fmt_day(e['day']), fmt_time(e['start']))),
                  'CATEGORIES:Revision,' + ics_escape(e['code']), 'TRANSP:OPAQUE']
        if alarm:
            lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + ics_escape(session_title(se)), 'TRIGGER:-PT%dM' % alarm, 'END:VALARM']
        lines.append('END:VEVENT')
    if exams is not False:
        for e in plan['exams']:
            if e['day'] < from_day or e['day'] > to_day:
                continue
            end_t = e['start'] + e['duration']
            lines += ['BEGIN:VEVENT', 'UID:exam-' + e['id'] + '@exam-season', 'DTSTAMP:' + stamp,
                      'DTSTART;TZID=Europe/London:' + ics_stamp(e['day'], e['start']),
                      'DTEND;TZID=Europe/London:' + ics_stamp(e['day'] + end_t // 1440, end_t % 1440),
                      'SUMMARY:' + ics_escape('EXAM ' + e['code'] + ' ' + e['name'])]
            if e['room']:
                lines.append('LOCATION:' + ics_escape(e['room']))
            lines += ['DESCRIPTION:' + ics_escape(('Seat ' + e['seat'] + '. ' if e['seat'] else '') + 'Bring your student card. Arrive 30 minutes early.'),
                      'CATEGORIES:Exam', 'BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + ics_escape('Exam tomorrow: ' + e['code'] + ' ' + e['name']),
                      'TRIGGER:-PT18H', 'END:VALARM', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(ics_fold(l) for l in lines) + '\r\n'


def day_text(project, plan, day):
    done = done_map(project)
    lines = [fmt_long(day)]
    idx = day - plan['from']
    dd = plan['days'][idx] if 0 <= idx < len(plan['days']) else None
    lst = [se for se in plan['sessions'] if se['day'] == day]
    for e in plan['exams']:
        if e['day'] == day:
            lines.append('  EXAM %s %s %s%s' % (fmt_time(e['start']), e['code'], e['name'], ', ' + e['room'] if e['room'] else ''))
    if dd and dd['reserved']:
        lines.append('  Kept for %s: final review only.' % ' and '.join(plan['byExam'][i]['code'] for i in dd['reserved']))
    if not lst:
        lines.append('  No revision (%s).' % (dd['label'] or 'day off') if (dd and dd['blocked']) else '  Nothing planned.')
    for se in lst:
        lines.append('  [%s] %s-%s  %s%s' % ('x' if se['id'] in done else ' ', fmt_time(se['start']), fmt_time(se['end']), session_title(se),
                                             ': ' + se['detail'] if se['kind'] in ('review', 'paper') else ''))
    mins = sum(se['min'] for se in lst)
    if lst:
        lines.append('  %s, %s of revision.' % (plural(len(lst), 'session'), fmt_dur(mins)))
    for e in plan['exams']:
        if e['day'] > day:
            lines.append('  %s in %s (%s)' % (e['code'], plural(e['day'] - day, 'day'), fmt_short(e['day'])))
    return '\n'.join(lines) + '\n'


def checklist_markdown(project, plan, from_day=None, to_day=None):
    """The plan as a Markdown checklist, for notes apps that tick boxes."""
    done = done_map(project)
    from_day = plan['from'] if from_day is None else from_day
    to_day = plan['last'] if to_day is None else to_day
    lines = ['# ' + project['name'], '', 'Revision plan from %s to %s.' % (fmt_day(max(from_day, plan['from'])), fmt_day(min(to_day, plan['last'])))]
    for d in range(max(from_day, plan['from']), min(to_day, plan['last']) + 1):
        lst = [se for se in plan['sessions'] if se['day'] == d]
        exams = [e for e in plan['exams'] if e['day'] == d]
        if not lst and not exams:
            continue
        lines += ['', '## ' + fmt_long(d), '']
        for e in exams:
            lines.append('- **Exam** %s %s %s%s' % (fmt_time(e['start']), e['code'], e['name'], ', ' + e['room'] if e['room'] else ''))
        for se in lst:
            lines.append('- [%s] %s-%s %s%s' % ('x' if se['id'] in done else ' ', fmt_time(se['start']), fmt_time(se['end']), session_title(se),
                                               ': ' + se['detail'] if se['kind'] in ('review', 'paper') else ''))
    return '\n'.join(lines) + '\n'


def project_file(project):
    p = project
    o = {
        'app': 'exam-season', 'version': VERSION, 'name': p['name'], 'student': p['student'],
        'planFrom': iso_day(p['planFrom']), 'planFromMin': p['planFromMin'], 'asOf': None if p['asOf'] is None else iso_day(p['asOf']),
        'settings': p['settings'],
        'exams': [{'id': e['id'], 'code': e['code'], 'name': e['name'], 'day': None if e['day'] is None else iso_day(e['day']), 'start': e['start'],
                   'duration': e['duration'], 'room': e['room'], 'seat': e['seat'], 'type': e['type'], 'resit': e['resit'], 'note': e['note']} for e in p['exams']],
        'topics': [{'id': t['id'], 'code': t['code'], 'name': t['name'], 'conf': t['conf'], 'size': t['size'], 'mode': t['mode'], 'note': t['note']} for t in p['topics']],
        'week': [{'from': w['from'], 'to': w['to'], 'minutes': w['minutes']} for w in p['week']],
        'overrides': [],
        'busy': [{'day': iso_day(b['day']), 'start': b['start'], 'end': b['end'], 'label': b['label']} for b in p['busy']],
        'allDay': [{'day': iso_day(b['day']), 'label': b['label']} for b in p['allDay']],
        'sources': p['sources'],
        'done': [{'id': d['id'], 'day': iso_day(d['day']), 'min': d['min'], 'exam': d['exam'], 'code': d['code'], 'title': d['title'], 'rating': d.get('rating') or 0} for d in p['done']],
        'settled': p['settled'],
        'missed': [{'id': d['id'], 'day': iso_day(d['day']), 'min': d['min'], 'exam': d['exam'], 'code': d['code'], 'title': d['title']} for d in p['missed']],
    }
    for v in p['overrides']:
        o2 = {'day': iso_day(v['day']), 'minutes': v['minutes'], 'label': v['label']}
        if v.get('from') is not None:
            o2['from'] = v['from']
        if v.get('to') is not None:
            o2['to'] = v['to']
        o['overrides'].append(o2)
    return json.dumps(o, indent=1, ensure_ascii=False) + '\n'


def read_project(text, today):
    try:
        obj = json.loads(strip_bom(str(text)))
    except ValueError:
        return {'project': None, 'messages': [{'level': 'error', 'text': 'This is not a project file (it is not valid JSON). Choose a file saved from Exam season.'}]}
    if not isinstance(obj, dict) or (obj.get('app') != 'exam-season' and not isinstance(obj.get('exams'), list)):
        return {'project': None, 'messages': [{'level': 'error', 'text': 'This JSON file is not an Exam season project.'}]}
    p = clean_project(obj, today)
    msgs = []
    if _is_number(obj.get('version')) and obj['version'] > VERSION:
        msgs.append({'level': 'warn', 'text': 'This project was saved by a newer version; anything this version does not know about was left out.'})
    return {'project': p, 'messages': msgs}


# ----------------------------------------------------------------------
# Templates
# ----------------------------------------------------------------------

def exam_template():
    return csv_text([
        ['Module code', 'Module title', 'Date', 'Start time', 'Duration', 'Venue', 'Seat', 'Type'],
        ['ABC1234', 'Example module', '11/01/2027', '09:30', '2 hours', 'Main Hall', '101', 'Unseen exam'],
        ['ABC5678', 'Another module', '2027-01-14', '14:00', '90 min', 'Room 2.04', '', 'Resit'],
        ['ABC9012', 'Third module', 'TBC', '', '', '', '', ''],
    ])


def topic_template():
    return csv_text([
        ['Module', 'Topic', 'Confidence', 'Size'],
        ['ABC1234', 'First topic', '2', 'L'],
        ['ABC1234', 'Second topic', '4', 'S'],
        ['ABC5678', 'Another topic', '3', '3h'],
    ])


# ----------------------------------------------------------------------
# Summary numbers for the headline figures
# ----------------------------------------------------------------------

def summary(project, plan, st):
    nxt = None
    for e in plan['exams']:
        if e['day'] >= st['today'] and nxt is None:
            nxt = e
    done = done_map(project)
    today_min = today_done = 0
    for se in st['todaySessions']:
        today_min += se['min']
        if se['id'] in done:
            today_done += se['min']
    planned = learn = review = paper = final = 0
    for se in plan['sessions']:
        planned += se['min']
        if se['kind'] == 'learn':
            learn += se['min']
        elif se['kind'] == 'review':
            review += se['min']
        elif se['kind'] == 'paper':
            paper += se['min']
        else:
            final += se['min']
    cap_min = sum(d['cap'] for d in plan['days'])
    return {
        'next': {'id': nxt['id'], 'code': nxt['code'], 'name': nxt['name'], 'day': nxt['day'], 'daysLeft': nxt['day'] - st['today']} if nxt else None,
        'exams': len(plan['exams']), 'topics': len(plan['topics']), 'sessions': len(plan['sessions']),
        'plannedMin': planned, 'learnMin': learn, 'reviewMin': review, 'paperMin': paper, 'finalMin': final, 'capMin': cap_min,
        'todayMin': today_min, 'todayDone': today_done, 'todayCount': len(st['todaySessions']),
        'doneMin': st['doneMin'], 'needMin': st['needMin'], 'missedMin': st['missedMin'], 'verdict': st['verdict'],
        'days': len(plan['days']), 'studyDays': sum(1 for d in plan['days'] if d['used'] > 0),
    }
