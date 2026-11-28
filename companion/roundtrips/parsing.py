"""Reading fills exports: delimited text, the header row, and each row as a fill, a fee or a reason it was set aside.

This mirrors readExport and its helpers in the browser model line for line.
"""

import re

from .common import (DAY, cmp, detect_date_order, date_shape, parse_cents, parse_date_time, parse_float_text, parse_time,
                     read_number, rnd, rx, s, scaled, sort_by, trim)


def sniff_delimiter(text):
    lines = [l for l in re.split(r'\r\n|\n|\r', _strip_bom(s(text))) if trim(l) != ''][:25]
    best, best_score = ',', -1
    for d in [',', ';', '\t', '|']:
        lines_with = total = 0
        for line in lines:
            n, q = 0, False
            for c in line:
                if c == '"':
                    q = not q
                elif c == d and not q:
                    n += 1
            if n > 0:
                lines_with += 1
            total += n
        score = lines_with * 100000 + total
        if score > best_score:
            best, best_score = d, score
    return best


def _strip_bom(text):
    return text[1:] if text.startswith('\ufeff') else text


def parse_delimited(text, delim):
    """Rows of cells, with the line each row starts on."""
    src = _strip_bom(s(text))
    rows, lines, row, cell, in_q, line, row_line, i, n, quoted = [], [], [], '', False, 1, 1, 0, len(src), False
    while i < n:
        c = src[i]
        if in_q:
            if c == '"':
                if i + 1 < n and src[i + 1] == '"':
                    cell += '"'
                    i += 2
                    continue
                in_q = False
                i += 1
                continue
            if c == '\r' or c == '\n':
                line += 1
                if c == '\r' and i + 1 < n and src[i + 1] == '\n':
                    cell += '\n'
                    i += 2
                    continue
            cell += c
            i += 1
            continue
        if c == '"' and cell == '' and not quoted:
            in_q = True
            quoted = True
            i += 1
            continue
        if c == delim:
            row.append(cell)
            cell, quoted = '', False
            i += 1
            continue
        if c == '\r' or c == '\n':
            row.append(cell)
            rows.append(row)
            lines.append(row_line)
            row, cell, quoted = [], '', False
            if c == '\r' and i + 1 < n and src[i + 1] == '\n':
                i += 1
            i += 1
            line += 1
            row_line = line
            continue
        cell += c
        i += 1
    if cell != '' or row or quoted:
        row.append(cell)
        rows.append(row)
        lines.append(row_line)
    return {'rows': rows, 'lines': lines}


_PAREN = rx(r'\([^)]*\)')
_NONALNUM = rx(r'[^a-z0-9]+')
_EDGE_SPACES = rx(r'^ +| +$')


def norm_header(text):
    return _EDGE_SPACES.sub('', _NONALNUM.sub(' ', _PAREN.sub(' ', trim(text).lower())))


