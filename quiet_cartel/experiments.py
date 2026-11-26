"""Batches of training runs: remedies compared with the baseline, and parameter sweeps.

Every run trains the sellers once with :func:`quiet_cartel.model.train` and
summarises the result with :func:`quiet_cartel.model.summarise`, exactly as the
browser app's "Remedies" tab does. Runs are independent, so a batch is spread
over worker processes; results always come back in the order the runs were
listed, so a batch gives the same numbers whatever the number of workers.

The per-scenario summary uses :func:`quiet_cartel.model.aggregate`, so the
mean and 90% interval for each option are identical to the browser app's for
the same runs (seeds 1 to N, in that order). On top of that this module adds a
paired comparison with the baseline (see :func:`paired_comparison`), which the
app does not attempt.
"""

import multiprocessing
import os

from . import model

__all__ = [
    'run_one', 'run_batch', 'summarise_batch', 'paired_comparison', 'sign_flip_test', 'holm',
    'sweep', 'SWEEP_PARAMS', 'EXACT_MAX', 'FLIP_REPS',
]

# Parameters a sweep may vary: the numeric, single-valued config keys.
SWEEP_PARAMS = ['nFirms', 'nPrices', 'mu', 'xi', 'outside', 'alpha', 'beta', 'delta',
                'exploreFloor', 'demandNoise', 'stableWindow', 'maxPeriods']

EXACT_MAX = 16          # up to this many pairs the sign-flip test enumerates every sign pattern
FLIP_REPS = 9999        # otherwise it draws this many random patterns
FLIP_SEED = 777         # seed of the random sign patterns
BOOT_REPS = 2000        # bootstrap resamples for the paired interval
BOOT_SEEDS = {'realisedGain': 303, 'harm': 404}
COMPARED = ('realisedGain', 'harm')
NAN = float('nan')


# ------------------------------------------------------------ one run

def run_one(base, scenario, seed):
    """Train one (scenario, seed) on a base config and return a flat dict of the outcome.

    Keys: ``scenario``, ``seed``, ``converged``, ``periods``, ``avgGain`` (profit
    gain on the settled cycle), ``realisedGain`` (profit gain over the last
    100,000 rounds of training, the number the app compares), ``harm``
    (shoppers' loss as a share of the gap between their surplus at competitive
    and at monopoly prices), ``punished``, ``collusive``, ``cycleLength`` and ``meanPrice``
    (average settled price over sellers). With two sellers it also has
    ``brGapA`` and ``brGapB``: the ``onPathGap`` of
    :func:`quiet_cartel.model.best_response_check`, or ``None`` for a seller that
    follows a fixed rule. That is the most a learning seller could gain by
    choosing a better price for one day where play settled and replying
    optimally afterwards, as a share of its best long-run profit. Being a
    one-day measure it is roughly (1 - delta) times what a seller could gain by
    changing its strategy for good, so a small gap does not by itself mean the
    learned strategies are close to an equilibrium.
    """
    cfg = model.apply_scenario(base, scenario)
    cfg['seed'] = seed
    tr = model.train(cfg)
    s = model.summarise(tr)
    row = {
        'scenario': scenario, 'seed': seed, 'converged': s['converged'], 'periods': s['periods'],
        'avgGain': s['avgGain'], 'realisedGain': s['realisedGain'], 'harm': s['harm'],
        'punished': s['punished'], 'collusive': s['collusive'], 'cycleLength': s['cycleLength'],
        'meanPrice': model.mean(s['price']),
    }
    if tr.market['n'] == 2:
        for i, key in enumerate(('brGapA', 'brGapB')):
            br = model.best_response_check(tr, i, s['cycle'])
            row[key] = None if br is None else br['onPathGap']
    return row


def _run_task(task):
    """Pool worker: unpack a (base, scenario, seed) task. Top level so that it can be pickled."""
    return run_one(*task)


def _run_tasks(tasks, jobs=None, progress=None):
    """Run tasks in input order, in-process when ``jobs`` is 1, otherwise in a process pool."""
    total = len(tasks)
    jobs = (os.cpu_count() or 1) if jobs is None else int(jobs)
    if jobs < 1:
        raise ValueError('jobs must be at least 1')
    if progress:
        progress(0, total, None)        # everything is checked: training starts now
    out = []
    if jobs == 1 or total <= 1:
        for task in tasks:
            out.append(_run_task(task))
            if progress:
                progress(len(out), total, out[-1])
        return out
    with multiprocessing.Pool(processes=min(jobs, total)) as pool:
        # chunksize 1: runs differ a lot in length (a third seller takes several times longer)
        for row in pool.imap(_run_task, tasks, chunksize=1):
            out.append(row)
            if progress:
                progress(len(out), total, row)
    return out


