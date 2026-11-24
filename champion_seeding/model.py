"""The Champion Seeding model, ported line for line from the browser app.

The random number generator (Mulberry32) and the order of every random draw match
``app/index.html``, and the model avoids library maths functions in its random
decisions, so both versions give identical results. ``tests/test_parity.py`` checks this.
"""

import math
import re

CONSTANTS = {
    "thresholdLow": 0.5,
    "thresholdSpan": 1.0,
    "holdShare": 0.5,
    "bandLow": 0.1,
    "bandHigh": 0.9,
    "networkSalt": 0x51ED27,
    "pickSalt": 0x2F6B4A,
}

# key, group, min, max, default, integer?
PARAMS = [
    ("champions", "champions", 1, 30, 8, True),
    ("championWeight", "champions", 1, 5, 2, True),
    ("socialProof", "tool", 0.0, 0.6, 0.35, False),
    ("peerPull", "tool", 0.01, 0.4, 0.06, False),
    ("spontaneous", "tool", 0.0, 0.03, 0.001, False),
    ("fit", "tool", 0.3, 1.0, 0.8, False),
    ("lapse", "tool", 0.0, 0.3, 0.1, False),
    ("people", "org", 40, 300, 180, True),
    ("teams", "org", 2, 30, 12, True),
    ("departments", "org", 1, 6, 3, True),
    ("tiesTeam", "org", 1.0, 12.0, 5.0, False),
    ("tiesDept", "org", 0.0, 6.0, 1.2, False),
    ("tiesOrg", "org", 0.0, 4.0, 0.4, False),
    ("weeks", "run", 8, 104, 52, True),
    ("runs", "run", 10, 100, 40, True),
    ("seed", "run", 1, 9999, 7, True),
]

PARAM_LABELS = {
    "champions": "Number of champions",
    "championWeight": "Champion influence",
    "socialProof": "Social proof needed",
    "peerPull": "Peer pull",
    "spontaneous": "Trying it unprompted",
    "fit": "Jobs it suits",
    "lapse": "Dropping it",
    "people": "People",
    "teams": "Teams",
    "departments": "Departments",
    "tiesTeam": "Close contacts in the team",
    "tiesDept": "Contacts in other teams",
    "tiesOrg": "Contacts in other departments",
    "weeks": "Weeks",
    "runs": "Rollouts per strategy",
    "seed": "Organisation seed",
}

STRATEGY_KEYS = ["random", "hubs", "bridges", "cluster", "spread"]
STRATEGY_LABELS = {
    "random": "Volunteers",
    "hubs": "Best connected",
    "bridges": "Bridge builders",
    "cluster": "One team first",
    "spread": "One per team",
}

PRESETS = {
    "assistant": {
        "label": "AI assistant that changes how a team works",
        "params": {"socialProof": 0.35, "peerPull": 0.06, "spontaneous": 0.001, "lapse": 0.1, "fit": 0.8, "strategy": "hubs"},
    },
    "plugin": {
        "label": "Handy add-on that spreads by word of mouth",
        "params": {"socialProof": 0, "peerPull": 0.05, "spontaneous": 0.002, "lapse": 0.03, "fit": 0.7, "strategy": "hubs"},
    },
    "silos": {
        "label": "Siloed organisation",
        "params": {"socialProof": 0.3, "peerPull": 0.06, "spontaneous": 0.001, "lapse": 0.1, "fit": 0.8, "tiesOrg": 0.1,
                   "tiesDept": 0.5, "strategy": "cluster"},
    },
}

DEFAULTS = {"strategy": "hubs"}
DEFAULTS.update({key: default for key, _g, _lo, _hi, default, _i in PARAMS})

MASK = 0xFFFFFFFF


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _imul(a, b):
    return (a * b) & MASK


class Rng:
    """Mulberry32, matching the JavaScript version bit for bit."""

    def __init__(self, seed):
        self.a = seed & MASK

    def uniform(self):
        self.a = (self.a + 0x6D2B79F5) & MASK
        t = self.a
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296


