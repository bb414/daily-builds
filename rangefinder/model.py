"""The Range finder engine: driver trees, 90% ranges, Latin hypercube sampling and analysis.

An estimate is a sum of terms, and each term is a sign (+1 or -1) times the
product of its drivers. Every driver is described by a 90% range: the person
is 90% sure the true value lies between low and high. Because each driver
appears exactly once, the estimate is linear in every driver, which makes the
variance shares and the value of information exact and cheap to work out.

This module mirrors the model block in app/index.html line for line, and
tests/test_app.py checks that the two agree.
"""

import json
import math
from pathlib import Path

FORMAT = "range-finder-model"
VERSION = 1
DISTS = ("lognormal", "normal", "share", "uniform", "fixed")
DIST_LABELS = {
    "lognormal": "Positive, skewed (lognormal)",
    "normal": "Symmetric (normal)",
    "share": "Percentage (0 to 100)",
    "uniform": "Anywhere in the range (uniform)",
    "fixed": "Known exactly",
}
Z95 = 1.6448536269514722   # a 90% range runs from the 5th to the 95th percentile
Z90 = 1.2815515655446004   # the 10th and 90th percentiles, used for the tornado
MAX_TERMS = 8
MAX_DRIVERS_PER_TERM = 12
MAX_DRIVERS = 30
MIN_SAMPLES = 1000
MAX_SAMPLES = 200000
DEFAULT_SAMPLES = 10000
DEFAULT_SEED = 1

_TEMPLATES_PATH = Path(__file__).with_name("templates.json")
with _TEMPLATES_PATH.open(encoding="utf-8") as _f:
    TEMPLATES = json.load(_f)


# ---------------------------------------------------------------------------
# Deterministic random numbers and the inverse normal (identical to the app)
# ---------------------------------------------------------------------------

_M32 = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & _M32


