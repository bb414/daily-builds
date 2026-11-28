"""The weekly review: the week's figures, what changed, the breaches, plain-English notes and text for a team chat.

Mirrors weekReview, reviewNotes and reviewText in the browser model.
"""

from .common import (DAY, cmp, fmt_day_month_year, fmt_duration, fmt_num, fmt_pct, fmt_price, fmt_qty, fmt_r, fmt_short, money, plural, rnd,
                     sort_by, week_label)
from .matching import RULES, currency_of_account, fx_rate
from .stats import breakdown, filter_trades, start_balance, stats, usable


def week_review(result, week, account=''):
    base = result['settings']['base']
    accounts = [account] if account else result['accounts']
    start = start_balance(result, accounts)
    in_week = filter_trades(result['closed'], account, week, week + 6)
    before = filter_trades(result['closed'], account, None, week - 1)
    start_of_week = start
    for t in usable(before):
        start_of_week += t['netBase']
    s = stats(in_week, start_of_week)
    prev_weeks = []
    for w in range(1, 5):
        ws = week - 7 * w
        tr = filter_trades(result['closed'], account, ws, ws + 6)
        if usable(tr):
            prev_weeks.append(stats(tr))
    prev = None
    if prev_weeks:
        pn = pnet = pw = 0
        for p in prev_weeks:
            pn += p['n']
            pnet += p['net']
            pw += p['wins']
        prev = {'weeks': len(prev_weeks), 'n': pn, 'net': pnet, 'perWeek': pnet / len(prev_weeks), 'expectancy': pnet / pn if pn else None,
                'winRate': pw / pn if pn else None}
    breaches = [b for b in result['breaches'] if (not account or b['account'] == account) and week <= b['day'] <= week + 6]
    breach_count = {}
    for b in breaches:
        breach_count[b['rule']] = breach_count.get(b['rule'], 0) + 1
    broke, kept = {'n': 0, 'net': 0}, {'n': 0, 'net': 0}
    for t in usable(in_week):
        x = broke if t['breaches'] else kept
        x['n'] += 1
        x['net'] += t['netBase']
    end_t = (week + 7) * DAY
    open_at_end = []
    for t in result['trades']:
        if account and t['account'] != account:
            continue
        if t['openT'] >= end_t:
            continue
        if t['status'] == 'closed' and t['closeT'] < end_t:
            continue
        q = 0
        for leg in t['legs']:
            if leg['day'] * DAY + (0 if leg['sec'] is None else leg['sec']) >= end_t:
                continue
            q += leg['q'] if leg['role'] in ('open', 'add') else -leg['q']
        if q > 0:
            open_at_end.append({'id': t['id'], 'account': t['account'], 'symbol': t['symbol'], 'dir': t['dir'], 'q': q, 'avgEntry': t['avgEntry'],
                                'openDay': t['openDay'], 'currency': t['currency']})
    fees = 0
    for e in result['unattached']:
        if (not account or e['account'] == account) and e['day'] is not None and week <= e['day'] <= week + 6:
            rate = fx_rate(result['settings'], currency_of_account(result['trades'], e['account'], base))
            if rate is not None:
                fees += rnd(e['amount'] * rate)
    untagged = no_risk = 0
    for t in usable(in_week):
        if not t['setup']:
            untagged += 1
        if t['plannedRisk'] is None:
            no_risk += 1
    review = {
        'week': week, 'account': account, 'base': base, 'label': week_label(week), 'start': start_of_week, 'stats': s, 'prev': prev,
        'bySetup': breakdown(in_week, 'setup'), 'bySymbol': breakdown(in_week, 'symbol'),
        'byMistake': [r for r in breakdown(in_week, 'mistake') if r['key'] != '(none tagged)'],
        'byHour': breakdown(in_week, 'hour'), 'byHold': breakdown(in_week, 'hold'),
        'breaches': breaches, 'breachCount': breach_count, 'broke': broke, 'kept': kept, 'openAtEnd': open_at_end, 'unattachedFees': fees,
        'untagged': untagged, 'noRisk': no_risk, 'trades': [t['id'] for t in usable(in_week)],
    }
    review['notes'] = review_notes(review)
    return review


