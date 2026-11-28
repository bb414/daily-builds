"""Files and the position-size calculator: the round-trip, breach and fills CSVs, the template and the journal file.

Mirrors positionSize, tradesCsv, breachesCsv, fillsCsv, templateCsv, projectFile and readProject in the
browser model, so the files the app and the companion write are byte for byte the same.
"""

import json
import math

from .common import (VERSION, cmp, fmt_num, fmt_price, fmt_qty, fmt_time, fmt_time_long, iso_stamp, money, parse_cents, parse_float_text,
                     parse_micro, plain_money, rnd, rx, s, sort_by, to_iso)
from .matching import RULES, clean_entry, empty_state, rule_label

_NEEDS_QUOTES = rx(r'[",\r\n]')
_EDGE_SPACE = rx(r'^\s|\s$')


def csv_cell(v):
    t = s(v)
    if _NEEDS_QUOTES.search(t) or _EDGE_SPACE.search(t):
        return '"' + t.replace('"', '""') + '"'
    return t


def csv_lines(rows):
    return '\ufeff' + '\r\n'.join(','.join(csv_cell(c) for c in r) for r in rows) + '\r\n'


def _mult_text(mult):
    t = fmt_num(mult, 4).replace(',', '')
    return rx(r'\.?0+$').sub('', t, count=1)


def trades_csv(result, trades=None):
    lst = result['trades'] if trades is None else trades
    base = result['settings']['base']
    rows = [['Trade ID', 'Account', 'Symbol', 'Direction', 'Status', 'Opened', 'Closed', 'Holding (minutes)', 'Max position', 'Entry orders', 'Exit orders',
             'Average entry', 'Average exit', 'Multiplier', 'Currency', 'Gross P&L', 'Fees', 'Net P&L', 'Net P&L (' + base + ')', 'Stop', 'Planned risk',
             'Max risk', 'R multiple', 'Setup', 'Mistakes', 'Rule breaches', 'Notes']]
    for t in lst:
        labels = []
        for b in t['breaches']:
            lab = rule_label(b)
            if lab not in labels:
                labels.append(lab)
        rows.append([
            t['id'], t['account'], t['symbol'], 'Long' if t['dir'] > 0 else 'Short', 'Closed' if t['status'] == 'closed' else 'Open',
            iso_stamp(t['openDay'], t['openSec']).replace('T', ' '), '' if t['closeDay'] is None else iso_stamp(t['closeDay'], t['closeSec']).replace('T', ' '),
            '' if t['holdSec'] is None else fmt_num(t['holdSec'] / 60, 1).replace(',', ''), fmt_qty(t['maxPos']).replace(',', ''), t['entryOrders'], t['exitOrders'],
            fmt_price(t['avgEntry']), fmt_price(t['avgExit']) if t['qtyOut'] else '', _mult_text(t['mult']), t['currency'],
            plain_money(t['gross']), plain_money(t['fees']), plain_money(t['net']), '' if t['netBase'] is None else plain_money(t['netBase']),
            '' if t['stop'] is None else fmt_price(t['stop']), '' if t['plannedRisk'] is None else plain_money(t['plannedRisk']),
            '' if t['maxRisk'] is None else plain_money(t['maxRisk']), '' if t['r'] is None else fmt_num(t['r'], 2), t['setup'], '; '.join(t['mistakes']),
            '; '.join(labels), t['notes'],
        ])
    return csv_lines(rows)


def breaches_csv(result, breaches=None):
    by_id = {t['id']: t for t in result['trades']}
    rows = [['Date', 'Time', 'Account', 'Symbol', 'Rule', 'What happened', 'Trade ID', 'Trade net P&L']]
    for b in result['breaches'] if breaches is None else breaches:
        t = by_id.get(b['trade']) if b['trade'] else None
        rows.append([to_iso(b['day']), fmt_time(b['sec']), b['account'], b['symbol'], b['label'], b['detail'], b['trade'],
                     plain_money(t['net']) if t and t['status'] == 'closed' else ''])
    return csv_lines(rows)


