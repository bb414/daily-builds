"""Clean hours model: a line-by-line port of the browser app's MODEL block.

The browser app (app/index.html) and this module must give identical numbers;
tests/test_parity.py runs both and compares them. Only +, -, *, /, sqrt and
floor are used on floating-point values, so both languages round identically.
"""

import math

DAYS = 364  # 52 weeks; day 0 is a Monday
HOURS = DAYS * 24  # 8,736 hours in the synthetic year
SQRT3 = 1.7320508075688772
WIND_RHO = 0.985  # hour-to-hour persistence of the weather
MAX_CF = 0.93
_M32 = 0xFFFFFFFF


# ---------- random numbers (mulberry32, seeded and reproducible) ----------
def _imul(a, b):
    return (a * b) & _M32


def mulberry32(seed):
    state = [int(seed) & _M32]

    def nxt():
        a = (state[0] + 0x6D2B79F5) & _M32
        state[0] = a
        t = _imul(a ^ (a >> 15), a | 1)
        t = t ^ ((t + _imul(t ^ (t >> 7), t | 61)) & _M32)
        return (t ^ (t >> 14)) / 4294967296

    return nxt


def mix_seed(a, b):
    h = (int(a) & _M32) ^ _imul((int(b) + 0x9E3779B9) & _M32, 0x85EBCA6B)
    h = _imul(h ^ (h >> 16), 0x7FEB352D)
    h = _imul(h ^ (h >> 15), 0x846CA68B)
    return h ^ (h >> 16)


def normal(r):
    """Approximately normal: sum of four uniforms, rescaled to unit variance."""
    return (r() + r() + r() + r() - 2) * SQRT3


def clamp(x, lo, hi):
    return min(max(x, lo), hi)


def seasonal(table, day):
    """Smoothly interpolate a 12-value monthly table for a day of the year."""
    pos = (day + 0.5) * 12 / DAYS - 0.5
    i0 = math.floor(pos)
    f = pos - i0
    a = table[((i0 % 12) + 12) % 12]
    b = table[(((i0 + 1) % 12) + 12) % 12]
    return a + (b - a) * f


# ---------- three invented grids ----------
UK_SHAPE = [0.80, 0.77, 0.75, 0.74, 0.75, 0.79, 0.88, 0.98, 1.03, 1.04, 1.04, 1.03,
            1.02, 1.01, 1.00, 1.01, 1.06, 1.13, 1.14, 1.10, 1.04, 0.97, 0.90, 0.84]
COOLING_SHAPE = [0.82, 0.79, 0.77, 0.76, 0.77, 0.80, 0.86, 0.92, 0.97, 1.01, 1.05, 1.09,
                 1.12, 1.14, 1.15, 1.15, 1.14, 1.13, 1.12, 1.09, 1.03, 0.96, 0.90, 0.85]
NORTH_DAYLEN = [8, 9.8, 11.8, 13.9, 15.7, 16.6, 16.2, 14.6, 12.6, 10.5, 8.6, 7.6]
NORTH_SUN = [0.22, 0.35, 0.52, 0.68, 0.78, 0.82, 0.80, 0.72, 0.58, 0.40, 0.26, 0.19]