def _checked_base(base):
    """Validate a (possibly partial) base config, as the app does, and return the full config."""
    v = model.validate_config(base or {})
    if v['errors']:
        raise ValueError('the base settings are not valid: ' + '; '.join(v['errors']))
    return v['config']


def _checked_scenarios(base, scenario_ids):
    """Known ids, baseline first, no repeats, and every scenario valid on this base."""
    known = [sc['id'] for sc in model.SCENARIOS]
    ids = []
    for sid in scenario_ids:
        if sid not in known:
            raise ValueError("unknown scenario '%s' (choose from %s)" % (sid, ', '.join(known)))
        if sid not in ids:
            ids.append(sid)
    if 'baseline' not in ids:
        ids.insert(0, 'baseline')
    for sid in ids:
        errors = model.validate_config(model.apply_scenario(base, sid))['errors']
        if errors:
            raise ValueError("scenario '%s' does not fit these settings: %s" % (sid, '; '.join(errors)))
    return ids


def _checked_seeds(seeds):
    seeds = list(seeds)
    if not seeds:
        raise ValueError('give at least one seed')
    for s in seeds:
        if isinstance(s, bool) or not isinstance(s, int) or not 0 <= s <= 4294967295:
            raise ValueError('seeds must be whole numbers from 0 to 4294967295, not %r' % (s,))
    if len(set(seeds)) != len(seeds):
        raise ValueError('seeds must not repeat (runs are paired by seed)')
    return seeds


def run_batch(base, scenario_ids, seeds, jobs=None, progress=None):
    """Train every scenario with every seed on the same base config.

    The baseline is always included (first, if it was not listed). Results are
    flat dicts from :func:`run_one`, ordered scenario by scenario and, within a
    scenario, in the order of ``seeds``. ``jobs`` is the number of worker
    processes (default: one per CPU); ``jobs=1`` runs everything in this process.
    ``progress(done, total, row)`` is called with ``done = 0`` once every input
    has been checked, then as each run finishes.
    """
    base = _checked_base(base)
    ids = _checked_scenarios(base, scenario_ids)
    seeds = _checked_seeds(seeds)
    tasks = [(base, sid, seed) for sid in ids for seed in seeds]
    return _run_tasks(tasks, jobs, progress)


# ------------------------------------------------------------ statistics

def sign_flip_test(diffs, reps=FLIP_REPS, seed=FLIP_SEED, exact_max=EXACT_MAX):
    """Two-sided sign-flip permutation test that the mean paired difference is zero.

    If an option made no difference, each run's difference from its baseline
    twin would be as likely to be positive as negative, so flipping the sign of
    any difference gives an equally likely data set. The p-value is the share
    of sign patterns whose absolute total is at least as large as the observed
    one (the total and the mean give the same ordering, since the number of
    pairs is fixed).

    * With ``exact_max`` pairs or fewer every one of the 2**n patterns is
      enumerated, so the p-value is exact. It includes the observed pattern, so
      with n pairs it can never be below 2 / 2**n (0.5 with two pairs).
    * With more pairs, ``reps`` random patterns are drawn with
      :class:`quiet_cartel.model.Rng` (fixed ``seed``), and
      p = (1 + count) / (1 + reps), which never reports an impossible zero.

    Ties are counted with a relative tolerance of 1e-9 of the total absolute
    difference, so rounding never decides the result. When every difference is
    zero the p-value is 1. NaN differences are dropped; with none left the
    result is NaN.
    """
    d = [x for x in diffs if x == x]
    n = len(d)
    if n == 0:
        return {'pValue': NAN, 'pairs': 0, 'exact': None, 'reps': 0}
    obs = abs(model.sum_(d))
    scale = 0.0
    for x in d:
        scale += abs(x)
    cut = obs - 1e-9 * scale
    if n <= exact_max:
        # Every signed total, built by doubling: each entry is added up left to right like sum_.
        totals = [0.0]
        for x in d:
            totals = [t + x for t in totals] + [t - x for t in totals]
        count = 0
        for t in totals:
            if abs(t) >= cut:
                count += 1
        return {'pValue': count / len(totals), 'pairs': n, 'exact': True, 'reps': len(totals)}
    rng = model.Rng(seed)
    count = 0
    for _ in range(reps):
        t = 0.0
        for x in d:
            t += x if rng.next() < 0.5 else -x
        if abs(t) >= cut:
            count += 1
    return {'pValue': (1 + count) / (1 + reps), 'pairs': n, 'exact': False, 'reps': reps}


