"""The Skill Fade model, ported line for line from the browser app.

Every random draw happens in the same order as in ``app/index.html`` and the
random number generator is the same (Mulberry32), so for the same settings both
versions produce the same numbers. ``tests/test_parity.py`` checks this.
"""

import math
import re

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
    "timeThink": 1.0,
    "timeCheck": 0.3,
    "timeGlance": 0.3,
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
    ("driftAt", "stress", 0, 500, 0, True),
    ("driftAccuracy", "stress", 0.5, 0.99, 0.65, False),
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


# Accepts numbers and plain decimal strings only ("0.7", "120", "1e-3"); anything else is rejected.
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
    """Fills in defaults, clamps every number to its allowed range and rejects bad values."""
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
    # A stress test can only make the AI worse.
    if out["driftAccuracy"] > out["aiAccuracy"]:
        out["driftAccuracy"] = out["aiAccuracy"]
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
                misleadChances=0, misled=0, consulted=0, deferred=0, engaged=0, switched=0,
                misleadChancesAfter=0, misledAfter=0, minutes=0)


def derived(p):
    """Values computed once per run: calibrated skill intercepts and blind-spot mixing."""
    sd_d = p["difficultySpread"]
    rho = p["errorOverlap"]
    return {
        "sd_d": sd_d,
        "human_mu": calibrate_intercept(p["humanAccuracy"], math.sqrt(p["skillSpread"] * p["skillSpread"] + sd_d * sd_d)),
        "ai_mu": calibrate_intercept(p["aiAccuracy"], sd_d),
        "ai_mu_after": calibrate_intercept(p["driftAccuracy"], sd_d),
        "shock_at": p["driftAt"] if 0 < p["driftAt"] < p["rounds"] else 0,
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
    ai_mu_after, shock_at = ctx["ai_mu_after"], ctx["shock_at"]
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
        shocked = shock_at > 0 and r >= shock_at
        p_h = sigmoid(s - d)
        p_belief = sigmoid(ai_mu - d_ai)  # how likely the AI "thinks" it is to be right
        p_a = sigmoid(ai_mu_after - d_ai) if shocked else p_belief
        human_right = rng.uniform() < p_h
        ai_right = rng.uniform() < p_a
        self_conf = clamp(sigmoid(logit(p_h) + c["metaNoise"] * rng.normal()), 0.5, 0.99)
        ai_conf = clamp(sigmoid(conf_scale * logit(p_belief) + c["confNoise"] * rng.normal()), 0.5, 0.99)
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
            if track is not None:
                track["ai"][r] += 1
        if shocked and disagree and not ai_right:
            k["misleadChancesAfter"] += 1
            if not final_right and wf != "none":
                k["misledAfter"] += 1
        k["minutes"] += c["timeGlance"] if deferred else c["timeThink"] + (c["timeCheck"] if seen else 0)
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
    track = {"cp": cp, "team": [0.0] * rounds, "ai": [0.0] * rounds, "trust": [0.0] * rounds, "skill": [0.0] * len(cp)}
    k = new_counts()
    end_trust = 0.0
    for i in range(people):
        _s0, _s1, trust = run_person(p, ctx, mix_seed(p["seed"], i), k, track)
        end_trust += trust

    n = people * rounds

    def ratio(a, b):
        return a / b if b > 0 else None

    skill = [v / people for v in track["skill"]]
    trust_series = [v / people for v in track["trust"]]
    team_acc, human_alone, ai_acc = k["team"] / n, k["human"] / n, k["ai"] / n

    def mean_of(arr, start, stop):
        t = 0.0
        for j in range(start, stop):
            t += arr[j]
        return t / ((stop - start) * people)

    at = ctx["shock_at"]
    shock = {
        "at": at,
        "teamBefore": mean_of(track["team"], 0, at),
        "teamAfter": mean_of(track["team"], at, rounds),
        "aiBefore": mean_of(track["ai"], 0, at),
        "aiAfter": mean_of(track["ai"], at, rounds),
        "misledAfter": None if wf == "none" else ratio(k["misledAfter"], k["misleadChancesAfter"]),
        "trustAtShock": trust_series[at],
        "trustEnd": end_trust / people,
    } if at else None
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
        "minutesPerCase": k["minutes"] / n,
        "shock": shock,
        "counts": k,
        "cases": n,
        "series": {
            "team": [v / people for v in track["team"]],
            "trust": trust_series,
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


def verdict_for(result, control):
    key, lift, gap = classify(result, control)
    out = {"key": key, "label": VERDICTS[key]["label"], "text": VERDICTS[key]["text"], "lift": lift, "skillGap": gap,
           "timeSaved": 1 - result["minutesPerCase"] / control["minutesPerCase"], "shock": None}
    if result["shock"]:
        out["shock"] = {"teamAfter": result["shock"]["teamAfter"], "aloneAfter": control["shock"]["teamAfter"],
                        "gap": result["shock"]["teamAfter"] - control["shock"]["teamAfter"]}
    return out


def analyse(src=None):
    """Runs the chosen workflow and the no-AI comparison group (same people, same cases)."""
    p = normalise_params(src)
    result = simulate(p)
    control = result if p["workflow"] == "none" else simulate(dict(p, workflow="none"))
    return {"result": result, "control": control, "verdict": verdict_for(result, control)}


def compare_workflows(src=None):
    """Runs all four workflows on the same people and cases."""
    p = normalise_params(src)
    control = simulate(dict(p, workflow="none"))
    rows = []
    for wf in WORKFLOW_KEYS:
        result = control if wf == "none" else simulate(dict(p, workflow=wf))
        rows.append({"workflow": wf, "result": result, "control": control, "verdict": verdict_for(result, control)})
    return rows


# Assumptions the robustness check moves down and up, one at a time: (key, mode, amount).
SENSITIVITY = [
    ("humanAccuracy", "abs", 0.08),
    ("aiAccuracy", "abs", 0.06),
    ("errorOverlap", "abs", 0.3),
    ("aiOverconfidence", "abs", 0.3),
    ("initialTrust", "abs", 0.2),
    ("feedbackRate", "abs", 0.2),
    ("learningRate", "rel", 0.5),
    ("decayRate", "rel", 0.5),
    ("complacency", "abs", 0.2),
    ("aversion", "abs", 1.5),
]
# Settings that cannot change what happens to people working without the AI.
CONTROL_FREE = ["aiAccuracy", "errorOverlap", "aiOverconfidence", "initialTrust", "complacency", "aversion", "decayRate"]

PARAM_LABELS = {
    "humanAccuracy": "People's starting accuracy",
    "initialTrust": "Starting trust in the AI",
    "aiAccuracy": "AI accuracy",
    "errorOverlap": "Shared blind spots",
    "aiOverconfidence": "AI overconfidence",
    "feedbackRate": "Feedback after each case",
    "rounds": "Cases per person",
    "driftAt": "AI gets worse after case",
    "driftAccuracy": "AI accuracy after the change",
    "learningRate": "Learning from practice",
    "decayRate": "Skill decay from disuse",
    "complacency": "Rubber-stamping (AI first)",
    "requestThreshold": "Ask threshold (on request)",
    "trustRate": "Trust update speed",
    "aversion": "Error sensitivity",
    "skillSpread": "Differences between people",
    "difficultySpread": "Spread of case difficulty",
    "people": "People simulated",
    "seed": "Random seed",
}


def _round6(x):
    return math.floor(x * 1e6 + 0.5) / 1e6


def _spec(key):
    for spec in PARAMS:
        if spec[0] == key:
            return spec
    return None


def sensitivity(src=None):
    """Moves each key assumption down and up and records how the verdict's two measures respond."""
    p = normalise_params(src)
    base_control = simulate(dict(p, workflow="none"))
    base = base_control if p["workflow"] == "none" else simulate(p)
    b_key, b_lift, b_gap = classify(base, base_control)
    rows = []
    for key, mode, amount in SENSITIVITY:
        _k, _g, lo, hi, _d, _i = _spec(key)
        v = p[key]
        low_v = _round6(clamp(v - amount if mode == "abs" else v * (1 - amount), lo, hi))
        high_v = _round6(clamp(v + amount if mode == "abs" else v * (1 + amount), lo, hi))

        def run_at(value):
            q = normalise_params(dict(p, **{key: value}))
            control = base_control if key in CONTROL_FREE else simulate(dict(q, workflow="none"))
            result = control if p["workflow"] == "none" else simulate(q)
            c_key, lift, gap = classify(result, control)
            return {"value": q[key], "lift": lift, "skillGap": gap, "verdict": c_key}

        rows.append({"key": key, "base": v, "low": run_at(low_v), "high": run_at(high_v)})
    return {"workflow": p["workflow"], "base": {"lift": b_lift, "skillGap": b_gap, "verdict": b_key}, "rows": rows}


def whole_pct(x):
    return "%d%%" % math.floor(x * 100 + 0.5)


def explain(a):
    """Plain-English reasons for the result, built from the numbers (matches the browser app)."""
    r, c, p = a["result"], a["control"], a["result"]["params"]
    out = []
    if p["workflow"] == "none":
        if p["feedbackRate"] == 0:
            tail = "Without feedback, practice alone does not improve their judgement."
        elif p["learningRate"] == 0:
            tail = "Learning from practice is set to zero, so their judgement stays where it started."
        else:
            tail = "Feedback on %s of cases lets them improve with practice." % whole_pct(p["feedbackRate"])
        out.append("Working alone, people reach %s accuracy. %s" % (whole_pct(r["teamAccuracy"]), tail))
        return out
    if r["aiRealisedAccuracy"] > c["teamAccuracy"] + 0.02:
        out.append("The AI is right more often than people working alone (%s against %s), so leaning on it raises accuracy."
                   % (whole_pct(r["aiRealisedAccuracy"]), whole_pct(c["teamAccuracy"])))
    else:
        out.append("The AI is not clearly better than people working alone (%s against %s), so leaning on it cannot lift accuracy much."
                   % (whole_pct(r["aiRealisedAccuracy"]), whole_pct(c["teamAccuracy"])))
    if r["deferralRate"] > 0.2:
        out.append("People accepted the AI's answer without thinking on %s of cases. Those cases give no practice%s"
                   % (whole_pct(r["deferralRate"]), ", so their own skill fades." if p["decayRate"] > 0 else "."))
    if p["feedbackRate"] < 0.3:
        out.append("People find out the right answer on only %s of cases, so they learn slowly and their trust barely tracks how good the AI really is."
                   % whole_pct(p["feedbackRate"]))
    if r["misledRate"] is not None and r["misledRate"] > 0.6:
        tail = ", helped by an AI that sounds more certain than it is." if p["aiOverconfidence"] >= 0.5 and p["showConfidence"] else "."
        out.append("When the AI was wrong and they were right, they still went with the AI %s of the time%s"
                   % (whole_pct(r["misledRate"]), tail))
    if r["rescueRate"] is not None and r["rescueRate"] < 0.5:
        out.append("When the AI was right and they were wrong, they kept their own answer %s of the time, so much of the AI's value is lost."
                   % whole_pct(1 - r["rescueRate"]))
    if p["errorOverlap"] >= 0.7:
        out.append("The AI struggles on the same cases people do, so it rarely rescues them where it matters most.")
    if r["complementarity"] > 0.005:
        out.append("The pair beats both the AI alone and people alone: each catches some of the other's mistakes.")
    elif r["teamAccuracy"] < r["aiRealisedAccuracy"] - 0.02:
        out.append("The pair does worse than the AI would on its own (%s against %s): people overrule it when it is right."
                   % (whole_pct(r["teamAccuracy"]), whole_pct(r["aiRealisedAccuracy"])))
    if p["workflow"] in ("human_first", "on_request") and a["verdict"]["skillGap"] > 0.005:
        out.append("Seeing the AI disagree, then learning who was right, teaches people faster than practising alone.")
    if a["verdict"]["shock"] and a["verdict"]["shock"]["gap"] < -0.005:
        out.append("After the AI got worse, people using it did worse than people working alone: trust and lost practice made the change hard to spot.")
    return out


def read_settings_file(obj):
    """Accepts the JSON file the browser app downloads (or a flat dict of settings)."""
    if not isinstance(obj, dict):
        raise ValueError("The file does not contain Skill Fade settings.")
    params = obj["params"] if isinstance(obj.get("params"), dict) else obj
    if not any(key in params for key, *_rest in PARAMS) and "workflow" not in params:
        raise ValueError("The file does not contain Skill Fade settings.")
    return normalise_params(params)


def moving_average(values, window):
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        out.append(total / min(i + 1, window))
    return out
