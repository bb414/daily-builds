"""Reading bank exports: amounts, dates, delimited text, header rows and whole statements.

Everything follows the browser model line for line, including the reasons
given for skipped rows and the line numbers they are recorded against.
"""

import math
import re

from .common import collapse_spaces, js_keys, js_regex, js_string, js_trim, text_or
from .dates import MONTHS, valid_day

# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------

_BRACKETED = js_regex(r'^\(.*\)$')
_TRAILING_MARK = js_regex(r'^(.*?)\s*\b(DR|CR|D|C)\.?$', 'i')
_LEADING_MARK = js_regex(r'^(DR|CR)\b\s*(.*)$', 'i')
_DIGIT = js_regex(r'\d')
_DEBIT_WORD = js_regex(r'^d', 'i')
_CURRENCY = js_regex(r'(GBP|EUR|USD|\u00a3|\u20ac|\$)', 'i')
_MINUS_BOTH_ENDS = js_regex(r'^-.*-$')
_SIGNED_BRACKETS = js_regex(r'^-?\(.*\)$')
_POINT_GROUPED = js_regex(r'^\d{1,3}(,\d{3})+(\.\d+)?$')
_POINT_PLAIN = js_regex(r'^\d+(\.\d+)?$')
_COMMA_GROUPED = js_regex(r'^\d{1,3}(\.\d{3})+,\d{1,2}$')
_COMMA_PLAIN = js_regex(r'^\d+,\d{1,2}$')
_FRACTION_ONLY = js_regex(r'^\.\d+$')


def parse_amount(raw):
    """Read an amount as whole pence, or None when the text is not an amount.

    Copes with currency symbols, thousands separators, brackets or a trailing
    minus for money out, DR and CR markers and comma decimals.
    """
    if raw is None:
        return None
    t = js_trim(js_string(raw))
    if not t:
        return None
    neg = False
    t = t.replace('\u2212', '-').replace('\u00a0', ' ')
    if _BRACKETED.search(t):
        neg = True
        t = js_trim(t[1:-1])
    m = _TRAILING_MARK.search(t)
    if m and _DIGIT.search(m.group(1)):
        if _DEBIT_WORD.search(m.group(2)):
            neg = not neg
        t = js_trim(m.group(1))
    m = _LEADING_MARK.search(t)
    if m and _DIGIT.search(m.group(2)):
        if _DEBIT_WORD.search(m.group(1)):
            neg = not neg
        t = js_trim(m.group(2))
    t = collapse_spaces(_CURRENCY.sub('', t), '')
    if _MINUS_BOTH_ENDS.search(t):
        return None
    if t.endswith('-'):
        neg = not neg
        t = t[:-1]
    if t[:1] in ('+', '-'):
        if t[0] == '-':
            neg = not neg
        t = t[1:]
    if _SIGNED_BRACKETS.search(t):
        neg = not neg
        t = t.replace('(', '').replace(')', '')
    if not t:
        return None
    if _POINT_GROUPED.search(t) or _POINT_PLAIN.search(t):
        parts = t.replace(',', '').split('.')
        int_part, frac = parts[0], (parts[1] if len(parts) > 1 else '')
    elif _COMMA_GROUPED.search(t) or _COMMA_PLAIN.search(t):
        parts = t.replace('.', '').split(',')
        int_part, frac = parts[0], parts[1]
    elif _FRACTION_ONLY.search(t):
        int_part, frac = '0', t[1:]
    else:
        return None
    whole = int(int_part)
    f = (frac + '000')[:3]
    pence = whole * 100 + int(f[:2]) + (1 if int(f[2]) >= 5 else 0)
    try:
        if math.isinf(float(whole) * 100):
            return None
    except OverflowError:
        return None
    return -pence if neg else pence


# ---------------------------------------------------------------------------
# Dates in exports
# ---------------------------------------------------------------------------

def month_index(word):
    """1 for January up to 12 for December, from the first three letters; 0 if not a month."""
    w = js_string(word).lower()[:3]
    return MONTHS.index(w) + 1 if w in MONTHS else 0


def full_year(y):
    """A year from its digits: two-digit years below 70 are 20xx, the rest 19xx."""
    if len(y) == 2:
        n = int(y)
        return 2000 + n if n < 70 else 1900 + n
    return int(y)


_WEEKDAY_PREFIX = js_regex(r'^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+', 'i')
_ISO_DATE = js_regex(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:$|[T\s])')
_YEAR_FIRST = js_regex(r'^(\d{4})[\/.](\d{1,2})[\/.](\d{1,2})(?:$|\s)')
_COMPACT = js_regex(r'^(\d{4})(\d{2})(\d{2})(?:\d{4}(?:\d{2})?)?(?:\.\d+)?(?:\s*\[.*\])?$')
_NUMERIC_PAIR = js_regex(r'^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2}|\d{4})(?:$|[\sT,])')
_DAY_MONTH_NAME = js_regex(r'^(\d{1,2})(?:st|nd|rd|th)?[\s\-\/.]*([A-Za-z]{3,9})\.?[\s\-\/.,]*'
                           r'(\d{2}|\d{4})(?:$|[\sT,])')
_MONTH_NAME_DAY = js_regex(r'^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?:$|[\sT,])')


