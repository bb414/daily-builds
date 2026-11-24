"""The forecasting model: synthetic sales, five forecasting methods plus planner
overrides, and scoring.

This is a line-for-line mirror of the MODEL block in app/index.html. It uses the
same arithmetic in the same order (only + - * / and floor), so the two give the
same numbers; tests/test_agreement.py checks that they do.
"""

import math

YEAR = 52
SQRT3 = 1.7320508075688772
ALPHA = 0.2       # smoothing: weight on the newest level
GAMMA = 0.15      # smoothing: weight on the newest seasonal index
MA_WEEKS = 8      # moving average length
LAMBDA = 2        # ridge penalty for the AI model
REFIT_EVERY = 4   # weeks between refits of the AI model

STORES = [
    {"id": "orchard", "name": "Orchard", "size": 1.6},
    {"id": "tampines", "name": "Tampines", "size": 1.3},
    {"id": "jurong-east", "name": "Jurong East", "size": 1.2},
    {"id": "bishan", "name": "Bishan", "size": 1.0},
    {"id": "bedok", "name": "Bedok", "size": 0.9},
    {"id": "clementi", "name": "Clementi", "size": 0.8},
    {"id": "woodlands", "name": "Woodlands", "size": 0.7},
    {"id": "punggol", "name": "Punggol", "size": 0.6},
]

EVENTS = [
    {"id": "cny", "name": "Chinese New Year", "weeks": [5, 3, 6], "shape": [[-2, 0.5], [-1, 1], [0, 0.7], [1, -0.4]]},
    {"id": "valentine", "name": "Valentine's Day", "weeks": [6, 6, 6], "shape": [[-1, 0.4], [0, 1]]},
    {"id": "raya", "name": "Hari Raya Puasa", "weeks": [16, 15, 13], "shape": [[-2, 0.4], [-1, 1], [0, 0.5], [1, -0.3]]},
    {"id": "deepavali", "name": "Deepavali", "weeks": [44, 43, 45], "shape": [[-1, 1], [0, 0.6], [1, -0.2]]},
    {"id": "christmas", "name": "Christmas", "weeks": [50, 50, 50], "shape": [[-1, 0.7], [0, 1], [1, -0.5]]},
]

PRODUCTS = [
    {"id": "pineapple-tarts", "name": "Pineapple tarts", "base": 30, "events": {"cny": 3.5}, "promo": 0.04, "promoLift": 1},
    {"id": "kueh-bangkit", "name": "Kueh bangkit", "base": 12, "events": {"cny": 4}, "promo": 0.03, "promoLift": 0.8},
    {"id": "love-letters", "name": "Love letters", "base": 14, "events": {"cny": 3}, "promo": 0.04, "promoLift": 0.8},
    {"id": "kueh-lapis", "name": "Kueh lapis", "base": 10, "events": {"raya": 3, "cny": 1.5}, "promo": 0.04, "promoLift": 0.8},
    {"id": "almond-londons", "name": "Almond londons", "base": 8, "events": {"raya": 3.5}, "promo": 0.03, "promoLift": 0.8},
    {"id": "murukku", "name": "Murukku", "base": 7, "events": {"deepavali": 4}, "promo": 0.03, "promoLift": 0.8},
    {"id": "truffles", "name": "Chocolate truffles", "base": 16, "events": {"valentine": 3, "christmas": 2}, "promo": 0.06, "promoLift": 1},
    {"id": "gingerbread", "name": "Gingerbread tins", "base": 4, "events": {"christmas": 5}, "promo": 0.02, "promoLift": 0.6},
    {"id": "gummy-bears", "name": "Gummy bears", "base": 40, "events": {}, "promo": 0.12, "promoLift": 1.2},
    {"id": "butter-mints", "name": "Butter mints", "base": 28, "events": {}, "promo": 0.05, "promoLift": 0.6},
    {"id": "mochi", "name": "Mochi assortment", "base": 18, "events": {"cny": 1.3}, "promo": 0.08, "promoLift": 1},
    {"id": "gift-box", "name": "Luxury gift box", "base": 1.5, "events": {"cny": 3, "christmas": 3}, "promo": 0, "promoLift": 0},
]