def review_notes(rv):
    s, base, notes = rv['stats'], rv['base'], []
    if not s['n']:
        return ['No trades closed this week.']
    if s['gross'] > 0 and s['net'] <= 0:
        notes.append('Before fees the week made ' + money(s['gross'], base) + '; fees of ' + money(s['fees'], base) + ' turned it into ' + money(s['net'], base, sign=True) + '.')
    elif s['gross'] > 0 and s['fees'] * 4 >= s['gross']:
        notes.append('Fees took ' + fmt_pct(s['fees'] / s['gross']) + ' of the profit before fees (' + money(s['fees'], base) + ' of ' + money(s['gross'], base) + ').')
    setups = [r for r in rv['bySetup'] if r['key'] != '(no setup)' and r['n'] >= 2]
    if len(setups) >= 2:
        top, bottom = setups[0], setups[-1]
        if top['net'] > 0:
            notes.append(top['label'] + ' made the most: ' + money(top['net'], base, sign=True) + ' over ' + plural(top['n'], 'trade') + ' (%d won).' % top['wins'])
        if bottom['net'] < 0:
            notes.append(bottom['label'] + ' cost the most: ' + money(bottom['net'], base, sign=True) + ' over ' + plural(bottom['n'], 'trade') + ' (%d won).' % bottom['wins'])
    if rv['broke']['n']:
        notes.append(plural(rv['broke']['n'], 'trade') + ' broke at least one rule and made ' + money(rv['broke']['net'], base, sign=True) + '; the '
                     + plural(rv['kept']['n'], 'trade') + ' that kept to every rule made ' + money(rv['kept']['net'], base, sign=True) + '.')
    else:
        notes.append('Every trade kept to the rules this week.')
    if s['avgHoldWin'] is not None and s['avgHoldLoss'] is not None and s['avgHoldLoss'] >= s['avgHoldWin'] * 1.5 and s['avgHoldLoss'] >= 120:
        notes.append('Losing trades were held ' + fmt_num(s['avgHoldLoss'] / s['avgHoldWin'], 1) + ' times as long as winners ('
                     + fmt_duration(s['avgHoldLoss']) + ' against ' + fmt_duration(s['avgHoldWin']) + ').')
    hours = sort_by([r for r in rv['byHour'] if r['n'] >= 3 and r['key'] != '99'], lambda a, b: (a['net'] - b['net']) or cmp(a['key'], b['key']))
    if len(hours) >= 2 and hours[0]['net'] < 0:
        notes.append('Trades opened ' + hours[0]['label'] + ' were the weakest hour: ' + money(hours[0]['net'], base, sign=True) + ' over ' + plural(hours[0]['n'], 'trade') + '.')
    if rv['prev'] and rv['prev']['expectancy'] is not None and s['expectancy'] is not None:
        notes.append('Expectancy ' + money(rnd(s['expectancy']), base, sign=True) + ' a trade, against ' + money(rnd(rv['prev']['expectancy']), base, sign=True)
                     + ' over the previous ' + plural(rv['prev']['weeks'], 'week') + ' with trades.')
    if rv['untagged'] or rv['noRisk']:
        parts = []
        if rv['untagged']:
            parts.append(plural(rv['untagged'], 'trade') + ' with no setup')
        if rv['noRisk']:
            parts.append(plural(rv['noRisk'], 'trade') + ' with no stop or planned risk')
        notes.append('Journal gaps: ' + ' and '.join(parts) + '. Fill them in so the setup and R figures cover the whole week.')
    return notes


def trade_name(t):
    return t['symbol'] + ' ' + ('long' if t['dir'] > 0 else 'short') + ' ' + fmt_short(t['openDay'])


def review_text(rv, result):
    """The review as plain text for a team chat."""
    s, base, lines = rv['stats'], rv['base'], []
    by_id = {t['id']: t for t in result['trades']}
    lines.append('WEEKLY TRADE REVIEW: ' + rv['label'] + ' to ' + fmt_day_month_year(rv['week'] + 6) + (' (' + rv['account'] + ')' if rv['account'] else ' (all accounts)'))
    if not s['n']:
        lines.append('No trades closed this week.')
    else:
        lines.append('Net after fees: ' + money(s['net'], base, sign=True) + ' from ' + plural(s['n'], 'closed trade') + ' (fees ' + money(s['fees'], base)
                     + ', before fees ' + money(s['gross'], base, sign=True) + ')')
        lines.append('Win rate ' + fmt_pct(s['winRate']) + ' (%d won, %d lost' % (s['wins'], s['losses']) + (', %d flat' % s['flat'] if s['flat'] else '')
                     + '), expectancy ' + money(rnd(s['expectancy']), base, sign=True) + ' a trade, profit factor '
                     + ('n/a (no losses)' if s['profitFactor'] is None else fmt_num(s['profitFactor'], 2)))
        lines.append('Average win ' + ('n/a' if s['avgWin'] is None else money(rnd(s['avgWin']), base)) + ', average loss '
                     + ('n/a' if s['avgLoss'] is None else money(rnd(s['avgLoss']), base))
                     + ('; average ' + fmt_r(s['avgR']) + ' on ' + plural(s['rCount'], 'trade') + ' with planned risk' if s['rCount'] else ''))
        best, worst = by_id[s['best']['id']], by_id[s['worst']['id']]
        lines.append('Best: ' + trade_name(best) + ' ' + money(s['best']['net'], base, sign=True) + (' (' + best['setup'] + ')' if best['setup'] else '')
                     + '. Worst: ' + trade_name(worst) + ' ' + money(s['worst']['net'], base, sign=True) + (' (' + worst['setup'] + ')' if worst['setup'] else ''))
        lines.append('Largest drop from a high this week: ' + money(s['maxDD'], base) + '; longest losing run: ' + plural(s['maxLossStreak'], 'trade'))
        setups = [r['label'] + ' ' + money(r['net'], base, sign=True) + ' (%d)' % r['n'] for r in rv['bySetup'][:6]]
        if setups:
            lines.append('Setups: ' + '; '.join(setups))
    if rv['breaches']:
        parts = [x['broken'] + ' x%d' % rv['breachCount'][x['id']] for x in RULES if rv['breachCount'].get(x['id'])]
        lines.append('Rule breaches: %d (' % len(rv['breaches']) + ', '.join(parts) + ')')
    else:
        lines.append('Rule breaches: none')
    if rv['byMistake']:
        lines.append('Mistakes tagged: ' + '; '.join(r['label'] + ' x%d (' % r['n'] + money(r['net'], base, sign=True) + ')' for r in rv['byMistake']))
    if rv['openAtEnd']:
        lines.append('Open at the end of the week: ' + '; '.join(o['symbol'] + (' long ' if o['dir'] > 0 else ' short ') + fmt_qty(o['q']) + ' at ' + fmt_price(o['avgEntry'])
                                                               for o in rv['openAtEnd']))
    if rv['unattachedFees']:
        lines.append('Fees not tied to a trade: ' + money(rv['unattachedFees'], base))
    if rv['notes']:
        lines.append('')
        lines.append('Notes:')
        for n in rv['notes']:
            lines.append('- ' + n)
    lines.append('')
    lines.append('Built from our own fills exports. Not financial advice.')
    return '\n'.join(lines) + '\n'
