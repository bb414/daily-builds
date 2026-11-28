"""The files the tool hands back: the register and budget spreadsheets, the calendar,
the template and the saved review.

Every file is byte-for-byte what the browser app writes: CSV files start with
a byte order mark and use CRLF line ends, calendar lines are folded at 75
bytes, and the saved review is JSON.stringify(review, null, 1).
"""

import json
import math

from .common import is_number, js_keys, js_regex, js_string, js_stringify, money, pad2, plain_money, \
    round_half_up, slug, text_or, truthy
from .dates import MONTH_NAMES, day_from_ymd, days_in_month, from_iso, iso, long_date, short_date, ymd
from .detect import CADENCE_BY_ID, clean_added
from .parsing import strip_bom
from .payees import CATEGORIES, CATEGORY_BY_ID, category_of
from .planning import DECISIONS, forecast, plan

DECISION_LABELS = {'keep': 'Keep', 'cancel': 'Cancel', 'review': 'Review', 'ignore': 'Not a cost'}

def _or(v, fallback):
    """v || fallback, with JavaScript truthiness."""
    return v if truthy(v) else fallback


_NEEDS_QUOTES = js_regex(r'[",\r\n]')
_SPACE_AT_END = js_regex(r'^\s|\s$')


def csv_cell(v):
    """One CSV cell, quoted when it holds a quote, comma, line break or space at either end."""
    s = '' if v is None else js_string(v)
    if _NEEDS_QUOTES.search(s) or _SPACE_AT_END.search(s):
        return '"' + s.replace('"', '""') + '"'
    return s


def to_csv(rows):
    """Rows of cells as CSV text, with a byte order mark so spreadsheets read the £ sign."""
    return '\ufeff' + '\r\n'.join(','.join(csv_cell(c) for c in r) for r in rows) + '\r\n'


REGISTER_HEADERS = ['Name', 'Category', 'Paid by', 'How often', 'Typical amount', 'Monthly equivalent', 'Yearly cost',
                    'Payments seen', 'First seen', 'Last seen', 'Next due', 'Status', 'Confidence', 'Checks',
                    'Decision', 'Note', 'Accounts']


def register_csv(result, decisions=None):
    """The register of regular payments as CSV."""
    decisions = decisions or {}
    rows = [REGISTER_HEADERS]
    for s in result['series']:
        d = decisions.get(s['id']) or {}
        decision = d.get('decision')
        rows.append([
            s['name'], category_of(s['category'])['label'], s['method'], CADENCE_BY_ID[s['cadence']]['label'],
            plain_money(s['typical']), plain_money(s['monthly']), plain_money(s['annual']), s['count'],
            iso(s['first']) if s['first'] is not None else '', iso(s['last']) if s['last'] is not None else '', iso(s['nextDue']) if s['nextDue'] is not None else '', s['status'],
            s['confidence'], ' '.join(f['text'] for f in s['flags']),
            DECISION_LABELS.get(decision, '') if truthy(decision) else '', _or(d.get('note'), ''), s['account'],
        ])
    return to_csv(rows)