METHODS = [
    {"id": "naive", "name": "Naive", "detail": "Last week's sales"},
    {"id": "average", "name": "Moving average", "detail": "The average of the last eight weeks"},
    {"id": "seasonal", "name": "Seasonal naive", "detail": "The same week last year"},
    {"id": "smoothing", "name": "Seasonal smoothing", "detail": "Exponential smoothing with a weekly seasonal pattern"},
    {"id": "ai", "name": "AI model", "detail": "A regression trained on all stores, with promotions and the festival calendar"},
    {"id": "planner", "name": "AI + planners", "detail": "The AI forecast after planners' manual overrides"},
]
METHOD_IDS = [m["id"] for m in METHODS]
SIMPLER = ["naive", "average", "seasonal", "smoothing"]

# key: (default, lowest, highest, whole number?)
SETTINGS = {
    "seed": (7, 0, 4294967295, True),
    "holidays": (1, 0, 2, False),
    "promoLift": (0.5, 0, 1.5, False),
    "noise": (0.2, 0, 0.6, False),
    "growth": (0.06, -0.2, 0.3, False),
    "horizon": (1, 1, 4, True),
    "overrideRate": (0.3, 0, 1, False),
    "optimism": (0.12, -0.3, 0.3, False),
    "insight": (0.2, 0, 1, False),
    "buffer": (0.1, 0, 0.5, False),
    "threshold": (0.03, 0, 0.1, False),
}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def normalise_settings(given=None):
    given = given if isinstance(given, dict) else {}
    out = {}
    for key, (default, lo, hi, whole) in SETTINGS.items():
        v = given.get(key)
        if not _is_number(v):
            v = default
        if whole:
            v = math.floor(v)
        out[key] = min(hi, max(lo, v))
    return out


def make_rng(seed):
    """Seeded generator matching the app's mulberry32, bit for bit."""
    state = int(seed) & 0xFFFFFFFF

    def rng():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rng


def normal(rng):
    """Roughly normal noise from four uniforms (mean 0, standard deviation 1)."""
    return (rng() + rng() + rng() + rng() - 2) * SQRT3


def clamp(x, lo, hi):
    return min(hi, max(lo, x))


def tri(w, centre, radius):
    d = abs(w - centre) / radius
    return 0 if d >= 1 else 1 - d


def season_factor(woy):
    return 1 + 0.08 * tri(woy, 24, 3) + 0.1 * tri(woy, 47, 4) - 0.05 * tri(woy, 34, 4)


def event_features(weeks):
    features = []
    for e in EVENTS:
        for offset, weight in e["shape"]:
            flags = []
            for t in range(weeks):
                year = t // YEAR
                flags.append(1 if year < len(e["weeks"]) and t % YEAR == e["weeks"][year] + offset else 0)
            features.append({"id": e["id"] + ("" if offset < 0 else "+") + str(offset), "event": e["id"],
                             "offset": offset, "weight": weight, "flags": flags})
    return features


def simulate(settings=None):
    """Three years of weekly sales for every product in every store."""
    s = normalise_settings(settings)
    weeks = 3 * YEAR
    rng = make_rng(s["seed"])
    promo = [[1 if rng() < p["promo"] else 0 for _ in range(weeks)] for p in PRODUCTS]
    events = event_features(weeks)
    sales = []
    for pi, p in enumerate(PRODUCTS):
        rows = []
        for st in STORES:
            row = []
            for t in range(weeks):
                m = p["base"] * st["size"]
                m = m * season_factor(t % YEAR)
                m = m * (1 + s["growth"] * t / YEAR)
                for f in events:
                    k = p["events"].get(f["event"])
                    if k is not None and f["flags"][t]:
                        m = m * max(0.3, 1 + (k - 1) * s["holidays"] * f["weight"])
                if promo[pi][t]:
                    m = m * (1 + s["promoLift"] * p["promoLift"])
                elif t > 0 and promo[pi][t - 1]:
                    m = m * max(0.3, 1 - 0.3 * s["promoLift"] * p["promoLift"])
                z = normal(rng)
                cv = s["noise"] + 1 / (1 + m)
                row.append(max(0, math.floor(m * (1 + cv * z) + 0.5)))
            rows.append(row)
        sales.append(rows)
    return {
        "weeks": weeks,
        "testStart": weeks - YEAR,
        "skus": [{"id": p["id"], "name": p["name"]} for p in PRODUCTS],
        "stores": [{"id": st["id"], "name": st["name"]} for st in STORES],
        "sales": sales,
        "promo": promo,
        "events": events,
        "synthetic": True,
    }


