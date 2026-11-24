"""The Save or sink engine: a student's synthetic year of money, and automatic saving rules run against it.

Every amount is a whole number of pennies, so the browser app (which has the
same code between its MODEL markers) and this package give identical answers.
tests/test_app.py checks that they do.

The year runs from Monday 1 September to 31 August (365 days). Each rule moves
money from the current account into a savings pot. When the current account
drops below the person's comfort point, they move money back from the pot (a
"rescue"). Overdraft interest is charged only beyond the interest-free limit.
"""

import base64
import json
import math
import re

FORMAT = "save-or-sink-settings"
VERSION = 1

MONTHS = [("Sep", 30), ("Oct", 31), ("Nov", 30), ("Dec", 31), ("Jan", 31), ("Feb", 28),
          ("Mar", 31), ("Apr", 30), ("May", 31), ("Jun", 30), ("Jul", 31), ("Aug", 31)]
MONTH_STARTS = []
_d = 0
for _name, _len in MONTHS:
    MONTH_STARTS.append(_d)
    _d += _len
DAYS = _d                      # 365
LOAN_DAYS = [21, 126, 231]     # 22 September, 5 January, 20 April
BILL_DAY = 9                   # the 10th of each month
RULES = ["none", "roundup", "weekly", "payday", "smart", "planner"]
RULE_NAMES = {
    "none": "No automatic saving",
    "roundup": "Round-ups",
    "weekly": "Fixed amount every Monday",
    "payday": "Share of every payment in",
    "smart": "Smart saver (forecasts what is safe to save)",
    "planner": "Term planner (budgets to the next loan payment)",
}
RESCUE_MODES = ("overdrawn", "near-limit", "never")
SHOCK_SPREAD = 0.6
LEARNING_DAYS = 7

PRESETS = {
    "steady": {
        "label": "Steady part-time job",
        "startBalance": 400, "loanPerTerm": 3000, "hourlyPay": 11.5, "hoursPerWeek": 10, "hoursVariability": 0.2,
        "rent": 520, "bills": 30, "everydayPerWeek": 90, "socialPerWeek": 40, "spendVariability": 0.35,
        "shockChance": 0.35, "shockSize": 180,
    },
    "shifts": {
        "label": "Zero-hours shifts",
        "startBalance": 250, "loanPerTerm": 2800, "hourlyPay": 11.5, "hoursPerWeek": 12, "hoursVariability": 0.8,
        "rent": 500, "bills": 35, "everydayPerWeek": 95, "socialPerWeek": 50, "spendVariability": 0.45,
        "shockChance": 0.4, "shockSize": 200,
    },
    "tight": {
        "label": "Tight budget, no job",
        "startBalance": 150, "loanPerTerm": 3600, "hourlyPay": 11.5, "hoursPerWeek": 0, "hoursVariability": 0,
        "rent": 480, "bills": 25, "everydayPerWeek": 70, "socialPerWeek": 25, "spendVariability": 0.3,
        "shockChance": 0.3, "shockSize": 160,
    },
}


def default_settings(preset="steady"):
    s = {"format": FORMAT, "version": VERSION, "preset": preset, "seed": 1}
    s.update({k: v for k, v in PRESETS[preset].items() if k != "label"})
    s.update({
        "overdraftLimit": 1000, "overdraftRate": 39.9, "savingsRate": 4.0, "rescue": "overdrawn",
        "rules": {
            "roundup": {"multiplier": 1},
            "weekly": {"amount": 15},
            "payday": {"percent": 10},
            "smart": {"horizon": 14, "buffer": 100, "aggressiveness": 0.5, "cap": 100, "knowsBills": True},
            "planner": {"buffer": 100, "aggressiveness": 0.5, "cap": 100},
        },
    })
    return s


