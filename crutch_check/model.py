"""Core model: message bank, session building, scoring and simulated participants.

Everything here mirrors the model block in app/index.html line for line, so a
session built or scored in Python matches one built or scored in the browser
exactly. tests/test_app.py checks that they agree.
"""

import json
import math
import re
from pathlib import Path

FORMAT = "crutch-check-session"
VERSION = 1

ROUND_LABELS = {1: "On your own", 2: "With the checker", 3: "On your own again"}
CONTROL_ROUND_LABELS = {1: "On your own", 2: "On your own (no checker)", 3: "On your own again"}
ARMS = ("checker", "control")

CONF_SURE = 0.95
CONF_UNSURE = 0.7
MAX_CHECKER_WRONG = 6

PROFILES = {
    "calibrated": "Well calibrated",
    "over_reliant": "Leaning on the checker",
    "under_reliant": "Going it alone",
    "mixed": "Swayed the wrong way",
    "few_disagreements": "Too few disagreements to tell",
    "control": "No checker in round 2",
    "incomplete": "Not finished yet",
}

_BANK_PATH = Path(__file__).with_name("messages.json")
with _BANK_PATH.open(encoding="utf-8") as _f:
    BANK = json.load(_f)
MESSAGES = BANK["messages"]
CUES = BANK["cues"]
BY_ID = {m["id"]: m for m in MESSAGES}


def default_design():
    """The default test design: the checker is wrong on 3 of the 12 assisted messages."""
    return {"checkerWrong": 3, "showReasons": True, "showConfidence": True}


# ---------------------------------------------------------------------------
# Deterministic random numbers (identical to the JavaScript versions)
# ---------------------------------------------------------------------------

_M32 = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & _M32


