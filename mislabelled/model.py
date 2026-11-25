"""The Mislabelled model: a synthetic statement, a generic transaction categoriser and the
corrections that teach it.

This is a line-by-line port of the MODEL block in app/index.html. Every calculation uses the
same operations in the same order, and the logarithm and exponential are built from basic
arithmetic, so the two versions give bit-identical results (tests/test_agreement.py checks it).
"""

import json
import math
import os
import re

M32 = 0xFFFFFFFF
LN2 = 0.6931471805599453
SQRT2 = 1.4142135623730951
NORM_SD = 0.5773502691896258  # sd of the sum of four uniforms
REF_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

with open(os.path.join(os.path.dirname(__file__), "data.json"), encoding="utf-8") as _fh:
    DATA = json.load(_fh)

CATS = DATA["categories"]
C = len(CATS)
MERCHANTS = {m["id"]: m for m in DATA["merchants"]}
PERSONAS = {p["id"]: p for p in DATA["personas"]}
NOISE = set(DATA["noise"]) | set(DATA["towns"])

STRATEGIES = [
    {"id": "random", "label": "Random spot checks", "short": "Random"},
    {"id": "unsure", "label": "Least confident first", "short": "Least confident"},
    {"id": "biggest", "label": "Biggest amounts first", "short": "Biggest"},
    {"id": "common", "label": "Most common merchants first", "short": "Most common"},
    {"id": "risk", "label": "Most money at risk first", "short": "Money at risk"},
]
STRATEGY_IDS = [s["id"] for s in STRATEGIES]

_DIGIT = re.compile(r"[0-9]")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


# ---------- deterministic arithmetic (identical in JavaScript and Python) ----------

def mulberry32(seed):
    state = seed & M32

    def rand():
        nonlocal state
        state = (state + 0x6D2B79F5) & M32
        t = ((state ^ (state >> 15)) * (state | 1)) & M32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & M32)) & M32) ^ t
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return rand


def fnv1a(text):
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & M32
    return h


def seed_for(seed, label):
    return (fnv1a(label) ^ (seed & M32)) & M32


def ln(x):
    """Natural log from + - * / only, matching the JavaScript version bit for bit."""
    if not (x > 0) or x == math.inf:
        raise ValueError("ln needs a positive finite number")
    e = 0
    m = x
    while m >= 2:
        m /= 2
        e += 1
    while m < 1:
        m *= 2
        e -= 1
    if m > SQRT2:
        m /= 2
        e += 1
    s = (m - 1) / (m + 1)
    s2 = s * s
    term = s
    total = 0
    for k in range(14):
        total += term / (2 * k + 1)
        term *= s2
    return 2 * total + e * LN2


def exp(x):
    if x < -745:
        return 0
    if x > 709:
        raise OverflowError("exp overflow")
    k = math.floor(x / LN2 + 0.5)
    r = x - k * LN2
    term = 1
    total = 1
    for i in range(1, 15):
        term *= r / i
        total += term
    if k > 0:
        for _ in range(k):
            total *= 2
    else:
        for _ in range(-k):
            total /= 2
    return total


def pick(rng, arr):
    return arr[math.floor(rng() * len(arr))]


def days_in_month(y, m):
    if m == 2:
        return 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
    return 30 if m in (4, 6, 9, 11) else 31


def date_of(day_index):
    y, m, d = DATA["start"][0], DATA["start"][1], DATA["start"][2] + day_index
    while d > days_in_month(y, m):
        d -= days_in_month(y, m)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return {"y": y, "m": m, "d": d, "iso": "%d-%02d-%02d" % (y, m, d)}


def draw_pennies(rng, mean, spread):
    s = rng() + rng() + rng() + rng()
    z = (s - 2) / NORM_SD
    a = mean * (1 + spread * z)
    if a < 0.5:
        a = 0.5
    return math.floor(a * 100 + 0.5)


def ref_code(rng, n):
    return "".join(REF_CHARS[math.floor(rng() * len(REF_CHARS))] for _ in range(n))


def init_state(rng, towns):
    town = pick(rng, towns)
    stores = [1000 + math.floor(rng() * 9000), 1000 + math.floor(rng() * 9000)]
    prefix = pick(rng, DATA["cardPrefixes"])
    ref = "".join(str(math.floor(rng() * 10)) for _ in range(8))
    return {"town": town, "stores": stores, "prefix": prefix, "ref": ref}