# ---------- Forecasting methods ----------

def _empty_grid(data):
    return [[[None] * data["weeks"] for _ in rows] for rows in data["sales"]]


def naive(data, h):
    out = _empty_grid(data)
    for p, rows in enumerate(data["sales"]):
        for s, y in enumerate(rows):
            for t in range(data["testStart"], data["weeks"]):
                out[p][s][t] = y[t - h]
    return out


def moving_average(data, h):
    out = _empty_grid(data)
    for p, rows in enumerate(data["sales"]):
        for s, y in enumerate(rows):
            for t in range(data["testStart"], data["weeks"]):
                total = 0
                for k in range(t - h - MA_WEEKS + 1, t - h + 1):
                    total += y[k]
                out[p][s][t] = total / MA_WEEKS
    return out


def seasonal_naive(data):
    out = _empty_grid(data)
    for p, rows in enumerate(data["sales"]):
        for s, y in enumerate(rows):
            for t in range(data["testStart"], data["weeks"]):
                out[p][s][t] = y[t - YEAR]
    return out


def smoothing_series(y, h, test_start):
    """Multiplicative seasonal exponential smoothing (Holt-Winters without a trend)."""
    fc = [None] * len(y)
    level = 0
    for t in range(YEAR):
        level += y[t]
    level = level / YEAR
    if level < 0.1:
        level = 0.1
    season = []
    for t in range(YEAR):
        prev = y[0 if t == 0 else t - 1]
        nxt = y[YEAR - 1 if t == YEAR - 1 else t + 1]
        season.append(clamp((prev + y[t] + nxt) / 3 / level, 0.1, 10))
    for o in range(YEAR, len(y)):
        si = season[o % YEAR]
        new_level = ALPHA * (y[o] / si) + (1 - ALPHA) * level
        if new_level < 0.1:
            new_level = 0.1
        season[o % YEAR] = clamp(GAMMA * (y[o] / new_level) + (1 - GAMMA) * si, 0.1, 10)
        level = new_level
        target = o + h
        if test_start <= target < len(y):
            fc[target] = level * season[target % YEAR]
    return fc


def smoothing(data, h):
    return [[smoothing_series(y, h, data["testStart"]) for y in rows] for rows in data["sales"]]


def feature_names(data):
    return (["intercept", "recent", "last four weeks", "same week last year", "promotion", "week after a promotion"]
            + ["event " + e["id"] for e in data["events"]] + ["festival week last year"])


def features(data, p, s, t, h):
    """Features for forecasting week t from h weeks earlier. Returns (level, x)."""
    y = data["sales"][p][s]
    total = 0
    for k in range(t - h - 51, t - h + 1):
        total += y[k]
    level = total / YEAR + 0.5
    recent4 = y[t - h - 3] + y[t - h - 2] + y[t - h - 1] + y[t - h]
    promo_now = data["promo"][p][t]
    post_promo = 1 if data["promo"][p][t - 1] and not promo_now else 0
    x = [1, y[t - h] / level, recent4 / 4 / level, y[t - YEAR] / level, promo_now, post_promo]
    last_year = 0
    for e in data["events"]:
        x.append(e["flags"][t])
        if e["flags"][t - YEAR]:
            last_year = 1
    x.append(last_year)
    return level, x


