"""Fitting the Banister fitness-fatigue model to a squad's performance tests.

Each player's test result on the morning of day t is modelled as

    perf(t) = p0 + k1 * F(t; tau1) - k2 * F(t; tau2),   F(t; tau) = sum over s < t of w(s) exp(-(t - s) / tau),

where w(s) is the day's training load (minutes times rpe) from the club's logbook, tau1 is how slowly fitness
fades and tau2 how quickly fatigue does. For fixed time constants the model is linear in p0, k1 and k2, so
those three are solved exactly by least squares (with k1 and k2 kept at zero or above) and the search runs over
the two time constants only. That search is a Nelder-Mead simplex written out below, on a smooth logistic
transform that keeps 1 < tau2 < 25 and tau2 + 5 < tau1 < tau2 + 120 (fitness outlasts fatigue), from several
fixed starting points so the result never depends on luck. Exponentials come from math.exp: the calibration
is not part of the browser model and need not match it bit for bit.
"""
import math

from . import model

TAU2_RANGE = (1.0, 25.0)
GAP_RANGE = (5.0, 120.0)          # tau1 - tau2
STARTS = [(40.0, 7.0), (25.0, 4.0), (60.0, 10.0), (90.0, 15.0), (30.0, 12.0)]
MIN_TESTS = 8
PARAMS = ['p0', 'k1', 'k2', 'tau1', 'tau2']
_DATE = ['date', 'day', 'session date', 'test date']
_PLAYER = ['player', 'name', 'athlete', 'player id', 'id']
_VALUE = ['jump_cm', 'jump', 'cmj', 'value', 'score', 'result', 'performance', 'test']


# ---------- Nelder-Mead ----------
def nelder_mead(f, x0, step=0.5, max_evals=2000, xtol=1e-8, ftol=1e-12):
    """Minimises f from x0 with the Nelder-Mead simplex (standard coefficients 1, 2, 0.5, 0.5).

    step is the size of the starting simplex along each axis (one number or one per axis). It stops when
    every vertex is within xtol of the best in every coordinate and their values within ftol, or after
    max_evals evaluations. Returns {'x', 'f', 'evals', 'converged'}.
    """
    n = len(x0)
    steps = list(step) if isinstance(step, (list, tuple)) else [step] * n
    simplex = [list(map(float, x0))]
    for i in range(n):
        v = list(simplex[0])
        v[i] += steps[i]
        simplex.append(v)
    values = [f(v) for v in simplex]
    evals = n + 1
    converged = False
    while True:
        order = sorted(range(n + 1), key=lambda k: values[k])
        simplex = [simplex[k] for k in order]
        values = [values[k] for k in order]
        best = simplex[0]
        x_spread = max(abs(v[i] - best[i]) for v in simplex[1:] for i in range(n))
        f_spread = max(abs(fv - values[0]) for fv in values[1:])
        if x_spread <= xtol and f_spread <= ftol:
            converged = True
            break
        if evals >= max_evals:
            break
        centroid = [sum(v[i] for v in simplex[:n]) / n for i in range(n)]
        worst = simplex[n]

        def toward(t):
            return [c + t * (c - w) for c, w in zip(centroid, worst)]

        xr = toward(1.0)
        fr = f(xr)
        evals += 1
        if fr < values[0]:
            xe = toward(2.0)
            fe = f(xe)
            evals += 1
            simplex[n], values[n] = (xe, fe) if fe < fr else (xr, fr)
            continue
        if fr < values[n - 1]:
            simplex[n], values[n] = xr, fr
            continue
        if fr < values[n]:
            xc = toward(0.5)
            fc = f(xc)
            evals += 1
            accept = fc <= fr
        else:
            xc = toward(-0.5)
            fc = f(xc)
            evals += 1
            accept = fc < values[n]
        if accept:
            simplex[n], values[n] = xc, fc
            continue
        for k in range(1, n + 1):
            simplex[k] = [b + 0.5 * (v - b) for b, v in zip(best, simplex[k])]
            values[k] = f(simplex[k])
        evals += n
    return {'x': simplex[0], 'f': values[0], 'evals': evals, 'converged': converged}


def bounded(u, lo, hi):
    """Maps any real u smoothly onto the open interval (lo, hi)."""
    if u >= 0:
        return lo + (hi - lo) / (1 + math.exp(-u))
    e = math.exp(u)
    return lo + (hi - lo) * e / (1 + e)


def unbounded(x, lo, hi):
    """The inverse of bounded()."""
    t = (x - lo) / (hi - lo)
    return math.log(t / (1 - t))