def fills_csv(result):
    rows = [['Date', 'Time', 'Account', 'Symbol', 'Side', 'Quantity', 'Price', 'Fees', 'Currency', 'Order ID', 'Trade ID', 'Role', 'File', 'Line']]
    for f in result['fills']:
        legs = result['legsByFill'].get(f['key'], [])
        rows.append([to_iso(f['day']), fmt_time_long(f['sec']), f['account'], f['symbol'], 'Buy' if f['side'] == 'B' else 'Sell', fmt_qty(f['q']).replace(',', ''),
                     fmt_price(f['price']), plain_money(result['feeOf'][f['key']]), f['currency'], f['orderId'], '; '.join(l['trade'] for l in legs),
                     '; '.join(l['role'] for l in legs) if legs else 'unmatched', f['file'], f['line']])
    return csv_lines(rows)


def template_csv():
    return csv_lines([
        ['Date', 'Time', 'Account', 'Symbol', 'Side', 'Quantity', 'Price', 'Commission', 'Currency', 'Order ID'],
        ['2026-11-23', '09:41:05', 'Challenge', 'HGRB', 'Buy', '300', '41.27', '1.50', 'USD', 'A-1001'],
        ['2026-11-23', '09:41:06', 'Challenge', 'HGRB', 'Buy', '200', '41.28', '1.00', 'USD', 'A-1001'],
        ['2026-11-23', '10:12:44', 'Challenge', 'HGRB', 'Sell', '500', '41.90', '2.50', 'USD', 'A-1002'],
        ['2026-11-23', '11:02:10', 'Challenge', 'PLMB', 'Sell Short', '400', '18.62', '2.00', 'USD', 'A-1003'],
        ['2026-11-23', '11:40:31', 'Challenge', 'PLMB', 'Buy to Cover', '400', '18.31', '2.00', 'USD', 'A-1004'],
        ['2026-11-24', '14:30:00', 'Futures', 'LKFZ6', 'Buy', '2', '5112.25', '4.10', 'USD', 'F-2001'],
        ['2026-11-24', '14:55:12', 'Futures', 'LKFZ6', 'Sell', '2', '5120.50', '4.10', 'USD', 'F-2002'],
    ])


def position_size(inp):
    """How many shares or contracts to trade so a stop-out loses no more than the chosen risk."""
    equity = parse_cents(inp.get('equity'))
    pct = parse_float_text(inp.get('riskPct'))
    entry = parse_micro(inp.get('entry'))
    stop = parse_micro(inp.get('stop'))
    mult = parse_float_text(inp.get('mult'))
    fee = parse_cents(inp.get('fee')) if inp.get('fee') else 0
    step = parse_float_text(inp.get('step')) if inp.get('step') else 1
    allowance = parse_cents(inp.get('allowance')) if inp.get('allowance') else None
    if equity is None or not equity > 0:
        return {'ok': False, 'msg': 'Enter the account size.'}
    if pct is None or not pct > 0:
        return {'ok': False, 'msg': 'Enter the risk per trade as a percentage of the account.'}
    if entry is None or not entry > 0:
        return {'ok': False, 'msg': 'Enter the entry price.'}
    if stop is None or not stop > 0:
        return {'ok': False, 'msg': 'Enter the stop price.'}
    if stop == entry:
        return {'ok': False, 'msg': 'The stop must be away from the entry.'}
    if mult is None or not mult > 0:
        mult = 1
    if fee is None or fee < 0:
        fee = 0
    if step is None or not step > 0:
        step = 1
    direction = 1 if stop < entry else -1
    per_unit = float((entry - stop) * direction) * mult / 10000 + fee
    budget = equity * pct / 100
    limited_by = 'risk'
    if allowance is not None and allowance >= 0 and allowance < budget:
        budget = allowance
        limited_by = 'allowance'
    units = math.floor(budget / per_unit / step + 1e-9) * step
    units = rnd(units * 1000000) / 1000000
    risk = rnd(units * per_unit)
    value = rnd(units * entry * mult / 10000)
    return {
        'ok': units > 0,
        'msg': '' if units > 0 else 'The stop is too far away for this risk: even one ' + ('step' if step < 1 else 'unit') + ' would risk more than '
        + money(rnd(budget), inp.get('currency') or '') + '.',
        'direction': 'long' if direction > 0 else 'short', 'units': units, 'perUnit': rnd(per_unit), 'budget': rnd(budget), 'risk': risk,
        'riskPct': risk * 100 / equity, 'value': value, 'valuePct': value * 100 / equity, 'limitedBy': limited_by,
        'targets': [{'r': k, 'price': entry + k * (entry - stop)} for k in (1, 2, 3)],
    }