# Allowed ranges for every setting: (min, max).
LIMITS = {
    "startBalance": (-2000, 20000), "loanPerTerm": (0, 10000), "hourlyPay": (0, 50), "hoursPerWeek": (0, 40),
    "hoursVariability": (0, 2), "rent": (0, 3000), "bills": (0, 500), "everydayPerWeek": (0, 1000),
    "socialPerWeek": (0, 1000), "spendVariability": (0, 1.5), "shockChance": (0, 1), "shockSize": (0, 5000),
    "overdraftLimit": (0, 5000), "overdraftRate": (0, 100), "savingsRate": (0, 20), "seed": (0, 4294967295),
}
RULE_LIMITS = {
    "roundup": {"multiplier": (1, 10)},
    "weekly": {"amount": (0, 1000)},
    "payday": {"percent": (0, 100)},
    "smart": {"horizon": (1, 120), "buffer": (0, 5000), "aggressiveness": (0, 1), "cap": (0, 5000)},
    "planner": {"buffer": (0, 5000), "aggressiveness": (0, 1), "cap": (0, 5000)},
}
INTEGER_KEYS = {"seed", "horizon", "multiplier"}


def _is_num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


def validate_settings(s):
    """Return a list of problems (empty if usable). Same rules and wording as the app."""
    if not isinstance(s, dict) or s.get("format") != FORMAT:
        return ["These are not Save or sink settings."]
    problems = []
    for key, (lo, hi) in LIMITS.items():
        v = s.get(key)
        if not _is_num(v) or not lo <= v <= hi or (key in INTEGER_KEYS and not float(v).is_integer()):
            problems.append("%s must be a %snumber from %s to %s." % (
                key, "whole " if key in INTEGER_KEYS else "", lo, hi))
    if s.get("rescue") not in RESCUE_MODES:
        problems.append("rescue must be one of: overdrawn, near-limit, never.")
    if s.get("preset") is not None and not isinstance(s["preset"], str):
        problems.append("preset must be text.")
    rules = s.get("rules")
    if not isinstance(rules, dict):
        problems.append("rules must be an object.")
        return problems
    for rule, fields in RULE_LIMITS.items():
        r = rules.get(rule)
        if not isinstance(r, dict):
            problems.append("rules.%s is missing." % rule)
            continue
        for key, (lo, hi) in fields.items():
            v = r.get(key)
            if not _is_num(v) or not lo <= v <= hi or (key in INTEGER_KEYS and not float(v).is_integer()):
                problems.append("rules.%s.%s must be a %snumber from %s to %s." % (
                    rule, key, "whole " if key in INTEGER_KEYS else "", lo, hi))
    if isinstance(rules.get("smart"), dict) and not isinstance(rules["smart"].get("knowsBills"), bool):
        problems.append("rules.smart.knowsBills must be true or false.")
    return problems


# ---------------------------------------------------------------------------
# Random numbers (identical to the app)
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


_A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
_B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]


def inv_norm(p):
    """Acklam's inverse normal CDF (relative error below 1.2e-9)."""
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


def _normal(rnd):
    u = rnd()
    return inv_norm(min(max(u, 1e-12), 1 - 1e-12))


def pennies(pounds):
    """Pounds to whole pennies, rounding halves up."""
    return int(math.floor(pounds * 100 + 0.5))


# ---------------------------------------------------------------------------
# A year of money in and out
# ---------------------------------------------------------------------------

