"""Statistics on closed trades: totals, win rate, expectancy, profit factor, R, the equity curve and drawdown, and breakdowns.

Mirrors stats, breakdown, weekly, rHistogram, filterTrades and startBalance in the browser model.
"""

import math

from .common import DAY_LONG, cmp, pad2, parse_cents, rnd, sort_by, weekday, week_start
from .matching import account_settings, currency_of_account, fx_rate


def usable(trades):
    """Closed trades with a figure in the base currency."""
    return [t for t in trades if t['status'] == 'closed' and t['netBase'] is not None]


def stats(trades, start=0):
    lst = usable(trades)
    s = {
        'n': len(lst), 'wins': 0, 'losses': 0, 'flat': 0, 'net': 0, 'gross': 0, 'fees': 0, 'grossWin': 0, 'grossLoss': 0, 'winRate': None,
        'avgWin': None, 'avgLoss': None, 'payoff': None, 'expectancy': None, 'profitFactor': None, 'best': None, 'worst': None,
        'maxWinStreak': 0, 'maxLossStreak': 0, 'avgHoldWin': None, 'avgHoldLoss': None, 'avgHold': None,
        'rCount': 0, 'rSum': 0, 'avgR': None, 'rWins': 0, 'maxDD': 0, 'maxDDPct': None, 'ddFrom': None, 'ddTo': None, 'recovery': None,
        'curve': [], 'days': [], 'sharpe': None, 'sortino': None, 'longN': 0, 'shortN': 0, 'longNet': 0, 'shortNet': 0,
    }
    streak_w = streak_l = hold_w = hold_l = hold_n = hold_all = n_w = n_l = 0
    start = start or 0
    cum, peak, peak_t, day_net, day_list = 0, start, None, {}, []
    for t in lst:
        v = t['netBase']
        s['net'] += v
        s['fees'] += t['feesBase']
        s['gross'] += t['grossBase']
        if t['dir'] > 0:
            s['longN'] += 1
            s['longNet'] += v
        else:
            s['shortN'] += 1
            s['shortNet'] += v
        if t['net'] > 0:
            s['wins'] += 1
            s['grossWin'] += v
            streak_w += 1
            streak_l = 0
            if t['holdSec'] is not None:
                hold_w += t['holdSec']
                n_w += 1
        elif t['net'] < 0:
            s['losses'] += 1
            s['grossLoss'] -= v
            streak_l += 1
            streak_w = 0
            if t['holdSec'] is not None:
                hold_l += t['holdSec']
                n_l += 1
        else:
            s['flat'] += 1
            streak_w = streak_l = 0
        s['maxWinStreak'] = max(s['maxWinStreak'], streak_w)
        s['maxLossStreak'] = max(s['maxLossStreak'], streak_l)
        if t['holdSec'] is not None:
            hold_all += t['holdSec']
            hold_n += 1
        if s['best'] is None or v > s['best']['net']:
            s['best'] = {'id': t['id'], 'net': v}
        if s['worst'] is None or v < s['worst']['net']:
            s['worst'] = {'id': t['id'], 'net': v}
        if t['r'] is not None:
            s['rCount'] += 1
            s['rSum'] += t['r']
            if t['r'] > 0:
                s['rWins'] += 1
        cum += v
        eq = start + cum
        if eq > peak:
            peak, peak_t = eq, t['closeT']
        dd = peak - eq
        if dd > s['maxDD']:
            s['maxDD'], s['ddFrom'], s['ddTo'] = dd, peak_t, t['closeT']
            s['maxDDPct'] = dd * 100 / peak if peak > 0 and start > 0 else None
        s['curve'].append({'t': t['closeT'], 'id': t['id'], 'cum': cum})
        if t['closeDay'] not in day_net:
            day_net[t['closeDay']] = 0
            day_list.append(t['closeDay'])
        day_net[t['closeDay']] += v
    if s['n']:
        s['winRate'] = s['wins'] / s['n']
        s['expectancy'] = s['net'] / s['n']
    if s['wins']:
        s['avgWin'] = s['grossWin'] / s['wins']
    if s['losses']:
        s['avgLoss'] = s['grossLoss'] / s['losses']
    if s['avgWin'] is not None and s['avgLoss']:
        s['payoff'] = s['avgWin'] / s['avgLoss']
    if s['grossLoss'] > 0:
        s['profitFactor'] = s['grossWin'] / s['grossLoss']
    if n_w:
        s['avgHoldWin'] = rnd(hold_w / n_w)
    if n_l:
        s['avgHoldLoss'] = rnd(hold_l / n_l)
    if hold_n:
        s['avgHold'] = rnd(hold_all / hold_n)
    if s['rCount']:
        s['avgR'] = s['rSum'] / s['rCount']
    if s['maxDD'] > 0:
        s['recovery'] = s['net'] / s['maxDD']
    s['days'] = [{'day': d, 'net': day_net[d]} for d in day_list]
    if start > 0 and len(s['days']) >= 2:
        total, n = 0, len(s['days'])
        for d in s['days']:
            total += d['net'] / start
        mean, ss, down = total / n, 0, 0
        for d in s['days']:
            x = d['net'] / start - mean
            ss += x * x
            y = d['net'] / start
            if y < 0:
                down += y * y
        sd = math.sqrt(ss / (n - 1))
        if sd > 0:
            s['sharpe'] = mean / sd * math.sqrt(252)
        dsd = math.sqrt(down / n)
        if dsd > 0:
            s['sortino'] = mean / dsd * math.sqrt(252)
    return s


