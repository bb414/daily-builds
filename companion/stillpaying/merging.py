"""Combining several statements: spotting re-exports of one account and removing repeats."""

import functools

from .common import cmp, js_regex, js_string, round_half_up

_NOT_ALNUM = js_regex(r'[^A-Z0-9]+')


def _desc_key(t):
    return _NOT_ALNUM.sub('', js_string(t['desc']).upper())


def dedupe_key(t):
    """What makes two payments the same one: account, day, amount and the letters and digits of the description."""
    return t['account'] + '|' + str(t['day']) + '|' + str(t['amount']) + '|' + _desc_key(t)


def _transaction_order(a, b):
    return (a['day'] - b['day']) or cmp(a['account'], b['account']) or (a['amount'] - b['amount']) \
        or cmp(a['desc'], b['desc'])


def merge_statements(statements):
    """Combine statements.

    Where two files cover the same account and the same days, a payment that
    appears in both is kept once; identical payments on the same day in one
    file are all kept.
    """
    counts, first_seen, order = {}, {}, []
    for st in statements:
        if not st or st.get('transactions') is None:
            continue
        local = {}
        for t in st['transactions']:
            local.setdefault(dedupe_key(t), []).append(t)
        for k, group in local.items():
            have, now = counts.get(k, 0), len(group)
            if k not in first_seen:
                first_seen[k] = []
                order.append(k)
            if now > have:
                first_seen[k].extend(group[have:now])
                counts[k] = now
    out = [t for k in order for t in first_seen[k]]
    total = sum(len(st['transactions']) for st in statements if st and st.get('transactions') is not None)
    out.sort(key=functools.cmp_to_key(_transaction_order))
    accounts = {}
    for st in statements:
        if not st or not st.get('transactions'):
            continue
        a = accounts.get(st['account'])
        if a is None:
            a = accounts[st['account']] = {'account': st['account'], 'start': st['start'], 'end': st['end'],
                                           'files': [], 'closing': None}
        a['start'] = min(a['start'], st['start'])
        a['end'] = max(a['end'], st['end'])
        a['files'].append(st['name'])
        if st.get('closing') and (not a['closing'] or st['closing']['day'] >= a['closing']['day']):
            a['closing'] = st['closing']
    return {'transactions': out, 'duplicates': total - len(out), 'accounts': [accounts[k] for k in sorted(accounts)]}


def link_same_accounts(statements):
    """Spot two files that are the same account exported twice.

    If at least 80% of one file's payments in the days both cover also appear
    in the other, they are labelled as one account so the overlap is only
    counted once. Files given an account name by the user are left alone.
    Returns a note for each file relabelled.
    """
    notes = []
    for j, b in enumerate(statements):
        if not b or not b.get('transactions') or b.get('accountGiven'):
            continue
        for i, a in enumerate(statements):
            if i == j or not a or not a.get('transactions') or a['account'] == b['account']:
                continue
            if len(b['transactions']) > len(a['transactions']):
                continue
            start, end = max(a['start'], b['start']), min(a['end'], b['end'])
            if end - start < 7:
                continue
            keys = {}
            for t in a['transactions']:
                if start <= t['day'] <= end:
                    k = str(t['day']) + '|' + str(t['amount']) + '|' + _desc_key(t)
                    keys[k] = keys.get(k, 0) + 1
            in_window = match = 0
            for t in b['transactions']:
                if not start <= t['day'] <= end:
                    continue
                in_window += 1
                k = str(t['day']) + '|' + str(t['amount']) + '|' + _desc_key(t)
                if keys.get(k):
                    keys[k] -= 1
                    match += 1
            if in_window >= 8 and match / in_window >= 0.8:
                was = b['account']
                b['account'] = a['account']
                for t in b['transactions']:
                    t['account'] = a['account']
                notes.append({'file': b['name'], 'account': a['account'], 'was': was,
                              'share': round_half_up(match / in_window * 100), 'other': a['name']})
                break
    return notes