def generate_year(s, seed):
    """Every payment in and out for one synthetic year. Each day is {"in": [...], "out": [...]}.

    Payments are [label, pennies] in and [label, pennies, kind] out, where kind is
    "card" (card purchases, which round-ups use) or "debit" (rent and bills).
    """
    rnd = mulberry32(int(seed) & _M32)
    days = [{"in": [], "out": []} for _ in range(DAYS)]
    loan = pennies(s["loanPerTerm"])
    if loan > 0:
        for d in LOAN_DAYS:
            days[d]["in"].append(["Student loan", loan])
    rent, bills = pennies(s["rent"]), pennies(s["bills"])
    for m0 in MONTH_STARTS:
        if rent > 0:
            days[m0]["out"].append(["Rent", rent, "debit"])
        if bills > 0:
            days[m0 + BILL_DAY]["out"].append(["Phone and subscriptions", bills, "debit"])
    v = s["spendVariability"]
    for d in range(DAYS):
        wd = d % 7
        if wd == 4:
            hours = max(0.0, s["hoursPerWeek"] * (1 + s["hoursVariability"] * _normal(rnd)))
            pay = pennies(hours * s["hourlyPay"])
            if pay > 0:
                days[d]["in"].append(["Wages", pay])
        k = 1 + math.floor(rnd() * 3)
        total = s["everydayPerWeek"] / 7 * math.exp(v * _normal(rnd) - v * v / 2)
        weights = [0.2 + rnd() for _ in range(k)]
        wsum = 0.0
        for w in weights:
            wsum += w
        for w in weights:
            amount = pennies(total * w / wsum)
            if amount > 0:
                days[d]["out"].append(["Everyday spending", amount, "card"])
        if wd == 4 or wd == 5:
            social = pennies(s["socialPerWeek"] / 2 * math.exp(v * _normal(rnd) - v * v / 2))
            if social > 0:
                days[d]["out"].append(["Going out", social, "card"])
    for i, (_, length) in enumerate(MONTHS):
        if rnd() < s["shockChance"]:
            day = MONTH_STARTS[i] + math.floor(rnd() * length)
            amount = pennies(s["shockSize"] * math.exp(SHOCK_SPREAD * _normal(rnd)))
            if amount > 0:
                days[day]["out"].append(["Unexpected cost", amount, "card"])
    return days


def scheduled_out(s, d):
    """Rent and bills due on day d (what a saver that 'knows your bills' can see coming)."""
    total = 0
    if d in MONTH_STARTS:
        total += pennies(s["rent"])
    if d - BILL_DAY in MONTH_STARTS:
        total += pennies(s["bills"])
    return total


def next_loan_day(d):
    """The next day a student loan payment is due after day d (or the end of the year)."""
    for x in LOAN_DAYS:
        if x > d:
            return x
    return DAYS


def rescue_point(s):
    """The balance (pennies) below which the person moves money back from savings, or None."""
    if s["rescue"] == "overdrawn":
        return 0
    if s["rescue"] == "near-limit":
        return -max(0, pennies(s["overdraftLimit"]) - 10000)
    return None


# ---------------------------------------------------------------------------
# Running one rule through one year
# ---------------------------------------------------------------------------