def holm(pvalues):
    """Holm's step-down adjustment of a family of p-values (controls the family-wise error rate).

    Sort the m valid p-values in increasing order, p(1) <= ... <= p(m). The
    adjusted value of p(k) is the largest of min(1, (m - j + 1) * p(j)) over
    j = 1..k, so adjusted values keep the order of the raw ones. ``None`` or NaN
    entries are left out of the family and come back as NaN.
    """
    valid = [i for i, p in enumerate(pvalues) if p is not None and p == p]
    m = len(valid)
    out = [NAN] * len(pvalues)
    running = 0.0
    for rank, i in enumerate(sorted(valid, key=lambda k: pvalues[k])):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        out[i] = running
    return out


def paired_comparison(rows, base_rows, key, boot_seed=303):
    """Compare one option with the baseline on ``key``, pairing runs that share a seed.

    Same seed means the same random starting prices and, until the two
    configurations diverge, the same exploration draws, so pairing removes
    much of the run-to-run noise. Returns the number of pairs, the mean
    difference (option minus baseline), a 90% percentile bootstrap interval for
    it (2,000 resamples of the pairs, :func:`quiet_cartel.model.bootstrap_mean`
    with a fixed seed) and the sign-flip p-value of :func:`sign_flip_test`.
    """
    base_by_seed = {r['seed']: r[key] for r in base_rows}
    diffs = [r[key] - base_by_seed[r['seed']] for r in rows if r['seed'] in base_by_seed]
    diffs = [x for x in diffs if x == x]
    boot = model.bootstrap_mean(diffs, 0.9, BOOT_REPS, boot_seed)
    test = sign_flip_test(diffs)
    return {'pairs': len(diffs), 'diff': boot['mean'], 'lo': boot['lo'], 'hi': boot['hi'],
            'pValue': test['pValue'], 'exact': test['exact'], 'pHolm': NAN}


def _mean_of(values):
    vals = [v for v in values if v is not None and v == v]
    return model.mean(vals) if vals else None


def summarise_batch(results):
    """Summarise a batch scenario by scenario, with paired comparisons against the baseline.

    For each scenario, in the order the runs appear:

    * ``agg``: :func:`quiet_cartel.model.aggregate` over its runs, in run
      order, so the means and 90% bootstrap intervals for profit gain and
      shoppers' loss, and the shares punished, settled and collusive, match the
      browser app's for the same runs.
    * ``meanPrice`` and ``brGap``: mean settled price, and the mean over runs
      of the larger learning seller's best-response gap (``None`` when no run
      had two sellers).
    * ``vsBaseline`` (not for the baseline): for ``realisedGain`` and ``harm``,
      the paired comparison of :func:`paired_comparison`, with ``pHolm``, the
      Holm-adjusted p-value over every non-baseline scenario in the batch. The
      two outcomes are adjusted as separate families.

    Returns ``{'order': [ids], 'scenarios': {id: summary}, 'seeds': [...]}``.
    """
    order, by_id, seeds = [], {}, []
    for r in results:
        if r['scenario'] not in by_id:
            order.append(r['scenario'])
            by_id[r['scenario']] = []
        by_id[r['scenario']].append(r)
        if r['seed'] not in seeds:
            seeds.append(r['seed'])
    if 'baseline' not in by_id:
        raise ValueError('the batch has no baseline runs to compare with')
    if 'baseline' in order:
        order.remove('baseline')
    order.insert(0, 'baseline')
    out = {}
    for sid in order:
        rows = by_id[sid]
        sc = model.scenario_by_id(sid) or {'label': sid, 'group': 'baseline', 'note': ''}
        gaps = []
        for r in rows:
            g = [r[k] for k in ('brGapA', 'brGapB') if r.get(k) is not None]
            if g:
                gaps.append(max(g))
        out[sid] = {
            'id': sid, 'label': sc['label'], 'group': sc['group'], 'note': sc['note'],
            'agg': model.aggregate(rows),
            'meanPrice': _mean_of([r['meanPrice'] for r in rows]),
            'brGap': _mean_of(gaps),
            'vsBaseline': None,
        }
        if sid != 'baseline':
            out[sid]['vsBaseline'] = {key: paired_comparison(rows, by_id['baseline'], key, BOOT_SEEDS[key])
                                      for key in COMPARED}
    others = order[1:]
    for key in COMPARED:
        adjusted = holm([out[sid]['vsBaseline'][key]['pValue'] for sid in others])
        for sid, p in zip(others, adjusted):
            out[sid]['vsBaseline'][key]['pHolm'] = p
    return {'order': order, 'scenarios': out, 'seeds': seeds}


