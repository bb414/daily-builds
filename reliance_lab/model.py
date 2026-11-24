"""The Reliance Lab model, ported line for line from the browser app.

Every random draw happens in the same order as in ``app/index.html`` and the
random number generator is the same (Mulberry32), so for the same settings both
versions produce the same numbers. ``tests/test_parity.py`` checks this.
"""

import math

# Fixed behavioural constants (see the README for what each one means).
CONSTANTS = {
    "decisiveness": 2.5,
    "metaNoise": 0.8,
    "confNoise": 0.3,
    "confWeight": 0.6,
    "anchor": 0.4,
    "teachBonus": 1.0,
    "skillCeiling": 4.0,
    "skillFloor": 0.0,
    "minEngage": 0.05,
    "quadPoints": 41,
    "maxCheckpoints": 50,
}

# key, group, min, max, default, integer?
PARAMS = [
    ("humanAccuracy", "people", 0.5, 0.95, 0.7, False),
    ("initialTrust", "people", 0.05, 0.95, 0.6, False),
    ("aiAccuracy", "ai", 0.5, 0.99, 0.85, False),
    ("errorOverlap", "ai", 0.0, 1.0, 0.5, False),
    ("aiOverconfidence", "ai", 0.0, 1.0, 0.2, False),
    ("feedbackRate", "setting", 0.0, 1.0, 0.5, False),
    ("rounds", "setting", 20, 500, 200, True),
    ("learningRate", "advanced", 0.0, 0.01, 0.002, False),
    ("decayRate", "advanced", 0.0, 0.01, 0.0015, False),
    ("complacency", "advanced", 0.0, 1.0, 0.8, False),
    ("requestThreshold", "advanced", 0.5, 0.99, 0.75, False),
    ("trustRate", "advanced", 0.005, 0.1, 0.03, False),
    ("aversion", "advanced", 1.0, 6.0, 3.0, False),
    ("skillSpread", "advanced", 0.0, 1.5, 0.5, False),
    ("difficultySpread", "advanced", 0.2, 2.0, 1.0, False),
    ("people", "advanced", 50, 1000, 300, True),
    ("seed", "advanced", 1, 9999, 42, True),
]

WORKFLOW_KEYS = ["none", "ai_first", "human_first", "on_request"]
WORKFLOW_LABELS = {
    "none": "No AI",
    "ai_first": "AI first",
    "human_first": "Human first",
    "on_request": "On request",
}

PRESETS = {
    "scam_teens": {
        "label": "Scam checks: 16 to 18-year-olds",
        "params": {"humanAccuracy": 0.68, "initialTrust": 0.65, "aiAccuracy": 0.88, "errorOverlap": 0.3,
                   "aiOverconfidence": 0.3, "feedbackRate": 0.25, "rounds": 120, "workflow": "ai_first",
                   "showConfidence": True},
    },
    "invoice_fraud": {
        "label": "Invoice fraud screening: finance team",
        "params": {"humanAccuracy": 0.8, "initialTrust": 0.5, "aiAccuracy": 0.9, "errorOverlap": 0.6,
                   "aiOverconfidence": 0.2, "feedbackRate": 0.6, "rounds": 250, "workflow": "human_first",
                   "showConfidence": True},
    },
    "lead_triage": {
        "label": "Sales lead triage: new sales reps",
        "params": {"humanAccuracy": 0.62, "initialTrust": 0.7, "aiAccuracy": 0.75, "errorOverlap": 0.5,
                   "aiOverconfidence": 0.6, "feedbackRate": 0.8, "rounds": 200, "workflow": "on_request",
                   "showConfidence": True},
    },
}

DEFAULTS = {"workflow": "ai_first", "showConfidence": True}
DEFAULTS.update({key: default for key, _g, _lo, _hi, default, _i in PARAMS})

VERDICTS = {
    "baseline": {"label": "Baseline: no AI",
                 "text": "This is the comparison group. Pick a workflow that uses the AI to see whether it helps or harms."},
    "helper": {"label": "Helper",
               "text": "People are more accurate with the AI, and their own judgement holds up as well as it would have without it."},
    "crutch": {"label": "Crutch",
               "text": "People are more accurate with the AI, but they end up worse on their own than if they had practised without it."},
    "no_lift": {"label": "No lift",
                "text": "The AI does not make people meaningfully more accurate, though their own judgement is not harmed."},
    "liability": {"label": "Liability",
                  "text": "The AI neither makes people more accurate nor protects their own judgement."},
}
TOLERANCE = 0.01

MASK = 0xFFFFFFFF


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def sigmoid(x):
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def logit(p):
    q = clamp(p, 1e-9, 1 - 1e-9)
    return math.log(q / (1 - q))


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

    def normal(self):
        u1 = self.uniform()
        if u1 < 1e-12:
            u1 = 1e-12
        u2 = self.uniform()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


def mix_seed(seed, i):
    h = ((seed & MASK) ^ _imul(i + 1, 0x9E3779B1)) & MASK
    h = _imul(h ^ (h >> 16), 0x85EBCA6B)
    h = _imul(h ^ (h >> 13), 0xC2B2AE35)
    return (h ^ (h >> 16)) & MASK