PRESETS = {
    "windy": {
        "label": "Windy island",
        "blurb": "Plenty of wind, some solar and nuclear, with gas setting the price most hours.",
        "demandGW": 31,
        "demandSeason": [1.16, 1.13, 1.06, 0.98, 0.92, 0.88, 0.87, 0.88, 0.92, 1.00, 1.10, 1.16],
        "dayShape": UK_SHAPE,
        "nuclearGW": 4.5, "windGW": 27, "solarGW": 16,
        "windMean": [0.44, 0.43, 0.40, 0.35, 0.30, 0.27, 0.26, 0.27, 0.32, 0.38, 0.42, 0.44],
        "windSpread": 0.28,
        "sunPeak": NORTH_SUN, "dayLength": NORTH_DAYLEN,
        "minThermalGW": 3,
        "blocks": [
            {"key": "ccgt", "name": "Gas, combined cycle", "gw": 34, "lo": 340, "hi": 420},
            {"key": "ocgt", "name": "Gas peakers", "gw": 10, "lo": 560, "hi": 660},
        ],
        "reserveIntensity": 800,
    },
    "coal": {
        "label": "Coal before gas",
        "blurb": "Cheap coal runs first and gas sits on top, so the plant that changes at night is often coal.",
        "demandGW": 31,
        "demandSeason": [1.14, 1.12, 1.05, 0.98, 0.93, 0.90, 0.89, 0.89, 0.93, 1.00, 1.08, 1.14],
        "dayShape": UK_SHAPE,
        "nuclearGW": 5, "windGW": 13, "solarGW": 8,
        "windMean": [0.40, 0.38, 0.35, 0.30, 0.26, 0.23, 0.22, 0.24, 0.28, 0.33, 0.37, 0.40],
        "windSpread": 0.22,
        "sunPeak": NORTH_SUN, "dayLength": NORTH_DAYLEN,
        "minThermalGW": 6,
        "blocks": [
            {"key": "coal", "name": "Coal", "gw": 14, "lo": 870, "hi": 1020},
            {"key": "ccgt", "name": "Gas, combined cycle", "gw": 26, "lo": 350, "hi": 420},
            {"key": "ocgt", "name": "Gas peakers", "gw": 8, "lo": 560, "hi": 660},
        ],
        "reserveIntensity": 800,
    },
    "sunny": {
        "label": "Sunny grid",
        "blurb": "A big solar fleet meets an afternoon cooling peak: midday looks clean on average, but gas still answers extra demand.",
        "demandGW": 30,
        "demandSeason": [0.95, 0.93, 0.92, 0.93, 0.98, 1.08, 1.15, 1.14, 1.04, 0.96, 0.93, 0.96],
        "dayShape": COOLING_SHAPE,
        "nuclearGW": 2, "windGW": 8, "solarGW": 40,
        "windMean": [0.32, 0.31, 0.30, 0.28, 0.26, 0.25, 0.25, 0.25, 0.26, 0.28, 0.30, 0.32],
        "windSpread": 0.20,
        "sunPeak": [0.50, 0.58, 0.68, 0.76, 0.82, 0.85, 0.86, 0.82, 0.74, 0.64, 0.54, 0.48],
        "dayLength": [10, 10.8, 11.9, 13, 13.9, 14.4, 14.2, 13.4, 12.3, 11.2, 10.3, 9.8],
        "minThermalGW": 3,
        "blocks": [
            {"key": "ccgt", "name": "Gas, combined cycle", "gw": 34, "lo": 340, "hi": 420},
            {"key": "ocgt", "name": "Gas peakers", "gw": 10, "lo": 560, "hi": 660},
        ],
        "reserveIntensity": 800,
    },
}

# ---------- an invented fleet of AI compute jobs ----------
DEFAULT_JOBS = [
    {"name": "Live inference", "mw": 3, "hours": 24, "everyDays": 1, "firstDay": 0, "releaseHour": 0, "window": 24, "pausable": False},
    {"name": "Nightly embedding refresh", "mw": 2.5, "hours": 4, "everyDays": 1, "firstDay": 0, "releaseHour": 18, "window": 14, "pausable": True},
    {"name": "Data backfill", "mw": 1, "hours": 8, "everyDays": 1, "firstDay": 0, "releaseHour": 2, "window": 22, "pausable": False},
    {"name": "Weekly fine-tune", "mw": 6, "hours": 18, "everyDays": 7, "firstDay": 0, "releaseHour": 9, "window": 96, "pausable": True},
    {"name": "Evaluation suite", "mw": 1.5, "hours": 6, "everyDays": 7, "firstDay": 2, "releaseHour": 12, "window": 36, "pausable": False},
    {"name": "Four-weekly retrain", "mw": 12, "hours": 60, "everyDays": 28, "firstDay": 3, "releaseHour": 8, "window": 168, "pausable": True},
]

POLICIES = [
    {"key": "now", "label": "Run on release", "short": "Run now"},
    {"key": "night", "label": "Midnight rule", "short": "Midnight"},
    {"key": "avg", "label": "Forecast of average intensity", "short": "Avg forecast"},
    {"key": "marg", "label": "Forecast of marginal intensity", "short": "Marg forecast"},
    {"key": "oracle", "label": "Hindsight best", "short": "Hindsight"},
]
POLICY_KEYS = [p["key"] for p in POLICIES]