def describe(rng, m, st, entry):
    style = m["style"]
    if style == "store":
        s = m["name"]
        if len(m["suffixes"]) > 0 and rng() < 0.35:
            s += " " + pick(rng, m["suffixes"])
        s += " " + str(st["stores"][0] if rng() < 0.8 else st["stores"][1]) + " " + st["town"]
        return s
    if style == "local":
        return st["prefix"] + m["name"] + " " + st["town"]
    if style == "online":
        s = pick(rng, m["variants"])
        if "#" in s:
            s = s.replace("#", ref_code(rng, 6), 1)
        return s
    if style == "wallet":
        return "PAYWALLET *" + "".join(m["name"].split(" ")) + " " + st["town"]
    if style == "dd":
        return "DD " + m["name"] + " " + st["ref"]
    if style == "transfer":
        return "TO " + entry["payee"] + " REF " + pick(rng, entry["memos"])
    raise ValueError("unknown style " + style)


# ---------- the synthetic statement ----------

def generate_statement(persona_id, weeks, seed):
    if persona_id not in PERSONAS:
        raise ValueError("unknown persona " + str(persona_id))
    p = PERSONAS[persona_id]
    weeks = max(1, min(52, math.floor(weeks)))
    rng = mulberry32(seed_for(seed, "statement:" + persona_id))
    monthly_states = [init_state(rng, p["towns"]) for _ in p["monthly"]]
    habit_states = [init_state(rng, p["towns"]) for _ in p["habits"]]
    habit_weight = []
    for h in p["habits"]:
        total = 0
        for i in range(7):
            total += h["days"][i]
        habit_weight.append(total)
    tx = []

    def add(entry, st, day, wd, dt):
        pennies = draw_pennies(rng, entry["amt"], entry["spread"])
        desc = describe(rng, MERCHANTS[entry["m"]], st, entry)
        tx.append({
            "id": len(tx), "day": day, "wd": wd, "date": dt["iso"],
            "month": "%d-%02d" % (dt["y"], dt["m"]),
            "desc": desc, "pennies": pennies, "cat": CATS.index(entry["cat"]), "merchant": entry["m"],
        })

    for day in range(weeks * 7):
        wd = day % 7
        week = day // 7
        dt = date_of(day)
        for i, mon in enumerate(p["monthly"]):
            if "from" in mon and week < mon["from"]:
                continue
            if "until" in mon and week >= mon["until"]:
                continue
            if mon["day"] == dt["d"]:
                add(mon, monthly_states[i], day, wd, dt)
        for i, h in enumerate(p["habits"]):
            u = rng()
            if "from" in h and week < h["from"]:
                continue
            if "until" in h and week >= h["until"]:
                continue
            lam = h["perWeek"] * h["days"][wd] / habit_weight[i]
            n = math.floor(lam)
            if u < lam - n:
                n += 1
            for _ in range(n):
                add(h, habit_states[i], day, wd, dt)
    return {"persona": persona_id, "weeks": weeks, "seed": seed, "tx": tx}


# ---------- what the app reads from a transaction ----------

def amount_band(pennies):
    b = 0
    bands = DATA["amountBands"]
    while b < len(bands) and pennies >= bands[b] * 100:
        b += 1
    return b


def featurise(desc, pennies, wd):
    raw = _NON_ALNUM.sub(" ", desc.upper()).strip().split(" ")
    channels = DATA["channels"]
    channel = "CARD"
    if len(raw) > 0 and raw[0] in channels:
        channel = channels[raw[0]]
    kept = []
    for t in raw:
        if t == "" or _DIGIT.search(t):
            continue
        if t in channels or t in NOISE:
            continue
        kept.append(t)
    key = " ".join(kept[:2]) if kept else "(blank)"
    feats = ["c:" + channel, "m:" + key]
    seen = set()
    for t in kept:
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        feats.append("w:" + t)
    feats.append("a:" + str(amount_band(pennies)))
    feats.append("d:we" if wd >= 5 else "d:wd")
    return {"key": key, "feats": feats}


# ---------- the generic model every new user starts with ----------

_POP_CACHE = None


