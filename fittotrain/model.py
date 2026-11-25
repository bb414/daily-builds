"""The Fit to train model: a synthetic CRM, six data defects, a win-probability
model and the gap between its back-test and its live performance.

This is a line-for-line port of the model block in app/index.html. The tests
in tests/test_parity.py prove the two give the same numbers.
"""

import math
import re
from datetime import date, timedelta

GO_LIVE = 540        # day the model goes live (month 18)
END_DAY = 720        # last day deals are created (month 24)
SCORE_DAY = 21       # deals are scored three weeks after creation
N_REPS = 12
LAMBDA = 1.0         # ridge penalty on every coefficient except the intercept
TEST_SHARE = 0.25    # the pilot's random hold-out
BASE_DATE = date(2024, 1, 1)

SEGMENTS = ["SMB", "Mid-market", "Enterprise"]
SOURCES = ["Inbound", "Outbound", "Partner", "Event"]
SEG_MEDIAN = [12000, 45000, 160000]
PLACEHOLDER = [10000, 50000, 150000]
STAKE_BASE = [1.6, 2.6, 3.6]
MEET_BASE = [2.2, 2.8, 3.2]
CHAMP_BASE = [0.30, 0.40, 0.45]
COMP_BASE = [0.30, 0.40, 0.55]
CYCLE_BASE = [40, 70, 110]
SEG_EFF = [0.2, 0, -0.4]
SRC_EFF = [0.3, -0.3, 0.4, 0]

FIELDS = ["stakeholders", "meetings", "champion", "competitor", "discount", "daysToFirst"]
EDITABLE = ["stakeholders", "champion", "competitor"]  # fields win and loss reviews tend to rewrite
FIELD_LABELS = {
    "stakeholders": "Stakeholders engaged",
    "meetings": "Meetings in first 3 weeks",
    "champion": "Champion identified",
    "competitor": "Competitor present",
    "discount": "Discount asked (%)",
    "daysToFirst": "Days to first meeting",
}
FEATURES = ["Intercept", "Stakeholders engaged", "Meetings in first 3 weeks", "Champion identified",
            "Competitor present", "Discount asked (per 10 points)", "Days to first meeting (per 10)",
            "Deal size (log of amount / 10k)", "Mid-market", "Enterprise", "Outbound", "Partner", "Event"]

STEMS = ["Quillon", "Marrowby", "Tessaly", "Brackwen", "Ondrava", "Velloran", "Corvane", "Haldmere",
         "Pinmoor", "Arkenby", "Sallowin", "Dravik", "Elmbrae", "Fodrin", "Gastrell", "Hollinby", "Ivarre",
         "Jastow", "Kelmont", "Lunwick", "Mossgarth", "Nellory", "Orrinby", "Pellisand", "Quarrow", "Ravensill",
         "Stelloway", "Tamberly", "Ulvane", "Varrick", "Wendlow", "Yarrowfen", "Zelbury", "Ashcombe Vale",
         "Brindlow", "Cadwyn", "Dunlarrow", "Esterby", "Felloway", "Grenmoor"]
SUFFIXES = ["Foods", "Logistics", "Health", "Analytics", "Retail", "Energy", "Works", "Systems",
            "Studios", "Partners", "Supply", "Labs"]

DEFECTS = [
    {"key": "blanks", "what": "Share of the six scoring fields left empty when a deal is entered.", "label": "Blank fields", "kind": "Missing data", "max": 0.6,
     "fix": "Make the scoring fields required at the stage they matter, with an explicit \"unknown\" option."},
    {"key": "retrofill", "what": "Share of closed deals whose champion, stakeholder or competitor fields were updated after the deal closed (win reviews, loss reasons).", "label": "Fields edited after the outcome", "kind": "Leakage", "max": 0.8,
     "fix": "Train on field values as they stood at the scoring point (field history or weekly snapshots), not on today\u2019s values."},
    {"key": "zombies", "what": "Share of lost deals never closed out, left open with a close date in the past.", "label": "Zombie deals", "kind": "Missing labels", "max": 0.8,
     "fix": "Auto-close deals 60 days past their close date with no activity, and keep them in training as losses."},
    {"key": "recreated", "what": "Share of won deals that stalled and were re-entered as a new opportunity, with the old record closed as lost.", "label": "Re-created deals", "kind": "Wrong labels", "max": 0.5,
     "fix": "Merge re-created opportunities and give them a \"duplicate\" close reason that keeps them out of training."},
    {"key": "placeholders", "what": "Share of deals entered with a round placeholder amount, corrected only if the deal is won.", "label": "Placeholder amounts", "kind": "Biased values", "max": 0.8,
     "fix": "Require a sized amount by the proposal stage and flag round numbers in pipeline reviews."},
    {"key": "loggingShift", "what": "Share of meetings that hand logging missed before calendar sync switched on at go-live.", "label": "Meetings logged by hand", "kind": "Drift", "max": 0.7,
     "fix": "Backfill historical meetings from calendars, or retrain once calendar sync has run for a quarter."},
]
DEFECT_KEYS = [d["key"] for d in DEFECTS]

