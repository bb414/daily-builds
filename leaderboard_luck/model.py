"""Simulated trading competitions: how much of a leaderboard is skill, and how much risk pays?

A line-for-line port of the MODEL block in ``app/index.html``, using the same random number
generator, so the same settings and seed give the same answer in both. ``tests/test_agreement.py``
checks that.

Each team runs a strategy with a true Sharpe ratio (its skill) at a chosen volatility (its risk).
Daily returns are ``mean + sd * z``, where every team's ``z`` shares a common market move (the
correlation) and, optionally, fat tails. Rivals' skill is drawn around zero; a share of them are
"gamblers" who run several times the usual risk. Your team's result is worked out at your chosen
risk and at twenty other levels on exactly the same luck, so the curves compare like with like.
"""

from __future__ import annotations

import math

DAYS_PER_YEAR = 252
RULES = ("return", "sharpe", "drawdown")
RULE_LABELS = {
    "return": "Highest return",
    "sharpe": "Highest Sharpe ratio",
    "drawdown": "Highest return, out if the drawdown limit is breached",
}

DEFAULTS = {
    "teams": 30,
    "days": 20,
    "skillSpread": 0.75,
    "fieldVol": 0.2,
    "gamblers": 0.2,
    "gamblerMultiple": 3,
    "correlation": 0.3,
    "fatTails": False,
    "rule": "return",
    "drawdownLimit": 0.15,
    "yourSharpe": 1,
    "yourVol": 0.2,
    "sims": 2000,
    "seed": 1,
}

# (min, max, whole number?)
RANGES = {
    "teams": (3, 100, True),
    "days": (5, 250, True),
    "skillSpread": (0, 2, False),
    "fieldVol": (0.05, 0.5, False),
    "gamblers": (0, 0.8, False),
    "gamblerMultiple": (1, 4, False),
    "correlation": (0, 0.9, False),
    "drawdownLimit": (0.02, 0.6, False),
    "yourSharpe": (-1, 3, False),
    "yourVol": (0.02, 1, False),
    "sims": (100, 20000, True),
    "seed": (0, 4294967295, True),
}

VOL_GRID = [i / 20 for i in range(1, 21)]

JUMP_PROB = 0.05
JUMP_SIZE = 3
JUMP_NORM = math.sqrt(1 + JUMP_PROB * (JUMP_SIZE * JUMP_SIZE - 1))

VOL_JITTER = 0.25

MASK = 0xFFFFFFFF


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def round_half_up(x: float) -> int:
    """Like JavaScript's Math.round (Python's round() rounds halves to even)."""
    return math.floor(x + 0.5)


def normalise(params: dict | None = None) -> dict:
    src = params or {}
    out = {}
    for key, default in DEFAULTS.items():
        v = src.get(key)
        if v is None:
            v = default
        if key == "rule":
            if v not in RULES:
                raise ValueError(f"rule must be one of {', '.join(RULES)}")
            out[key] = v
            continue
        if key == "fatTails":
            if not isinstance(v, bool):
                raise ValueError("fatTails must be true or false")
            out[key] = v
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{key} must be a finite number")
        lo, hi, whole = RANGES[key]
        v = clamp(v, lo, hi)
        out[key] = round_half_up(v) if whole else v
    return out


# ---------- random numbers (identical to the browser app) ----------

def _imul(a: int, b: int) -> int:
    """JavaScript's Math.imul, returned as an unsigned 32-bit integer."""
    return ((a & MASK) * (b & MASK)) & MASK


class Rng:
    """mulberry32 uniforms and polar-method normals, exactly as in the browser app."""

    def __init__(self, seed: int):
        self.t = seed & MASK
        self.spare = None

    def uniform(self) -> float:
        self.t = (self.t + 0x6D2B79F5) & MASK
        t = self.t
        r = _imul(t ^ (t >> 15), 1 | t)
        r = ((r + _imul(r ^ (r >> 7), 61 | r)) & MASK) ^ r
        return ((r ^ (r >> 14)) & MASK) / 4294967296

    def normal(self) -> float:
        if self.spare is not None:
            s0 = self.spare
            self.spare = None
            return s0
        while True:
            u = 2 * self.uniform() - 1
            v = 2 * self.uniform() - 1
            s = u * u + v * v
            if 0 < s < 1:
                break
        f = math.sqrt(-2 * math.log(s) / s)
        self.spare = v * f
        return u * f


def competition_seed(seed: int, k: int) -> int:
    return (seed * 1000003 + k) % 4294967296


def shock(g: Rng, fat: bool) -> float:
    z = g.normal()
    if not fat:
        return z
    return (JUMP_SIZE if g.uniform() < JUMP_PROB else 1) * z / JUMP_NORM