def build_population():
    global _POP_CACHE
    if _POP_CACHE is not None:
        return _POP_CACHE
    P = DATA["population"]
    rng = mulberry32(seed_for(P["seed"], "population"))
    docs = []

    def add_doc(m, entry, amt, cat):
        st = init_state(rng, DATA["towns"])
        desc = describe(rng, m, st, entry)
        pennies = draw_pennies(rng, amt, P["spread"])
        wd = math.floor(rng() * 7)
        docs.append({"desc": desc, "feats": featurise(desc, pennies, wd)["feats"], "cat": CATS.index(cat)})

    for m in DATA["merchants"]:
        if not m["known"]:
            continue
        for _ in range(P["perChain"]):
            add_doc(m, None, m["popAmt"], m["pop"])
    for g in P["generic"]:
        for _ in range(P["perGeneric"]):
            name = pick(rng, P["neutral"])
            if rng() < 0.4:
                name += " " + pick(rng, P["neutral"])
            if len(g["words"]) > 0:
                name += " " + pick(rng, g["words"])
            style = pick(rng, g["styles"])
            compact = "".join(name.split(" "))
            m = {"name": name, "style": style, "suffixes": [], "variants": [name + " #", compact + ".COM"]}
            entry = None
            if style == "transfer":
                entry = {"payee": pick(rng, P["initials"]) + " " + pick(rng, P["surnames"]), "memos": P["memos"]}
            add_doc(m, entry, g["amt"], g["cat"])
    vocab = {}
    counts = [[] for _ in range(C)]
    docs_per_cat = [0] * C
    totals = [0] * C
    for d in docs:
        docs_per_cat[d["cat"]] += 1
        for f in d["feats"]:
            if f not in vocab:
                vocab[f] = len(vocab)
                for c2 in range(C):
                    counts[c2].append(0)
            counts[d["cat"]][vocab[f]] += 1
            totals[d["cat"]] += 1
    _POP_CACHE = {"docs": docs, "vocab": vocab, "counts": counts, "docsPerCat": docs_per_cat, "totals": totals}
    return _POP_CACHE


# ---------- naive Bayes that learns from the user's corrections ----------

class Model:
    def __init__(self, statement, weight=None, temperature=None):
        pop = build_population()
        self.alpha = DATA["model"]["alpha"]
        self.weight = DATA["model"]["weight"] if weight is None else weight
        self.temperature = DATA["model"]["temperature"] if temperature is None else temperature
        vocab = dict(pop["vocab"])
        n = len(statement["tx"])
        self.fids = []
        self.keys = []
        for tx in statement["tx"]:
            f = featurise(tx["desc"], tx["pennies"], tx["wd"])
            self.keys.append(f["key"])
            ids = []
            for feat in f["feats"]:
                if feat not in vocab:
                    vocab[feat] = len(vocab)
                ids.append(vocab[feat])
            self.fids.append(ids)
        self.V = len(vocab)
        self.vocab = vocab
        self.counts = []
        self.docs = []
        self.totals = []
        for c in range(C):
            row = list(pop["counts"][c]) + [0] * (self.V - len(pop["counts"][c]))
            self.counts.append(row)
            self.docs.append(pop["docsPerCat"][c])
            self.totals.append(pop["totals"][c])
        self.postings = [None] * self.V
        for t in range(n):
            for fid in self.fids[t]:
                if self.postings[fid] is None:
                    self.postings[fid] = []
                lst = self.postings[fid]
                if not lst or lst[-1] != t:
                    lst.append(t)
        self.ln_memo = {}
        self.class_term = [self.lnc(self.docs[c] + 1) for c in range(C)]
        self.den_term = [self.lnc(self.totals[c] + self.alpha * self.V) for c in range(C)]
        self.feat_sum = [[self.sum_for(t, c) for c in range(C)] for t in range(n)]
        self.pred = [0] * n
        self.conf = [0.0] * n
        self.probs = [None] * n
        self.stamp = [0] * n
        self.stamp_no = 0
        for t in range(n):
            self.predict_one(t)

    def lnc(self, x):
        v = self.ln_memo.get(x)
        if v is None:
            v = ln(x)
            self.ln_memo[x] = v
        return v

    def sum_for(self, t, c):
        row = self.counts[c]
        s = 0
        for fid in self.fids[t]:
            s += self.lnc(row[fid] + self.alpha)
        return s

    def scores(self, t):
        F = len(self.fids[t])
        fs = self.feat_sum[t]
        return [self.class_term[c] + fs[c] - F * self.den_term[c] for c in range(C)]

    def predict_one(self, t):
        s = self.scores(t)
        best = 0
        for c in range(1, C):
            if s[c] > s[best]:
                best = c
        z = 0
        ex = []
        for c in range(C):
            d = (s[c] - s[best]) / self.temperature
            e = 0 if d < -40 else exp(d)
            ex.append(e)
            z += e
        self.pred[t] = best
        self.conf[t] = 1 / z
        self.probs[t] = [ex[c] / z for c in range(C)]

    def learn(self, t, c, sign=1):
        """Count a checked payment's features `weight` times towards category c.
        sign=-1 takes a lesson back out (used when a checked payment is re-filed)."""
        ids = self.fids[t]
        w = -self.weight if sign == -1 else self.weight
        row = self.counts[c]
        for fid in ids:
            row[fid] += w
        self.docs[c] += w
        self.totals[c] += w * len(ids)
        self.class_term[c] = self.lnc(self.docs[c] + 1)
        self.den_term[c] = self.lnc(self.totals[c] + self.alpha * self.V)
        self.stamp_no += 1
        for fid in ids:
            lst = self.postings[fid]
            if lst is None:
                continue
            for u in lst:
                if self.stamp[u] != self.stamp_no:
                    self.stamp[u] = self.stamp_no
                    self.feat_sum[u][c] = self.sum_for(u, c)
        for t2 in range(len(self.fids)):
            self.predict_one(t2)


