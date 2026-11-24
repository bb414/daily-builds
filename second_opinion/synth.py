"""Synthetic participants, for trying out the analysis before collecting real data.

Each synthetic person has four hidden traits: how good they are at spotting scams,
how overconfident they are, how readily they trust the checker, and how much their
own confidence holds them back from switching. Sessions are built in exactly the
same order the app would use for the same seed, and saved in the app's format.

The behavioural assumptions are illustrative, not estimates from data. They exist
so that the analysis pipeline, and a study's sample size, can be tested end to end.
"""

import math
import random

from .design import ITEM_BY_ID, build_session, normalise_condition

# Log-odds of a correct judgement for an average person, by difficulty.
BASE_LOGIT = {"easy": 2.0, "medium": 1.0, "hard": 0.0}

# How each way of showing advice shifts the log-odds of switching to the checker.
# Showing a reason is assumed to raise reliance, on right and wrong advice alike.
ADVICE_SHIFT = {"verdict": -0.3, "confidence": 0.0, "reason": 0.4}


def _sigmoid(x):
    return 1 / (1 + math.exp(-x))


def _round_confidence(p):
    level = int(round(min(1.0, max(0.5, p)) * 10)) * 10
    return min(100, max(50, level))


def draw_person(rng):
    """Draw one synthetic person's hidden traits."""
    return {
        "skill": rng.gauss(0.0, 0.6),
        "bias": rng.gauss(0.08, 0.06),
        "trust": rng.gauss(0.0, 1.0),
        "sensitivity": max(0.0, rng.gauss(1.0, 0.4)),
    }


def _judge(item, skill, bias, rng):
    p = _sigmoid(BASE_LOGIT[item["difficulty"]] + skill)
    correct = rng.random() < p
    other = "genuine" if item["truth"] == "scam" else "scam"
    felt = p + bias + (0.06 if correct else -0.06) + rng.gauss(0.0, 0.07)
    return {"answer": item["truth"] if correct else other, "confidence": _round_confidence(felt)}


def simulate_session(seed, condition=None, person=None, crutch=0.0):
    """Fill a session with one synthetic person's answers.

    crutch is the assumed drop in log-odds of a correct solo judgement after the
    checker phase for a fully trusting person (0 means no effect).
    """
    rng = random.Random(seed)
    person = person or draw_person(rng)
    session = build_session(seed, condition)
    condition = normalise_condition(condition)
    session["synthetic"] = True
    trust = person["trust"]
    shift = ADVICE_SHIFT[condition["advice"]]
    for trial in session["trials"]:
        item = ITEM_BY_ID[trial["item"]]
        if trial["phase"] == "before":
            trial["initial"] = _judge(item, person["skill"], person["bias"], rng)
        elif trial["phase"] == "after":
            skill = person["skill"] - crutch * _sigmoid(person["trust"])
            trial["initial"] = _judge(item, skill, person["bias"], rng)
        else:
            initial = _judge(item, person["skill"], person["bias"], rng)
            trial["initial"] = initial
            ai = trial["ai"]
            if initial["answer"] == ai["verdict"]:
                final = {"answer": initial["answer"], "confidence": min(100, initial["confidence"] + 10)}
            else:
                x = (trust + shift + 4 * (ai["confidence"] / 100 - 0.85)
                     - 4 * person["sensitivity"] * (initial["confidence"] / 100 - 0.75))
                if rng.random() < _sigmoid(x):
                    final = {"answer": ai["verdict"], "confidence": _round_confidence(ai["confidence"] / 100 - 0.1)}
                else:
                    final = {"answer": initial["answer"], "confidence": max(50, initial["confidence"] - 10)}
            trial["final"] = final
            if condition["feedback"]:
                # With feedback, people see when the checker was wrong and trust it less.
                trust += -0.8 if ai["verdict"] != trial["truth"] else 0.1
    return session


def simulate_cohort(n, seed=1, condition=None, crutch=0.0):
    """Simulate n people under one condition. Seeds are derived from seed, so runs repeat."""
    master = random.Random(seed)
    return [simulate_session(master.randrange(1, 2 ** 32), condition, crutch=crutch) for _ in range(n)]