def simulate(s, days, rule, trace=False):
    """Run one saving rule through one year of payments. Returns the totals (and, optionally, every day)."""
    limit = pennies(s["overdraftLimit"])
    od_rate = s["overdraftRate"] / 100 / 365
    save_rate = s["savingsRate"] / 100 / 365
    rescue_at = rescue_point(s)
    p = s["rules"].get(rule, {})
    bal = pennies(s["startBalance"])
    pot = 0
    acc_od = acc_save = 0.0
    out = {"savedIn": 0, "rescued": 0, "rescues": 0, "daysOverdrawn": 0, "daysBeyond": 0,
           "overdraftCost": 0, "interestEarned": 0, "lowest": bal, "potPeak": 0, "potDays": 0}
    history = []            # card spending per day, for the smart saver's forecast
    daily = [] if trace else None
    sched = [scheduled_out(s, d) for d in range(DAYS)] if rule in ("smart", "planner") else None
    month_end = set(st + length - 1 for st, (_, length) in zip(MONTH_STARTS, MONTHS))
    for d in range(DAYS):
        day = days[d]
        income = 0
        for _, amount in day["in"]:
            income += amount
        bal += income
        card = 0
        roundups = 0
        for _, amount, kind in day["out"]:
            bal -= amount
            if kind == "card":
                card += amount
                roundups += (100 - amount % 100) % 100
        history.append(card)

        move = 0
        if rule == "roundup":
            move = roundups * int(p["multiplier"])
        elif rule == "weekly":
            if d % 7 == 0:
                move = pennies(p["amount"])
        elif rule == "payday":
            move = int(math.floor(income * p["percent"] / 100 + 0.5))
        elif rule == "smart" and d >= LEARNING_DAYS:
            window = history[max(0, d - 27):d + 1]
            spent = 0
            for x in window:
                spent += x
            expected = spent / len(window) * p["horizon"]
            if p["knowsBills"]:
                for k in range(d + 1, min(DAYS, d + 1 + int(p["horizon"]))):
                    expected += sched[k]
            safe = bal - expected - pennies(p["buffer"])
            if safe > 0:
                move = min(int(math.floor(safe * p["aggressiveness"])), pennies(p["cap"]))
        elif rule == "planner" and d >= LEARNING_DAYS:
            # Like the smart saver, but it budgets for every day until the next loan payment, or until
            # 31 August after the last one (wages are left out, to be safe), and for every bill due by then.
            window = history[max(0, d - 27):d + 1]
            spent = 0
            for x in window:
                spent += x
            nxt = next_loan_day(d)
            expected = spent / len(window) * (min(nxt, DAYS - 1) - d)
            for k in range(d + 1, min(DAYS, nxt + 1)):
                expected += sched[k]
            safe = bal - expected - pennies(p["buffer"])
            if safe > 0:
                move = min(int(math.floor(safe * p["aggressiveness"])), pennies(p["cap"]))
        if move > 0:
            bal -= move
            pot += move
            out["savedIn"] += move

        rescued_today = 0
        if rescue_at is not None and bal < rescue_at and pot > 0:
            back = min(pot, -bal)
            pot -= back
            bal += back
            rescued_today = back
            out["rescued"] += back
            out["rescues"] += 1

        if bal < -limit:
            acc_od += (-limit - bal) * od_rate
            out["daysBeyond"] += 1
        if bal < 0:
            out["daysOverdrawn"] += 1
        acc_save += pot * save_rate
        if d in month_end:
            charge = int(math.floor(acc_od + 0.5))
            earned = int(math.floor(acc_save + 0.5))
            bal -= charge
            pot += earned
            out["overdraftCost"] += charge
            out["interestEarned"] += earned
            acc_od = acc_save = 0.0
        out["lowest"] = min(out["lowest"], bal)
        out["potPeak"] = max(out["potPeak"], pot)
        out["potDays"] += pot
        if trace:
            daily.append({"balance": bal, "pot": pot, "moved": move, "rescued": rescued_today})
    out["endBalance"] = bal
    out["endPot"] = pot
    out["averagePot"] = out.pop("potDays") / DAYS
    if trace:
        out["daily"] = daily
    return out


# ---------------------------------------------------------------------------
# Many years: the stress test
# ---------------------------------------------------------------------------

def year_seed(seed, k):
    return (int(seed) * 7919 + k) & _M32


def percentile(sorted_values, q):
    n = len(sorted_values)
    h = (n - 1) * q
    lo = math.floor(h)
    if lo + 1 >= n:
        return sorted_values[-1]
    return sorted_values[lo] + (h - lo) * (sorted_values[lo + 1] - sorted_values[lo])


def _sum(xs):
    total = 0
    for x in xs:
        total += x
    return total


def _mean(xs):
    total = 0.0
    for x in xs:
        total += x
    return total / len(xs)


def came_back(results):
    """Share of everything that went into savings (money moved in plus interest) that was moved back out."""
    went_in = _sum([x["savedIn"] + x["interestEarned"] for x in results])
    return _sum([x["rescued"] for x in results]) / went_in if went_in > 0 else 0.0