HOLD_BUCKETS = [
    ('h1', 'Under 5 min'), ('h2', '5 to 30 min'), ('h3', '30 min to 2 h'), ('h4', '2 h or more, same day'),
    ('h5', 'Same day, no times'), ('h6', '1 to 4 nights'), ('h7', '5 nights or more'),
]
BREAKDOWNS = [('setup', 'Setup'), ('symbol', 'Symbol'), ('side', 'Long or short'), ('weekday', 'Day of the week'), ('hour', 'Hour opened'),
              ('hold', 'Holding time'), ('mistake', 'Mistake tag'), ('account', 'Account')]
NATURAL = {'weekday', 'hour', 'hold'}


def hold_bucket(t):
    nights = t['closeDay'] - t['openDay']
    if nights >= 5:
        return 'h7'
    if nights >= 1:
        return 'h6'
    if not t['timeKnown']:
        return 'h5'
    if t['holdSec'] < 300:
        return 'h1'
    if t['holdSec'] < 1800:
        return 'h2'
    if t['holdSec'] < 7200:
        return 'h3'
    return 'h4'


def group_keys(t, by):
    if by == 'setup':
        return [t['setup'] or '(no setup)']
    if by == 'symbol':
        return [t['symbol']]
    if by == 'side':
        return ['Long' if t['dir'] > 0 else 'Short']
    if by == 'weekday':
        return [str(weekday(t['openDay']))]
    if by == 'hour':
        return ['99' if t['openSec'] is None or not t['timeKnown'] else pad2(math.floor(t['openSec'] / 3600))]
    if by == 'hold':
        return [hold_bucket(t)]
    if by == 'mistake':
        return list(t['mistakes']) if t['mistakes'] else ['(none tagged)']
    if by == 'account':
        return [t['account']]
    return ['']


def group_label(key, by):
    if by == 'weekday':
        return DAY_LONG[int(key)]
    if by == 'hour':
        return 'Time not given' if key == '99' else key + ':00 to ' + key + ':59'
    if by == 'hold':
        for k, label in HOLD_BUCKETS:
            if k == key:
                return label
    return key


def breakdown(trades, by):
    groups, keys = {}, []
    for t in usable(trades):
        for k in group_keys(t, by):
            if k not in groups:
                groups[k] = []
                keys.append(k)
            groups[k].append(t)
    rows = []
    for k in keys:
        g = groups[k]
        net = wins = losses = gw = gl = r_n = fees = 0
        r_s = 0
        for t in g:
            net += t['netBase']
            fees += t['feesBase']
            if t['net'] > 0:
                wins += 1
                gw += t['netBase']
            elif t['net'] < 0:
                losses += 1
                gl -= t['netBase']
            if t['r'] is not None:
                r_n += 1
                r_s += t['r']
        rows.append({'key': k, 'label': group_label(k, by), 'n': len(g), 'wins': wins, 'losses': losses, 'winRate': wins / len(g), 'net': net, 'fees': fees,
                     'avg': net / len(g), 'profitFactor': gw / gl if gl > 0 else None, 'avgR': r_s / r_n if r_n else None, 'rCount': r_n})
    if by in NATURAL:
        return sort_by(rows, lambda a, b: cmp(a['key'], b['key']))
    return sort_by(rows, lambda a, b: (b['net'] - a['net']) or (b['n'] - a['n']) or cmp(a['label'], b['label']))


