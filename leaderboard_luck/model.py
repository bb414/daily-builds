"""Simulated trading competitions: how much of a leaderboard is skill, and how much risk pays?

A line-for-line port of the MODEL block in ``app/index.html``, using the same random number
generator, so the same settings and seed give the same answer in both. ``tests/test_agreement.py``
checks that.

Each team runs a strategy with a true Sharpe ratio (its skill) at a chosen volatility (its risk).
Daily returns are ``mean + sd * z``, where every team's ``z`` shares a common market move (the
correlation) and, optionally, fat tails. Rivals' skill is drawn around zero; a share of them are
"gamblers" who run several times the usual risk. Your team's result is worked out at your chosen
risk and at twenty levels from 5% to 100% on exactly the same luck, so the curves compare like with like.
"""

from __future__ import annotations

import math

DAYS_PER_YEAR = 252
RULES = ("return", "sharpe", "drawdown", "sortino", "calmar")
RULE_LABELS = {
    "return": "Highest return",
    "sharpe": "Highest Sharpe ratio",
    "drawdown": "Highest return, out if the drawdown limit is breached",
    "sortino": "Highest Sortino ratio",
    "calmar": "Highest return over worst drawdown",
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
    "catchUp": False,
    "catchUpVol": 0.8,
    "checkpoint": 0.75,
    "rivalsCatchUp": 0,
    "leverageCap": False,
    "volCap": 0.4,
    "cost": 0,
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
    "catchUpVol": (0.02, 1, False),
    "checkpoint": (0.25, 0.9, False),
    "rivalsCatchUp": (0, 1, False),
    "volCap": (0.05, 1, False),
    "cost": (0, 0.5, False),
    "sims": (100, 20000, True),
    "seed": (0, 4294967295, True),
}

VOL_GRID = [i / 20 for i in range(1, 21)]

JUMP_PROB = 0.05
JUMP_SIZE = 3
JUMP_NORM = math.sqrt(1 + JUMP_PROB * (JUMP_SIZE * JUMP_SIZE - 1))

VOL_JITTER = 0.25

# "Going for broke": a team outside the top three at the checkpoint switches to higher risk.
CATCH_TOP = 3

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
        if key in ("fatTails", "catchUp", "leverageCap"):
            if not isinstance(v, bool):
                raise ValueError(f"{key} must be true or false")
            out[key] = v
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{key} must be a finite number")
        lo, hi, whole = RANGES[key]
        v = clamp(v, lo, hi)
        out[key] = round_half_up(v) if whole else v
    return out


# ---------- random numbers (identical to the browser app) ----------

class Rng:
    """mulberry32 uniforms and polar-method normals, exactly as in the browser app.

    The 32-bit multiplications are written out inline (each is JavaScript's Math.imul) because
    this generator is the slowest part of the Python simulation.
    """

    __slots__ = ("t", "spare")

    def __init__(self, seed: int):
        self.t = seed & MASK
        self.spare = None

    def uniform(self) -> float:
        t = (self.t + 0x6D2B79F5) & MASK
        self.t = t
        r = ((t ^ (t >> 15)) * (1 | t)) & MASK
        r = ((r + (((r ^ (r >> 7)) * (61 | r)) & MASK)) & MASK) ^ r
        return ((r ^ (r >> 14)) & MASK) / 4294967296

    def normal(self) -> float:
        if self.spare is not None:
            s0 = self.spare
            self.spare = None
            return s0
        t = self.t
        while True:
            t = (t + 0x6D2B79F5) & MASK
            r = ((t ^ (t >> 15)) * (1 | t)) & MASK
            r = ((r + (((r ^ (r >> 7)) * (61 | r)) & MASK)) & MASK) ^ r
            u = 2 * (((r ^ (r >> 14)) & MASK) / 4294967296) - 1
            t = (t + 0x6D2B79F5) & MASK
            r = ((t ^ (t >> 15)) * (1 | t)) & MASK
            r = ((r + (((r ^ (r >> 7)) * (61 | r)) & MASK)) & MASK) ^ r
            v = 2 * (((r ^ (r >> 14)) & MASK) / 4294967296) - 1
            s = u * u + v * v
            if 0 < s < 1:
                break
        self.t = t
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
    __slots__ = ("wealth", "peak", "max_dd", "total", "total_sq", "down_sq", "bust", "path")

    def __init__(self, record: bool):
        self.wealth = 1.0
        self.peak = 1.0
        self.max_dd = 0.0
        self.total = 0.0
        self.total_sq = 0.0
        self.down_sq = 0.0
        self.bust = False
        self.path = [1.0] if record else None

    def step(self, r: float) -> None:
        if not self.bust:
            self.total += r
            self.total_sq += r * r
            if r < 0:
                self.down_sq += r * r
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
        "score": rule_score(acc, p, n),
    }


