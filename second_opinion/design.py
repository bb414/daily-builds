"""The experiment design: which messages exist, which are scams, and what the checker says.

This mirrors the item bank inside the browser app (app/index.html). Only the
fields needed for scoring and simulation are kept here; the message text lives
in the app. A test checks that the two stay identical.
"""

FORMAT = "second-opinion-session"
VERSION = 1
PHASES = ("before", "with", "after")
CONFIDENCE_LEVELS = (50, 60, 70, 80, 90, 100)
ADVICE_STYLES = ("verdict", "confidence", "reason")


def _checker(item_id, truth, difficulty, verdict, confidence):
    return {
        "id": item_id, "role": "checker", "pair": None, "truth": truth, "difficulty": difficulty,
        "ai_verdict": verdict, "ai_confidence": confidence,
    }


def _solo(item_id, pair, truth, difficulty):
    return {
        "id": item_id, "role": "solo", "pair": pair, "truth": truth, "difficulty": difficulty,
        "ai_verdict": None, "ai_confidence": None,
    }


ITEMS = [
    _checker("m01", "scam", "easy", "scam", 94),
    _checker("m02", "scam", "easy", "scam", 97),
    _checker("m03", "scam", "medium", "scam", 88),
    _checker("m04", "scam", "medium", "scam", 91),
    _checker("m05", "scam", "medium", "scam", 83),
    _checker("m06", "scam", "easy", "scam", 96),
    _checker("m07", "scam", "hard", "genuine", 71),
    _checker("m08", "scam", "hard", "genuine", 76),
    _checker("m09", "genuine", "easy", "genuine", 87),
    _checker("m10", "genuine", "easy", "genuine", 90),
    _checker("m11", "genuine", "easy", "genuine", 82),
    _checker("m12", "genuine", "easy", "genuine", 85),
    _checker("m13", "genuine", "easy", "genuine", 93),
    _checker("m14", "genuine", "medium", "genuine", 80),
    _checker("m15", "genuine", "medium", "scam", 78),
    _checker("m16", "genuine", "medium", "scam", 84),
    _solo("m17", "p1", "scam", "easy"),
    _solo("m18", "p1", "scam", "easy"),
    _solo("m19", "p2", "scam", "medium"),
    _solo("m20", "p2", "scam", "medium"),
    _solo("m21", "p3", "scam", "hard"),
    _solo("m22", "p3", "scam", "hard"),
    _solo("m23", "p4", "genuine", "easy"),
    _solo("m24", "p4", "genuine", "easy"),
    _solo("m25", "p5", "genuine", "medium"),
    _solo("m26", "p5", "genuine", "medium"),
    _solo("m27", "p6", "genuine", "hard"),
    _solo("m28", "p6", "genuine", "hard"),
]

ITEM_BY_ID = {item["id"]: item for item in ITEMS}


def make_rng(seed):
    """Seeded generator matching the app's mulberry32, bit for bit."""
    state = seed & 0xFFFFFFFF

    def rng():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rng


def _shuffle(items, rng):
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = int(rng() * (i + 1))
        out[i], out[j] = out[j], out[i]
    return out


def _base36(n):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def _ai_right(item):
    return item["ai_verdict"] is not None and item["ai_verdict"] == item["truth"]


def normalise_condition(condition=None, seed=0):
    """How advice is shown and whether feedback is on. 'random' assigns an advice
    style from the seed, exactly as the app does."""
    condition = condition or {}
    requested = condition.get("advice")
    random_assignment = requested == "random" or condition.get("assignment") == "random"
    advice = requested if requested in ADVICE_STYLES else "reason"
    if requested == "random":
        advice = ADVICE_STYLES[(seed & 0xFFFFFFFF) % len(ADVICE_STYLES)]
    return {
        "advice": advice,
        "feedback": condition.get("feedback") is True,
        "assignment": "random" if random_assignment else "fixed",
    }


def build_session(seed, condition=None):
    """Build the order of a session exactly as the app does for the same seed."""
    if isinstance(seed, bool) or not isinstance(seed, (int, float)) or seed != seed or seed in (float("inf"), float("-inf")):
        s = 1
    else:
        s = int(abs(seed)) % 4294967296
    rng = make_rng(s)
    pairs = {}
    for item in ITEMS:
        if item["role"] == "solo":
            pairs.setdefault(item["pair"], []).append(item)
    before, after = [], []
    for key in sorted(pairs):
        members = sorted(pairs[key], key=lambda it: it["id"])
        if rng() < 0.5:
            before.append(members[0])
            after.append(members[1])
        else:
            before.append(members[1])
            after.append(members[0])
    before = _shuffle(before, rng)
    after = _shuffle(after, rng)
    checker = _shuffle([it for it in ITEMS if it["role"] == "checker"], rng)
    for i in range(2):
        if not _ai_right(checker[i]):
            for j in range(2, len(checker)):
                if _ai_right(checker[j]):
                    checker[i], checker[j] = checker[j], checker[i]
                    break
    trials = []

    def add(item, phase):
        trial = {"item": item["id"], "phase": phase, "position": len(trials) + 1,
                 "truth": item["truth"], "initial": None}
        if phase == "with":
            trial["ai"] = {"verdict": item["ai_verdict"], "confidence": item["ai_confidence"]}
            trial["final"] = None
        trials.append(trial)

    for item in before:
        add(item, "before")
    for item in checker:
        add(item, "with")
    for item in after:
        add(item, "after")
    return {
        "format": FORMAT,
        "version": VERSION,
        "id": "so-" + _base36(s),
        "seed": s,
        "condition": normalise_condition(condition, s),
        "trials": trials,
    }
