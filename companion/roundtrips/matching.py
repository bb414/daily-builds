"""Settings, the journal state, matching fills into round trips, the rules and the whole analysis.

Mirrors the browser model: importFiles, matchTrades, tradeRisk, analyse and checkRules.
A trade runs from flat to flat in one symbol in one account; inside it, closing
quantities are matched to opening lots first in, first out.
"""

import math

from .common import (DAY, cmp, fmt_date, fmt_num, fmt_price, fmt_qty, fmt_r, from_iso, iso_stamp, jsnum, money, parse_cents, parse_float_text,
                     parse_micro, plural, rnd, rx, sort_by, trim, week_start)
from .parsing import read_export, symbol_root


def default_rules():
    return {
        'maxRiskPct': {'on': True, 'value': '1'},
        'maxDailyLoss': {'on': True, 'value': '2', 'unit': 'pct'},
        'maxTradesPerDay': {'on': True, 'value': '6'},
        'noAddingToLoser': {'on': True},
        'maxLossR': {'on': True, 'value': '1.5'},
        'needPlannedRisk': {'on': True},
    }


def default_settings():
    return {
        'base': 'USD', 'dateOrder': 'auto', 'fx': [], 'multipliers': [], 'accounts': [], 'rules': default_rules(),
        'setups': ['Opening range break', 'Pullback', 'Breakout', 'Reversal', 'News'],
        'mistakes': ['Chased entry', 'Moved stop', 'Added to a loser', 'Oversized', 'Early exit', 'Revenge trade', 'No plan'],
    }


def empty_state():
    return {'settings': default_settings(), 'sources': [], 'fills': [], 'feeRows': [], 'journal': [], 'carry': [], 'seq': 0}


def lookup(lst, key, field):
    for e in lst:
        if e.get(field) == key:
            return e
    return None


def import_files(state, files):
    """Add exports to the journal, skipping fills that are already in it."""
    nxt = {'settings': state['settings'], 'sources': list(state['sources']), 'fills': list(state['fills']), 'feeRows': list(state['feeRows']),
           'journal': state['journal'], 'carry': state.get('carry') or [], 'seq': state['seq']}
    have = {f['key'] for f in nxt['fills']}
    have_fee = {e['key'] for e in nxt['feeRows']}
    reports = []
    for file in files:
        rep = read_export(file['name'], file['text'], {'dateOrder': file.get('dateOrder') or state['settings']['dateOrder'],
                                                       'account': file.get('account'), 'base': state['settings']['base'], 'columns': file.get('columns')})
        sid = 1
        for src in nxt['sources']:
            if src['id'] >= sid:
                sid = src['id'] + 1
        added = dupes = fees_added = 0
        for f in rep['fills']:
            if f['key'] in have:
                dupes += 1
                continue
            have.add(f['key'])
            nxt['seq'] += 1
            g = dict(f)
            g['src'] = sid
            g['seq'] = nxt['seq']
            nxt['fills'].append(g)
            added += 1
        for e in rep['fees']:
            if e['key'] in have_fee:
                continue
            have_fee.add(e['key'])
            nxt['seq'] += 1
            g = dict(e)
            g['src'] = sid
            g['seq'] = nxt['seq']
            g['file'] = rep['name']
            nxt['feeRows'].append(g)
            fees_added += 1
        source = {
            'id': sid, 'name': rep['name'], 'ok': rep['ok'], 'error': rep['error'], 'account': rep['account'], 'columns': rep['columns'],
            'dateOrder': rep['dateOrder'], 'dateNote': rep['dateNote'], 'notes': rep['notes'], 'counts': rep['counts'], 'added': added,
            'duplicates': dupes, 'feesAdded': fees_added, 'skipped': rep['skipped'][:300], 'first': None, 'last': None, 'headerCells': rep['headerCells'],
        }
        for f in rep['fills']:
            if source['first'] is None or f['day'] < source['first']:
                source['first'] = f['day']
            if source['last'] is None or f['day'] > source['last']:
                source['last'] = f['day']
        if rep['ok'] or rep['error']:
            nxt['sources'].append(source)
        reports.append(source)
    return {'state': nxt, 'reports': reports}