def daily_mean(sharpe: float, vol: float, cost: float) -> float:
    """The cost of risk is a return lost per year for each 100% of volatility run, so it lowers every
    team's Sharpe ratio by the same amount but costs a high-risk team the most."""
    return (sharpe - cost) * vol / DAYS_PER_YEAR


def risk_of(p: dict, vol: float) -> float:
    """The volatility a team actually runs: what it wants, unless the rules cap it."""
    return p["volCap"] if p["leverageCap"] and vol > p["volCap"] else vol


def daily_sd(vol: float) -> float:
    return vol / math.sqrt(DAYS_PER_YEAR)


# Where the Sortino ratio or return over worst drawdown would divide by zero (no losing day, or no
# fall at all) a tiny floor is used instead, so that team ranks first, by return.
SCORE_FLOOR = 1e-9


def rule_score(acc: Account, p: dict, n: int) -> float:
    """A team's score on the leaderboard after n days."""
    if acc.bust or (p["rule"] == "drawdown" and acc.max_dd > p["drawdownLimit"]):
        return -math.inf
    if p["rule"] in ("return", "drawdown"):
        return acc.wealth - 1
    if p["rule"] == "calmar":
        return (acc.wealth - 1) / max(SCORE_FLOOR, acc.max_dd)
    mean = acc.total / n
    if p["rule"] == "sortino":
        return mean / max(SCORE_FLOOR, math.sqrt(acc.down_sq / n)) * math.sqrt(DAYS_PER_YEAR)
    variance = (acc.total_sq - n * mean * mean) / (n - 1) if n > 1 else 0.0
    return mean / math.sqrt(variance) * math.sqrt(DAYS_PER_YEAR) if variance > 0 else 0.0


def interim_score(acc: Account, p: dict, n: int) -> float:
    return rule_score(acc, p, n)


def checkpoint_day(p: dict) -> int:
    return clamp(round_half_up(p["checkpoint"] * p["days"]), 1, p["days"] - 1)


def ahead_of(scores: list[float], mine: float, skip: int) -> int:
    return sum(1 for i, sc in enumerate(scores) if i != skip and sc > mine)


def run_you(p: dict, c: dict, vol: float, record: bool = False) -> dict:
    """Your team at a given starting risk, switching risk at the checkpoint if going for broke."""
    acc = Account(record)
    vol = risk_of(p, vol)
    mu = daily_mean(p["yourSharpe"], vol, p["cost"])
    sd = daily_sd(vol)
    cp = checkpoint_day(p)
    switch_day = None
    for t, zt in enumerate(c["yourZ"]):
        if t == cp and p["catchUp"]:
            mine = interim_score(acc, p, cp)
            if mine > -math.inf and ahead_of(c["checkpointScores"], mine, -1) >= CATCH_TOP:
                mu = daily_mean(p["yourSharpe"], risk_of(p, p["catchUpVol"]), p["cost"])
                sd = daily_sd(risk_of(p, p["catchUpVol"]))
                switch_day = cp
        acc.step(mu + sd * zt)
    f = finish(acc, p)
    f["switchDay"] = switch_day
    if record:
        f["path"] = acc.path
    return f