def date_shape(raw):
    """Classify a date string.

    Returns {'kind': 'fixed', 'day': ...} when the text can only mean one
    date (day is None if that date does not exist), {'kind': 'pair', 'a',
    'b', 'y'} for numeric dates that could be day first or month first, or
    None when the text is not a date at all.
    """
    t = _WEEKDAY_PREFIX.sub('', js_trim(text_or(raw)), count=1)
    if not t:
        return None
    m = _ISO_DATE.search(t) or _YEAR_FIRST.search(t) or _COMPACT.search(t)
    if m:
        return {'kind': 'fixed', 'day': valid_day(int(m.group(1)), int(m.group(2)), int(m.group(3)))}
    m = _NUMERIC_PAIR.search(t)
    if m:
        return {'kind': 'pair', 'a': int(m.group(1)), 'b': int(m.group(2)), 'y': full_year(m.group(3))}
    m = _DAY_MONTH_NAME.search(t)
    if m and month_index(m.group(2)):
        return {'kind': 'fixed', 'day': valid_day(full_year(m.group(3)), month_index(m.group(2)), int(m.group(1)))}
    m = _MONTH_NAME_DAY.search(t)
    if m and month_index(m.group(1)):
        return {'kind': 'fixed', 'day': valid_day(int(m.group(3)), month_index(m.group(1)), int(m.group(2)))}
    return None


def detect_date_order(values):
    """Decide whether d/m/y or m/d/y dates are in use: UK order unless the data says otherwise."""
    dmy = mdy = pairs = 0
    for v in values:
        s = date_shape(v)
        if not s or s['kind'] != 'pair':
            continue
        pairs += 1
        if s['a'] > 12 and s['b'] <= 12:
            dmy += 1
        elif s['b'] > 12 and s['a'] <= 12:
            mdy += 1
    if mdy > 0 and dmy == 0:
        return {'order': 'MDY', 'ambiguous': False, 'pairs': pairs}
    return {'order': 'DMY', 'ambiguous': pairs > 0 and dmy == 0, 'conflicting': dmy > 0 and mdy > 0, 'pairs': pairs}


def parse_date(raw, order=None):
    """A date string as a day number, reading numeric dates in the given order ('DMY' or 'MDY')."""
    s = date_shape(raw)
    if not s:
        return None
    if s['kind'] == 'fixed':
        return s['day']
    if order == 'MDY':
        return valid_day(s['y'], s['a'], s['b'])
    return valid_day(s['y'], s['b'], s['a'])


# ---------------------------------------------------------------------------
# Delimited text
# ---------------------------------------------------------------------------

def strip_bom(text):
    """Drop a leading byte order mark."""
    return text[1:] if text[:1] == '\ufeff' else text


def parse_delimited(text, delim):
    """Split delimited text into rows of cells (RFC 4180 quotes, quoted line breaks).

    Returns {'rows': [...], 'lines': [...]}, where lines holds the line number
    each row starts on.
    """
    rows, row, lines = [], [], []
    cell = ''
    i, n = 0, len(text)
    in_q = False
    line_no = row_line = 1
    while i < n:
        ch = text[i]
        if in_q:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    cell += '"'
                    i += 2
                    continue
                in_q = False
                i += 1
                continue
            if ch == '\n':
                line_no += 1
            cell += ch
            i += 1
            continue
        if ch == '"' and js_trim(cell) == '':
            in_q = True
            cell = ''
            i += 1
            continue
        if ch == delim:
            row.append(cell)
            cell = ''
            i += 1
            continue
        if ch == '\r' or ch == '\n':
            row.append(cell)
            rows.append(row)
            lines.append(row_line)
            row, cell = [], ''
            if ch == '\r' and i + 1 < n and text[i + 1] == '\n':
                i += 1
            i += 1
            line_no += 1
            row_line = line_no
            continue
        cell += ch
        i += 1
    if cell != '' or row:
        row.append(cell)
        rows.append(row)
        lines.append(row_line)
    return {'rows': rows, 'lines': lines}


_LINE_BREAK = js_regex(r'\r?\n')


def sniff_delimiter(text):
    """Pick the delimiter that splits the first 30 lines most consistently."""
    sample = [line for line in _LINE_BREAK.split(text) if js_trim(line)][:30]
    best, best_score = ',', -1
    for d in [',', ';', '\t', '|']:
        counts = []
        for line in sample:
            c, q = 0, False
            for ch in line:
                if ch == '"':
                    q = not q
                elif not q and ch == d:
                    c += 1
            if c > 0:
                counts.append(c)
        if not counts:
            continue
        freq = {}
        for c in counts:
            freq[c] = freq.get(c, 0) + 1
        mode = mode_n = 0
        for k in sorted(freq):
            if freq[k] > mode_n or (freq[k] == mode_n and k > mode):
                mode, mode_n = k, freq[k]
        score = mode_n * 10 + mode
        if score > best_score:
            best_score, best = score, d
    return best


# ---------------------------------------------------------------------------
# Header rows
# ---------------------------------------------------------------------------