# ---------- a user's session: what the app shows after any checks ----------

class Session:
    def __init__(self, statement, weight=None, temperature=None):
        self.statement = statement
        self.model = Model(statement, weight=weight, temperature=temperature)
        self.labels = [-1] * len(statement["tx"])
        self.checks = 0
        self.order = []

    def reported(self, t):
        return self.labels[t] if self.labels[t] >= 0 else self.model.pred[t]

    def reported_all(self):
        return [self.reported(t) for t in range(len(self.labels))]

    def correct(self, t, label):
        before = self.labels[t]
        if before >= 0:
            # re-filing a payment already checked: forget the old lesson, keep one check
            self.model.learn(t, before, -1)
            self.order.remove(t)
        else:
            self.checks += 1
        self.labels[t] = label
        self.order.append(t)
        self.model.learn(t, label)

    def metrics(self):
        return metrics(self.statement, self.reported_all())


def metrics(statement, reported):
    true_totals = [0] * C
    app_totals = [0] * C
    n = len(statement["tx"])
    correct = 0
    correct_p = 0
    total = 0
    for t, tx in enumerate(statement["tx"]):
        total += tx["pennies"]
        true_totals[tx["cat"]] += tx["pennies"]
        app_totals[reported[t]] += tx["pennies"]
        if reported[t] == tx["cat"]:
            correct += 1
            correct_p += tx["pennies"]
    gap = 0
    for c in range(C):
        gap += abs(app_totals[c] - true_totals[c])
    mis_p = gap / 2
    return {
        "n": n,
        "correct": correct,
        "accuracy": correct / n if n > 0 else 1,
        "totalP": total,
        "correctP": correct_p,
        "valueAccuracy": correct_p / total if total > 0 else 1,
        "misP": mis_p,
        "misPct": mis_p * 100 / total if total > 0 else 0,
        "trueTotals": true_totals,
        "appTotals": app_totals,
    }


# ---------- which transaction should the app ask the user to check next? ----------