FILL_FIELDS = ['key', 'account', 'symbol', 'day', 'sec', 'side', 'intent', 'q', 'price', 'fee', 'currency', 'mult', 'orderId', 'execId', 'asset', 'file', 'line', 'src', 'seq']
FEE_FIELDS = ['key', 'account', 'symbol', 'day', 'sec', 'amount', 'orderId', 'label', 'file', 'line', 'src', 'seq']
SOURCE_FIELDS = ['id', 'name', 'account', 'first', 'last', 'added', 'duplicates', 'feesAdded']


def _pick(o, fields):
    return {f: o.get(f) for f in fields}


def project_file(state, saved_on=''):
    """The journal file: settings, sources, journal entries, fills and fee rows, as JSON."""
    st = state['settings']
    rules = {}
    for x in RULES:
        v = (st.get('rules') or {}).get(x['id']) or {}
        rules[x['id']] = {'on': bool(v.get('on')), 'value': s(v.get('value')), 'unit': s(v.get('unit'))}
    out = {
        'app': 'round-trips', 'version': VERSION, 'saved': saved_on or '',
        'settings': {
            'base': st['base'], 'dateOrder': st['dateOrder'],
            'fx': [{'currency': e['currency'], 'rate': s(e.get('rate'))} for e in st.get('fx') or []],
            'multipliers': [{'symbol': e['symbol'], 'value': s(e.get('value'))} for e in st.get('multipliers') or []],
            'accounts': [{'name': a['name'], 'start': s(a.get('start')), 'currency': s(a.get('currency')), 'longOnly': bool(a.get('longOnly'))}
                         for a in st.get('accounts') or []],
            'rules': rules, 'setups': list(st.get('setups') or []), 'mistakes': list(st.get('mistakes') or []),
        },
        'sources': [_pick(x, SOURCE_FIELDS) for x in state['sources'] if not x.get('error')],
        'journal': [{'id': e['id'], 'setup': e['setup'], 'stop': e['stop'], 'risk': e['risk'], 'target': e.get('target') or '',
                     'mistakes': list(e['mistakes']), 'notes': e['notes']} for e in state.get('journal') or []],
        'fills': [_pick(f, FILL_FIELDS) for f in state['fills']],
        'feeRows': [_pick(e, FEE_FIELDS) for e in state['feeRows']],
        'seq': state['seq'],
    }
    return json.dumps(out, indent=1, ensure_ascii=False) + '\n'


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_CODE = rx(r'^[A-Z]{3}$')