FIELDS = [
    ['date', ['date time', 'datetime', 'date and time', 'trade date time', 'execution date time', 'fill date time', 'timestamp', 'trade date', 'execution date', 'fill date', 'transaction date', 'deal date', 'order date', 'date', 'trade time', 'execution time', 'exec time', 'fill time', 'filled time', 'time']],
    ['time', ['time', 'trade time', 'execution time', 'exec time', 'fill time', 'filled time', 'time of trade', 'deal time']],
    ['symbol', ['symbol', 'ticker', 'instrument', 'contract', 'instrument code', 'ticker symbol', 'stock', 'security', 'epic', 'product', 'underlying', 'stock code', 'security code', 'name']],
    ['qty', ['filled qty', 'filled quantity', 'fill qty', 'fill quantity', 'exec qty', 'executed qty', 'executed quantity', 'quantity filled', 'qty filled', 'filled', 'quantity', 'qty', 'shares', 'no of shares', 'number of shares', 'contracts', 'lots', 'units', 'size', 'volume', 'amount of shares']],
    ['price', ['avg fill price', 'average fill price', 'fill price', 'filled price', 'execution price', 'exec price', 'trade price', 't price', 'deal price', 'avg price', 'average price', 'price', 'share price', 'unit price', 'price per share', 'avg fill', 'execution px', 'px']],
    ['side', ['side', 'action', 'buy sell', 'b s', 'bs', 'buy or sell', 'direction', 'order side', 'trade side', 'transaction type', 'trade type', 'deal type', 'order action', 'type', 'activity', 'operation', 'transaction']],
    ['fees', ['total fees', 'total costs', 'total charges', 'commission', 'commissions', 'comm', 'comm fee', 'comm fees', 'commission fee', 'fee', 'fees', 'charges', 'charge', 'costs', 'brokerage', 'stamp duty', 'ptm levy', 'sec fee', 'taf fee', 'finra fee', 'exchange fee', 'exchange fees', 'reg fee', 'regulatory fee', 'regulatory fees', 'clearing fee', 'clearing fees', 'nfa fee', 'transaction fee', 'transaction fees', 'fx fee', 'other fees', 'platform fee', 'ib commission', 'ecn fee', 'routing fee']],
    ['currency', ['currency', 'ccy', 'curr', 'currency code', 'trade currency', 'settlement currency', 'price currency']],
    ['account', ['account', 'account id', 'account number', 'account no', 'account name', 'acct', 'acct id', 'account code', 'portfolio', 'sub account', 'trader', 'book']],
    ['mult', ['multiplier', 'mult', 'contract multiplier', 'point value', 'value per point', 'contract size']],
    ['status', ['status', 'order status', 'fill status', 'state', 'order state']],
    ['orderId', ['order id', 'order', 'order number', 'order no', 'order ref', 'order reference', 'orderid', 'parent order id']],
    ['execId', ['exec id', 'execution id', 'fill id', 'trade id', 'transaction id', 'deal id', 'deal reference', 'trade ref', 'trade reference', 'ticket', 'trade number', 'trade no', 'contract note', 'contract note number', 'reference', 'ref']],
    ['openClose', ['open close', 'o c', 'oc', 'position effect', 'effect', 'opening closing', 'open or close']],
    ['asset', ['asset category', 'asset class', 'security type', 'sec type', 'instrument type', 'asset type', 'product type']],
    ['recordType', ['record type', 'type', 'transaction type', 'activity', 'activity type', 'entry type', 'category', 'transaction']],
    ['amount', ['proceeds', 'net amount', 'net proceeds', 'consideration', 'amount', 'value', 'net value', 'total', 'net', 'cash']],
    ['description', ['description', 'security name', 'instrument name', 'name', 'details']],
]
FEE_TOTALS = ['total fees', 'total costs', 'total charges']


def header_candidates(cells):
    norm = [norm_header(c) for c in cells]
    out = {}
    for field, names in FIELDS:
        found = []
        for name in names:
            for i, h in enumerate(norm):
                if h == name and i not in found:
                    found.append(i)
        out[field] = found
    return {'norm': norm, 'cand': out}


_SIDE_CLEAN = rx(r'[^a-z]+')
_SIDE_RULES = [
    (rx(r' (sell short|short sell|sell to open|sto|ss|short|sell open|open short|short open) '), 'S', 'open'),
    (rx(r' (buy to cover|buy cover|cover|btc|buy to close|close short|buy close) '), 'B', 'close'),
    (rx(r' (sell to close|stc|close long|sell close) '), 'S', 'close'),
    (rx(r' (buy to open|bto|open long|buy open) '), 'B', 'open'),
    (rx(r' (buy|bought|bot|b|long|purchase|purchased) '), 'B', ''),
    (rx(r' (sell|sold|sld|s|sale) '), 'S', ''),
]


def classify_side(text):
    t = ' ' + _SIDE_CLEAN.sub(' ', trim(text).lower()) + ' '
    if not trim(t):
        return None
    for pattern, side, intent in _SIDE_RULES:
        if pattern.search(t):
            return {'side': side, 'intent': intent}
    return None


