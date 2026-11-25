"""Assurance mix: the model.

A line-for-line port of the block between MODEL START and MODEL END in
app/index.html. Both read the same catalogue (catalogue.json, copied into the
app by tools/sync_catalogue.py) and the parity tests check that they give
identical results, down to the last bit of every number.
"""

import json
import math
import re
from pathlib import Path

DATA = json.loads((Path(__file__).with_name("catalogue.json")).read_text(encoding="utf-8"))

EPS = 1e-9
PRINCIPLES = [p["id"] for p in DATA["principles"]]
TECHNIQUES = {t["id"]: t for t in DATA["techniques"]}
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def js_num_str(x):
    """Write a number the way JavaScript's String() does, for identical notes."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    r = repr(x)
    if "e" in r:
        mant, exp = r.split("e")
        sign = "-" if exp.startswith("-") else "+"
        exp = exp.lstrip("+-").lstrip("0") or "0"
        return mant + "e" + sign + exp
    return r


def js_str(v):
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return js_num_str(v)
    return str(v)


def js_round(x):
    return math.floor(x + 0.5)


def clamp(x, lo, hi):
    return min(hi, max(lo, x))


def to_prob(score):
    """Likelihood score (0 to 5) to the probability of a material problem."""
    S, P = DATA["likelihood"]["scores"], DATA["likelihood"]["probabilities"]
    if score <= S[0]:
        return P[0]
    if score >= S[-1]:
        return P[-1]
    for k in range(1, len(S)):
        if score <= S[k]:
            return P[k - 1] + (score - S[k - 1]) * (P[k] - P[k - 1]) / (S[k] - S[k - 1])
    return P[-1]


def from_prob(prob):
    """Probability of a material problem back to a likelihood score."""
    S, P = DATA["likelihood"]["scores"], DATA["likelihood"]["probabilities"]
    if prob <= P[0]:
        return S[0]
    if prob >= P[-1]:
        return S[-1]
    for k in range(1, len(P)):
        if prob <= P[k]:
            return S[k - 1] + (prob - P[k - 1]) * (S[k] - S[k - 1]) / (P[k] - P[k - 1])
    return S[-1]


def weeks_phrase(w):
    return "1 week" if w == 1 else js_num_str(w) + " weeks"


def band(score):
    for b in DATA["riskBands"]:
        if score <= b["max"] + EPS:
            return b["label"]
    return DATA["riskBands"][-1]["label"]


def technique_by_id(tid):
    return TECHNIQUES.get(tid)


def finite_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None
    if isinstance(v, str) and v.strip() != "":
        s = v.strip()
        if not _NUMBER.match(s):
            return None
        n = float(s)
        return n if math.isfinite(n) else None
    return None


def _empty(v):
    return v is None or v == "" and isinstance(v, str)


def normalise_input(raw):
    """Turn whatever the caller passed into a complete, valid input, noting anything odd."""
    raw = raw if isinstance(raw, dict) else {}
    notes = []
    d = DATA["defaults"]
    answers = {}
    raw_answers = raw.get("answers") if isinstance(raw.get("answers"), dict) else {}
    for q in DATA["questions"]:
        v = raw_answers.get(q["id"])
        if any(o["id"] == v for o in q["options"]):
            answers[q["id"]] = v
        else:
            answers[q["id"]] = d["answers"][q["id"]]
            if not _empty(v):
                notes.append('Unknown answer "%s" for %s; used "%s".' % (js_str(v), q["id"], d["answers"][q["id"]]))

    def num(name, lo, hi):
        if _empty(raw.get(name)):
            return d[name]
        n = finite_number(raw[name])
        if n is None:
            notes.append('Could not read %s "%s"; used %s.' % (name, js_str(raw[name]), js_num_str(d[name])))
            return d[name]
        c = clamp(n, lo, hi)
        if c != n:
            notes.append("%s %s is outside %s to %s; used %s." % (name, js_num_str(n), js_num_str(lo), js_num_str(hi), js_num_str(c)))
        return c

    appetite = num("appetite", 0.5, 25)
    budget = js_round(num("budget", 0, 5000))
    weeks = js_round(num("weeks", 0, 104))
    lm = raw.get("legalMust")
    legal_must = d["legalMust"] if "legalMust" not in raw else (lm is True or lm == "true")

    def id_list(v, name):
        out = []
        if isinstance(v, list):
            items = v
        elif isinstance(v, str):
            items = re.split(r"[;,]", v)
        else:
            items = []
        for x in items:
            x = js_str(x).strip()
            if not x:
                continue
            if not technique_by_id(x):
                notes.append('Unknown technique "%s" in %s; ignored.' % (x, name))
                continue
            if x not in out:
                out.append(x)
        return out

    must = id_list(raw.get("must"), "must")
    exclude = id_list(raw.get("exclude"), "exclude")
    both = [x for x in exclude if x in must]
    if both:
        notes.append("Listed as both a must and ruled out: %s; kept as a must." % ", ".join(both))
        exclude = [x for x in exclude if x not in must]
    overrides = {"L": {}, "I": {}}
    ro = raw.get("overrides") if isinstance(raw.get("overrides"), dict) else {}
    for kind in ("L", "I"):
        src = ro.get(kind) if isinstance(ro.get(kind), dict) else {}
        for p in PRINCIPLES:
            if _empty(src.get(p)):
                continue
            n = finite_number(src[p])
            if n is None:
                notes.append("Could not read override %s for %s; ignored." % (kind, p))
                continue
            overrides[kind][p] = clamp(n, 1, 5)
    return {"answers": answers, "appetite": appetite, "budget": budget, "weeks": weeks, "legalMust": legal_must,
            "must": must, "exclude": exclude, "overrides": overrides, "notes": notes}


def inherent_risk(inp):
    """Likelihood and impact start at 1, each answer adds to them (capped at 5); score = L x I."""
    out = []
    for p in DATA["principles"]:
        L, I = 1, 1
        parts = []
        for q in DATA["questions"]:
            o = next(x for x in q["options"] if x["id"] == inp["answers"][q["id"]])
            dl, di = o["L"].get(p["id"], 0), o["I"].get(p["id"], 0)
            if dl or di:
                parts.append({"question": q["id"], "option": o["id"], "L": dl, "I": di})
            L += dl
            I += di
        L = clamp(L, 1, 5)
        I = clamp(I, 1, 5)
        overridden = {"L": p["id"] in inp["overrides"]["L"], "I": p["id"] in inp["overrides"]["I"]}
        if overridden["L"]:
            L = inp["overrides"]["L"][p["id"]]
        if overridden["I"]:
            I = inp["overrides"]["I"][p["id"]]
        score = L * I
        out.append({"id": p["id"], "L": L, "I": I, "score": score, "prob": to_prob(L), "band": band(score),
                    "parts": parts, "overridden": overridden})
    return out


def technique_status(inp):
    """How well each technique works for this system (0 means it cannot be used), and why."""
    a = inp["answers"]
    status = []
    for t in DATA["techniques"]:
        f, reason = 1, ""
        if t.get("access") and a["source"] != "inhouse":
            f *= t["access"][a["source"]]
        if f == 0:
            reason = "Needs test access to the system before go-live" if a["source"] == "docs" else "Needs full access to the model"
        if f > 0 and t.get("model"):
            f *= t["model"][a["model"]]
            if f == 0:
                reason = "Not practical for general-purpose or generative models"
        if t.get("needsData") and a["data"] == "none":
            f, reason = 0, "No personal data, so not needed"
        if t.get("boughtInOnly") and a["source"] == "inhouse":
            f, reason = 0, "Only for bought-in systems"
        coverage = {p: t["coverage"][p] * f for p in PRINCIPLES}
        required = bool(inp["legalMust"] and t.get("needsData") and a["data"] != "none")
        ruled_out = t["id"] in inp["exclude"]
        status.append({"id": t["id"], "factor": f, "available": f > 0, "reason": reason, "coverage": coverage,
                       "required": required, "must": required or t["id"] in inp["must"],
                       "excluded": ruled_out and not required, "overruled": ruled_out and required})
    by_id = {s["id"]: s for s in status}
    changed = True
    while changed:
        changed = False
        for s in status:
            if not s["available"] or s["excluded"]:
                continue
            for r in TECHNIQUES[s["id"]].get("requires", []):
                rs = by_id[r]
                if not rs["available"] or rs["excluded"]:
                    s["available"] = False
                    s["reason"] = "Needs " + TECHNIQUES[r]["name"].lower() + (
                        ", which is ruled out" if rs["excluded"] else ", which is not available")
                    changed = True
                    break
    changed = True
    while changed:
        changed = False
        for s in status:
            if not s["must"] or not s["available"]:
                continue
            for r in TECHNIQUES[s["id"]].get("requires", []):
                if not by_id[r]["must"]:
                    by_id[r]["must"] = True
                    changed = True
    return status


def prepare(inp):
    risk = inherent_risk(inp)
    status = technique_status(inp)
    notes = list(inp["notes"])
    for s in status:
        if s["must"] and not s["available"]:
            notes.append("%s is a must but cannot be used here (%s)." % (TECHNIQUES[s["id"]]["name"], s["reason"].lower()))
        if s["overruled"]:
            notes.append("%s is treated as required, so it was kept although it was ruled out." % TECHNIQUES[s["id"]]["name"])
    act = [s["id"] for s in status if s["available"] and not s["excluded"]]
    by_id = {s["id"]: s for s in status}
    miss, cost, req_mask = [], [], []
    must_mask = 0
    for i, tid in enumerate(act):
        t = TECHNIQUES[tid]
        s = by_id[tid]
        miss.append([1 - s["coverage"][p] for p in PRINCIPLES])
        cost.append(t["cost"])
        if s["must"]:
            must_mask |= 1 << i
        rm = 0
        for r in t.get("requires", []):
            rm |= 1 << act.index(r)
        req_mask.append(rm)
    return {"input": inp, "risk": risk, "status": status, "notes": notes, "ids": act, "n": len(act),
            "miss": miss, "cost": cost, "mustMask": must_mask, "reqMask": req_mask}


def enumerate_plans(prep):
    """Cost, coverage products and size of every subset of the usable techniques."""
    n = prep["n"]
    N = 1 << n
    P = len(PRINCIPLES)
    cost = [0] * N
    cnt = [0] * N
    prod = [[1.0] * N for _ in range(P)]
    pc, pm = prep["cost"], prep["miss"]
    for m in range(1, N):
        low = m & -m
        i = low.bit_length() - 1
        prev = m ^ low
        cost[m] = cost[prev] + pc[i]
        cnt[m] = cnt[prev] + 1
        mi = pm[i]
        for p in range(P):
            prod[p][m] = prod[p][prev] * mi[p]
    return {"N": N, "cost": cost, "cnt": cnt, "prod": prod}


def residual_for(risk, prods):
    r = []
    for p, rk in enumerate(risk):
        prob = rk["prob"] * prods[p]
        L = from_prob(prob)
        r.append({"id": rk["id"], "prob": prob, "L": L, "score": L * rk["I"]})
    return r


def mask_feasible(prep, m):
    if (m & prep["mustMask"]) != prep["mustMask"]:
        return False
    for i in range(prep["n"]):
        rm = prep["reqMask"][i]
        if rm and (m >> i) & 1 and (m & rm) != rm:
            return False
    return True


def schedule(ids):
    """Weeks from the start of design work. Stages run in order; techniques in a stage
    run side by side; a technique starts only when its prerequisites finish."""
    finish, rows = {}, []
    stage_start = 0
    for st in DATA["stages"]:
        stage_end = stage_start
        for t in DATA["techniques"]:
            if t["stage"] != st["id"] or t["id"] not in ids:
                continue
            start = stage_start
            for r in t.get("requires", []):
                if r in finish and finish[r] > start:
                    start = finish[r]
            finish[t["id"]] = start + t["weeks"]
            rows.append({"id": t["id"], "stage": st["id"], "start": start, "end": start + t["weeks"]})
            if finish[t["id"]] > stage_end:
                stage_end = finish[t["id"]]
        if st["id"] != "live":
            stage_start = stage_end
    return {"goLive": stage_start, "rows": rows}


def mask_ids(prep, m):
    return [prep["ids"][i] for i in range(prep["n"]) if (m >> i) & 1]


def _search(prep, en, worst, total, feasible):
    inp = prep["input"]
    cheap = cheap_key = in_budget = budget_key = best = best_key = None
    weeks_cache = {}

    def weeks_ok(m):
        if m not in weeks_cache:
            weeks_cache[m] = schedule(mask_ids(prep, m))["goLive"] <= inp["weeks"]
        return weeks_cache[m]

    cost, cnt = en["cost"], en["cnt"]
    appetite = inp["appetite"] + EPS
    budget = inp["budget"]
    for m in range(en["N"]):
        if not feasible[m]:
            continue
        w, c = worst[m], cost[m]
        if w <= appetite:
            key = (c, w, cnt[m], m)
            if (cheap_key is None or key < cheap_key) and weeks_ok(m):
                cheap, cheap_key = m, key
        k2 = (w, total[m], c, cnt[m], m)
        if c <= budget and (budget_key is None or k2 < budget_key) and weeks_ok(m):
            in_budget, budget_key = m, k2
        if (best_key is None or k2 < best_key) and weeks_ok(m):
            best, best_key = m, k2
    order = [m for m in range(en["N"]) if feasible[m]]
    order.sort(key=lambda m: (cost[m], worst[m], total[m], cnt[m], m))
    frontier = []
    best_worst = math.inf
    for m in order:
        if worst[m] < best_worst and weeks_ok(m):
            frontier.append(m)
            best_worst = worst[m]
    return {"cheapest": cheap, "inBudget": in_budget, "best": best, "frontier": frontier}


def describe(prep, en, m):
    ids = mask_ids(prep, m)
    prods = [en["prod"][p][m] for p in range(len(PRINCIPLES))]
    residual = residual_for(prep["risk"], prods)
    worst, total, worst_id = 0, 0, residual[0]["id"]
    for r in residual:
        total += r["score"]
        if r["score"] > worst:
            worst, worst_id = r["score"], r["id"]
    appetite = prep["input"]["appetite"]
    for r in residual:
        r["band"] = band(r["score"])
        r["meets"] = r["score"] <= appetite + EPS
    sched = schedule(ids)
    return {"ids": ids, "cost": en["cost"][m], "weeks": sched["goLive"], "schedule": sched["rows"],
            "residual": residual, "worst": worst, "worstId": worst_id, "sum": total,
            "meets": worst <= appetite + EPS, "withinBudget": en["cost"][m] <= prep["input"]["budget"], "mask": m}


def marginal(prep, en, m):
    """What happens if one technique (and anything that depends on it) is dropped."""
    out = []
    n = prep["n"]
    for i in range(n):
        if not (m >> i) & 1:
            continue
        tid = prep["ids"][i]
        if (prep["mustMask"] >> i) & 1:
            out.append({"id": tid, "locked": True})
            continue
        drop, grew = 1 << i, True
        while grew:
            grew = False
            for j in range(n):
                if (m >> j) & 1 and not (drop >> j) & 1 and prep["reqMask"][j] & drop:
                    drop |= 1 << j
                    grew = True
        m2 = m & ~drop
        d = describe(prep, en, m2)
        out.append({"id": tid, "locked": (drop & prep["mustMask"]) != 0,
                    "alsoDrops": [x for x in mask_ids(prep, drop) if x != tid],
                    "saves": en["cost"][m] - en["cost"][m2], "worstWithout": d["worst"],
                    "worstIdWithout": d["worstId"], "meetsWithout": d["meets"]})
    return out


def analyse(raw_input):
    """Search every combination of usable techniques and report the plans that matter."""
    inp = normalise_input(raw_input)
    prep = prepare(inp)
    en = enumerate_plans(prep)
    N = en["N"]
    risk = prep["risk"]
    probs = [r["prob"] for r in risk]
    impacts = [r["I"] for r in risk]
    P = len(PRINCIPLES)
    worst = [0.0] * N
    total = [0.0] * N
    prod = en["prod"]
    for m in range(N):
        w = 0
        s = 0
        for p in range(P):
            sc = from_prob(probs[p] * prod[p][m]) * impacts[p]
            s += sc
            if sc > w:
                w = sc
        worst[m] = w
        total[m] = s
    feasible = [mask_feasible(prep, m) for m in range(N)]
    found = _search(prep, en, worst, total, feasible)

    def plan(m):
        if m is None:
            return None
        d = describe(prep, en, m)
        d["marginal"] = marginal(prep, en, m)
        return d

    notes = list(prep["notes"])
    best = plan(found["best"])
    if best is None:
        must_ids = mask_ids(prep, prep["mustMask"])
        notes.append("No plan fits in %s: the techniques that must be included take %s on their own."
                     % (weeks_phrase(inp["weeks"]), weeks_phrase(schedule(must_ids)["goLive"])))
    inherent_worst = 0
    for r in risk:
        if r["score"] > inherent_worst:
            inherent_worst = r["score"]
    return {
        "input": inp,
        "notes": notes,
        "risk": risk,
        "inherentWorst": inherent_worst,
        "techniques": prep["status"],
        "usable": list(prep["ids"]),
        "cheapest": plan(found["cheapest"]),
        "inBudget": plan(found["inBudget"]),
        "best": best,
        "frontier": [{"cost": en["cost"][m], "worst": worst[m], "ids": mask_ids(prep, m)} for m in found["frontier"]],
        "plansSearched": sum(1 for f in feasible if f),
    }


def evaluate_plan(raw_input, ids):
    """Score a plan put together by hand. Prerequisites are added automatically."""
    inp = normalise_input(raw_input)
    prep = prepare(inp)
    notes, chosen = [], []

    def add(tid):
        if tid in chosen:
            return
        if tid not in prep["ids"]:
            name = TECHNIQUES[tid]["name"] if tid in TECHNIQUES else tid
            notes.append("%s cannot be used here; left out." % name)
            return
        for r in TECHNIQUES[tid].get("requires", []):
            if r not in ids and r not in chosen:
                notes.append("%s needs %s, so that was added." % (TECHNIQUES[tid]["name"], TECHNIQUES[r]["name"].lower()))
            add(r)
        chosen.append(tid)

    for tid in ids:
        add(tid)
    for i in range(prep["n"]):
        if (prep["mustMask"] >> i) & 1 and prep["ids"][i] not in chosen:
            notes.append("%s is required, so it was added." % TECHNIQUES[prep["ids"][i]]["name"])
            chosen.append(prep["ids"][i])
    m = 0
    for tid in chosen:
        m |= 1 << prep["ids"].index(tid)
    prods = [1] * len(PRINCIPLES)
    for i in range(prep["n"]):
        if (m >> i) & 1:
            for p in range(len(PRINCIPLES)):
                prods[p] = prods[p] * prep["miss"][i][p]
    residual = residual_for(prep["risk"], prods)
    worst, total, worst_id, cost = 0, 0, residual[0]["id"], 0
    for r in residual:
        total += r["score"]
        if r["score"] > worst:
            worst, worst_id = r["score"], r["id"]
        r["band"] = band(r["score"])
        r["meets"] = r["score"] <= inp["appetite"] + EPS
    for i in range(prep["n"]):
        if (m >> i) & 1:
            cost += prep["cost"][i]
    sched = schedule(mask_ids(prep, m))
    return {"ids": mask_ids(prep, m), "cost": cost, "weeks": sched["goLive"], "schedule": sched["rows"],
            "residual": residual, "worst": worst, "worstId": worst_id, "sum": total,
            "meets": worst <= inp["appetite"] + EPS, "withinBudget": cost <= inp["budget"],
            "fitsDeadline": sched["goLive"] <= inp["weeks"], "mask": m, "notes": notes}