def multiplier_for(settings, symbol, file_mult):
    e = lookup(settings.get('multipliers') or [], symbol, 'symbol')
    if not e:
        r = symbol_root(symbol)
        if r:
            e = lookup(settings.get('multipliers') or [], r, 'symbol')
    if e:
        v = parse_float_text(e.get('value'))
        if v is not None and v > 0:
            return jsnum(v)
    if file_mult:
        return file_mult
    return 1


def account_settings(settings, account):
    return lookup(settings.get('accounts') or [], account, 'name') or {'name': account, 'start': '', 'longOnly': False}


def fx_rate(settings, currency):
    if currency == settings['base']:
        return 1
    e = lookup(settings.get('fx') or [], currency, 'currency')
    v = parse_float_text(e.get('rate')) if e else None
    return v if v is not None and v > 0 else None


def fill_t(f):
    return f['day'] * DAY + (0 if f['sec'] is None else f['sec'])


def _by_time(a, b):
    return (fill_t(a) - fill_t(b)) or (a['seq'] - b['seq'])


def piece_pnl(entry, exit_, direction, q, mult):
    """Profit on a matched piece in cents: (exit - entry) x direction x quantity x multiplier."""
    return rnd(float(exit_ - entry) * direction * q * mult / 10000000000)


def same_order(a, b):
    if a['orderId'] and b['orderId']:
        return a['orderId'] == b['orderId']
    if a['sec'] is None or b['sec'] is None:
        return False
    return a['day'] == b['day'] and fill_t(b) - fill_t(a) <= 5


def _fee_order(a, b):
    return (((0 if a['day'] is None else a['day']) - (0 if b['day'] is None else b['day']))
            or ((0 if a['sec'] is None else a['sec']) - (0 if b['sec'] is None else b['sec'])) or (a['seq'] - b['seq']))


def carry_key(c):
    return '|'.join(['c', c['account'], c['symbol'], str(c['day']), c['side'], str(c['q']), str(c['price'])])


def carry_fills(state):
    """Opening positions typed in for closes whose opening fill is older than the exports, as fills."""
    carry = state.get('carry') or []
    return [{'key': carry_key(c), 'account': c['account'], 'symbol': c['symbol'], 'day': c['day'], 'sec': None, 'side': c['side'], 'intent': 'open',
             'q': c['q'], 'price': c['price'], 'fee': c.get('fee') or 0, 'currency': c['currency'], 'mult': None, 'orderId': '', 'execId': '', 'asset': '',
             'file': 'Opening position', 'line': 0, 'src': 0, 'seq': -(len(carry) - i)} for i, c in enumerate(carry)]


def make_carry(u, date_text, price_text):
    """An opening position for a close with no opening fill: the date (YYYY-MM-DD) and price it was opened at."""
    day = from_iso(date_text)
    if day is None:
        return {'ok': False, 'msg': 'Enter the date the position was opened.'}
    if day > u['day']:
        return {'ok': False, 'msg': 'The opening date must be on or before ' + fmt_date(u['day']) + ', when it was closed.'}
    price = parse_micro(price_text)
    if price is None or not price > 0:
        return {'ok': False, 'msg': 'Enter the price it was opened at.'}
    return {'ok': True, 'carry': {'account': u['account'], 'symbol': u['symbol'], 'side': 'B' if u['side'] == 'S' else 'S', 'q': u['q'], 'price': price,
                                  'day': day, 'fee': 0, 'currency': u.get('currency') or ''}}