FEE_TYPE = rx(r'\b(fee|fees|commission|commissions|charge|charges|levy|stamp|exchange|regulatory|clearing|platform|data|nfa|sec|finra|ptm)\b')
NON_TRADE = rx(r'\b(dividend|dividends|interest|deposit|deposits|withdrawal|withdrawals|transfer|transfers|funding|adjustment|journal|rebate|split|corporate|coupon|tax|withholding|conversion|fx)\b')
TRADE_TYPE = rx(r'\b(trade|trades|fill|fills|execution|executions|order|buy|sell|bought|sold)\b')

_ST_FILLED = rx(r'fill|execut|done|complete|match|\bok\b|settled')
_ST_WORKING = rx(r'pending|working|open|active|submitted|placed|new')
_ST_NOT = rx(r'delete|void|inactive|unfilled|not filled')


def status_reason(text):
    t = trim(text).lower()
    if not t:
        return ''
    if _ST_FILLED.search(t):
        return ''
    if 'cancel' in t:
        return 'order cancelled, nothing filled'
    if 'reject' in t:
        return 'order rejected, nothing filled'
    if 'expire' in t:
        return 'order expired, nothing filled'
    if _ST_WORKING.search(t):
        return 'order still working, nothing filled yet'
    if _ST_NOT.search(t):
        return 'order not filled'
    return ''


_TOTAL = rx(r'^(grand\s+)?(sub\s*)?totals?\b|^sum\b|^net total\b')


def is_total_row(cells):
    for i in range(min(len(cells), 4)):
        c = trim(cells[i]).lower()
        if not c:
            continue
        return bool(_TOTAL.search(c))
    return False


_EXT = rx(r'\.[A-Za-z0-9]{1,5}$')
_DATE_IN_NAME = rx(r'\d{4}[-_.]?\d{2}[-_.]?\d{2}')
_WEEK_IN_NAME = rx(r'\b(wk|week)\s*\d+\b', re.I)
_SEPARATORS = rx(r'[_\-.]+')
_NUMBERS = rx(r'\b\d+\b')
_RUNS = rx(r'\s+')


def clean_account_name(name):
    t = _EXT.sub('', trim(name), count=1)
    t = _SEPARATORS.sub(' ', _WEEK_IN_NAME.sub(' ', _DATE_IN_NAME.sub(' ', t)))
    t = _RUNS.sub(' ', _NUMBERS.sub(' ', t))
    t = trim(t)
    if not t:
        return 'Main account'
    return t[0].upper() + t[1:]


_ROOT = rx(r'^([A-Z0-9]{1,4}?)\s?([FGHJKMNQUVXZ])(\d{1,2})$')
_ROOT_MONTH = rx(r'^([A-Z0-9]{1,4})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}$')
_LETTER = rx(r'[A-Z]')


def symbol_root(symbol):
    t = trim(symbol).upper()
    m = _ROOT.match(t)
    if m and _LETTER.search(m.group(1)):
        return m.group(1)
    m = _ROOT_MONTH.match(t)
    if m:
        return m.group(1)
    return ''


def cell(cells, i):
    if i is None or i < 0 or i >= len(cells):
        return ''
    return trim(cells[i])


_JSONISH = rx(r'^\s*[{\[]')
_JSON_KEYS = re.compile(r'"(fills|journal|app)"')
_BINARY = re.compile('^%PDF|^PK\u0003\u0004')
_HEADER_DATA = rx(r'^(header|data)$', re.I)
_TRADES = rx(r'^trades?$', re.I)
_SECTION_ROW = rx(r'^(header|data|subtotal|total)$', re.I)
_DATA = rx(r'^data$', re.I)
_HEADER = rx(r'^header$', re.I)
_PENCE_HEADER = rx(r'\(\s*(p|pence|gbx)\s*\)|\bpence\b|\bgbx\b', re.I)
_GBP = rx(r'£|\bgbp\b', re.I)
_USD = rx(r'\$|\busd\b', re.I)
_EUR = rx(r'€|\beur\b', re.I)
_NONZERO = rx(r'[1-9]')
_OPEN = rx(r'^(o|open|opening|to open)\b')
_CLOSE = rx(r'^(c|close|closing|to close)\b')


