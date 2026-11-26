"""Quiet cartel model.

An exact port of the JavaScript model in ``app/index.html`` (the block between
``/* MODEL START */`` and ``/* MODEL END */``).

A repeated price-setting game between sellers of similar products, with logit
demand. Each learning seller runs tabular Q-learning with an exploration rate
that decays over time and remembers last period's prices.

Every floating-point operation is carried out in the same order and grouping
as the JavaScript, so both versions give bit-identical results. In particular:

* ``det_exp`` and ``det_log`` replace ``exp`` and ``log`` (never ``math.exp``
  or ``math.log``), exactly as in the JavaScript.
* Float sums are accumulated left to right in plain loops. The built-in
  ``sum`` is never used on floats: since Python 3.12 it uses compensated
  summation, which can differ from a plain loop in the last bit.
* JavaScript ``Math.round`` is reproduced exactly (``_math_round``), including
  the cases where ``floor(x + 0.5)`` would differ.
* Sorts never see NaN (``bootstrap_mean`` drops it and ``roc_curve`` ranks it
  last), so every sort is by a consistent order and Python's stable ``sorted``
  gives the same result as JavaScript's stable ``Array.prototype.sort``.

Config dicts and returned dicts use the same camelCase keys as the JavaScript
objects, so results can be compared key by key and both versions read the
same JSON files. JavaScript ``null`` is ``None``; ``NaN`` and ``Infinity`` are
``float('nan')`` and ``math.inf``. In option dicts (``opts``) a missing key and
a value of ``None`` both mean "not given". ``validate_config`` follows the
JavaScript rules for JSON values exactly, so ``null`` in a numeric field is
reported as "must be a number", and strings are converted as JavaScript's
``Number()`` would convert them.

Only the standard library is used.
"""

import math
import re
from itertools import chain, repeat
from operator import add, mul, sub

__all__ = [
    'LN2', 'det_exp', 'det_log', 'Rng',
    'sum_', 'mean', 'sd', 'sorted_copy', 'quantile', 'round_',
    'bootstrap_mean', 'roc_curve',
    'LIMITS', 'FIRM_TYPES', 'MEMORY', 'default_config', 'validate_config',
    'shares', 'profits_at', 'consumer_surplus', 'nash_prices', 'monopoly_prices',
    'SHOCKS', 'build_market', 'decode_joint', 'encode_joint', 'nearest_index',
    'state_tables', 'rule_table', 'Trainer', 'train', 'limit_cycle', 'outcome_of',
    'static_best_response', 'impulse_response', 'summarise', 'best_response_check',
    'SCENARIOS', 'scenario_by_id', 'apply_scenario', 'run_scenario', 'aggregate',
    'observe', 'screens', 'permutation_test',
    'CASE_MIX', 'CASE_MU', 'case_config', 'finish_case', 'make_case',
    'SCREEN_LIST', 'screen_score', 'evaluate_screens', 'confusion',
]

LN2 = 0.6931471805599453
NAN = float('nan')
INF = math.inf
_U32 = 0xFFFFFFFF
_TWO32 = 4294967296.0


# ------------------------------------------------------------ JavaScript semantics

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _truthy(v):
    """JavaScript ToBoolean for JSON-style values."""
    if v is None or isinstance(v, bool):
        return bool(v)
    if _is_num(v):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return v != ''
    return True


def _or(v, default):
    """JavaScript ``v || default``."""
    return v if _truthy(v) else default


def _div(a, b):
    """JavaScript division: Infinity or NaN instead of ZeroDivisionError."""
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return NAN
        return math.copysign(INF, a) * math.copysign(1.0, b)


def _floor(x):
    """JavaScript Math.floor: an int for finite input; NaN and infinities pass through."""
    return x if x != x or x in (INF, -INF) else math.floor(x)


def _count(x):
    """How many times ``for (i = 0; i < x; i++)`` runs."""
    return math.ceil(x) if x > 0 else 0


def _math_round(x):
    """JavaScript Math.round, exactly.

    ``math.floor(x + 0.5)`` is not the same: it gives 1 for 0.49999999999999994
    and rounds odd integers above 2**52 up, because ``x + 0.5`` is itself
    rounded. Like JavaScript, a result of zero from a negative input is -0.
    """
    if x != x or x in (INF, -INF):
        return x
    f = math.floor(x)
    r = f + 1 if x - f >= 0.5 else f
    if r == 0 and math.copysign(1.0, x) < 0:
        return -0.0
    return r


def _js_set(lst, i, value):
    """``lst[i] = value`` as JavaScript does it, growing the list when needed."""
    lst.extend([None] * (i + 1 - len(lst)))
    lst[i] = value


# JavaScript white space and line terminators (what Number() and String.prototype.trim remove)
_JS_SPACE = ('\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005'
             '\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')
_DECIMAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
_RADIX = re.compile(r'0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+')


def _string_to_number(s):
    """JavaScript ``Number(string)``."""
    s = s.strip(_JS_SPACE)
    if s == '':
        return 0.0
    if _DECIMAL.fullmatch(s):
        if s.endswith('Infinity'):
            return -INF if s[0] == '-' else INF
        return float(s)
    if _RADIX.fullmatch(s):
        try:
            return float(int(s, 0))
        except OverflowError:
            return INF
    return NAN


def _to_number(v):
    """JavaScript ``Number(value)`` for null, booleans, numbers and strings (anything else is NaN)."""
    if v is None or isinstance(v, bool):
        return float(bool(v))
    if _is_num(v):
        try:
            return float(v)
        except OverflowError:
            return INF if v > 0 else -INF
    if isinstance(v, str):
        return _string_to_number(v)
    return NAN


def _num_to_string(x):
    """JavaScript ``String(number)``: the shortest round-trip digits in JavaScript's layout."""
    x = float(x)
    if x != x:
        return 'NaN'
    if x == 0:
        return '0'
    if x in (INF, -INF):
        return 'Infinity' if x > 0 else '-Infinity'
    sign = '-' if x < 0 else ''
    mant, _, exp = repr(abs(x)).partition('e')
    ip, _, fp = mant.partition('.')
    digits = (ip + fp).lstrip('0')
    n = len(digits) + int(exp or 0) - len(fp)       # the value is 0.<digits> times 10**n
    digits = digits.rstrip('0')
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + '0' * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + '.' + digits[n:]
    if -6 < n <= 0:
        return sign + '0.' + '0' * -n + digits
    e = n - 1
    return sign + digits[0] + ('.' + digits[1:] if k > 1 else '') + ('e+' if e >= 0 else 'e-') + str(abs(e))


def _to_string(v):
    """JavaScript ``String(value)`` for the simple values a scenario id might be."""
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return _num_to_string(v) if _is_num(v) else str(v)


def _to_uint32(x):
    """JavaScript ``x >>> 0``."""
    x = _to_number(x)
    return 0 if x != x or x in (INF, -INF) else int(x) & _U32


def _js_max(a, b):
    """JavaScript ``Math.max(a, b)``."""
    a = a if _is_num(a) else _to_number(a)
    b = b if _is_num(b) else _to_number(b)
    if a != a or b != b:
        return NAN
    if a == b == 0:
        return a if math.copysign(1.0, a) > 0 else b      # +0 beats -0
    return a if a > b else b


# ---------------------------------------------------------------- helpers

