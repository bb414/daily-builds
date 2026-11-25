"""Core model: a line-for-line port of the browser app's MODEL block.

Synthetic applicants, a small boosted-tree shortlisting model, exact
minimum-cost recourse, exact Shapley values and a cohort audit. Every
calculation follows the same order as the JavaScript so that both versions
give identical numbers (the agreement tests check this).
"""

import heapq
import math

FEATURES = [
    {"key": "test", "label": "Aptitude test score", "short": "Test score", "min": 0, "max": 100, "unit": "points", "dir": 1, "actionable": True, "cap": 10, "weight": 1},
    {"key": "experience", "label": "Relevant work experience", "short": "Experience", "min": 0, "max": 36, "unit": "months", "dir": 1, "actionable": True, "cap": 12, "weight": 1},
    {"key": "projects", "label": "Projects and leadership roles", "short": "Projects", "min": 0, "max": 6, "unit": "roles", "dir": 1, "actionable": True, "cap": 2, "weight": 1},
    {"key": "certs", "label": "Professional certificates", "short": "Certificates", "min": 0, "max": 4, "unit": "certificates", "dir": 1, "actionable": True, "cap": 2, "weight": 1},
    {"key": "degree", "label": "Degree result", "short": "Degree", "min": 1, "max": 4, "unit": "", "dir": 1, "actionable": False, "cap": 1, "weight": 1, "levels": ["Third", "2:2", "2:1", "First"]},
    {"key": "gap", "label": "Months since last study or work", "short": "Gap", "min": 0, "max": 24, "unit": "months", "dir": -1, "actionable": False, "cap": 24, "weight": 1},
]
D = len(FEATURES)
THRESHOLD = 0.5
DEFAULTS = {"trainSeed": 11, "auditSeed": 29, "nextSeed": 47, "nTrain": 1600, "nAudit": 500,
            "trees": 60, "lr": 0.15, "minLeaf": 15, "quota": 0.38}

# Example applicants, identical to the browser app's menu.
PRESETS = [
    {"name": "Near miss", "x": [64, 7, 4, 1, 3, 0]},
    {"name": "Four ways in", "x": [66, 4, 3, 1, 3, 0]},
    {"name": "Held back by degree result", "x": [62, 9, 3, 1, 1, 3]},
    {"name": "Held back by a past gap", "x": [66, 7, 1, 1, 3, 7]},
    {"name": "Strong experience, weak test", "x": [47, 24, 3, 0, 3, 0]},
    {"name": "No route within a year", "x": [44, 3, 1, 0, 2, 6]},
    {"name": "Already shortlisted", "x": [74, 12, 3, 1, 3, 0]},
]

MASK = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & MASK