def read_export(name, text, opts=None):
    """Read one export: its fills, separate fee rows, the rows set aside with reasons, and notes."""
    opts = opts or {}
    out = {
        'name': s(name), 'ok': False, 'error': '', 'delimiter': '', 'headerLine': 0, 'columns': {}, 'dateOrder': '', 'dateNote': '',
        'account': '', 'fills': [], 'fees': [], 'skipped': [], 'notes': [], 'counts': {'rows': 0, 'blank': 0, 'fills': 0, 'fees': 0, 'skipped': 0},
    }
    src = s(text)
    if not trim(src):
        out['error'] = 'The file is empty.'
        return out
    if _JSONISH.search(src) and _JSON_KEYS.search(src[:400]):
        out['error'] = 'This looks like a saved journal file: use Open journal file instead.'
        return out
    if _BINARY.search(src[:8]):
        out['error'] = 'This is not a text export (it looks like a PDF or a spreadsheet). Save it as CSV first.'
        return out
    delim = sniff_delimiter(src)
    out['delimiter'] = delim
    parsed = parse_delimited(src, delim)
    rows, lines = parsed['rows'], parsed['lines']
    sectioned = len([r for r in rows if _HEADER_DATA.match(trim(r[1] if len(r) > 1 else ''))]) > len(rows) / 2
    if sectioned:
        keep_rows, keep_lines = [], []
        for i, r in enumerate(rows):
            c0, c1 = trim(r[0] if r else ''), trim(r[1] if len(r) > 1 else '')
            if _TRADES.match(c0) and _SECTION_ROW.match(c1):
                keep_rows.append(r[2:] if (_DATA.match(c1) or _HEADER.match(c1)) else ['Total'] + r[3:])
                keep_lines.append(lines[i])
        rows, lines = keep_rows, keep_lines
        out['notes'].append('Read the Trades section of a sectioned statement.')
    hi, hc = -1, None
    for r in range(min(len(rows), 40)):
        c = header_candidates(rows[r])
        has_date = len(c['cand']['date']) > 0 or len(c['cand']['time']) > 0
        if has_date and c['cand']['symbol'] and c['cand']['qty'] and c['cand']['price']:
            hi, hc = r, c
            break
    if hi < 0:
        first = ', '.join([x for x in rows[0] if trim(x) != ''][:8]) if rows else ''
        out['error'] = 'Could not find a header row with date, symbol, quantity and price columns' + (' (the first row reads: ' + first + ')' if first else '') + '.'
        return out
    out['headerLine'] = lines[hi]
    if hi > 0:
        out['notes'].append('%d %s above the header were ignored.' % (hi, 'line' if hi == 1 else 'lines'))
    header = rows[hi]
    body = rows[hi + 1:]
    body_lines = lines[hi + 1:]

    used, col = {}, {}

    def take(field, lst):
        for i in lst:
            if i not in used:
                used[i] = True
                col[field] = i
                return i
        return -1

    cand = hc['cand']

    def values(i):
        v = []
        for row in body:
            if len(v) >= 200:
                break
            x = cell(row, i)
            if x:
                v.append(x)
        return v

    def looks_like_dates(i):
        v = values(i)
        ok = len([x for x in v if parse_date_time(x, 'DMY') or parse_date_time(x, 'MDY')])
        return len(v) > 0 and ok >= len(v) * 0.5

    date_list = [i for i in cand['date'] if looks_like_dates(i)]
    if not date_list:
        date_list = cand['date'][:1]
    take('date', date_list)

    def looks_like_times(i):
        v = values(i)
        return bool(v) and len([x for x in v if parse_time(x) is not None]) >= len(v) * 0.5

    take('time', [i for i in cand['time'] if looks_like_times(i)])
    take('symbol', cand['symbol'])
    take('qty', cand['qty'])
    take('price', cand['price'])

    def looks_like_sides(i):
        v = values(i)
        return bool(v) and len([x for x in v if classify_side(x)]) >= len(v) * 0.5

    take('side', [i for i in cand['side'] if looks_like_sides(i)])
    fee_total = [i for i in cand['fees'] if hc['norm'][i] in FEE_TOTALS]
    fee_cols = []
    for i in (fee_total[:1] if fee_total else cand['fees']):
        if i not in used:
            used[i] = True
            fee_cols.append(i)
    for f in ['currency', 'account', 'mult', 'status', 'orderId', 'execId', 'openClose', 'asset', 'recordType', 'amount', 'description']:
        take(f, cand[f])
    if 'symbol' not in col and 'description' in col:
        col['symbol'] = col['description']
    for f in col:
        out['columns'][f] = trim(header[col[f]])
    if fee_cols:
        out['columns']['fees'] = ' + '.join(trim(header[i]) for i in fee_cols)

    pence_col = 'price' in col and bool(_PENCE_HEADER.search(header[col['price']]))
    header_cur = ''
    for h in header:
        if _GBP.search(h):
            header_cur = header_cur or 'GBP'
        elif _USD.search(h):
            header_cur = header_cur or 'USD'
        elif _EUR.search(h):
            header_cur = header_cur or 'EUR'
    decimal_comma = delim == ';'

    date_vals = values(col.get('date'))
    detected = detect_date_order(date_vals)
    wanted = opts.get('dateOrder') if opts.get('dateOrder') in ('DMY', 'MDY') else 'auto'
    if wanted != 'auto':
        order = wanted
        out['dateNote'] = 'Dates read ' + ('day first' if order == 'DMY' else 'month first') + ', as set.'
    elif detected in ('DMY', 'MDY'):
        order = detected
        out['dateNote'] = 'Dates read ' + ('day first (UK style)' if order == 'DMY' else 'month first (US style)') + ': some days are over 12.'
    else:
        order = 'DMY'
        numeric = any(date_shape(v) for v in date_vals)
        if detected == 'MIXED':
            out['dateNote'] = 'Dates are written both ways in this file; read day first. Check the dates.'
        elif numeric:
            out['dateNote'] = 'Dates could be day first or month first (no day is over 12); read day first (UK style). Change this if they are US dates.'
    out['dateOrder'] = order

    fee_sign = []
    for i in fee_cols:
        neg = pos = 0
        for x in values(i):
            n = read_number(x, decimal_comma)
            if n and (n['int'] != '0' or _NONZERO.search(n['frac'])):
                if n['neg']:
                    neg += 1
                else:
                    pos += 1
        fee_sign.append(-1 if neg > pos else 1)
    signed_qty = False
    for x in values(col.get('qty')):
        n = read_number(x, decimal_comma)
        if n and n['neg']:
            signed_qty = True
            break

    default_account = trim(opts.get('account')) or clean_account_name(name)
    header_norm = '|'.join(norm_header(h) for h in header)
    accounts = {}

    def skip(k, reason):
        out['skipped'].append({'line': body_lines[k], 'reason': reason, 'text': ', '.join(x for x in (trim(c) for c in body[k]) if x != '')[:140]})

    g = col.get
    for k, cells in enumerate(body):
        if not any(trim(x) != '' for x in cells):
            out['counts']['blank'] += 1
            continue
        out['counts']['rows'] += 1
        if '|'.join(norm_header(c) for c in cells) == header_norm:
            skip(k, 'repeated header row')
            continue
        if is_total_row(cells):
            skip(k, 'total row, not a fill')
            continue
        sr = status_reason(cell(cells, g('status')))
        if sr:
            skip(k, sr)
            continue
        account = cell(cells, g('account')) if g('account') is not None and cell(cells, g('account')) else default_account
        symbol = cell(cells, g('symbol')).upper()
        side_text = cell(cells, g('side'))
        type_text = cell(cells, g('recordType')).lower()
        side = classify_side(side_text) if side_text else None
        qty_num = read_number(cell(cells, g('qty')), decimal_comma)
        qty_zero = not qty_num or scaled(qty_num, 6) == 0
        price_text = cell(cells, g('price'))
        kind = ''
        if type_text and not TRADE_TYPE.search(type_text):
            if FEE_TYPE.search(type_text) and not NON_TRADE.search(type_text):
                kind = 'fee'
            elif NON_TRADE.search(type_text):
                kind = 'other'
        elif not type_text and side_text and not side:
            st = side_text.lower()
            if FEE_TYPE.search(st) and not NON_TRADE.search(st):
                kind = 'fee'
            elif NON_TRADE.search(st):
                kind = 'other'
            else:
                skip(k, 'buy or sell not recognised: ' + side_text)
                continue
        if kind == 'fee' and qty_zero and not price_text:
            fee_amt, any_fee = 0, False
            for j, i in enumerate(fee_cols):
                v = parse_cents(cell(cells, i), decimal_comma)
                if v is not None:
                    fee_amt += v * fee_sign[j]
                    any_fee = True
            if not any_fee and g('amount') is not None:
                av = parse_cents(cell(cells, g('amount')), decimal_comma)
                if av is not None:
                    fee_amt = -av if av < 0 else av
                    any_fee = True
            if not any_fee or fee_amt == 0:
                skip(k, 'fee row without an amount')
                continue
            fdt = parse_date_time(cell(cells, g('date')), order)
            if fdt and fdt['sec'] is None and g('time') is not None:
                fdt['sec'] = parse_time(cell(cells, g('time')))
            out['fees'].append({
                'account': account, 'symbol': symbol, 'day': fdt['day'] if fdt else None, 'sec': fdt['sec'] if fdt else None, 'amount': fee_amt,
                'orderId': cell(cells, g('orderId')), 'label': trim(type_text or side_text).lower() or 'fee', 'line': body_lines[k],
            })
            accounts[account] = True
            out['counts']['fees'] += 1
            continue
        if kind:
            skip(k, 'not a trade (' + trim(type_text or side_text) + ')')
            continue
        if not symbol:
            skip(k, 'no symbol')
            continue
        dt = parse_date_time(cell(cells, g('date')), order)
        if not dt:
            skip(k, 'date not recognised: ' + cell(cells, g('date')) if cell(cells, g('date')) else 'no date')
            continue
        if dt['sec'] is None and g('time') is not None and cell(cells, g('time')):
            tm = parse_time(cell(cells, g('time')))
            if tm is None:
                skip(k, 'time not recognised: ' + cell(cells, g('time')))
                continue
            dt['sec'] = tm
        if not qty_num:
            skip(k, 'quantity not recognised: ' + cell(cells, g('qty')) if cell(cells, g('qty')) else 'no quantity')
            continue
        q = scaled(qty_num, 6)
        if q == 0:
            skip(k, 'quantity is zero, nothing filled')
            continue
        intent = ''
        if side:
            intent = side['intent']
        elif side_text:
            skip(k, 'buy or sell not recognised: ' + side_text)
            continue
        elif q < 0 or signed_qty:
            side = {'side': 'S' if q < 0 else 'B', 'intent': ''}
        elif g('amount') is not None and read_number(cell(cells, g('amount')), decimal_comma):
            amt = read_number(cell(cells, g('amount')), decimal_comma)
            side = {'side': 'B' if amt['neg'] else 'S', 'intent': ''}
        else:
            skip(k, 'cannot tell a buy from a sell (no side column and the quantity has no sign)')
            continue
        if q < 0:
            q = -q
        oc = cell(cells, g('openClose')).lower()
        if _OPEN.search(oc):
            intent = 'open'
        elif _CLOSE.search(oc):
            intent = 'close'
        pn = read_number(price_text, decimal_comma)
        if not pn:
            skip(k, 'price not recognised: ' + price_text if price_text else 'no price')
            continue
        if pn['neg']:
            skip(k, 'negative price: ' + price_text)
            continue
        currency = cell(cells, g('currency')).upper() or pn['cur'] or header_cur or ''
        price = scaled(pn, 6)
        if pence_col or pn['pence'] or currency == 'GBX' or cell(cells, g('currency')) == 'GBp':
            price = rnd(price / 100)
            currency = 'GBP'
        fee = 0
        for fj, i in enumerate(fee_cols):
            fv = parse_cents(cell(cells, i), decimal_comma)
            if fv is not None:
                fee += fv * fee_sign[fj]
            if not currency:
                fn = read_number(cell(cells, i), decimal_comma)
                if fn and fn['cur']:
                    currency = fn['cur']
        mult_text = cell(cells, g('mult'))
        mult = parse_float_text(mult_text) if mult_text else None
        if mult is not None and not (mult > 0):
            mult = None
        if mult is not None and mult == int(mult) and mult < 2 ** 53:
            mult = int(mult)
        asset_text = cell(cells, g('asset')).lower()
        out['fills'].append({
            'key': '', 'account': account, 'symbol': symbol, 'day': dt['day'], 'sec': dt['sec'], 'side': side['side'], 'intent': intent,
            'q': q, 'price': price, 'fee': fee, 'currency': currency or trim(opts.get('base')) or 'USD', 'mult': mult,
            'orderId': cell(cells, g('orderId')), 'execId': cell(cells, g('execId')),
            'asset': 'future' if 'fut' in asset_text else ('option' if 'opt' in asset_text else ''),
            'file': out['name'], 'line': body_lines[k],
        })
        accounts[account] = True
        out['counts']['fills'] += 1
    out['counts']['skipped'] = len(out['skipped'])
    fills = out['fills']
    up = down = 0
    for z in range(1, len(fills)):
        ta = fills[z - 1]['day'] * DAY + (fills[z - 1]['sec'] or 0)
        tb = fills[z]['day'] * DAY + (fills[z]['sec'] or 0)
        if tb > ta:
            up += 1
        elif tb < ta:
            down += 1
    if down > up:
        fills.reverse()
        out['notes'].append('Rows were listed newest first; read oldest first.')
    markers = any((f['side'] == 'S' and f['intent'] == 'open') or (f['side'] == 'B' and f['intent'] == 'close') for f in fills)
    if markers:
        for f in fills:
            if f['side'] == 'S' and f['intent'] == '':
                f['intent'] = 'close'
    _content_keys(fills)
    seen_fee = {}
    for e in out['fees']:
        base = '|'.join(['e', e['account'], e['symbol'], '' if e['day'] is None else str(e['day']), '' if e['sec'] is None else str(e['sec']),
                         str(e['amount']), e['orderId'], e['label']])
        seen_fee[base] = seen_fee.get(base, 0) + 1
        e['key'] = base + '#' + str(seen_fee[base])
    out['account'] = ', '.join(sort_by(list(accounts), cmp))
    if not fills and not out['fees']:
        out['error'] = 'No fills could be read from this file.'
        return out
    if any(f['sec'] is None for f in fills):
        out['notes'].append('Some fills have no time of day, so holding times for them are in whole days.')
    out['ok'] = True
    return out


def _content_key(f):
    return '|'.join(['f', f['account'], f['symbol'], str(f['day']), '' if f['sec'] is None else str(f['sec']), f['side'], str(f['q']), str(f['price'])])


def _content_keys(fills):
    """Keys that let the same fill be recognised in next week's export: the execution ID, else the fill's content."""
    seen = {}
    for f in fills:
        if f['execId']:
            f['key'] = 'x|' + f['account'] + '|' + f['symbol'] + '|' + f['execId']
            continue
        base = _content_key(f)
        seen[base] = seen.get(base, 0) + 1
        f['key'] = base + '#' + str(seen[base])
    counts = {}
    for f in fills:
        if f['key'][:1] == 'x':
            counts[f['key']] = counts.get(f['key'], 0) + 1
    if any(n > 1 for n in counts.values()):
        seen = {}
        for f in fills:
            base = _content_key(f)
            seen[base] = seen.get(base, 0) + 1
            f['key'] = base + '#' + str(seen[base])
