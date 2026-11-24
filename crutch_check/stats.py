"""Small, dependency-free statistics helpers used by the study analysis."""

import math
import random


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def sd(xs):
    """Sample standard deviation (n - 1)."""
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def hedges_g(a, b):
    """Standardised mean difference (a minus b) with the small-sample correction."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    pooled = math.sqrt(((na - 1) * sd(a) ** 2 + (nb - 1) * sd(b) ** 2) / (na + nb - 2))
    if pooled == 0:
        return None
    d = (mean(a) - mean(b)) / pooled
    return d * (1 - 3 / (4 * (na + nb) - 9))


def permutation_test(a, b, n_perm=5000, seed=1):
    """Two-sided p-value for a difference in means, by shuffling group labels."""
    if not a or not b:
        return None
    rng = random.Random(seed)
    observed = abs(mean(a) - mean(b))
    pooled = list(a) + list(b)
    na = len(a)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        if abs(mean(pooled[:na]) - mean(pooled[na:])) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def bootstrap_ci(a, b, n_boot=2000, seed=2, level=0.95):
    """Percentile bootstrap interval for mean(a) - mean(b)."""
    if not a or not b:
        return None
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        ra = [a[rng.randrange(len(a))] for _ in a]
        rb = [b[rng.randrange(len(b))] for _ in b]
        diffs.append(mean(ra) - mean(rb))
    diffs.sort()
    lo = diffs[int(math.floor((1 - level) / 2 * n_boot))]
    hi = diffs[min(n_boot - 1, int(math.ceil((1 + level) / 2 * n_boot)) - 1)]
    return lo, hi


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx = mean([p[0] for p in pairs])
    my = mean([p[1] for p in pairs])
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


# Student's t distribution via the regularised incomplete beta function
# (continued fraction from Numerical Recipes), for Welch's t-test.

def _tiny(v):
    return v if abs(v) > 1e-300 else 1e-300


def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c = 1.0
    d = 1 / _tiny(1 - qab * x / qap)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 / _tiny(1 + aa * d)
        c = _tiny(1 + aa / c)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 / _tiny(1 + aa * d)
        c = _tiny(1 + aa / c)
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h


def betainc(a, b, x):
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(ln)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_two_sided_p(t, df):
    return betainc(df / 2, 0.5, df / (df + t * t))


def welch_t(a, b):
    """Welch's t-test: returns (t, df, two-sided p) or None."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    va, vb = sd(a) ** 2 / na, sd(b) ** 2 / nb
    if va + vb == 0:
        return None
    t = (mean(a) - mean(b)) / math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1))
    return t, df, t_two_sided_p(t, df)
