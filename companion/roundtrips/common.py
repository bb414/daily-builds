"""Small helpers shared by the whole package: rounding, dates, numbers and formatting.

Every function here mirrors one in the browser model (src/model.js) so the two
give identical answers. Money is held as whole cents, prices and quantities as
whole millionths, dates as day numbers (days since 1970-01-01) and times as
seconds into the day. Regular expressions use explicit ASCII classes so they
match exactly what the JavaScript ones match.
"""

import math
import re
from functools import cmp_to_key

PRICE_SCALE = 1000000
QTY_SCALE = 1000000
DAY = 86400
VERSION = 1

# The characters JavaScript's \s matches.
WS_BODY = '\t\n\x0b\x0c\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def rx(pattern, flags=0):
    """Compile a pattern with ASCII classes, where \\s stands for JavaScript's whitespace class."""
    out, i, in_class = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == '\\' and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            if nxt == 's':
                out.append(WS_BODY if in_class else '[' + WS_BODY + ']')
            else:
                out.append(ch + nxt)
            i += 2
            continue
        if ch == '[' and not in_class:
            in_class = True
        elif ch == ']' and in_class:
            in_class = False
        out.append(ch)
        i += 1
    return re.compile(''.join(out), flags | re.ASCII)


def cmp(a, b):
    return -1 if a < b else (1 if a > b else 0)


def sort_by(items, compare):
    """A stable sort with a JavaScript-style comparator."""
    return sorted(items, key=cmp_to_key(compare))


def rnd(x):
    """Round half away from zero to a whole number."""
    return -math.floor(-x + 0.5) if x < 0 else math.floor(x + 0.5)


def jsnum(v):
    """A float that holds a whole number as an int, so JSON matches JavaScript's."""
    if isinstance(v, float) and v == v and abs(v) < 2 ** 53 and v == int(v):
        return int(v)
    return v


def s(v):
    return '' if v is None else str(v)


_TRIM_L = rx(r'^[\s\u00a0\ufeff]+')
_TRIM_R = rx(r'[\s\u00a0]+$')


def trim(v):
    return _TRIM_R.sub('', _TRIM_L.sub('', s(v)))


def pad2(n):
    return '0' + str(n) if n < 10 else str(n)


# ---------- dates ----------

def days_from_civil(y, m, d):
    y -= 1 if m <= 2 else 0
    era = math.floor(y / 400)
    yoe = y - era * 400
    mp = (m + 9) % 12
    doy = math.floor((153 * mp + 2) / 5) + d - 1
    doe = yoe * 365 + math.floor(yoe / 4) - math.floor(yoe / 100) + doy
    return era * 146097 + doe - 719468


def civil(z):
    z += 719468
    era = math.floor(z / 146097)
    doe = z - era * 146097
    yoe = math.floor((doe - math.floor(doe / 1460) + math.floor(doe / 36524) - math.floor(doe / 146096)) / 365)
    y = yoe + era * 400
    doy = doe - (365 * yoe + math.floor(yoe / 4) - math.floor(yoe / 100))
    mp = math.floor((5 * doy + 2) / 153)
    d = doy - math.floor((153 * mp + 2) / 5) + 1
    m = mp + 3 if mp < 10 else mp - 9
    return [y + 1 if m <= 2 else y, m, d]


def days_in_month(y, m):
    if m == 2:
        return 29 if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0 else 28
    return 30 if m in (4, 6, 9, 11) else 31


def make_day(y, m, d):
    if not (1900 <= y <= 2200 and 1 <= m <= 12 and 1 <= d <= days_in_month(y, m)):
        return None
    return days_from_civil(y, m, d)


def to_iso(day):
    c = civil(day)
    return '%d-%s-%s' % (c[0], pad2(c[1]), pad2(c[2]))


_ISO = rx(r'^(\d{4})-(\d{2})-(\d{2})$')


