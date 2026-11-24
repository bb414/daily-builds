"""The markdown model: exact dynamic programming over days, stock and price.

A line-by-line port of the MODEL block in app/index.html. The tests run both
versions on the same inputs and check that they agree, so a plan worked out in
the browser and one worked out here are the same plan.
"""

import math
import re

# Discounts on the ladder, in % off the full price.
LADDER = [0, 10, 20, 30, 50]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# Demand by weekday, Monday first. Each pattern averages 1.
WEEK_PATTERNS = {
    "flat": [1, 1, 1, 1, 1, 1, 1],
    "highStreet": [0.8, 0.8, 0.85, 0.95, 1.15, 1.45, 1.0],
    "office": [1.2, 1.2, 1.2, 1.15, 1.05, 0.6, 0.6],
}
# Allowed range, step and default for every setting.
FIELDS = {
    "stock": {"min": 1, "max": 300, "step": 1, "value": 60},
    "days": {"min": 1, "max": 21, "step": 1, "value": 7},
    "price": {"min": 0.5, "max": 100, "step": 0.1, "value": 12},
    "unitCost": {"min": 0, "max": 100, "step": 0.1, "value": 4.8},
    "wasteCost": {"min": -50, "max": 50, "step": 0.05, "value": 0.3},
    "demand": {"min": 0.1, "max": 100, "step": 0.1, "value": 6},
    "elasticity": {"min": 0, "max": 6, "step": 0.1, "value": 1.8},
    "freshness": {"min": 0, "max": 40, "step": 1, "value": 0},
    "startDay": {"min": 0, "max": 6, "step": 1, "value": 0},
}
PRESETS = {
    "truffles": {"name": "Chocolate truffle box", "stock": 60, "days": 7, "price": 12, "unitCost": 4.8, "wasteCost": 0.3, "demand": 6, "elasticity": 1.8, "freshness": 3, "startDay": 0, "pattern": "highStreet"},
    "mochi": {"name": "Fresh mochi, pack of six", "stock": 40, "days": 3, "price": 6.5, "unitCost": 2.4, "wasteCost": 0.2, "demand": 10, "elasticity": 2.5, "freshness": 15, "startDay": 3, "pattern": "highStreet"},
    "eclairs": {"name": "Coffee eclairs at an office kiosk", "stock": 30, "days": 2, "price": 3.2, "unitCost": 1.1, "wasteCost": 0.1, "demand": 11, "elasticity": 3, "freshness": 20, "startDay": 3, "pattern": "office"},
    "tins": {"name": "Festive biscuit tins", "stock": 120, "days": 14, "price": 15, "unitCost": 6, "wasteCost": 2, "demand": 6, "elasticity": 2.2, "freshness": 0, "startDay": 0, "pattern": "highStreet"},
}
MAX_STOCK = FIELDS["stock"]["max"]

# log(k!) for k = 0..MAX_STOCK, summed in the same order as the browser app.
LOG_FACT = [0.0]
for _k in range(1, MAX_STOCK + 1):
    LOG_FACT.append(LOG_FACT[_k - 1] + math.log(_k))


def js_round(x):
    """JavaScript's Math.round: halves round up."""
    return math.floor(x + 0.5)


_MISSING = object()
_JS_DECIMAL = re.compile(r"[+-]?(Infinity|([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?)")
_JS_PREFIXED = re.compile(r"0([xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)")


def _js_string(value):
    """JavaScript's String(value) for values inside an array (enough for js_number)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ",".join(_js_string(v) for v in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


def js_number(value):
    """JavaScript's Number(value) for anything a JSON settings file can hold. NaN if not a number."""
    if value is _MISSING:
        return math.nan
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return js_number(_js_string(value))
    if isinstance(value, str):
        text = value.strip(" \t\n\r\v\f\u00a0\ufeff")
        if not text:
            return 0.0
        if _JS_PREFIXED.fullmatch(text):
            return float(int(text, 0))
        if _JS_DECIMAL.fullmatch(text):
            return float(text.replace("Infinity", "inf"))
    return math.nan


def clamp_field(name, x):
    f = FIELDS[name]
    v = js_number(x)
    if not math.isfinite(v):
        v = float(f["value"])
    v = min(f["max"], max(f["min"], v))
    return int(js_round(v)) if f["step"] == 1 else v


def normalise(cfg=None):
    """Fill in defaults and keep every setting inside its range, as the browser app does."""
    if not isinstance(cfg, dict):
        cfg = {}
    out = {name: clamp_field(name, cfg.get(name, _MISSING)) for name in FIELDS}
    out["pattern"] = cfg.get("pattern") if isinstance(cfg.get("pattern"), str) and cfg.get("pattern") in WEEK_PATTERNS else "flat"
    out["monotone"] = cfg.get("monotone") is not False
    return out


