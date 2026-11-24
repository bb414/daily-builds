"""How many people would a study need? Power by simulation.

Simulates many pairs of groups of synthetic people (one group per arm), compares
them on one measure with Welch's t-test, and reports how often the difference is
detected. The answer is only as good as the assumed effects in synth.py, which
can be changed with the shifts argument.
"""

import math
import random

from .cohort import person_row
from .design import ADVICE_STYLES
from .synth import simulate_cohort


def parse_arm(text):
    """'reason', 'verdict+feedback' and so on, as a condition dict."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts or parts[0] not in ADVICE_STYLES or any(p != "feedback" for p in parts[1:]):
        raise ValueError("An arm is an advice style (%s), optionally followed by +feedback, not %r."
                         % (", ".join(ADVICE_STYLES), text))
    return {"advice": parts[0], "feedback": "feedback" in parts[1:]}


def welch_test(a, b):
    """Two-sided Welch test using the normal approximation. Returns (difference, p)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return (None, None)
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return (mb - ma, 1.0 if ma == mb else 0.0)
    z = (mb - ma) / se
    return (mb - ma, math.erfc(abs(z) / math.sqrt(2)))


def power_curve(arm_a, arm_b, measure, sizes, reps=100, alpha=0.05, seed=1, shifts=None, crutch=0.0):
    """For each group size, the share of simulated studies that detect a difference."""
    master = random.Random(seed)
    curve = []
    for n in sizes:
        hits = 0
        diffs = []
        for _ in range(reps):
            a = [person_row(s)[measure] for s in simulate_cohort(n, master.randrange(2 ** 31), arm_a, crutch, shifts)]
            b = [person_row(s)[measure] for s in simulate_cohort(n, master.randrange(2 ** 31), arm_b, crutch, shifts)]
            diff, p = welch_test([x for x in a if x is not None], [x for x in b if x is not None])
            if diff is None:
                continue
            diffs.append(diff)
            if p < alpha:
                hits += 1
        curve.append({"n": n, "power": hits / reps, "difference": sum(diffs) / len(diffs) if diffs else None})
    return curve


def smallest_adequate(curve, target=0.8):
    for row in curve:
        if row["power"] >= target:
            return row["n"]
    return None