DEFAULT_CONFIG = {
    "preset": "windy", "seed": 1, "windScale": 1, "solarScale": 1,
    "forecastError": 1, "slack": 1, "jobs": DEFAULT_JOBS,
}


def margin_labels(p):
    return ["Spare clean power"] + [b["name"] for b in p["blocks"]] + ["Emergency supply"]


def margin_keys(p):
    return ["surplus"] + [b["key"] for b in p["blocks"]] + ["reserve"]


# ---------- merit-order dispatch for one hour ----------
def dispatch(p, D, W, S):
    """D, W, S in GW. Intensities in gCO2/kWh. Marginal code: 0 = spare clean
    power (curtailment), 1..n = thermal block, n + 1 = emergency supply."""
    N, M, R = p["nuclearGW"], p["minThermalGW"], W + S
    residual = D - N - M
    nuclear = N
    if residual <= R:
        used = residual if residual > 0 else 0
        curtail = R - used
        wind_used = used * W / R if R > 0 else 0
        solar_used = used - wind_used
        if residual < 0:
            nuclear = N + residual
        thermal = M
    else:
        curtail = 0
        wind_used, solar_used = W, S
        thermal = D - N - R
    rem, emis, marg, code, gen = thermal, 0, -1, -1, []
    for i, b in enumerate(p["blocks"]):
        g = rem if rem < b["gw"] else b["gw"]
        if g < 0:
            g = 0
        gen.append(g)
        emis += g * (b["lo"] + (b["hi"] - b["lo"]) * g / (2 * b["gw"]))
        if code < 0 and rem <= b["gw"]:
            marg = b["lo"] + (b["hi"] - b["lo"]) * g / b["gw"]
            code = i + 1
        rem -= g
    shortfall = rem if rem > 0 else 0
    if shortfall > 0:
        emis += shortfall * p["reserveIntensity"]
        marg = p["reserveIntensity"]
        code = len(p["blocks"]) + 1
    if curtail > 0:
        marg, code = 0, 0
    return {
        "nuclear": nuclear, "wind": wind_used, "solar": solar_used, "curtail": curtail,
        "thermal": gen, "shortfall": shortfall, "emis": emis,
        "avg": emis / D, "marg": marg, "code": code,
    }


# ---------- a synthetic year of weather, demand and dispatch ----------
def simulate_grid(cfg):
    p = PRESETS[cfg["preset"]]
    r = mulberry32(mix_seed(cfg["seed"], 1))
    wind_gw = p["windGW"] * cfg["windScale"]
    solar_gw = p["solarGW"] * cfg["solarScale"]
    g = {
        "preset": p, "windGW": wind_gw, "solarGW": solar_gw,
        "demand": [], "windCf": [], "sunShape": [], "clear": [],
        "wind": [], "solar": [], "nuclear": [], "curtail": [], "thermal": [], "shortfall": [],
        "avg": [], "marg": [], "code": [],
    }
    x = 0
    innov = math.sqrt(1 - WIND_RHO * WIND_RHO)
    for d in range(DAYS):
        day_noise = 1 + 0.025 * normal(r)
        c = clamp(0.62 + 0.25 * normal(r), 0.08, 1)
        g["clear"].append(c)
        season = seasonal(p["demandSeason"], d)
        wm = seasonal(p["windMean"], d)
        sp = seasonal(p["sunPeak"], d)
        dl = seasonal(p["dayLength"], d)
        weekend = 0.93 if (d % 7) >= 5 else 1
        for h in range(24):
            x = WIND_RHO * x + innov * normal(r)
            cf = clamp(wm + p["windSpread"] * x, 0, MAX_CF)
            u = (h + 0.5 - 12) / (dl / 2)
            shape = 1 - u * u
            if shape < 0:
                shape = 0
            D = p["demandGW"] * season * p["dayShape"][h] * weekend * day_noise
            ss = sp * shape
            W = wind_gw * cf
            S = solar_gw * ss * c
            o = dispatch(p, D, W, S)
            g["demand"].append(D)
            g["windCf"].append(cf)
            g["sunShape"].append(ss)
            g["wind"].append(o["wind"])
            g["solar"].append(o["solar"])
            g["nuclear"].append(o["nuclear"])
            g["curtail"].append(o["curtail"])
            g["thermal"].append(o["thermal"])
            g["shortfall"].append(o["shortfall"])
            g["avg"].append(o["avg"])
            g["marg"].append(o["marg"])
            g["code"].append(o["code"])
    return g