# Column names that banks use, by role.
ROLE_NAMES = {
    'date': ['transaction date', 'date', 'posting date', 'posted date', 'completed date', 'started date',
             'booking date', 'trans date', 'txn date', 'date of transaction', 'posted', 'transaction time',
             'value date', 'created'],
    'payee': ['name', 'payee', 'counter party', 'counterparty', 'merchant', 'merchant name', 'description',
              'transaction description', 'details', 'transaction details', 'narrative', 'particulars',
              'beneficiary', 'party'],
    'memo': ['reference', 'memo', 'notes', 'notes and tags', 'note', 'additional details', 'extra details', 'ref'],
    'amount': ['amount', 'amount gbp', 'transaction amount', 'value', 'amount in gbp', 'net amount', 'sum',
               'billing amount', 'amount gbp gbp'],
    'out': ['paid out', 'money out', 'debit', 'debit amount', 'debits', 'withdrawals', 'withdrawal', 'withdrawn',
            'payments', 'out', 'spent', 'outgoing', 'outgoings', 'amount out', 'paid out gbp', 'money out gbp'],
    'in': ['paid in', 'money in', 'credit', 'credit amount', 'credits', 'deposits', 'deposit', 'receipts', 'in',
           'incoming', 'amount in', 'paid in gbp', 'money in gbp'],
    'sign': ['debit credit', 'dr cr', 'cr dr', 'credit debit', 'indicator', 'direction', 'transaction direction',
             'debit or credit'],
    'type': ['type', 'transaction type', 'payment type', 'method', 'tran type', 'payment method', 'transaction code'],
    'category': ['category', 'spending category', 'subcategory', 'spending type', 'categories'],
    'balance': ['balance', 'running balance', 'balance gbp', 'account balance'],
    'acct': ['account number', 'account no', 'account', 'acct no', 'account id', 'sort code and account number', 'iban'],
    'currency': ['currency', 'ccy', 'local currency'],
    'status': ['state', 'status', 'transaction status'],
}
_NOT_KEY_CHARS = js_regex(r'[^a-z0-9]+')
_ROLE_PATTERNS = [
    (js_regex(r'\bdate\b'), js_regex(r'update'), 'date'),
    (js_regex(r'\b(paid out|money out|debit)\b'), None, 'out'),
    (js_regex(r'\b(paid in|money in|credit)\b'), None, 'in'),
    (js_regex(r'\bamount\b'), js_regex(r'local|original|foreign'), 'amount'),
    (js_regex(r'\b(description|details|narrative|payee|merchant)\b'), None, 'payee'),
    (js_regex(r'\b(reference|memo|notes?)\b'), None, 'memo'),
    (js_regex(r'\bbalance\b'), None, 'balance'),
    (js_regex(r'\bcategory\b'), None, 'category'),
    (js_regex(r'\btype\b'), None, 'type'),
]


def header_key(h):
    """A header cell reduced to lower-case words for matching: 'Paid out (£)' becomes 'paid out gbp'."""
    k = text_or(h).lower().replace('\u00a3', ' gbp ').replace('#', ' ')
    return js_trim(_NOT_KEY_CHARS.sub(' ', k))


def role_of(h):
    """The role a header cell plays (date, payee, amount ...), or None."""
    k = header_key(h)
    if not k:
        return None
    for role, names in ROLE_NAMES.items():
        if k in names:
            return role
    for pattern, unless, role in _ROLE_PATTERNS:
        if pattern.search(k) and not (unless and unless.search(k)):
            return role
    return None


def map_header(cells):
    """Map header cells to roles. The earliest synonym in each list wins when two columns compete."""
    mapping, rank = {}, {}
    for i, c in enumerate(cells):
        r = role_of(c)
        if not r:
            continue
        k = header_key(c)
        pos = ROLE_NAMES[r].index(k) if k in ROLE_NAMES[r] else 50
        if r == 'payee' and 'payee' in mapping:
            # A second description-like column becomes the memo if there is none.
            if 'memo' not in mapping and pos >= rank['payee']:
                mapping['memo'] = i
                rank['memo'] = pos
                continue
        if r not in mapping or pos < rank[r]:
            if r == 'payee' and 'payee' in mapping and 'memo' not in mapping:
                mapping['memo'] = mapping['payee']
                rank['memo'] = rank['payee']
            mapping[r] = i
            rank[r] = pos
    return mapping


def has_amount_role(mapping):
    """True when a mapping says where the money is."""
    return 'amount' in mapping or 'out' in mapping or 'in' in mapping


def _cell(row, index):
    """row[index] the JavaScript way: None when the cell is not there."""
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(row):
        return row[index]
    return None


_LETTER_RUN = js_regex(r'[a-z]{3,}', 'i')
_MARKER_WORDS = js_regex(r'gbp|dr|cr', 'i')