def mulberry32(seed):
    state = [seed & _M32]

    def rnd():
        state[0] = (state[0] + 0x6D2B79F5) & _M32
        t = state[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t = ((t + _imul(t ^ (t >> 7), t | 61)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return rnd


def shuffle(items, rnd):
    for i in range(len(items) - 1, 0, -1):
        j = math.floor(rnd() * (i + 1))
        items[i], items[j] = items[j], items[i]
    return items


# Acklam's rational approximation to the inverse normal CDF (relative error < 1.2e-9).
_A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
_B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]


def inv_norm(p):
    if not 0 < p < 1:
        raise ValueError("p must be between 0 and 1")
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return ((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
                / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    if p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(1 - p))
        return -((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
                 / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    q = p - 0.5
    r = q * q
    return ((((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _is_int(x):
    return _is_num(x) and float(x).is_integer()


def validate_model(model):
    """Return a list of problems (empty if the model can be run). Same rules and wording as the app."""
    if not isinstance(model, dict):
        return ["This is not a Range finder model."]
    problems = []
    if model.get("format") != FORMAT:
        problems.append("This is not a Range finder model (the format field is missing or wrong).")
        return problems
    for key in ("title", "outputName", "unit"):
        if not isinstance(model.get(key), str):
            problems.append("The model's %s must be text." % key)
    if isinstance(model.get("unit"), str) and len(model["unit"]) > 12:
        problems.append("The unit must be 12 characters or fewer.")
    if model.get("unitPosition") not in ("prefix", "suffix"):
        problems.append("The unit position must be prefix or suffix.")
    t = model.get("threshold")
    if t is not None and not _is_num(t):
        problems.append("The decision threshold must be a number or left empty.")
    n = model.get("samples")
    if n is not None and (not _is_int(n) or not MIN_SAMPLES <= n <= MAX_SAMPLES):
        problems.append("Samples must be a whole number from %d to %d." % (MIN_SAMPLES, MAX_SAMPLES))
    s = model.get("seed")
    if s is not None and (not _is_int(s) or not 0 <= s <= _M32):
        problems.append("The seed must be a whole number from 0 to 4294967295.")
    terms = model.get("terms")
    if not isinstance(terms, list) or not terms:
        problems.append("The estimate needs at least one term.")
        return problems
    if len(terms) > MAX_TERMS:
        problems.append("The estimate can have at most %d terms." % MAX_TERMS)
    total = 0
    for ti, term in enumerate(terms):
        where = "Term %d" % (ti + 1)
        if not isinstance(term, dict):
            problems.append("%s is not valid." % where)
            continue
        if not isinstance(term.get("name"), str):
            problems.append("%s needs a name." % where)
        if term.get("sign") not in (1, -1) or isinstance(term.get("sign"), bool):
            problems.append("%s must be added (+1) or taken away (-1)." % where)
        drivers = term.get("drivers")
        if not isinstance(drivers, list) or not drivers:
            problems.append("%s needs at least one driver." % where)
            continue
        if len(drivers) > MAX_DRIVERS_PER_TERM:
            problems.append("%s can have at most %d drivers." % (where, MAX_DRIVERS_PER_TERM))
        for di, d in enumerate(drivers):
            total += 1
            label = "%s, driver %d" % (where, di + 1)
            if not isinstance(d, dict):
                problems.append("%s is not valid." % label)
                continue
            if isinstance(d.get("name"), str) and d["name"].strip():
                label += " (%s)" % d["name"].strip()
            else:
                problems.append("%s needs a name." % label)
            dist = d.get("dist")
            if dist not in DISTS:
                problems.append("%s has an unknown kind of range." % label)
                continue
            lo, hi = d.get("low"), d.get("high")
            if not _is_num(lo) or (dist != "fixed" and not _is_num(hi)):
                problems.append("%s needs numbers for its range." % label)
                continue
            if dist == "fixed":
                continue
            if not lo < hi:
                problems.append("%s: the low value must be below the high value." % label)
            elif dist == "lognormal" and lo <= 0:
                problems.append("%s: a skewed (lognormal) range must be above zero." % label)
            elif dist == "share" and not (0 < lo and hi < 100):
                problems.append("%s: a percentage range must be between 0 and 100, not including them." % label)
    if total > MAX_DRIVERS:
        problems.append("The estimate can have at most %d drivers." % MAX_DRIVERS)
    return problems


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------

def _logit(p):
    return math.log(p / (1 - p))


def dist_params(d):
    dist, lo, hi = d["dist"], d["low"], d.get("high")
    if dist == "lognormal":
        a, b = math.log(lo), math.log(hi)
        return {"mu": (a + b) / 2, "sigma": (b - a) / (2 * Z95)}
    if dist == "normal":
        return {"mu": (lo + hi) / 2, "sigma": (hi - lo) / (2 * Z95)}
    if dist == "share":
        a, b = _logit(lo / 100), _logit(hi / 100)
        return {"mu": (a + b) / 2, "sigma": (b - a) / (2 * Z95)}
    return {}


def transform(d, p, z, u):
    """The driver's value at normal score z (or uniform position u). Shares come out as fractions."""
    dist = d["dist"]
    if dist == "lognormal":
        return math.exp(p["mu"] + p["sigma"] * z)
    if dist == "normal":
        return p["mu"] + p["sigma"] * z
    if dist == "share":
        return 1 / (1 + math.exp(-(p["mu"] + p["sigma"] * z)))
    if dist == "uniform":
        return d["low"] + (d["high"] - d["low"]) * u
    return d["low"]


def quantile(d, which):
    """The 10th, 50th or 90th percentile of a driver (which = -1, 0 or 1)."""
    p = dist_params(d)
    return transform(d, p, which * Z90, (0.1, 0.5, 0.9)[which + 1])


def midpoint(d):
    """The middle of the range, as someone plugging in single numbers might use."""
    if d["dist"] == "fixed":
        return d["low"]
    m = (d["low"] + d["high"]) / 2
    return m / 100 if d["dist"] == "share" else m


def drivers_of(model):
    out = []
    for ti, term in enumerate(model["terms"]):
        for di, d in enumerate(term["drivers"]):
            out.append((ti, di, d))
    return out


def evaluate(model, values):
    """The estimate for one set of driver values (listed in model order)."""
    total = 0.0
    k = 0
    for term in model["terms"]:
        prod = float(term["sign"])
        for _ in term["drivers"]:
            prod *= values[k]
            k += 1
        total += prod
    return total


# ---------------------------------------------------------------------------
# Sampling and analysis
# ---------------------------------------------------------------------------

def simulate(model, samples=None, seed=None):
    """Latin hypercube samples: returns (estimate values, one column of values per driver)."""
    n = int(samples if samples is not None else model.get("samples") or DEFAULT_SAMPLES)
    s = int(seed if seed is not None else (model.get("seed") if model.get("seed") is not None else DEFAULT_SEED))
    rnd = mulberry32(s)
    columns = []
    for _, _, d in drivers_of(model):
        if d["dist"] == "fixed":
            columns.append([float(d["low"])] * n)
            continue
        p = dist_params(d)
        perm = shuffle(list(range(n)), rnd)
        col = []
        for k in range(n):
            u = (perm[k] + rnd()) / n
            u = min(max(u, 1e-12), 1 - 1e-12)
            z = 0.0 if d["dist"] == "uniform" else inv_norm(u)
            col.append(transform(d, p, z, u))
        columns.append(col)
    values = []
    for k in range(n):
        total = 0.0
        c = 0
        for term in model["terms"]:
            prod = float(term["sign"])
            for _ in term["drivers"]:
                prod *= columns[c][k]
                c += 1
            total += prod
        values.append(total)
    return values, columns


def percentile(sorted_values, q):
    """Linear interpolation between order statistics (the usual 'type 7' definition)."""
    n = len(sorted_values)
    h = (n - 1) * q
    lo = math.floor(h)
    if lo + 1 >= n:
        return sorted_values[-1]
    return sorted_values[lo] + (h - lo) * (sorted_values[lo + 1] - sorted_values[lo])


def mean(xs):
    total = 0.0
    for x in xs:
        total += x
    return total / len(xs)


def variance(xs, m=None):
    if len(xs) < 2:
        return 0.0
    m = mean(xs) if m is None else m
    total = 0.0
    for x in xs:
        total += (x - m) * (x - m)
    return total / (len(xs) - 1)


def analyse(model, samples=None, seed=None):
    """Run the model and return the summary the app shows."""
    problems = validate_model(model)
    if problems:
        raise ValueError(problems[0])
    values, columns = simulate(model, samples, seed)
    srt = sorted(values)
    m = mean(values)
    var = variance(values, m)
    drv = drivers_of(model)
    medians = [quantile(d, 0) for _, _, d in drv]
    base = evaluate(model, medians)
    means = [mean(col) for col in columns]
    rows = []
    for i, (ti, di, d) in enumerate(drv):
        lo_vals = list(medians)
        hi_vals = list(medians)
        lo_vals[i] = quantile(d, -1)
        hi_vals[i] = quantile(d, 1)
        low_out = evaluate(model, lo_vals)
        high_out = evaluate(model, hi_vals)
        # The estimate is linear in each driver: slope = sign x product of the other drivers' means.
        slope = float(model["terms"][ti]["sign"])
        for j, (tj, _, _) in enumerate(drv):
            if tj == ti and j != i:
                slope *= means[j]
        var_i = variance(columns[i], means[i])
        rows.append({
            "term": ti,
            "index": di,
            "name": d["name"],
            "dist": d["dist"],
            "mean": means[i],
            "p10": lo_vals[i],
            "p50": medians[i],
            "p90": hi_vals[i],
            "lowOut": low_out,
            "highOut": high_out,
            "swing": abs(high_out - low_out),
            "slope": slope,
            "varShare": (slope * slope * var_i / var) if var > 0 else 0.0,
        })
    order = sorted(range(len(rows)), key=lambda i: (-rows[i]["swing"], i))
    share_total = 0.0
    for r in rows:
        share_total += r["varShare"]
    threshold = model.get("threshold")
    above = None
    voi = None
    if threshold is not None:
        count = 0
        for v in values:
            if v >= threshold:
                count += 1
        above = count / len(values)
        voi = value_of_information(model, values, columns, means, rows, m, threshold)
    return {
        "n": len(values),
        "mean": m,
        "sd": math.sqrt(var),
        "min": srt[0],
        "max": srt[-1],
        "p5": percentile(srt, 0.05),
        "p10": percentile(srt, 0.10),
        "p25": percentile(srt, 0.25),
        "p50": percentile(srt, 0.50),
        "p75": percentile(srt, 0.75),
        "p90": percentile(srt, 0.90),
        "p95": percentile(srt, 0.95),
        "atMedians": base,
        "atMidpoints": evaluate(model, [midpoint(d) for _, _, d in drv]),
        "threshold": threshold,
        "probAbove": above,
        "drivers": rows,
        "tornado": order,
        "interaction": max(0.0, 1 - share_total),
        "voi": voi,
    }


def value_of_information(model, values, columns, means, rows, m, threshold):
    """How much pinning down each driver would be worth before a go/hold decision.

    Going ahead pays (estimate - threshold); holding off pays 0. Today's call is
    whichever has the higher expected payoff. Because the estimate is linear in
    each driver, the expected estimate given driver i is base + slope_i x (x_i - mean_i),
    which makes the expected value of partial perfect information (EVPPI) a
    one-dimensional average over that driver's samples.

    Both are written as the average loss from the cases where today's call
    turns out wrong (rather than as a difference of two large averages), which
    is the same quantity without the rounding error of a subtraction.
    """
    n = len(values)
    go = m >= threshold
    total = 0.0
    wrong = 0
    for v in values:
        total += max(threshold - v, 0.0) if go else max(v - threshold, 0.0)
        if (v >= threshold) != go:
            wrong += 1
    evpi = total / n
    base = evaluate(model, means)
    base_go = base >= threshold
    out = []
    for i, r in enumerate(rows):
        acc = 0.0
        flips = 0
        col = columns[i]
        for k in range(n):
            cond = base + r["slope"] * (col[k] - means[i])
            acc += max(threshold - cond, 0.0) if base_go else max(cond - threshold, 0.0)
            if (cond >= threshold) != base_go:
                flips += 1
        out.append({"evppi": acc / n, "flip": flips / n})
    order = sorted(range(len(out)), key=lambda i: (-out[i]["evppi"], -out[i]["flip"], i))
    return {"decision": "go" if go else "hold", "expected": m, "wrongChance": wrong / n, "evpi": evpi,
            "drivers": out, "order": order}


# ---------------------------------------------------------------------------
# Number formatting (identical in the app, so reports and screen agree)
# ---------------------------------------------------------------------------

def _decimals(v):
    if v >= 100:
        return 0
    if v >= 10:
        return 1
    if v >= 1:
        return 2
    if v >= 0.1:
        return 3
    if v >= 0.01:
        return 4
    if v >= 0.001:
        return 5
    return 6


def _fixed(v, dec):
    f = 10 ** dec
    return math.floor(v * f + 0.5) / f


def format_number(x):
    """Three significant figures with k, m and bn: 1234567 -> '1.23m'."""
    if not _is_num(x):
        return "n/a"
    a = abs(x)
    scales = [(1e9, "bn"), (1e6, "m"), (1e3, "k"), (1, "")]
    idx = len(scales) - 1
    for i, (scale, _) in enumerate(scales):
        if a >= scale:
            idx = i
            break
    v = a / scales[idx][0]
    dec = _decimals(v)
    r = _fixed(v, dec)
    if r >= 1000 and idx > 0:
        idx -= 1
        v = a / scales[idx][0]
        dec = _decimals(v)
        r = _fixed(v, dec)
    s = "%.*f" % (dec, r)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s == "0":
        return "0"
    return ("-" if x < 0 else "") + s + scales[idx][1]


def format_value(x, unit="", position="prefix"):
    s = format_number(x)
    if s == "n/a" or not unit:
        return s
    neg = s.startswith("-")
    body = s[1:] if neg else s
    if position == "prefix":
        return ("-" if neg else "") + unit + body
    return s + " " + unit


def format_driver(x, d):
    """A driver's value in its own terms: shares as percentages."""
    if d["dist"] == "share":
        return format_number(x * 100) + "%"
    unit = d.get("unit") or ""
    if unit == "£":
        return format_value(x, "£", "prefix")
    return format_number(x) + (" " + unit if unit else "")
