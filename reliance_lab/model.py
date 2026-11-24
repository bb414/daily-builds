"""The reliance model: when does a person reviewing AI advice beat both of them alone?

This is a line-for-line port of the MODEL block in ``app/index.html``. The tests in
``tests/test_agreement.py`` run both versions on the same inputs and check that they agree.

The set-up is a yes/no decision (for example, "is this payment fraud?"). The person and the AI
each give an answer. Where they agree there is nothing to decide. Where they disagree, a
*reliance rule* decides whether the person switches to the AI's answer. Every rule is judged
on the same disagreements, so the model can say exactly how many errors come from following a
wrong AI (over-reliance), from ignoring a right AI (under-reliance), and from cases that both
get wrong (shared blind spots, which no rule can fix).

Confidence follows signal detection theory. On each case the AI has a hidden signal
``s ~ Normal(+d/2, 1)`` when it is right and ``Normal(-d/2, 1)`` when it is wrong, where ``d`` is
how informative its confidence is. Its displayed confidence is ``sigmoid(logit(accuracy) + bias
+ d * s)``, which is perfectly calibrated when ``bias`` is zero. The person's own confidence
works the same way.
"""

from __future__ import annotations

import math

POLICIES = ("fixed", "threshold", "surer", "optimal")

POLICY_LABELS = {
    "fixed": "Defer at a fixed rate",
    "threshold": "Follow the AI when it sounds sure",
    "surer": "Go with whoever is surer",
    "optimal": "Best possible rule",
}

DEFAULTS = {
    "human": 0.75,
    "ai": 0.85,
    "overlap": 0.2,
    "aiSignal": 1.5,
    "humanSignal": 1.0,
    "aiBias": 0.0,
    "humanBias": 0.0,
    "threshold": 0.8,
    "deferRate": 0.7,
}

RANGES = {
    "human": (0.5, 0.99),
    "ai": (0.5, 0.99),
    "overlap": (-1.0, 1.0),
    "aiSignal": (0.0, 4.0),
    "humanSignal": (0.0, 4.0),
    "aiBias": (-2.0, 2.0),
    "humanBias": (-2.0, 2.0),
    "threshold": (0.5, 0.99),
    "deferRate": (0.0, 1.0),
}


def norm_cdf(x: float) -> float:
    """Standard normal CDF (Hart 1968, as given by West 2005), matching the browser app."""
    if x != x:
        return float("nan")
    if x == math.inf:
        return 1.0
    if x == -math.inf:
        return 0.0
    z = abs(x)
    if z > 37:
        c = 0.0
    else:
        e = math.exp(-z * z / 2)
        if z < 7.07106781186547:
            n = 3.52624965998911e-2 * z + 0.700383064443688
            n = n * z + 6.37396220353165
            n = n * z + 33.912866078383
            n = n * z + 112.079291497871
            n = n * z + 221.213596169931
            n = n * z + 220.206867912376
            d = 8.83883476483184e-2 * z + 1.75566716318264
            d = d * z + 16.064177579207
            d = d * z + 86.7807322029461
            d = d * z + 296.564248779674
            d = d * z + 637.333633378831
            d = d * z + 793.826512519948
            d = d * z + 440.413735824752
            c = e * n / d
        else:
            b = z + 0.65
            b = z + 4 / b
            b = z + 3 / b
            b = z + 2 / b
            b = z + 1 / b
            c = e / b / 2.506628274631
    return 1 - c if x > 0 else c


_A = (-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
      1.38357751867269e2, -3.066479806614716e1, 2.506628277459239)
_B = (-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
      6.680131188771972e1, -1.328068155288572e1)
_C = (-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
      -2.549732539343734, 4.374664141464968, 2.938163982698783)
_D = (7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
      3.754408661907416)