def infer_columns(rows):
    """Guess roles for a file with no header row, from what the cells look like."""
    sample = [r for r in rows if any(js_trim(js_string(c)) for c in r)][:60]
    if not sample:
        return None
    width = max(len(r) for r in sample)
    stats = []
    for c in range(width):
        dates = nums = filled = text_len = abs_sum = 0
        for r in sample:
            raw = _cell(r, c)
            v = js_trim(js_string('' if raw is None else raw))
            if not v:
                continue
            filled += 1
            if date_shape(v):
                dates += 1
            else:
                a = parse_amount(v)
                if a is not None and _DIGIT.search(v) and not _LETTER_RUN.search(_MARKER_WORDS.sub('', v)):
                    nums += 1
                    abs_sum += abs(a)
                else:
                    text_len += len(v)
        stats.append({'c': c, 'dates': dates, 'nums': nums, 'filled': filled, 'textLen': text_len, 'absSum': abs_sum})
    mapping = {}
    date_cols = [s for s in stats if s['filled'] and s['dates'] / s['filled'] >= 0.8]
    if not date_cols:
        return None
    mapping['date'] = date_cols[0]['c']
    num_cols = [s for s in stats if s['c'] != mapping['date'] and s['filled'] and s['nums'] / s['filled'] >= 0.8]
    sparse = [s for s in stats if s['c'] != mapping['date'] and s['nums'] > 0 and s['filled'] < len(sample) * 0.9
              and s['nums'] / max(1, s['filled']) >= 0.8]
    if len(sparse) >= 2:
        mapping['out'] = sparse[0]['c']
        mapping['in'] = sparse[1]['c']
    elif num_cols:
        mapping['amount'] = num_cols[0]['c']
        if len(num_cols) >= 2:
            mapping['balance'] = num_cols[-1]['c']
    else:
        return None
    used = set(mapping.values())
    texts = [s for s in stats if s['c'] not in used and s['textLen'] > 0]
    texts.sort(key=lambda s: (-s['textLen'], s['c']))
    if not texts:
        return None
    mapping['payee'] = texts[0]['c']
    return mapping


# ---------------------------------------------------------------------------
# Whole statements
# ---------------------------------------------------------------------------

TOTAL_LINE = js_regex(r'^(total|totals|sub ?total|opening balance|closing balance|balance brought forward|'
                      r'balance carried forward|brought forward|carried forward|start balance|end balance)\b', 'i')
SKIP_STATUS = js_regex(r'^(declined|reverted|reversed|failed|cancelled|canceled|void|rejected)$', 'i')
_PENDING = js_regex(r'^pending$', 'i')
_LOOKS_JSON = js_regex(r'^\s*[{\[]')
_LOOKS_PDF = js_regex(r'^\s*%PDF')
_CONTROL_CHARS = js_regex(r'[\u0000-\u0008]')
_SIGN_OUT = js_regex(r'^(d|dr|debit|out|money out|paid out|withdrawal)')
_SIGN_IN = js_regex(r'^(c|cr|credit|in|money in|paid in|deposit)')

WARN_UNKNOWN_HEADER = ('The column names were not ones this tool knows, so the columns were worked out from what '
                       'they contain. Check them with Change columns.')
_NOT_DIGITS = js_regex(r'\D')
_CARD_NAME = js_regex(r'card|credit|amex|visa|mastercard', 'i')
_REPAYMENT = js_regex(r'PAYMENT|THANK YOU|REPAYMENT|RECEIVED|DIRECT DEBIT', 'i')
WARN_MOSTLY_IN = ('Most amounts in this file are positive, so they were read as money coming in. If this is a credit '
                  'card export where spending shows as positive, choose "Positive is money out" under Change columns.')
WARN_NO_HEADER = ('No header row was found, so the columns were worked out from what they contain. '
                  'Check the column choices below.')
WARN_FLIPPED = ('Most amounts in this file are positive, so positive amounts were read as money spent (the way '
                'credit card exports usually work). Switch this if it is wrong.')
WARN_AMBIGUOUS = ('Every date in this file could be read either way, so they were read the UK way (day first). '
                  'Switch to month first if your bank is not in the UK.')
WARN_CONFLICTING = ('Some dates only make sense day first and others only month first. They were read day first; '
                    'check the rows listed below.')