def match_trades(state):
    settings = state['settings']
    fills = sort_by(state['fills'] + carry_fills(state), _by_time)
    fee_of = {f['key']: f['fee'] for f in fills}
    by_order, by_day = {}, {}
    for f in fills:
        if f['orderId']:
            ko = f['account'] + '\u0000' + f['orderId']
            if ko not in by_order:
                by_order[ko] = f
        by_day.setdefault(f['account'] + '\u0000' + f['symbol'] + '\u0000' + str(f['day']), []).append(f)
    unattached = []
    for e in sort_by(state['feeRows'], _fee_order):
        target = None
        if e['orderId']:
            target = by_order.get(e['account'] + '\u0000' + e['orderId'])
        if not target and e['symbol'] and e['day'] is not None:
            same = by_day.get(e['account'] + '\u0000' + e['symbol'] + '\u0000' + str(e['day']), [])
            before = after = None
            et = e['day'] * DAY + (DAY - 1 if e['sec'] is None else e['sec'])
            for f in same:
                if fill_t(f) <= et:
                    before = f
                elif not after:
                    after = f
            target = before or after
        if target:
            fee_of[target['key']] += e['amount']
        else:
            unattached.append({'key': e['key'], 'account': e['account'], 'symbol': e['symbol'], 'day': e['day'], 'sec': e['sec'],
                               'amount': e['amount'], 'label': e['label'], 'file': e['file'], 'seq': e['seq']})

    groups, order = {}, []
    for f in fills:
        g = f['account'] + '\u0000' + f['symbol']
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(f)
    order = sort_by(order, cmp)
    trades, unmatched, legs_by_fill, events = [], [], {}, []
    id_count = {}

    for g in order:
        lst = groups[g]
        acc = account_settings(settings, lst[0]['account'])
        st = {'pos': 0, 'lots': [], 'trade': None, 'group': None}

        def event(f, cents, kind, tid):
            events.append({'account': f['account'], 'symbol': f['symbol'], 'day': f['day'], 'sec': f['sec'], 't': fill_t(f), 'seq': f['seq'], 'cents': cents,
                           'trade': tid, 'kind': kind})

        def no_trade(f, q, fee):
            unmatched.append({'key': f['key'], 'account': f['account'], 'symbol': f['symbol'], 'side': f['side'], 'q': q, 'price': f['price'],
                              'day': f['day'], 'sec': f['sec'], 'fee': fee, 'file': f['file'], 'line': f['line'], 'currency': f['currency']})
            event(f, -fee, 'fee', '')

        def add_leg(f, q, role, fee):
            trade = st['trade']
            prev = trade['legs'][-1] if trade['legs'] else None
            if f['sec'] is None:
                trade['timeKnown'] = False
            if role in ('open', 'add'):
                new_order = not prev or prev['role'] not in ('open', 'add') or not same_order(prev, f)
                if new_order:
                    trade['entryOrders'] += 1
                    st['group'] = None
                    if role == 'add':
                        lq, lv = 0, 0
                        for lot in st['lots']:
                            lq += lot['q']
                            lv += float(lot['price']) * lot['q']
                        st['group'] = {'day': f['day'], 'sec': f['sec'], 'q': 0, 'value': 0, 'avgBefore': lv / lq if lq else 0, 'worse': False}
                        trade['adds'].append(st['group'])
                if role == 'add' and st['group']:
                    st['group']['q'] += q
                    st['group']['value'] += float(f['price']) * q
                trade['qtyIn'] += q
                trade['entryValue'] += float(f['price']) * q
            else:
                st['group'] = None
                if not prev or prev['role'] in ('open', 'add') or not same_order(prev, f):
                    trade['exitOrders'] += 1
                trade['qtyOut'] += q
                trade['exitValue'] += float(f['price']) * q
            trade['fees'] += fee
            trade['legs'].append({'key': f['key'], 'role': role, 'side': f['side'], 'q': q, 'price': f['price'], 'day': f['day'], 'sec': f['sec'],
                                  'fee': fee, 'orderId': f['orderId']})
            legs_by_fill.setdefault(f['key'], []).append({'trade': trade['id'], 'role': role, 'q': q})
            event(f, -fee, 'fee', trade['id'])

        def open_trade(f, q, fee):
            mult = multiplier_for(settings, f['symbol'], f['mult'])
            base = f['account'] + '|' + f['symbol'] + '|' + iso_stamp(f['day'], f['sec'])
            id_count[base] = id_count.get(base, 0) + 1
            st['trade'] = {
                'id': base + '|' + str(id_count[base]) if id_count[base] > 1 else base,
                'account': f['account'], 'symbol': f['symbol'], 'root': symbol_root(f['symbol']), 'currency': f['currency'], 'mult': mult,
                'dir': 1 if f['side'] == 'B' else -1, 'openDay': f['day'], 'openSec': f['sec'], 'closeDay': None, 'closeSec': None,
                'legs': [], 'matches': [], 'qtyIn': 0, 'qtyOut': 0, 'maxPos': q, 'gross': 0, 'fees': 0, 'status': 'open', 'reversal': False,
                'entryValue': 0, 'exitValue': 0, 'timeKnown': True, 'entryOrders': 0, 'exitOrders': 0, 'adds': [],
            }
            trades.append(st['trade'])
            st['group'] = None
            add_leg(f, q, 'open', fee)
            st['lots'] = [{'q': q, 'price': f['price'], 'key': f['key'], 'day': f['day'], 'sec': f['sec']}]
            st['pos'] = (1 if f['side'] == 'B' else -1) * q

        for f in lst:
            fee = fee_of[f['key']]
            direction = 1 if f['side'] == 'B' else -1
            q = f['q']
            if st['pos'] == 0:
                if f['intent'] == 'close' or (acc.get('longOnly') and f['side'] == 'S'):
                    no_trade(f, q, fee)
                    continue
                open_trade(f, q, fee)
                continue
            trade = st['trade']
            if (st['pos'] > 0 and direction > 0) or (st['pos'] < 0 and direction < 0):
                last = trade['legs'][-1]
                add_leg(f, q, 'open' if last['role'] == 'open' and same_order(last, f) else 'add', fee)
                st['lots'].append({'q': q, 'price': f['price'], 'key': f['key'], 'day': f['day'], 'sec': f['sec']})
                st['pos'] += direction * q
                if abs(st['pos']) > trade['maxPos']:
                    trade['maxPos'] = abs(st['pos'])
                grp = st['group']
                if grp and grp['q']:
                    grp['worse'] = trade['dir'] * (grp['value'] / grp['q'] - grp['avgBefore']) < 0
                continue
            open_q = abs(st['pos'])
            close_q = q if q < open_q else open_q
            extra = q - close_q
            close_fee = rnd(float(fee) * close_q / q) if extra > 0 else fee
            add_leg(f, close_q, 'close' if close_q == open_q else 'reduce', close_fee)
            left = close_q
            lots = st['lots']
            while left > 0 and lots:
                lot = lots[0]
                take = lot['q'] if lot['q'] < left else left
                pnl = piece_pnl(lot['price'], f['price'], trade['dir'], take, trade['mult'])
                trade['matches'].append({'open': lot['key'], 'close': f['key'], 'q': take, 'entry': lot['price'], 'exit': f['price'], 'pnl': pnl,
                                         'holdSec': fill_t(f) - (lot['day'] * DAY + (0 if lot['sec'] is None else lot['sec']))})
                trade['gross'] += pnl
                event(f, pnl, 'pnl', trade['id'])
                lot['q'] -= take
                left -= take
                if lot['q'] == 0:
                    lots.pop(0)
            st['pos'] += direction * close_q
            if st['pos'] == 0:
                trade['status'] = 'closed'
                trade['closeDay'] = f['day']
                trade['closeSec'] = f['sec']
                st['trade'] = None
                st['group'] = None
                st['lots'] = []
            if extra > 0:
                rest_fee = fee - close_fee
                if f['intent'] != 'close' and not (acc.get('longOnly') and f['side'] == 'S'):
                    open_trade(f, extra, rest_fee)
                    st['trade']['reversal'] = True
                else:
                    no_trade(f, extra, rest_fee)
        if st['trade']:
            st['trade']['openLots'] = [{'q': l['q'], 'price': l['price'], 'day': l['day'], 'sec': l['sec']} for l in st['lots']]

    for e in unattached:
        events.append({'account': e['account'], 'symbol': e['symbol'], 'day': 0 if e['day'] is None else e['day'], 'sec': e['sec'],
                       't': 0 if e['day'] is None else e['day'] * DAY + (0 if e['sec'] is None else e['sec']),
                       'seq': e['seq'], 'cents': -e['amount'], 'trade': '', 'kind': 'fee'})
    events = sort_by(events, lambda a, b: cmp(a['account'], b['account']) or (a['t'] - b['t']) or (a['seq'] - b['seq']) or cmp(a['kind'], b['kind']))
    for t in trades:
        t['net'] = t['gross'] - t['fees']
        t['openT'] = t['openDay'] * DAY + (0 if t['openSec'] is None else t['openSec'])
        t['closeT'] = None if t['closeDay'] is None else t['closeDay'] * DAY + (0 if t['closeSec'] is None else t['closeSec'])
        t['holdSec'] = None if t['closeT'] is None else t['closeT'] - t['openT']
        t['avgEntry'] = t['entryValue'] / t['qtyIn'] if t['qtyIn'] else 0
        t['avgExit'] = t['exitValue'] / t['qtyOut'] if t['qtyOut'] else 0
        hq, hv = 0, 0
        for m in t['matches']:
            hq += m['q']
            hv += float(m['holdSec']) * m['q']
        t['fifoHoldSec'] = rnd(hv / hq) if hq else None
        if 'openLots' not in t:
            t['openLots'] = []
        t['openQty'] = sum(l['q'] for l in t['openLots'])
        t['adds'] = [{'day': a['day'], 'sec': a['sec'], 'q': a['q'], 'price': a['value'] / a['q'] if a['q'] else 0, 'avgBefore': a['avgBefore'],
                      'worse': a['worse']} for a in t['adds']]
    return {'fills': fills, 'feeOf': fee_of, 'trades': trades, 'unmatched': unmatched, 'unattached': unattached, 'legsByFill': legs_by_fill, 'events': events}


