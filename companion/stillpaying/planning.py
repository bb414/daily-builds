"""Looking ahead: the forecast of payments to come, suggestions, decisions and the plan.

Also compares a fresh analysis with a saved review ("since your last
review"): new regulars, price changes, stopped ones and anything still being
charged after you decided to cancel it.
"""

import functools

from .common import cmp, is_number, money, pad2, truthy
from .dates import from_iso, long_date, ymd
from .detect import CADENCE_BY_ID, last_nominal, schedule_from
from .payees import CATEGORY_BY_ID, category_of

DECISIONS = ['keep', 'cancel', 'review', 'ignore']


def expected_amount(s, day):
    """What a payment on a given day is likely to be.

    For a bill that varies, with a year of history, it is what was paid
    around the same day last year; otherwise the current typical amount.
    """
    if s['amounts']['kind'] != 'variable' or not s.get('seasonal'):
        return s['typical']
    target, best = day - 365, None
    for p in s['payments']:
        e = abs(p['day'] - target)
        if e <= 20 and (best is None or e < best[0]):
            best = (e, p['amount'])
    return best[1] if best else s['typical']


def _forecast_order(a, b):
    return (a['day'] - b['day']) or cmp(a['direction'], b['direction']) or (b['amount'] - a['amount']) \
        or cmp(a['id'], b['id'])


def forecast(result, days, decisions=None):
    """Every expected payment from the review date for a number of days, for active series and income."""
    decisions = decisions or {}
    as_of = result['asOf']
    until = as_of + days - 1
    items = []
    for s in result['series'] + result['income']:
        if s['status'] != 'active':
            continue
        d = decisions.get(s['id']) or {}
        for i, u in enumerate(schedule_from(s, last_nominal(s), 2000, until + 10)):
            due, late = u['due'], False
            if due < as_of:
                if i != 0:
                    continue
                due, late = as_of, True
            if due > until:
                continue
            variable = s['amounts']['kind'] == 'variable'
            items.append({'day': due, 'nominal': u['nominal'], 'id': s['id'], 'name': s['name'],
                          'amount': expected_amount(s, u['due']), 'direction': s['direction'],
                          'category': s['category'], 'decision': d.get('decision') or None, 'late': late,
                          'low': s['amounts']['min'] if variable else s['typical'],
                          'high': s['amounts']['max'] if variable else s['typical']})
    items.sort(key=functools.cmp_to_key(_forecast_order))
    return items


def month_totals(items, include_decisions=False):
    """Total due in each calendar month of a forecast, split into essential and optional."""
    months = {}
    for it in items:
        if it['direction'] != 'out':
            continue
        if not include_decisions and it['decision'] in ('cancel', 'ignore'):
            continue
        cat = CATEGORY_BY_ID.get(it['category'])
        if cat and not cat['cost']:
            continue
        y, m, _ = ymd(it['day'])
        k = str(y) + '-' + pad2(m)
        if k not in months:
            months[k] = {'key': k, 'y': y, 'm': m, 'total': 0, 'essential': 0, 'optional': 0, 'count': 0}
        months[k]['total'] += it['amount']
        months[k]['count'] += 1
        if cat and cat['essential']:
            months[k]['essential'] += it['amount']
        else:
            months[k]['optional'] += it['amount']
    return [months[k] for k in sorted(months)]


def is_cost(s):
    """An active payment out that counts as spending (not savings or a transfer to yourself)."""
    cat = CATEGORY_BY_ID.get(s['category'])
    return s['direction'] == 'out' and s['status'] == 'active' and (not cat or cat['cost'])