# ---------- the Banister model ----------
def decayed_sums(loads, tau, days):
    """F(t; tau) for each t in days (ascending), with loads after the logbook's end taken as zero."""
    d = math.exp(-1 / tau)
    out, acc, t = [], 0.0, 0
    for target in days:
        while t < target:
            acc = d * (acc + (loads[t] if t < len(loads) else 0.0))
            t += 1
        out.append(acc)
    return out


def _linear_fit(f1, f2, y):
    """Least-squares p0, k1, k2 >= 0 for y = p0 + k1 f1 - k2 f2, and the residual sum of squares."""
    n = len(y)
    m1, m2, my = sum(f1) / n, sum(f2) / n, sum(y) / n
    a = [v - m1 for v in f1]
    b = [m2 - v for v in f2]
    c = [v - my for v in y]
    saa = sum(v * v for v in a)
    sbb = sum(v * v for v in b)
    sab = sum(u * v for u, v in zip(a, b))
    say = sum(u * v for u, v in zip(a, c))
    sby = sum(u * v for u, v in zip(b, c))
    syy = sum(v * v for v in c)
    # The best feasible least-squares fit over the four ways of holding k1 and/or k2 at zero is the
    # constrained optimum (the problem is convex).
    candidates = [(0.0, 0.0, syy)]
    if saa > 0:
        k1 = say / saa
        candidates.append((k1, 0.0, syy - k1 * say))
    if sbb > 0:
        k2 = sby / sbb
        candidates.append((0.0, k2, syy - k2 * sby))
    det = saa * sbb - sab * sab
    if det > 1e-12 * saa * sbb:
        k1 = (sbb * say - sab * sby) / det
        k2 = (saa * sby - sab * say) / det
        candidates.append((k1, k2, syy - k1 * say - k2 * sby))
    k1, k2, sse = min((cand for cand in candidates if cand[0] >= 0 and cand[1] >= 0), key=lambda cand: cand[2])
    return {'p0': my - k1 * m1 + k2 * m2, 'k1': k1, 'k2': k2, 'sse': max(sse, 0.0), 'syy': syy}


def _taus(u):
    tau2 = bounded(u[1], *TAU2_RANGE)
    return tau2 + bounded(u[0], *GAP_RANGE), tau2


def derived_days(k1, k2, tau1, tau2):
    """Days after a hard session until its net effect turns positive (t0) and until it peaks (tpeak).

    None means never (no fitness gain at all); 0 means from the start."""
    if not (k1 > 0) or tau1 <= tau2:
        return None, None
    scale = tau1 * tau2 / (tau1 - tau2)
    t0 = scale * math.log(k2 / k1) if k2 > k1 else 0.0
    tpeak = scale * math.log(k2 * tau1 / (k1 * tau2)) if k2 * tau1 > k1 * tau2 else 0.0
    return t0, tpeak


def fit_banister(loads, days, values):
    """The best Banister fit to one player's tests (days ascending, counted from the logbook's first day)."""

    def sse(u):
        tau1, tau2 = _taus(u)
        return _linear_fit(decayed_sums(loads, tau1, days), decayed_sums(loads, tau2, days), values)['sse']

    best = None
    for tau1, tau2 in STARTS:
        u0 = [unbounded(tau1 - tau2, *GAP_RANGE), unbounded(tau2, *TAU2_RANGE)]
        res = nelder_mead(sse, u0, step=0.6, max_evals=400, xtol=1e-5, ftol=1e-9)
        if best is None or res['f'] < best['f']:
            best = res
    tau1, tau2 = _taus(best['x'])
    lin = _linear_fit(decayed_sums(loads, tau1, days), decayed_sums(loads, tau2, days), values)
    n = len(values)
    t0, tpeak = derived_days(lin['k1'], lin['k2'], tau1, tau2)
    return {'p0': lin['p0'], 'k1': lin['k1'], 'k2': lin['k2'], 'tau1': tau1, 'tau2': tau2,
            'r2': 1 - lin['sse'] / lin['syy'] if lin['syy'] > 0 else math.nan,
            'rmse': math.sqrt(lin['sse'] / n), 'tests': n, 't0': t0, 'tpeak': tpeak}


# ---------- reading the files ----------
def _column(head, aliases):
    for a in aliases:
        if a in head:
            return head.index(a)
    return -1


def _text(row, i):
    v = row[i] if 0 <= i < len(row) else ''
    return (v or '').strip()