def from_iso(text):
    m = _ISO.match(trim(text))
    return make_day(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def weekday(day):
    """0 is Monday."""
    return ((day + 3) % 7 + 7) % 7


def week_start(day):
    return day - weekday(day)


MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
MONTH_FULL = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAY_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def month_index(word):
    w = word.lower()
    if w == 'sept':
        w = 'sep'
    if len(w) < 3:
        return -1
    for i in range(12):
        if w == MONTHS[i] or w == MONTH_FULL[i]:
            return i + 1
    return -1


def full_year(y):
    n = int(y)
    if len(y) == 2:
        return 2000 + n if n < 70 else 1900 + n
    return n


_TIME = rx(r'^(\d{1,2})[:.](\d{2})(?:[:.](\d{2})(?:[.,]\d+)?)?\s*(AM|PM|A\.M\.|P\.M\.)?\s*(?:Z|UTC|GMT|BST|ET|EST|EDT|CT|CST|CDT|[+-]\d{2}:?\d{2})?$')
_TIME_COMPACT = rx(r'^(\d{2})(\d{2})(\d{2})?$')


def parse_time(text):
    """Seconds into the day, or None."""
    t = trim(text).upper()
    if not t:
        return None
    m = _TIME.match(t)
    if not m:
        m = _TIME_COMPACT.match(t)
        if not m:
            return None
        h, mi, se, ap = int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else 0, ''
    else:
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else 0
        ap = m.group(4)[0] if m.group(4) else ''
    if ap:
        if h < 1 or h > 12:
            return None
        if ap == 'P' and h < 12:
            h += 12
        if ap == 'A' and h == 12:
            h = 0
    if h > 23 or mi > 59 or se > 59:
        return None
    return h * 3600 + mi * 60 + se


_SHAPE = rx(r'^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?![\d])')


def date_shape(text):
    m = _SHAPE.match(trim(text))
    return [int(m.group(1)), int(m.group(2))] if m else None


def detect_date_order(values):
    dmy = mdy = False
    for v in values:
        sh = date_shape(v)
        if not sh:
            continue
        if sh[0] > 12 and sh[1] <= 12:
            dmy = True
        if sh[1] > 12 and sh[0] <= 12:
            mdy = True
    if dmy and not mdy:
        return 'DMY'
    if mdy and not dmy:
        return 'MDY'
    return 'MIXED' if dmy and mdy else ''


_WEEKDAY_PREFIX = rx(r'^(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+', re.I)
_D_ISO = rx(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s,;]+(.*))?$', re.S)
_D_COMPACT = rx(r'^(\d{4})(\d{2})(\d{2})(?:[T\s,;]+(.*))?$', re.S)
_D_YMD = rx(r'^(\d{4})[/.](\d{1,2})[/.](\d{1,2})(?:[T\s,;]+(.*))?$', re.S)
_D_NUM = rx(r'^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?:[T\s,;]+(.*))?$', re.S)
_D_DMON = rx(r'^(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})\.?[\s\-,]+(\d{4}|\d{2})(?:[T\s,;]+(.*))?$', re.S)
_D_MOND = rx(r'^([A-Za-z]{3,9})\.?[\s\-]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-]+(\d{4}|\d{2})(?:[T\s,;]+(.*))?$', re.S)


def parse_date_time(text, order):
    """A date with an optional time: {'day', 'sec'} (sec None when no time is given) or None."""
    t = _WEEKDAY_PREFIX.sub('', trim(text), count=1)
    if not t:
        return None
    day, rest = None, ''
    m = _D_ISO.match(t)
    if m:
        day, rest = make_day(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4) or ''
    else:
        m = _D_COMPACT.match(t)
        if m:
            day, rest = make_day(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4) or ''
        else:
            m = _D_YMD.match(t)
            if m:
                day, rest = make_day(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4) or ''
            else:
                m = _D_NUM.match(t)
                if m:
                    a, b, y = int(m.group(1)), int(m.group(2)), full_year(m.group(3))
                    day = make_day(y, a, b) if order == 'MDY' else make_day(y, b, a)
                    rest = m.group(4) or ''
                else:
                    m = _D_DMON.match(t)
                    if m:
                        mi = month_index(m.group(2))
                        day = make_day(full_year(m.group(3)), mi, int(m.group(1))) if mi > 0 else None
                        rest = m.group(4) or ''
                    else:
                        m = _D_MOND.match(t)
                        if m:
                            mj = month_index(m.group(1))
                            day = make_day(full_year(m.group(3)), mj, int(m.group(2))) if mj > 0 else None
                            rest = m.group(4) or ''
    if day is None:
        return None
    rest = trim(rest)
    if not rest:
        return {'day': day, 'sec': None}
    sec = parse_time(rest)
    if sec is None:
        return None
    return {'day': day, 'sec': sec}


