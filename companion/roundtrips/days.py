"""Days: each trading day's realised result after fees, and a single day replayed fill by fill.

Mirrors dayLedger, dayDetail and daysCsv in the browser model.
"""

from .common import DAY_LONG, cmp, plain_money, rnd, sort_by, to_iso, weekday
from .matching import currency_of_account, fx_rate
from .outputs import csv_lines


def to_base(result):
    """A converter from each account's currency to the base currency (None when there is no rate)."""
    rates = {}

    def conv(account, cents):
        if account not in rates:
            rates[account] = fx_rate(result['settings'], currency_of_account(result['trades'], account, result['settings']['base']))
        return None if rates[account] is None else rnd(cents * rates[account])
    return conv


def day_ledger(result, account=''):
    conv = to_base(result)
    days, keys = {}, []

    def at(day):
        if day not in days:
            days[day] = {'day': day, 'realised': 0, 'pnl': 0, 'fees': 0, 'opened': 0, 'closed': 0, 'wins': 0, 'losses': 0, 'closedNet': 0, 'breaches': 0,
                         'limitHit': False}
            keys.append(day)
        return days[day]

    for e in result['events']:
        if (account and e['account'] != account) or e['day'] < 1:
            continue
        v = conv(e['account'], e['cents'])
        if v is None:
            continue
        d = at(e['day'])
        d['realised'] += v
        if e['kind'] == 'pnl':
            d['pnl'] += v
        else:
            d['fees'] -= v
    for t in result['trades']:
        if account and t['account'] != account:
            continue
        at(t['openDay'])['opened'] += 1
        if t['status'] == 'closed' and t['netBase'] is not None:
            d = at(t['closeDay'])
            d['closed'] += 1
            d['closedNet'] += t['netBase']
            if t['net'] > 0:
                d['wins'] += 1
            elif t['net'] < 0:
                d['losses'] += 1
    for b in result['breaches']:
        if account and b['account'] != account:
            continue
        d = at(b['day'])
        d['breaches'] += 1
        if b['rule'] == 'maxDailyLoss' and not b['trade']:
            d['limitHit'] = True
    return [days[k] for k in sorted(keys)]


def day_detail(result, day, account=''):
    conv = to_base(result)
    lst = sort_by([e for e in result['events'] if e['day'] == day and (not account or e['account'] == account)],
                  lambda a, b: (a['t'] - b['t']) or cmp(a['account'], b['account']) or (a['seq'] - b['seq']) or cmp(a['kind'], b['kind']))
    rows, run, high, low, drop = [], 0, 0, 0, 0
    for e in lst:
        v = conv(e['account'], e['cents'])
        if v is None:
            continue
        last = rows[-1] if rows else None
        row = last if last and last['t'] == e['t'] and last['account'] == e['account'] and last['seq'] == e['seq'] else None
        if not row:
            row = {'t': e['t'], 'sec': e['sec'], 'account': e['account'], 'symbol': e['symbol'], 'seq': e['seq'], 'trades': [], 'pnl': 0, 'fees': 0, 'total': 0}
            rows.append(row)
        if e['trade'] and e['trade'] not in row['trades']:
            row['trades'].append(e['trade'])
        if e['kind'] == 'pnl':
            row['pnl'] += v
        else:
            row['fees'] -= v
        run += v
        row['total'] = run
        high = max(high, run)
        low = min(low, run)
        drop = max(drop, high - run)
    breaches = [b for b in result['breaches'] if b['day'] == day and (not account or b['account'] == account)]
    opened = [t['id'] for t in result['trades'] if t['openDay'] == day and (not account or t['account'] == account)]
    return {'day': day, 'account': account, 'rows': rows, 'total': run, 'high': high, 'low': low, 'drop': drop, 'breaches': breaches, 'opened': opened}


def days_csv(result, account=''):
    base = result['settings']['base']
    rows = [['Date', 'Weekday', 'Realised after fees (' + base + ')', 'Before fees', 'Fees', 'Trades opened', 'Trades closed', 'Won', 'Lost', 'Closed trades net',
             'Rule breaches', 'Daily limit hit']]
    for d in day_ledger(result, account):
        rows.append([to_iso(d['day']), DAY_LONG[weekday(d['day'])], plain_money(d['realised']), plain_money(d['pnl']), plain_money(d['fees']), d['opened'], d['closed'],
                     d['wins'], d['losses'], plain_money(d['closedNet']), d['breaches'], 'Yes' if d['limitHit'] else ''])
    return csv_lines(rows)