def mulberry32(seed):
    """A small, fast 32-bit generator. Returns a function giving floats in [0, 1)."""
    state = [seed & _M32]

    def rnd():
        state[0] = (state[0] + 0x6D2B79F5) & _M32
        t = state[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t = ((t + _imul(t ^ (t >> 7), t | 61)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return rnd


def hash_string(text):
    """32-bit FNV-1a over UTF-16 code units, matching JavaScript's charCodeAt."""
    h = 0x811C9DC5
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = _imul(h, 16777619)
    return h


def shuffle(items, rnd):
    """Fisher-Yates shuffle in place, drawing from rnd."""
    for i in range(len(items) - 1, 0, -1):
        j = math.floor(rnd() * (i + 1))
        items[i], items[j] = items[j], items[i]
    return items


def round2(x):
    """Round to 2 decimal places, halves upwards (the same in both languages)."""
    return math.floor(x * 100 + 0.5) / 100


def points(x):
    """Whole percentage points, halves rounded away from zero (the same in both languages)."""
    v = math.floor(abs(x) * 100 + 0.5)
    return -v if x < 0 else v


def other(verdict):
    return "genuine" if verdict == "scam" else "scam"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Building a session
# ---------------------------------------------------------------------------

def assign_arm(study, participant):
    """Reproducible random allocation to the checker or control arm.

    The hash goes through the generator first: the lowest bit of an FNV-1a hash
    only reflects how many characters have odd codes, so it is not random.
    """
    return "checker" if mulberry32(hash_string("arm|" + study + "|" + participant))() < 0.5 else "control"


def participant_seed(study, participant):
    return hash_string(study + "|" + participant)


_NUMERIC = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$")


def _int_or(x, default):
    """Whole number from a number or plain numeric string, else the default (as in the app)."""
    if isinstance(x, bool):
        return default
    if isinstance(x, (int, float)):
        v = float(x)
    elif isinstance(x, str) and _NUMERIC.match(x):
        v = float(x)
    else:
        return default
    return int(v) if math.isfinite(v) else default


def normalise_design(design):
    d = default_design()
    if design:
        d.update({k: design[k] for k in d if k in design})
    d["checkerWrong"] = int(clamp(_int_or(d["checkerWrong"], 3), 0, MAX_CHECKER_WRONG))
    for key in ("showReasons", "showConfidence"):
        if not isinstance(d[key], bool):
            d[key] = default_design()[key]
    return d


def build_session(seed, arm="checker", design=None, participant="", study=""):
    """Pick 28 messages for three rounds and script the checker's advice.

    Round 1 and round 3 (8 messages each) are matched: one easy, two medium and
    one hard message of each kind. Round 2 has 12 messages (two of each kind at
    each difficulty). The checker is wrong on design["checkerWrong"] of the 12,
    split between missed scams and false alarms.
    """
    if arm not in ARMS:
        raise ValueError("arm must be 'checker' or 'control'")
    design = normalise_design(design)
    seed = int(seed) & _M32
    rnd = mulberry32(seed)

    cells = []
    for truth in ("scam", "genuine"):
        for difficulty in (1, 2, 3):
            cell = [m for m in MESSAGES if m["truth"] == truth and m["difficulty"] == difficulty]
            cells.append(shuffle(cell, rnd))

    r1, r2, r3 = [], [], []
    for cell in cells:
        r1.append(cell[0])
        r2.append(cell[1])
        r2.append(cell[2])
        r3.append(cell[3])
    for cell in (cells[1], cells[4]):
        r1.append(cell[4])
        r3.append(cell[5])
    shuffle(r1, rnd)
    shuffle(r2, rnd)
    shuffle(r3, rnd)

    wrong_count = design["checkerWrong"]
    misses = (wrong_count + 1) // 2
    false_alarms = wrong_count // 2
    scam_idx = shuffle([i for i, m in enumerate(r2) if m["truth"] == "scam"], rnd)
    genuine_idx = shuffle([i for i, m in enumerate(r2) if m["truth"] == "genuine"], rnd)
    wrong = set(scam_idx[:misses] + genuine_idx[:false_alarms])
    advice = []
    for i, m in enumerate(r2):
        correct = i not in wrong
        u = rnd()
        confidence = round2(0.78 + 0.2 * u if correct else 0.6 + 0.25 * u)
        advice.append({
            "verdict": m["truth"] if correct else other(m["truth"]),
            "confidence": confidence,
            "correct": correct,
        })

    trials = []
    for rnum, items in ((1, r1), (2, r2), (3, r3)):
        for pos, m in enumerate(items):
            trials.append({
                "round": rnum,
                "position": pos,
                "messageId": m["id"],
                "truth": m["truth"],
                "difficulty": m["difficulty"],
                "channel": m["channel"],
                "checker": dict(advice[pos]) if (rnum == 2 and arm == "checker") else None,
                "initial": None,
                "final": None,
            })
    return {
        "format": FORMAT,
        "version": VERSION,
        "seed": seed,
        "arm": arm,
        "participant": participant,
        "study": study,
        "design": design,
        "trials": trials,
    }


def checker_reasons(trial):
    """The reasons the checker gives: real cues when it is right, decoys when it is wrong."""
    if not trial.get("checker"):
        return []
    m = BY_ID[trial["messageId"]]
    tags = m["cues"] if trial["checker"]["correct"] else m["decoys"]
    return [CUES[t] for t in tags[:3]]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def confidence(resp):
    return CONF_SURE if resp["sure"] else CONF_UNSURE


def p_scam(resp):
    c = confidence(resp)
    return c if resp["verdict"] == "scam" else 1 - c


def _ratio(a, b):
    return None if b == 0 else a / b


def _mean(values):
    # A plain running total on purpose: Python's sum() compensates for rounding
    # error on floats, JavaScript does not, and the two must agree exactly.
    if not values:
        return None
    total = 0.0
    for v in values:
        total += v
    return total / len(values)


def round_stats(trials, key="final"):
    answered = [t for t in trials if t.get(key)]
    n = len(answered)
    correct = hits = misses = fas = crs = sure_n = sure_c = unsure_n = unsure_c = 0
    confs = []
    sq = []
    for t in answered:
        r = t[key]
        right = r["verdict"] == t["truth"]
        correct += right
        if t["truth"] == "scam":
            if right:
                hits += 1
            else:
                misses += 1
        else:
            if right:
                crs += 1
            else:
                fas += 1
        confs.append(confidence(r))
        y = 1 if t["truth"] == "scam" else 0
        sq.append((p_scam(r) - y) ** 2)
        if r["sure"]:
            sure_n += 1
            sure_c += right
        else:
            unsure_n += 1
            unsure_c += right
    accuracy = _ratio(correct, n)
    mean_conf = _mean(confs)
    return {
        "n": n,
        "correct": correct,
        "accuracy": accuracy,
        "scams": hits + misses,
        "genuines": crs + fas,
        "hits": hits,
        "misses": misses,
        "falseAlarms": fas,
        "correctRejections": crs,
        "hitRate": _ratio(hits, hits + misses),
        "falseAlarmRate": _ratio(fas, crs + fas),
        "meanConfidence": mean_conf,
        "brier": _mean(sq),
        "overconfidence": None if n == 0 else mean_conf - accuracy,
        "sure": {"n": sure_n, "correct": sure_c, "accuracy": _ratio(sure_c, sure_n)},
        "unsure": {"n": unsure_n, "correct": unsure_c, "accuracy": _ratio(unsure_c, unsure_n)},
    }


def assisted_stats(trials):
    """How the participant used the checker's advice in round 2 (two-step design)."""
    ts = [t for t in trials if t.get("checker") and t.get("initial") and t.get("final")]
    if not ts:
        return None
    n = len(ts)
    c = {"bothRight": 0, "bothWrong": 0, "switchedToRight": 0, "stayedWrong": 0,
         "keptRight": 0, "switchedToWrong": 0}
    initial_correct = final_correct = checker_correct = 0
    followed_wrong = checker_wrong = rejected_right = switches = other_changes = 0
    for t in ts:
        truth = t["truth"]
        ini = t["initial"]["verdict"]
        fin = t["final"]["verdict"]
        adv = t["checker"]["verdict"]
        i_ok = ini == truth
        f_ok = fin == truth
        a_ok = adv == truth
        initial_correct += i_ok
        final_correct += f_ok
        checker_correct += a_ok
        if fin != ini:
            switches += 1
        if a_ok:
            if fin != adv:
                rejected_right += 1
        else:
            checker_wrong += 1
            if fin == adv:
                followed_wrong += 1
        if i_ok and a_ok:
            c["bothRight"] += 1
            if fin != ini:
                other_changes += 1
        elif not i_ok and not a_ok:
            c["bothWrong"] += 1
            if fin != ini:
                other_changes += 1
        elif a_ok:
            c["switchedToRight" if f_ok else "stayedWrong"] += 1
        else:
            c["keptRight" if f_ok else "switchedToWrong"] += 1
    initial_acc = initial_correct / n
    final_acc = final_correct / n
    checker_acc = checker_correct / n
    disagreements = c["switchedToRight"] + c["stayedWrong"] + c["keptRight"] + c["switchedToWrong"]
    return {
        "n": n,
        "initialCorrect": initial_correct,
        "finalCorrect": final_correct,
        "checkerCorrect": checker_correct,
        "initialAccuracy": initial_acc,
        "finalAccuracy": final_acc,
        "checkerAccuracy": checker_acc,
        "cases": c,
        "disagreements": disagreements,
        "switches": switches,
        "otherChanges": other_changes,
        "rair": _ratio(c["switchedToRight"], c["switchedToRight"] + c["stayedWrong"]),
        "rsr": _ratio(c["keptRight"], c["keptRight"] + c["switchedToWrong"]),
        "checkerWrong": checker_wrong,
        "followedWrong": followed_wrong,
        "overReliance": _ratio(followed_wrong, checker_wrong),
        "checkerRight": n - checker_wrong,
        "rejectedRight": rejected_right,
        "underReliance": _ratio(rejected_right, n - checker_wrong),
        "complementarity": final_acc - max(initial_acc, checker_acc),
    }


def classify(arm, assisted, complete):
    if not complete:
        return "incomplete"
    if arm == "control":
        return "control"
    if assisted is None or assisted["disagreements"] < 2:
        return "few_disagreements"
    rair = assisted["rair"]
    rsr = assisted["rsr"]
    good_rely = rair is None or rair >= 0.5
    good_self = rsr is None or rsr >= 0.5
    if good_rely and good_self:
        return "calibrated"
    if good_self:
        return "under_reliant"
    if good_rely:
        return "over_reliant"
    return "mixed"


def _diff(a, b):
    return None if a is None or b is None else a - b


STRATEGIES = [
    ("yourFinal", "Your final answers"),
    ("yourFirst", "Never use the checker (your first answers)"),
    ("alwaysFollow", "Always follow the checker"),
    ("followConfident", "Follow it only when it is at least 90% sure"),
    ("followWhenUnsure", "Follow it only when you said \"probably\""),
]


def strategies(trials):
    """What would have happened in round 2 under simple rules for using the checker."""
    ts = [t for t in trials if t.get("checker") and t.get("initial") and t.get("final")]
    if not ts:
        return None
    correct = {k: 0 for k, _ in STRATEGIES}
    for t in ts:
        adv = t["checker"]
        ini = t["initial"]
        picks = {
            "yourFinal": t["final"]["verdict"],
            "yourFirst": ini["verdict"],
            "alwaysFollow": adv["verdict"],
            "followConfident": adv["verdict"] if adv["confidence"] >= 0.9 else ini["verdict"],
            "followWhenUnsure": ini["verdict"] if ini["sure"] else adv["verdict"],
        }
        for k, v in picks.items():
            correct[k] += v == t["truth"]
    n = len(ts)
    return [{"key": k, "label": label, "correct": correct[k], "n": n, "accuracy": correct[k] / n}
            for k, label in STRATEGIES]


# Acklam's rational approximation to the inverse normal CDF (relative error < 1.2e-9).
_A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
_B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]


def inv_norm(p):
    if p <= 0 or p >= 1:
        raise ValueError("p must be between 0 and 1")
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return ((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
                / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    if p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(1 - p))
        return -((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
                 / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    q = p - 0.5
    r = q * q
    return ((((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1))


def sdt(trials):
    """Signal detection: sensitivity (d') and bias (c) from final answers.

    Uses the log-linear correction (add 0.5 to each count and 1 to each total)
    so perfect scores stay finite. c above zero means leaning towards
    "genuine" (trusting), below zero leaning towards "scam" (suspicious).
    """
    st = round_stats(trials)
    if st["scams"] == 0 or st["genuines"] == 0:
        return None
    h = (st["hits"] + 0.5) / (st["scams"] + 1)
    f = (st["falseAlarms"] + 0.5) / (st["genuines"] + 1)
    zh, zf = inv_norm(h), inv_norm(f)
    return {"dPrime": zh - zf, "c": -(zh + zf) / 2, "hitRate": st["hitRate"],
            "falseAlarmRate": st["falseAlarmRate"]}


def cue_profile(trials):
    """Which warning signs were on the scams someone missed, and which decoys fooled them."""
    missed, seen, fooled = {}, {}, {}
    missed_n = false_alarms = 0
    for t in trials:
        if not t.get("final"):
            continue
        m = BY_ID[t["messageId"]]
        wrong = t["final"]["verdict"] != t["truth"]
        if t["truth"] == "scam":
            for cue in m["cues"]:
                seen[cue] = seen.get(cue, 0) + 1
                if wrong:
                    missed[cue] = missed.get(cue, 0) + 1
            missed_n += wrong
        elif wrong:
            false_alarms += 1
            for d in m["decoys"]:
                fooled[d] = fooled.get(d, 0) + 1

    def ranked(counts, extra=None):
        keys = sorted(counts, key=lambda k: (-counts[k], k))
        return [dict({"cue": k, "label": CUES[k], "count": counts[k]},
                     **({"seen": extra[k]} if extra else {})) for k in keys]

    return {"missedScams": missed_n, "falseAlarms": false_alarms,
            "missed": ranked(missed, seen), "fooledBy": ranked(fooled)}


def score_session(session):
    """Score a session (complete or not) and return a results dictionary."""
    trials = session["trials"]
    rounds = []
    for rnum in (1, 2, 3):
        st = round_stats([t for t in trials if t["round"] == rnum])
        st["round"] = rnum
        st["planned"] = sum(1 for t in trials if t["round"] == rnum)
        rounds.append(st)
    complete = all(t.get("final") for t in trials) and all(
        t.get("initial") for t in trials if t.get("checker"))
    assisted = assisted_stats(trials) if session["arm"] == "checker" else None
    profile = classify(session["arm"], assisted, complete)
    sdt1 = sdt([t for t in trials if t["round"] == 1])
    sdt3 = sdt([t for t in trials if t["round"] == 3])
    return {
        "arm": session["arm"],
        "complete": complete,
        "rounds": rounds,
        "assisted": assisted,
        "change": {
            "accuracy": _diff(rounds[2]["accuracy"], rounds[0]["accuracy"]),
            "brier": _diff(rounds[2]["brier"], rounds[0]["brier"]),
            "dPrime": _diff(sdt3 and sdt3["dPrime"], sdt1 and sdt1["dPrime"]),
            "c": _diff(sdt3 and sdt3["c"], sdt1 and sdt1["c"]),
        },
        "sdt": {"round1": sdt1, "round3": sdt3},
        "strategies": strategies(trials) if session["arm"] == "checker" else None,
        "cueProfile": cue_profile(trials),
        "profile": profile,
        "profileTitle": PROFILES[profile],
    }


# ---------------------------------------------------------------------------
# Simulated participants (for demos, cohorts and power analysis)
# ---------------------------------------------------------------------------

# The demo in the app uses these seeds: each persona shows its typical pattern.
DEMO_SEEDS = {"session": 2026, "responses": 1}

PERSONAS = {
    "calibrated": {"skill": 0.82, "sureBias": 0.55, "reliance": 0.45, "learning": 0.05},
    "leaner": {"skill": 0.72, "sureBias": 0.45, "reliance": 0.92, "learning": -0.05},
    "loner": {"skill": 0.72, "sureBias": 0.7, "reliance": 0.05, "learning": 0.0},
}


def _respond(truth, p_correct, sure_bias, rnd):
    right = rnd() < p_correct
    verdict = truth if right else other(truth)
    sure = rnd() < clamp(sure_bias + (0.15 if right else -0.15), 0, 1)
    return {"verdict": verdict, "sure": sure, "ms": 2500 + math.floor(rnd() * 9000)}


def simulate_responses(session, persona, seed):
    """Fill a copy of the session with a simulated participant's answers.

    persona: skill (chance of being right on an easy message, 0.12 lower per
    difficulty step), sureBias (how often they say 'definitely'), reliance (how
    often they switch to the checker's answer when they disagree) and learning
    (the change in skill by round 3).
    """
    rnd = mulberry32(int(seed) & _M32)
    out = json.loads(json.dumps(session))
    show_conf = out["design"]["showConfidence"]
    for t in out["trials"]:
        shift = persona["learning"] if t["round"] == 3 else 0
        p = clamp(persona["skill"] - 0.12 * (t["difficulty"] - 1) + shift, 0.05, 0.98)
        own = _respond(t["truth"], p, persona["sureBias"], rnd)
        adv = t.get("checker")
        if adv:
            t["initial"] = own
            u = rnd()
            v = rnd()
            if adv["verdict"] != own["verdict"]:
                ps = persona["reliance"]
                if show_conf and adv["confidence"] >= 0.9:
                    ps += 0.1
                if own["sure"]:
                    ps -= 0.2
                ps = clamp(ps, 0, 1)
                if u < ps:
                    final = {"verdict": adv["verdict"], "sure": v < persona["sureBias"]}
                else:
                    final = {"verdict": own["verdict"], "sure": own["sure"]}
            else:
                final = {"verdict": own["verdict"], "sure": own["sure"] or v < 0.5}
            final["ms"] = 1500 + math.floor(rnd() * 4000)
            t["final"] = final
        else:
            t["initial"] = None
            t["final"] = own
    return out


# ---------------------------------------------------------------------------
# Validation and CSV
# ---------------------------------------------------------------------------

def _is_int(x):
    # JSON cannot tell 1 from 1.0 in JavaScript, so whole-number floats count too.
    if isinstance(x, bool):
        return False
    return isinstance(x, int) or (isinstance(x, float) and x.is_integer())


def _valid_answer(r):
    return (isinstance(r, dict) and r.get("verdict") in ("scam", "genuine")
            and isinstance(r.get("sure"), bool))


def validate_session(session):
    """Raise ValueError with a readable message if the session is not usable.

    The browser app applies exactly the same rules, with the same messages.
    """
    if not isinstance(session, dict) or session.get("format") != FORMAT:
        raise ValueError("not a Crutch check session file")
    if session.get("arm") not in ARMS:
        raise ValueError("session has an unknown group (arm)")
    seed = session.get("seed")
    if not _is_int(seed) or not 0 <= seed <= 4294967295:
        raise ValueError("session has an invalid seed")
    for key in ("participant", "study"):
        if session.get(key) is not None and not isinstance(session[key], str):
            raise ValueError("session has an invalid %s" % key)
    trials = session.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("session has no messages")
    for i, t in enumerate(trials):
        where = "message %d" % (i + 1)
        if not isinstance(t, dict):
            raise ValueError("%s is not a valid record" % where)
        m = BY_ID.get(t.get("messageId")) if isinstance(t.get("messageId"), str) else None
        if m is None:
            raise ValueError("%s has an unknown message id" % where)
        if not _is_int(t.get("round")) or t["round"] not in (1, 2, 3):
            raise ValueError("%s has an invalid round" % where)
        if t.get("truth") != m["truth"]:
            raise ValueError("%s has the wrong answer key" % where)
        if (t.get("difficulty") != m["difficulty"] or isinstance(t.get("difficulty"), bool)
                or t.get("channel") != m["channel"]
                or not _is_int(t.get("position")) or t["position"] < 0):
            raise ValueError("%s does not match the message bank" % where)
        adv = t.get("checker")
        if adv is not None:
            if (not isinstance(adv, dict) or adv.get("verdict") not in ("scam", "genuine")
                    or isinstance(adv.get("confidence"), bool)
                    or not isinstance(adv.get("confidence"), (int, float))
                    or not 0 <= adv["confidence"] <= 1
                    or adv.get("correct") is not (adv["verdict"] == m["truth"])):
                raise ValueError("%s has invalid checker advice" % where)
        for key in ("initial", "final"):
            if t.get(key) is not None and not _valid_answer(t[key]):
                raise ValueError("%s has an invalid %s answer" % (where, key))
    return session


CSV_COLUMNS = ["participant", "study", "arm", "seed", "round", "position", "messageId",
               "truth", "difficulty", "channel", "checkerVerdict", "checkerConfidence",
               "initialVerdict", "initialSure", "initialMs", "finalVerdict", "finalSure",
               "finalMs", "finalCorrect"]


def session_rows(session):
    rows = []
    for t in session["trials"]:
        adv = t.get("checker") or {}
        ini = t.get("initial") or {}
        fin = t.get("final") or {}
        rows.append({
            "participant": session.get("participant", ""),
            "study": session.get("study", ""),
            "arm": session["arm"],
            "seed": session["seed"],
            "round": t["round"],
            "position": t["position"],
            "messageId": t["messageId"],
            "truth": t["truth"],
            "difficulty": t["difficulty"],
            "channel": t["channel"],
            "checkerVerdict": adv.get("verdict", ""),
            "checkerConfidence": adv.get("confidence", ""),
            "initialVerdict": ini.get("verdict", ""),
            "initialSure": "" if not ini else str(ini["sure"]).lower(),
            "initialMs": ini.get("ms", ""),
            "finalVerdict": fin.get("verdict", ""),
            "finalSure": "" if not fin else str(fin["sure"]).lower(),
            "finalMs": fin.get("ms", ""),
            "finalCorrect": "" if not fin else str(fin["verdict"] == t["truth"]).lower(),
        })
    return rows