def run_competition(p: dict, k: int, record: bool = False) -> dict:
    """One whole competition: the rivals' results, their standings at the checkpoint, and your
    daily shocks, so your result can be worked out at any level of risk on the same luck."""
    g = Rng(competition_seed(p["seed"], k))
    n_rivals = p["teams"] - 1
    n_gamblers = round_half_up(p["gamblers"] * n_rivals)
    n_catch = round_half_up(p["rivalsCatchUp"] * (n_rivals - n_gamblers))
    a = math.sqrt(p["correlation"])
    b = math.sqrt(1 - p["correlation"])
    fat = p["fatTails"]
    days = p["days"]
    rivals = []
    for j in range(n_rivals):
        gambler = j < n_gamblers
        z1 = g.normal()
        z2 = g.normal()
        rivals.append({
            "gambler": gambler,
            "catcher": (not gambler) and j - n_gamblers < n_catch,
            "sharpe": p["skillSpread"] * z1,
            "vol": risk_of(p, p["fieldVol"] * (p["gamblerMultiple"] if gambler else 1) * math.exp(VOL_JITTER * z2)),
        })
    market = [shock(g, fat) for _ in range(days)]
    shocks = [[shock(g, fat) for _ in range(days)] for _ in rivals]
    your_z = [a * market[t] + b * shock(g, fat) for t in range(days)]

    accs = [Account(record) for _ in rivals]
    mus = [daily_mean(rv["sharpe"], rv["vol"], p["cost"]) for rv in rivals]
    sds = [daily_sd(rv["vol"]) for rv in rivals]
    switch_days = [None] * len(rivals)
    cp = checkpoint_day(p)
    checkpoint_scores = None
    for day in range(days):
        if day == cp:
            checkpoint_scores = [interim_score(acc, p, cp) for acc in accs]
            for i, rv in enumerate(rivals):
                if (rv["catcher"] and checkpoint_scores[i] > -math.inf
                        and ahead_of(checkpoint_scores, checkpoint_scores[i], i) >= CATCH_TOP):
                    mus[i] = daily_mean(rv["sharpe"], risk_of(p, rv["vol"] * p["gamblerMultiple"]), p["cost"])
                    sds[i] = daily_sd(risk_of(p, rv["vol"] * p["gamblerMultiple"]))
                    switch_days[i] = cp
        m = a * market[day]
        for i in range(len(rivals)):
            accs[i].step(mus[i] + sds[i] * (m + b * shocks[i][day]))
    for i, rv in enumerate(rivals):
        f = finish(accs[i], p)
        rv.update({"ret": f["ret"], "realisedSharpe": f["sharpe"], "maxDD": f["maxDD"], "bust": f["bust"],
                   "out": f["out"], "score": f["score"], "switchDay": switch_days[i]})
        if record:
            rv["path"] = accs[i].path
    return {"rivals": rivals, "yourZ": your_z, "checkpointScores": checkpoint_scores}


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
    return {"wins": 0, "top3": 0, "rankSum": 0.0, "out": 0, "switched": 0}


def _add(t: dict, rank: float, you: dict) -> None:
    if not you["out"] and rank == 1:
        t["wins"] += 1
    if not you["out"] and rank <= 3:
        t["top3"] += 1
    t["rankSum"] += rank
    if you["out"]:
        t["out"] += 1
    if you["switchDay"] is not None:
        t["switched"] += 1


def _rates(t: dict, n: int) -> dict:
    return {"pWin": t["wins"] / n, "pTop3": t["top3"] / n, "meanRank": t["rankSum"] / n, "pOut": t["out"] / n,
            "pSwitched": t["switched"] / n}


class Run:
    """A run that can be advanced in chunks and read at any time, like createRun in the app."""

    def __init__(self, params: dict | None = None):
        self.params = normalise(params)
        self.done = 0
        self.main = _tally()
        self.grid = [_tally() for _ in VOL_GRID]
        self.winners = {"you": 0, "gambler": 0, "steady": 0, "none": 0, "noEdge": 0, "mostSkilled": 0, "switched": 0}

    def advance(self, count: int) -> bool:
        stop = min(self.params["sims"], self.done + count)
        for k in range(self.done, stop):
            self._one(k)
        self.done = stop
        return self.done >= self.params["sims"]

    def _one(self, k: int) -> None:
        p = self.params
        c = run_competition(p, k)
        you = run_you(p, c, p["yourVol"])
        _add(self.main, place_you(c["rivals"], you), you)
        for i, vol in enumerate(VOL_GRID):
            alt = run_you(p, c, vol)
            _add(self.grid[i], place_you(c["rivals"], alt), alt)
        best = None if you["out"] else {"score": you["score"], "sharpe": p["yourSharpe"], "kind": "you",
                                        "switched": you["switchDay"] is not None}
        top_skill = p["yourSharpe"]
        for j, rv in enumerate(c["rivals"]):
            if rv["sharpe"] > top_skill:
                top_skill = rv["sharpe"]
            if not rv["out"] and (best is None or rv["score"] > best["score"]):
                best = {"score": rv["score"], "sharpe": rv["sharpe"],
                        "kind": "gambler" if rv["gambler"] else "steady",
                        "switched": rv["switchDay"] is not None}
        w = self.winners
        if best is None:
            w["none"] += 1
        else:
            w[best["kind"]] += 1
            if best["sharpe"] <= 0:
                w["noEdge"] += 1
            if best["sharpe"] == top_skill:
                w["mostSkilled"] += 1
            if best["switched"]:
                w["switched"] += 1

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
            "bestVol": risk_of(self.params, best["vol"]),
            "bestPWin": best["pWin"],
            "winners": {k: v / n for k, v in self.winners.items()},
            "skillPercentile": skill_percentile(self.params),
        }


def simulate(params: dict | None = None) -> dict:
    run = Run(params)
    run.advance(run.params["sims"])
    return run.result()