def parse_csv(text, name=None, options=None):
    """Read one export.

    Returns the transactions it could read, the rows it skipped with reasons
    and a description of the layout it found. options may hold account,
    dateOrder ('DMY' or 'MDY'), signConvention ('auto', 'negative-out' or
    'positive-out'), delimiter, mapping ({role: column index}) and headerRow.
    """
    options = options or {}
    text = strip_bom(text_or(text))
    result = {'name': name or 'statement', 'format': 'csv', 'account': options.get('account') or default_account(name),
              'transactions': [], 'skipped': [], 'warnings': [], 'layout': None, 'ok': False, 'rowCount': 0,
              'blankRows': 0, 'closing': None}
    if not js_trim(text):
        result['error'] = 'The file is empty.'
        return result
    if _LOOKS_JSON.search(text):
        result['error'] = ('This looks like a JSON file, not a bank statement. '
                           'To reopen a saved review, use Open a saved review.')
        return result
    if _LOOKS_PDF.search(text):
        result['error'] = 'This is a PDF. Download your statement as CSV from your banking app or website instead.'
        return result
    if text.startswith('PK') or _CONTROL_CHARS.search(text[:2000]):
        result['error'] = ('This looks like a spreadsheet or other binary file. '
                           'Save it as CSV first (File, Save as, CSV).')
        return result
    delim = options.get('delimiter') or sniff_delimiter(text)
    parsed = parse_delimited(text, delim)
    rows, lines = parsed['rows'], parsed['lines']
    header_idx, mapping = -1, None
    if options.get('mapping') is not None and options.get('headerRow') is not None:
        header_idx, mapping = options['headerRow'], options['mapping']
    else:
        for i in range(min(len(rows), 40)):
            m = map_header(rows[i])
            if 'date' in m and has_amount_role(m) and ('payee' in m or 'memo' in m):
                header_idx, mapping = i, m
                break
        if options.get('mapping') is not None:
            mapping = options['mapping']
    headers = [js_trim(js_string(h)) for h in rows[header_idx]] if header_idx >= 0 else None
    if mapping is None:
        # A first row of plain words is a header with names this tool does not know.
        fi = 0
        while fi < len(rows) and not any(js_trim(js_string(c)) for c in rows[fi]):
            fi += 1
        looks_header = (fi < len(rows) - 1 and len(rows[fi]) > 1
                        and all(date_shape(c) is None and parse_amount(c) is None for c in rows[fi]))
        mapping = infer_columns(rows[fi + 1:] if looks_header else rows)
        if mapping and looks_header:
            header_idx = fi
            headers = [js_trim(js_string(h)) for h in rows[fi]]
            result['warnings'].append(WARN_UNKNOWN_HEADER)
        elif mapping:
            result['warnings'].append(WARN_NO_HEADER)
    if mapping is None or 'date' not in mapping or not has_amount_role(mapping):
        result['error'] = ('Could not find a date column and an amount column. Choose the columns by hand, '
                           'or download the template to see the layout that always works.')
        width = len(rows[0]) if rows else 0
        result['headers'] = headers if headers is not None else ['Column ' + str(i + 1) for i in range(width)]
        result['preview'] = rows[:6]
        result['delimiter'] = delim
        return result
    if 'payee' not in mapping and 'memo' in mapping:
        mapping['payee'] = mapping.pop('memo')
    body, body_lines = rows[header_idx + 1:], lines[header_idx + 1:]
    order = options.get('dateOrder') or None
    date_info = detect_date_order([_cell(r, mapping['date']) for r in body])
    if not order:
        order = date_info['order']
    raw = []
    currencies = {}
    joiner = ' | ' if delim == '\t' else delim
    for k, r in enumerate(body):
        line = body_lines[k]
        cells = [js_string(c) for c in r]
        if not any(js_trim(c) for c in cells):
            result['blankRows'] += 1
            continue
        result['rowCount'] += 1

        def get(role):
            if role not in mapping:
                return ''
            value = _cell(cells, mapping[role])
            return js_trim('' if value is None else value)

        def skip(reason):
            result['skipped'].append({'line': line, 'reason': reason, 'raw': raw_line})

        raw_line = joiner.join(cells)[:160]
        desc = collapse_spaces(get('payee'))
        memo = collapse_spaces(get('memo'))
        date_text = get('date')
        if headers is not None and js_trim('|'.join(cells)) == js_trim('|'.join(headers)):
            skip('A repeated header row')
            continue
        if not date_text:
            if TOTAL_LINE.search(desc) or TOTAL_LINE.search(js_trim(' '.join(cells))):
                skip('A total or balance line, not a payment')
            else:
                skip('No date in this row')
            continue
        day = parse_date(date_text, order)
        if day is None:
            skip('Could not read the date "' + date_text[:30] + '"')
            continue
        if TOTAL_LINE.search(desc):
            skip('A total or balance line, not a payment')
            continue
        status = get('status')
        if status and SKIP_STATUS.search(status):
            skip('Marked ' + status.lower() + ', so no money left the account')
            continue
        if status and _PENDING.search(status):
            skip('Still pending, so it may change or drop off')
            continue
        amount, amount_source = None, ''
        if 'amount' in mapping:
            at = get('amount')
            amount = parse_amount(at)
            amount_source = at
            if amount is not None and 'sign' in mapping:
                sg = get('sign').lower()
                if _SIGN_OUT.search(sg):
                    amount = -abs(amount)
                elif _SIGN_IN.search(sg):
                    amount = abs(amount)
        else:
            ot, it = get('out'), get('in')
            o, n2 = parse_amount(ot), parse_amount(it)
            amount_source = ot or it
            if ot and o is None:
                skip('Could not read the amount "' + ot[:20] + '"')
                continue
            if it and n2 is None:
                skip('Could not read the amount "' + it[:20] + '"')
                continue
            if o is not None and o != 0:
                amount = -abs(o)
            elif n2 is not None and n2 != 0:
                amount = abs(n2)
            elif o == 0 or n2 == 0:
                amount = 0
        if amount is None:
            if amount_source:
                skip('Could not read the amount "' + amount_source[:20] + '"')
            else:
                skip('No amount in this row')
            continue
        if amount == 0:
            skip('A zero amount, so nothing was paid')
            continue
        cur = get('currency').upper()
        if cur:
            currencies[cur] = currencies.get(cur, 0) + 1
        if not desc and not memo:
            desc = '(no description)'
        raw.append({'day': day, 'amount': amount, 'desc': desc or memo, 'memo': memo if desc else '',
                    'type': get('type'), 'category': get('category'), 'line': line,
                    'balance': parse_amount(get('balance')) if 'balance' in mapping else None})
    sign_mode = options.get('signConvention') or 'auto'
    flipped = False
    if 'amount' in mapping and 'sign' not in mapping and raw:
        pos = len([t for t in raw if t['amount'] > 0])
        mostly_positive = len(raw) >= 5 and pos / len(raw) > 0.7
        # Only treat positive amounts as spending when something says this is a card: its name, or a repayment line.
        card_hint = bool(_CARD_NAME.search(result['name'] + ' ' + result['account'])) or any(
            t['amount'] < 0 and _REPAYMENT.search(t['desc']) for t in raw)
        if sign_mode == 'positive-out' or (sign_mode == 'auto' and mostly_positive and card_hint):
            for t in raw:
                t['amount'] = -t['amount']
            flipped = True
            if sign_mode == 'auto':
                result['warnings'].append(WARN_FLIPPED)
        elif sign_mode == 'auto' and mostly_positive:
            result['warnings'].append(WARN_MOSTLY_IN)
    if 'balance' in mapping and not flipped and raw:
        # The balance after the last payment: the last row of the latest day, whichever way round the file is sorted.
        with_bal = [t for t in raw if t['balance'] is not None]
        if with_bal:
            max_day = max(t['day'] for t in with_bal)
            same_day = [t for t in with_bal if t['day'] == max_day]
            pick = same_day[-1] if raw[0]['day'] <= raw[-1]['day'] else same_day[0]
            result['closing'] = {'day': pick['day'], 'balance': pick['balance']}
    non_gbp = [c for c in js_keys(currencies) if c != 'GBP']
    if non_gbp:
        result['warnings'].append('Some rows are in ' + ', '.join(non_gbp)
                                  + '. Amounts are used as they are, so totals mix currencies.')
    if date_info['ambiguous'] and not options.get('dateOrder'):
        result['warnings'].append(WARN_AMBIGUOUS)
    if date_info.get('conflicting'):
        result['warnings'].append(WARN_CONFLICTING)
    if 'acct' in mapping and not options.get('account'):
        # One account number for the whole file names the account, the same way every month.
        ids = {}
        for r in body:
            v = js_trim(js_string(_cell(r, mapping['acct']) or ''))
            if v:
                ids[v] = 1
        if len(ids) == 1:
            only = next(iter(ids))
            digits = _NOT_DIGITS.sub('', only)
            result['account'] = 'Account ending ' + digits[-4:] if len(digits) >= 4 else only[:40]
    account = result['account']
    result['transactions'] = [{'day': t['day'], 'amount': t['amount'], 'desc': t['desc'], 'memo': t['memo'],
                               'type': t['type'], 'category': t['category'], 'account': account,
                               'source': result['name'], 'line': t['line']} for t in raw]
    if 'amount' not in mapping:
        convention = 'columns'
    elif 'sign' in mapping:
        convention = 'marker'
    else:
        convention = 'positive-out' if flipped else 'negative-out'
    result['layout'] = {'delimiter': delim, 'headerRow': header_idx, 'headers': headers, 'mapping': mapping,
                        'dateOrder': order, 'signConvention': convention,
                        'description': describe_layout(mapping, headers, flipped, order)}
    result['ok'] = len(result['transactions']) > 0
    if not result['ok'] and not result.get('error'):
        result['error'] = ('No payments could be read from this file. The rows it skipped are listed with reasons.'
                           if result['skipped'] else 'The file has a header row but no payments under it.')
    finish_range(result)
    return result


