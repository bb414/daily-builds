"""Finding regular payments: cadences, series, their flags and the next payday.

Payments are grouped by payee, each group is split into series that follow a
cadence (weekly up to yearly), and each series is described: how often, how
much, how sure the match is, whether it has stopped, and anything worth a
second look (price rises, intro prices ending, double charges, new or
overlapping services).
"""

import functools
import math

from .common import cmp, is_number, js_regex, js_string, js_trim, money, round_half_up, slug, truthy
from .dates import DAY_NAMES, add_months, day_from_ymd, days_in_month, from_iso, iso, long_date, next_working_day, \
    nominal_in_month, ordinal, weekday, ymd
from .payees import CATEGORY_BY_ID, DUPLICATE_PRONE, METHODS, categorise, clean_description, display_name, \
    group_keys, payee_key, payment_method, tokens


def _cadence(cid, label, days, tol, minimum, per_year, months=0):
    return {'id': cid, 'label': label, 'months': months, 'days': days, 'tol': tol, 'min': minimum, 'perYear': per_year}


CADENCES = [
    _cadence('weekly', 'Weekly', 7, 1, 4, 52),
    _cadence('fortnightly', 'Every two weeks', 14, 2, 3, 26),
    _cadence('four-weekly', 'Every four weeks', 28, 1, 3, 13),
    _cadence('monthly', 'Monthly', 30.44, 4, 3, 12, months=1),
    _cadence('two-monthly', 'Every two months', 60.88, 5, 3, 6, months=2),
    _cadence('quarterly', 'Quarterly', 91.31, 7, 2, 4, months=3),
    _cadence('six-monthly', 'Every six months', 182.62, 10, 2, 2, months=6),
    _cadence('yearly', 'Yearly', 365.25, 14, 2, 1, months=12),
]
CADENCE_BY_ID = {c['id']: c for c in CADENCES}

_CARD_ACCOUNT = js_regex(r'card|credit', 'i')

# Words that suggest a single payment is a renewal worth watching.
RENEWAL_WORDS = ['ANNUAL', 'YEARLY', 'RENEWAL', 'RENEW', 'MEMBERSHIP', 'SUBSCRIPTION', 'SUBS', 'PREMIUM', 'LICENCE',
                 'LICENSE', 'INSURANCE', 'COVER', 'PRO', 'PLUS']


def anchor_day(days):
    """The nominal day of the month a monthly payment is due: the most common day, earliest on a tie."""
    counts = {}
    for d in days:
        y, m, dom = ymd(d)
        if dom >= 28 and dom == days_in_month(y, m):
            dom = 31
        counts[dom] = counts.get(dom, 0) + 1
    best = best_n = 0
    for k in sorted(counts):
        n = counts[k]
        if n > best_n or (n == best_n and k < best):
            best, best_n = k, n
    return best


def rule_anchor(days):
    """A monthly rule that every payment follows exactly, such as the last Friday of the month."""
    if len(days) < 3:
        return None
    for rule in ['LW', 'L5', 'L1', 'L2', 'L3', 'L4']:
        if not all(nominal_in_month(ymd(d)[0], ymd(d)[1], rule) == d for d in days):
            continue
        # Only worth a rule if a plain day of the month would not do.
        if len({ymd(d)[2] for d in days}) > 1:
            return rule
    # A set day, or the working day before when that day is a weekend or bank holiday (common for pay).
    counts = {}
    for d in days:
        counts[ymd(d)[2]] = counts.get(ymd(d)[2], 0) + 1
    mode, mode_n = 0, 0
    for k in counts:
        if counts[k] > mode_n or (counts[k] == mode_n and k > mode):
            mode, mode_n = k, counts[k]
    if len(counts) > 1 and all(nominal_in_month(ymd(d)[0], ymd(d)[1], 'B' + str(mode)) == d for d in days):
        return 'B' + str(mode)
    return None


def step_from(day, cad, anchor, k=1):
    """The nominal due date k steps of a cadence after a day."""
    k = k or 1
    if cad['months']:
        return add_months(day, cad['months'] * k, anchor)
    return day + cad['days'] * k