# ---------- forecasts made when a job is released ----------
def forecast(g, cfg, release, length):
    """Errors grow with lead time: wind and demand drift as slowly reverting
    random walks, and cloudiness is wrong by more for each day further ahead."""
    p, sk = g["preset"], cfg["forecastError"]
    r = mulberry32(mix_seed(cfg["seed"], 1000003 + release))
    ew = ed = es = 0
    last_day = -1
    rel_day = release // 24
    avg, marg = [], []
    for k in range(length):
        t = release + k
        ew = 0.985 * ew + 0.013 * sk * normal(r)
        ed = 0.98 * ed + 0.003 * sk * normal(r)
        day = t // 24
        if day != last_day:
            sd = 0.05 * (1 + day - rel_day)
            if sd > 0.2:
                sd = 0.2
            es = sd * sk * normal(r)
            last_day = day
        cf = clamp(g["windCf"][t] + ew, 0, MAX_CF)
        cl = clamp(g["clear"][day] + es, 0.08, 1)
        o = dispatch(p, g["demand"][t] * (1 + ed), g["windGW"] * cf, g["solarGW"] * g["sunShape"][t] * cl)
        avg.append(o["avg"])
        marg.append(o["marg"])
    return {"avg": avg, "marg": marg}


# ---------- turning jobs into dated instances ----------
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _whole(v):
    return _num(v) and math.floor(v) == v


def validate_jobs(jobs):
    errors = []
    if not jobs:
        errors.append("Add at least one job.")
    for i, j in enumerate(jobs or []):
        n = "Job %d%s" % (i + 1, " (%s)" % j["name"] if j.get("name") else "")
        if not _num(j.get("mw")) or j["mw"] <= 0 or j["mw"] > 1000:
            errors.append(n + ": power must be above 0 and at most 1,000 MW.")
        if not _whole(j.get("hours")) or j["hours"] < 1 or j["hours"] > 336:
            errors.append(n + ": run time must be a whole number of hours from 1 to 336.")
        if not _whole(j.get("everyDays")) or j["everyDays"] < 1 or j["everyDays"] > 364:
            errors.append(n + ": repeat interval must be 1 to 364 days.")
        if not _whole(j.get("firstDay")) or j["firstDay"] < 0 or j["firstDay"] > 363:
            errors.append(n + ": first day must be 0 to 363.")
        if not _whole(j.get("releaseHour")) or j["releaseHour"] < 0 or j["releaseHour"] > 23:
            errors.append(n + ": ready time must be an hour from 0 to 23.")
        if (not _whole(j.get("window")) or not _num(j.get("hours"))
                or j["window"] < j["hours"] or j["window"] > 672):
            errors.append(n + ": the window must be at least the run time and at most 672 hours.")
    return errors


def scaled_window(job, slack):
    return job["hours"] + math.floor((job["window"] - job["hours"]) * slack + 0.5)


def build_instances(jobs, slack):
    out = []
    for ji, j in enumerate(jobs):
        win = scaled_window(j, slack)
        day = j["firstDay"]
        while day < DAYS:
            rel = day * 24 + j["releaseHour"]
            if rel + win > HOURS:
                break
            out.append({"job": ji, "release": rel, "hours": j["hours"], "window": win,
                        "mw": j["mw"], "pausable": bool(j["pausable"])})
            day += j["everyDays"]
    return out


# ---------- choosing hours ----------
def choose_hours(values, hours, window, pausable):
    """values[k] is the signal k hours after release. Returns offsets from release."""
    if window <= hours:
        return list(range(hours))
    if pausable:
        idx = sorted(range(window), key=lambda k: (values[k], k))
        return sorted(idx[:hours])
    best, best_sum = -1, 0
    for s in range(window - hours + 1):
        total = 0
        for k in range(s, s + hours):
            total += values[k]
        if best < 0 or total < best_sum:
            best, best_sum = s, total
    return list(range(best, best + hours))


def midnight_hours(inst):
    start = 0
    for k in range(inst["window"] - inst["hours"] + 1):
        if (inst["release"] + k) % 24 == 0:
            start = k
            break
    return list(range(start, start + inst["hours"]))