def journal_entry(state, tid):
    return lookup(state.get('journal') or [], tid, 'id')


def clean_entry(tid, f):
    mistakes = []
    for m in f.get('mistakes') or []:
        m = trim(m)
        if m and m not in mistakes:
            mistakes.append(m)
    notes = (f.get('notes') or '')
    notes = notes if isinstance(notes, str) else str(notes)
    notes = rx(r'\s+$').sub('', notes.replace('\r\n', '\n').replace('\r', '\n'))
    return {'id': tid, 'setup': trim(f.get('setup')), 'stop': trim(f.get('stop')), 'risk': trim(f.get('risk')), 'target': trim(f.get('target')),
            'mistakes': mistakes, 'notes': notes}


def set_journal(journal, tid, fields):
    """Store one trade's journal fields, returning a new journal list sorted by trade id."""
    out, found = [], False
    for e in journal or []:
        if e['id'] == tid:
            found = True
            out.append(clean_entry(tid, fields))
        else:
            out.append(e)
    if not found:
        out.append(clean_entry(tid, fields))
    out = [e for e in out if e['setup'] or e['stop'] or e['risk'] or e['notes'] or e['mistakes'] or e['target']]
    return sort_by(out, lambda a, b: cmp(a['id'], b['id']))


def trade_risk(trade, stop):
    """Open risk given a stop price: the most the open lots could lose at the stop, after each fill."""
    if stop is None:
        return None
    lots, initial, mx = [], None, 0
    legs = trade['legs']
    for i, leg in enumerate(legs):
        if leg['role'] in ('open', 'add'):
            lots.append({'q': leg['q'], 'price': leg['price']})
        else:
            left = leg['q']
            while left > 0 and lots:
                take = lots[0]['q'] if lots[0]['q'] < left else left
                lots[0]['q'] -= take
                left -= take
                if lots[0]['q'] == 0:
                    lots.pop(0)
        risk = 0
        for lot in lots:
            per = trade['dir'] * (lot['price'] - stop)
            if per > 0:
                risk += float(per) * lot['q']
        cents = rnd(risk * trade['mult'] / 10000000000)
        if cents > mx:
            mx = cents
        nxt = legs[i + 1] if i + 1 < len(legs) else None
        if initial is None and leg['role'] == 'open' and not (nxt and nxt['role'] == 'open'):
            initial = cents
    return {'initial': 0 if initial is None else initial, 'max': mx}