def stress_test(s, years=200, rules=None):
    """Run every rule through the same set of synthetic years and summarise. Amounts in pennies."""
    problems = validate_settings(s)
    if problems:
        raise ValueError(problems[0])
    if not _is_num(years) or years != int(years) or not 1 <= years <= 20000:
        raise ValueError("years must be a whole number from 1 to 20000")
    years = int(years)
    rules = rules or RULES
    runs = {r: [] for r in rules}
    for k in range(years):
        days = generate_year(s, year_seed(s["seed"], k))
        base = None
        for r in rules:
            res = simulate(s, days, r)
            if r == "none":
                base = res
            runs[r].append(res)
        if base is None:
            base = simulate(s, days, "none")
        for r in rules:
            res = runs[r][-1]
            res["net"] = (res["endBalance"] + res["endPot"]) - (base["endBalance"] + base["endPot"])
    out = {}
    for r in rules:
        rs = runs[r]
        pots = sorted(x["endPot"] for x in rs)
        nets = sorted(x["net"] for x in rs)
        saved = sorted(x["savedIn"] for x in rs)
        out[r] = {
            "years": years,
            "savedIn": {"p10": percentile(saved, 0.1), "p50": percentile(saved, 0.5), "p90": percentile(saved, 0.9)},
            "endPot": {"p10": percentile(pots, 0.1), "p50": percentile(pots, 0.5), "p90": percentile(pots, 0.9)},
            "net": {"p10": percentile(nets, 0.1), "p50": percentile(nets, 0.5), "p90": percentile(nets, 0.9),
                    "mean": _mean(nets)},
            "beyondChance": sum(1 for x in rs if x["daysBeyond"] > 0) / years,
            "meanDaysBeyond": _mean([x["daysBeyond"] for x in rs]),
            "meanDaysOverdrawn": _mean([x["daysOverdrawn"] for x in rs]),
            "meanRescues": _mean([x["rescues"] for x in rs]),
            "meanRescued": _mean([x["rescued"] for x in rs]),
            "meanOverdraftCost": _mean([x["overdraftCost"] for x in rs]),
            "meanInterest": _mean([x["interestEarned"] for x in rs]),
            "meanLowest": _mean([x["lowest"] for x in rs]),
            "meanAveragePot": _mean([x["averagePot"] for x in rs]),
            "cameBack": came_back(rs),
        }
    return out


SWEEP_DEFAULTS = {
    "smart": {"horizon": (7, 14, 28, 56, 90), "buffer": (0, 100, 200, 400, 800)},
    "planner": {"buffer": (0, 100, 200, 400, 800), "aggressiveness": (0.25, 0.5, 0.75, 1)},
}


def _beats(o, r):
    """True when sweep row o is at least as good as row r on every count and better on one."""
    keys = (("net", 1), ("beyondChance", -1), ("meanRescues", -1))
    if o is r or any((o[k] - r[k]) * sign < 0 for k, sign in keys):
        return False
    return any((o[k] - r[k]) * sign > 0 for k, sign in keys)