def det_exp(x):
    """exp(x) from +, -, *, / only (range reduction then a 24-term series)."""
    if x != x:
        return NAN
    if x > 700:
        return INF
    if x < -700:
        return 0
    k = math.floor(x / LN2 + 0.5)
    r = x - k * LN2
    s = term = 1
    for i in range(1, 25):
        term = term * r / i
        s += term
    if k > 0:
        for _ in range(k):
            s *= 2
    else:
        for _ in range(-k):
            s *= 0.5
    return s


def det_log(x):
    """log(x) from +, -, *, / only (range reduction then the atanh series)."""
    if not (x > 0):
        return -INF if x == 0 else NAN
    if x == INF:
        return INF
    k = 0
    while x >= 1.5:
        x *= 0.5
        k += 1
    while x < 0.75:
        x *= 2
        k -= 1
    z = (x - 1) / (x + 1)
    z2 = z * z
    s = 0
    term = z
    for i in range(40):
        s += term / (2 * i + 1)
        term *= z2
    return 2 * s + k * LN2


class Rng(object):
    """mulberry32: a small, fast 32-bit generator that is easy to copy exactly.

    The state ``a`` is held as an unsigned 32-bit int.
    """
    __slots__ = ('a',)

    def __init__(self, seed):
        self.a = _to_uint32(seed)

    def next(self):
        a = self.a = (self.a + 0x6D2B79F5) & _U32
        t = ((a ^ (a >> 15)) * (a | 1)) & _U32
        t = ((t + (t ^ (t >> 7)) * (t | 61)) & _U32) ^ t
        return (t ^ (t >> 14)) / _TWO32

    def int(self, n):
        return _floor(self.next() * n)


def sum_(xs):
    """Left-to-right sum, as the JavaScript ``sum`` (not the built-in ``sum``)."""
    s = 0
    for x in xs:
        s += x
    return s


def mean(xs):
    return sum_(xs) / len(xs) if len(xs) else NAN


def sd(xs):
    if len(xs) < 2:
        return 0
    m = mean(xs)
    s = 0
    for x in xs:
        s += (x - m) * (x - m)
    return math.sqrt(s / (len(xs) - 1))


def sorted_copy(xs):
    """``xs.slice().sort((a, b) => a - b)``: both sorts are stable, so they agree on any input without NaN."""
    return sorted(xs)


def quantile(sorted_xs, q):
    n = len(sorted_xs)
    if not n:
        return NAN
    pos = q * (n - 1)
    if not (0 <= pos <= n - 1):
        return NAN                  # JavaScript reads past either end as undefined
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_xs[lo]
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def round_(x, d):
    """Round to ``d`` decimal places, as the JavaScript ``round``."""
    f = 1.0
    for _ in range(_count(d)):
        f *= 10
    return _math_round(x * f) / f


def bootstrap_mean(xs, level, reps=None, seed=None):
    """Percentile bootstrap interval for a mean (NaN values dropped), with its own seeded generator."""
    xs = [x for x in xs if x == x]
    n = len(xs)
    if n == 0:
        return {'mean': NAN, 'lo': NAN, 'hi': NAN}
    m = mean(xs)
    if n == 1:
        return {'mean': m, 'lo': m, 'hi': m}
    rng = Rng(12345 if seed is None else seed)
    means = []
    for _rep in range(_count(_or(reps, 1000))):
        s = 0
        for _ in range(n):
            s += xs[rng.int(n)]
        means.append(s / n)
    means = sorted_copy(means)
    tail = (1 - level) / 2
    return {'mean': m, 'lo': quantile(means, tail), 'hi': quantile(means, 1 - tail)}


def roc_curve(scores, labels):
    """Area under the ROC curve (probability a random positive outscores a random negative)."""
    pos = sum(1 for lab in labels if _truthy(lab))
    neg = len(labels) - pos
    # NaN scores rank last; ties keep their original order (the sort is stable).
    scores = [s if s == s else -INF for s in scores]
    idx = sorted(range(len(scores)), key=lambda k: -scores[k])
    tp = fp = 0
    auc = prev_fp = prev_tp = 0
    pts = [{'fpr': 0, 'tpr': 0, 'threshold': INF}]
    for i, k in enumerate(idx):
        if k < len(labels) and _truthy(labels[k]):
            tp += 1
        else:
            fp += 1
        if i == len(idx) - 1 or scores[idx[i + 1]] != scores[k]:
            fpr = fp / neg if neg else 0
            tpr = tp / pos if pos else 0
            auc += (fpr - prev_fp) * (tpr + prev_tp) / 2
            prev_fp, prev_tp = fpr, tpr
            pts.append({'fpr': fpr, 'tpr': tpr, 'threshold': scores[k]})
    return {'points': pts, 'auc': auc if pos and neg else NAN, 'positives': pos, 'negatives': neg}


# ---------------------------------------------------------------- market

LIMITS = {
    'nFirms': [2, 3], 'nPrices': [5, 21], 'mu': [0.05, 1], 'xi': [0, 0.5], 'quality': [1, 3],
    'cost': [0, 2], 'outside': [-2, 2], 'alpha': [0.01, 0.5], 'beta': [5e-7, 1e-4],
    'delta': [0, 0.99], 'exploreFloor': [0, 0.2], 'demandNoise': [0, 0.5],
    'stableWindow': [1000, 200000], 'maxPeriods': [20000, 6000000],
}
FIRM_TYPES = ['learn', 'nash', 'match', 'undercut']
MEMORY = ['full', 'own', 'none']
_SCALAR_KEYS = ['nFirms', 'nPrices', 'mu', 'xi', 'outside', 'alpha', 'beta', 'delta',
                'exploreFloor', 'demandNoise', 'stableWindow', 'maxPeriods']


def default_config():
    return {
        'nFirms': 2, 'quality': [2, 2, 2], 'cost': [1, 1, 1], 'outside': 0, 'mu': 0.25,
        'nPrices': 15, 'xi': 0.1, 'alpha': 0.15, 'beta': 4e-6, 'delta': 0.95, 'memory': 'full',
        'firmTypes': ['learn', 'learn', 'learn'], 'sharedVendor': False, 'exploreFloor': 0,
        'demandNoise': 0, 'stableWindow': 100000, 'maxPeriods': 3000000, 'seed': 1,
    }


def _clamp_num(v, lim, fallback, name, errors):
    x = _string_to_number(v) if isinstance(v, str) else v
    if not _is_num(x) or x != x:
        errors.append(name + ' must be a number')
        return fallback
    if x < lim[0] or x > lim[1]:
        errors.append('%s must be between %s and %s' % (name, _num_to_string(lim[0]), _num_to_string(lim[1])))
        return lim[0] if x < lim[0] else lim[1]
    return x