def read_project(text):
    """Read a saved journal file back: {'ok', 'error', 'state', 'saved'}."""
    raw = s(text)
    if raw.startswith('\ufeff'):
        raw = raw[1:]
    try:
        data = json.loads(raw)
    except ValueError:
        return {'ok': False, 'error': 'This is not a journal file (it is not valid JSON).'}
    if not isinstance(data, dict) or data.get('app') != 'round-trips' or not isinstance(data.get('fills'), list):
        return {'ok': False, 'error': 'This is not a Round trips journal file.'}
    if _is_num(data.get('version')) and data['version'] > VERSION:
        return {'ok': False, 'error': 'This journal was saved by a newer version of Round trips.'}
    st = empty_state()
    sd = data.get('settings') or {}
    d = st['settings']
    if isinstance(sd.get('base'), str) and _CODE.match(sd['base']):
        d['base'] = sd['base']
    if sd.get('dateOrder') in ('DMY', 'MDY', 'auto'):
        d['dateOrder'] = sd['dateOrder']
    if isinstance(sd.get('fx'), list):
        d['fx'] = [{'currency': s(e['currency']), 'rate': s(e.get('rate'))} for e in sd['fx'] if isinstance(e, dict) and e.get('currency')]
    if isinstance(sd.get('multipliers'), list):
        d['multipliers'] = [{'symbol': s(e['symbol']), 'value': s(e.get('value'))} for e in sd['multipliers'] if isinstance(e, dict) and e.get('symbol')]
    if isinstance(sd.get('accounts'), list):
        d['accounts'] = [{'name': s(e['name']), 'start': s(e.get('start')), 'currency': s(e.get('currency')), 'longOnly': bool(e.get('longOnly'))}
                         for e in sd['accounts'] if isinstance(e, dict) and e.get('name')]
    if isinstance(sd.get('rules'), dict):
        for x in RULES:
            v = sd['rules'].get(x['id'])
            if v:
                d['rules'][x['id']] = {'on': bool(v.get('on')), 'value': s(v.get('value')), 'unit': s(v.get('unit'))}
    for x in RULES:
        v = d['rules'][x['id']]
        if not v.get('value'):
            v.pop('value', None)
        if not v.get('unit'):
            v.pop('unit', None)
    if isinstance(sd.get('setups'), list):
        d['setups'] = [s(x) for x in sd['setups']]
    if isinstance(sd.get('mistakes'), list):
        d['mistakes'] = [s(x) for x in sd['mistakes']]
    sources = []
    for x in data.get('sources') or []:
        o = _pick(x, SOURCE_FIELDS)
        o.update({'ok': True, 'error': '', 'columns': {}, 'notes': [], 'skipped': [], 'counts': None, 'dateNote': '', 'saved': True})
        sources.append(o)
    st['sources'] = sources
    bad, fills = 0, []
    for f in data['fills']:
        ok = (isinstance(f, dict) and isinstance(f.get('key'), str) and _is_num(f.get('day')) and f.get('side') in ('B', 'S')
              and _is_num(f.get('q')) and f['q'] > 0 and _is_num(f.get('price')))
        if not ok:
            bad += 1
            continue
        g = _pick(f, FILL_FIELDS)
        if g['fee'] is None:
            g['fee'] = 0
        if g['intent'] is None:
            g['intent'] = ''
        for k in ('orderId', 'execId', 'asset', 'file', 'currency'):
            if g[k] is None:
                g[k] = ''
        fills.append(g)
    st['fills'] = fills
    fee_rows = []
    for e in data.get('feeRows') or []:
        if isinstance(e, dict) and isinstance(e.get('key'), str) and _is_num(e.get('amount')):
            g = _pick(e, FEE_FIELDS)
            for k in ('orderId', 'label', 'file', 'symbol'):
                if g[k] is None:
                    g[k] = ''
            fee_rows.append(g)
    st['feeRows'] = fee_rows
    st['journal'] = sort_by([clean_entry(e['id'], e) for e in data.get('journal') or [] if isinstance(e, dict) and isinstance(e.get('id'), str)],
                            lambda a, b: cmp(a['id'], b['id']))
    max_seq = 0
    for f in fills + fee_rows:
        if _is_num(f.get('seq')) and f['seq'] > max_seq:
            max_seq = f['seq']
    st['seq'] = data['seq'] if _is_num(data.get('seq')) and data['seq'] >= max_seq else max_seq
    return {'ok': True, 'error': '%d damaged fills in the file were skipped.' % bad if bad else '', 'state': st, 'saved': s(data.get('saved'))}