# ------------------------------------------------------------ sweeps

def _check_param(name, values, scenario):
    if name not in SWEEP_PARAMS:
        raise ValueError("cannot sweep '%s': choose a numeric setting (%s)" % (name, ', '.join(SWEEP_PARAMS)))
    if name in model.scenario_by_id(scenario)['change'] and name != 'maxPeriods':
        raise ValueError("scenario '%s' fixes %s, so it cannot be swept" % (scenario, name))
    values = list(values)
    if not values:
        raise ValueError('give at least one value for %s' % name)
    lo, hi = model.LIMITS[name]
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            raise ValueError('%s values must be numbers, not %r' % (name, v))
        if not lo <= v <= hi:
            raise ValueError('%s must be between %s and %s, not %s' % (name, lo, hi, v))
    if len(set(values)) != len(values):
        raise ValueError('%s values must not repeat' % name)
    return values


def sweep(base, x_param, x_values, y_param, y_values, seeds, scenario='baseline', jobs=None, progress=None):
    """Train a grid of settings and report, per cell, how high prices settle.

    ``x_param`` and ``y_param`` are two different numeric config keys (see
    ``SWEEP_PARAMS``) and every value must lie within ``model.LIMITS``. Each
    cell is the base config with those two values set, then the scenario
    applied (a scenario that fixes either setting is refused), trained once per
    seed. Every cell config is validated before anything is trained.
    ``progress`` is called as in :func:`run_batch`.

    Returns the axes and ``cells[iy][ix]`` (rows follow ``y_values``, columns
    ``x_values``), each with ``runs``, ``gain`` (mean realised profit gain),
    ``harm`` (mean shoppers' loss), ``punishedShare`` and ``convergedShare``.
    """
    if scenario is None or model.scenario_by_id(scenario) is None:
        raise ValueError("unknown scenario '%s'" % (scenario,))
    if x_param == y_param:
        raise ValueError('the two sweep settings must differ')
    base = _checked_base(base)
    xs = _check_param(x_param, x_values, scenario)
    ys = _check_param(y_param, y_values, scenario)
    seeds = _checked_seeds(seeds)
    tasks = []
    for y in ys:
        for x in xs:
            cell = dict(base)
            cell[x_param], cell[y_param] = x, y
            errors = model.validate_config(model.apply_scenario(cell, scenario))['errors']
            if errors:
                raise ValueError('%s = %s, %s = %s is not valid: %s' % (x_param, x, y_param, y, '; '.join(errors)))
            tasks.extend((cell, scenario, seed) for seed in seeds)
    rows = _run_tasks(tasks, jobs, progress)
    k, per = 0, len(seeds)
    cells = []
    for y in ys:
        line = []
        for x in xs:
            runs = rows[k:k + per]
            k += per
            line.append({
                'x': x, 'y': y, 'runs': per,
                'gain': model.mean([r['realisedGain'] for r in runs]),
                'harm': model.mean([r['harm'] for r in runs]),
                'punishedShare': sum(1 for r in runs if r['punished']) / per,
                'convergedShare': sum(1 for r in runs if r['converged']) / per,
            })
        cells.append(line)
    return {'x': {'param': x_param, 'values': xs}, 'y': {'param': y_param, 'values': ys},
            'scenario': scenario, 'seeds': seeds, 'cells': cells, 'runs': rows}