def demand_rate(cfg, t, j):
    """Expected demand on day t (0 = first day) at ladder step j: weekday, freshness and discount."""
    weekday = (cfg["startDay"] + t) % 7
    return (cfg["demand"] * WEEK_PATTERNS[cfg["pattern"]][weekday] * (1 - cfg["freshness"] / 100) ** t *
            (1 - LADDER[j] / 100) ** (-cfg["elasticity"]))


def quantile(dist, q):
    """Smallest s with P(stock <= s) >= q."""
    cum = 0.0
    for s, p in enumerate(dist):
        cum += p
        if cum >= q - 1e-12:
            return s
    return len(dist) - 1


def poisson_window(lam, s_max):
    """Poisson probabilities for the counts that matter (see the browser app for details)."""
    if not lam > 0:
        return 0, 0, [1.0]
    spread = 12 * math.sqrt(lam) + 20
    lo = max(0, math.floor(lam - spread))
    hi = min(s_max, math.ceil(lam + spread))
    log_lam = math.log(lam)
    return lo, hi, [math.exp(-lam + c * log_lam - LOG_FACT[c]) for c in range(lo, hi + 1)]


def expected_values(win, price, nxt, s_max):
    """Expected takings today plus the value of what is left, for every stock level."""
    lo, hi, p = win
    out = [0.0] * (s_max + 1)
    for s in range(s_max + 1):
        total = mass = 0.0
        for c in range(lo, min(hi, s - 1) + 1):
            q = p[c - lo]
            total += q * (price * c + nxt[s - c])
            mass += q
        tail = max(0.0, 1 - mass)
        out[s] = total + tail * (price * s + nxt[0])
    return out


def solve(cfg_in):
    """Backward induction. Returns the best expected value, the value tables and the policy."""
    return solve_exact(normalise(cfg_in))


def solve_exact(cfg):
    """The same, for settings that are already complete (used directly by the robustness check)."""
    T, S, J = cfg["days"], cfg["stock"], len(LADDER)
    terminal = [-cfg["wasteCost"] * s for s in range(S + 1)]
    V = [None] * (T + 1)
    policy = [None] * T
    Q = [None] * T
    V[T] = [terminal for _ in LADDER]
    for t in range(T - 1, -1, -1):
        Q[t] = []
        for j in range(J):
            win = poisson_window(demand_rate(cfg, t, j), S)
            Q[t].append(expected_values(win, cfg["price"] * (1 - LADDER[j] / 100), V[t + 1][j], S))
        V[t], policy[t] = [], []
        for i in range(J):
            v, pol = [0.0] * (S + 1), [0] * (S + 1)
            for s in range(S + 1):
                best_j, best = -1, -math.inf
                for j in range(i if cfg["monotone"] else 0, J):
                    if Q[t][j][s] > best + 1e-9:
                        best, best_j = Q[t][j][s], j
                v[s], pol[s] = best, best_j
            V[t].append(v)
            policy[t].append(pol)
    return {"cfg": cfg, "value": V[0][0][S], "V": V, "Q": Q, "policy": policy}


def rule_step(pct):
    v = js_number(pct)
    return LADDER.index(int(v)) if math.isfinite(v) and v.is_integer() and int(v) in LADDER else 0


def policy_optimal(sol):
    return lambda t, s, i: sol["policy"][t][i][s]


def policy_never(sol):
    return lambda t, s, i: i


def policy_last_day(sol):
    T = sol["cfg"]["days"]
    return lambda t, s, i: len(LADDER) - 1 if t == T - 1 else i


def policy_rule(sol, pct, days_left):
    T, j = sol["cfg"]["days"], rule_step(pct)
    return lambda t, s, i: max(i, j) if T - t <= days_left else i


def evaluate(cfg_in, policy_fn):
    """Exact expected outcome of following a policy (no simulation)."""
    return evaluate_exact(normalise(cfg_in), policy_fn)