# ---------- the full run ----------
def run(cfg, grid=None):
    p = PRESETS[cfg["preset"]]
    g = grid or simulate_grid(cfg)
    inst = build_instances(cfg["jobs"], cfg["slack"])
    n_codes = len(p["blocks"]) + 2

    need = {}
    for it in inst:
        if it["window"] > it["hours"] and need.get(it["release"], 0) < it["window"]:
            need[it["release"]] = it["window"]
    fc = {rel: forecast(g, cfg, rel, length) for rel, length in need.items()}

    res = {}
    for key in POLICY_KEYS:
        res[key] = {"mwh": 0, "reported": 0, "real": 0, "delay": 0, "mix": [0] * n_codes,
                    "perJob": [{"mwh": 0, "reported": 0, "real": 0, "delay": 0, "n": 0} for _ in cfg["jobs"]],
                    "placements": []}

    for it in inst:
        f = fc.get(it["release"])
        for key in POLICY_KEYS:
            if key == "now" or it["window"] <= it["hours"]:
                offs = choose_hours(None, it["hours"], it["hours"], False)
            elif key == "night":
                offs = midnight_hours(it)
            elif key == "avg":
                offs = choose_hours(f["avg"], it["hours"], it["window"], it["pausable"])
            elif key == "marg":
                offs = choose_hours(f["marg"], it["hours"], it["window"], it["pausable"])
            else:
                offs = choose_hours(g["marg"][it["release"]:it["release"] + it["window"]],
                                    it["hours"], it["window"], it["pausable"])
            R = res[key]
            J = R["perJob"][it["job"]]
            rep = real = 0
            for o in offs:
                t = it["release"] + o
                rep += it["mw"] * g["avg"][t] / 1000
                real += it["mw"] * g["marg"][t] / 1000
                R["mix"][g["code"][t]] += it["mw"]
            delay = offs[-1] + 1 - it["hours"]
            R["mwh"] += it["mw"] * it["hours"]
            R["reported"] += rep
            R["real"] += real
            R["delay"] += delay
            J["mwh"] += it["mw"] * it["hours"]
            J["reported"] += rep
            J["real"] += real
            J["delay"] += delay
            J["n"] += 1
            R["placements"].append({"job": it["job"], "release": it["release"], "offsets": offs})

    base = res["now"]
    for key in POLICY_KEYS:
        R = res[key]
        R["reportedSavedT"] = base["reported"] - R["reported"]
        R["realSavedT"] = base["real"] - R["real"]
        R["reportedSaving"] = R["reportedSavedT"] / base["reported"] if base["reported"] > 0 else 0
        R["realSaving"] = R["realSavedT"] / base["real"] if base["real"] > 0 else 0
        R["meanDelay"] = R["delay"] / len(inst) if inst else 0
    for key in POLICY_KEYS:
        res[key]["verdict"] = verdict(res[key], base)
    return {"config": cfg, "grid": g, "instances": len(inst), "policies": res, "summary": grid_summary(g)}


def verdict(R, base):
    """How the reported saving compares with the real one, in tonnes."""
    tol = 0.002 * base["real"]
    rep, real = R["reportedSavedT"], R["realSavedT"]
    if abs(rep) <= tol and abs(real) <= tol:
        return "nothing"
    if real < -tol and rep > tol:
        return "backfires"
    if real < -tol:
        return "worse"
    if rep > real * 1.25:
        return "overstates"
    if real > rep * 1.25:
        return "understates"
    return "matches"


def grid_summary(g):
    n = len(g["avg"])
    sa = sm = sd = se = curtail_h = curtail_e = renew = 0
    hours_by_code = [0] * (len(g["preset"]["blocks"]) + 2)
    for t in range(n):
        sa += g["avg"][t]
        sm += g["marg"][t]
        sd += g["demand"][t]
        se += g["avg"][t] * g["demand"][t]
        if g["curtail"][t] > 0:
            curtail_h += 1
        curtail_e += g["curtail"][t]
        renew += g["wind"][t] + g["solar"][t]
        hours_by_code[g["code"][t]] += 1
    return {
        "meanAvg": sa / n, "meanMarg": sm / n, "demandTWh": sd / 1000,
        "weightedAvg": se / sd, "curtailShare": curtail_h / n, "curtailTWh": curtail_e / 1000,
        "renewableShare": renew / sd, "hoursByCode": hours_by_code,
    }