def _build_quadrature():
    k = CONSTANTS["quadPoints"]
    z, w = [], []
    tot = 0.0
    for i in range(k):
        x = -5 + 10 * i / (k - 1)
        wt = math.exp(-0.5 * x * x)
        z.append(x)
        w.append(wt)
        tot += wt
    return z, [v / tot for v in w]


QUAD_Z, QUAD_W = _build_quadrature()


def expected_accuracy(mu, sd):
    """Expected accuracy for skill ``mu`` (log-odds) over normally distributed case difficulty."""
    t = 0.0
    for z, w in zip(QUAD_Z, QUAD_W):
        t += w * sigmoid(mu + sd * z)
    return t


def calibrate_intercept(target, sd):
    lo, hi = -12.0, 12.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if expected_accuracy(mid, sd) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _parse_bool(v, default):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "off", "")
    return default


def normalise_params(src=None):
    """Fills in defaults, clamps every number to its allowed range and rejects bad values."""
    src = src or {}
    out = {}
    for key, _group, lo, hi, default, is_int in PARAMS:
        raw = src.get(key)
        try:
            v = float("nan") if raw is None or raw == "" or isinstance(raw, bool) else float(raw)
        except (TypeError, ValueError):
            v = float("nan")
        if not math.isfinite(v):
            v = default
        v = clamp(v, lo, hi)
        if is_int:
            v = int(math.floor(v + 0.5))
        out[key] = v
    wf = src.get("workflow")
    out["workflow"] = wf if wf in WORKFLOW_KEYS else DEFAULTS["workflow"]
    out["showConfidence"] = _parse_bool(src.get("showConfidence"), DEFAULTS["showConfidence"])
    return out


def preset_params(key):
    out = dict(DEFAULTS)
    if key in PRESETS:
        out.update(PRESETS[key]["params"])
    return normalise_params(out)


def switch_probability(trust, ai_conf, self_conf, anchor, show_confidence):
    c = CONSTANTS
    perceived = (1 - c["confWeight"]) * trust + c["confWeight"] * ai_conf if show_confidence else trust
    return sigmoid(c["decisiveness"] * (logit(perceived) + anchor - logit(self_conf)))


def checkpoints_for(rounds):
    every = max(1, math.ceil(rounds / CONSTANTS["maxCheckpoints"]))
    return list(range(0, rounds, every)) + [rounds]


def new_counts():
    return dict(team=0, human=0, ai=0, bothRight=0, bothWrong=0, rescueChances=0, rescued=0,
                misleadChances=0, misled=0, consulted=0, deferred=0, engaged=0, switched=0)


def derived(p):
    """Values computed once per run: calibrated skill intercepts and blind-spot mixing."""
    sd_d = p["difficultySpread"]
    rho = p["errorOverlap"]
    return {
        "sd_d": sd_d,
        "human_mu": calibrate_intercept(p["humanAccuracy"], math.sqrt(p["skillSpread"] * p["skillSpread"] + sd_d * sd_d)),
        "ai_mu": calibrate_intercept(p["aiAccuracy"], sd_d),
        "rho": rho,
        "rho_c": math.sqrt(max(0.0, 1 - rho * rho)),
        "conf_scale": 1 + 2 * p["aiOverconfidence"],
    }