# ---------- numbers ----------

_BRACKETS = rx(r'^\(.*\)$', re.S)
_CODE_START = rx(r'^(USD|GBP|EUR|GBX|CHF|JPY|CAD|AUD|HKD|SGD)\s*', re.I)
_CODE_END = rx(r'\s*(USD|GBP|EUR|GBX|CHF|JPY|CAD|AUD|HKD|SGD)$', re.I)
_PENCE = rx(r"^[\d.,\s']+p$", re.I)
_SPACES = rx(r"[\s\u00a0\u202f']")
_THOUSANDS = rx(r'^\d{1,3}(,\d{3})+$')
_DEC_COMMA = rx(r'^\d+,\d{1,2}$')
_NUMBER = rx(r'^(\d*)(?:\.(\d*))?$')
_LEAD_ZEROS = rx(r'^0+(?=\d)')


def read_number(text, decimal_comma=False):
    """A number as text, cleaned of currency signs, thousands separators and brackets.

    Returns {'neg', 'int', 'frac', 'cur', 'pence'} or None.
    """
    t = trim(text)
    if not t:
        return None
    neg, cur, pence = False, '', False
    if _BRACKETS.match(t):
        neg = True
        t = trim(t[1:-1])
    mm = _CODE_START.match(t)
    if mm:
        cur = mm.group(1).upper()
        t = t[len(mm.group(0)):]
    mm = _CODE_END.search(t)
    if mm:
        cur = mm.group(1).upper()
        t = t[:len(t) - len(mm.group(0))]
    t = trim(t)
    for _ in range(2):
        c = t[:1]
        if c in ('-', '\u2212'):
            neg = not neg
            t = trim(t[1:])
        elif c == '+':
            t = trim(t[1:])
        c = t[:1]
        if c == '$':
            cur = cur or 'USD'
            t = trim(t[1:])
        elif c == '£':
            cur = cur or 'GBP'
            t = trim(t[1:])
        elif c == '€':
            cur = cur or 'EUR'
            t = trim(t[1:])
    if t.endswith('-'):
        neg = not neg
        t = trim(t[:-1])
    if _PENCE.match(t):
        pence = True
        t = trim(t[:-1])
    t = _SPACES.sub('', t)
    if decimal_comma:
        t = t.replace('.', '').replace(',', '.', 1)
    elif ',' in t:
        if '.' in t:
            t = t.replace(',', '')
        elif _THOUSANDS.match(t):
            t = t.replace(',', '')
        elif _DEC_COMMA.match(t):
            t = t.replace(',', '.', 1)
        else:
            return None
    m = _NUMBER.match(t)
    if not m or (m.group(1) == '' and (m.group(2) is None or m.group(2) == '')):
        return None
    return {'neg': neg, 'int': _LEAD_ZEROS.sub('', m.group(1), count=1), 'frac': m.group(2) or '', 'cur': cur, 'pence': pence}


def scaled(n, dp):
    """A read number as a whole number of 10^-dp units, rounded half away from zero."""
    if not n:
        return None
    frac = n['frac'] + '000000000000'
    whole = float(int(n['int'] or '0')) * float(10 ** dp) + float(int(frac[:dp] or '0'))
    if int(frac[dp]) >= 5:
        whole += 1
    whole = jsnum(whole)
    return -whole if n['neg'] and whole != 0 else whole


def to_float(n):
    if not n:
        return None
    v = float((n['int'] or '0') + '.' + (n['frac'] or '0'))
    return -v if n['neg'] else v


def parse_cents(text, decimal_comma=False):
    return scaled(read_number(text, decimal_comma), 2)


def parse_micro(text, decimal_comma=False):
    return scaled(read_number(text, decimal_comma), 6)


def parse_float_text(text):
    return to_float(read_number(text, False))


# ---------- formatting ----------

SYMBOLS = {'USD': '$', 'GBP': '£', 'EUR': '€'}


def group3(digits):
    out = []
    for i, ch in enumerate(digits):
        if i > 0 and (len(digits) - i) % 3 == 0:
            out.append(',')
        out.append(ch)
    return ''.join(out)