def validate_config(input=None):
    """Returns ``{'config': ..., 'errors': [...]}``. Values out of range are clamped and reported."""
    d = default_config()
    c = {k: list(v) if isinstance(v, list) else v for k, v in d.items()}
    errors = []
    if not isinstance(input, dict):
        input = {}
    for k in _SCALAR_KEYS:
        if k in input:
            c[k] = _clamp_num(input[k], LIMITS[k], d[k], k, errors)
    for k in ('nFirms', 'nPrices', 'stableWindow', 'maxPeriods'):
        c[k] = int(_math_round(c[k]))
    for key in ('quality', 'cost'):
        if key in input:
            if not isinstance(input[key], list):
                errors.append(key + ' must be a list')
                continue
            for j, v in enumerate(input[key][:3]):
                c[key][j] = _clamp_num(v, LIMITS[key], d[key][j], '%s[%d]' % (key, j), errors)
    if 'firmTypes' in input:
        if not isinstance(input['firmTypes'], list):
            errors.append('firmTypes must be a list')
        else:
            for f, t in enumerate(input['firmTypes'][:3]):
                if isinstance(t, str) and t in FIRM_TYPES:
                    c['firmTypes'][f] = t
                else:
                    errors.append('firmTypes[%d] must be one of %s' % (f, ', '.join(FIRM_TYPES)))
    if 'memory' in input:
        mem = input['memory']
        if isinstance(mem, str) and mem in MEMORY:
            c['memory'] = mem
        else:
            errors.append('memory must be one of ' + ', '.join(MEMORY))
    if 'sharedVendor' in input:
        c['sharedVendor'] = _truthy(input['sharedVendor'])
    if 'seed' in input:
        # Only a number, or a string that is not blank, can be a seed (a boolean is not a number).
        v = input['seed']
        if _is_num(v):
            s = _to_number(v)
        elif isinstance(v, str) and v.strip(_JS_SPACE):
            s = _string_to_number(v)
        else:
            s = NAN
        if not (s >= 0) or s == INF or s != math.floor(s) or s > 4294967295:
            errors.append('seed must be a whole number from 0 to 4294967295')
        else:
            c['seed'] = s if s == 0 else int(s)     # keeps a seed of -0 as JavaScript does
    n = c['nFirms']
    learners = sum(1 for t in c['firmTypes'][:n] if t == 'learn')
    if learners == 0:
        errors.append('at least one seller must learn')
    if c['sharedVendor']:
        same = all(c['quality'][h] == c['quality'][0] and c['cost'][h] == c['cost'][0] for h in range(1, n))
        if learners != n or not same:
            errors.append('a shared vendor needs every seller to learn and to have the same quality and cost')
            c['sharedVendor'] = False
    if c['stableWindow'] > c['maxPeriods']:
        errors.append('stableWindow must not exceed maxPeriods')
        c['stableWindow'] = c['maxPeriods']
    return {'config': c, 'errors': errors}


def shares(prices, quality, outside, mu):
    e = [det_exp((quality[i] - prices[i]) / mu) for i in range(len(prices))]
    total = det_exp(outside / mu)
    for x in e:
        total += x
    return [x / total for x in e]


def profits_at(prices, quality, cost, outside, mu):
    q = shares(prices, quality, outside, mu)
    return [(prices[i] - cost[i]) * q[i] for i in range(len(prices))]


def consumer_surplus(prices, quality, outside, mu):
    """Consumer surplus per shopper (logit inclusive value), up to a constant."""
    total = det_exp(outside / mu)
    for i in range(len(prices)):
        total += det_exp((quality[i] - prices[i]) / mu)
    return mu * det_log(total)


def best_reply_price(p, i, quality, cost, outside, mu):
    """Seller i's best one-day price against the others' prices.

    The root of p - c = mu / (1 - q_i(p)), which is unique because the left
    side minus the right side rises with p. Found by bisection.
    """
    trial = list(p)
    lo, hi = cost[i], cost[i] + 50 * mu + 10
    for _ in range(200):
        mid = (lo + hi) / 2
        if mid <= lo or mid >= hi:
            break
        trial[i] = mid
        q = shares(trial, quality, outside, mu)[i]
        if mid - cost[i] - mu / (1 - q) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def nash_prices(quality, cost, outside, mu):
    """Competitive (static Nash) prices: every seller in turn moves to its best one-day price, until none moves."""
    n = len(quality)
    p = [cost[i] + mu for i in range(n)]
    for _ in range(1000):
        change = 0
        for i in range(n):
            np_ = best_reply_price(p, i, quality, cost, outside, mu)
            dd = abs(np_ - p[i])
            if dd > change:
                change = dd
            p[i] = np_
        if change < 1e-13:
            break
    return p


def monopoly_prices(quality, cost, outside, mu):
    """Joint-profit maximum: with logit demand every product carries the same markup m, where m(1 - Q) = mu."""
    lo, hi = 0, 60 * mu + 10

    def f(mk):
        q = shares([c + mk for c in cost[:len(quality)]], quality, outside, mu)
        return mk * (1 - sum_(q)) - mu

    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    m = (lo + hi) / 2
    return [c + m for c in cost[:len(quality)]]


SHOCKS = [-1, -0.5, 0, 0.5, 1]


def build_market(cfg):
    """Everything about the market that does not depend on learning."""
    n, m = cfg['nFirms'], cfg['nPrices']
    outside, mu, xi = cfg['outside'], cfg['mu'], cfg['xi']
    quality, cost = cfg['quality'][:n], cfg['cost'][:n]
    pN = nash_prices(quality, cost, outside, mu)
    pM = monopoly_prices(quality, cost, outside, mu)
    grids = []
    for i in range(n):
        lo = pN[i] - xi * (pM[i] - pN[i])
        hi = pM[i] + xi * (pM[i] - pN[i])
        step = (hi - lo) / (m - 1)
        grids.append([lo + k * step for k in range(m)])
    n_joint = m ** n
    levels = len(SHOCKS) if cfg['demandNoise'] > 0 else 1
    decoded = [decode_joint(j, n, m) for j in range(n_joint)]
    e_out = det_exp(outside / mu)
    profit = []
    for lv in range(levels):
        shock = SHOCKS[lv] * cfg['demandNoise'] if levels > 1 else 0
        # Each share term depends only on (seller, own price), so it is worked out once; it is the
        # same det_exp((quality[i] + shock - price) / mu) that profits_at would compute.
        terms = [[det_exp((quality[i] + shock - g) / mu) for g in grids[i]] for i in range(n)]
        margins = [[g - cost[i] for g in grids[i]] for i in range(n)]
        per_firm = [[0.0] * n_joint for _ in range(n)]
        for j, acts in enumerate(decoded):
            total = e_out
            for i in range(n):
                total += terms[i][acts[i]]
            for i in range(n):
                per_firm[i][j] = margins[i][acts[i]] * (terms[i][acts[i]] / total)
        profit.append(per_firm)
    return {
        'n': n, 'm': m, 'nJoint': n_joint, 'quality': quality, 'cost': cost, 'outside': outside, 'mu': mu,
        'pN': pN, 'pM': pM,
        'piN': profits_at(pN, quality, cost, outside, mu), 'piM': profits_at(pM, quality, cost, outside, mu),
        'csN': consumer_surplus(pN, quality, outside, mu), 'csM': consumer_surplus(pM, quality, outside, mu),
        'grids': grids, 'profit': profit, 'levels': levels,
        'nashIdx': [nearest_index(grids[i], pN[i]) for i in range(n)],
        'monoIdx': [nearest_index(grids[i], pM[i]) for i in range(n)],
    }


def decode_joint(j, n, m):
    a = []
    for _ in range(n):
        a.append(j % m)
        j //= m
    return a


def encode_joint(acts, m):
    j, mult = 0, 1
    for a in acts:
        j += a * mult
        mult *= m
    return j


def nearest_index(grid, p):
    best, bd = 0, INF
    for k, g in enumerate(grid):
        d = abs(g - p)
        if d < bd:
            bd, best = d, k
    return best


def state_tables(mk, memory):
    """Which state a learning seller sees, for every possible set of last prices."""
    n, m, n_joint = mk['n'], mk['m'], mk['nJoint']
    size = n_joint if memory == 'full' else m if memory == 'own' else 1
    tabs = []
    for i in range(n):
        tab = []
        for j in range(n_joint):
            a = decode_joint(j, n, m)
            if memory == 'full':
                s, mult = a[i], m
                for o in range(n):
                    if o != i:
                        s += a[o] * mult
                        mult *= m
            else:
                s = a[i] if memory == 'own' else 0
            tab.append(s)
        tabs.append(tab)
    return {'tabs': tabs, 'sizes': [size] * n}


