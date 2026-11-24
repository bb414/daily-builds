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
    "custom": "Your picks",
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

DEFAULTS = {"strategy": "hubs", "custom": []}
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
    out["custom"] = read_picks(src.get("custom"), out["people"], out["champions"])
    strategy = src.get("strategy")
    allowed = strategy in STRATEGY_KEYS or (strategy == "custom" and len(out["custom"]) > 0)
    out["strategy"] = strategy if allowed else DEFAULTS["strategy"]
    return out


def read_picks(raw, people, limit):
    """Your own champions: person numbers (counting from 0), as a list or a comma-separated string."""
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    seen, out = set(), []
    for item in items:
        v = to_number(item) if isinstance(item, (str, int, float)) and not isinstance(item, bool) else math.nan
        if not math.isfinite(v) or v != math.floor(v) or v < 0 or v >= people or v in seen:
            continue
        seen.add(v)
        out.append(int(v))
    out.sort()
    return out[:limit]


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


def champions_for(net, p, strategy, rng):
    if strategy == "custom":
        return [v for v in p["custom"] if v < net["size"]][:p["champions"]]
    return pick_champions(net, p["champions"], strategy, rng)


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
    # a[i] = weighted number of i's contacts using the tool (a champion counts as w users).
    a = [0] * n
    for i in range(n):
        total = 0
        for j in adj[i]:
            if user[j]:
                total += w if champ[j] else 1
        a[i] = total
    lapse, fit, spont, peer_state = p["lapse"], p["fit"], p["spontaneous"], rng.a
    for week in range(1, weeks + 1):
        nxt = user[:]
        for i in range(n):
            # Mulberry32 inlined for speed (identical to Rng.uniform).
            peer_state = (peer_state + 0x6D2B79F5) & MASK
            t = peer_state
            t = ((t ^ (t >> 15)) * (t | 1)) & MASK
            t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK
            u = ((t ^ (t >> 14)) & MASK) / 4294967296
            if champ[i]:
                continue
            deg = degree[i]
            share = min(1, a[i] / deg) if deg > 0 else 0
            if user[i]:
                if u < lapse * (1 - share):
                    nxt[i] = 0
            elif suit[i] < fit:
                is_open = deg > 0 and share >= theta[i]
                p_try = 1 - (1 - spont) * (stay[a[i]] if is_open else 1)
                if u < p_try:
                    nxt[i] = 1
                    ever[i] = 1
        # Update the counts only around people who changed this week.
        for i in range(n):
            if nxt[i] != user[i]:
                delta = nxt[i] - user[i]
                count += delta
                for j in adj[i]:
                    a[j] += delta
        user = nxt
        curve.append(count / n)
        if reached is None and count / n >= 0.5:
            reached = week
        if states is not None:
            states.append(user[:])
    rng.a = peer_state
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
    p["custom"] = read_picks((src or {}).get("custom"), net["size"], p["champions"])
    finals, evers, holds, reached_weeks = [], [], [], []
    by_week = [[] for _ in range(p["weeks"] + 1)]
    first = None
    for r in range(p["runs"]):
        champs = champions_for(net, p, strategy, Rng(mix_seed(p["seed"] ^ CONSTANTS["pickSalt"], r)))
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
    order = STRATEGY_KEYS + ["custom"]
    return sorted(results, key=lambda r: (-r["finalMean"], order.index(r["strategy"])))


def strategies_for(p):
    """The five strategies, plus your own picks when there are any."""
    return STRATEGY_KEYS + ["custom"] if p["custom"] else list(STRATEGY_KEYS)


# Values each "what if" sweep tries.
SWEEPS = {
    "socialProof": [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6],
    "champions": [1, 2, 4, 6, 8, 10, 12, 16, 20, 25, 30],
    "peerPull": [0.02, 0.04, 0.06, 0.08, 0.1, 0.15, 0.2, 0.3, 0.4],
    "tiesOrg": [0, 0.2, 0.4, 0.8, 1.2, 1.6, 2.4, 3.2, 4],
    "lapse": [0, 0.02, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3],
}
SWEEP_KEYS = ["socialProof", "champions", "peerPull", "tiesOrg", "lapse"]


def sweep_point(src, key, value):
    """The same organisation shape with one setting changed, all five strategies."""
    q = normalise_params(dict(normalise_params(src), **{key: value}))
    net = build_network(q)
    results = []
    for s in STRATEGY_KEYS:
        r = run_strategy(net, q, s)
        results.append({"strategy": s, "finalMean": r["finalMean"], "everMean": r["everMean"], "reachShare": r["reachShare"]})
    return {"value": q[key], "results": results, "best": rank_strategies(results)[0]["strategy"]}