def mix_seed(seed, i):
    h = ((seed & MASK) ^ _imul(i + 1, 0x9E3779B1)) & MASK
    h = _imul(h ^ (h >> 16), 0x85EBCA6B)
    h = _imul(h ^ (h >> 13), 0xC2B2AE35)
    return (h ^ (h >> 16)) & MASK


# Accepts numbers and plain decimal strings only; anything else falls back to the default.
NUMBER_PATTERN = re.compile(r"[ \t\r\n]*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?[ \t\r\n]*")


def to_number(raw):
    if isinstance(raw, bool):
        return math.nan
    try:
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str) and NUMBER_PATTERN.fullmatch(raw):
            return float(raw)
    except OverflowError:
        pass
    return math.nan


def normalise_params(src=None):
    src = src if isinstance(src, dict) else {}
    out = {}
    for key, _group, lo, hi, default, is_int in PARAMS:
        v = to_number(src.get(key))
        if not math.isfinite(v):
            v = default
        v = clamp(v, lo, hi)
        if is_int:
            v = int(math.floor(v + 0.5))
        out[key] = v
    # Every team needs at least three people, and every department at least one team.
    out["teams"] = min(out["teams"], out["people"] // 3)
    out["departments"] = min(out["departments"], out["teams"])
    strategy = src.get("strategy")
    out["strategy"] = strategy if strategy in STRATEGY_KEYS else DEFAULTS["strategy"]
    return out


def preset_params(key):
    out = dict(DEFAULTS)
    if key in PRESETS:
        out.update(PRESETS[key]["params"])
    return normalise_params(out)


# ---- The organisation ----

def build_network(src=None):
    """A synthetic organisation: dense ties inside teams, fewer across teams, fewest across departments."""
    p = normalise_params(src)
    n, t_count, d_count = p["people"], p["teams"], p["departments"]
    rng = Rng(mix_seed(p["seed"], CONSTANTS["networkSalt"]))
    team, team_size = [], []
    base, extra = n // t_count, n % t_count
    for t in range(t_count):
        size = base + (1 if t < extra else 0)
        team_size.append(size)
        team.extend([t] * size)
    dept = [t % d_count for t in range(t_count)]
    dept_size = [0] * d_count
    teams_in_dept = [0] * d_count
    for t in range(t_count):
        teams_in_dept[t % d_count] += 1
        dept_size[t % d_count] += team_size[t]
    p_team = [min(1, p["tiesTeam"] / (s - 1)) for s in team_size]
    p_dept = []
    for k, s in enumerate(dept_size):
        others = s - s / teams_in_dept[k]
        p_dept.append(min(1, p["tiesDept"] / others) if others > 0 else 0)
    other_depts = n - n / d_count
    p_org = min(1, p["tiesOrg"] / other_depts) if other_depts > 0 else 0
    adj = [[] for _ in range(n)]
    for i in range(n):
        ti = team[i]
        for j in range(i + 1, n):
            tj = team[j]
            if ti == tj:
                prob = p_team[ti]
            elif dept[ti] == dept[tj]:
                prob = p_dept[dept[ti]]
            else:
                prob = p_org
            if rng.uniform() < prob:
                adj[i].append(j)
                adj[j].append(i)
    for i in range(n):
        if not adj[i]:
            for j in range(n):
                if j != i and team[j] == team[i]:
                    adj[i].append(j)
                    adj[j].append(i)
                    break
    for lst in adj:
        lst.sort()
    need = [CONSTANTS["thresholdLow"] + CONSTANTS["thresholdSpan"] * rng.uniform() for _ in range(n)]
    suit = [rng.uniform() for _ in range(n)]
    return finish_network(adj, team, need, suit, dept)


def finish_network(adj, team, need, suit, dept=None):
    """Degrees, ties, betweenness and team summaries, shared by synthetic and loaded networks."""
    n = len(adj)
    t_count = max(team) + 1 if team else 0
    degree = [len(a) for a in adj]
    outside = [sum(1 for w in a if team[w] != team[v]) for v, a in enumerate(adj)]
    edges = sum(degree) / 2
    team_size = [0] * t_count
    team_ties = [0] * t_count
    for i in range(n):
        team_size[team[i]] += 1
        for w in adj[i]:
            if w > i and team[w] == team[i]:
                team_ties[team[i]] += 1
    outside_total = sum(outside)
    return {
        "size": n, "teams": t_count, "adj": adj, "team": team, "dept": dept, "need": need, "suit": suit,
        "degree": degree, "outside": outside, "edges": edges, "teamSize": team_size, "teamTies": team_ties,
        "betweenness": betweenness(adj),
        "meanDegree": 2 * edges / n if n else 0, "outsideShare": outside_total / (2 * edges) if edges else 0,
    }


def betweenness(adj):
    """Brandes' algorithm (unweighted, undirected; each pair counted twice), same order as the JavaScript."""
    n = len(adj)
    cb = [0.0] * n
    for s in range(n):
        stack = []
        preds = [[] for _ in range(n)]
        sigma = [0] * n
        dist = [-1] * n
        delta = [0.0] * n
        sigma[s] = 1
        dist[s] = 0
        queue = [s]
        head = 0
        while head < len(queue):
            v = queue[head]
            head += 1
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        while stack:
            x = stack.pop()
            for v in preds[x]:
                delta[v] += sigma[v] / sigma[x] * (1 + delta[x])
            if x != s:
                cb[x] += delta[x]
    return cb


# ---- Choosing champions ----

def team_order(net):
    def key(t):
        s = net["teamSize"][t]
        density = net["teamTies"][t] / (s * (s - 1) / 2) if s > 1 else 0
        return (-density, -s, t)
    return sorted(range(net["teams"]), key=key)


def members_by_degree(net, t):
    return sorted((v for v in range(net["size"]) if net["team"][v] == t), key=lambda v: (-net["degree"][v], v))


def pick_champions(net, k, strategy, rng):
    n = net["size"]
    k = min(k, n)
    out = []
    if strategy == "random":
        pool = list(range(n))
        for i in range(k):
            j = i + int(math.floor(rng.uniform() * (n - i)))
            pool[i], pool[j] = pool[j], pool[i]
            out.append(pool[i])
    elif strategy == "hubs":
        out = sorted(range(n), key=lambda v: (-net["degree"][v], v))[:k]
    elif strategy == "bridges":
        out = sorted(range(n), key=lambda v: (-net["betweenness"][v], -net["degree"][v], v))[:k]
    elif strategy == "cluster":
        for t in team_order(net):
            for v in members_by_degree(net, t):
                if len(out) >= k:
                    break
                out.append(v)
            if len(out) >= k:
                break
    elif strategy == "spread":
        lists = [members_by_degree(net, t) for t in team_order(net)]
        rnd = 0
        while len(out) < k:
            added = False
            for lst in lists:
                if len(out) >= k:
                    break
                if rnd < len(lst):
                    out.append(lst[rnd])
                    added = True
            if not added:
                break
            rnd += 1
    else:
        raise ValueError("Unknown strategy: %s" % strategy)
    return sorted(out)


# ---- One rollout ----

def simulate_rollout(net, p, champions, rng, record=False):
    """Runs one rollout week by week; everyone draws one random number per week, whatever their state."""
    n, weeks, w = net["size"], p["weeks"], p["championWeight"]
    adj, degree, suit = net["adj"], net["degree"], net["suit"]
    user = [0] * n
    champ = [0] * n
    ever = [0] * n
    theta = [p["socialProof"] * net["need"][i] for i in range(n)]
    for c in champions:
        user[c] = champ[c] = ever[c] = 1
    max_a = max(d * w for d in degree) if n else 0
    stay = [1.0]
    for k in range(1, max_a + 1):
        stay.append(stay[k - 1] * (1 - p["peerPull"]))
    count = len(champions)
    curve = [count / n]
    reached = 0 if count / n >= 0.5 else None
    states = [user[:]] if record else None
    a = [0] * n
    for week in range(1, weeks + 1):
        for i in range(n):
            total = 0
            for j in adj[i]:
                if user[j]:
                    total += w if champ[j] else 1
            a[i] = total
        nxt = user[:]
        for i in range(n):
            u = rng.uniform()
            if champ[i]:
                continue
            deg = degree[i]
            share = min(1, a[i] / deg) if deg > 0 else 0
            if user[i]:
                if u < p["lapse"] * (1 - share):
                    nxt[i] = 0
            elif suit[i] < p["fit"]:
                is_open = deg > 0 and share >= theta[i]
                p_try = 1 - (1 - p["spontaneous"]) * (stay[a[i]] if is_open else 1)
                if u < p_try:
                    nxt[i] = 1
                    ever[i] = 1
        user = nxt
        count = sum(user)
        curve.append(count / n)
        if reached is None and count / n >= 0.5:
            reached = week
        if states is not None:
            states.append(user[:])
    in_team = [0] * net["teams"]
    using_in_team = [0] * net["teams"]
    for i in range(n):
        in_team[net["team"][i]] += 1
        using_in_team[net["team"][i]] += user[i]
    holds = sum(1 for k in range(net["teams"]) if in_team[k] > 0 and using_in_team[k] / in_team[k] >= CONSTANTS["holdShare"])
    return {"curve": curve, "final": count / n, "ever": sum(ever) / n, "holds": holds, "reached": reached,
            "states": states}


def _mean(xs):
    total = 0.0
    for x in xs:
        total += x
    return total / len(xs) if xs else None


def _percentile(sorted_values, q):
    return sorted_values[int(math.floor(q * (len(sorted_values) - 1)))]


def run_strategy(net, src, strategy):
    """Runs every rollout for one strategy and summarises them."""
    p = normalise_params(src)
    finals, evers, holds, reached_weeks = [], [], [], []
    by_week = [[] for _ in range(p["weeks"] + 1)]
    first = None
    for r in range(p["runs"]):
        champs = pick_champions(net, p["champions"], strategy, Rng(mix_seed(p["seed"] ^ CONSTANTS["pickSalt"], r)))
        if r == 0:
            first = champs
        res = simulate_rollout(net, p, champs, Rng(mix_seed(p["seed"], 1000 + r)))
        finals.append(res["final"])
        evers.append(res["ever"])
        holds.append(res["holds"])
        if res["reached"] is not None:
            reached_weeks.append(res["reached"])
        for k in range(p["weeks"] + 1):
            by_week[k].append(res["curve"][k])
    curve_mean, curve_low, curve_high = [], [], []
    for values in by_week:
        ordered = sorted(values)
        curve_mean.append(_mean(values))
        curve_low.append(_percentile(ordered, CONSTANTS["bandLow"]))
        curve_high.append(_percentile(ordered, CONSTANTS["bandHigh"]))
    reached_weeks.sort()
    return {
        "strategy": strategy,
        "champions": first,
        "finalMean": _mean(finals),
        "everMean": _mean(evers),
        "holdsMean": _mean(holds),
        "reachShare": len(reached_weeks) / p["runs"],
        "weeksToHalf": reached_weeks[(len(reached_weeks) - 1) // 2] if reached_weeks else None,
        "curveMean": curve_mean,
        "curveLow": curve_low,
        "curveHigh": curve_high,
    }


def rank_strategies(results):
    return sorted(results, key=lambda r: (-r["finalMean"], STRATEGY_KEYS.index(r["strategy"])))


def summarise_network(net):
    return {"size": net["size"], "teams": net["teams"], "edges": net["edges"], "meanDegree": net["meanDegree"],
            "outsideShare": net["outsideShare"]}


def compare_strategies(src=None, net=None):
    """Runs all five strategies on one organisation (built from the settings unless ``net`` is given)."""
    p = normalise_params(src)
    if net is None:
        net = build_network(p)
    results = [run_strategy(net, p, s) for s in STRATEGY_KEYS]
    return {"params": p, "network": summarise_network(net), "results": results,
            "ranking": [r["strategy"] for r in rank_strategies(results)]}


def whole_pct(x):
    return "%d%%" % math.floor(x * 100 + 0.5)


def explain(cmp):
    """Plain-English reasons, built from the numbers (matches the browser app word for word)."""
    p = cmp["params"]
    by = {r["strategy"]: r for r in cmp["results"]}
    best, second, worst = by[cmp["ranking"][0]], by[cmp["ranking"][1]], by[cmp["ranking"][-1]]
    ties = cmp["network"]["outsideShare"]
    label = STRATEGY_LABELS
    out = []
    if best["finalMean"] - second["finalMean"] < 0.03:
        out.append("It is close: %s ends at %s and %s at %s, so where the champions sit matters little for how far it spreads."
                   % (label[best["strategy"]].lower(), whole_pct(best["finalMean"]), label[second["strategy"]].lower(),
                      whole_pct(second["finalMean"])))
        if best["weeksToHalf"] is not None and second["weeksToHalf"] is not None and best["weeksToHalf"] != second["weeksToHalf"]:
            fast, slow = (best, second) if best["weeksToHalf"] < second["weeksToHalf"] else (second, best)
            out.append("It does change the speed: %s reaches half the organisation in %d weeks, %s in %d."
                       % (label[fast["strategy"]].lower(), fast["weeksToHalf"], label[slow["strategy"]].lower(), slow["weeksToHalf"]))
    else:
        out.append("%s does best: %s of people are using the tool after %d weeks, against %s for %s."
                   % (label[best["strategy"]], whole_pct(best["finalMean"]), p["weeks"], whole_pct(second["finalMean"]),
                      label[second["strategy"]].lower()))
        if best["strategy"] == "spread":
            out.append("Every team gets a champion that people work with closely. Only %s of working ties cross team lines, so use rarely jumps between teams on its own: starting in many teams at once matters."
                       % whole_pct(ties))
        elif best["strategy"] == "cluster":
            out.append("Concentrated champions push one team well past the bar, and that team then carries its neighbours.")
        elif best["strategy"] == "hubs":
            out.append("The best-connected people are seen by the most colleagues, so they clear the bar for more people than champions anywhere else.")
        elif best["strategy"] == "bridges":
            out.append("Bridge builders sit between groups, so their use is seen on both sides of the gaps that otherwise stop it spreading.")
        else:
            out.append("Champions chosen at random do as well as any plan here.")
    if p["socialProof"] >= 0.15:
        out.append("People need about %s of their contacts using it before they are open to it, so a lone user rarely persuades anyone."
                   % whole_pct(p["socialProof"]))
    elif p["socialProof"] < 0.1:
        out.append("Very little social proof is needed, so one colleague using it is enough to get someone to try it.")
    if worst["strategy"] == "cluster" and best["finalMean"] - worst["finalMean"] > 0.15:
        out.append("Starting in one pilot team is the weakest choice (%s): use takes hold in that team but rarely crosses into others."
                   % whole_pct(worst["finalMean"]))
    if best["everMean"] - best["finalMean"] > 0.1:
        out.append("%s of people tried it at some point but only %s are still using it: people left using it alone tend to drop it."
                   % (whole_pct(best["everMean"]), whole_pct(best["finalMean"])))
    if best["finalMean"] < 0.2:
        out.append("No strategy gets far. Try more champions, more peer pull or less need for social proof to see what would tip it.")
    return out