def describe_layout(mapping, headers, flipped, order):
    """The layout in words, for showing beside the file."""
    def name(role):
        if role not in mapping:
            return 'column NaN'
        if headers is not None:
            header = _cell(headers, mapping[role])
            return '"' + ('undefined' if header is None else header) + '"'
        return 'column ' + str(mapping[role] + 1)
    parts = ['dates from ' + name('date') + ' (' + ('month first' if order == 'MDY' else 'day first') + ')']
    if 'amount' in mapping:
        if 'sign' in mapping:
            how = ' with ' + name('sign') + ' saying which way'
        else:
            how = ', positive means money out' if flipped else ', negative means money out'
        parts.append('amounts from ' + name('amount') + how)
    else:
        parts.append('money out from ' + (name('out') if 'out' in mapping else 'nowhere')
                     + ' and money in from ' + (name('in') if 'in' in mapping else 'nowhere'))
    parts.append('payee from ' + name('payee'))
    if 'type' in mapping:
        parts.append('payment type from ' + name('type'))
    return '; '.join(parts)


def finish_range(result):
    """Record the first and last day a statement covers (None when it has no payments)."""
    days = [t['day'] for t in result['transactions']]
    result['start'] = min(days) if days else None
    result['end'] = max(days) if days else None


_EXTENSION = js_regex(r'\.[a-z0-9]+$', 'i')
_UNDERSCORES = js_regex(r'[_]+')
_DATE_IN_NAME = js_regex(r'\b(19|20)\d{2}[-_ ]?\d{2}([-_ ]?\d{2})?\b')
_COPY_NUMBER = js_regex(r'\(\d+\)')
_NUMBERS = js_regex(r'\b\d+\b')
_MONTH_WORDS = js_regex(r'\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?|oct(ober)?'
                        r'|nov(ember)?|dec(ember)?)\b', 'i')
_EXPORT_WORDS = js_regex(r'\b(statements?|exported|export|transactions?|downloaded|download|csv|ofx|qif|data|history|from|to)\b', 'i')
_DASHES_AND_SPACES = js_regex(r'[-\s]+')


def default_account(name):
    """An account name from a file name, without the parts that change from one download to the next.

    Dates, months, numbers and copy markers such as "(3)" are dropped, so
    'current-account-december.csv' becomes 'Current account' and next month's
    file lands in the same account.
    """
    n = js_trim(_UNDERSCORES.sub(' ', _EXTENSION.sub('', text_or(name, 'Account'), count=1)))
    n = _MONTH_WORDS.sub('', _NUMBERS.sub('', _COPY_NUMBER.sub('', _DATE_IN_NAME.sub('', n))))
    n = js_trim(_DASHES_AND_SPACES.sub(' ', _EXPORT_WORDS.sub('', n)))
    if not n:
        return 'Account'
    return n[0].upper() + n[1:]