def sweep(s, rule="smart", dials=None, years=200):
    """Try every combination of two dials of a forecasting rule over the same synthetic years.

    dials maps exactly two of the rule's settings to the values to try, for example
    {"horizon": [7, 14, 28], "buffer": [0, 200]}. Returns one row per combination (amounts in pennies).
    A row is on the "frontier" when no other row is at least as good on all three counts (better off in a
    typical year, fewer years past the overdraft limit, fewer raids) and better on at least one. "Set aside"
    is not one of the counts: a big pot means little if the current account is deep in paid overdraft.
    """
    problems = validate_settings(s)
    if problems:
        raise ValueError(problems[0])
    if rule not in SWEEP_DEFAULTS:
        raise ValueError("rule must be one of: %s" % ", ".join(SWEEP_DEFAULTS))
    if not _is_num(years) or years != int(years) or not 1 <= years <= 20000:
        raise ValueError("years must be a whole number from 1 to 20000")
    years = int(years)
    dials = SWEEP_DEFAULTS[rule] if dials is None else dials
    if not isinstance(dials, dict) or len(dials) != 2:
        raise ValueError("choose exactly two dials to sweep")
    for key, values in dials.items():
        if key not in RULE_LIMITS[rule]:
            raise ValueError("%s has no dial called %s; try: %s" % (rule, key, ", ".join(RULE_LIMITS[rule])))
        lo, hi = RULE_LIMITS[rule][key]
        whole = key in INTEGER_KEYS
        if (not isinstance(values, (list, tuple)) or not values
                or any(not _is_num(v) or not lo <= v <= hi or (whole and v != int(v)) for v in values)):
            raise ValueError("%s values must be %snumbers from %s to %s" % (key, "whole " if whole else "", lo, hi))
    (ka, va), (kb, vb) = dials.items()
    if len(va) * len(vb) * years > 2000000:
        raise ValueError("that sweep is too large; use fewer values or fewer years")
    combos = [(a, b) for a in va for b in vb]
    trial = []
    for a, b in combos:
        t = json.loads(json.dumps(s))
        t["rules"][rule][ka] = a
        t["rules"][rule][kb] = b
        trial.append(t)
    runs = [[] for _ in combos]
    beyond_without = 0
    days_without = []
    for k in range(years):
        days = generate_year(s, year_seed(s["seed"], k))
        base = simulate(s, days, "none")
        beyond_without += 1 if base["daysBeyond"] > 0 else 0
        days_without.append(base["daysBeyond"])
        for i, t in enumerate(trial):
            res = simulate(t, days, rule)
            res["net"] = (res["endBalance"] + res["endPot"]) - (base["endBalance"] + base["endPot"])
            runs[i].append(res)
    rows = []
    for (a, b), rs in zip(combos, runs):
        rows.append({
            ka: a,
            kb: b,
            "endPot": percentile(sorted(x["endPot"] for x in rs), 0.5),
            "savedIn": percentile(sorted(x["savedIn"] for x in rs), 0.5),
            "net": percentile(sorted(x["net"] for x in rs), 0.5),
            "beyondChance": sum(1 for x in rs if x["daysBeyond"] > 0) / years,
            "meanDaysBeyond": _mean([x["daysBeyond"] for x in rs]),
            "meanRescues": _mean([x["rescues"] for x in rs]),
            "cameBack": came_back(rs),
        })
    for r in rows:
        r["frontier"] = not any(_beats(o, r) for o in rows)
    return {"rule": rule, "dials": [ka, kb], "years": years, "beyondWithoutSaving": beyond_without / years,
            "daysBeyondWithoutSaving": _mean(days_without),
            "rows": rows}


# ---------------------------------------------------------------------------
# Money formatting (identical to the app)
# ---------------------------------------------------------------------------

def money(p, signed=False):
    """Pennies as pounds: 123456 -> '£1,234.56', whole pounds from £1,000 up."""
    if p is None or not _is_num(p):
        return "n/a"
    v = int(math.floor(abs(p) + 0.5))
    sign = "-" if p < 0 and v != 0 else ("+" if signed and v != 0 else "")
    pounds, pence = divmod(v, 100)
    if pounds >= 1000:
        pounds = int(math.floor(abs(p) / 100 + 0.5))
        return "%s£%s" % (sign, "{:,}".format(pounds))
    return "%s£%d.%02d" % (sign, pounds, pence)


# ---------------------------------------------------------------------------
# Settings links (identical to the app)
# ---------------------------------------------------------------------------

LINK_MISSING = "That link does not contain Save or sink settings."
LINK_DAMAGED = "That link is damaged: the settings in it could not be read."
_LINK = re.compile(r"(?:^|[#&?])s=([A-Za-z0-9_-]+)")


def _js_numbers(x):
    """Whole-number floats as ints, so the JSON matches what the app writes (4.0 becomes 4)."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, dict):
        return {k: _js_numbers(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_js_numbers(v) for v in x]
    return x


def encode_link(s):
    """Settings as a link fragment: s= then the JSON in URL-safe base64 without padding."""
    raw = json.dumps(_js_numbers(s), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "s=" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _no_constants(name):
    raise ValueError(name)


def decode_link(text):
    """Accepts a whole link from the app or just its fragment. Returns the settings (not yet validated)."""
    m = _LINK.search(str(text).strip(" \t\r\n"))
    if not m:
        raise ValueError(LINK_MISSING)
    b = m.group(1)
    try:
        if len(b) % 4 == 1:
            raise ValueError(b)
        raw = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))
        return json.loads(raw.decode("utf-8"), parse_constant=_no_constants)
    except (ValueError, RecursionError):
        raise ValueError(LINK_DAMAGED) from None