RULES = [
    {'id': 'maxRiskPct', 'label': 'Maximum risk per trade', 'broken': 'risk over the limit'},
    {'id': 'maxDailyLoss', 'label': 'Maximum daily loss', 'broken': 'daily loss limit'},
    {'id': 'maxTradesPerDay', 'label': 'Maximum trades per day', 'broken': 'too many trades in a day'},
    {'id': 'noAddingToLoser', 'label': 'No adding to a loser', 'broken': 'added to a loser'},
    {'id': 'maxLossR', 'label': 'Loss no bigger than planned', 'broken': 'loss bigger than planned'},
    {'id': 'needPlannedRisk', 'label': 'Stop or planned risk recorded', 'broken': 'no stop or planned risk'},
]


def rule_label(rid):
    for x in RULES:
        if x['id'] == rid:
            return x['label']
    return rid


def rule_value(rule):
    v = parse_float_text(rule.get('value')) if rule else None
    return None if v is None or not (v > 0) else v


def currency_of_account(trades, account, base):
    for t in trades:
        if t['account'] == account:
            return t['currency']
    return base


_PENCE_STOP = rx(r'p$', 0)


def _trade_order(a, b):
    return (a['closeT'] - b['closeT']) or (a['openT'] - b['openT']) or cmp(a['id'], b['id'])