def suggest(s):
    """A suggested decision for a series, with the reason, before the user decides."""
    cat = category_of(s['category'])
    ids = [f['id'] for f in s['flags']]
    if s['status'] == 'stopped':
        return {'decision': None, 'text': 'Looks stopped already. Check it does not restart.'}
    if not cat['cost']:
        return {'decision': 'ignore', 'text': 'Money to your own savings, not a cost.'}
    if 'double' in ids:
        return {'decision': 'review', 'text': 'Check the double charge with the company.'}
    if 'intro' in ids:
        return {'decision': 'review', 'text': 'The intro price has ended. Still worth the full price?'}
    if 'overlap' in ids:
        return {'decision': 'review', 'text': 'Do you need all of these?'}
    if any(f['id'] == 'rise' and f['tone'] == 'warn' for f in s['flags']):
        return {'decision': 'review', 'text': 'The price went up recently. Shop around or ask for a better deal.'}
    if 'new' in ids:
        return {'decision': 'review', 'text': 'New this month. Did you mean to sign up?'}
    if cat['essential']:
        return {'decision': 'keep', 'text': 'An essential bill. Keep, but check you are on a good deal.'}
    return {'decision': 'review', 'text': 'Optional. Did you use it in the last month?'}


def notice_days_for(s):
    """Working days of notice to give before a payment: three for mandates, two for cards."""
    return 3 if s['method'] in ('direct debit', 'standing order') else 2


def how_to_stop(s):
    """How to stop a payment, step by step, by how it is paid."""
    method, name = s['method'], s['name']
    if method == 'direct debit':
        return ['Cancel the service with ' + name + ' first, so you are not left owing anything under the contract.',
                'Then cancel the Direct Debit in your banking app, or ask your bank to, at least a couple of working '
                'days before it is due.',
                'If a Direct Debit is taken in error after that, the Direct Debit Guarantee lets you claim it back '
                'from your bank.']
    if method == 'standing order':
        return ['You set up standing orders, so only you can stop them: cancel it in your banking app or online '
                'banking.',
                'Do it at least a working day before it is due.',
                'Tell the person or company you pay, so they are not surprised.']
    if method == 'card':
        return ['Cancel in your account settings on ' + name + "'s website or app (or the app store you subscribed "
                'through).',
                'Keep the confirmation email or a screenshot.',
                'If it charges you again after you cancelled, ask your card provider to stop the recurring payment '
                'and dispute the charge.']
    if method == 'transfer':
        return ['This is a payment you send yourself. Stop sending it, or cancel any scheduled transfer in your '
                'banking app.']
    return ['Find how you pay ' + name + ' (Direct Debit, card or standing order) and cancel with the company first.',
            'Then stop the payment in your banking app if it is a Direct Debit or standing order.']


def cancel_message(s, details=None):
    """A ready-to-send message asking a company to cancel."""
    details = details or {}
    your_name = details.get('name') or '[your name]'
    ref = details.get('account') or '[your account email or customer number]'
    last = s['payments'][-1]
    what = 'membership' if s['category'] in ('gym', 'memberships') else 'subscription'
    return '\n'.join([
        'Subject: Please cancel my ' + s['name'] + ' ' + what,
        '',
        'Hello,',
        '',
        'Please cancel my ' + s['name'] + ' ' + what + ' and stop all further payments from today.',
        '',
        'My account: ' + ref,
        'Last payment: ' + money(last['amount']) + ' on ' + long_date(last['day']),
        '',
        'Please confirm in writing that it is cancelled and that no further payments will be taken. If any payment '
        'is taken after today, I will ask for it to be refunded.',
        '',
        'Thank you,',
        your_name,
    ])


