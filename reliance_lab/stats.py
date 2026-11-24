"""Small statistics helpers (standard library only): Welch's t-test and Cohen's d."""

import math


def mean(xs):
    return sum(xs) / len(xs)


def variance(xs):
    """Sample variance (n - 1 in the denominator)."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def _beta_continued_fraction(a, b, x):
    """Continued fraction for the regularised incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h


def betainc(a, b, x):
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(log_front) * _beta_continued_fraction(a, b, x) / a
    return 1 - math.exp(log_front) * _beta_continued_fraction(b, a, 1 - x) / b


def t_two_sided_p(t, df):
    """Two-sided p-value for a t statistic with ``df`` degrees of freedom."""
    if not math.isfinite(t):
        return 0.0
    return betainc(df / 2, 0.5, df / (df + t * t))


def t_critical(df, alpha=0.05):
    """Critical value c with P(|T| > c) = alpha, found by bisection."""
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_two_sided_p(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def welch(a, b, alpha=0.05, interval=True):
    """Welch's t-test for mean(a) - mean(b), with Cohen's d and (optionally) a confidence interval."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        raise ValueError("Each group needs at least two observations")
    ma, mb = mean(a), mean(b)
    va, vb = variance(a), variance(b)
    diff = ma - mb
    se2 = va / na + vb / nb
    pooled_sd = math.sqrt((va + vb) / 2)
    d = diff / pooled_sd if pooled_sd > 0 else 0.0
    if se2 == 0:
        p = 1.0 if diff == 0 else 0.0
        return {"diff": diff, "se": 0.0, "t": 0.0 if diff == 0 else math.copysign(math.inf, diff),
                "df": na + nb - 2, "p": p, "low": diff, "high": diff, "d": d}
    se = math.sqrt(se2)
    t = diff / se
    df = se2 ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    crit = t_critical(df, alpha) if interval else math.nan
    return {"diff": diff, "se": se, "t": t, "df": df, "p": t_two_sided_p(t, df),
            "low": diff - crit * se, "high": diff + crit * se, "d": d}