def rule_table(mk, i, type):
    """What a rule-based seller charges, for every possible set of last prices."""
    n, m, grids = mk['n'], mk['m'], mk['grids']
    tab = []
    for j in range(mk['nJoint']):
        a = decode_joint(j, n, m)
        cheapest = min((grids[o][a[o]] for o in range(n) if o != i), default=INF)
        if type == 'nash':
            tab.append(mk['nashIdx'][i])
        elif type == 'match':
            tab.append(nearest_index(grids[i], cheapest))
        else:
            # undercut the cheapest rival by one step; when the price war reaches the bottom, reset to the top
            near = nearest_index(grids[i], cheapest)
            tab.append(near - 1 if near > 0 else m - 1)
    return tab


# ---------------------------------------------------------------- learning

def _row_views(tables, m):
    """Split each flat Q table into one list per state for the training loop.

    Tables shared between sellers (a shared vendor) get one shared set of rows.
    Returns the per-seller rows and the (table, rows) pairs to write back.
    """
    views = {}
    for Q in tables:
        if Q is not None and id(Q) not in views:
            views[id(Q)] = (Q, [Q[s:s + m] for s in range(0, len(Q), m)])
    return [None if Q is None else views[id(Q)][1] for Q in tables], list(views.values())


def _write_back(pairs):
    for Q, rows in pairs:
        Q[:] = chain.from_iterable(rows)