def _line_at(text, index):
    return text.count('\n', 0, index) + 1


def _new_result(name, fmt, options):
    return {'name': name or 'statement', 'format': fmt, 'account': options.get('account') or default_account(name),
            'transactions': [], 'skipped': [], 'warnings': [], 'layout': None, 'ok': False, 'rowCount': 0,
            'blankRows': 0, 'closing': None}


OFX_TYPES = {'DIRECTDEBIT': 'Direct debit', 'REPEATPMT': 'Standing order', 'POS': 'Card payment', 'ATM': 'Cash machine',
             'XFER': 'Transfer', 'CHECK': 'Cheque', 'PAYMENT': 'Payment', 'FEE': 'Fee', 'SRVCHG': 'Service charge',
             'INT': 'Interest', 'DIV': 'Dividend', 'DEP': 'Deposit', 'DIRECTDEP': 'Bank credit', 'CASH': 'Cash',
             'CREDIT': 'Credit', 'DEBIT': 'Debit', 'OTHER': ''}
# [\s\S] in the JavaScript means any character, which is "." with DOTALL here.
_STMTTRN = re.compile(r'<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))', re.IGNORECASE | re.DOTALL)
_LEDGER = re.compile(r'<LEDGERBAL>(.*?)(?:</LEDGERBAL>|<AVAILBAL>|</STMTRS>|</CCSTMTRS>|\Z)', re.IGNORECASE | re.DOTALL)
_CARD_STATEMENT = js_regex(r'<CCSTMTRS>|<CCACCTFROM>', 'i')
_SPACES = js_regex(r'\s+')


def _ofx_get(block, tag):
    m = js_regex('<' + tag + '>([^<\\r\\n]*)', 'i').search(block)
    return js_trim(m.group(1)) if m else ''


def _ofx_unescape(s):
    return (s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
            .replace('&amp;', '&'))


def parse_ofx(text, name=None, options=None):
    """Read an OFX file (the Money and Quicken download many banks offer), in SGML or XML form."""
    options = options or {}
    text = strip_bom(text_or(text))
    result = _new_result(name, 'ofx', options)
    cur = _ofx_get(text, 'CURDEF').upper()
    is_card = bool(_CARD_STATEMENT.search(text))
    for m in _STMTTRN.finditer(text):
        block, line = m.group(1), _line_at(text, m.start())
        result['rowCount'] += 1
        date_text = _ofx_get(block, 'DTPOSTED') or _ofx_get(block, 'DTUSER')
        amount_text = _ofx_get(block, 'TRNAMT')
        nm, memo = _ofx_unescape(_ofx_get(block, 'NAME')), _ofx_unescape(_ofx_get(block, 'MEMO'))
        raw = ('<STMTTRN> ' + ' | '.join(x for x in [date_text, amount_text, nm, memo] if x))[:160]
        if not date_text:
            result['skipped'].append({'line': line, 'reason': 'No date in this transaction', 'raw': raw})
            continue
        day = parse_date(date_text, 'DMY')
        if day is None:
            result['skipped'].append({'line': line, 'reason': 'Could not read the date "' + date_text[:30] + '"', 'raw': raw})
            continue
        amount = parse_amount(amount_text)
        if amount is None:
            reason = ('Could not read the amount "' + amount_text[:20] + '"') if amount_text else 'No amount in this transaction'
            result['skipped'].append({'line': line, 'reason': reason, 'raw': raw})
            continue
        if amount == 0:
            result['skipped'].append({'line': line, 'reason': 'A zero amount, so nothing was paid', 'raw': raw})
            continue
        trn_type = _ofx_get(block, 'TRNTYPE').upper()
        desc = _SPACES.sub(' ', nm or memo or '(no description)')
        result['transactions'].append({'day': day, 'amount': amount, 'desc': desc, 'memo': _SPACES.sub(' ', memo) if nm else '',
                                       'type': OFX_TYPES.get(trn_type, trn_type), 'category': '',
                                       'account': result['account'], 'source': result['name'], 'line': line})
    if not result['rowCount']:
        result['error'] = 'This OFX file has no transactions in it.'
        finish_range(result)
        return result
    if cur and cur != 'GBP':
        result['warnings'].append('This file is in ' + cur + '. Amounts are used as they are.')
    led = _LEDGER.search(text)
    if led:
        bal_amt, bal_day = parse_amount(_ofx_get(led.group(1), 'BALAMT')), parse_date(_ofx_get(led.group(1), 'DTASOF'), 'DMY')
        if bal_amt is not None and bal_day is not None and not is_card:
            result['closing'] = {'day': bal_day, 'balance': bal_amt}
    result['layout'] = {'format': 'ofx', 'description': 'an OFX download (the Money and Quicken format) for a '
                        + ('credit card' if is_card else 'bank account')
                        + ', with dates from DTPOSTED, signed amounts from TRNAMT and payees from NAME',
                        'mapping': None, 'headers': None}
    result['ok'] = len(result['transactions']) > 0
    if not result['ok']:
        result['error'] = 'No payments could be read from this file. The transactions it skipped are listed with reasons.'
    finish_range(result)
    return result