def solve_ridge(xtx, xty):
    """Solve (X'X + lambda I) b = X'y by Gaussian elimination with partial pivoting."""
    n = len(xty)
    a = []
    b = []
    for i in range(n):
        row = []
        for j in range(n):
            v = xtx[i][j] if i <= j else xtx[j][i]
            if i == j and i > 0:
                v = v + LAMBDA
            row.append(v)
        a.append(row)
        b.append(xty[i])
    for col in range(n):
        piv = col
        for r in range(col + 1, n):
            if abs(a[r][col]) > abs(a[piv][col]):
                piv = r
        if piv != col:
            a[piv], a[col] = a[col], a[piv]
            b[piv], b[col] = b[col], b[piv]
        if abs(a[col][col]) < 1e-12:
            continue
        for r in range(col + 1, n):
            f = a[r][col] / a[col][col]
            if f != 0:
                for c in range(col, n):
                    a[r][c] -= f * a[col][c]
                b[r] -= f * b[col]
    beta = [0] * n
    for i in range(n - 1, -1, -1):
        total = b[i]
        for j in range(i + 1, n):
            total -= a[i][j] * beta[j]
        beta[i] = 0 if abs(a[i][i]) < 1e-12 else total / a[i][i]
    return beta


def ai_model(data, h):
    """One ridge regression per product, pooled across stores, refitted every four weeks."""
    out = _empty_grid(data)
    coefficients = []
    first = 51 + h
    n_stores = len(data["stores"])
    for p, rows in enumerate(data["sales"]):
        n = 7 + len(data["events"])
        xtx = [[0] * n for _ in range(n)]
        xty = [0] * n
        nxt = first
        beta = None
        for start in range(data["testStart"], data["weeks"], REFIT_EVERY):
            while nxt <= start - h:
                for s in range(n_stores):
                    level, x = features(data, p, s, nxt, h)
                    target = rows[s][nxt] / level
                    for i in range(n):
                        xi = x[i]
                        xty[i] += xi * target
                        row = xtx[i]
                        for j in range(i, n):
                            row[j] += xi * x[j]
                nxt += 1
            beta = solve_ridge(xtx, xty)
            for t in range(start, min(start + REFIT_EVERY, data["weeks"])):
                for s in range(n_stores):
                    level, x = features(data, p, s, t, h)
                    dot = 0
                    for i in range(n):
                        dot += beta[i] * x[i]
                    out[p][s][t] = max(0, level * dot)
        coefficients.append(beta)
    return out, coefficients


def planners(data, ai, s):
    """Planner overrides: some real information, some noise, and an upward lean."""
    out = _empty_grid(data)
    info = _empty_grid(data)
    rng = make_rng((s["seed"] ^ 0x9E3779B9) & 0xFFFFFFFF)
    for p, rows in enumerate(data["sales"]):
        for st, y in enumerate(rows):
            for t in range(data["testStart"], data["weeks"]):
                u = rng()
                z = normal(rng)
                base = ai[p][st][t]
                f = base
                if u < s["overrideRate"]:
                    f = max(0, base * (1 + s["optimism"] + 0.15 * z) + s["insight"] * (y[t] - base))
                out[p][st][t] = f
                info[p][st][t] = u < s["overrideRate"]
    return out, info


# ---------- Scoring ----------

def week_type(data, p, t):
    if data["promo"][p][t] or (t > 0 and data["promo"][p][t - 1]):
        return "promo"
    for e in data["events"]:
        if e["flags"][t]:
            return "festival"
    return "ordinary"


def _new_tally():
    return {"abs": 0, "signed": 0, "actual": 0, "sold": 0, "waste": 0, "lost": 0, "n": 0}


def _add(tally, actual, forecast, buffer):
    stock = math.floor(forecast * (1 + buffer) + 0.5)
    sold = min(stock, actual)
    tally["abs"] += abs(actual - forecast)
    tally["signed"] += forecast - actual
    tally["actual"] += actual
    tally["sold"] += sold
    tally["waste"] += stock - sold
    tally["lost"] += actual - sold
    tally["n"] += 1


def _summary(tally):
    a = tally["actual"]
    return {
        "n": tally["n"],
        "actual": a,
        "wape": tally["abs"] / a if a > 0 else None,
        "bias": tally["signed"] / a if a > 0 else None,
        "fillRate": tally["sold"] / a if a > 0 else None,
        "waste": tally["waste"],
        "lost": tally["lost"],
    }