# ---------- one team's account ----------

class Account:
    __slots__ = ("wealth", "peak", "max_dd", "total", "total_sq", "bust", "path")

    def __init__(self, record: bool):
        self.wealth = 1.0
        self.peak = 1.0
        self.max_dd = 0.0
        self.total = 0.0
        self.total_sq = 0.0
        self.bust = False
        self.path = [1.0] if record else None

    def step(self, r: float) -> None:
        if not self.bust:
            self.total += r
            self.total_sq += r * r
            self.wealth *= 1 + r
            if self.wealth <= 0:
                self.wealth = 0.0
                self.bust = True
            if self.wealth > self.peak:
                self.peak = self.wealth
            dd = 1 - self.wealth / self.peak
            if dd > self.max_dd:
                self.max_dd = dd
        if self.path is not None:
            self.path.append(self.wealth)


def finish(acc: Account, p: dict) -> dict:
    n = p["days"]
    mean = acc.total / n
    variance = (acc.total_sq - n * mean * mean) / (n - 1) if n > 1 else 0.0
    sharpe = mean / math.sqrt(variance) * math.sqrt(DAYS_PER_YEAR) if variance > 0 else 0.0
    out = acc.bust or (p["rule"] == "drawdown" and acc.max_dd > p["drawdownLimit"])
    ret = acc.wealth - 1
    return {
        "ret": ret,
        "sharpe": sharpe,
        "maxDD": acc.max_dd,
        "bust": acc.bust,
        "out": out,
        "score": -math.inf if out else (sharpe if p["rule"] == "sharpe" else ret),
    }


def daily_mean(sharpe: float, vol: float) -> float:
    return sharpe * vol / DAYS_PER_YEAR


def daily_sd(vol: float) -> float:
    return vol / math.sqrt(DAYS_PER_YEAR)


def run_you(p: dict, z: list[float], vol: float, record: bool = False) -> dict:
    acc = Account(record)
    mu = daily_mean(p["yourSharpe"], vol)
    sd = daily_sd(vol)
    for zt in z:
        acc.step(mu + sd * zt)
    f = finish(acc, p)
    if record:
        f["path"] = acc.path
    return f


def run_competition(p: dict, k: int, record: bool = False) -> dict:
    """One whole competition: the rivals' results and your daily shocks."""
    g = Rng(competition_seed(p["seed"], k))
    n_rivals = p["teams"] - 1
    n_gamblers = round_half_up(p["gamblers"] * n_rivals)
    a = math.sqrt(p["correlation"])
    b = math.sqrt(1 - p["correlation"])
    fat = p["fatTails"]
    rivals = []
    for j in range(n_rivals):
        gambler = j < n_gamblers
        z1 = g.normal()
        z2 = g.normal()
        rivals.append({
            "gambler": gambler,
            "sharpe": p["skillSpread"] * z1,
            "vol": p["fieldVol"] * (p["gamblerMultiple"] if gambler else 1) * math.exp(VOL_JITTER * z2),
        })
    market = [shock(g, fat) for _ in range(p["days"])]
    for rv in rivals:
        acc = Account(record)
        mu = daily_mean(rv["sharpe"], rv["vol"])
        sd = daily_sd(rv["vol"])
        for t in range(p["days"]):
            acc.step(mu + sd * (a * market[t] + b * shock(g, fat)))
        f = finish(acc, p)
        rv.update({"ret": f["ret"], "realisedSharpe": f["sharpe"], "maxDD": f["maxDD"], "bust": f["bust"],
                   "out": f["out"], "score": f["score"]})
        if record:
            rv["path"] = acc.path
    your_z = [a * market[t] + b * shock(g, fat) for t in range(p["days"])]
    return {"rivals": rivals, "yourZ": your_z}


def place_you(rivals: list[dict], you: dict) -> float:
    in_rivals = 0
    better = 0
    for rv in rivals:
        if not rv["out"]:
            in_rivals += 1
            if rv["score"] > you["score"]:
                better += 1
    if you["out"]:
        return (in_rivals + 1 + len(rivals) + 1) / 2
    return better + 1


# ---------- many competitions ----------

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
            bb = z + 0.65
            bb = z + 4 / bb
            bb = z + 3 / bb
            bb = z + 2 / bb
            bb = z + 1 / bb
            c = e / bb / 2.506628274631
    return 1 - c if x > 0 else c


def skill_percentile(p: dict) -> float:
    """Share of rivals whose true Sharpe ratio is below yours."""
    if p["skillSpread"] == 0:
        return 1.0 if p["yourSharpe"] > 0 else (0.5 if p["yourSharpe"] == 0 else 0.0)
    return norm_cdf(p["yourSharpe"] / p["skillSpread"])


