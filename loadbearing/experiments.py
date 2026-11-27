"""Batch experiments the browser app does not offer: a cluster-randomised trial across clubs, and sweeps of one
setting. Both lean on common random numbers: the same club and season seed replay the same luck, so a season
played with and without the warning light differs only by what the light changed.
"""
import itertools
import math
import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from . import model

OUTCOMES = ['injuriesTotal', 'nc', 'contact', 'daysLost', 'points']
SWEEP_PARAMS = {'threshold': (1, 3), 'budget': (1, 50), 'spike': (0, 4), 'contactScale': (0, 3),
                'intensity': (0.7, 1.3), 'restTraining': (0, 1), 'rotateAfter': (2, 10)}
SWEEP_METRICS = [('injuriesTotal', 'injuries'), ('nc', 'soft_tissue'), ('daysLost', 'days_lost'),
                 ('points', 'points')]
RATIO_FLAGS = ('coupled', 'uncoupled', 'ewma')
ALPHA = 0.05


def default_workers():
    """The processor cores this process may use."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def parallel_map(fn, jobs, workers=None):
    """[fn(*job) for job in jobs], spread over worker processes; serial when workers is 1 or processes fail."""
    jobs = list(jobs)
    workers = min(default_workers() if workers is None else workers, len(jobs))
    if workers > 1:
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(fn, *job) for job in jobs]
                return [f.result() for f in futures]
        except (OSError, NotImplementedError, ImportError, BrokenProcessPool, pickle.PicklingError):
            pass
    return [fn(*job) for job in jobs]


def light_policy(settings):
    """Settings with a policy that acts on the light: 'none' becomes 'rest', as on the app's pilot page."""
    s = model.with_defaults(settings)
    if s['policy'] == 'none':
        s['policy'] = 'rest'
    return s


def _outcomes(res):
    return {k: res[k] for k in OUTCOMES}


def play_pair(settings, seeds):
    """Each season seed played without the light and with it (same luck): [{'seed', 'none', 'light'}]."""
    s = model.with_defaults(settings)
    ctx = model.prepare(s)
    off = dict(s, policy='none')
    return [{'seed': seed, 'none': _outcomes(model.simulate_season(ctx, off, seed)),
             'light': _outcomes(model.simulate_season(ctx, s, seed))} for seed in seeds]


# ---------- a cluster-randomised trial ----------
def simulate_pool(settings, clubs, seasons, workers=None):
    """A pool of clubs (squad seeds counting up from settings' squadSeed), each season played both ways."""
    s = light_policy(settings)
    squad_seeds = [s['squadSeed'] + k for k in range(clubs)]
    season_seeds = list(range(1, seasons + 1))
    jobs = [(dict(s, squadSeed=q), season_seeds) for q in squad_seeds]
    return {'settings': s, 'squadSeeds': squad_seeds, 'seasonSeeds': season_seeds,
            'clubs': parallel_map(play_pair, jobs, workers)}


def _pick(rng, items, k):
    """k distinct items in random order (a partial Fisher-Yates shuffle)."""
    a = list(items)
    for i in range(k):
        j = i + rng.int_(len(a) - i)
        a[i], a[j] = a[j], a[i]
    return a[:k]


def check_trial(club_counts, seasons_per_club, pool_clubs, pool_seasons):
    """Raises ValueError unless every trial size is even, at least 4 and fits in the pool."""
    for c in club_counts:
        if c < 4 or c % 2:
            raise ValueError(f'a trial needs an even number of clubs, at least 4 (not {c})')
    if max(club_counts) > pool_clubs:
        raise ValueError(f'a trial of {max(club_counts)} clubs needs a pool of at least that many clubs '
                         f'(the pool has {pool_clubs})')
    if not 1 <= seasons_per_club <= pool_seasons:
        raise ValueError(f'{seasons_per_club} seasons per club needs between 1 and {pool_seasons} '
                         'pool seasons')


def permutation_p(values, n_light, rng, permutations, combos=None):
    """Two-sided permutation p-value of mean(light) - mean(rest), the first n_light values being the light arm.

    combos lists every possible light arm for exact enumeration; otherwise random reassignments are drawn."""
    n = len(values)
    total = sum(values)
    n_off = n - n_light

    def stat(light_sum):
        return abs(light_sum / n_light - (total - light_sum) / n_off)

    observed = stat(sum(values[:n_light])) - 1e-9
    if combos is not None:
        hits = sum(1 for c in combos if stat(sum(values[i] for i in c)) >= observed)
        return hits / len(combos)
    a = list(values)
    hits = 0
    for _ in range(permutations):
        for i in range(n_light):
            j = i + rng.int_(n - i)
            a[i], a[j] = a[j], a[i]
        if stat(sum(a[:n_light])) >= observed:
            hits += 1
    return (hits + 1) / (permutations + 1)