def forecast_all(data, settings=None):
    s = normalise_settings(settings)
    ai, coefficients = ai_model(data, s["horizon"])
    planned, overridden = planners(data, ai, s)
    return {
        "settings": s,
        "forecasts": {
            "naive": naive(data, s["horizon"]),
            "average": moving_average(data, s["horizon"]),
            "seasonal": seasonal_naive(data),
            "smoothing": smoothing(data, s["horizon"]),
            "ai": ai,
            "planner": planned,
        },
        "overridden": overridden,
        "coefficients": coefficients,
        "featureNames": feature_names(data),
    }


def evaluate(data, fc):
    s = fc["settings"]
    overall = {m: _new_tally() for m in METHOD_IDS}
    by_type = {k: {m: _new_tally() for m in METHOD_IDS} for k in ("festival", "promo", "ordinary")}
    groups = {k: {"n": 0, "before": 0, "after": 0, "actual": 0} for k in ("up", "down", "small", "large")}
    by_sku = []
    for p, rows in enumerate(data["sales"]):
        sku = {m: _new_tally() for m in METHOD_IDS}
        for st, y in enumerate(rows):
            for t in range(data["testStart"], data["weeks"]):
                kind = week_type(data, p, t)
                for m in METHOD_IDS:
                    f = fc["forecasts"][m][p][st][t]
                    _add(overall[m], y[t], f, s["buffer"])
                    _add(sku[m], y[t], f, s["buffer"])
                    _add(by_type[kind][m], y[t], f, s["buffer"])
                if fc["overridden"][p][st][t]:
                    before = fc["forecasts"]["ai"][p][st][t]
                    after = fc["forecasts"]["planner"][p][st][t]
                    if after != before:
                        direction = "up" if after > before else "down"
                        size = "small" if abs(after - before) / max(before, 1) < 0.2 else "large"
                        for k in (direction, size):
                            groups[k]["n"] += 1
                            groups[k]["before"] += abs(y[t] - before)
                            groups[k]["after"] += abs(y[t] - after)
                            groups[k]["actual"] += y[t]
        w = {m: _summary(sku[m]) for m in METHOD_IDS}
        best = SIMPLER[0]
        for m in SIMPLER:
            if w[m]["wape"] is not None and (w[best]["wape"] is None or w[m]["wape"] < w[best]["wape"]):
                best = m
        gain = w[best]["wape"] - w["ai"]["wape"] if w["ai"]["wape"] is not None and w[best]["wape"] is not None else None
        planner_gain = (w["ai"]["wape"] - w["planner"]["wape"]
                        if w["ai"]["wape"] is not None and w["planner"]["wape"] is not None else None)
        by_sku.append({
            "id": data["skus"][p]["id"],
            "name": data["skus"][p]["name"],
            "methods": w,
            "bestSimpler": best,
            "aiGain": gain,
            "plannerGain": planner_gain,
            "verdict": "ai" if gain is not None and gain >= s["threshold"] else "simpler",
        })
    naive_wape = _summary(overall["naive"])["wape"]
    methods = []
    for i, m in enumerate(METHODS):
        r = _summary(overall[m["id"]])
        r["id"] = m["id"]
        r["name"] = m["name"]
        prev = _summary(overall[METHOD_IDS[i - 1]])["wape"] if i > 0 else None
        r["fvaNaive"] = naive_wape - r["wape"] if r["wape"] is not None and naive_wape is not None else None
        r["fvaPrevious"] = prev - r["wape"] if i > 0 and r["wape"] is not None and prev is not None else None
        methods.append(r)
    types = {k: {m: _summary(by_type[k][m]) for m in METHOD_IDS} for k in by_type}
    overrides = {}
    for k, g in groups.items():
        overrides[k] = {
            "n": g["n"],
            "wapeBefore": g["before"] / g["actual"] if g["actual"] > 0 else None,
            "wapeAfter": g["after"] / g["actual"] if g["actual"] > 0 else None,
            "improved": (g["before"] - g["after"]) / g["actual"] if g["actual"] > 0 else None,
        }
    return {
        "settings": s,
        "methods": methods,
        "bySku": by_sku,
        "byWeekType": types,
        "overrides": overrides,
        "deployOn": sum(1 for x in by_sku if x["verdict"] == "ai"),
    }


def run(settings=None):
    data = simulate(settings)
    fc = forecast_all(data, settings)
    return {"data": data, "forecasts": fc, "results": evaluate(data, fc)}