def choose_next(strategy, session, rng, allowed=None):
    """Pick the next payment to ask about. `allowed` optionally limits the choice."""
    model = session.model
    tx = session.statement["tx"]
    labels = session.labels
    n = len(tx)
    best = -1

    def is_open(i):
        return labels[i] < 0 and (allowed is None or allowed(i))

    if strategy == "random":
        pool = [t for t in range(n) if is_open(t)]
        if not pool:
            return -1
        return pool[math.floor(rng() * len(pool))]
    if strategy == "biggest":
        for t in range(n):
            if not is_open(t):
                continue
            if best < 0 or tx[t]["pennies"] > tx[best]["pennies"]:
                best = t
        return best
    if strategy == "unsure":
        for t in range(n):
            if not is_open(t):
                continue
            if best < 0 or model.conf[t] < model.conf[best]:
                best = t
        return best
    order = []
    stats = {}
    if strategy == "common":
        checked_keys = {model.keys[t] for t in range(n) if labels[t] >= 0}
        for t in range(n):
            k = model.keys[t]
            if not is_open(t) or k in checked_keys:
                continue
            if k not in stats:
                stats[k] = {"count": 0, "first": t}
                order.append(k)
            stats[k]["count"] += 1
        best_key = None
        for k in order:
            if best_key is None or stats[k]["count"] > stats[best_key]["count"]:
                best_key = k
        if best_key is None:
            return choose_next("unsure", session, rng, allowed)
        return stats[best_key]["first"]
    if strategy == "risk":
        for t in range(n):
            if not is_open(t):
                continue
            k = model.keys[t]
            r = tx[t]["pennies"] * (1 - model.conf[t])
            if k not in stats:
                stats[k] = {"risk": 0, "top": t, "topRisk": r}
                order.append(k)
            stats[k]["risk"] += r
            if r > stats[k]["topRisk"]:
                stats[k]["topRisk"] = r
                stats[k]["top"] = t
        best_key = None
        for k in order:
            if best_key is None or stats[k]["risk"] > stats[best_key]["risk"]:
                best_key = k
        return -1 if best_key is None else stats[best_key]["top"]
    raise ValueError("unknown strategy " + str(strategy))


def answer(statement, t, rng, slip):
    """What the person taps: the true pot, unless a slip sends it to another one."""
    truth = statement["tx"][t]["cat"]
    if rng() < slip:
        return (truth + 1 + math.floor(rng() * (C - 1))) % C
    return truth


def summarise(m):
    return {"misPct": m["misPct"], "misP": m["misP"], "accuracy": m["accuracy"], "valueAccuracy": m["valueAccuracy"]}


def run_curve(statement, strategy, checks=60, slip=0, seed=None, weight=None, temperature=None):
    session = Session(statement, weight=weight, temperature=temperature)
    rng = mulberry32(seed_for(statement["seed"] if seed is None else seed, "sim:" + strategy))
    points = [summarise(session.metrics())]
    picks = []
    for _ in range(checks):
        t = choose_next(strategy, session, rng)
        if t < 0:
            break
        session.correct(t, answer(statement, t, rng, slip))
        picks.append(t)
        points.append(summarise(session.metrics()))
    return {"strategy": strategy, "points": points, "picks": picks}


def checks_to_target(points, target):
    for k, p in enumerate(points):
        if p["misPct"] <= target:
            return k
    return None


def compare_strategies(statement, checks=60, target=5, slip=0, seed=None, weight=None, temperature=None):
    out = []
    for s in STRATEGIES:
        curve = run_curve(statement, s["id"], checks=checks, slip=slip, seed=seed, weight=weight,
                          temperature=temperature)
        out.append({
            "strategy": s["id"],
            "label": s["label"],
            "points": curve["points"],
            "picks": curve["picks"],
            "toTarget": checks_to_target(curve["points"], target),
        })
    return out


# ---------- living with the app: a few checks each week, months go by ----------

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def metrics_for(statement, reported, indices):
    return metrics({"tx": [statement["tx"][i] for i in indices]}, [reported[i] for i in indices])


def run_weekly(statement, strategy, per_week=3, slip=0, seed=None, weight=None, temperature=None):
    """Each Sunday the person answers up to per_week checks about that week's payments.
    When a calendar month ends, the app's view of that month is scored as it stood then."""
    if strategy == "none":
        per_week = 0
    session = Session(statement, weight=weight, temperature=temperature)
    rng = mulberry32(seed_for(statement["seed"] if seed is None else seed, "weekly:" + strategy))
    tx = statement["tx"]
    last_day = statement["weeks"] * 7 - 1
    months = []
    week_start = [0]

    def in_week(i):
        return week_start[0] <= tx[i]["day"] <= week_start[0] + 6

    for day in range(last_day + 1):
        if day % 7 == 6:
            week_start[0] = day - 6
            for _ in range(per_week):
                t = choose_next(strategy, session, rng, in_week)
                if t < 0:
                    break
                session.correct(t, answer(statement, t, rng, slip))
        dt = date_of(day)
        if day == last_day or date_of(day + 1)["m"] != dt["m"]:
            key = "%d-%02d" % (dt["y"], dt["m"])
            idx = [i for i, t in enumerate(tx) if t["month"] == key]
            m = metrics_for(statement, session.reported_all(), idx)
            first_day = max(0, day - dt["d"] + 1)
            months.append({
                "month": key, "name": MONTHS[dt["m"] - 1], "from": date_of(first_day)["d"], "to": dt["d"],
                "partial": date_of(first_day)["d"] > 1 or dt["d"] < days_in_month(dt["y"], dt["m"]),
                "misPct": m["misPct"], "misP": m["misP"], "totalP": m["totalP"], "n": m["n"],
                "accuracy": m["accuracy"], "checks": session.checks,
            })
    return {"strategy": strategy, "months": months, "checks": session.checks}