def norm_inv(p: float) -> float:
    """Inverse standard normal CDF (Acklam's approximation plus one Halley step)."""
    if not (0 < p < 1):
        if p == 0:
            return -math.inf
        if p == 1:
            return math.inf
        return float("nan")
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        x = ((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
             / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    elif p <= 1 - p_low:
        q = p - 0.5
        r = q * q
        x = ((((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q
             / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1))
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
              / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    err = norm_cdf(x) - p
    u = err * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def normalise(params: dict | None = None) -> dict:
    """Merge with the defaults, reject non-numbers and clamp each value to its range."""
    src = params or {}
    out = {}
    for key, default in DEFAULTS.items():
        v = src.get(key)
        if v is None:
            v = default
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{key} must be a finite number")
        lo, hi = RANGES[key]
        out[key] = clamp(float(v), lo, hi)
    return out


def joint_cells(h: float, a: float, rho: float) -> dict:
    """Joint probabilities of who is right.

    ``p10`` is person right and AI wrong, ``p01`` person wrong and AI right. ``rho`` is the
    correlation between the person being right and the AI being right; it is clamped to what
    the two accuracies allow.
    """
    sd = math.sqrt(h * (1 - h) * a * (1 - a))
    raw = h * a + rho * sd
    p11 = clamp(raw, max(0.0, h + a - 1), min(h, a))
    return {
        "p11": p11,
        "p10": max(0.0, h - p11),
        "p01": max(0.0, a - p11),
        "p00": max(0.0, 1 - h - a + p11),
        "rho": (p11 - h * a) / sd if sd > 0 else 0.0,
        "clamped": abs(p11 - raw) > 1e-12,
    }


def _pass_rates(k: float, q: float) -> tuple[float, float]:
    """Follow rates when the person follows the AI if ``aiSignal*s - humanSignal*t > k``."""
    if q > 0:
        return norm_cdf((q * q / 2 - k) / q), norm_cdf((-q * q / 2 - k) / q)
    f = 1.0 if 0 > k else 0.0
    return f, f


def follow_rates(p: dict, policy: str, cells: dict) -> tuple[float, float]:
    """Return (f1, f0): the chance of following the AI when it is right / when it is wrong,
    counting only cases where the person and the AI disagree."""
    la = logit(p["ai"])
    lh = logit(p["human"])
    da = p["aiSignal"]
    dh = p["humanSignal"]
    q = math.sqrt(da * da + dh * dh)
    if policy == "fixed":
        return p["deferRate"], p["deferRate"]
    if policy == "threshold":
        lt = logit(p["threshold"])
        if da > 0:
            s_star = (lt - la - p["aiBias"]) / da
            return norm_cdf(da / 2 - s_star), norm_cdf(-da / 2 - s_star)
        always = 1.0 if la + p["aiBias"] >= lt else 0.0
        return always, always
    if policy == "surer":
        return _pass_rates(lh + p["humanBias"] - la - p["aiBias"], q)
    if policy == "optimal":
        if cells["p01"] <= 0 and cells["p10"] <= 0:
            return 0.0, 0.0
        if cells["p10"] <= 0:
            log_odds = math.inf
        elif cells["p01"] <= 0:
            log_odds = -math.inf
        else:
            log_odds = math.log(cells["p01"] / cells["p10"])
        return _pass_rates(-log_odds, q)
    raise ValueError(f"Unknown policy: {policy}")


def evaluate(params: dict | None, policy: str) -> dict:
    """Team accuracy and its error breakdown for one reliance rule."""
    p = normalise(params)
    cells = joint_cells(p["human"], p["ai"], p["overlap"])
    f1, f0 = follow_rates(p, policy, cells)
    over = cells["p10"] * f0
    under = cells["p01"] * (1 - f1)
    team = cells["p11"] + cells["p01"] * f1 + cells["p10"] * (1 - f0)
    dis = cells["p01"] + cells["p10"]
    best = max(p["human"], p["ai"])
    return {
        "policy": policy,
        "label": POLICY_LABELS[policy],
        "team": team,
        "shared": cells["p00"],
        "overErrors": over,
        "underErrors": under,
        "gain": team - best,
        "gainOverHuman": team - p["human"],
        "gainOverAI": team - p["ai"],
        "overRelianceRate": f0,
        "underRelianceRate": 1 - f1,
        "rair": f1,
        "rsr": 1 - f0,
        "followRate": (cells["p01"] * f1 + cells["p10"] * f0) / dis if dis > 0 else 0.0,
        "disagreeRate": dis,
    }


def analyse(params: dict | None = None) -> dict:
    """Evaluate every rule for one set of assumptions."""
    p = normalise(params)
    cells = joint_cells(p["human"], p["ai"], p["overlap"])
    policies = {key: evaluate(p, key) for key in POLICIES}
    return {
        "params": p,
        "cells": cells,
        "best": max(p["human"], p["ai"]),
        "ceiling": policies["optimal"]["team"],
        "sharedMistakeShare": cells["p00"] / (1 - p["ai"]) if (1 - p["ai"]) > 0 else 0.0,
        "policies": policies,
    }


def threshold_curve(params: dict | None = None, steps: int = 50) -> list[dict]:
    """Team accuracy as the confidence bar for following the AI rises from 50% to 99%."""
    p = normalise(params)
    lo, hi = RANGES["threshold"]
    out = []
    for i in range(steps + 1):
        t = lo + (hi - lo) * i / steps
        r = evaluate({**p, "threshold": t}, "threshold")
        out.append({"threshold": t, "team": r["team"], "over": r["overRelianceRate"],
                    "under": r["underRelianceRate"]})
    return out


def gain_grid(params: dict | None = None, policy: str = "optimal", steps: int = 50) -> dict:
    """Gain over the better solo for every pair of accuracies, holding everything else fixed.

    ``gains[i][j]`` is for person accuracy ``values[i]`` and AI accuracy ``values[j]``.
    """
    n = max(2, steps)
    p = normalise(params)
    lo, hi = RANGES["human"]
    values = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    gains = [[evaluate({**p, "human": h, "ai": a}, policy)["gain"] for a in values] for h in values]
    return {"values": values, "gains": gains}


SENSITIVITY_STEPS = {
    "human": 0.05, "ai": 0.05, "overlap": 0.2, "aiSignal": 0.5, "humanSignal": 0.5,
    "aiBias": 0.5, "humanBias": 0.5,
}

SENSITIVITY_LABELS = {
    "human": "Person’s accuracy ±5 pts",
    "ai": "AI’s accuracy ±5 pts",
    "overlap": "Error overlap ±0.2",
    "aiSignal": "AI confidence signal ±0.5",
    "humanSignal": "Person’s confidence signal ±0.5",
    "aiBias": "AI overconfidence ±0.5",
    "humanBias": "Person’s overconfidence ±0.5",
}


def sensitivity(params: dict | None = None, policy: str = "optimal") -> list[dict]:
    """How far team accuracy moves if each assumption is nudged down or up by a fixed step,
    biggest swing first. Values are clamped to their ranges, so a setting at its limit can
    only move one way."""
    p = normalise(params)
    base = evaluate(p, policy)["team"]
    rows = []
    for order, (key, step) in enumerate(SENSITIVITY_STEPS.items()):
        low = evaluate({**p, key: p[key] - step}, policy)["team"] - base
        high = evaluate({**p, key: p[key] + step}, policy)["team"] - base
        rows.append({"key": key, "label": SENSITIVITY_LABELS[key], "step": step, "low": low,
                     "high": high, "swing": abs(high - low), "order": order})
    rows.sort(key=lambda r: (-r["swing"], r["order"]))
    return rows