def evaluate_exact(cfg, policy_fn):
    T, S, J = cfg["days"], cfg["stock"], len(LADDER)
    dist = [[0.0] * (S + 1) for _ in range(J)]
    dist[0][S] = 1.0
    revenue = sold = discount_sum = 0.0
    days = []
    for t in range(T):
        nxt = [[0.0] * (S + 1) for _ in range(J)]
        day = {"stockStart": 0.0, "revenue": 0.0, "sold": 0.0, "stepProb": [0.0] * J, "stockDist": [0.0] * (S + 1)}
        wins = [poisson_window(demand_rate(cfg, t, jj), S) for jj in range(J)]
        for i in range(J):
            for s in range(S + 1):
                w = dist[i][s]
                if not w > 0:
                    continue
                day["stockStart"] += w * s
                day["stockDist"][s] += w
                j = policy_fn(t, s, i)
                if cfg["monotone"] and j < i:
                    j = i
                day["stepProb"][j] += w
                price = cfg["price"] * (1 - LADDER[j] / 100)
                lo, hi, p = wins[j]
                mass = 0.0
                for c in range(lo, min(hi, s - 1) + 1):
                    q = w * p[c - lo]
                    nxt[j][s - c] += q
                    day["revenue"] += q * price * c
                    day["sold"] += q * c
                    mass += p[c - lo]
                tail = w * max(0.0, 1 - mass)
                nxt[j][0] += tail
                day["revenue"] += tail * price * s
                day["sold"] += tail * s
                discount_sum += w * LADDER[j]
        day["p10"] = quantile(day["stockDist"], 0.1)
        day["p50"] = quantile(day["stockDist"], 0.5)
        day["p90"] = quantile(day["stockDist"], 0.9)
        revenue += day["revenue"]
        sold += day["sold"]
        days.append(day)
        dist = nxt
    left = [0.0] * (S + 1)
    for i in range(J):
        for s in range(S + 1):
            left[s] += dist[i][s]
    waste = 0.0
    for s in range(S + 1):
        waste += s * left[s]
    return {
        "revenue": revenue,
        "sold": sold,
        "waste": waste,
        "profit": revenue - cfg["wasteCost"] * waste,
        "profitAfterStock": revenue - cfg["wasteCost"] * waste - cfg["unitCost"] * S,
        "sellOut": left[0],
        "avgDiscount": discount_sum / T,
        "leftover": left,
        "leftoverP10": quantile(left, 0.1),
        "leftoverP50": quantile(left, 0.5),
        "leftoverP90": quantile(left, 0.9),
        "days": days,
    }


def card_thresholds(sol):
    """For each day, the smallest stock at which each discount starts (from the plan before any markdown)."""
    T, S, J = sol["cfg"]["days"], sol["cfg"]["stock"], len(LADDER)
    rows = []
    for t in range(T):
        pol, start = sol["policy"][t][0], [None] * J
        for s in range(1, S + 1):
            for j in range(1, pol[s] + 1):
                if start[j] is None:
                    start[j] = s
        rows.append({"day": t, "from": start})
    return rows


def policy_card(sol, rows=None):
    """Follow the shelf card exactly as printed, never moving back up the ladder."""
    rows = rows or card_thresholds(sol)

    def step(t, s, i):
        j = 0
        for k, start in enumerate(rows[t]["from"]):
            if start is not None and s >= start:
                j = k
        return max(i, j)
    return step


def shelf_card(sol):
    """The card, and what following it exactly would earn against the full plan."""
    rows = card_thresholds(sol)
    card = evaluate(sol["cfg"], policy_card(sol, rows))
    return {"rows": rows, "profit": card["profit"], "gap": sol["value"] - card["profit"]}


ROBUST_DEMAND = [0.6, 0.8, 1, 1.25, 1.5]
ROBUST_ELASTICITY = [0.6, 1, 1.4]


def robustness(cfg_in):
    """Plan with the numbers given, then score that plan when the truth is different."""
    cfg = normalise(cfg_in)
    plan = policy_optimal(solve(cfg))
    cells = []
    for g in ROBUST_ELASTICITY:
        for f in ROBUST_DEMAND:
            # Not clamped to the input limits: the truth can lie outside what you would type in.
            truth = dict(cfg, demand=cfg["demand"] * f, elasticity=cfg["elasticity"] * g)
            ideal = solve_exact(truth)["value"]
            cells.append({
                "demandFactor": f, "elasticityFactor": g,
                "planned": evaluate_exact(truth, plan)["profit"],
                "never": evaluate_exact(truth, policy_never(None))["profit"],
                "ideal": ideal,
            })
    return cells


def compare_policies(cfg_in, rule=None):
    """The best plan against three simple rules, each evaluated exactly."""
    sol = solve(cfg_in)
    rule = rule or {"pct": 30, "daysLeft": 2}
    rows = [
        {"key": "optimal", "name": "Best plan (this model)", "fn": policy_optimal(sol)},
        {"key": "never", "name": "Never discount", "fn": policy_never(sol)},
        {"key": "lastDay", "name": "Half price on the last day", "fn": policy_last_day(sol)},
        {"key": "rule", "name": "%s%% off with %s %s left" % (rule["pct"], rule["daysLeft"], "day" if rule["daysLeft"] == 1 else "days"),
         "fn": policy_rule(sol, rule["pct"], rule["daysLeft"])},
    ]
    for r in rows:
        r["result"] = evaluate(sol["cfg"], r["fn"])
    return {"solution": sol, "rows": rows}
