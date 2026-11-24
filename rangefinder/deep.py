"""Heavier checks that are too slow for a browser tab.

* Sobol indices by the pick-and-freeze method: first-order (Saltelli 2010) and
  total-effect (Jansen 1999) indices from (k + 2) x N model runs. The app's
  first-order shares are worked out exactly from the linear structure, so this
  is an independent check on them, and the total-effect indices add what the
  app cannot show: how much each driver matters once its interactions count.
* Seed stability: the headline numbers re-run under many seeds, to show how
  much of any difference is sampling noise.
"""

import math

from .model import drivers_of, mean, percentile, simulate, variance


def _columns(model, n, seed):
    return simulate(model, n, seed)[1]


def _evaluate_rows(model, cols, k):
    total = 0.0
    c = 0
    for term in model["terms"]:
        prod = float(term["sign"])
        for _ in term["drivers"]:
            prod *= cols[c][k]
            c += 1
        total += prod
    return total


def sobol(model, n=20000, seed=11):
    """First-order and total-effect Sobol indices for every driver."""
    a = _columns(model, n, seed)
    b = _columns(model, n, seed + 1000003)
    fa = [_evaluate_rows(model, a, k) for k in range(n)]
    fb = [_evaluate_rows(model, b, k) for k in range(n)]
    total_var = variance(fa + fb)
    out = []
    for i, (_, _, d) in enumerate(drivers_of(model)):
        if d["dist"] == "fixed" or total_var == 0:
            out.append({"name": d["name"], "first": 0.0, "total": 0.0})
            continue
        ab = list(a)
        ab[i] = b[i]
        fab = [_evaluate_rows(model, ab, k) for k in range(n)]
        first = mean([fb[k] * (fab[k] - fa[k]) for k in range(n)]) / total_var
        tot = mean([(fa[k] - fab[k]) ** 2 for k in range(n)]) / (2 * total_var)
        out.append({"name": d["name"], "first": first, "total": tot})
    return out


def stability(model, seeds=20, n=None):
    """Mean and spread of the headline numbers across seeds."""
    keys = ("p10", "p50", "p90", "mean", "probAbove")
    runs = {k: [] for k in keys}
    threshold = model.get("threshold")
    for s in range(1, seeds + 1):
        values, _ = simulate(model, n, s)
        srt = sorted(values)
        runs["p10"].append(percentile(srt, 0.1))
        runs["p50"].append(percentile(srt, 0.5))
        runs["p90"].append(percentile(srt, 0.9))
        runs["mean"].append(mean(values))
        if threshold is not None:
            runs["probAbove"].append(sum(1 for v in values if v >= threshold) / len(values))
    out = {}
    for k in keys:
        xs = runs[k]
        if xs:
            out[k] = {"mean": mean(xs), "sd": math.sqrt(variance(xs)), "min": min(xs), "max": max(xs)}
    return out
