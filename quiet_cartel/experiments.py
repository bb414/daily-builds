"""Batches of training runs: remedies compared with the baseline, parameter sweeps, and pilots taken to scale.

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

The pilot functions (:func:`run_pilots`, :func:`summarise_pilots`) repeat the
browser app's "Pilot to scale" tab over many seeds and ask whether the profit
uplift seller A sees in its pilot predicts what it earns once seller B adopts
an algorithm too.
"""

import math
import multiprocessing
import os

from . import model

__all__ = [
    'run_one', 'run_batch', 'summarise_batch', 'paired_comparison', 'sign_flip_test', 'holm',
    'sweep', 'SWEEP_PARAMS', 'EXACT_MAX', 'FLIP_REPS',
    'run_pilot_stages', 'run_together', 'run_pilots', 'summarise_pilots', 'pearson', 'spearman', 'ranks',
    'PILOT_LABELS', 'PILOT_STAGES',
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
    ``replyGainA`` and ``replyGainB``: the ``bestReplyGain`` of
    :func:`quiet_cartel.model.best_response_check`, or ``None`` for a seller that
    follows a fixed rule. That is how much more the seller would earn over time,
    starting where play settled, by switching to its exact best reply to the
    others' learned strategies, as a share of what its own learned strategy
    earns. Zero means the learned strategy is already a best reply there.
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
        for i, key in enumerate(('replyGainA', 'replyGainB')):
            br = model.best_response_check(tr, i, s['cycle'])
            row[key] = None if br is None else br['bestReplyGain']
    return row


def _run_task(task):
    """Pool worker: unpack a (base, scenario, seed) task. Top level so that it can be pickled."""
    return run_one(*task)


def _run_tasks(tasks, jobs=None, progress=None, worker=_run_task):
    """Run tasks in input order, in-process when ``jobs`` is 1, otherwise in a process pool.

    ``worker`` must be a top-level function of this module, so that the pool can pickle it.
    """
    total = len(tasks)
    jobs = (os.cpu_count() or 1) if jobs is None else int(jobs)
    if jobs < 1:
        raise ValueError('jobs must be at least 1')
    if progress:
        progress(0, total, None)        # everything is checked: training starts now
    out = []
    if jobs == 1 or total <= 1:
        for task in tasks:
            out.append(worker(task))
            if progress:
                progress(len(out), total, out[-1])
        return out
    with multiprocessing.Pool(processes=min(jobs, total)) as pool:
        # chunksize 1: runs differ a lot in length (a third seller takes several times longer)
        for row in pool.imap(worker, tasks, chunksize=1):
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
    * ``meanPrice`` and ``replyGain``: mean settled price, and the mean over
      runs and learning sellers of the gain from a best reply (``None`` when no
      run had two sellers).
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
            g = [r[k] for k in ('replyGainA', 'replyGainB') if r.get(k) is not None]
            if g:
                gaps.append(max(g))
        out[sid] = {
            'id': sid, 'label': sc['label'], 'group': sc['group'], 'note': sc['note'],
            'agg': model.aggregate(rows),
            'meanPrice': _mean_of([r['meanPrice'] for r in rows]),
            'replyGain': _mean_of(gaps),
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


# ------------------------------------------------------------ pilot to scale

PILOT_STAGES = ('pilot', 'scaled', 'together')
PILOT_LABELS = {'nash': 'B keeps the competitive price', 'match': 'B matches the cheapest price',
                'undercut': 'B undercuts by one step'}
PILOT_BOOT_SEEDS = {'pilotUpliftA': 601, 'scaledUpliftA': 602, 'togetherUpliftA': 603,
                    'pilotUpliftB': 604, 'scaledUpliftB': 605, 'gapA': 606}


def run_pilot_stages(base, rule, adopt_after, seed):
    """Seller A's pilot and the scale-up after B adopts: the first two thirds of ``model.pilot_run``.

    Seller A learns while B follows ``rule``; at round ``adopt_after`` B starts
    learning too and training runs on until both settle. Returns the
    :func:`quiet_cartel.model.summarise` of the market at the end of the pilot
    (``pilot``) and at the end (``scaled``). The steps are exactly those of
    ``model.pilot_run``, which a test checks.
    """
    tr = model.Trainer(model.pilot_config(base, rule, adopt_after, seed))
    while tr.t < adopt_after and not tr.run(adopt_after - tr.t):
        pass
    pilot = model.summarise(tr)
    tr.run_to_end()
    return {'pilot': pilot, 'scaled': model.summarise(tr)}


def run_together(base, seed):
    """Both sellers learning from the start, as in ``model.pilot_run``. It does not depend on B's rule."""
    return model.summarise(model.train(model.together_config(base, seed)))


def _pilot_task(task):
    """Pool worker for pilots: ('pilot', base, rule, adopt_after, seed) or ('together', base, seed)."""
    if task[0] == 'pilot':
        return run_pilot_stages(*task[1:])
    return run_together(*task[1:])


def _checked_rules(rules):
    rules = list(rules)
    out = []
    for r in rules:
        if r not in model.PILOT_RULES:
            raise ValueError("unknown pilot rule '%s' (choose from %s)" % (r, ', '.join(model.PILOT_RULES)))
        if r not in out:
            out.append(r)
    if not out:
        raise ValueError('give at least one pilot rule')
    return out


def run_pilots(base, rules, seeds, adopt_after, jobs=None, progress=None):
    """Run the pilot-to-scale experiment for every rule and seed and return one flat row per run.

    For each (rule, seed): seller A pilots a learning algorithm while B keeps
    ``rule`` ('nash' keeps the competitive price, 'match' matches the cheapest
    price, 'undercut' undercuts by one step); B adopts an algorithm at round
    ``adopt_after``. The "together" comparison (both learning from the start)
    depends only on the seed, so it is trained once per seed and shared by the
    rules; the uplifts then come from ``model.pilot_summary`` exactly as in
    ``model.pilot_run``.

    Each row has ``rule``, ``seed``; ``<stage>UpliftA`` and ``<stage>UpliftB``
    for the stages ``pilot``, ``scaled`` and ``together`` (profit relative to
    the status quo in which both charge the competitive grid price, so 0.25
    means 25% more); ``<stage>Gain`` (profit gain on the settled cycle, 0
    competitive, 1 monopoly), ``<stage>Harm`` (shoppers' loss) and
    ``<stage>Punished``; ``periods`` and ``scaledSettled`` for the pilot run, and
    ``togetherPeriods`` and ``togetherSettled``. ``progress`` is called as in
    :func:`run_batch` (its total counts the shared together runs too).
    """
    base = _checked_base(base)
    rules = _checked_rules(rules)
    seeds = _checked_seeds(seeds)
    if isinstance(adopt_after, bool) or not isinstance(adopt_after, int) or adopt_after < 1:
        raise ValueError('adopt_after must be a whole number of rounds, at least 1')
    for rule in rules:
        errors = model.validate_config(model.pilot_config(base, rule, adopt_after, seeds[0]))['errors']
        if errors:
            raise ValueError('the pilot with rule %s is not valid: %s' % (rule, '; '.join(errors)))
    errors = model.validate_config(model.together_config(base, seeds[0]))['errors']
    if errors:
        raise ValueError('the both-learn comparison is not valid: ' + '; '.join(errors))
    tasks = [('pilot', base, rule, adopt_after, seed) for rule in rules for seed in seeds]
    tasks += [('together', base, seed) for seed in seeds]       # shorter runs last, for an even load
    results = _run_tasks(tasks, jobs, progress, worker=_pilot_task)
    together = dict(zip(seeds, results[len(rules) * len(seeds):]))
    # The market (and so the status quo) does not depend on the rule or the seed.
    mk = model.build_market(model.validate_config(model.pilot_config(base, rules[0], adopt_after, seeds[0]))['config'])
    rows = []
    for k, (rule, seed) in enumerate((r, s) for r in rules for s in seeds):
        stages = results[k]
        summary = model.pilot_summary(mk, stages['pilot'], stages['scaled'], together[seed])
        row = {'rule': rule, 'seed': seed}
        for stage in PILOT_STAGES:
            row[stage + 'UpliftA'] = summary['upliftA'][stage]
            row[stage + 'UpliftB'] = summary['upliftB'][stage]
        for stage in PILOT_STAGES:
            s = summary[stage]
            row[stage + 'Gain'], row[stage + 'Harm'], row[stage + 'Punished'] = s['avgGain'], s['harm'], s['punished']
        row.update({'periods': stages['scaled']['periods'], 'scaledSettled': stages['scaled']['converged'],
                    'togetherPeriods': together[seed]['periods'], 'togetherSettled': together[seed]['converged']})
        rows.append(row)
    return rows


def _pairs(xs, ys):
    if len(xs) != len(ys):
        raise ValueError('the two lists must have the same length')
    return [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None and x == x and y == y]


def pearson(xs, ys):
    """Pearson's correlation: how close the points lie to a straight rising (1) or falling (-1) line.

    r = sum((x - mean x)(y - mean y)) / sqrt(sum((x - mean x)**2) * sum((y - mean y)**2)),
    over the pairs where neither value is missing (None or NaN). NaN when fewer
    than two pairs remain or either list does not vary.
    """
    pairs = _pairs(xs, ys)
    n = len(pairs)
    if n < 2:
        return NAN
    mx = math.fsum(x for x, _ in pairs) / n
    my = math.fsum(y for _, y in pairs) / n
    sxx = math.fsum((x - mx) ** 2 for x, _ in pairs)
    syy = math.fsum((y - my) ** 2 for _, y in pairs)
    sxy = math.fsum((x - mx) * (y - my) for x, y in pairs)
    if not (sxx > 0 and syy > 0):
        return NAN
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def ranks(xs):
    """Ranks from 1 (smallest) to n; tied values share the average of the ranks they span."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs, ys):
    """Spearman's rank correlation: Pearson's correlation of the ranks (ties get average ranks).

    It asks whether a higher x goes with a higher y at all, whatever the shape,
    and one extreme run cannot dominate it. Missing pairs are dropped first.
    """
    pairs = _pairs(xs, ys)
    return pearson(ranks([x for x, _ in pairs]), ranks([y for _, y in pairs]))


def _correlation(rows):
    xs, ys = [r['pilotUpliftA'] for r in rows], [r['scaledUpliftA'] for r in rows]
    return {'runs': len(_pairs(xs, ys)), 'pearson': pearson(xs, ys), 'spearman': spearman(xs, ys)}


def summarise_pilots(rows):
    """Summarise pilot runs rule by rule, and ask whether the pilot predicts the result at scale.

    For each rule, in the order the rows appear: the mean and 90% bootstrap
    interval (:func:`quiet_cartel.model.bootstrap_mean`, 2,000 resamples, fixed
    seeds) of A's uplift in the pilot, after B adopts (``scaled``) and with both
    learning from the start (``together``); of B's uplift in the pilot and after
    adopting; of the run-by-run gap ``scaled - pilot`` for A (a paired interval,
    since each gap comes from one run); the share of runs in which a one-day cut
    is punished in each stage; the mean profit gain and shoppers' loss in each
    stage; and the correlation within the rule.

    ``correlation`` pools every run: Pearson's and Spearman's correlation
    between A's pilot uplift and A's uplift after B adopts. Pooling mixes the
    rules, so a high pooled value can simply mean that the rule which helps the
    pilot also helps at scale; the per-rule values say whether, within one
    rule, a better pilot run goes with a better result at scale.

    Returns ``{'order': [rules], 'rules': {rule: summary}, 'correlation': {...}, 'seeds': [...]}``.
    """
    order, by_rule, seeds = [], {}, []
    for r in rows:
        if r['rule'] not in by_rule:
            order.append(r['rule'])
            by_rule[r['rule']] = []
        by_rule[r['rule']].append(r)
        if r['seed'] not in seeds:
            seeds.append(r['seed'])
    if not order:
        raise ValueError('no pilot runs to summarise')
    out = {}
    for rule in order:
        rs = by_rule[rule]

        def boot(key, values=None):
            vals = [r[key] for r in rs] if values is None else values
            return model.bootstrap_mean(vals, 0.9, BOOT_REPS, PILOT_BOOT_SEEDS[key])

        out[rule] = {
            'rule': rule, 'label': PILOT_LABELS.get(rule, rule), 'runs': len(rs),
            'upliftA': {stage: boot(stage + 'UpliftA') for stage in PILOT_STAGES},
            'upliftB': {stage: boot(stage + 'UpliftB') for stage in ('pilot', 'scaled')},
            'gapA': boot('gapA', [r['scaledUpliftA'] - r['pilotUpliftA'] for r in rs]),
            'punishedShare': {stage: sum(1 for r in rs if r[stage + 'Punished']) / len(rs) for stage in PILOT_STAGES},
            'gain': {stage: model.mean([r[stage + 'Gain'] for r in rs]) for stage in PILOT_STAGES},
            'harm': {stage: model.mean([r[stage + 'Harm'] for r in rs]) for stage in PILOT_STAGES},
            'correlation': _correlation(rs),
        }
    return {'order': order, 'rules': out, 'correlation': _correlation(rows), 'seeds': seeds}