def run_person(p, ctx, person_seed, k, track=None):
    """Simulates one person through every case. Updates the counts ``k`` in place.

    ``track`` (optional) holds per-round accumulators for the charts. Returns the
    person's skill (log-odds) before and after, and their final trust.
    """
    c = CONSTANTS
    wf = p["workflow"]
    sd_d, ai_mu, rho, rho_c, conf_scale = ctx["sd_d"], ctx["ai_mu"], ctx["rho"], ctx["rho_c"], ctx["conf_scale"]
    show = p["showConfidence"]
    rng = Rng(person_seed)
    s = ctx["human_mu"] + p["skillSpread"] * rng.normal()
    s_start = s
    trust = p["initialTrust"]
    cp = track["cp"] if track else None
    cpi = 0
    for r in range(p["rounds"]):
        if track is not None:
            if cp[cpi] == r:
                track["skill"][cpi] += expected_accuracy(s, sd_d)
                cpi += 1
            track["trust"][r] += trust
        d = sd_d * rng.normal()
        d_ai = rho * d + rho_c * sd_d * rng.normal()
        p_h = sigmoid(s - d)
        p_a = sigmoid(ai_mu - d_ai)
        human_right = rng.uniform() < p_h
        ai_right = rng.uniform() < p_a
        self_conf = clamp(sigmoid(logit(p_h) + c["metaNoise"] * rng.normal()), 0.5, 0.99)
        ai_conf = clamp(sigmoid(conf_scale * logit(p_a) + c["confNoise"] * rng.normal()), 0.5, 0.99)
        u_engage = rng.uniform()
        u_switch = rng.uniform()
        feedback = rng.uniform() < p["feedbackRate"]
        disagree = human_right != ai_right
        engaged, seen, deferred, switched = True, False, False, False

        if wf == "ai_first":
            seen = True
            engaged = u_engage < max(c["minEngage"], 1 - p["complacency"] * trust)
            if not engaged:
                deferred = True
            elif disagree:
                switched = u_switch < switch_probability(trust, ai_conf, self_conf, c["anchor"], show)
        elif wf == "human_first":
            seen = True
            if disagree:
                switched = u_switch < switch_probability(trust, ai_conf, self_conf, 0, show)
        elif wf == "on_request":
            seen = self_conf < p["requestThreshold"]
            if seen and disagree:
                switched = u_switch < switch_probability(trust, ai_conf, self_conf, 0, show)
        final_right = ai_right if (deferred or switched) else human_right

        if final_right:
            k["team"] += 1
            if track is not None:
                track["team"][r] += 1
        if human_right:
            k["human"] += 1
        if ai_right:
            k["ai"] += 1
        if human_right and ai_right:
            k["bothRight"] += 1
        if not human_right and not ai_right:
            k["bothWrong"] += 1
        if disagree:
            if ai_right:
                k["rescueChances"] += 1
                if final_right and wf != "none":
                    k["rescued"] += 1
            else:
                k["misleadChances"] += 1
                if not final_right and wf != "none":
                    k["misled"] += 1
        if seen:
            k["consulted"] += 1
        if deferred:
            k["deferred"] += 1
        if engaged:
            k["engaged"] += 1
        if switched:
            k["switched"] += 1

        if seen and feedback:
            if ai_right:
                trust = trust + p["trustRate"] * (1 - trust)
            else:
                trust = trust - p["trustRate"] * p["aversion"] * trust
            trust = clamp(trust, 0.01, 0.99)
        if engaged:
            if feedback:
                bonus = 1 + c["teachBonus"] if (seen and disagree) else 1
                s += p["learningRate"] * bonus * max(0.0, c["skillCeiling"] - s)
        else:
            s -= p["decayRate"] * max(0.0, s - c["skillFloor"])
    if track is not None:
        while cpi < len(cp):
            track["skill"][cpi] += expected_accuracy(s, sd_d)
            cpi += 1
    return s_start, s, trust


def simulate(src=None):
    """Runs one workflow for a population of simulated people. Returns a dict of results."""
    p = normalise_params(src)
    wf = p["workflow"]
    ctx = derived(p)
    rounds, people = p["rounds"], p["people"]
    cp = checkpoints_for(rounds)
    track = {"cp": cp, "team": [0.0] * rounds, "trust": [0.0] * rounds, "skill": [0.0] * len(cp)}
    k = new_counts()
    end_trust = 0.0
    for i in range(people):
        _s0, _s1, trust = run_person(p, ctx, mix_seed(p["seed"], i), k, track)
        end_trust += trust

    n = people * rounds

    def ratio(a, b):
        return a / b if b > 0 else None

    skill = [v / people for v in track["skill"]]
    team_acc, human_alone, ai_acc = k["team"] / n, k["human"] / n, k["ai"] / n
    return {
        "params": p,
        "teamAccuracy": team_acc,
        "humanAloneAccuracy": human_alone,
        "aiRealisedAccuracy": ai_acc,
        "complementarity": team_acc - max(human_alone, ai_acc),
        "skillBefore": skill[0],
        "skillAfter": skill[-1],
        "skillChange": skill[-1] - skill[0],
        "rescueRate": None if wf == "none" else ratio(k["rescued"], k["rescueChances"]),
        "misledRate": None if wf == "none" else ratio(k["misled"], k["misleadChances"]),
        "consultRate": k["consulted"] / n,
        "deferralRate": k["deferred"] / n,
        "engagementRate": k["engaged"] / n,
        "trustStart": p["initialTrust"],
        "trustEnd": end_trust / people,
        "counts": k,
        "cases": n,
        "series": {
            "team": [v / people for v in track["team"]],
            "trust": [v / people for v in track["trust"]],
            "skillRounds": cp,
            "skill": skill,
        },
    }


def classify(result, control):
    if result["params"]["workflow"] == "none":
        return "baseline", 0.0, 0.0
    lift = result["teamAccuracy"] - control["teamAccuracy"]
    gap = result["skillAfter"] - control["skillAfter"]
    if lift >= TOLERANCE:
        key = "helper" if gap >= -TOLERANCE else "crutch"
    else:
        key = "no_lift" if gap >= -TOLERANCE else "liability"
    return key, lift, gap


def analyse(src=None):
    """Runs the chosen workflow and the no-AI comparison group, and classifies the outcome."""
    p = normalise_params(src)
    result = simulate(p)
    control = result if p["workflow"] == "none" else simulate(dict(p, workflow="none"))
    key, lift, gap = classify(result, control)
    return {
        "result": result,
        "control": control,
        "verdict": {"key": key, "label": VERDICTS[key]["label"], "text": VERDICTS[key]["text"],
                    "lift": lift, "skillGap": gap},
    }


def moving_average(values, window):
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        out.append(total / min(i + 1, window))
    return out
