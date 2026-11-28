"""Combining several statements: spotting re-exports of one account and removing repeats."""

import functools
import math

from .common import cmp, js_regex, js_string, round_half_up
from .payees import payee_key

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
                              'share': round_half_up(match / in_window * 100), 'other': a['name'], 'kind': 'overlap'})
                break
    # A later file that does not overlap: the same account if most of its payees appear in the
    # months just before it, and its name matched no other file.
    for j, later_st in enumerate(statements):
        if not later_st or not later_st.get('transactions') or len(later_st['transactions']) < 8 \
                or later_st.get('accountGiven'):
            continue
        if any(k != j and o and o.get('transactions') and o['account'] == later_st['account']
               for k, o in enumerate(statements)):
            continue
        later = payee_set(later_st['transactions'], -math.inf)
        if len(later) < 3:
            continue
        best = None
        for k, e in enumerate(statements):
            if k == j or not e or not e.get('transactions') or e['account'] == later_st['account']:
                continue
            if e['end'] >= later_st['start'] or later_st['start'] - e['end'] > 45:
                continue
            earlier = payee_set(e['transactions'], e['end'] - 90)
            share = len([key for key in later if key in earlier]) / len(later)
            if share >= 0.5 and (best is None or share > best[1]):
                best = (e, share)
        if best:
            was = later_st['account']
            later_st['account'] = best[0]['account']
            for t in later_st['transactions']:
                t['account'] = best[0]['account']
            notes.append({'file': later_st['name'], 'account': best[0]['account'], 'was': was,
                          'share': round_half_up(best[1] * 100), 'other': best[0]['name'], 'kind': 'follows'})
    return notes


def payee_set(transactions, from_day):
    """The payees money went out to, from a given day on."""
    return {payee_key(t['desc']): 1 for t in transactions if t['amount'] < 0 and t['day'] >= from_day}


def separate_generic_accounts(statements):
    """Files whose name says nothing get their own account until their payments show they belong with another."""
    seen = 0
    for st in statements:
        if not st or st.get('accountGiven') or st['account'] != 'Account' or not st.get('transactions'):
            continue
        seen += 1
        if seen > 1:
            st['account'] = 'Account ' + str(seen)
            for t in st['transactions']:
                t['account'] = st['account']