_LINE_BREAKS = js_regex(r'\r\n|\n|\r')
_QIF_YEAR = js_regex(r"'\s*(\d{1,2})$")
_ALL_DIGITS = js_regex(r'^\d+$')


def _qif_date(s):
    """Quicken writes years after 2000 as 28/11'26 or 11/28' 6."""
    s = _QIF_YEAR.sub(lambda m: '/' + ('0' + m.group(1) if len(m.group(1)) == 1 else m.group(1)), s, count=1)
    return s.replace("'", '/')


def parse_qif(text, name=None, options=None):
    """Read a QIF file (the older Quicken interchange format): one field per line, records ending in ^."""
    options = options or {}
    text = strip_bom(text_or(text))
    result = _new_result(name, 'qif', options)
    records, rec = [], None
    for i, line in enumerate(_LINE_BREAKS.split(text)):
        if not js_trim(line):
            continue
        if line[0] == '!':
            continue
        if rec is None:
            rec = {'line': i + 1, 'fields': {}}
        if line[0] == '^':
            records.append(rec)
            rec = None
            continue
        code, val = line[0], js_trim(line[1:])
        if code not in rec['fields']:
            rec['fields'][code] = val
    if rec is not None and rec['fields']:
        records.append(rec)
    if options.get('dateOrder'):
        date_order = options['dateOrder']
    else:
        info = detect_date_order([_qif_date(r['fields'].get('D', '')) for r in records])
        date_order = info['order']
        if info['ambiguous']:
            result['warnings'].append(WARN_AMBIGUOUS)
    for r in records:
        result['rowCount'] += 1
        f = r['fields']
        raw = ' | '.join(k + f[k] for k in js_keys(f))[:160]
        if not f.get('D'):
            result['skipped'].append({'line': r['line'], 'reason': 'No date in this record', 'raw': raw})
            continue
        day = parse_date(_qif_date(f['D']), date_order)
        if day is None:
            result['skipped'].append({'line': r['line'], 'reason': 'Could not read the date "' + f['D'][:30] + '"', 'raw': raw})
            continue
        at = f['T'] if 'T' in f else f.get('U')
        amount = parse_amount(at)
        if amount is None:
            reason = ('Could not read the amount "' + at[:20] + '"') if at else 'No amount in this record'
            result['skipped'].append({'line': r['line'], 'reason': reason, 'raw': raw})
            continue
        if amount == 0:
            result['skipped'].append({'line': r['line'], 'reason': 'A zero amount, so nothing was paid', 'raw': raw})
            continue
        desc = _SPACES.sub(' ', f.get('P') or f.get('M') or '(no description)')
        number = f.get('N') or ''
        result['transactions'].append({'day': day, 'amount': amount, 'desc': desc,
                                       'memo': _SPACES.sub(' ', f.get('M') or '') if f.get('P') else '',
                                       'type': number if number and not _ALL_DIGITS.search(number) else '',
                                       'category': f.get('L') or '', 'account': result['account'],
                                       'source': result['name'], 'line': r['line']})
    if not result['rowCount']:
        result['error'] = 'This QIF file has no transactions in it.'
        finish_range(result)
        return result
    result['layout'] = {'format': 'qif', 'description': 'a QIF file (the Quicken interchange format), with dates from D ('
                        + ('month first' if date_order == 'MDY' else 'day first') + '), amounts from T and payees from P',
                        'mapping': None, 'headers': None, 'dateOrder': date_order}
    result['ok'] = len(result['transactions']) > 0
    if not result['ok']:
        result['error'] = 'No payments could be read from this file. The records it skipped are listed with reasons.'
    finish_range(result)
    return result


_OFX_HEADER = js_regex(r'^\s*OFXHEADER\s*:', 'i')
_OFX_XML = js_regex(r'^\s*<\?xml[^>]*>\s*<\?OFX', 'i')
_OFX_START = js_regex(r'^\s*<OFX>', 'i')
_OFX_TAG = js_regex(r'<OFX>', 'i')
_OFX_TRN = js_regex(r'<STMTTRN>', 'i')
_QIF_HEADER = js_regex(r'^\s*!(Type|Account|Option)', 'i')
_QIF_SHAPE = js_regex(r'^\s*D[^\r\n]+\r?\n(?:[A-Z][^\r\n]*\r?\n)*?T-?[\d.,]+\r?\n')
_QIF_END = js_regex(r'\n\^')


def sniff_format(text):
    """What kind of file this is, from its content rather than its name."""
    full = strip_bom(text_or(text))
    head = full[:4000]
    if (_OFX_HEADER.search(head) or _OFX_XML.search(head) or _OFX_START.search(head)
            or (_OFX_TAG.search(head) and _OFX_TRN.search(text_or(text)))):
        return 'ofx'
    if _QIF_HEADER.search(head):
        return 'qif'
    if _QIF_SHAPE.search(head) and _QIF_END.search(head):
        return 'qif'
    return 'csv'


def parse_statement(text, name=None, options=None):
    """Read any supported file: delimited text (CSV, TSV, pasted tables), OFX or QIF."""
    fmt = sniff_format(text)
    if fmt == 'ofx':
        return parse_ofx(text, name, options)
    if fmt == 'qif':
        return parse_qif(text, name, options)
    return parse_csv(text, name, options)