def budget_months(as_of, months):
    """The YYYY-MM keys of the months a budget covers, starting with the review month."""
    y, m, _ = ymd(as_of)
    keys = []
    for i in range(months):
        total = y * 12 + m - 1 + i
        keys.append(str(total // 12) + '-' + pad2(total % 12 + 1))
    return keys


def budget_csv(result, decisions=None, months=12):
    """Committed spending by month and category for the coming months, for a spreadsheet."""
    months = months or 12
    decisions = decisions or {}
    keys = budget_months(result['asOf'], months)
    last_y, last_m = (int(x) for x in keys[-1].split('-'))
    until = day_from_ymd(last_y, last_m, days_in_month(last_y, last_m))
    cats, cat_order = {}, []
    for it in forecast(result, until - result['asOf'] + 1, decisions):
        if it['direction'] != 'out' or it['decision'] in ('cancel', 'ignore'):
            continue
        c = category_of(it['category'])
        if not c['cost']:
            continue
        if c['id'] not in cats:
            cats[c['id']] = {}
            cat_order.append(c['id'])
        y, m, _ = ymd(it['day'])
        k = str(y) + '-' + pad2(m)
        cats[c['id']][k] = cats[c['id']].get(k, 0) + it['amount']
    cat_order.sort(key=lambda cid: CATEGORIES.index(CATEGORY_BY_ID[cid]))
    rows = [['Category'] + [MONTH_NAMES[int(k[5:]) - 1][:3] + ' ' + k[:4] for k in keys] + ['Total']]
    col_totals = [0] * len(keys)
    for cid in cat_order:
        row, total = [CATEGORY_BY_ID[cid]['label']], 0
        for i, k in enumerate(keys):
            v = cats[cid].get(k, 0)
            total += v
            col_totals[i] += v
            row.append(plain_money(v))
        row.append(plain_money(total))
        rows.append(row)
    rows.append(['Total'] + [plain_money(v) for v in col_totals] + [plain_money(sum(col_totals))])
    return to_csv(rows)


def ics_escape(s):
    """Escape text for a calendar property value."""
    s = js_string(s).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
    return s.replace('\r\n', '\\n').replace('\n', '\\n')


def utf8_length(ch):
    """Bytes a character takes in UTF-8."""
    c = ord(ch)
    return 1 if c < 0x80 else 2 if c < 0x800 else 3 if c < 0x10000 else 4


def ics_fold(line):
    """Fold a content line at 75 bytes, as the calendar standard asks."""
    out, cur, size = [], '', 0
    for ch in line:
        b = utf8_length(ch)
        if size + b > 75:
            out.append(cur)
            cur, size = ' ', 1
        cur += ch
        size += b
    out.append(cur)
    return '\r\n'.join(out)


def ics_date(day):
    """A day number as YYYYMMDD."""
    return iso(day).replace('-', '')


def find_series(result, sid):
    """The series or income with an id, or None."""
    return next((s for s in result['series'] + result['income'] if s['id'] == sid), None)


def build_ics(result, decisions=None, days=92, include_income=False, reminders=True, details=None):
    """A calendar of upcoming payments, each with a reminder the evening before, plus cancel-by reminders.

    Returns {'text': calendar text, 'events': number of events}.
    """
    decisions = decisions or {}
    days = days or 92
    stamp = ics_date(result['asOf']) + 'T090000Z'
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Still paying//Regular payments//EN', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH', 'X-WR-CALNAME:Regular payments']
    items = forecast(result, days, decisions)
    actions = plan(result, decisions, details)['actions']
    cancel_ids = {a['id'] for a in actions}
    count = 0
    for it in items:
        if it['direction'] == 'in' and not include_income:
            continue
        if it['decision'] == 'ignore':
            continue
        s = find_series(result, it['id'])
        variable = s is not None and s['amounts']['kind'] == 'variable'
        label = 'Expected in: ' if it['direction'] == 'in' else ''
        amount_text = ('about ' if variable else '') + money(it['amount'])
        summary = label + amount_text + ' ' + it['name'] + (' (you plan to cancel)' if it['id'] in cancel_ids else '')
        parts = [CADENCE_BY_ID[s['cadence']]['label'] + ' payment'
                 + (' by ' + s['method'] if s['method'] != 'unknown' else '') + '.']
        if variable:
            parts.append('Recent payments ranged from ' + money(s['amounts']['min']) + ' to '
                         + money(s['amounts']['max']) + '.')
        parts.append('Found by Still paying from your bank export.')
        desc = ' '.join(parts)
        lines += ['BEGIN:VEVENT',
                  'UID:' + slug(it['id']) + '-' + ics_date(it['day']) + '@still-paying.local',
                  'DTSTAMP:' + stamp,
                  'DTSTART;VALUE=DATE:' + ics_date(it['day']),
                  'DTEND;VALUE=DATE:' + ics_date(it['day'] + 1),
                  'SUMMARY:' + ics_escape(summary),
                  'DESCRIPTION:' + ics_escape(desc),
                  'TRANSP:TRANSPARENT',
                  'CATEGORIES:' + ics_escape(category_of(it['category'])['label'])]
        if it['direction'] == 'out' and reminders is not False:
            lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + ics_escape(summary + ' leaves tomorrow'),
                      'TRIGGER:-PT15H', 'END:VALARM']
        lines.append('END:VEVENT')
        count += 1
    for a in actions:
        before = short_date(a['nextDue']) if a['nextDue'] is not None else 'the next payment'
        summary = 'Cancel ' + a['name'] + ' before ' + before
        desc = ' '.join(a['steps']) + ' Next payment ' + money(a['amount']) \
            + (' on ' + long_date(a['nextDue']) if a['nextDue'] is not None else '') + '.'
        lines += ['BEGIN:VEVENT',
                  'UID:cancel-' + slug(a['id']) + '-' + ics_date(a['cancelBy']) + '@still-paying.local',
                  'DTSTAMP:' + stamp,
                  'DTSTART;VALUE=DATE:' + ics_date(a['cancelBy']),
                  'DTEND;VALUE=DATE:' + ics_date(a['cancelBy'] + 1),
                  'SUMMARY:' + ics_escape(summary),
                  'DESCRIPTION:' + ics_escape(desc),
                  'BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + ics_escape(summary), 'TRIGGER:PT9H', 'END:VALARM',
                  'END:VEVENT']
        count += 1
    lines.append('END:VCALENDAR')
    return {'text': '\r\n'.join(ics_fold(line) for line in lines) + '\r\n', 'events': count}


TEMPLATE_ROWS = [
    ['Date', 'Description', 'Type', 'Amount', 'Balance'],
    ['01/11/2026', 'HARBOUR LETTINGS RENT', 'Standing order', '-525.00', '812.40'],
    ['03/11/2026', 'IRONWORKS GYM', 'Card payment', '-24.99', '787.41'],
    ['12/11/2026', 'BRIGHTSPARK ENERGY', 'Direct debit', '-58.20', '729.21'],
    ['27/11/2026', 'CAMPUS CAFE PAYROLL', 'Bank credit', '412.50', '1141.71'],
]


def template_csv():
    """A template showing the layout that always reads cleanly."""
    return to_csv(TEMPLATE_ROWS)


def project_file(state):
    """The saved review as JSON text, reopenable in the browser app.

    state holds transactions, result, decisions, accounts, aliases, names,
    manual, overrides, details and optionally reviewedOn (a day number).
    """
    tx = [[iso(t['day']), t['amount'], t['desc'], t.get('memo') or '', t.get('type') or '', t.get('category') or '',
           t['account']] for t in state['transactions']]
    result = state.get('result')
    known = {s['id']: {'typical': s['typical'], 'status': s['status'], 'name': s['name'], 'kind': s['amounts']['kind']}
             for s in (result['series'] if result else [])}
    decisions = {}
    given = _or(state.get('decisions'), {})
    for sid in js_keys(given):
        d = given[sid]
        decided = d.get('decidedOn')
        decisions[sid] = {'decision': _or(d.get('decision'), None), 'note': _or(d.get('note'), ''),
                          'decidedOn': iso(decided) if is_number(decided) else _or(decided, None),
                          'noticeDays': d.get('noticeDays')}
    reviewed = state['reviewedOn'] if state.get('reviewedOn') is not None else result['asOf']
    return js_stringify({
        'format': 'still-paying-review', 'version': 1, 'reviewedOn': iso(reviewed),
        'accounts': [{'account': a['account'], 'files': a['files']} for a in _or(state.get('accounts'), [])],
        'balances': balances_of(state.get('accounts')), 'transactions': tx, 'decisions': decisions, 'known': known, 'aliases': _or(state.get('aliases'), {}),
        'names': _or(state.get('names'), {}), 'manual': _or(state.get('manual'), []),
        'overrides': _or(state.get('overrides'), {}),
        'added': [{'id': a['id'], 'name': a['name'], 'amount': a['amount'], 'cadence': a['cadence'], 'next': iso(a['next']),
                   'method': a['method'], 'category': a['category'], 'account': a['account']}
                  for a in (clean_added(x) for x in (state.get('added') or [])) if a],
        'details': _or(state.get('details'), {}),
    })


def _reject_constant(name):
    raise ValueError(name)


def _item(row, i):
    """row[i] the JavaScript way for a saved transaction row: None when it is not there."""
    if isinstance(row, (list, str)) and i < len(row):
        return row[i]
    return None


def _newer_version(v):
    if is_number(v):
        return v > 1
    if isinstance(v, str):
        try:
            return float(v.strip() or '0') > 1
        except ValueError:
            return False
    return False


def balances_of(accounts):
    """Each account's latest balance, for the saved review."""
    return {a['account']: {'day': iso(a['closing']['day']), 'balance': a['closing']['balance']}
            for a in (accounts or []) if a.get('closing')}


def read_balances(raw):
    """Balances from a saved review, keeping only well-formed ones."""
    out = {}
    for k, b in (raw.items() if isinstance(raw, dict) else []):
        b = b if isinstance(b, dict) else {}
        day = from_iso(b.get('day'))
        bal = b.get('balance')
        if day is not None and isinstance(bal, (int, float)) and not isinstance(bal, bool) and math.isfinite(bal):
            out[k] = {'day': day, 'balance': round_half_up(bal)}
    return out


def read_project(text):
    """Read a saved review back.

    Returns reviewedOn, transactions, decisions, known, aliases, names,
    manual, overrides, details, accounts and badRows, or {'error': ...}.
    """
    try:
        data = json.loads(strip_bom(js_string(text)), parse_constant=_reject_constant)
    except ValueError:
        return {'error': 'This file is not a saved review (it is not valid JSON).'}
    if not isinstance(data, dict) or data.get('format') != 'still-paying-review':
        return {'error': 'This JSON file is not a Still paying review.'}
    if _newer_version(data.get('version')):
        return {'error': 'This review was saved by a newer version of the tool.'}
    tx, bad = [], 0
    rows = data.get('transactions')
    for i, r in enumerate(rows if isinstance(rows, list) else []):
        day = from_iso(_item(r, 0))
        amount = _item(r, 1)
        if day is None or not is_number(amount) or not math.isfinite(amount):
            bad += 1
            continue
        tx.append({'day': day, 'amount': round_half_up(amount), 'desc': text_or(_item(r, 2)),
                   'memo': text_or(_item(r, 3)), 'type': text_or(_item(r, 4)), 'category': text_or(_item(r, 5)),
                   'account': text_or(_item(r, 6), 'Account'), 'source': 'saved review', 'line': i + 1})
    decisions = {}
    saved = data.get('decisions')
    for sid in js_keys(saved) if isinstance(saved, dict) else []:
        d = saved[sid] if isinstance(saved[sid], dict) else {}
        if truthy(d.get('decision')) and d.get('decision') not in DECISIONS:
            continue
        entry = {'decision': _or(d.get('decision'), None), 'note': text_or(d.get('note')),
                 'decidedOn': from_iso(d['decidedOn']) if truthy(d.get('decidedOn')) else None}
        if is_number(d.get('noticeDays')):
            entry['noticeDays'] = d['noticeDays']
        decisions[sid] = entry
    return {'reviewedOn': from_iso(data.get('reviewedOn')), 'transactions': tx, 'decisions': decisions,
            'known': _or(data.get('known'), {}), 'aliases': _or(data.get('aliases'), {}),
            'names': _or(data.get('names'), {}), 'manual': _or(data.get('manual'), []),
            'overrides': _or(data.get('overrides'), {}), 'details': _or(data.get('details'), {}),
            'accounts': _or(data.get('accounts'), []), 'badRows': bad, 'balances': read_balances(data.get('balances')),
            'added': [a for a in (clean_added(x) for x in (data.get('added') if isinstance(data.get('added'), list) else [])) if a]}