def trial_power(pool, club_counts, seasons_per_club, reps, seed, permutations=499, outcome='injuriesTotal'):
    """Power of a cluster-randomised trial for each number of clubs, by resampling the simulated pool.

    Each replicate draws distinct clubs and distinct seasons for each from the pool, gives half of the clubs
    the light at random, averages each club's injuries over its seasons and tests the difference between the
    arms by permutation at the 5% level (exactly, over every possible split, when there are few enough). Clubs
    are never drawn twice: a club-season and its common-random-numbers twin in the other arm would make the
    arms look more alike than two real clubs ever are, so the pool must hold at least as many clubs as the
    largest trial and at least as many seasons as each club plays.
    """
    clubs = pool['clubs']
    n_pool, n_seasons = len(clubs), len(clubs[0])
    check_trial(club_counts, seasons_per_club, n_pool, n_seasons)
    diffs = [s['light'][outcome] - s['none'][outcome] for club in clubs for s in club]
    out = []
    for c in club_counts:
        rng = model.Rng(model.hash_seed(seed, c, 71))
        n_light = c // 2
        assignments = math.comb(c, n_light)
        exact = assignments <= permutations + 1
        combos = list(itertools.combinations(range(c), n_light)) if exact else None
        effects, rejected = [], 0
        for _ in range(reps):
            chosen = _pick(rng, range(n_pool), c)  # in random order: the first half get the light
            values = []
            for k, club in enumerate(chosen):
                key = 'light' if k < n_light else 'none'
                picks = _pick(rng, range(n_seasons), seasons_per_club)
                values.append(model.mean([clubs[club][j][key][outcome] for j in picks]))
            effects.append(model.mean(values[:n_light]) - model.mean(values[n_light:]))
            if permutation_p(values, n_light, rng, permutations, combos) <= ALPHA:
                rejected += 1
        out.append({'clubs': c, 'power': rejected / reps, 'meanEffect': model.mean(effects),
                    'sdEffect': model.sd(effects), 'exact': exact, 'assignments': assignments,
                    'smallestP': 2 / assignments if exact else 1 / (permutations + 1)})
    none_values = [s['none'][outcome] for club in clubs for s in club]
    club_means = [model.mean([s['none'][outcome] for s in club]) for club in clubs]
    return {'outcome': outcome, 'seasonsPerClub': seasons_per_club, 'reps': reps, 'permutations': permutations,
            'seed': seed, 'poolClubs': n_pool, 'poolSeasons': n_seasons,
            'trueEffect': model.mean(diffs), 'trueEffectCI': model.boot_mean(diffs, 41),
            'meanWithout': model.mean(none_values), 'sdWithout': model.sd(none_values),
            'sdBetweenClubs': model.sd(club_means), 'results': out}


def run_trial(settings, club_counts, seasons_per_club=1, pool_clubs=32, pool_seasons=3, reps=400, seed=1,
              permutations=499, workers=None):
    """Simulates the pool and estimates the trial's power for each number of clubs."""
    check_trial(club_counts, seasons_per_club, pool_clubs, pool_seasons)
    pool = simulate_pool(settings, pool_clubs, pool_seasons, workers)
    out = trial_power(pool, club_counts, seasons_per_club, reps, seed, permutations)
    out['policy'] = pool['settings']['policy']
    out['flag'] = pool['settings']['flag']
    out['squadSeeds'] = pool['squadSeeds']
    out['seasonSeeds'] = pool['seasonSeeds']
    return out


# ---------- sweeps of one setting ----------
def sweep_inert(param, settings):
    """Why the setting cannot change the comparison under these settings, or None when it can."""
    s = light_policy(settings)
    acts = s['policy'] in ('rest', 'modify')
    if param == 'threshold' and not (acts and s['flag'] in RATIO_FLAGS):
        return 'the threshold only matters for a ratio flag (coupled, uncoupled or ewma) under rest or modify'
    if param == 'budget' and not (acts and s['flag'] not in RATIO_FLAGS):
        return 'the budget only matters for the model or oracle flag under rest or modify'
    if param == 'restTraining' and s['policy'] != 'rest':
        return 'restTraining only matters under the rest policy'
    if param == 'rotateAfter' and s['policy'] != 'rotate':
        return 'rotateAfter only matters under the rotate policy'
    return None


def sweep_value(settings, param, value, seeds):
    """The light against no light on the same seeds, with one setting changed: mean differences and 95%
    bootstrap intervals for injuries, soft-tissue injuries, days lost and league points."""
    s = light_policy(dict(settings, **{param: value}))
    pairs = play_pair(s, seeds)
    metrics = {}
    for k, (m, _) in enumerate(SWEEP_METRICS):
        diffs = [p['light'][m] - p['none'][m] for p in pairs]
        lo, hi = model.boot_mean(diffs, 11 + k)
        metrics[m] = {'none': model.mean([p['none'][m] for p in pairs]),
                      'light': model.mean([p['light'][m] for p in pairs]),
                      'diff': model.mean(diffs), 'lo': lo, 'hi': hi}
    return {'value': s[param], 'requested': value, 'seasons': len(pairs), 'metrics': metrics}


def run_sweep(settings, param, values, seeds, workers=None):
    """sweep_value() for each value (in parallel); the light's policy and flag come from settings."""
    s = light_policy(settings)
    rows = parallel_map(sweep_value, [(s, param, v, seeds) for v in values], workers)
    return {'param': param, 'policy': s['policy'], 'flag': s['flag'], 'seeds': list(seeds), 'rows': rows}


# ---------- the analyses behind the report ----------
def flag_seeds(n):
    """The silent seasons the app scores its lights on: seeds 1 to n."""
    return list(range(1, n + 1))


def compare_seeds(n):
    """The seasons the app plays its policies on: seeds 101 to 100 + n."""
    return list(range(101, 101 + n))


def run_analysis(name, settings, size):
    """One of the app's analyses by name: 'flags' or 'compare' over size seasons, 'pilot' over size pairs."""
    if name == 'flags':
        return model.evaluate_flags(settings, flag_seeds(size))
    if name == 'compare':
        return model.compare_policies(settings, compare_seeds(size))
    return model.pilot_study(settings, size)


def report_analyses(settings, seasons, pairs, workers=None):
    """The flags, compare and pilot analyses, run side by side in separate processes when cores allow."""
    jobs = [('compare', settings, seasons), ('pilot', settings, pairs), ('flags', settings, seasons)]
    compare, pilot, flags = parallel_map(run_analysis, jobs, workers)
    return {'flags': flags, 'compare': compare, 'pilot': pilot}