def _tally() -> dict:
    return {"wins": 0, "top3": 0, "rankSum": 0.0, "out": 0}


def _add(t: dict, rank: float, out: bool) -> None:
    if not out and rank == 1:
        t["wins"] += 1
    if not out and rank <= 3:
        t["top3"] += 1
    t["rankSum"] += rank
    if out:
        t["out"] += 1


def _rates(t: dict, n: int) -> dict:
    return {"pWin": t["wins"] / n, "pTop3": t["top3"] / n, "meanRank": t["rankSum"] / n, "pOut": t["out"] / n}


class Run:
    """A run that can be advanced in chunks and read at any time, like createRun in the app."""

    def __init__(self, params: dict | None = None):
        self.params = normalise(params)
        self.done = 0
        self.main = _tally()
        self.grid = [_tally() for _ in VOL_GRID]
        self.winners = {"you": 0, "gambler": 0, "steady": 0, "none": 0, "noEdge": 0, "mostSkilled": 0}

    def advance(self, count: int) -> bool:
        stop = min(self.params["sims"], self.done + count)
        for k in range(self.done, stop):
            self._one(k)
        self.done = stop
        return self.done >= self.params["sims"]

    def _one(self, k: int) -> None:
        p = self.params
        c = run_competition(p, k)
        you = run_you(p, c["yourZ"], p["yourVol"])
        _add(self.main, place_you(c["rivals"], you), you["out"])
        for i, vol in enumerate(VOL_GRID):
            alt = run_you(p, c["yourZ"], vol)
            _add(self.grid[i], place_you(c["rivals"], alt), alt["out"])
        best = None if you["out"] else {"score": you["score"], "sharpe": p["yourSharpe"], "kind": "you", "index": -1}
        top_skill = p["yourSharpe"]
        top_index = -1
        for j, rv in enumerate(c["rivals"]):
            if rv["sharpe"] > top_skill:
                top_skill = rv["sharpe"]
                top_index = j
            if not rv["out"] and (best is None or rv["score"] > best["score"]):
                best = {"score": rv["score"], "sharpe": rv["sharpe"],
                        "kind": "gambler" if rv["gambler"] else "steady", "index": j}
        w = self.winners
        if best is None:
            w["none"] += 1
        else:
            w[best["kind"]] += 1
            if best["sharpe"] <= 0:
                w["noEdge"] += 1
            if best["index"] == top_index:
                w["mostSkilled"] += 1

    def result(self) -> dict:
        n = max(1, self.done)
        curve = []
        for i, vol in enumerate(VOL_GRID):
            r = _rates(self.grid[i], n)
            r["vol"] = vol
            curve.append(r)
        best = curve[0]
        for pt in curve:
            if pt["pWin"] > best["pWin"]:
                best = pt
        return {
            "params": self.params,
            "sims": self.done,
            "you": _rates(self.main, n),
            "curve": curve,
            "bestVol": best["vol"],
            "bestPWin": best["pWin"],
            "winners": {k: v / n for k, v in self.winners.items()},
            "skillPercentile": skill_percentile(self.params),
        }


def simulate(params: dict | None = None) -> dict:
    run = Run(params)
    run.advance(run.params["sims"])
    return run.result()


def sample_competition(params: dict | None, k: int) -> list[dict]:
    """One competition in full, ranked. Competition k is the same as competition k in simulate()."""
    p = normalise(params)
    c = run_competition(p, k, record=True)
    you = run_you(p, c["yourZ"], p["yourVol"], record=True)
    teams = [{"name": "Your team", "you": True, "gambler": False, "sharpe": p["yourSharpe"], "vol": p["yourVol"],
              "ret": you["ret"], "realisedSharpe": you["sharpe"], "maxDD": you["maxDD"], "bust": you["bust"],
              "out": you["out"], "score": you["score"], "path": you["path"]}]
    for j, rv in enumerate(c["rivals"]):
        teams.append({"name": f"Team {j + 2}", "you": False, "gambler": rv["gambler"], "sharpe": rv["sharpe"],
                      "vol": rv["vol"], "ret": rv["ret"], "realisedSharpe": rv["realisedSharpe"],
                      "maxDD": rv["maxDD"], "bust": rv["bust"], "out": rv["out"], "score": rv["score"],
                      "path": rv["path"]})
    order = sorted(range(len(teams)), key=lambda i: (-teams[i]["score"], i))
    ranked = []
    for pos, i in enumerate(order):
        t = teams[i]
        t["rank"] = pos + 1
        ranked.append(t)
    return ranked