PRESETS = {
    "clean": {"label": "Spotless", "blanks": 0, "retrofill": 0, "zombies": 0, "recreated": 0, "placeholders": 0, "loggingShift": 0},
    "tidy": {"label": "Tidy team", "blanks": 0.1, "retrofill": 0.05, "zombies": 0.05, "recreated": 0.03, "placeholders": 0.1, "loggingShift": 0.1},
    "typical": {"label": "Typical CRM", "blanks": 0.3, "retrofill": 0.35, "zombies": 0.35, "recreated": 0.15, "placeholders": 0.35, "loggingShift": 0.35},
    "chaos": {"label": "Quarter-end chaos", "blanks": 0.5, "retrofill": 0.65, "zombies": 0.65, "recreated": 0.35, "placeholders": 0.65, "loggingShift": 0.55},
}

DEFAULTS = {"seed": 2026, "deals": 4000, "blanks": 0.3, "retrofill": 0.35, "zombies": 0.35, "recreated": 0.15,
            "placeholders": 0.35, "loggingShift": 0.35}

M32 = 0xFFFFFFFF


# ---- Deterministic random numbers (identical to the browser app) ----------
def _imul(a, b):
    return (a * b) & M32


def mulberry32(seed):
    state = [seed & M32]

    def rand():
        a = (state[0] + 0x6D2B79F5) & M32
        state[0] = a
        t = a
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return rand


def mix(a, b):
    h = _imul((a ^ 0x9E3779B9) & M32, 0x85EBCA6B) ^ (b & M32)
    h = _imul(h ^ (h >> 13), 0xC2B2AE35)
    h ^= h >> 16
    return h & M32


def normal(r):
    s = 0.0
    for _ in range(12):
        s += r()
    return s - 6