def weekly(trades):
    by_week, keys = {}, []
    for t in usable(trades):
        w = week_start(t['closeDay'])
        if w not in by_week:
            by_week[w] = {'week': w, 'n': 0, 'net': 0, 'wins': 0}
            keys.append(w)
        by_week[w]['n'] += 1
        by_week[w]['net'] += t['netBase']
        if t['net'] > 0:
            by_week[w]['wins'] += 1
    return [by_week[k] for k in sorted(keys)]


def r_histogram(trades):
    edges = []
    e = -3
    while e < 4:
        edges.append(e)
        e += 0.5
    counts = [0] * len(edges)
    for t in usable(trades):
        if t['r'] is None:
            continue
        i = math.floor((t['r'] + 3) / 0.5)
        i = max(0, min(len(counts) - 1, i))
        counts[i] += 1
    return [{'from': e, 'to': e + 0.5, 'n': counts[i]} for i, e in enumerate(edges)]


def filter_trades(trades, account='', start=None, end=None):
    """Trades for an account and a span of days (closing day, or opening day for open trades)."""
    out = []
    for t in trades:
        if account and t['account'] != account:
            continue
        d = t['closeDay'] if t['status'] == 'closed' else t['openDay']
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        out.append(t)
    return out


SKIP_RULES = ['maxTradesPerDay', 'maxDailyLoss', 'tradingWindow', 'coolOff']


def what_if(result, account='', start=None, end=None):
    """An estimate, trade by trade, of keeping to the rules: skip the trades the rules ruled out, size oversized trades
    down to the risk limit, and take every stop as planned (the loss before fees no bigger than the planned risk). Later trades are left as they were."""
    lst = usable(filter_trades(result['closed'], account, start, end))
    out = {'actual': 0, 'combined': 0, 'n': len(lst), 'skip': {'n': 0, 'change': 0}, 'size': {'n': 0, 'change': 0}, 'cap': {'n': 0, 'change': 0}}
    for t in lst:
        v = t['netBase']
        out['actual'] += v
        skipped = any(b in SKIP_RULES for b in t['breaches'])
        scale = t['riskLimit'] / t['maxRisk'] if 'maxRiskPct' in t['breaches'] and t['riskLimit'] is not None and t['maxRisk'] and t['maxRisk'] > 0 else 1
        floor = -rnd((t['plannedRisk'] + t['fees']) * t['rate']) if t['plannedRisk'] is not None and t['gross'] < -t['plannedRisk'] else None
        if skipped:
            out['skip']['n'] += 1
            out['skip']['change'] -= v
        if scale < 1:
            out['size']['n'] += 1
            out['size']['change'] += rnd(v * scale) - v
        if floor is not None:
            out['cap']['n'] += 1
            out['cap']['change'] += (floor if floor > v else v) - v
        if skipped:
            continue
        w = rnd(v * scale) if scale < 1 else v
        if floor is not None:
            f2 = rnd(floor * scale) if scale < 1 else floor
            if f2 > w:
                w = f2
        out['combined'] += w
    return out


def start_balance(result, accounts):
    """The starting balances of some accounts in the base currency (0 when none is set)."""
    settings = result['settings']
    total, found = 0, False
    for a in accounts:
        acc = account_settings(settings, a)
        v = parse_cents(acc['start']) if acc.get('start') else None
        if v is not None and v > 0:
            cur = acc.get('currency') or currency_of_account(result['trades'], a, settings['base'])
            rate = fx_rate(settings, cur)
            if rate is not None:
                total += rnd(v * rate)
                found = True
    return total if found else 0