def sweep(src, key):
    if key not in SWEEPS:
        raise ValueError("Cannot sweep %s. Choose from: %s" % (key, ", ".join(SWEEP_KEYS)))
    return {"key": key, "points": [sweep_point(src, key, v) for v in SWEEPS[key]]}


def winner_spans(sw):
    spans = []
    for pt in sw["points"]:
        if spans and spans[-1]["strategy"] == pt["best"]:
            spans[-1]["to"] = pt["value"]
        else:
            spans.append({"strategy": pt["best"], "from": pt["value"], "to": pt["value"]})
    return spans


# ---- Other organisations of the same shape ----

ROBUST_COUNT, ROBUST_RUNS = 10, 20


def robust_seed(seed, i):
    return ((seed - 1 + 7919 * (i + 1)) % 9999) + 1


def robustness_point(src, i):
    """One organisation drawn with a different seed (your own picks are left out: they name people in this one)."""
    p = normalise_params(src)
    q = dict(p, seed=robust_seed(p["seed"], i), runs=min(p["runs"], ROBUST_RUNS), custom=[])
    cmp = compare_strategies(q)
    return {"seed": q["seed"], "ranking": cmp["ranking"], "finals": [r["finalMean"] for r in cmp["results"]]}


def summarise_robustness(points):
    out = []
    for si, s in enumerate(STRATEGY_KEYS):
        vals = [pt["finals"][si] for pt in points]
        total = 0.0
        for v in vals:
            total += v
        out.append({"strategy": s, "wins": sum(1 for pt in points if pt["ranking"][0] == s),
                    "mean": total / len(vals), "low": min(vals), "high": max(vals)})
    return out


def robustness(src):
    points = [robustness_point(src, i) for i in range(ROBUST_COUNT)]
    return {"points": points, "summary": summarise_robustness(points)}


def read_settings_file(obj):
    """Accepts the JSON file the browser app downloads (or a flat dict of settings)."""
    if not isinstance(obj, dict):
        raise ValueError("The file does not contain Champion Seeding settings.")
    params = obj["params"] if isinstance(obj.get("params"), dict) else obj
    if not any(key in params for key, *_rest in PARAMS) and "strategy" not in params:
        raise ValueError("The file does not contain Champion Seeding settings.")
    return normalise_params(params)


def summarise_network(net):
    return {"size": net["size"], "teams": net["teams"], "edges": net["edges"], "meanDegree": net["meanDegree"],
            "outsideShare": net["outsideShare"]}


def compare_strategies(src=None, net=None):
    """Runs all five strategies on one organisation (built from the settings unless ``net`` is given)."""
    p = normalise_params(src)
    if net is None:
        net = build_network(p)
    else:
        # A loaded network can be a different size from the synthetic one: check your picks against it.
        p["custom"] = read_picks((src or {}).get("custom"), net["size"], p["champions"])
        if p["strategy"] == "custom" and not p["custom"]:
            p["strategy"] = DEFAULTS["strategy"]
    results = [run_strategy(net, p, s) for s in strategies_for(p)]
    return {"params": p, "network": summarise_network(net), "results": results,
            "ranking": [r["strategy"] for r in rank_strategies(results)]}


def whole_pct(x):
    return "%d%%" % math.floor(x * 100 + 0.5)


def explain(cmp):
    """Plain-English reasons, built from the numbers (matches the browser app word for word)."""
    p = cmp["params"]
    by = {r["strategy"]: r for r in cmp["results"]}
    # The standard strategies are compared with each other; your own picks get a sentence of their own.
    ranking = [k for k in cmp["ranking"] if k != "custom"]
    best, second, worst = by[ranking[0]], by[ranking[1]], by[ranking[-1]]
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
    if "custom" in by:
        mine = by["custom"]
        gap = mine["finalMean"] - best["finalMean"]
        size = " (%d of %d champions)" % (len(mine["champions"]), p["champions"]) if len(mine["champions"]) < p["champions"] else ""
        if gap > 0.005:
            tail = "beating every standard strategy."
        elif gap < -0.005:
            tail = "against %s for %s." % (whole_pct(best["finalMean"]), label[best["strategy"]].lower())
        else:
            tail = "level with %s." % label[best["strategy"]].lower()
        out.append("Your picks%s reach %s, %s" % (size, whole_pct(mine["finalMean"]), tail))
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