def sigmoid(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _js_round(x):
    """Math.round in JavaScript: halves round up."""
    return math.floor(x + 0.5)


# ---- Settings ----------------------------------------------------------------
NUMERIC = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$")


def _finite(v):
    """Only plain numbers and decimal strings count, exactly as in the browser app."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str) and NUMERIC.match(v) and v.strip().isascii():
        f = float(v)
    else:
        return None
    return f if math.isfinite(f) else None


def normalise_settings(src=None):
    src = src or {}
    s = {}
    seed = _finite(src.get("seed"))
    s["seed"] = int(math.floor(abs(seed))) % 4294967296 if seed is not None else DEFAULTS["seed"]
    deals = _finite(src.get("deals"))
    s["deals"] = int(clamp(_js_round(deals), 1000, 8000)) if deals is not None else DEFAULTS["deals"]
    for d in DEFECTS:
        v = _finite(src.get(d["key"]))
        s[d["key"]] = clamp(v, 0, d["max"]) if v is not None else DEFAULTS[d["key"]]
    return s


def account_name(k):
    base = STEMS[k % len(STEMS)] + " " + SUFFIXES[(k // len(STEMS)) % len(SUFFIXES)]
    return base + " Ltd" if k % 3 == 0 else base


def twin_name(name, u):
    if u < 0.25:
        return name
    if u < 0.5:
        return name.upper()
    if u < 0.75:
        return name[:-4] + " Limited" if name.endswith(" Ltd") else name + " Ltd"
    return name + " - new"


def norm_name(name):
    n = name.lower()
    if n.endswith(" - new"):
        n = n[:-6]
    if n.endswith(" limited"):
        n = n[:-8]
    if n.endswith(" ltd"):
        n = n[:-4]
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


# ---- The true world ------------------------------------------------------------
def generate_world(settings=None):
    s = normalise_settings(settings)
    n = s["deals"]
    w = mulberry32(mix(s["seed"], 1))
    rep_skill = [0.35 * normal(w) for _ in range(N_REPS)]
    n_accounts = min(len(STEMS) * len(SUFFIXES), max(40, n // 4))
    deals = []
    for i in range(n):
        created = math.floor((i + w()) * END_DAY / n)
        rep = math.floor(w() * N_REPS)
        account = math.floor(w() * n_accounts)
        u = w()
        seg = 0 if u < 0.5 else (1 if u < 0.85 else 2)
        v = w()
        src = 0 if v < 0.35 else (1 if v < 0.65 else (2 if v < 0.85 else 3))
        amount = max(1000, math.floor(SEG_MEDIAN[seg] * math.exp(0.5 * normal(w)) / 100 + 0.5) * 100)
        stakeholders = clamp(math.floor(STAKE_BASE[seg] + normal(w) + 0.5), 1, 8)
        meetings = clamp(math.floor(MEET_BASE[seg] + 1.3 * normal(w) + 0.5), 0, 10)
        champion = 1 if w() < CHAMP_BASE[seg] + (0.1 if src == 2 else 0) else 0
        competitor = 1 if w() < COMP_BASE[seg] else 0
        discount = clamp(math.floor(8 + 5 * normal(w) + 0.5), 0, 30)
        days_to_first = clamp(1 + math.floor(w() * 21) + (5 if src == 1 else 0), 1, 30)
        z = (-1.0 + 0.32 * (stakeholders - 2.5) + 0.28 * (meetings - 2.7) + 1.0 * champion - 0.65 * competitor
             - 0.04 * (discount - 8) - 0.03 * (days_to_first - 11) + SEG_EFF[seg] + SRC_EFF[src]
             - 0.2 * math.log(amount / SEG_MEDIAN[seg]) + rep_skill[rep])
        p_win = sigmoid(z)
        won = w() < p_win
        cycle = math.floor(CYCLE_BASE[seg] * (0.7 + 0.8 * w()) * (1 if won else 0.85))
        deals.append({"id": i, "created": created, "close": created + cycle, "rep": rep, "account": account,
                      "seg": seg, "src": src, "amount": amount, "stakeholders": stakeholders,
                      "meetings": meetings, "champion": champion, "competitor": competitor,
                      "discount": discount, "daysToFirst": days_to_first, "pWin": p_win, "won": won})
    return {"settings": s, "deals": deals, "nAccounts": n_accounts, "repSkill": rep_skill}


# ---- The CRM as it was recorded -------------------------------------------------
def build_crm(world, settings=None):
    s = normalise_settings(settings) if settings else world["settings"]
    streams = [mulberry32(mix(s["seed"], 101 + k)) for k in range(len(DEFECTS))]
    r_b, r_r, r_z, r_d, r_p, r_l = streams
    history, twins, live = [], [], []
    for d in world["deals"]:
        is_live = d["created"] >= GO_LIVE
        kept = 0
        for j in range(10):
            ul = r_l()
            if j < d["meetings"] and ul >= s["loggingShift"]:
                kept += 1
        placeholder = r_p() < s["placeholders"]
        rec = {
            "id": d["id"], "dealId": d["id"], "account": account_name(d["account"]), "rep": d["rep"],
            "seg": d["seg"], "src": d["src"], "created": d["created"], "close": d["close"], "status": "open",
            "amount": d["amount"], "stakeholders": d["stakeholders"],
            "meetings": d["meetings"] if is_live else kept, "champion": d["champion"],
            "competitor": d["competitor"], "discount": d["discount"], "daysToFirst": d["daysToFirst"],
            "editedAfterClose": False, "twin": False, "zombie": False, "placeholder": placeholder,
            "live": is_live, "truth": d,
        }
        for f in FIELDS:
            if r_b() < s["blanks"]:
                rec[f] = None
        uz = r_z()
        ud, ud2, ud3 = r_d(), r_d(), r_d()
        ur = r_r()
        if not is_live and d["close"] < GO_LIVE:
            if d["won"]:
                rec["status"] = "won"
            else:
                pz = min(1, s["zombies"] * (1.4 if d["meetings"] <= 2 else 0.7))
                if uz < pz:
                    rec["zombie"] = True
                else:
                    rec["status"] = "lost"
        if rec["status"] == "won" and ud < s["recreated"]:
            tw = dict(rec)
            tw["id"] = 1000000 + d["id"]
            tw["account"] = twin_name(rec["account"], ud3)
            tw["created"] = max(0, d["created"] - (15 + math.floor(ud2 * 30)))
            tw["close"] = d["created"]
            tw["status"] = "lost"
            tw["twin"] = True
            tw["amount"] = PLACEHOLDER[d["seg"]] if placeholder else d["amount"]
            twins.append(tw)
        if rec["status"] in ("won", "lost") and ur < s["retrofill"]:
            if rec["status"] == "won":
                rec["champion"] = 1
                rec["stakeholders"] = max(d["stakeholders"], 4)
            else:
                rec["competitor"] = 1
                rec["champion"] = 0
            rec["editedAfterClose"] = True
        if placeholder and rec["status"] != "won":
            rec["amount"] = PLACEHOLDER[d["seg"]]
        (live if is_live else history).append(rec)
    return {"history": history + twins, "live": live}


# ---- Logistic regression (ridge-penalised Newton steps) ---------------------------
def field_means(recs):
    means = {}
    for f in FIELDS:
        total, n = 0, 0
        for r in recs:
            v = r[f]
            if v is not None:
                total += v
                n += 1
        means[f] = total / n if n > 0 else 0
    return means


def feature_row(rec, means):
    def g(f):
        return means[f] if rec[f] is None else rec[f]
    return [1, g("stakeholders"), g("meetings"), g("champion"), g("competitor"), g("discount") / 10,
            g("daysToFirst") / 10, math.log(rec["amount"] / 10000), 1 if rec["seg"] == 1 else 0,
            1 if rec["seg"] == 2 else 0, 1 if rec["src"] == 1 else 0, 1 if rec["src"] == 2 else 0,
            1 if rec["src"] == 3 else 0]


def solve(a, b):
    n = len(b)
    m = [list(a[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        piv = c
        for r in range(c + 1, n):
            if abs(m[r][c]) > abs(m[piv][c]):
                piv = r
        if piv != c:
            m[c], m[piv] = m[piv], m[c]
        dg = m[c][c]
        for r in range(c + 1, n):
            fct = m[r][c] / dg
            if fct != 0:
                row_r, row_c = m[r], m[c]
                for k in range(c, n + 1):
                    row_r[k] -= fct * row_c[k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = m[i][n]
        for k in range(i + 1, n):
            s -= m[i][k] * x[k]
        x[i] = s / m[i][i]
    return x


def fit_logistic(xs, ys):
    p = len(xs[0])
    beta = [0.0] * p
    iterations = 0
    for it in range(50):
        iterations = it + 1
        h = [[0.0] * p for _ in range(p)]
        g = [0.0] * p
        for x, yv in zip(xs, ys):
            z = 0
            for j in range(p):
                z += x[j] * beta[j]
            pr = sigmoid(z)
            wgt = pr * (1 - pr)
            if wgt < 1e-9:
                wgt = 1e-9
            resid = yv - pr
            for j in range(p):
                g[j] += x[j] * resid
                wx = wgt * x[j]
                hj = h[j]
                for k in range(j, p):
                    hj[k] += wx * x[k]
        for j in range(p):
            for k in range(j):
                h[j][k] = h[k][j]
        for j in range(1, p):
            h[j][j] += LAMBDA
            g[j] -= LAMBDA * beta[j]
        step = solve(h, g)
        biggest = 0
        for j in range(p):
            beta[j] += step[j]
            if abs(step[j]) > biggest:
                biggest = abs(step[j])
        if biggest < 1e-10:
            break
    return {"beta": beta, "iterations": iterations}


def predict(beta, xs):
    out = []
    for x in xs:
        z = 0
        for j in range(len(beta)):
            z += x[j] * beta[j]
        out.append(sigmoid(z))
    return out


# ---- Metrics -------------------------------------------------------------------
def auc(scores, labels):
    n = len(scores)
    idx = sorted(range(n), key=lambda i: (scores[i], i))
    n_pos = n_neg = 0
    rank_sum = 0.0
    start = 0
    while start < n:
        end = start
        while end + 1 < n and scores[idx[end + 1]] == scores[idx[start]]:
            end += 1
        avg_rank = (start + end) / 2 + 1
        for q in range(start, end + 1):
            if labels[idx[q]]:
                n_pos += 1
                rank_sum += avg_rank
            else:
                n_neg += 1
        start = end + 1
    if n_pos == 0 or n_neg == 0:
        return None
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def evaluate(p, y, amount_forecast, amount_actual):
    n = len(p)
    sum_p = sum_y = brier = fc = act = 0
    for i in range(n):
        sum_p += p[i]
        sum_y += y[i]
        brier += (p[i] - y[i]) * (p[i] - y[i])
        fc += p[i] * amount_forecast[i]
        act += y[i] * amount_actual[i]
    order = sorted(range(n), key=lambda i: (-p[i], i))
    top = math.floor(0.2 * n)
    hit = 0
    for t in range(top):
        hit += y[order[t]]
    bins = [{"n": 0, "p": 0, "y": 0} for _ in range(10)]
    for r in range(n):
        o = order[n - 1 - r]
        b = bins[math.floor(r * 10 / n)]
        b["n"] += 1
        b["p"] += p[o]
        b["y"] += y[o]
    deciles = [{"n": b["n"], "predicted": b["p"] / b["n"] if b["n"] else 0,
                "actual": b["y"] / b["n"] if b["n"] else 0} for b in bins]
    return {
        "n": n, "auc": auc(p, y), "brier": brier / n if n else None,
        "meanPredicted": sum_p / n if n else None, "winRate": sum_y / n if n else None,
        "capture20": hit / sum_y if sum_y > 0 else None,
        "forecast": fc, "actual": act, "forecastError": fc / act - 1 if act > 0 else None,
        "deciles": deciles,
    }


def in_test_split(seed, rid):
    return mix(mix(seed, 7777), rid) / 4294967296 < TEST_SHARE


def labelled(rec):
    return rec["status"] in ("won", "lost")


# ---- Audit: what a CRM owner can see without knowing the truth ------------------
def light(v, amber, red):
    return "red" if v >= red else ("amber" if v >= amber else "green")


def audit_crm(crm, as_of=GO_LIVE):
    """Checks a CRM owner can run without knowing the truth. `as_of` is the extract date."""
    h = crm["history"]
    n = len(h)
    rows = []
    blank_total = 0
    blank_by_field = {}
    for f in FIELDS:
        c = sum(1 for r in h if r[f] is None)
        blank_by_field[f] = c / n if n else 0
        blank_total += c
    blank_share = blank_total / (n * len(FIELDS)) if n else 0
    rows.append({"key": "blanks", "check": "Blank scoring fields", "value": blank_share,
                 "light": light(blank_share, 0.05, 0.15),
                 "detail": "of the six scoring fields are empty across {:,} records".format(n)})

    closed = edited = 0
    for r in h:
        if labelled(r):
            closed += 1
            if r["editedAfterClose"]:
                edited += 1
    edited_share = edited / closed if closed else 0
    rows.append({"key": "retrofill", "check": "Closed deals edited after closing", "value": edited_share,
                 "light": light(edited_share, 0.05, 0.15),
                 "detail": "of {:,} closed deals had a scoring field changed after the close date".format(closed)})

    open_n = stale = 0
    for r in h:
        if r["status"] == "open":
            open_n += 1
            if r["close"] < as_of:
                stale += 1
    stale_share = stale / (closed + stale) if (closed + stale) else 0
    rows.append({"key": "zombies", "check": "Open deals past their close date", "value": stale_share,
                 "light": light(stale_share, 0.05, 0.15),
                 "detail": "of deals due to close by go-live are still open ({:,} of {:,} open deals)".format(stale, open_n)})

    groups = {}
    for i, r in enumerate(h):
        key = norm_name(r["account"])
        if key:
            groups.setdefault(key, []).append(i)
    flagged = set()
    for key in sorted(groups):
        g = groups[key]
        for a in range(len(g)):
            for b in range(a + 1, len(g)):
                ra, rb = h[g[a]], h[g[b]]
                big = max(ra["amount"], rb["amount"])
                if abs(ra["created"] - rb["created"]) <= 60 and abs(ra["amount"] - rb["amount"]) <= 0.05 * big:
                    flagged.add(g[a])
                    flagged.add(g[b])
    dup_share = len(flagged) / n if n else 0
    rows.append({"key": "recreated", "check": "Possible duplicate opportunities", "value": dup_share,
                 "light": light(dup_share, 0.05, 0.15),
                 "detail": "of records share an account, an amount within 5% and a start within 60 days with another record"})

    rnd = sum(1 for r in h if r["amount"] % 10000 == 0)
    round_share = rnd / n if n else 0
    rows.append({"key": "placeholders", "check": "Suspiciously round amounts", "value": round_share,
                 "light": light(round_share, 0.05, 0.15),
                 "detail": "of amounts are exact multiples of 10,000"})

    hm = hn = lm = ln = 0
    for r in h:
        if not r["twin"] and r["meetings"] is not None:
            hm += r["meetings"]
            hn += 1
    for r in crm["live"]:
        if r["meetings"] is not None:
            lm += r["meetings"]
            ln += 1
    if not crm["live"]:
        rows.append({"key": "loggingShift", "check": "Meetings per deal, after go-live vs before", "value": None,
                     "light": "na", "detail": "needs deals scored after go-live: run this check again a quarter in",
                     "afterGoLive": True})
        return {"rows": rows, "blankByField": blank_by_field, "completeness": 1 - blank_share}
    drift = (lm / ln) / (hm / hn) - 1 if (hn and ln and hm > 0) else 0
    rows.append({"key": "loggingShift", "check": "Meetings per deal, after go-live vs before", "value": drift,
                 "light": light(abs(drift), 0.05, 0.15),
                 "detail": "change in logged meetings per deal once the model is live (invisible in the history alone)",
                 "afterGoLive": True})
    return {"rows": rows, "blankByField": blank_by_field, "completeness": 1 - blank_share}


def truth_counts(crm):
    h = crm["history"]
    wins = lost = zombies = twins = retro = closed = plc = meet_true = meet_logged = non_twin = 0
    for r in h:
        if r["twin"]:
            twins += 1
            continue
        non_twin += 1
        if r["placeholder"]:
            plc += 1
        t = r["truth"]
        if t["close"] < GO_LIVE:
            if t["won"]:
                wins += 1
            else:
                lost += 1
            if r["zombie"]:
                zombies += 1
        if labelled(r):
            closed += 1
            if r["editedAfterClose"]:
                retro += 1
        if r["meetings"] is not None:
            meet_true += t["meetings"]
            meet_logged += r["meetings"]
    live_blanks = sum(1 for r in crm["live"] for f in FIELDS if r[f] is None)
    return {
        "historyRecords": len(h), "liveDeals": len(crm["live"]), "closedWins": wins, "closedLosses": lost,
        "blanksAtEntry": live_blanks / (len(crm["live"]) * len(FIELDS)) if crm["live"] else 0,
        "zombies": zombies, "zombieShare": zombies / lost if lost else 0,
        "twins": twins, "twinShare": twins / wins if wins else 0,
        "editedShare": retro / closed if closed else 0,
        "placeholderShare": plc / non_twin if non_twin else 0,
        "meetingsMissed": 1 - meet_logged / meet_true if meet_true else 0,
    }


# ---- The whole experiment ------------------------------------------------------
# ---- Pilot and go-live ------------------------------------------------------------
def split_closed(records, seed):
    train, test = [], []
    for r in records:
        if not labelled(r):
            continue
        (test if in_test_split(seed, r["id"]) else train).append(r)
    return train, test


def fit_pilot(train):
    means = field_means(train)
    fit = fit_logistic([feature_row(r, means) for r in train], [1 if r["status"] == "won" else 0 for r in train])
    return {"beta": fit["beta"], "means": means}


def score_backtest(fit, test):
    p = predict(fit["beta"], [feature_row(r, fit["means"]) for r in test])
    amt = [r["amount"] for r in test]
    return evaluate(p, [1 if r["status"] == "won" else 0 for r in test], amt, amt)


def score_live(fit, live):
    p = predict(fit["beta"], [feature_row(r, fit["means"]) for r in live])
    return evaluate(p, [1 if r["truth"]["won"] else 0 for r in live],
                    [r["amount"] for r in live], [r["truth"]["amount"] for r in live])


def pilot(crm, seed):
    """Train on the history the way a pilot team would, then follow the model into go-live."""
    train, test = split_closed(crm["history"], seed)
    fit = fit_pilot(train)
    return {"fit": fit, "backtest": score_backtest(fit, test), "live": score_live(fit, crm["live"]),
            "trainSize": len(train), "testSize": len(test)}


# ---- An honest back-test: repairs anyone can make from the CRM alone -------------
def median(xs):
    a = sorted(xs)
    return a[len(a) // 2]


def is_round(amount):
    return amount % 10000 == 0


def repair_crm(crm, as_of):
    h = crm["history"]
    groups = {}
    for i, r in enumerate(h):
        key = norm_name(r["account"])
        if key:
            groups.setdefault(key, []).append(i)
    dup_loss = set()
    for key in sorted(groups):
        g = groups[key]
        for a in g:
            ra = h[a]
            if ra["status"] != "lost":
                continue
            for b in g:
                rb = h[b]
                if rb["status"] != "won":
                    continue
                if (abs(ra["created"] - rb["created"]) <= 60
                        and abs(ra["amount"] - rb["amount"]) <= 0.05 * max(ra["amount"], rb["amount"])):
                    dup_loss.add(a)
                    break
    by_seg, every = [[], [], []], []
    for r in h:
        if is_round(r["amount"]):
            continue
        every.append(r["amount"])
        if r["seg"] in (0, 1, 2):
            by_seg[r["seg"]].append(r["amount"])
    all_med = median(every) if every else 10000
    seg_med = [median(xs) if xs else all_med for xs in by_seg]

    def fix_amount(r):
        if not is_round(r["amount"]):
            return r["amount"]
        return seg_med[r["seg"]] if r["seg"] in (0, 1, 2) else all_med

    steps = {"edited": 0, "duplicates": 0, "zombies": 0, "amounts": 0}
    out = []
    for i, r in enumerate(h):
        if i in dup_loss:
            steps["duplicates"] += 1
            continue
        c = dict(r)
        if labelled(c) and c["editedAfterClose"]:
            for f in EDITABLE:
                c[f] = None
            steps["edited"] += 1
        if c["status"] == "open" and c["close"] < as_of - 30:
            c["status"] = "lost"
            steps["zombies"] += 1
        fixed = fix_amount(c)
        if fixed != c["amount"]:
            c["amount"] = fixed
            steps["amounts"] += 1
        out.append(c)
    live = []
    for r in crm["live"]:
        c = dict(r)
        c["amount"] = fix_amount(r)
        live.append(c)
    return {"history": out, "live": live, "steps": steps}


# ---- Which habit to fix first ------------------------------------------------------
def fix_first(world, s, base):
    rows = []
    for k, d in enumerate(DEFECTS):
        if not s[d["key"]] > 0:
            continue
        s2 = dict(s)
        s2[d["key"]] = 0
        p = pilot(build_crm(world, s2), s["seed"])
        rows.append({
            "key": d["key"], "label": d["label"], "kind": d["kind"], "fix": d["fix"], "order": k,
            "liveAuc": p["live"]["auc"], "backtestAuc": p["backtest"]["auc"],
            "gain": p["live"]["auc"] - base["live"]["auc"],
            "illusionDrop": (base["backtest"]["auc"] - base["live"]["auc"]) - (p["backtest"]["auc"] - p["live"]["auc"]),
            "calibration": p["live"]["meanPredicted"] - p["live"]["winRate"],
        })
    rows.sort(key=lambda x: (-x["gain"], x["order"]))
    path = [{"key": None, "label": "As kept today", "liveAuc": base["live"]["auc"], "backtestAuc": base["backtest"]["auc"]}]
    cur = dict(s)
    for row in rows:
        cur[row["key"]] = 0
        q = pilot(build_crm(world, cur), s["seed"])
        path.append({"key": row["key"], "label": row["label"], "liveAuc": q["live"]["auc"], "backtestAuc": q["backtest"]["auc"]})
    return {"rows": rows, "path": path}


# ---- The whole experiment ------------------------------------------------------
def run_lab(settings=None, fixes=True):
    s = normalise_settings(settings)
    world = generate_world(s)
    crm = build_crm(world, s)
    base = pilot(crm, s["seed"])

    clean_train = []
    for d in world["deals"]:
        if d["created"] < GO_LIVE and d["close"] < GO_LIVE and not in_test_split(s["seed"], d["id"]):
            r = dict(d)
            r["status"] = "won" if d["won"] else "lost"
            clean_train.append(r)
    clean_fit = fit_pilot(clean_train)
    live_truth = []
    for r in crm["live"]:
        t = dict(r["truth"])
        t["truth"] = r["truth"]
        live_truth.append(t)
    ceiling = score_live(clean_fit, live_truth)

    rep = repair_crm(crm, GO_LIVE)
    repaired = pilot(rep, s["seed"])

    return {
        "settings": s,
        "backtest": base["backtest"],
        "live": base["live"],
        "ceiling": ceiling,
        "illusion": base["backtest"]["auc"] - base["live"]["auc"],
        "debt": ceiling["auc"] - base["live"]["auc"],
        "repaired": {"backtest": repaired["backtest"], "live": repaired["live"], "steps": rep["steps"],
                     "trainSize": repaired["trainSize"], "testSize": repaired["testSize"]},
        "fixes": fix_first(world, s, base) if fixes else None,
        "model": {"features": FEATURES, "dirty": base["fit"]["beta"], "clean": clean_fit["beta"], "repaired": repaired["fit"]["beta"],
                  "trainSize": base["trainSize"], "testSize": base["testSize"], "cleanTrainSize": len(clean_train)},
        "audit": audit_crm(crm),
        "truth": truth_counts(crm),
        "crm": crm,
    }


# ---- How sure is this? The same settings on other synthetic worlds -----------------
def summarise(xs):
    a = sorted(x for x in xs if x is not None and math.isfinite(x))
    if not a:
        return {"n": 0, "mean": None, "low": None, "high": None, "median": None}
    total = 0
    for x in a:
        total += x
    return {"n": len(a), "mean": total / len(a), "low": a[0], "high": a[-1], "median": a[len(a) // 2]}


def robustness(settings=None, n_worlds=12):
    s = normalise_settings(settings)
    f = _finite(n_worlds)
    n = int(clamp(math.floor(f) if f else 12, 1, 60))
    worlds = []
    for k in range(n):
        sk = dict(s)
        sk["seed"] = (s["seed"] + 1 + k) % 4294967296
        r = run_lab(sk, fixes=False)
        worlds.append({
            "seed": sk["seed"], "backtest": r["backtest"]["auc"], "live": r["live"]["auc"], "ceiling": r["ceiling"]["auc"],
            "illusion": r["illusion"], "debt": r["debt"],
            "repairedBacktest": r["repaired"]["backtest"]["auc"], "repairedLive": r["repaired"]["live"]["auc"],
            "repairedGap": r["repaired"]["backtest"]["auc"] - r["repaired"]["live"]["auc"],
            "bias": r["live"]["meanPredicted"] - r["live"]["winRate"],
            "repairedBias": r["repaired"]["live"]["meanPredicted"] - r["repaired"]["live"]["winRate"],
        })
    keys = ["backtest", "live", "ceiling", "illusion", "debt", "repairedBacktest", "repairedLive", "repairedGap", "bias", "repairedBias"]
    summary = {key: summarise([w[key] for w in worlds]) for key in keys}
    return {
        "settings": s, "worlds": worlds, "summary": summary,
        "overpromised": sum(1 for w in worlds if w["illusion"] > 0.05),
        "repairedHonest": sum(1 for w in worlds if abs(w["repairedGap"]) <= 0.05),
        "repairHelped": sum(1 for w in worlds if w["repairedLive"] > w["live"]),
    }


def day_to_iso(day):
    return (BASE_DATE + timedelta(days=int(day))).isoformat()