class Trainer(object):
    """Q-learning sellers in the market described by a (validated) config.

    Attributes mirror the JavaScript object: ``cfg``, ``errors``, ``market``,
    ``state_tab``, ``state_size``, ``learn``, ``rule_tab``, ``Q``, ``best``,
    ``best_v``, ``rng``, ``last``, ``t``, ``eps``, ``decay``, ``stable``,
    ``converged``, ``done``, ``block`` and ``history``. ``Q[i]`` is a flat list
    indexed by ``state * m + action``, like the JavaScript Float64Array. The
    JavaScript scratch buffers ``_acts`` and ``_states`` are locals of the
    training loop here.
    """

    def __init__(self, input=None):
        v = validate_config(input)
        self.cfg = cfg = v['config']
        self.errors = v['errors']
        self.market = mk = build_market(cfg)
        n, m, n_joint = mk['n'], mk['m'], mk['nJoint']
        st = state_tables(mk, cfg['memory'])
        self.state_tab, self.state_size = st['tabs'], st['sizes']
        self.learn = [cfg['firmTypes'][i] == 'learn' for i in range(n)]
        self.rule_tab = [None if self.learn[i] else rule_table(mk, i, cfg['firmTypes'][i]) for i in range(n)]
        # Initial Q: the average profit of each own price against uniformly random rival prices, forever.
        self.Q, self.best, self.best_v = [], [], []
        for i in range(n):
            if not self.learn[i]:
                Q = best = best_v = None
            elif cfg['sharedVendor'] and i > 0:
                Q, best, best_v = self.Q[0], self.best[0], self.best_v[0]
            else:
                own = [j // m ** i % m for j in range(n_joint)]
                avg = [0] * m
                for per_firm in mk['profit']:
                    prof = per_firm[i]
                    for j in range(n_joint):
                        avg[own[j]] += prof[j]
                count = mk['levels'] * n_joint / m
                avg = [x / count / (1 - cfg['delta']) for x in avg]
                # Every state starts from the same row, so its best action and value are found once.
                bv, ba = -INF, 0
                for a, x in enumerate(avg):
                    if x > bv:
                        bv, ba = x, a
                S = self.state_size[i]
                Q, best, best_v = avg * S, [ba] * S, [bv] * S
            self.Q.append(Q)
            self.best.append(best)
            self.best_v.append(best_v)
        self.rng = Rng(cfg['seed'])
        # Start from a random set of prices.
        self.last = encode_joint([self.rng.int(m) for _ in range(n)], m)
        self.t = 0
        self.eps = 1
        self.decay = det_exp(-cfg['beta'])
        self.stable = 0
        self.converged = False
        self.done = False
        self.block = 10000
        self.history = []           # one point per block: mean price and profit per seller
        self._acc = {'price': [0] * n, 'profit': [0] * n, 'count': 0}
        self._fast = True           # use the specialised two-seller loop when it applies

    def run(self, max_steps=None):
        """Run up to ``max_steps`` more periods. Returns True when training has finished."""
        if self.done:
            return True
        if max_steps is None:
            return self.done
        end = self.t + max_steps
        if not end > self.t:
            return self.done
        room = max(self.cfg['maxPeriods'] - self.t, 1)
        allowed = room if end == INF else min(math.ceil(end - self.t), room)
        if self._fast and self.market['n'] == 2:
            self._run_pair(allowed)
        else:
            self._run_any(allowed)
        return self.done

    def _run_pair(self, allowed):
        """The training loop for two sellers, unrolled, with the generator inlined.

        It performs exactly the same arithmetic and generator calls as the
        JavaScript loop. Notes on the rewrites:

        * ``rng.next() < eps`` is ``x / 2**32 < eps``, which is the same test as
          ``x < eps * 2**32`` because both scalings by a power of two are exact.
        * ``Math.floor(rng.next() * k)`` is ``(x * k) >> 32``: ``x * k`` is below
          2**53, so ``x / 2**32 * k`` is exact and its floor is that shift.
        * A seller's state next period is ``state_tab[i][joint]``, which the
          update has just looked up, so it is carried over.
        * ``stable = changed ? 0 : stable + 1`` becomes ``stable = -1`` on a
          change followed by ``stable += 1``.
        * The period counter and block counter are advanced once per run of
          periods up to the next block boundary; the convergence test is still
          made after every period.
        """
        cfg, mk = self.cfg, self.market
        m, levels = mk['m'], mk['levels']
        noisy = levels > 1
        alpha, delta, floor = cfg['alpha'], cfg['delta'], cfg['exploreFloor']
        oma = 1 - alpha
        decay, window, max_t = self.decay, cfg['stableWindow'], cfg['maxPeriods']
        block, history = self.block, self.history
        learn0, learn1 = self.learn
        tab0, tab1 = self.state_tab
        rule0, rule1 = self.rule_tab
        best0, best1 = self.best
        val0, val1 = self.best_v
        (rows0, rows1), pairs = _row_views(self.Q, m)
        prof0 = [lv[0] for lv in mk['profit']]
        prof1 = [lv[1] for lv in mk['profit']]
        pr0, pr1 = prof0[0], prof1[0]
        g0, g1 = mk['grids']
        acc = self._acc
        sp0, sp1 = acc['price']
        sr0, sr1 = acc['profit']
        count = acc['count']
        st, last, t, eps, stable = self.rng.a, self.last, self.t, self.eps, self.stable
        thr = eps * _TWO32
        s0 = tab0[last] if learn0 else 0
        s1 = tab1[last] if learn1 else 0
        finished = False
        while allowed > 0:
            chunk = min(block - count, allowed)
            steps = chunk
            for k in range(chunk):
                # seller 0 picks a price
                if learn0:
                    st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                    x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                    x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                    if (x ^ (x >> 14)) < thr:
                        st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                        x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                        x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                        a0 = ((x ^ (x >> 14)) * m) >> 32
                    else:
                        a0 = best0[s0]
                else:
                    a0 = rule0[last]
                # seller 1 picks a price
                if learn1:
                    st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                    x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                    x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                    if (x ^ (x >> 14)) < thr:
                        st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                        x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                        x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                        a1 = ((x ^ (x >> 14)) * m) >> 32
                    else:
                        a1 = best1[s1]
                else:
                    a1 = rule1[last]
                joint = a0 + a1 * m
                if noisy:
                    st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                    x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                    x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                    lvl = ((x ^ (x >> 14)) * levels) >> 32
                    pr0 = prof0[lvl]
                    pr1 = prof1[lvl]
                # seller 0 learns
                r = pr0[joint]
                sp0 += g0[a0]
                sr0 += r
                if learn0:
                    ns = tab0[joint]
                    row = rows0[s0]
                    nq = oma * row[a0] + alpha * (r + delta * val0[ns])
                    row[a0] = nq
                    b = best0[s0]
                    if a0 == b:
                        if nq >= val0[s0]:
                            val0[s0] = nq
                        else:
                            bv = max(row)
                            ba = row.index(bv)
                            best0[s0] = ba
                            val0[s0] = bv
                            if ba != b:
                                stable = -1
                    elif nq > val0[s0]:
                        best0[s0] = a0
                        val0[s0] = nq
                        stable = -1
                    s0 = ns
                # seller 1 learns (after seller 0, which matters when they share one table)
                r = pr1[joint]
                sp1 += g1[a1]
                sr1 += r
                if learn1:
                    ns = tab1[joint]
                    row = rows1[s1]
                    nq = oma * row[a1] + alpha * (r + delta * val1[ns])
                    row[a1] = nq
                    b = best1[s1]
                    if a1 == b:
                        if nq >= val1[s1]:
                            val1[s1] = nq
                        else:
                            bv = max(row)
                            ba = row.index(bv)
                            best1[s1] = ba
                            val1[s1] = bv
                            if ba != b:
                                stable = -1
                    elif nq > val1[s1]:
                        best1[s1] = a1
                        val1[s1] = nq
                        stable = -1
                    s1 = ns
                last = joint
                stable += 1
                eps = eps * decay
                if eps < floor:
                    eps = floor
                thr = eps * _TWO32
                if stable >= window:
                    steps = k + 1
                    break
            t += steps
            count += steps
            allowed -= steps
            if count == block:
                history.append({'t': t, 'eps': eps, 'price': [sp0 / block, sp1 / block],
                                'profit': [sr0 / block, sr1 / block]})
                sp0 = sp1 = sr0 = sr1 = count = 0
            if stable >= window:
                self.converged = finished = True
                break
            if t >= max_t:
                finished = True
                break
        _write_back(pairs)
        acc['price'], acc['profit'], acc['count'] = [sp0, sp1], [sr0, sr1], count
        self.rng.a, self.last, self.t, self.eps, self.stable = st, last, t, eps, stable
        if finished:
            self.done = True

    def _run_any(self, allowed):
        """The training loop for any number of sellers (the same arithmetic as ``_run_pair``)."""
        cfg, mk = self.cfg, self.market
        n, m, levels = mk['n'], mk['m'], mk['levels']
        firms = range(n)
        noisy = levels > 1
        alpha, delta, floor = cfg['alpha'], cfg['delta'], cfg['exploreFloor']
        oma = 1 - alpha
        decay, window, max_t = self.decay, cfg['stableWindow'], cfg['maxPeriods']
        block, history = self.block, self.history
        learn, tabs, rules, bests, vals = self.learn, self.state_tab, self.rule_tab, self.best, self.best_v
        rowsets, pairs = _row_views(self.Q, m)
        profit, grids = mk['profit'], mk['grids']
        prof = profit[0]
        mults = [m ** i for i in firms]
        acc = self._acc
        sp, sr, count = list(acc['price']), list(acc['profit']), acc['count']
        st, last, t, eps, stable = self.rng.a, self.last, self.t, self.eps, self.stable
        thr = eps * _TWO32
        states = [tabs[i][last] if learn[i] else 0 for i in firms]
        acts = [0] * n
        finished = False
        while allowed > 0:
            chunk = min(block - count, allowed)
            steps = chunk
            for k in range(chunk):
                joint = 0
                for i in firms:
                    if learn[i]:
                        st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                        x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                        x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                        if (x ^ (x >> 14)) < thr:
                            st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                            x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                            x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                            ai = ((x ^ (x >> 14)) * m) >> 32
                        else:
                            ai = bests[i][states[i]]
                    else:
                        ai = rules[i][last]
                    acts[i] = ai
                    joint += ai * mults[i]
                if noisy:
                    st = (st + 0x6D2B79F5) & 0xFFFFFFFF
                    x = ((st ^ (st >> 15)) * (st | 1)) & 0xFFFFFFFF
                    x = ((x + (x ^ (x >> 7)) * (x | 61)) & 0xFFFFFFFF) ^ x
                    prof = profit[((x ^ (x >> 14)) * levels) >> 32]
                for i in firms:
                    r = prof[i][joint]
                    a = acts[i]
                    sp[i] += grids[i][a]
                    sr[i] += r
                    if not learn[i]:
                        continue
                    s, ns, best, val = states[i], tabs[i][joint], bests[i], vals[i]
                    row = rowsets[i][s]
                    nq = oma * row[a] + alpha * (r + delta * val[ns])
                    row[a] = nq
                    b = best[s]
                    if a == b:
                        if nq >= val[s]:
                            val[s] = nq
                        else:
                            bv = max(row)
                            ba = row.index(bv)
                            best[s] = ba
                            val[s] = bv
                            if ba != b:
                                stable = -1
                    elif nq > val[s]:
                        best[s] = a
                        val[s] = nq
                        stable = -1
                    states[i] = ns
                last = joint
                stable += 1
                eps = eps * decay
                if eps < floor:
                    eps = floor
                thr = eps * _TWO32
                if stable >= window:
                    steps = k + 1
                    break
            t += steps
            count += steps
            allowed -= steps
            if count == block:
                history.append({'t': t, 'eps': eps, 'price': [x / block for x in sp],
                                'profit': [x / block for x in sr]})
                sp, sr, count = [0] * n, [0] * n, 0
            if stable >= window:
                self.converged = finished = True
                break
            if t >= max_t:
                finished = True
                break
        _write_back(pairs)
        acc['price'], acc['profit'], acc['count'] = sp, sr, count
        self.rng.a, self.last, self.t, self.eps, self.stable = st, last, t, eps, stable
        if finished:
            self.done = True

    def run_to_end(self):
        while not self.run(1000000):
            pass
        return self

    def greedy_actions(self, joint):
        """The prices every seller charges next, given last period's prices, with no exploration."""
        return [self.best[i][self.state_tab[i][joint]] if self.learn[i] else self.rule_tab[i][joint]
                for i in range(self.market['n'])]

    def greedy_next(self, joint):
        return encode_joint(self.greedy_actions(joint), self.market['m'])


def limit_cycle(tr, start=None):
    """Follow the learned strategies from a starting point until prices repeat."""
    seen, path = {}, []
    j = tr.last if start is None else start
    for _ in range(tr.market['nJoint'] + 2):
        if j in seen:
            return {'states': path[seen[j]:], 'transient': seen[j]}
        seen[j] = len(path)
        path.append(j)
        j = tr.greedy_next(j)
    return {'states': [j], 'transient': len(path)}


def outcome_of(mk, joint_list):
    n = mk['n']
    avg_p, avg_pi, cs = [0] * n, [0] * n, 0
    for jt in joint_list:
        a = decode_joint(jt, n, mk['m'])
        prices = [mk['grids'][i][a[i]] for i in range(n)]
        pr = profits_at(prices, mk['quality'], mk['cost'], mk['outside'], mk['mu'])
        for i in range(n):
            avg_p[i] += prices[i]
            avg_pi[i] += pr[i]
        cs += consumer_surplus(prices, mk['quality'], mk['outside'], mk['mu'])
    L = len(joint_list)
    avg_p = [_div(x, L) for x in avg_p]
    avg_pi = [_div(x, L) for x in avg_pi]
    gain = [_div(avg_pi[i] - mk['piN'][i], mk['piM'][i] - mk['piN'][i]) for i in range(n)]
    cs = _div(cs, L)
    return {'price': avg_p, 'profit': avg_pi, 'gain': gain, 'avgGain': mean(gain),
            'cs': cs, 'harm': _div(mk['csN'] - cs, mk['csN'] - mk['csM'])}


def static_best_response(mk, i, joint):
    """Static best response of seller i to rivals' prices in a joint action (no shocks)."""
    a = decode_joint(joint, mk['n'], mk['m'])
    best, bv = 0, -INF
    for k in range(mk['m']):
        a[i] = k
        v = mk['profit'][0][i][encode_joint(a, mk['m'])]
        if v > bv:
            bv, best = v, k
    return best


def impulse_response(tr, opts=None):
    """Force one seller to charge a different price for one period, then let the strategies play on.

    The horizon is a whole number of periods from 2 to 500 (default 25).
    """
    opts = opts or {}
    mk = tr.market
    n, m, grids, profit0 = mk['n'], mk['m'], mk['grids'], mk['profit'][0]
    cyc = opts.get('cycle')
    if not _truthy(cyc):
        cyc = limit_cycle(tr)['states']
    L = len(cyc)
    dev = _or(opts.get('deviator'), 0)
    delta = tr.cfg['delta']
    H = 25 if opts.get('horizon') is None else _floor(_to_number(opts['horizon']))
    if not (H >= 2):
        H = 2
    if H > 500:
        H = 500
    j0, cf1 = cyc[0], cyc[1 % L]
    cf_acts = decode_joint(cf1, n, m)
    dev_act = opts.get('price')
    if dev_act is None or dev_act == 'best':
        dev_act = static_best_response(mk, dev, cf1)
        if dev_act == cf_acts[dev]:
            dev_act = max(0, cf_acts[dev] - 1)
    acts1 = tr.greedy_actions(j0)
    acts1[dev] = dev_act
    j = encode_joint(acts1, m)
    path, cf_path = [j0, j], [j0, cf1]
    for t in range(2, H + 1):
        j = tr.greedy_next(j)
        path.append(j)
        cf_path.append(cyc[t % L])
    prices, cf_prices = [[] for _ in range(n)], [[] for _ in range(n)]
    profits, cf_profits = [[] for _ in range(n)], [[] for _ in range(n)]
    for t in range(H + 1):
        a, b = decode_joint(path[t], n, m), decode_joint(cf_path[t], n, m)
        for i in range(n):
            prices[i].append(grids[i][a[i]])
            cf_prices[i].append(grids[i][b[i]])
            profits[i].append(profit0[i][path[t]])
            cf_profits[i].append(profit0[i][cf_path[t]])
    gain_now = profits[dev][1] - cf_profits[dev][1]
    later, disc = 0.0, 1.0
    for t in range(2, H + 1):
        disc *= delta
        later += disc * (profits[dev][t] - cf_profits[dev][t])
    cyc_set = set(cyc)
    returned = next((t for t in range(2, H + 1) if path[t] in cyc_set), None)
    # Did any rival answer with a lower price than it would otherwise have charged?
    rival_cut, deepest = False, 0
    for i in range(n):
        if i == dev:
            continue
        if cf_prices[i][2] - prices[i][2] > 1e-12:
            rival_cut = True
        for t in range(2, H + 1):
            d = cf_prices[i][t] - prices[i][t]
            if d > deepest:
                deepest = d
    return {
        'deviator': dev, 'devPrice': grids[dev][dev_act], 'devAction': dev_act, 'horizon': H,
        'prices': prices, 'cfPrices': cf_prices, 'profits': profits, 'cfProfits': cf_profits,
        'gainNow': gain_now, 'lossLater': -later, 'net': gain_now + later,
        'rivalCut': rival_cut, 'deepestCut': deepest, 'returnedAt': returned, 'tempting': gain_now > 0,
        # punished: the cut pays on the day, a rival answers with a lower price, and the cut loses money overall
        'punished': rival_cut and gain_now > 0 and gain_now + later < 0,
    }


def summarise(tr):
    """Summary of a finished (or stopped) training run."""
    mk = tr.market
    lc = limit_cycle(tr)
    out = outcome_of(mk, lc['states'])
    ir = impulse_response(tr, {'cycle': lc['states']})
    tail = tr.history[-10:]
    realised = []
    for i in range(mk['n']):
        if not tail:
            realised.append(out['gain'][i])     # no history yet: fall back on the cycle's gain
            continue
        s = 0
        for pt in tail:
            s += pt['profit'][i]
        realised.append(_div(s / len(tail) - mk['piN'][i], mk['piM'][i] - mk['piN'][i]))
    return {
        'converged': tr.converged, 'periods': tr.t, 'cycleLength': len(lc['states']), 'cycle': lc['states'],
        'price': out['price'], 'profit': out['profit'], 'gain': out['gain'], 'avgGain': out['avgGain'],
        'harm': out['harm'], 'realisedGain': mean(realised),
        'punished': ir['punished'], 'rivalCut': ir['rivalCut'], 'devNet': ir['net'], 'returnedAt': ir['returnedAt'],
        'collusive': ir['punished'] and out['avgGain'] >= 0.2,
    }


def train(cfg=None):
    return Trainer(cfg).run_to_end()


def best_response_check(tr, i, cycle=None):
    """Holding every rival's learned strategy fixed, is seller i's learned strategy its best long-run reply?

    Solved exactly by value iteration over all possible sets of last prices
    (at most 5000 sweeps; ``settled`` says whether it converged). Each sweep
    uses ``map`` so that it runs at C speed; each value is still
    ``R[s*m + a] + delta * V[NS[s*m + a]]`` and each state's value is the
    largest of its row, exactly as in the JavaScript loop.
    """
    if not tr.learn[i]:
        return None
    mk = tr.market
    m, nJ, levels, profit = mk['m'], mk['nJoint'], mk['levels'], mk['profit']
    delta = tr.cfg['delta']
    R, NS = [0.0] * (nJ * m), [0] * (nJ * m)
    for s in range(nJ):
        acts = tr.greedy_actions(s)
        for a in range(m):
            acts[i] = a
            j = encode_joint(acts, m)
            r = 0
            for lv in range(levels):
                r += profit[lv][i][j]
            R[s * m + a] = r / levels
            NS[s * m + a] = j
    V = [0.0] * nJ
    settled = False
    for iters in range(1, 5001):
        values = map(add, R, map(mul, repeat(delta), map(V.__getitem__, NS)))
        it = iter(values)
        next_v = list(map(max, *([it] * m)))       # m >= 5, so max gets one row of m values at a time
        change = max(map(abs, map(sub, next_v, V)))
        V = next_v
        if change < 1e-11:
            settled = True
            break
    best_i, tab_i = tr.best[i], tr.state_tab[i]
    # Value of keeping the learned strategy, by iterating its own Bellman equation.
    LA = [best_i[tab_i[s]] for s in range(nJ)]
    RL = [R[s * m + LA[s]] for s in range(nJ)]
    NL = [NS[s * m + LA[s]] for s in range(nJ)]
    W = [0.0] * nJ
    for _ in range(5000):
        next_w = list(map(add, RL, map(mul, repeat(delta), map(W.__getitem__, NL))))
        ch2 = max(map(abs, map(sub, next_w, W)))
        W = next_w
        if ch2 < 1e-11:
            break
    optimal, gap_sum, on_path, on_path_gap, reply_gain = 0, 0, True, 0, 0
    on_set = set(cycle) if _truthy(cycle) else set()
    for s in range(nJ):
        la = best_i[tab_i[s]]
        lv = R[s * m + la] + delta * V[NS[s * m + la]]
        vs = V[s]
        gap = vs - lv
        av = -vs if vs < 0 else vs
        rel = gap / av if vs != 0 else 0
        if gap <= 1e-8 * av + 1e-12:
            optimal += 1
        elif s in on_set:
            on_path = False
        if s in on_set and rel > on_path_gap:
            on_path_gap = rel
        if s in on_set and W[s] > 0:
            g2 = (vs - W[s]) / W[s]
            if g2 > reply_gain:
                reply_gain = g2
        gap_sum += rel
    return {'firm': i, 'shareOptimal': optimal / nJ, 'onPathOptimal': on_path, 'onPathGap': on_path_gap,
            'bestReplyGain': reply_gain, 'meanGap': gap_sum / nJ, 'iterations': iters, 'settled': settled}


# ---------------------------------------------------------------- scenarios

SCENARIOS = [
    {'id': 'baseline', 'group': 'baseline', 'label': 'Both learn and see all prices', 'change': {},
     'note': 'The textbook case: two self-learning sellers who can see what each other charged yesterday.'},
    {'id': 'own', 'group': 'remedy', 'label': 'Rivals\u2019 prices banned as an input', 'change': {'memory': 'own'},
     'note': 'Each algorithm may only use its own past price, not what rivals charged.'},
    {'id': 'myopic', 'group': 'remedy', 'label': 'Rewarded on today\u2019s profit only', 'change': {'delta': 0},
     'note': 'The algorithm is told to maximise today\u2019s profit, with no weight on the future.'},
    {'id': 'third', 'group': 'remedy', 'label': 'A third seller enters', 'change': {'nFirms': 3, 'maxPeriods': 6000000},
     'note': 'Another self-learning seller joins the market.'},
    {'id': 'fixedrival', 'group': 'remedy', 'label': 'Rival keeps a fixed competitive price',
     'change': {'firmTypes': ['learn', 'nash', 'learn']},
     'note': 'One seller ignores the algorithm and always charges the competitive price.'},
    {'id': 'floor', 'group': 'remedy', 'label': 'Must keep testing prices (5% of days)', 'change': {'exploreFloor': 0.05},
     'note': 'A rule that algorithms keep experimenting, so no pattern is ever fully settled.'},
    {'id': 'none', 'group': 'design', 'label': 'No memory at all', 'change': {'memory': 'none'},
     'note': 'Neither algorithm remembers any past price, so neither can punish.'},
    {'id': 'matcher', 'group': 'risk', 'label': 'Rival matches the cheapest price',
     'change': {'firmTypes': ['learn', 'match', 'learn']},
     'note': 'One seller uses a simple price-match rule instead of learning.'},
    {'id': 'vendor', 'group': 'risk', 'label': 'Both buy the same pricing tool', 'change': {'sharedVendor': True},
     'note': 'One vendor\u2019s algorithm learns from both sellers\u2019 sales at once (hub and spoke).'},
    {'id': 'noisy', 'group': 'risk', 'label': 'Busy and quiet days', 'change': {'demandNoise': 0.2},
     'note': 'Demand swings from day to day, so profits are noisier to learn from.'},
]


def scenario_by_id(id):
    return next((sc for sc in SCENARIOS if sc['id'] == id), None)


def apply_scenario(base, id):
    sc = scenario_by_id(id)
    if not sc:
        raise ValueError('unknown scenario ' + _to_string(id))
    out = {k: list(v) if isinstance(v, list) else v for k, v in base.items()}
    for k, v in sc['change'].items():
        if k == 'firmTypes':
            types = out.get('firmTypes')
            out['firmTypes'] = list(types) if _truthy(types) else ['learn', 'learn', 'learn']
            for f, typ in enumerate(v):
                if typ != 'learn':
                    _js_set(out['firmTypes'], f, typ)
        elif k == 'maxPeriods':
            out['maxPeriods'] = _js_max(_or(out.get('maxPeriods'), 0), v)
        else:
            out[k] = list(v) if isinstance(v, list) else v
    if _truthy(out.get('sharedVendor')):
        g, n_f = 1, _or(out.get('nFirms'), 2)
        while g < n_f:
            _js_set(out['quality'], g, out['quality'][0])
            _js_set(out['cost'], g, out['cost'][0])
            g += 1
    return out


def run_scenario(base, id, seed):
    cfg = apply_scenario(base, id)
    cfg['seed'] = seed
    s = summarise(train(cfg))
    s['scenario'], s['seed'] = id, seed
    return s


def aggregate(results):
    n = len(results) or 1
    return {
        'runs': len(results),
        'gain': bootstrap_mean([r['realisedGain'] for r in results], 0.9, 1000, 101),
        'harm': bootstrap_mean([r['harm'] for r in results], 0.9, 1000, 202),
        'punishedShare': sum(1 for r in results if _truthy(r['punished'])) / n,
        'convergedShare': sum(1 for r in results if _truthy(r['converged'])) / n,
        'collusiveShare': sum(1 for r in results if _truthy(r['collusive'])) / n,
    }


# ---------------------------------------------------------------- what a regulator sees

def observe(tr, opts=None):
    """A year of daily prices once the algorithms are deployed.

    On a small share of days each seller tries a random price (a test or a
    promotion); otherwise it follows its strategy.
    """
    opts = opts or {}
    mk = tr.market
    n, m, grids = mk['n'], mk['m'], mk['grids']
    test = opts.get('experiment')
    if test is None:
        test = 0.03
    rng = Rng(99 if opts.get('seed') is None else opts['seed'])
    j = limit_cycle(tr)['states'][0]
    prices = [[] for _ in range(n)]
    for _ in range(_count(_or(opts.get('days'), 365))):
        acts = tr.greedy_actions(j)
        for i in range(n):
            if rng.next() < test:
                acts[i] = rng.int(m)
        j = encode_joint(acts, m)
        for i in range(n):
            prices[i].append(grids[i][acts[i]])
    return prices


def screens(prices, opts=None):
    """Screens a competition authority could run on daily prices alone.

    prices: one list of daily prices per seller. opts: ``tol`` (default 0.005),
    ``window`` (default 10), ``cost`` (optional list of unit costs) and
    ``detail`` (also return ``eventList``; the key is absent otherwise, as the
    JavaScript leaves it undefined).
    """
    opts = opts or {}
    n, T = len(prices), len(prices[0])
    tol = 0.005 if opts.get('tol') is None else opts['tol']
    win = _or(opts.get('window'), 10)
    cost = opts.get('cost') if _truthy(opts.get('cost')) else None
    detail = _truthy(opts.get('detail'))
    keep = 1 - tol
    margin_sum, margin_n, cvs = 0, 0, []
    for i, p in enumerate(prices):
        cvs.append(_div(sd(p), mean(p)))
        if cost is not None:
            for t in range(T):
                margin_sum += _div(p[t] - cost[i], p[t])
                margin_n += 1

    def cut(k, tt):
        return prices[k][tt] < prices[k][tt - 1] * keep

    def still(k, tt):
        b = prices[k][tt - 1]
        return abs(prices[k][tt] - b) <= tol * b

    events = followed = back = punish_back = quiet = quiet_cuts = 0
    size_sum = 0
    lst = []
    for t in range(1, T - 1):
        if all(still(i, t) for i in range(n)):
            # base rate: how often does someone cut on a day that follows a quiet day?
            for j in range(n):
                quiet += 1
                if cut(j, t + 1):
                    quiet_cuts += 1
            continue
        for i in range(n):
            if not cut(i, t) or not all(still(j, t) for j in range(n) if j != i) or t < 2:
                continue
            # only a cut out of a calm day counts, so a rival's answer is not itself counted as a new cut
            if not all(still(j, t - 1) for j in range(n)):
                continue
            events += 1
            any_follow, biggest = False, 0
            for j in range(n):
                if j != i and cut(j, t + 1):
                    any_follow = True
                    sz = _div(prices[j][t] - prices[j][t + 1], prices[j][t])
                    if sz > biggest:
                        biggest = sz
            if any_follow:
                followed += 1
                size_sum += biggest
            # snap-back: within the window, every seller is back to at least its pre-cut price
            ok = False
            u = t + 1
            while u <= t + win and u < T:
                if not any(prices[j][u] < prices[j][t - 1] * keep for j in range(n)):
                    ok = True
                    break
                u += 1
            if ok:
                back += 1
                if any_follow:
                    punish_back += 1
            if detail:
                lst.append({'t': t, 'who': i, 'followed': any_follow, 'back': ok})
    follow_rate = followed / events if events else NAN
    base_rate = quiet_cuts / quiet if quiet else 0
    out = {
        'days': T, 'margin': _div(margin_sum, margin_n) if cost is not None else None, 'cv': mean(cvs),
        'events': events, 'followRate': follow_rate, 'baseRate': base_rate,
        'retaliation': follow_rate - base_rate if events else NAN,
        'responseSize': size_sum / followed if followed else 0,
        'snapBack': back / events if events else NAN,
        'punishReturn': punish_back / events if events else NAN,
    }
    if detail:
        out['eventList'] = lst
    return out


def permutation_test(prices, opts=None):
    """Is the follow rate higher than it would be if the rivals' timing were unrelated?

    Shifts every rival's series round in a circle by a random amount and recomputes.
    """
    opts = opts or {}
    rng = Rng(4242 if opts.get('seed') is None else opts['seed'])
    T = len(prices[0])
    obs = screens(prices, opts)['retaliation']
    if obs != obs or T < 30:
        return {'observed': obs, 'pValue': NAN, 'reps': 0}
    margin = _or(opts.get('window'), 10)
    ge = valid = 0
    for _ in range(_count(_or(opts.get('reps'), 999))):
        k = margin + rng.int(T - 2 * margin)
        shifted = [prices[0]] + [p[k:] + p[:k] for p in prices[1:]]
        v = screens(shifted, opts)['retaliation']
        if v != v:
            continue
        valid += 1
        if v >= obs - 1e-12:
            ge += 1
    return {'observed': obs, 'pValue': (ge + 1) / (valid + 1), 'reps': valid}


CASE_MIX = ['baseline', 'baseline', 'vendor', 'matcher', 'noisy', 'own', 'myopic', 'fixedrival', 'none', 'floor']
CASE_MU = [0.1, 0.25, 0.5]


def case_config(base, k, seed):
    """Market k's hidden set-up in a file of simulated markets."""
    rng = Rng(_to_number(seed) * 7919 + _to_number(k) * 104729 + 17)
    id = CASE_MIX[rng.int(len(CASE_MIX))]
    mu = CASE_MU[rng.int(len(CASE_MU))]
    cfg = apply_scenario(base, id)
    cfg['mu'] = mu
    cfg['nFirms'] = 2
    cfg['seed'] = 1 + rng.int(1000000)
    return {'k': k, 'scenario': id, 'mu': mu, 'cfg': cfg}


def finish_case(tr, meta, opts=None):
    """Turn a market's trained sellers into a case: the hidden truth and the prices a regulator sees."""
    opts = opts or {}
    s = summarise(tr)
    experiment = opts.get('experiment')
    prices = observe(tr, {'days': _or(opts.get('days'), 365),
                          'experiment': 0.03 if experiment is None else experiment,
                          'seed': meta['cfg']['seed'] + 1})
    return {
        'id': meta['k'] + 1, 'scenario': meta['scenario'], 'mu': meta['mu'], 'seed': meta['cfg']['seed'],
        'truth': {'coordinated': s['collusive'], 'highPrice': s['avgGain'] >= 0.5, 'gain': s['avgGain'],
                  'punished': s['punished']},
        'screens': screens(prices, {'cost': tr.market['cost']}), 'prices': prices,
        'competitive': list(tr.market['pN']), 'monopoly': list(tr.market['pM']),
    }


def make_case(base, k, seed, opts=None):
    meta = case_config(base, k, seed)
    return finish_case(train(meta['cfg']), meta, opts)


SCREEN_LIST = [
    {'id': 'margin', 'label': 'High margin', 'sign': 1, 'note': 'Average (price \u2212 cost) / price.'},
    {'id': 'stability', 'label': 'Stable prices', 'sign': 1,
     'note': 'Low day-to-day variation (scored as minus the coefficient of variation).'},
    {'id': 'retaliation', 'label': 'Rivals hit back', 'sign': 1,
     'note': 'How much more often a rival cuts the day after an unprovoked cut than on an ordinary day.'},
    {'id': 'snapBack', 'label': 'Prices snap back', 'sign': 1,
     'note': 'Share of unprovoked cuts after which every price is back up within 10 days.'},
    {'id': 'punishReturn', 'label': 'Hit back, then back up', 'sign': 1,
     'note': 'Share of unprovoked cuts that a rival answers the next day and after which every price is back up '
             'within 10 days.'},
]


def screen_score(sc, id):
    if id == 'margin':
        return NAN if sc.get('margin') is None else sc['margin']
    if id == 'stability':
        # JavaScript negates a double, so a cv of 0 (an int when read from JSON) must give -0.
        return -_to_number(sc['cv'])
    if id in ('retaliation', 'snapBack', 'punishReturn'):
        return 0 if sc[id] != sc[id] else sc[id]
    return NAN


def evaluate_screens(cases, target):
    labels = [c['truth']['highPrice'] if target == 'highPrice' else c['truth']['coordinated'] for c in cases]
    out = []
    for s in SCREEN_LIST:
        scores = [screen_score(c['screens'], s['id']) for c in cases]
        roc = roc_curve(scores, labels)
        out.append({'id': s['id'], 'label': s['label'], 'auc': roc['auc'], 'roc': roc, 'scores': scores})
    return out


def confusion(scores, labels, threshold):
    """Flag every market at or above a threshold; count what that catches and what it wrongly flags."""
    tp = fp = fn = tn = 0
    for i, score in enumerate(scores):
        flag = score >= threshold
        lab = i < len(labels) and _truthy(labels[i])
        if flag and lab:
            tp += 1
        elif flag:
            fp += 1
        elif lab:
            fn += 1
        else:
            tn += 1
    return {'caught': tp, 'falseAlarms': fp, 'missed': fn, 'cleared': tn,
            'precision': tp / (tp + fp) if tp + fp else NAN, 'recall': tp / (tp + fn) if tp + fn else NAN}