def plan(result, decisions=None, details=None):
    """Summarise decisions: committed spending, savings from cancelling, and the list of things to cancel."""
    decisions = decisions or {}
    as_of = result['asOf']
    fc = forecast(result, 365, decisions)
    costs = [s for s in result['series'] if is_cost(s)]
    totals = {'monthly': 0, 'annual': 0, 'essentialMonthly': 0, 'optionalMonthly': 0, 'keepMonthly': 0,
              'cancelMonthly': 0, 'cancelAnnual': 0, 'cancelNext12': 0, 'reviewMonthly': 0, 'undecidedMonthly': 0,
              'count': len(costs)}
    actions = []
    for s in costs:
        d = decisions.get(s['id']) or {}
        decision = d.get('decision') or None
        if decision == 'ignore':
            continue
        totals['monthly'] += s['monthly']
        totals['annual'] += s['annual']
        if category_of(s['category'])['essential']:
            totals['essentialMonthly'] += s['monthly']
        else:
            totals['optionalMonthly'] += s['monthly']
        if decision == 'keep':
            totals['keepMonthly'] += s['monthly']
        elif decision == 'cancel':
            totals['cancelMonthly'] += s['monthly']
            totals['cancelAnnual'] += s['annual']
            next12 = sum(it['amount'] for it in fc if it['id'] == s['id'])
            totals['cancelNext12'] += next12
            notice = d['noticeDays'] if d.get('noticeDays') is not None else notice_days_for(s)
            by = s['nextDue'] - notice if s['nextDue'] is not None else as_of
            actions.append({'id': s['id'], 'name': s['name'], 'method': s['method'], 'nextDue': s['nextDue'],
                            'cancelBy': max(by, as_of), 'amount': s['typical'], 'cadence': s['cadence'],
                            'saveNext12': next12, 'annual': s['annual'], 'steps': how_to_stop(s),
                            'message': cancel_message(s, details), 'note': d.get('note') or ''})
        elif decision == 'review':
            totals['reviewMonthly'] += s['monthly']
        else:
            totals['undecidedMonthly'] += s['monthly']
    actions.sort(key=functools.cmp_to_key(lambda a, b: (a['cancelBy'] - b['cancelBy']) or (b['amount'] - a['amount'])
                                          or cmp(a['id'], b['id'])))
    return {'totals': totals, 'actions': actions, 'forecast': fc}


def since_last_review(result, saved):
    """Compare the regulars now with a saved review.

    Reports what is new, what changed price, what stopped, and anything still
    charging after you decided to cancel it. saved is a review as read back by
    read_project (or the raw saved data); returns None without a review date.
    """
    if not saved or not truthy(saved.get('reviewedOn')):
        return None
    reviewed = saved['reviewedOn'] if is_number(saved['reviewedOn']) else from_iso(saved['reviewedOn'])
    base = reviewed or 0
    known = saved.get('known') if isinstance(saved.get('known'), dict) else {}
    decisions = saved.get('decisions') if isinstance(saved.get('decisions'), dict) else {}
    out = {'reviewedOn': reviewed, 'stillCharging': [], 'newSince': [], 'priceChanges': [], 'stoppedSince': []}
    for s in result['series']:
        d = decisions.get(s['id'])
        if isinstance(d, dict) and d.get('decision') == 'cancel':
            decided = d['decidedOn'] if is_number(d.get('decidedOn')) else (from_iso(d.get('decidedOn')) or reviewed)
            grace = d['noticeDays'] if d.get('noticeDays') is not None else notice_days_for(s)
            after = [p for p in s['payments'] if p['day'] > (decided or 0) + grace]
            if after:
                out['stillCharging'].append({'id': s['id'], 'name': s['name'], 'decidedOn': decided, 'payments': after,
                                             'total': sum(p['amount'] for p in after), 'method': s['method']})
        k = known.get(s['id'])
        if not truthy(k) and s['status'] == 'active' and s['last'] > base:
            out['newSince'].append({'id': s['id'], 'name': s['name'], 'first': s['first'], 'amount': s['typical'],
                                    'cadence': s['cadence']})
        if (isinstance(k, dict) and 'typical' in k and k['typical'] != s['typical'] and s['status'] == 'active'
                and s['amounts']['kind'] != 'variable' and k.get('kind') != 'variable'):
            out['priceChanges'].append({'id': s['id'], 'name': s['name'], 'from': k['typical'], 'to': s['typical']})
        if isinstance(k, dict) and k.get('status') == 'active' and s['status'] == 'stopped':
            out['stoppedSince'].append({'id': s['id'], 'name': s['name'], 'last': s['last']})
    return out