def analyse(state):
    settings = state['settings']
    m = match_trades(state)
    journal = {e['id']: e for e in state.get('journal') or []}
    warnings = []
    for t in m['trades']:
        j = journal.get(t['id']) or {'setup': '', 'stop': '', 'risk': '', 'target': '', 'mistakes': [], 'notes': ''}
        t['setup'] = j.get('setup') or ''
        t['mistakes'] = list(j.get('mistakes') or [])
        t['notes'] = j.get('notes') or ''
        t['stopText'] = j.get('stop') or ''
        t['riskText'] = j.get('risk') or ''
        t['targetText'] = j.get('target') or ''
        stop = parse_micro(j['stop']) if j.get('stop') else None
        if stop is not None and trim(j['stop'])[-1:] in ('p', 'P') and t['currency'] == 'GBP':
            stop = rnd(stop / 100)
        t['stop'] = stop
        risk = trade_risk(t, stop)
        planned = parse_cents(j['risk']) if j.get('risk') else None
        if planned is not None and planned <= 0:
            planned = None
        t['initialRisk'] = risk['initial'] if risk else None
        t['maxRisk'] = risk['max'] if risk else planned
        t['plannedRisk'] = planned if planned is not None else (risk['initial'] if risk and risk['initial'] > 0 else None)
        t['r'] = t['net'] / t['plannedRisk'] if t['status'] == 'closed' and t['plannedRisk'] else None
        rate = fx_rate(settings, t['currency'])
        t['rate'] = rate
        t['netBase'] = None if rate is None else rnd(t['net'] * rate)
        t['feesBase'] = None if rate is None else rnd(t['fees'] * rate)
        t['grossBase'] = None if rate is None else t['netBase'] + t['feesBase']
        t['target'] = parse_micro(j['target']) if j.get('target') else None
        t['breaches'] = []
    missing = {}
    for t in m['trades']:
        if t['rate'] is None:
            missing[t['currency']] = missing.get(t['currency'], 0) + 1
    for c in sort_by(list(missing), cmp):
        n = missing[c]
        warnings.append({'kind': 'fx', 'text': plural(n, 'trade') + (' is' if n == 1 else ' are') + ' in ' + c + ' but there is no ' + c + ' to ' + settings['base']
                         + ' rate, so ' + ('it is' if n == 1 else 'they are') + ' left out of the totals. Add a rate under Rules and settings.'})
    symbols = {}
    for f in m['fills']:
        k = f['account'] + '|' + f['symbol']
        sy = symbols.get(k)
        if not sy:
            sy = symbols[k] = {'account': f['account'], 'symbol': f['symbol'], 'root': symbol_root(f['symbol']), 'currency': f['currency'], 'fills': 0,
                               'fileMult': f['mult'], 'asset': f['asset']}
        sy['fills'] += 1
        if f['asset']:
            sy['asset'] = f['asset']
    symbol_list = []
    for k in sort_by(list(symbols), cmp):
        sy = symbols[k]
        sy['mult'] = multiplier_for(settings, sy['symbol'], sy['fileMult'])
        sy['multSet'] = bool(lookup(settings.get('multipliers') or [], sy['symbol'], 'symbol') or (sy['root'] and lookup(settings.get('multipliers') or [], sy['root'], 'symbol')))
        sy['looksFuture'] = bool(sy['root']) or sy['asset'] == 'future'
        symbol_list.append(sy)
    no_mult = [x for x in symbol_list if x['looksFuture'] and not x['multSet'] and not x['fileMult']]
    if no_mult:
        warnings.append({'kind': 'mult', 'text': ', '.join(x['symbol'] for x in no_mult) + (' looks' if len(no_mult) == 1 else ' look')
                         + ' like a futures contract but has no contract multiplier, so each point counts as 1. Set the multiplier under Fills.'})
    nu = len(m['unmatched'])
    if nu:
        warnings.append({'kind': 'unmatched', 'text': str(nu) + (' fill closes' if nu == 1 else ' fills close')
                         + ' a position with no opening fill in these exports (probably opened before the first export), so '
                         + ('it is' if nu == 1 else 'they are') + ' not counted as a trade. See Fills.'})
    closed = sort_by([t for t in m['trades'] if t['status'] == 'closed'], _trade_order)
    opened = sort_by([t for t in m['trades'] if t['status'] == 'open'], lambda a, b: (a['openT'] - b['openT']) or cmp(a['id'], b['id']))
    rules = check_rules(closed, opened, m['events'], settings)
    accounts = {f['account'] for f in m['fills']} | {e['account'] for e in m['unattached']}
    weeks = {week_start(t['closeDay']) for t in closed} | {week_start(f['day']) for f in m['fills']}
    return {
        'settings': settings, 'fills': m['fills'], 'feeOf': m['feeOf'], 'legsByFill': m['legsByFill'], 'trades': closed + opened, 'closed': closed,
        'open': opened, 'unmatched': m['unmatched'], 'unattached': m['unattached'], 'events': m['events'], 'breaches': rules['breaches'],
        'ruleSummary': rules['summary'], 'warnings': warnings, 'symbols': symbol_list, 'accounts': sort_by(list(accounts), cmp),
        'weeks': sorted(weeks),
    }