def money(cents, currency, sign=False, whole=False):
    """Cents as money: -$1,234.56. sign adds a plus to positives; whole drops the pennies."""
    if cents is None:
        return ''
    neg = cents < 0
    v = -cents if neg else cents
    if whole:
        v = rnd(v / 100) * 100
    units, pence = str(math.floor(v / 100)), pad2(v % 100)
    sym = SYMBOLS.get(currency)
    body = group3(units) + ('' if whole else '.' + pence)
    text = sym + body if sym else ((currency + ' ') if currency else '') + body
    if neg and v != 0:
        return '-' + text
    if sign and v != 0:
        return '+' + text
    return text


def fmt_num(x, dp):
    """A number with a fixed number of decimals, half away from zero."""
    if x is None:
        return ''
    f = 10 ** dp
    v = rnd(x * f)
    neg = v < 0
    if neg:
        v = -v
    whole = str(math.floor(v / f))
    frac = str(v % f) if dp else ''
    frac = frac.rjust(dp, '0') if dp else ''
    return ('-' if neg else '') + group3(whole) + ('.' + frac if dp else '')


def fmt_pct(x, dp=0):
    return '' if x is None else fmt_num(x * 100, dp) + '%'


def fmt_r(r):
    if r is None:
        return ''
    return ('+' if r > 0 and rnd(r * 100) != 0 else '') + fmt_num(r, 2) + 'R'


def fmt_price(micro, grouping=False):
    if micro is None:
        return ''
    v = rnd(micro)
    neg = v < 0
    if neg:
        v = -v
    whole = str(math.floor(v / PRICE_SCALE))
    frac = str(v % PRICE_SCALE).rjust(6, '0').rstrip('0').ljust(2, '0')
    return ('-' if neg else '') + (group3(whole) if grouping else whole) + '.' + frac


def fmt_qty(q):
    if q is None:
        return ''
    v = rnd(q)
    whole = str(math.floor(v / QTY_SCALE))
    frac = str(v % QTY_SCALE).rjust(6, '0').rstrip('0')
    return group3(whole) + ('.' + frac if frac else '')


def fmt_date(day):
    c = civil(day)
    return '%s %d %s %d' % (DAY_NAMES[weekday(day)], c[2], MONTH_NAMES[c[1] - 1], c[0])


def fmt_short(day):
    c = civil(day)
    return '%d %s' % (c[2], MONTH_NAMES[c[1] - 1])


def fmt_day_month_year(day):
    c = civil(day)
    return '%d %s %d' % (c[2], MONTH_NAMES[c[1] - 1], c[0])


def fmt_time(sec):
    return '' if sec is None else pad2(math.floor(sec / 3600)) + ':' + pad2(math.floor(sec / 60) % 60)


def fmt_time_long(sec):
    return '' if sec is None else fmt_time(sec) + ':' + pad2(sec % 60)


def fmt_duration(sec, time_known=True):
    if sec is None:
        return ''
    if time_known is False:
        d0 = math.floor(sec / DAY)
        return 'same day' if d0 == 0 else '%d %s' % (d0, 'day' if d0 == 1 else 'days')
    if sec < 60:
        return '%d s' % sec
    mins = math.floor(sec / 60)
    if mins < 60:
        return '%d min' % mins
    h, m = math.floor(mins / 60), mins % 60
    if h < 24:
        return '%d h %s min' % (h, pad2(m))
    d = math.floor(h / 24)
    return '%d %s%d h' % (d, 'day ' if d == 1 else 'days ', h % 24)


def week_label(week):
    return 'w/c ' + fmt_day_month_year(week)


def plural(n, one, many=None):
    return '%d %s' % (n, one if n == 1 else (many or one + 's'))


def iso_stamp(day, sec):
    if sec is None:
        return to_iso(day)
    return to_iso(day) + 'T' + pad2(math.floor(sec / 3600)) + ':' + pad2(math.floor(sec / 60) % 60) + ':' + pad2(sec % 60)


def plain_money(cents):
    if cents is None:
        return ''
    neg = cents < 0
    v = -cents if neg else cents
    return ('-' if neg else '') + str(math.floor(v / 100)) + '.' + pad2(v % 100)