def _number(text):
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def read_tests(table):
    """Performance tests from CSV rows with date, player and a result column (e.g. jump_cm)."""
    if not table:
        return {'error': 'The tests file is empty.'}
    head = [h.strip().lower() for h in table[0]]
    c_date, c_player = _column(head, _DATE), _column(head, _PLAYER)
    c_value = _column(head, _VALUE)
    if c_value < 0 and len(head) == 3 and c_date >= 0 and c_player >= 0:
        c_value = 3 - c_date - c_player
    if c_date < 0 or c_player < 0 or c_value < 0:
        return {'error': 'The tests file needs date, player and result columns (for example date,player,jump_cm).'}
    tests, skipped = {}, 0
    for row in table[1:]:
        day = model.parse_day(_text(row, c_date))
        name = _text(row, c_player)
        value = _number(_text(row, c_value))
        if day is None or not name or value is None:
            skipped += 1
            continue
        tests.setdefault(name, []).append((day, value))
    if not tests:
        return {'error': 'No test rows could be read. Dates should look like 2026-09-07.'}
    warnings = []
    if skipped:
        warnings.append(f"{skipped} test row{' was' if skipped == 1 else 's were'} skipped "
                        '(unreadable date, empty player or result).')
    return {'tests': tests, 'column': head[c_value], 'warnings': warnings}


def read_truth(table):
    """True parameters per player from CSV rows with columns player, p0, k1, k2, tau1 and tau2."""
    if not table:
        return {'error': 'The truth file is empty.'}
    head = [h.strip().lower() for h in table[0]]
    cols = {k: _column(head, [k]) for k in ['player'] + PARAMS}
    if min(cols.values()) < 0:
        return {'error': 'The truth file needs the columns player, p0, k1, k2, tau1 and tau2.'}
    truth = {}
    for row in table[1:]:
        values = {k: _number(_text(row, cols[k])) for k in PARAMS}
        name = _text(row, cols['player'])
        if name and all(v is not None for v in values.values()):
            truth[name] = values
    if not truth:
        return {'error': 'No rows of the truth file could be read.'}
    return {'truth': truth}


# ---------- the squad ----------
def median(values):
    """The median of the finite values (NaN when there are none)."""
    v = sorted(x for x in values if x is not None and math.isfinite(x))
    return model.quantile(v, 0.5) if v else math.nan


def calibrate_squad(book, tests, truth=None):
    """Fits every player who has a logbook and enough tests; compares with the truth when it is given.

    book comes from model.read_logbook, tests from read_tests()['tests'] and truth from read_truth()['truth'].
    """
    index = {n: k for k, n in enumerate(book['names'])}
    players, skipped = [], []
    for name in sorted(tests, key=lambda n: index.get(n, len(index))):
        if name not in index:
            skipped.append({'player': name, 'reason': 'not in the logbook'})
            continue
        rows = sorted((day - book['start'], v) for day, v in tests[name] if day >= book['start'])
        if len(rows) < MIN_TESTS:
            skipped.append({'player': name, 'reason': f'only {len(rows)} tests on or after the first logbook day'})
            continue
        fit = fit_banister(book['loads'][index[name]], [d for d, _ in rows], [v for _, v in rows])
        fit['player'] = name
        players.append(fit)
    keys = PARAMS + ['r2', 'rmse', 't0', 'tpeak']
    out = {'players': players, 'skipped': skipped,
           'medians': {k: median([p[k] for p in players]) for k in keys}}
    if truth:
        out['truth'] = compare_truth(players, truth)
    return out


def compare_truth(players, truth):
    """Median absolute and relative errors of each parameter against the truth, beside the truth's spread."""
    matched = [(p, truth[p['player']]) for p in players if p['player'] in truth]
    out = {'players': len(matched), 'params': {}}
    for k in PARAMS:
        errors = [abs(p[k] - t[k]) for p, t in matched]
        rel = [abs(p[k] - t[k]) / abs(t[k]) for p, t in matched if t[k]]
        true_values = [t[k] for _, t in matched]
        out['params'][k] = {'medianAbsError': median(errors), 'medianRelError': median(rel),
                            'trueMedian': median(true_values), 'trueSd': model.sd(true_values)}
    true_days = [dict(zip(('t0', 'tpeak'), derived_days(t['k1'], t['k2'], t['tau1'], t['tau2'])))
                 for _, t in matched]
    for k in ('t0', 'tpeak'):
        pairs = [(p[k], td[k]) for (p, _), td in zip(matched, true_days) if p[k] is not None and td[k] is not None]
        true_values = [tv for _, tv in pairs]
        out['params'][k] = {'medianAbsError': median([abs(e - tv) for e, tv in pairs]),
                            'medianRelError': median([abs(e - tv) / tv for e, tv in pairs if tv]),
                            'trueMedian': median(true_values), 'trueSd': model.sd(true_values)}
    return out