def nearest_nominal(day, anchor):
    """For monthly cadences: the nominal due date nearest to a payment day (earlier on a tie)."""
    y, m, _ = ymd(day)
    cand = []
    for dm in (-1, 0, 1):
        total = y * 12 + (m - 1) + dm
        cand.append(nominal_in_month(total // 12, total % 12 + 1, anchor))
    best = cand[0]
    for c in cand:
        if abs(day - c) < abs(day - best) or (abs(day - c) == abs(day - best) and c < best):
            best = c
    return best


def fit_cadence(days):
    """Test how well a list of payment days fits each cadence and return the best fit.

    The fit says how many gaps match one step, how many look like a missed
    payment (two steps), which payments are extra charges close to another,
    and the average error in days.
    """
    if len(days) < 2:
        return None
    best = None
    for cad in CADENCES:
        if cad['months']:
            anchor = (rule_anchor(days) or anchor_day(days)) if cad['months'] == 1 else anchor_day(days)
        else:
            anchor = 0
        matched = missed = bad = err = 0
        extras = []
        prev = days[0]
        late_tol = cad['tol']
        early_tol = min(cad['tol'], 3) if cad['months'] else cad['tol']
        for d in days[1:]:
            gap = d - prev
            if cad['months']:
                # Compare with the due date one and two steps on from the previous nominal date.
                nominal_prev = nearest_nominal(prev, anchor)
                e1 = d - step_from(nominal_prev, cad, anchor, 1)
                e2 = d - step_from(nominal_prev, cad, anchor, 2)
            else:
                e1 = gap - cad['days']
                e2 = gap - cad['days'] * 2
            if -early_tol <= e1 <= late_tol:
                matched += 1
                err += abs(e1)
                prev = d
                continue
            if -early_tol <= e2 <= late_tol:
                missed += 1
                err += abs(e2)
                prev = d
                continue
            if gap <= max(3, cad['days'] * 0.25):
                extras.append(d)
                continue
            bad += 1
            prev = d
        gaps = matched + missed + bad
        if not gaps:
            continue
        score = (matched + missed) / gaps
        mae = err / max(1, matched + missed)
        fit = {'cadence': cad['id'], 'anchor': anchor, 'matched': matched, 'missed': missed, 'bad': bad,
               'extras': extras, 'mae': mae, 'score': score}
        allowed_missed = max(1, math.floor(gaps * 0.25))
        fit['ok'] = (matched >= 1 and score >= 0.75 and missed <= allowed_missed
                     and len(extras) <= max(1, len(days) // 6) and matched >= missed)
        rank = score - mae * 0.02 - missed * 0.01
        fit['rank'] = rank
        if best is None or (fit['ok'] and not best['ok']) or (fit['ok'] == best['ok'] and rank > best['rank'] + 1e-9):
            best = fit
    return best


def median(values):
    """The middle value (the rounded mean of the middle two for an even count); 0 for none."""
    s = sorted(values)
    if not s:
        return 0
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else round_half_up((s[mid - 1] + s[mid]) / 2)


def amount_profile(payments):
    """Describe how a series' amounts behave: fixed, stepped (price changes) or variable."""
    amounts = [abs(p['amount']) for p in payments]
    runs = []
    for p, a in zip(payments, amounts):
        if runs and runs[-1]['amount'] == a:
            runs[-1]['count'] += 1
            runs[-1]['end'] = p['day']
        else:
            runs.append({'amount': a, 'count': 1, 'start': p['day'], 'end': p['day']})
    singles = len([r for r in runs if r['count'] == 1])
    if len(set(amounts)) == 1:
        kind = 'fixed'
    elif (len(runs) <= 4 and (len(runs) <= -(-len(amounts) // 2) or len(runs) == 2) and runs[-1]['count'] >= 1
          and singles <= 1 + (1 if runs[0]['count'] == 1 else 0)):
        kind = 'stepped'
    else:
        kind = 'variable'
    if kind == 'fixed':
        typical = amounts[0]
    elif kind == 'stepped':
        typical = runs[-1]['amount']
    else:
        typical = median(amounts[-3:])
    changes = []
    if kind == 'stepped':
        changes = [{'day': runs[i]['start'], 'from': runs[i - 1]['amount'], 'to': runs[i]['amount']}
                   for i in range(1, len(runs))]
    return {'kind': kind, 'typical': typical, 'min': min(amounts), 'max': max(amounts), 'changes': changes,
            'runs': runs, 'last': amounts[-1]}


def _cluster_order(x, y):
    return (x[0]['day'] - y[0]['day']) or (abs(x[0]['amount']) - abs(y[0]['amount']))


def explain_group(payments, signals=None):
    """Split a payee's payments into regular series.

    Returns {'series': [{'payments', 'fit'}], 'rest': payments that fit no series}.
    """
    if len(payments) >= 2:
        whole = fit_cadence([p['day'] for p in payments])
        mandate = bool(signals and signals.get('mandate'))
        steady = mandate or CADENCE_BY_ID[whole['cadence'] if whole else 'monthly']['months'] or steady_amounts(payments)
        if whole and whole['ok'] and not whole['extras'] and steady and (amounts_compatible(payments) or mandate):
            return {'series': [{'payments': payments, 'fit': whole}], 'rest': []}
    # Same amount, then join runs that follow on from each other (price changes, intro offers).
    by_amount, keys = {}, []
    for p in payments:
        a = abs(p['amount'])
        if a not in by_amount:
            by_amount[a] = []
            keys.append(a)
        by_amount[a].append(p)
    order = functools.cmp_to_key(_cluster_order)
    clusters = sorted((by_amount[a] for a in keys), key=order)
    merged = True
    while merged:
        merged = False
        best_pair = None
        for i, a_run in enumerate(clusters):
            for j, b_run in enumerate(clusters):
                if i == j or a_run[-1]['day'] >= b_run[0]['day'] or (len(a_run) < 2 and len(b_run) < 2):
                    continue
                ref = fit_cadence([p['day'] for p in (a_run if len(a_run) >= len(b_run) else b_run)])
                if not ref or not ref['ok']:
                    continue
                union = a_run + b_run
                uf = fit_cadence([p['day'] for p in union])
                if not uf or not uf['ok'] or uf['cadence'] != ref['cadence'] or uf['extras']:
                    continue
                cost = join_error(a_run, b_run, ref)
                if cost is None:
                    continue
                if best_pair is None or cost < best_pair[2]:
                    best_pair = (i, j, cost)
        if best_pair:
            i, j = best_pair[0], best_pair[1]
            joined = clusters[i] + clusters[j]
            clusters = [c for k, c in enumerate(clusters) if k != i and k != j]
            clusters.append(joined)
            clusters.sort(key=order)
            merged = True
    found, rest = [], []
    for c in clusters:
        if len(c) >= 2:
            f = fit_cadence([p['day'] for p in c])
            if f and f['ok'] and not busy_around(c, payments):
                found.append({'payments': c, 'fit': f})
                continue
        rest.extend(c)
    return {'series': found, 'rest': rest}


def busy_around(run, all_payments):
    """True when the payee was paid more often between a run's first and last payment than the run itself."""
    a, b = run[0]['day'], run[-1]['day']
    others = len([p for p in all_payments if a <= p['day'] <= b and not any(p is q for q in run)])
    return others > len(run)


def steady_amounts(payments):
    """Weekly and fortnightly card payments to one place only count if the amount is steady, not a wandering takeaway."""
    a = [abs(p['amount']) for p in payments]
    return len(set(a)) <= 2 or max(a) <= min(a) * 1.25


def amounts_compatible(payments):
    """Bills vary, but a whole payee group only counts as one series if its amounts stay in a sensible band."""
    a = [abs(p['amount']) for p in payments]
    if len(set(a)) == 1 or max(a) <= min(a) * 3:
        return True
    # An intro or trial price at the start, then a steady price.
    tail = a[1:]
    return a[0] < min(tail) and max(tail) <= min(tail) * 3


def join_error(a_run, b_run, fit):
    """How far the gap between two runs is from one step of the cadence, or None if it is not a follow-on."""
    cad = CADENCE_BY_ID[fit['cadence']]
    last, first = a_run[-1]['day'], b_run[0]['day']
    if cad['months']:
        expected = step_from(nearest_nominal(last, fit['anchor']), cad, fit['anchor'], 1)
    else:
        expected = last + cad['days']
    err = first - expected
    early_tol = min(cad['tol'], 3) if cad['months'] else cad['tol']
    if err < -early_tol or err > cad['tol']:
        return None
    return abs(err)


def minimum_count(cad, method, keyword):
    """Minimum payments needed before a pattern counts, given what else we know."""
    n = cad['min']
    if method in ('direct debit', 'standing order'):
        n = max(2, n - 1)
    elif keyword and cad['months']:
        n = max(2, n - 1)
    return n


def schedule_from(series, from_nominal, count, until_day=None):
    """Expected payment dates after a nominal date, rolled to working days for direct debits and standing orders."""
    cad = CADENCE_BY_ID[series['cadence']]
    out = []
    nominal = from_nominal
    for _ in range(count):
        nominal = step_from(nominal, cad, series['anchor'], 1)
        if until_day is not None and nominal > until_day:
            break
        due = next_working_day(nominal) if series['rolls'] else nominal
        out.append({'nominal': nominal, 'due': due})
    return out


def last_nominal(series):
    """The nominal due date of a series' latest payment."""
    cad = CADENCE_BY_ID[series['cadence']]
    # A payment added by hand has no history: step back one from its next due date.
    if not series['payments']:
        if cad['months']:
            return add_months(series['nominalNext'], -cad['months'], series['anchor'])
        return series['nominalNext'] - cad['days']
    last = series['payments'][-1]['day']
    if cad['months']:
        return nearest_nominal(last, series['anchor'])
    return last


def annual_cost(typical, cadence_id):
    """What a payment of this size costs over a year at this cadence."""
    return typical * CADENCE_BY_ID[cadence_id]['perYear']


def monthly_cost(typical, cadence_id):
    """The monthly equivalent of a payment of this size at this cadence."""
    return round_half_up(annual_cost(typical, cadence_id) / 12)


def confidence_for(s):
    """How sure the match is, from 5 to 99."""
    score = min(40, s['count'] * 10)
    score += round_half_up(25 * s['fit']['score'])
    score += 15 if s['amounts']['kind'] == 'fixed' else 12 if s['amounts']['kind'] == 'stepped' else 6
    if s['method'] in ('direct debit', 'standing order'):
        score += 10
    elif s['method'] == 'card':
        score += 3
    if s['keyword']:
        score += 7
    score -= s['fit']['missed'] * 5 + len(s['extras']) * 3
    score -= round_half_up(s['fit']['mae'])
    return max(5, min(99, score))


def confidence_label(c):
    """Sure, Likely or Possible."""
    return 'Sure' if c >= 75 else 'Likely' if c >= 50 else 'Possible'


def find_regulars(transactions, as_of=None, aliases=None, names=None, manual=None, overrides=None, added=None):
    """Find regular payments in merged transactions.

    aliases maps a payee group key to another group key, names maps a series
    id to the name the user prefers, manual lists candidates the user has
    confirmed ({'id', 'cadence'}), and overrides maps a series id to a
    {'category', 'method'} correction.
    """
    aliases = aliases or {}
    overrides = overrides or {}
    coverage = {}
    for t in transactions:
        c = coverage.get(t['account'])
        if c is None:
            c = coverage[t['account']] = {'start': t['day'], 'end': t['day']}
        c['start'] = min(c['start'], t['day'])
        c['end'] = max(c['end'], t['day'])
    data_end = max((c['end'] for c in coverage.values()), default=None)
    data_start = min((c['start'] for c in coverage.values()), default=None)
    if as_of is None:
        as_of = data_end + 1 if data_end is not None else day_from_ymd(2026, 1, 1)

    transfers = match_transfers(transactions)
    series, candidates, income = [], [], []
    for direction in ('out', 'in'):
        chosen = [t for t in transactions if (t['amount'] < 0 if direction == 'out' else t['amount'] > 0) and not is_cash(t)]
        keys = {}
        for t in chosen:
            keys[payee_key(t['desc'])] = 1
        parents = group_keys(list(keys))
        groups, gorder = {}, []
        for t in chosen:
            k = payee_key(t['desc'])
            g = parents.get(k) or k
            if truthy(aliases.get(g)):
                g = aliases[g]
            if g not in groups:
                groups[g] = []
                gorder.append(g)
            groups[g].append({'day': t['day'], 'amount': t['amount'], 'desc': t['desc'], 'memo': t.get('memo'),
                              'type': t.get('type'), 'category': t.get('category'), 'account': t['account'], 'key': k,
                              'transfer': transfer_id(t) in transfers})
        for g in sorted(gorder):
            pays = sorted(groups[g], key=lambda p: (p['day'], abs(p['amount'])))
            mandates = len([p for p in pays
                            if payment_method(p['type'], p['desc']) in ('direct debit', 'standing order')])
            ex = explain_group(pays, {'mandate': mandates * 2 > len(pays)})
            seq = {}
            for raw in ex['series']:
                base = g + '~' + raw['fit']['cadence']
                seq[base] = seq.get(base, 0) + 1
                sid = base + '~' + str(seq[base])
                s = build_series(g, raw, direction, coverage, as_of, overrides.get(sid))
                s['id'] = sid
                min_n = minimum_count(CADENCE_BY_ID[s['cadence']], s['method'], s['keyword'])
                if len(s['payments']) < min_n:
                    if direction == 'in' or s['fit']['mae'] > 2 or s['category'] == 'personal':
                        continue
                    candidates.append(candidate_from(s, 'Only ' + str(len(s['payments'])) + ' payments so far, '
                                                     + CADENCE_BY_ID[s['cadence']]['label'].lower() + ' apart.'))
                    continue
                if direction == 'in':
                    if not s['transfer']:
                        income.append(s)
                else:
                    series.append(s)
            if direction == 'out':
                for p in ex['rest']:
                    candidate = _renewal_candidate(g, p, as_of)
                    if candidate:
                        candidates.append(candidate)
    # Payments the user has confirmed by hand.
    for m in manual or []:
        idx = -1
        for i, c in enumerate(candidates):
            if c['id'] == m.get('id'):
                idx = i
        if idx < 0:
            continue
        c = candidates.pop(idx)
        fit = {'cadence': m.get('cadence') or c['cadence'], 'anchor': anchor_day([p['day'] for p in c['payments']]),
               'matched': 0, 'missed': 0, 'bad': 0, 'extras': [], 'mae': 0, 'score': 1, 'ok': True}
        s = build_series(c['key'], {'payments': c['payments'], 'fit': fit}, 'out', coverage, as_of,
                         overrides.get(c['id']))
        s['id'] = c['id']
        s['manual'] = True
        s['confidence'] = 60
        s['reasons'].insert(0, 'You confirmed this as a regular payment.')
        series.append(s)

    for raw in added or []:
        a = clean_added(raw)
        if a and not any(s['id'] == a['id'] for s in series):
            series.append(added_series(a, as_of))
    flag_duplicates(series)
    series.sort(key=functools.cmp_to_key(lambda a, b: (status_rank(a) - status_rank(b)) or (b['annual'] - a['annual'])
                                         or cmp(a['id'], b['id'])))
    income.sort(key=functools.cmp_to_key(lambda a, b: (b['annual'] - a['annual']) or cmp(a['id'], b['id'])))
    candidates.sort(key=functools.cmp_to_key(lambda a, b: (b['amount'] - a['amount']) or cmp(a['id'], b['id'])))
    names = names or {}
    for s in series + income:
        if truthy(names.get(s['id'])):
            s['name'] = names[s['id']]
    return {'asOf': as_of, 'dataStart': data_start, 'dataEnd': data_end, 'coverage': coverage, 'series': series,
            'income': income, 'candidates': candidates, 'payday': find_payday(income, as_of),
            'transferCount': len(transfers),
            'everyday': everyday_spending(transactions, series + income, transfers, coverage)}


def _renewal_candidate(g, p, as_of):
    """A single payment worth watching because its description suggests a yearly renewal."""
    words = ' ' + ' '.join(tokens(clean_description(p['desc'] + ' ' + (p['memo'] or '')))) + ' '
    hit = next((w for w in RENEWAL_WORDS if ' ' + w + ' ' in words), None)
    if not hit or abs(p['amount']) < 1000 or as_of - p['day'] > 400:
        return None
    cat = categorise(p['desc'] + ' ' + (p['memo'] or ''), p['category'])
    return {
        'id': g + '~single~' + iso(p['day']), 'key': g, 'name': display_name(g), 'account': p['account'],
        'cadence': 'yearly', 'amount': abs(p['amount']), 'lastDay': p['day'], 'payments': [p],
        'method': payment_method(p['type'], p['desc']), 'category': cat['id'],
        'reason': ('One payment of ' + money(abs(p['amount'])) + ' on ' + long_date(p['day']) + ' with "'
                   + hit.lower() + '" in the description. If it renews yearly, the next one is due about '
                   + long_date(add_months(p['day'], 12)) + '.'),
    }


def status_rank(s):
    """Stopped series sort after active ones."""
    return 1 if s['status'] == 'stopped' else 0


def everyday_spending(transactions, all_series, transfers, coverage):
    """Spending outside the regular payments and transfers: the average a day over the last 91 days of each account."""
    regular = {}
    for s in all_series:
        for p in s['payments']:
            k = p['account'] + '|' + str(p['day']) + '|' + str(-p['amount'] if s['direction'] == 'out' else p['amount']) + '|' + p['desc']
            regular[k] = regular.get(k, 0) + 1
    out = {}
    for acc in sorted(coverage):
        c = coverage[acc]
        start = max(c['start'], c['end'] - 90)
        days = c['end'] - start + 1
        total = count = refunds = 0
        payees = {}
        for t in transactions:
            if t['account'] != acc or t['amount'] >= 0 or t['day'] < start or t['day'] > c['end']:
                continue
            k = t['account'] + '|' + str(t['day']) + '|' + str(t['amount']) + '|' + t['desc']
            if regular.get(k):
                regular[k] -= 1
                continue
            if transfers.get(transfer_id(t)):
                continue
            total += -t['amount']
            count += 1
            payees[_refund_key(t['desc'])] = 1
        # Money back from a shop you spent with (a refund) is taken off again.
        for t in transactions:
            if t['account'] != acc or t['amount'] <= 0 or t['day'] < start or t['day'] > c['end']:
                continue
            k = t['account'] + '|' + str(t['day']) + '|' + str(t['amount']) + '|' + t['desc']
            if regular.get(k):
                regular[k] -= 1
                continue
            if transfers.get(transfer_id(t)):
                continue
            if payees.get(_refund_key(t['desc'])):
                refunds += t['amount']
        total = max(0, total - refunds)
        out[acc] = {'perDay': round_half_up(total / days), 'days': days, 'count': count, 'total': total,
                    'refunds': refunds}
    return out


_CASH_TYPE = js_regex(r'\b(ATM|CASH|CASH MACHINE|CASHPOINT|CPT)\b', 'i')
_CASH_DESC = js_regex(r'\b(ATM|CASH WITHDRAWAL|CASH MACHINE|CASHPOINT)\b|^\s*CPT\b', 'i')
_REFUND_PREFIX = js_regex(r'^\s*(REFUND|REVERSAL)(\s+(FROM|OF))?\s+', 'i')


def is_cash(t):
    """Cash taken out is everyday spending, never a regular payment to someone."""
    return bool(_CASH_TYPE.search(t.get('type') or '') or _CASH_DESC.search(t.get('desc') or ''))


def _refund_key(desc):
    return payee_key(_REFUND_PREFIX.sub('', js_string(desc), count=1))


def transfer_id(t):
    """Identifies a transaction for transfer matching."""
    return t['account'] + '|' + str(t['day']) + '|' + str(t['amount']) + '|' + t['desc']


def match_transfers(transactions):
    """Money moved between two of your own accounts: out of one and into another for the same amount within three days.

    Returns the transfer ids of both sides of every match.
    """
    if len({t['account'] for t in transactions}) < 2:
        return {}
    ins, marked = {}, {}
    for t in transactions:
        if t['amount'] > 0:
            ins.setdefault(t['amount'], []).append(t)
    for t in transactions:
        if t['amount'] >= 0:
            continue
        for c in ins.get(-t['amount'], []):
            if c['account'] == t['account'] or transfer_id(c) in marked:
                continue
            if c['day'] < t['day'] or c['day'] - t['day'] > 3:
                continue
            marked[transfer_id(c)] = 1
            marked[transfer_id(t)] = 1
            break
    return marked


def build_series(group_key, raw, direction, coverage, as_of, override=None):
    """Turn a group of payments and their cadence fit into a described series."""
    override = override or {}
    payments = sorted(raw['payments'], key=lambda p: p['day'])
    fit = raw['fit']
    set_by_you = False
    if override.get('cadence') and override['cadence'] in CADENCE_BY_ID and override['cadence'] != fit['cadence']:
        cd = CADENCE_BY_ID[override['cadence']]
        fit = dict(fit, cadence=cd['id'], anchor=anchor_day([p['day'] for p in payments]) if cd['months'] else 0)
        set_by_you = True
    cad = CADENCE_BY_ID[fit['cadence']]
    extras = fit.get('extras') or []
    methods = {}
    for p in payments:
        m = payment_method(p['type'], p['desc'])
        methods[m] = methods.get(m, 0) + 1
    method, m_n = 'unknown', 0
    for m in sorted(methods):
        if m != 'unknown' and methods[m] > m_n:
            method, m_n = m, methods[m]
    if method == 'unknown' and all(_CARD_ACCOUNT.search(p['account']) for p in payments):
        method = 'card'
    if truthy(override.get('method')) and override['method'] in METHODS:
        method = override['method']
    last_p = payments[-1]
    cat = categorise(' '.join(p['desc'] + ' ' + (p['memo'] or '') for p in payments), last_p['category'])
    transfer_share = len([p for p in payments if p.get('transfer')]) / len(payments)
    if transfer_share >= 0.5 and direction == 'out':
        cat = {'id': 'savings', 'word': None, 'transfer': True}
    if direction == 'in':
        cat = {'id': 'income', 'word': None, 'transfer': transfer_share >= 0.5}
    elif truthy(override.get('category')) and override['category'] in CATEGORY_BY_ID:
        cat = {'id': override['category'], 'word': None, 'user': True}
    amounts = amount_profile(payments)
    acc_list = sorted({p['account'] for p in payments})
    cov_end = max(coverage[a]['end'] for a in acc_list)
    cov_start = min(coverage[a]['start'] for a in acc_list)
    s = {
        'id': '', 'key': group_key, 'name': display_name(group_key), 'direction': direction,
        'account': ', '.join(acc_list), 'accounts': acc_list, 'cadence': cad['id'], 'cadenceLabel': cad['label'],
        'anchor': fit['anchor'],
        'payments': [{'day': p['day'], 'amount': abs(p['amount']), 'desc': p['desc'], 'account': p['account']}
                     for p in payments],
        'count': len(payments), 'first': payments[0]['day'], 'last': last_p['day'],
        'method': method, 'rolls': method in ('direct debit', 'standing order'),
        'category': cat['id'], 'keyword': cat.get('word') or None, 'bankCategory': cat.get('bank') or None,
        'transfer': bool(cat.get('transfer')),
        'amounts': amounts, 'typical': amounts['typical'], 'fit': fit, 'extras': extras, 'flags': [], 'reasons': [],
    }
    s['annual'] = annual_cost(s['typical'], s['cadence'])
    if amounts['kind'] == 'variable' and s['last'] - s['first'] >= 300:
        # A year of a variable bill: what the last twelve months actually cost.
        recent = [p for p in s['payments'] if p['day'] > s['last'] - 365]
        total = sum(p['amount'] for p in recent)
        s['annual'] = round_half_up(total * cad['perYear'] / len(recent))
        s['seasonal'] = True
    s['monthly'] = round_half_up(s['annual'] / 12)
    # Status: still going, or stopped?
    upcoming = schedule_from(s, last_nominal(s), 60, as_of + 800)
    grace = max(4, round_half_up(cad['days'] * 0.2))
    missed_at_end = len([u for u in upcoming if u['due'] + grace < cov_end])
    s['missedAtEnd'] = missed_at_end
    if missed_at_end >= 1:
        s['status'] = 'stopped'
        s['nextDue'] = None
    else:
        s['status'] = 'active'
        s['nextDue'] = upcoming[0]['due'] if upcoming else None
        if s['nextDue'] is not None and s['nextDue'] < as_of:
            s['late'] = True
        # New if it started within the last three steps, or the last three months for shorter cadences.
        if (cad['days'] <= 32 and s['first'] - cov_start >= cad['days'] * 0.8
                and s['first'] >= cov_end - max(3 * cad['days'], CADENCE_BY_ID['quarterly']['days'])):
            s['isNew'] = True
    s['coverageEnd'] = cov_end
    s['coverageStart'] = cov_start
    s['confidence'] = confidence_for(s)
    s['confidenceLabel'] = confidence_label(s['confidence'])
    describe_series(s, as_of)
    if set_by_you:
        s['reasons'].insert(0, 'You set how often this is paid.')
    return s


def clean_added(a):
    """Check a payment added by hand; None if it cannot be used."""
    if not isinstance(a, dict):
        return None
    name = js_trim(js_string(a.get('name') or ''))
    amount = a.get('amount')
    amount = abs(round_half_up(amount)) if is_number(amount) and math.isfinite(amount) else 0
    nxt = a.get('next')
    nxt = nxt if is_number(nxt) else from_iso(a.get('next'))
    if not name or not amount or nxt is None or a.get('cadence') not in CADENCE_BY_ID:
        return None
    return {'id': js_string(a['id']) if truthy(a.get('id')) else 'added~' + slug(name), 'name': name[:80],
            'amount': amount, 'cadence': a['cadence'], 'next': nxt,
            'method': a['method'] if a.get('method') in METHODS else 'unknown',
            'category': a['category'] if a.get('category') in CATEGORY_BY_ID and a.get('category') != 'income' else 'other',
            'account': js_string(a.get('account') or '')}


def added_series(a, as_of):
    """A regular payment the user added by hand, such as one paid from an account they did not load."""
    cad = CADENCE_BY_ID[a['cadence']]
    anchor = ymd(a['next'])[2] if cad['months'] else 0
    nxt, guard = a['next'], 0
    while nxt < as_of and guard < 2000:
        nxt = step_from(nxt, cad, anchor, 1)
        guard += 1
    rolls = a['method'] in ('direct debit', 'standing order')
    amounts = {'kind': 'fixed', 'typical': a['amount'], 'min': a['amount'], 'max': a['amount'], 'changes': [],
               'runs': [], 'last': a['amount']}
    return {
        'id': a['id'], 'key': a['name'].upper(), 'name': a['name'], 'direction': 'out', 'account': a['account'],
        'accounts': [a['account']] if a['account'] else [], 'cadence': cad['id'], 'cadenceLabel': cad['label'],
        'anchor': anchor, 'payments': [], 'count': 0, 'first': None, 'last': None, 'method': a['method'],
        'rolls': rolls, 'category': a['category'], 'keyword': None, 'bankCategory': None, 'transfer': False,
        'amounts': amounts, 'typical': a['amount'],
        'fit': {'cadence': cad['id'], 'anchor': anchor, 'matched': 0, 'missed': 0, 'bad': 0, 'extras': [], 'mae': 0,
                'score': 1, 'ok': True},
        'extras': [], 'flags': [], 'reasons': ['You added this by hand: ' + money(a['amount']) + ' '
                                               + cad['label'].lower() + ', next due ' + long_date(nxt) + '.'],
        'annual': annual_cost(a['amount'], cad['id']), 'monthly': monthly_cost(a['amount'], cad['id']),
        'missedAtEnd': 0, 'status': 'active', 'nominalNext': nxt, 'nextDue': next_working_day(nxt) if rolls else nxt,
        'coverageEnd': None, 'coverageStart': None, 'confidence': 100, 'confidenceLabel': 'Sure', 'added': True,
        'manual': True,
    }


def anchor_text(anchor):
    """The due day of a monthly anchor in words: '14th', 'last Friday of the month'."""
    if anchor == 'LW':
        return 'last working day of the month'
    if isinstance(anchor, str) and anchor[0] == 'B':
        return ordinal(int(anchor[1:])) + ' (or the working day before)'
    if isinstance(anchor, str):
        return 'last ' + DAY_NAMES[int(anchor[1:])] + ' of the month'
    return ordinal(anchor) + (' (the last day)' if anchor == 31 else '')


def _plural(n, word):
    return str(n) + ' ' + word + ('s' if n > 1 else '')


def describe_series(s, as_of):
    """Write a series' reasons (why it counts as regular) and flags (what deserves a second look)."""
    cad = CADENCE_BY_ID[s['cadence']]
    if isinstance(s['anchor'], str):
        when = 'monthly, on the ' + anchor_text(s['anchor'])
    elif cad['months'] == 1:
        when = 'monthly, usually on the ' + ordinal(s['anchor']) + (' (the last day)' if s['anchor'] == 31 else '')
    elif cad['months']:
        when = cad['label'].lower() + ', around the ' + ordinal(s['anchor'])
    else:
        when = cad['label'].lower() + ', on ' + DAY_NAMES[weekday(s['last'])] + 's'
    missed = s['fit']['missed']
    reasons = [str(s['count']) + ' payments, ' + when + (', with ' + _plural(missed, 'gap') if missed else '') + '.']
    amounts = s['amounts']
    if amounts['kind'] == 'fixed':
        reasons.append('The same amount every time (' + money(s['typical']) + ').')
    elif amounts['kind'] == 'stepped':
        reasons.append('The amount changed ' + _plural(len(amounts['changes']), 'time') + '; it is now '
                       + money(s['typical']) + '.')
    else:
        reasons.append('The amount varies, from ' + money(amounts['min']) + ' to ' + money(amounts['max'])
                       + '; recent typical ' + money(s['typical']) + '.')
    if s['method'] != 'unknown':
        reasons.append('Paid by ' + s['method'] + '.')
    if s['keyword']:
        reasons.append('The description mentions "' + s['keyword'].lower() + '".')
    s['reasons'] = reasons
    flags = []
    if s['status'] == 'stopped':
        flags.append({'id': 'stopped', 'tone': 'info',
                      'text': 'No payment since ' + long_date(s['last']) + ' ('
                              + _plural(s['missedAtEnd'], 'expected payment') + ' missing), so it looks stopped.'})
    if s['direction'] == 'out':
        intro = None
        if amounts['kind'] == 'stepped' and len(amounts['runs']) >= 2:
            r0, r1 = amounts['runs'][0], amounts['runs'][1]
            if r0['amount'] * 2 <= r1['amount'] and r0['count'] <= 3:
                intro = {'day': r1['start'], 'from': r0['amount'], 'to': r1['amount']}
                flags.append({'id': 'intro', 'tone': 'warn',
                              'text': 'An intro price of ' + money(r0['amount']) + ' ended on ' + long_date(r1['start'])
                                      + '; it is now ' + money(r1['amount']) + '.'})
        for c in amounts['changes']:
            if intro and c['day'] == intro['day']:
                continue
            if c['to'] > c['from']:
                pct = round_half_up((c['to'] - c['from']) / c['from'] * 1000) / 10
                flags.append({'id': 'rise', 'tone': 'warn' if as_of - c['day'] <= 190 else 'info', 'day': c['day'],
                              'text': 'Went up from ' + money(c['from']) + ' to ' + money(c['to']) + ' (+'
                                      + format(pct, '.1f') + '%) on ' + long_date(c['day']) + '.'})
            else:
                flags.append({'id': 'drop', 'tone': 'info', 'day': c['day'],
                              'text': 'Went down from ' + money(c['from']) + ' to ' + money(c['to']) + ' on '
                                      + long_date(c['day']) + '.'})
        if amounts['kind'] == 'variable' and len(s['payments']) >= 6:
            a = [p['amount'] for p in s['payments']]
            early, late = median(a[:3]), median(a[-3:])
            if late > early * 1.15:
                flags.append({'id': 'creep', 'tone': 'info',
                              'text': 'Recent payments (' + money(late) + ' typical) are higher than the first ones ('
                                      + money(early) + ').'})
        for d in s['extras']:
            p = next((x for x in s['payments'] if x['day'] == d), None)
            flags.append({'id': 'double', 'tone': 'alert', 'day': d,
                          'text': 'Charged twice: an extra ' + money(p['amount'] if p else s['typical']) + ' on '
                                  + long_date(d) + '. Check it was not taken in error.'})
        if s.get('isNew'):
            flags.append({'id': 'new', 'tone': 'warn', 'text': 'New: first taken on ' + long_date(s['first']) + '.'})
        if s.get('late'):
            flags.append({'id': 'late', 'tone': 'info',
                          'text': 'Due on ' + long_date(s['nextDue']) + ' but not in your statement yet.'})
    s['flags'] = flags


def candidate_from(s, reason):
    """A series too short to count yet, kept as a possible regular payment."""
    return {
        'id': s['id'], 'key': s['key'], 'name': s['name'], 'account': s['account'], 'cadence': s['cadence'],
        'amount': s['typical'], 'lastDay': s['last'],
        'payments': [{'day': p['day'], 'amount': -p['amount'], 'desc': p['desc'], 'account': p['account'], 'memo': '',
                      'type': '', 'category': ''} for p in s['payments']],
        'method': s['method'], 'category': s['category'], 'reason': reason,
    }


def flag_duplicates(series):
    """Flag active services that overlap (two in one category) and payees paid at two amounts."""
    by_cat, by_key = {}, {}
    for s in series:
        if s['status'] != 'active':
            continue
        if s['category'] in DUPLICATE_PRONE:
            by_cat.setdefault(s['category'], []).append(s)
        by_key.setdefault(s['key'], []).append(s)
    for c, group in by_cat.items():
        if len(group) < 2:
            continue
        label = CATEGORY_BY_ID[c]['label'].lower()
        for s in group:
            others = [o['name'] for o in group if o is not s]
            s['flags'].append({'id': 'overlap', 'tone': 'warn',
                               'text': 'You pay for ' + str(len(group)) + ' services in ' + label + ' (also '
                                       + ', '.join(others) + ').'})
    for group in by_key.values():
        if len(group) < 2:
            continue
        for s in group:
            s['flags'].append({'id': 'same-payee', 'tone': 'info',
                               'text': 'One of ' + str(len(group)) + ' regular payments to ' + s['name']
                                       + ', at different amounts.'})


def find_payday(income, as_of):
    """The next expected pay day from the largest regular income, or None."""
    regular = [s for s in income if s['status'] == 'active'
               and s['cadence'] in ('monthly', 'four-weekly', 'fortnightly', 'weekly')]
    if not regular:
        return None
    best = sorted(regular, key=functools.cmp_to_key(lambda a, b: (b['monthly'] - a['monthly'])
                                                    or cmp(a['id'], b['id'])))[0]
    nxt = best['nextDue']
    if nxt is None:
        return None
    # Step on from nominal dates, so a payment rolled into the next month does not skip one.
    nominal = schedule_from(best, last_nominal(best), 1)[0]['nominal']
    while nxt < as_of:
        step = schedule_from(best, nominal, 1)[0]
        nominal, nxt = step['nominal'], step['due']
    return {'seriesId': best['id'], 'name': best['name'], 'next': nxt, 'typical': best['typical'],
            'cadence': best['cadence']}