def check_rules(closed, opened, events, settings):
    rules = settings.get('rules') or default_rules()
    breaches = []
    unchecked = {'maxRiskPct': 0, 'maxDailyLoss': 0, 'maxLossR': 0}

    def add(rid, t, day, sec, detail, account=''):
        breaches.append({'rule': rid, 'label': rule_label(rid), 'account': t['account'] if t else account, 'symbol': t['symbol'] if t else '',
                         'trade': t['id'] if t else '', 'day': day, 'sec': sec, 'detail': detail})
        if t:
            t['breaches'].append(rid)

    every = sort_by(closed + opened, lambda a, b: (a['openT'] - b['openT']) or cmp(a['id'], b['id']))
    start_of = {}

    def start_cents(account):
        if account in start_of:
            return start_of[account]
        a = account_settings(settings, account)
        v = parse_cents(a['start']) if a.get('start') else None
        start_of[account] = v if v is not None and v > 0 else None
        return start_of[account]

    runs = {}
    for c in closed:
        lst = runs.setdefault(c['account'], [])
        lst.append({'t': c['closeT'], 'cum': (lst[-1]['cum'] if lst else 0) + c['net']})

    def equity_at(account, t):
        s0 = start_cents(account)
        if s0 is None:
            return None
        lst = runs.get(account, [])
        lo, hi = 0, len(lst)
        while lo < hi:
            mid = (lo + hi) // 2
            if lst[mid]['t'] <= t:
                lo = mid + 1
            else:
                hi = mid
        return s0 + lst[lo - 1]['cum'] if lo else s0

    r = rules.get('maxRiskPct')
    if r and r.get('on') and rule_value(r) is not None:
        pct = rule_value(r)
        for t in every:
            risk = t['maxRisk']
            eq = equity_at(t['account'], t['openT'])
            if risk is None or eq is None:
                unchecked['maxRiskPct'] += 1
                continue
            limit = rnd(eq * pct / 100)
            if risk > limit:
                add('maxRiskPct', t, t['openDay'], t['openSec'], 'Risked ' + money(risk, t['currency']) + ' (' + fmt_num(risk * 100 / eq, 2) + '% of '
                    + money(eq, t['currency']) + '), over the ' + fmt_num(pct, 2) + '% limit of ' + money(limit, t['currency']))
    r = rules.get('maxTradesPerDay')
    if r and r.get('on') and rule_value(r) is not None:
        max_n = math.floor(rule_value(r))
        count = {}
        for t in every:
            k = t['account'] + '|' + str(t['openDay'])
            count[k] = count.get(k, 0) + 1
            if count[k] > max_n:
                add('maxTradesPerDay', t, t['openDay'], t['openSec'], 'Trade %d of the day; the limit is %d' % (count[k], max_n))
    r = rules.get('noAddingToLoser')
    if r and r.get('on'):
        for t in every:
            for a in t['adds']:
                if a['worse']:
                    add('noAddingToLoser', t, a['day'], a['sec'], 'Added ' + fmt_qty(a['q']) + ' at ' + fmt_price(a['price'])
                        + ' while the position was losing (average entry ' + fmt_price(a['avgBefore']) + ')')
    r = rules.get('maxLossR')
    if r and r.get('on') and rule_value(r) is not None:
        max_r = rule_value(r)
        for t in closed:
            if t['r'] is None:
                unchecked['maxLossR'] += 1
                continue
            if t['r'] < -max_r:
                add('maxLossR', t, t['closeDay'], t['closeSec'], 'Lost ' + fmt_r(t['r']) + ', more than the ' + fmt_num(max_r, 2) + 'R allowed: the stop was not respected')
    r = rules.get('needPlannedRisk')
    if r and r.get('on'):
        for t in closed:
            if t['plannedRisk'] is None:
                add('needPlannedRisk', t, t['openDay'], t['openSec'], 'No stop or planned risk recorded in the journal')
    r = rules.get('maxDailyLoss')
    if r and r.get('on') and rule_value(r) is not None:
        v = rule_value(r)
        by_day, keys = {}, []
        for e in events:
            k = e['account'] + '|' + str(e['day'])
            if k not in by_day:
                by_day[k] = []
                keys.append(k)
            by_day[k].append(e)
        trades_by_day = {}
        for t in every:
            trades_by_day.setdefault(t['account'] + '|' + str(t['openDay']), []).append(t)
        for k in keys:
            lst = by_day[k]
            account, day = lst[0]['account'], lst[0]['day']
            if r.get('unit') == 'money':
                limit = rnd(v * 100)
            else:
                s0 = start_cents(account)
                if s0 is None:
                    unchecked['maxDailyLoss'] += 1
                    continue
                limit = rnd(s0 * v / 100)
            run, hit_at, total = 0, None, 0
            for e in lst:
                total += e['cents']
                run += e['cents']
                if hit_at is None and run <= -limit:
                    hit_at = e['t']
            cur = currency_of_account(every, account, settings['base'])
            if total < -limit:
                add('maxDailyLoss', None, day, None, account + ' lost ' + money(-total, cur) + ' on ' + fmt_date(day) + ', over the daily limit of ' + money(limit, cur), account)
            if hit_at is not None:
                for t in trades_by_day.get(k, []):
                    if t['openT'] > hit_at:
                        add('maxDailyLoss', t, t['openDay'], t['openSec'], 'Opened after the daily loss limit of ' + money(limit, cur) + ' had been hit')
    order_of = {x['id']: i for i, x in enumerate(RULES)}
    breaches = sort_by(breaches, lambda a, b: (a['day'] - b['day']) or ((-1 if a['sec'] is None else a['sec']) - (-1 if b['sec'] is None else b['sec']))
                       or (order_of[a['rule']] - order_of[b['rule']]) or cmp(a['trade'], b['trade']) or cmp(a['account'], b['account']))
    summary = []
    for x in RULES:
        rule = rules.get(x['id']) or {}
        n, ids = 0, set()
        for b in breaches:
            if b['rule'] == x['id']:
                n += 1
                if b['trade']:
                    ids.add(b['trade'])
        summary.append({'id': x['id'], 'label': x['label'], 'broken': x['broken'], 'on': bool(rule.get('on')), 'breaches': n, 'trades': len(ids),
                        'unchecked': unchecked.get(x['id'], 0)})
    return {'breaches': breaches, 'summary': summary}
