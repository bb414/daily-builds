"""Presentation helpers shared by the terminal output, the HTML report and the Markdown changes.

None of this is part of the browser model: it turns the model's results into
the short labels, headline figures, upcoming lists and summaries that the
companion's own jobs print and write.
"""

from .common import money, plain_money
from .dates import iso, long_date
from .detect import CADENCE_BY_ID
from .outputs import DECISION_LABELS, find_series, to_csv
from .planning import forecast, is_cost, plan

# Short names for the checks (flags) the model raises, for tables and labels.
FLAG_LABELS = {
    'stopped': 'stopped', 'intro': 'intro ended', 'rise': 'price up', 'drop': 'price down', 'creep': 'creeping up',
    'double': 'charged twice', 'new': 'new', 'late': 'not seen yet', 'overlap': 'overlap', 'same-payee': 'same payee',
}


def flag_label(flag):
    """The short label for one flag."""
    return FLAG_LABELS.get(flag['id'], flag['id'])


def status_label(s):
    """Active, Late (due but not in the statement yet) or Stopped."""
    if s['status'] == 'stopped':
        return 'Stopped'
    return 'Late' if s.get('late') else 'Active'


def cadence_label(s):
    """How often, in words: Monthly, Every two weeks ..."""
    return CADENCE_BY_ID[s['cadence']]['label']


def decision_label(decisions, sid):
    """Keep, Cancel, Review, Not a cost, or '' when undecided."""
    d = decisions.get(sid) or {}
    return DECISION_LABELS.get(d.get('decision'), '')


# What to do when a payment carries on after you cancelled, as the app says it.
STILL_CHARGING_ADVICE = {
    'card': 'If you did cancel, ask your card provider to stop the recurring payment and claim it back.',
    'direct debit': 'If you did cancel, claim it back from your bank under the Direct Debit Guarantee.',
}


def headline(result, decisions):
    """The figures that lead a review: committed spending, counts and the next payday."""
    totals = plan(result, decisions)['totals']
    active = [s for s in result['series'] if s['status'] == 'active']
    return {'monthly': totals['monthly'], 'annual': totals['annual'], 'regulars': len(active),
            'costs': totals['count'], 'payday': result['payday'],
            # Counted the way the app counts them: costs with a warning or an alert.
            'checks': len([s for s in active if is_cost(s) and any(f['tone'] in ('warn', 'alert') for f in s['flags'])])}


def upcoming(result, decisions, days=31):
    """Payments leaving in the next few days, with a running total of the ones you are keeping.

    Payments marked 'Not a cost' are left out; ones you plan to cancel are
    listed but not added to the total.
    """
    rows, running = [], 0
    for it in forecast(result, days, decisions):
        if it['direction'] != 'out' or it['decision'] == 'ignore':
            continue
        cancelling = it['decision'] == 'cancel'
        if not cancelling:
            running += it['amount']
        s = find_series(result, it['id'])
        rows.append({'day': it['day'], 'name': it['name'], 'amount': it['amount'], 'late': it['late'],
                     'about': s['amounts']['kind'] == 'variable', 'cancelling': cancelling, 'running': running})
    return rows


def signed_money(pence):
    """A change in money with its sign: +£1.00, -£2.50, £0.00."""
    return ('+' if pence > 0 else '') + money(pence)


def price_history_csv(result):
    """One row per regular payment per payment seen, with the change from the payment before."""
    rows = [['Series id', 'Name', 'Date', 'Amount', 'Change from previous']]
    for s in result['series']:
        previous = None
        for p in s['payments']:
            change = ''
            if previous is not None:
                change = ('+' if p['amount'] > previous else '') + plain_money(p['amount'] - previous)
            rows.append([s['id'], s['name'], iso(p['day']), plain_money(p['amount']), change])
            previous = p['amount']
    return to_csv(rows)


def _section(lines, heading, items, empty):
    lines += ['', '## ' + heading, '']
    lines += ['- ' + item for item in items] if items else [empty]


def changes_markdown(result, decisions, since, previous_file=None):
    """A short Markdown summary of what changed since the last review, ready to paste into notes or an email."""
    lines = ['# Still paying? Review for ' + long_date(result['asOf']), '']
    if since is None:
        lines.append('This is your first review, so there is nothing to compare with yet. '
                     'Next month this will show what has changed.')
    else:
        lines.append('Changes since your last review on ' + long_date(since['reviewedOn'])
                     + (' (' + previous_file + ')' if previous_file else '') + '.')
        charging = []
        for c in since['stillCharging']:
            paid = ', '.join(money(p['amount']) + ' on ' + long_date(p['day']) for p in c['payments'])
            charging.append(c['name'] + ': ' + paid + ', after you decided to cancel on ' + long_date(c['decidedOn'])
                            + '. ' + STILL_CHARGING_ADVICE.get(c['method'], 'Check it was cancelled, and ask for a refund.'))
        _section(lines, 'Still being charged after you decided to cancel', charging, 'Nothing. Good.')
        _section(lines, 'New regular payments',
                 [n['name'] + ': ' + money(n['amount']) + ' ' + CADENCE_BY_ID[n['cadence']]['label'].lower()
                  + ', first taken on ' + long_date(n['first']) + '.' for n in since['newSince']], 'None.')
        _section(lines, 'Price changes',
                 [p['name'] + ': ' + money(p['from']) + ' to ' + money(p['to'])
                  + ' (' + signed_money(p['to'] - p['from']) + ').' for p in since['priceChanges']], 'None.')
        _section(lines, 'Stopped', [s['name'] + ': last paid on ' + long_date(s['last']) + '.'
                                    for s in since['stoppedSince']], 'None.')
    rows = upcoming(result, decisions, 31)
    due = []
    for r in rows:
        note = ' (you plan to cancel)' if r['cancelling'] else ' (due, not in your statement yet)' if r['late'] else ''
        due.append(long_date(r['day']) + ': ' + ('about ' if r['about'] else '') + money(r['amount']) + ' '
                   + r['name'] + note)
    _section(lines, 'Due in the next 31 days', due, 'Nothing is due.')
    kept = [r for r in rows if not r['cancelling']]
    if rows:
        lines += ['', 'Total: ' + money(rows[-1]['running']) + ' across ' + str(len(kept)) + ' payment'
                  + ('' if len(kept) == 1 else 's') + (', not counting the ones you plan to cancel.'
                                                       if len(kept) < len(rows) else '.')]
    return '\n'.join(lines) + '\n'