# ---------- how long before skill shows? ----------

DURATIONS = [5, 10, 20, 40, 60, 120, 250]


def average_ranks(values: list[float]) -> list[float]:
    """Ranks with ties sharing the average place (rank 1 = highest value)."""
    order = sorted(range(len(values)), key=lambda i: (-values[i], i))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx = 0.0
    my = 0.0
    for i in range(n):
        mx += xs[i]
        my += ys[i]
    mx /= n
    my /= n
    sxy = sxx = syy = 0.0
    for k in range(n):
        sxy += (xs[k] - mx) * (ys[k] - my)
        sxx += (xs[k] - mx) * (xs[k] - mx)
        syy += (ys[k] - my) * (ys[k] - my)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def skill_job(params: dict | None, rule: str, days: int, sims_each: int = 300) -> dict:
    """One scoring rule at one challenge length: how often the most skilled team wins, how
    closely final places follow true skill (rank correlation), and who the winners were."""
    p = {**normalise(params), "rule": rule, "days": days}
    n = max(1, round_half_up(sims_each))
    best = no_edge = gambler = 0
    corr = 0.0
    for k in range(n):
        c = run_competition(p, k)
        you = run_you(p, c, p["yourVol"])
        skills = [p["yourSharpe"]] + [rv["sharpe"] for rv in c["rivals"]]
        scores = [you["score"]] + [rv["score"] for rv in c["rivals"]]
        corr += correlation(average_ranks(skills), average_ranks(scores))
        top_skill = skills[0]
        for i in range(1, len(skills)):
            if skills[i] > top_skill:
                top_skill = skills[i]
        winner = -1
        for j, sc in enumerate(scores):
            if sc > -math.inf and (winner < 0 or sc > scores[winner]):
                winner = j
        if winner >= 0:
            if skills[winner] == top_skill:
                best += 1
            if skills[winner] <= 0:
                no_edge += 1
            if winner > 0 and c["rivals"][winner - 1]["gambler"]:
                gambler += 1
    return {"rule": rule, "days": days, "pBestWins": best / n, "rankCorr": corr / n,
            "pNoEdgeWins": no_edge / n, "pGamblerWins": gambler / n}


def skill_by_length(params: dict | None = None, sims_each: int = 300, workers: int = 1) -> list[dict]:
    """skill_job for every rule and length, in the same order as the browser app's
    createSkillRun. With workers > 1 the jobs run in parallel processes; the answer is the same."""
    p = normalise(params)
    jobs = [(p, rule, days, sims_each) for rule in RULES for days in DURATIONS]
    if workers <= 1:
        return [skill_job(*job) for job in jobs]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(skill_job, *zip(*jobs)))


def sample_competition(params: dict | None, k: int) -> list[dict]:
    """One competition in full, ranked. Competition k is the same as competition k in simulate()."""
    p = normalise(params)
    c = run_competition(p, k, record=True)
    you = run_you(p, c, p["yourVol"], record=True)
    # Rivals are numbered in a shuffled order (from a separate generator, so results are
    # untouched); otherwise the gamblers would always be the lowest-numbered teams.
    namer = Rng((competition_seed(p["seed"], k) ^ 0x5BD1E995) & MASK)
    numbers = [j + 2 for j in range(len(c["rivals"]))]
    for i in range(len(numbers) - 1, 0, -1):
        swap = math.floor(namer.uniform() * (i + 1))
        numbers[i], numbers[swap] = numbers[swap], numbers[i]
    teams = [{"name": "Your team", "you": True, "gambler": False, "sharpe": p["yourSharpe"], "vol": risk_of(p, p["yourVol"]),
              "ret": you["ret"], "realisedSharpe": you["sharpe"], "maxDD": you["maxDD"], "bust": you["bust"],
              "out": you["out"], "score": you["score"], "switchDay": you["switchDay"], "path": you["path"]}]
    for j, rv in enumerate(c["rivals"]):
        teams.append({"name": f"Team {numbers[j]}", "you": False, "gambler": rv["gambler"], "sharpe": rv["sharpe"],
                      "vol": rv["vol"], "ret": rv["ret"], "realisedSharpe": rv["realisedSharpe"],
                      "maxDD": rv["maxDD"], "bust": rv["bust"], "out": rv["out"], "score": rv["score"],
                      "switchDay": rv["switchDay"], "path": rv["path"]})
    order = sorted(range(len(teams)), key=lambda i: (-teams[i]["score"], i))
    ranked = []
    for pos, i in enumerate(order):
        t = teams[i]
        t["rank"] = pos + 1
        ranked.append(t)
    return ranked