def mulberry32(seed):
    state = [seed & MASK]

    def rng():
        state[0] = (state[0] + 0x6D2B79F5) & MASK
        t = state[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t = (t ^ ((t + _imul(t ^ (t >> 7), t | 61)) & MASK)) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    return rng


def irwin_hall(rng):
    s = 0.0
    for _ in range(12):
        s += rng()
    return s - 6


def clamp_round(v, lo, hi):
    r = math.floor(v + 0.5)
    return lo if r < lo else hi if r > hi else r


def generate_cohort(n, seed, strength=0.0, quota=None):
    s = strength or 0
    q = DEFAULTS["quota"] if quota is None else quota
    rng = mulberry32(seed)
    rows = []
    for _ in range(n):
        g = 1 if rng() < 0.35 else 0
        test = clamp_round(61 + 6 * s + 13 * irwin_hall(rng), 0, 100)
        experience = clamp_round((6 if g else 10) + 3 * s + 6 * irwin_hall(rng), 0, 36)
        projects = clamp_round((1.9 if g else 2.3) + 0.5 * s + 1.2 * irwin_hall(rng), 0, 6)
        certs = clamp_round(0.9 + 0.8 * irwin_hall(rng), 0, 4)
        u = rng()
        if g:
            degree = 1 if u < 0.06 else 2 if u < 0.28 else 3 if u < 0.78 else 4
        else:
            degree = 1 if u < 0.05 else 2 if u < 0.22 else 3 if u < 0.73 else 4
        gap = clamp_round(2 + 8 * rng(), 1, 24) if rng() < (0.4 if g else 0.3) else 0
        noise = irwin_hall(rng)
        latent = (0.06 * (test - 60) + 0.09 * min(experience, 18) + 0.35 * projects + 0.3 * certs
                  + 0.6 * (degree - 3) - 0.08 * gap + (0.5 if (test >= 70 and experience >= 6) else 0) + 0.8 * noise)
        rows.append({"x": [test, experience, projects, certs, degree, gap], "g": g, "latent": latent, "y": 0})
    order = sorted(range(n), key=lambda i: (-rows[i]["latent"], i))
    k = math.floor(q * n + 0.5)
    for rank in range(k):
        rows[order[rank]]["y"] = 1
    return rows


def best_split(X, r, idx, min_leaf):
    n = len(idx)
    total = 0.0
    for i in idx:
        total += r[i]
    best = None
    best_gain = 1e-12
    for f in range(D):
        lo = FEATURES[f]["min"]
        B = FEATURES[f]["max"] - lo + 1
        cnt = [0] * B
        sm = [0.0] * B
        for i in idx:
            b = X[i][f] - lo
            cnt[b] += 1
            sm[b] += r[i]
        nL = 0
        sL = 0.0
        for b in range(B - 1):
            if cnt[b] == 0:
                continue
            nL += cnt[b]
            sL += sm[b]
            nR = n - nL
            if nL < min_leaf:
                continue
            if nR < min_leaf:
                break
            sR = total - sL
            gain = sL * sL / nL + sR * sR / nR - total * total / n
            if gain > best_gain:
                best_gain = gain
                best = (f, lo + b)
    return best


def grow_node(X, r, idx, depth, max_depth, min_leaf):
    if depth < max_depth:
        s = best_split(X, r, idx, min_leaf)
        if s:
            f, t = s
            L = [i for i in idx if X[i][f] <= t]
            R = [i for i in idx if X[i][f] > t]
            return {"f": f, "t": t,
                    "l": grow_node(X, r, L, depth + 1, max_depth, min_leaf),
                    "r": grow_node(X, r, R, depth + 1, max_depth, min_leaf)}
    s = 0.0
    for i in idx:
        s += r[i]
    return {"v": s / len(idx)}


def leaf_value(node, x):
    while "v" not in node:
        node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
    return node["v"]


def collect_splits(trees):
    sets = [set() for _ in range(D)]

    def walk(node):
        if "v" in node:
            return
        sets[node["f"]].add(node["t"])
        walk(node["l"])
        walk(node["r"])

    for t in trees:
        walk(t)
    return [sorted(s) for s in sets]


def train_model(rows, trees=None, lr=None, min_leaf=None, depth=2):
    trees_n = DEFAULTS["trees"] if trees is None else trees
    lr = DEFAULTS["lr"] if lr is None else lr
    min_leaf = DEFAULTS["minLeaf"] if min_leaf is None else min_leaf
    n = len(rows)
    X = [row["x"] for row in rows]
    base = 0.0
    for row in rows:
        base += row["y"]
    base /= n
    F = [base] * n
    r = [0.0] * n
    allidx = list(range(n))
    out = []
    for _ in range(trees_n):
        for i in range(n):
            r[i] = rows[i]["y"] - F[i]
        tree = grow_node(X, r, allidx, 0, depth, min_leaf)
        out.append(tree)
        for i in range(n):
            F[i] += lr * leaf_value(tree, X[i])
    return {"base": base, "lr": lr, "trees": out, "threshold": THRESHOLD, "splits": collect_splits(out)}


def predict(model, x):
    s = model["base"]
    lr = model["lr"]
    for tree in model["trees"]:
        s += lr * leaf_value(tree, x)
    return s


def cost_tables(rows):
    tables = []
    for j, f in enumerate(FEATURES):
        B = f["max"] - f["min"] + 1
        c = [1] * B
        for row in rows:
            c[row["x"][j] - f["min"]] += 1
        N = len(rows) + B
        cdf = []
        below = 0
        for b in range(B):
            cdf.append((below + 0.5 * c[b]) / N)
            below += c[b]
        tables.append(cdf)
    return tables


def default_settings():
    return [{"actionable": f["actionable"], "cap": f["cap"], "weight": f["weight"]} for f in FEATURES]


def feature_cost(tables, settings, j, frm, to):
    lo = FEATURES[j]["min"]
    return 100 * settings[j]["weight"] * abs(tables[j][to - lo] - tables[j][frm - lo])


def candidates(model, x, j, setting):
    f = FEATURES[j]
    out = [x[j]]
    if not setting["actionable"] or setting["cap"] <= 0:
        return out
    th = model["splits"][j]
    if f["dir"] > 0:
        hi = min(f["max"], x[j] + setting["cap"])
        for t in th:
            v = t + 1
            if x[j] < v <= hi:
                out.append(v)
    else:
        lo = max(f["min"], x[j] - setting["cap"])
        for t in reversed(th):
            if lo <= t < x[j]:
                out.append(t)
    return out


def max_leaf(node, lo, hi):
    """The best leaf a tree can reach when each feature stays between lo and hi."""
    if "v" in node:
        return node["v"]
    best = -math.inf
    f, t = node["f"], node["t"]
    if lo[f] <= t:
        h = list(hi)
        h[f] = min(h[f], t)
        best = max(best, max_leaf(node["l"], lo, h))
    if hi[f] > t:
        lw = list(lo)
        lw[f] = max(lw[f], t + 1)
        best = max(best, max_leaf(node["r"], lw, hi))
    return best


def score_bound(model, lo, hi):
    """No plan can score more than the sum of each tree's best reachable leaf."""
    s = model["base"]
    for tree in model["trees"]:
        s += model["lr"] * max_leaf(tree, lo, hi)
    return s


def search_routes(model, tables, x, settings, margins, max_levers=D, allowed=None, max_states=200000):
    """Exact minimum-cost recourse by uniform-cost search over split points.

    The visiting order does not depend on the target, so one search answers
    several safety margins at once, exactly as separate searches would.
    """
    score0 = predict(model, x)
    if score0 >= model["threshold"]:
        return [{"status": "already", "score": score0, "cost": 0, "values": list(x), "changes": [], "explored": 0}
                for _ in margins]
    results = [None] * len(margins)
    targets = [model["threshold"] + m for m in margins]
    open_count = len(margins)
    lists = []
    for j in range(D):
        ok = allowed[j] if allowed is not None else True
        lists.append(candidates(model, x, j, settings[j]) if ok else [x[j]])
    bound = score_bound(model, [min(l) for l in lists], [max(l) for l in lists])
    for k in range(len(margins)):
        if targets[k] > bound:
            results[k] = {"status": "none", "score": score0, "cost": None, "values": None, "changes": [], "explored": 0}
            open_count -= 1
    if open_count == 0:
        return results
    unit_cost = [[feature_cost(tables, settings, j, x[j], v) for v in lists[j]] for j in range(D)]

    def cost_of(idx):
        c = 0.0
        for j in range(D):
            c += unit_cost[j][idx[j]]
        return c

    # Each combination of candidate positions gets a number (mixed radix).
    strides = []
    total = 1
    for j in range(D):
        strides.append(total)
        total *= len(lists[j])
    heap = [(0, 0, (0,) * D, 0)]
    seen = {0}
    seq = 1
    explored = 0

    def finish(status):
        return [r if r is not None else {"status": status, "score": score0, "cost": None, "values": None,
                                         "changes": [], "explored": explored} for r in results]

    while heap:
        c, _, idx, key = heapq.heappop(heap)
        explored += 1
        vals = [lists[j][idx[j]] for j in range(D)]
        sc = predict(model, vals)
        for k in range(len(margins)):
            if results[k] is not None or sc < targets[k]:
                continue
            changes = [{"j": j, "from": x[j], "to": vals[j], "cost": unit_cost[j][idx[j]]}
                       for j in range(D) if vals[j] != x[j]]
            results[k] = {"status": "found", "score": sc, "cost": c, "values": list(vals), "changes": changes,
                          "explored": explored}
            open_count -= 1
        if open_count == 0:
            return results
        if explored >= max_states:
            return finish("limit")
        levers = sum(1 for k in idx if k > 0)
        for j in range(D):
            if idx[j] + 1 >= len(lists[j]):
                continue
            if idx[j] == 0 and levers >= max_levers:
                continue
            nkey = key + strides[j]
            if nkey in seen:
                continue
            seen.add(nkey)
            nidx = idx[:j] + (idx[j] + 1,) + idx[j + 1:]
            heapq.heappush(heap, (cost_of(nidx), seq, nidx, nkey))
            seq += 1
    return finish("none")


def find_recourse(model, tables, x, settings, margin=0.0, max_levers=D, allowed=None, max_states=200000):
    return search_routes(model, tables, x, settings, [margin], max_levers=max_levers, allowed=allowed,
                         max_states=max_states)[0]


def main_lever(plan):
    best, best_cost = -1, -1
    for ch in plan["changes"]:
        if ch["cost"] > best_cost:
            best_cost = ch["cost"]
            best = ch["j"]
    return best


def recourse_options(model, tables, x, settings, margin=0.0, max_levers=D):
    first = find_recourse(model, tables, x, settings, margin=margin, max_levers=max_levers)
    if first["status"] != "found":
        return {"status": first["status"], "score": first["score"], "options": []}
    movable = [j for j in range(D) if len(candidates(model, x, j, settings[j])) > 1]
    pool = []
    for mask in range(1, 1 << len(movable)):
        allowed = [False] * D
        size = 0
        for k, j in enumerate(movable):
            if mask & (1 << k):
                allowed[j] = True
                size += 1
        if size > max_levers:
            continue
        r = find_recourse(model, tables, x, settings, margin=margin, max_levers=max_levers, allowed=allowed)
        if r["status"] != "found" or len(r["changes"]) != size:
            continue
        r["mask"] = mask
        r["lever"] = main_lever(r)
        pool.append(r)
    by_lever = {}
    for r in pool:
        cur = by_lever.get(r["lever"])
        if (cur is None or r["cost"] < cur["cost"] or (r["cost"] == cur["cost"] and (
                len(r["changes"]) < len(cur["changes"]) or (len(r["changes"]) == len(cur["changes"]) and r["mask"] < cur["mask"])))):
            by_lever[r["lever"]] = r
    options = sorted(by_lever.values(), key=lambda r: (r["cost"], len(r["changes"]), r["mask"]))
    return {"status": "found", "score": first["score"], "options": options}


def background_sample(rows, size):
    step = len(rows) // size
    return [rows[k * step]["x"] for k in range(size)]


def tree_features(node):
    seen = set()

    def walk(n):
        if "v" in n:
            return
        seen.add(n["f"])
        walk(n["l"])
        walk(n["r"])

    walk(node)
    return sorted(seen)


def bin_of(cuts, v):
    b = 0
    while b < len(cuts) and v > cuts[b]:
        b += 1
    return b


def shapley_prep(model, background):
    """Group the reference applicants by which side of each split they fall on, tree by tree."""
    prep = []
    for tree in model["trees"]:
        F = tree_features(tree)
        cuts = []
        for f in F:
            found = set()

            def walk(n, f=f, found=found):
                if "v" in n:
                    return
                if n["f"] == f:
                    found.add(n["t"])
                walk(n["l"])
                walk(n["r"])

            walk(tree)
            cuts.append(sorted(found))
        sizes = [len(c) + 1 for c in cuts]
        strides = []
        total = 1
        for i in range(len(F)):
            strides.append(total)
            total *= sizes[i]
        counts = [0] * total
        for bg in background:
            p = 0
            for i in range(len(F)):
                p += bin_of(cuts[i], bg[F[i]]) * strides[i]
            counts[p] += 1
        leaf = [0.0] * total
        z = [0] * D
        for p in range(total):
            for i in range(len(F)):
                b = (p // strides[i]) % sizes[i]
                z[F[i]] = cuts[i][b] if b < len(cuts[i]) else cuts[i][-1] + 1
            leaf[p] = leaf_value(tree, z)
        prep.append({"F": F, "cuts": cuts, "sizes": sizes, "strides": strides, "counts": counts, "leaf": leaf})
    return prep


def shapley(model, x, background, prep=None):
    """Exact interventional Shapley values, computed tree by tree.

    Shapley values add up over the trees and each tree only reads the
    features it splits on, and only which side of each split a value falls,
    so the answer equals the textbook 64-combination definition but needs a
    few dozen look-ups per tree.
    """
    P = prep if prep is not None else shapley_prep(model, background)
    B = len(background)
    phi = [0.0] * D
    fact = [1, 1, 2, 6, 24, 120, 720]
    for T in P:
        k = len(T["F"])
        if k == 0:
            continue
        xb = [bin_of(T["cuts"][i], x[f]) for i, f in enumerate(T["F"])]
        n = 1 << k
        v = [0.0] * n
        counts, leaf, strides, sizes = T["counts"], T["leaf"], T["strides"], T["sizes"]
        for mask in range(n):
            s = 0.0
            for p in range(len(counts)):
                if counts[p] == 0:
                    continue
                q = 0
                for i in range(k):
                    b = xb[i] if (mask >> i) & 1 else (p // strides[i]) % sizes[i]
                    q += b * strides[i]
                s += counts[p] * leaf[q]
            v[mask] = s / B
        for i in range(k):
            acc = 0.0
            for mask in range(n):
                if (mask >> i) & 1:
                    continue
                size = bin(mask).count("1")
                acc += fact[size] * fact[k - size - 1] / fact[k] * (v[mask | (1 << i)] - v[mask])
            phi[T["F"][i]] += model["lr"] * acc
    base = 0.0
    for bg in background:
        base += predict(model, bg)
    return {"phi": phi, "base": base / B, "value": predict(model, x)}


def median(sorted_vals):
    n = len(sorted_vals)
    if n == 0:
        return None
    if n % 2:
        return sorted_vals[(n - 1) // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2


def mean(arr):
    if not arr:
        return None
    s = 0.0
    for a in arr:
        s += a
    return s / len(arr)


def audit(model, tables, cohort, settings, margin=0.0, max_levers=D):
    groups = [{"g": g, "n": 0, "shortlisted": 0, "rejected": 0, "feasible": 0, "costs": [],
               "lever": [0] * D, "expAdded": []} for g in (0, 1)]
    rows = []
    for i, row in enumerate(cohort):
        G = groups[row["g"]]
        G["n"] += 1
        r = find_recourse(model, tables, row["x"], settings, margin=margin, max_levers=max_levers)
        if r["status"] == "already":
            G["shortlisted"] += 1
            rows.append({"i": i, "g": row["g"], "status": "already", "cost": 0})
            continue
        G["rejected"] += 1
        if r["status"] == "found":
            G["feasible"] += 1
            G["costs"].append(r["cost"])
            for ch in r["changes"]:
                G["lever"][ch["j"]] += 1
            G["expAdded"].append(r["values"][1] - row["x"][1])
        rows.append({"i": i, "g": row["g"], "status": r["status"], "cost": r["cost"],
                     "lever": main_lever(r) if r["status"] == "found" else -1,
                     "changed": [ch["j"] for ch in r["changes"]]})
    summary = []
    for G in groups:
        summary.append({
            "g": G["g"], "n": G["n"], "shortlisted": G["shortlisted"], "rejected": G["rejected"], "feasible": G["feasible"],
            "shortlistRate": G["shortlisted"] / G["n"] if G["n"] else None,
            "feasibleShare": G["feasible"] / G["rejected"] if G["rejected"] else None,
            "meanCost": mean(G["costs"]), "medianCost": median(sorted(G["costs"])),
            "leverShare": [c / G["feasible"] if G["feasible"] else 0 for c in G["lever"]],
            "meanExpAdded": mean(G["expAdded"]),
        })
    return {"groups": summary, "rows": rows}


# ---- Will it hold? Routes against a retrained model ----
MARGINS = [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]


def next_model(strength, retrain):
    """Next year's model: same hidden rule and quota, a fresh, stronger pool."""
    return train_model(generate_cohort(DEFAULTS["nTrain"], DEFAULTS["nextSeed"] + retrain - 1, strength))


def route_table(model, tables, cohort, settings, margins, max_levers=D):
    """The cheapest route for every applicant at every safety margin."""
    table = [[] for _ in margins]
    for row in cohort:
        res = search_routes(model, tables, row["x"], settings, margins, max_levers=max_levers)
        for k, r in enumerate(res):
            table[k].append({"status": r["status"], "values": r["values"], "cost": r["cost"]})
    return table


def summarise_hold(acc):
    return {
        "rejected": acc["rejected"], "routes": acc["routes"], "kept": acc["kept"],
        "routeShare": acc["routes"] / acc["rejected"] if acc["rejected"] else None,
        "keptShare": acc["kept"] / acc["routes"] if acc["routes"] else None,
        "medianCost": median(sorted(acc["costs"])), "meanCost": mean(acc["costs"]),
    }


def hold_summary(model2, cohort, table, margins):
    out = []
    for k, m in enumerate(margins):
        acc = [{"rejected": 0, "routes": 0, "kept": 0, "costs": []} for _ in range(3)]
        for i, r in enumerate(table[k]):
            if r["status"] == "already":
                continue
            targets = [acc[cohort[i]["g"]], acc[2]]
            for a in targets:
                a["rejected"] += 1
            if r["status"] != "found":
                continue
            kept = predict(model2, r["values"]) >= model2["threshold"]
            for a in targets:
                a["routes"] += 1
                a["costs"].append(r["cost"])
                if kept:
                    a["kept"] += 1
        out.append({"margin": m, "groups": [summarise_hold(acc[0]), summarise_hold(acc[1])], "all": summarise_hold(acc[2])})
    return out


# ---- Explanation versus advice ----
def biggest_drag(phi):
    j = -1
    for k in range(D):
        if phi[k] < 0 and (j < 0 or phi[k] < phi[j]):
            j = k
    return j


def explain_gap(model, cohort, audit_rows, background, settings, prep=None):
    """Biggest Shapley drag against the main lever of the cheapest route, by group."""
    P = prep if prep is not None else shapley_prep(model, background)
    acc = [{"rejected": 0, "routed": 0, "dragFixed": 0, "noDrag": 0, "mismatch": 0,
            "matrix": [[0] * (D + 1) for _ in range(D + 1)]} for _ in range(3)]
    for row in audit_rows:
        if row["status"] == "already":
            continue
        drag = biggest_drag(shapley(model, cohort[row["i"]]["x"], background, P)["phi"])
        lever = row["lever"] if row["status"] == "found" else -1
        for a in (acc[row["g"]], acc[2]):
            a["rejected"] += 1
            if drag < 0:
                a["noDrag"] += 1
            elif not settings[drag]["actionable"]:
                a["dragFixed"] += 1
            if lever >= 0:
                a["routed"] += 1
                if drag not in row["changed"]:
                    a["mismatch"] += 1
            a["matrix"][D if drag < 0 else drag][D if lever < 0 else lever] += 1
    return [{
        "rejected": a["rejected"], "routed": a["routed"], "dragFixed": a["dragFixed"], "noDrag": a["noDrag"],
        "mismatch": a["mismatch"],
        "dragFixedShare": a["dragFixed"] / a["rejected"] if a["rejected"] else None,
        "mismatchShare": a["mismatch"] / a["routed"] if a["routed"] else None,
        "matrix": a["matrix"],
    } for a in acc]


# ---- Saving and loading a setup (the same JSON the browser app downloads) ----
SETUP_TOOL = "what-would-it-take"


class SetupError(ValueError):
    pass


def make_setup(x, settings, max_levers, margin, points, retrain):
    return {
        "tool": SETUP_TOOL, "version": 1,
        "applicant": {f["key"]: x[j] for j, f in enumerate(FEATURES)},
        "rules": {f["key"]: {"canChange": settings[j]["actionable"], "upTo": settings[j]["cap"], "weight": settings[j]["weight"]}
                  for j, f in enumerate(FEATURES)},
        "maxLevers": max_levers, "margin": margin, "nextYear": {"points": points, "retrain": retrain},
    }


def _is_int(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer()


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_setup(obj):
    """Check a setup and fill gaps with defaults. Raises SetupError saying what is wrong."""
    if not isinstance(obj, dict):
        raise SetupError("A setup must be a JSON object.")
    if "tool" in obj and obj["tool"] != SETUP_TOOL:
        raise SetupError("This file is not a setup for this tool.")
    x = list(PRESETS[0]["x"])
    settings = default_settings()
    app = obj.get("applicant", {})
    if not isinstance(app, dict):
        raise SetupError('"applicant" must be an object.')
    rules = obj.get("rules", {})
    if not isinstance(rules, dict):
        raise SetupError('"rules" must be an object.')
    for j, f in enumerate(FEATURES):
        if f["key"] in app:
            v = app[f["key"]]
            if not _is_int(v) or v < f["min"] or v > f["max"]:
                raise SetupError("applicant.%s must be a whole number from %d to %d." % (f["key"], f["min"], f["max"]))
            x[j] = int(v)
        if f["key"] not in rules:
            continue
        r = rules[f["key"]]
        if not isinstance(r, dict):
            raise SetupError("rules.%s must be an object." % f["key"])
        if "canChange" in r:
            if not isinstance(r["canChange"], bool):
                raise SetupError("rules.%s.canChange must be true or false." % f["key"])
            settings[j]["actionable"] = r["canChange"]
        if "upTo" in r:
            if not _is_int(r["upTo"]) or r["upTo"] < 0 or r["upTo"] > f["max"] - f["min"]:
                raise SetupError("rules.%s.upTo must be a whole number from 0 to %d." % (f["key"], f["max"] - f["min"]))
            settings[j]["cap"] = int(r["upTo"])
        if "weight" in r:
            w = r["weight"]
            if not _is_num(w) or not w > 0 or w > 10:
                raise SetupError("rules.%s.weight must be above 0 and at most 10." % f["key"])
            settings[j]["weight"] = w
    max_levers = D
    if "maxLevers" in obj:
        v = obj["maxLevers"]
        if not _is_int(v) or v < 1 or v > D:
            raise SetupError("maxLevers must be a whole number from 1 to %d." % D)
        max_levers = int(v)
    margin = 0
    if "margin" in obj:
        if not _is_num(obj["margin"]) or obj["margin"] not in MARGINS:
            raise SetupError("margin must be one of %s." % ", ".join("%g" % m for m in MARGINS))
        margin = obj["margin"]
    ny = obj.get("nextYear", {})
    if not isinstance(ny, dict):
        raise SetupError('"nextYear" must be an object.')
    points, retrain = 0, 1
    if "points" in ny:
        if not _is_int(ny["points"]) or ny["points"] < 0 or ny["points"] > 6:
            raise SetupError("nextYear.points must be a whole number from 0 to 6.")
        points = int(ny["points"])
    if "retrain" in ny:
        if not _is_int(ny["retrain"]) or ny["retrain"] < 1 or ny["retrain"] > 20:
            raise SetupError("nextYear.retrain must be a whole number from 1 to 20.")
        retrain = int(ny["retrain"])
    return {"x": x, "settings": settings, "maxLevers": max_levers, "margin": margin, "points": points, "retrain": retrain}