def compare_weekly(statement, per_week=3, slip=0, seed=None, weight=None, temperature=None):
    out = []
    for s in [{"id": "none", "label": "Never checks"}] + STRATEGIES:
        r = run_weekly(statement, s["id"], per_week=per_week, slip=slip, seed=seed, weight=weight,
                       temperature=temperature)
        out.append({"strategy": s["id"], "label": s["label"], "months": r["months"], "checks": r["checks"]})
    return out


# ---------- explanations and robustness ----------

BANDS = [(0, 0.5, "Under 50% sure"), (0.5, 0.8, "50 to 80% sure"), (0.8, 0.95, "80 to 95% sure"),
         (0.95, 2, "95% sure or more")]


def confidence_bands(session):
    """How often the app is right at each level of confidence, and how much misfiled money it was sure about.
    Only payments the person has not checked are included."""
    tx = session.statement["tx"]
    model = session.model
    out = [{"lo": lo, "hi": hi, "label": label, "n": 0, "right": 0, "totalP": 0, "wrongP": 0} for lo, hi, label in BANDS]
    wrong_p = 0
    sure_wrong_p = 0
    for t in range(len(tx)):
        if session.labels[t] >= 0:
            continue
        c = model.conf[t]
        b = 0
        while b < len(out) - 1 and c >= out[b]["hi"]:
            b += 1
        band = out[b]
        band["n"] += 1
        band["totalP"] += tx[t]["pennies"]
        if model.pred[t] == tx[t]["cat"]:
            band["right"] += 1
        else:
            band["wrongP"] += tx[t]["pennies"]
            wrong_p += tx[t]["pennies"]
            if c >= 0.8:
                sure_wrong_p += tx[t]["pennies"]
    return {"bands": out, "wrongP": wrong_p, "sureWrongP": sure_wrong_p,
            "sureShare": sure_wrong_p / wrong_p if wrong_p > 0 else 0}


def winners(results):
    """Strategies that did best on one statement: fewest checks to the target or, if none got there,
    the lowest wrong pot at the end. Ties share the win."""
    reached = [r for r in results if r["toTarget"] is not None]
    if reached:
        best = min(r["toTarget"] for r in reached)
        return [r["strategy"] for r in reached if r["toTarget"] == best]
    low = min(r["points"][-1]["misPct"] for r in results)
    return [r["strategy"] for r in results if r["points"][-1]["misPct"] == low]


def quantile(values, q):
    """Linear-interpolation quantile (the common 'type 7' definition)."""
    xs = sorted(values)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def robustness(persona_id, weeks, seeds, checks=60, target=5, slip=0, weight=None):
    """Replay every strategy on several statements for the same person. Unreached runs count as checks + 1."""
    rows = [{"strategy": s["id"], "label": s["label"], "wins": 0, "reached": 0, "toTargets": []} for s in STRATEGIES]
    for seed in seeds:
        st = generate_statement(persona_id, weeks, seed)
        res = compare_strategies(st, checks=checks, target=target, slip=slip, seed=seed, weight=weight)
        w = winners(res)
        for i, r in enumerate(res):
            if r["strategy"] in w:
                rows[i]["wins"] += 1 / len(w)
            if r["toTarget"] is not None:
                rows[i]["reached"] += 1
            rows[i]["toTargets"].append(checks + 1 if r["toTarget"] is None else r["toTarget"])
    for r in rows:
        med = quantile(r["toTargets"], 0.5)
        r["median"] = None if med > checks else med
        r["runs"] = len(seeds)
    return rows
