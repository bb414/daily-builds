"""Scoring one session: accuracy, appropriate reliance, confidence and a profile.

This is the same logic as the score() function in the browser app. The result
uses the same keys as the app, so results from either side can be compared
directly, and a test runs both on the same sessions to prove they agree.
"""

from .design import CONFIDENCE_LEVELS, FORMAT, PHASES, VERSION

PROFILES = {
    "calibrated": ("Calibrated partner",
                   "You took the checker's advice when it was right and held your ground when it was wrong. "
                   "That is what appropriate reliance looks like."),
    "over": ("Over-reliant",
             "You tended to go along with the checker, including when it was wrong. Its mistakes became your mistakes."),
    "under": ("Under-reliant",
              "You tended to stick with your first answer, even when the checker was right and you were not. "
              "Its help went to waste."),
    "misplaced": ("Second-guesser",
                  "Your changes of mind did not line up with when the checker was right: "
                  "you kept wrong answers and gave up right ones."),
    "takes-advice": ("Open to good advice",
                     "When the checker was right and you were not, you mostly switched. You never faced a case where "
                     "you were right and it was wrong, so we cannot tell whether you would also follow bad advice."),
    "holds-firm": ("Holds firm",
                   "When you were right and the checker was wrong, you mostly kept your answer. You were never wrong "
                   "where it was right, so we cannot tell whether you would take good advice."),
    "untested": ("Not enough disagreements to tell",
                 "Your first answers always matched the checker's verdict, so there was never a moment where relying "
                 "on it, or not, made a difference."),
}


def _answered(response):
    return (isinstance(response, dict) and response.get("answer") in ("scam", "genuine")
            and isinstance(response.get("confidence"), (int, float))
            and not isinstance(response.get("confidence"), bool))


def is_complete(trial):
    if not _answered(trial.get("initial")):
        return False
    if trial.get("phase") == "with":
        return _answered(trial.get("final")) and bool(trial.get("ai"))
    return True


def _ratio(k, n):
    return k / n if n > 0 else None


def _mean(values):
    if not values:
        return None
    total = 0
    for v in values:
        total += v
    return total / len(values)


def _confidence_stats(pairs):
    """pairs: list of (response, truth)."""
    if not pairs:
        return {"n": 0, "accuracy": None, "meanConfidence": None, "brier": None, "overconfidence": None}
    conf = [r["confidence"] / 100 for r, _ in pairs]
    right = [1 if r["answer"] == truth else 0 for r, truth in pairs]
    squared = [(c - k) * (c - k) for c, k in zip(conf, right)]
    accuracy = _mean(right)
    mean_conf = _mean(conf)
    return {
        "n": len(pairs),
        "accuracy": accuracy,
        "meanConfidence": mean_conf,
        "brier": _mean(squared),
        "overconfidence": mean_conf - accuracy,
    }


def profile_for(rair, rsr, n_correctable, n_misleading):
    if rair is None and rsr is None:
        key = "untested"
    elif rair is not None and rsr is not None:
        if rair >= 0.5 and rsr >= 0.5:
            key = "calibrated"
        elif rair >= 0.5:
            key = "over"
        elif rsr >= 0.5:
            key = "under"
        else:
            key = "misplaced"
    elif rair is not None:
        key = "takes-advice" if rair >= 0.5 else "under"
    else:
        key = "holds-firm" if rsr >= 0.5 else "over"
    tentative = key != "untested" and (rair is None or rsr is None or (n_correctable + n_misleading) < 3)
    label, summary = PROFILES[key]
    return {"key": key, "label": label, "summary": summary, "tentative": tentative}


def score(session):
    """Score a session dict (as saved by the app). Unfinished trials are ignored."""
    all_trials = session.get("trials") or [] if isinstance(session, dict) else []
    trials = [t for t in all_trials if is_complete(t)]
    by = {"before": [], "with": [], "after": []}
    for t in trials:
        if t.get("phase") in by:
            by[t["phase"]].append(t)
    w = by["with"]

    def count_right(items, pick):
        return sum(1 for t in items if pick(t) == t["truth"])

    correct = {
        "before": count_right(by["before"], lambda t: t["initial"]["answer"]),
        "withInitial": count_right(w, lambda t: t["initial"]["answer"]),
        "withFinal": count_right(w, lambda t: t["final"]["answer"]),
        "checker": count_right(w, lambda t: t["ai"]["verdict"]),
        "after": count_right(by["after"], lambda t: t["initial"]["answer"]),
    }
    n = {"before": len(by["before"]), "with": len(w), "after": len(by["after"]), "total": len(trials)}
    accuracy = {
        "before": _ratio(correct["before"], n["before"]),
        "withInitial": _ratio(correct["withInitial"], n["with"]),
        "withFinal": _ratio(correct["withFinal"], n["with"]),
        "checker": _ratio(correct["checker"], n["with"]),
        "after": _ratio(correct["after"], n["after"]),
    }

    cells = {
        "bothRight": {"n": 0, "finalRight": 0},
        "checkerRight": {"n": 0, "corrected": 0},
        "checkerWrong": {"n": 0, "heldFirm": 0},
        "bothWrong": {"n": 0, "finalRight": 0},
    }
    toward = away = disagreements = 0
    ai_wrong = followed_wrong = ai_right = followed_right = 0
    for t in w:
        initial_right = t["initial"]["answer"] == t["truth"]
        checker_right = t["ai"]["verdict"] == t["truth"]
        final_right = t["final"]["answer"] == t["truth"]
        if initial_right and checker_right:
            cells["bothRight"]["n"] += 1
            cells["bothRight"]["finalRight"] += final_right
        elif checker_right:
            cells["checkerRight"]["n"] += 1
            cells["checkerRight"]["corrected"] += final_right
        elif initial_right:
            cells["checkerWrong"]["n"] += 1
            cells["checkerWrong"]["heldFirm"] += final_right
        else:
            cells["bothWrong"]["n"] += 1
            cells["bothWrong"]["finalRight"] += final_right
        if t["initial"]["answer"] != t["ai"]["verdict"]:
            disagreements += 1
            if t["final"]["answer"] == t["ai"]["verdict"]:
                toward += 1
        elif t["final"]["answer"] != t["ai"]["verdict"]:
            away += 1
        if checker_right:
            ai_right += 1
            followed_right += t["final"]["answer"] == t["ai"]["verdict"]
        else:
            ai_wrong += 1
            followed_wrong += t["final"]["answer"] == t["ai"]["verdict"]

    for cell in cells.values():
        for key in cell:
            cell[key] = int(cell[key])
    rair = _ratio(cells["checkerRight"]["corrected"], cells["checkerRight"]["n"])
    rsr = _ratio(cells["checkerWrong"]["heldFirm"], cells["checkerWrong"]["n"])
    reliance = {
        "cells": cells,
        "rair": rair,
        "rsr": rsr,
        "overReliance": None if rsr is None else 1 - rsr,
        "underReliance": None if rair is None else 1 - rair,
        "appropriate": _ratio(cells["checkerRight"]["corrected"] + cells["checkerWrong"]["heldFirm"],
                              cells["checkerRight"]["n"] + cells["checkerWrong"]["n"]),
        "disagreements": disagreements,
        "switches": {"towardChecker": toward, "awayFromChecker": away, "total": toward + away},
        "switchRate": _ratio(toward + away, n["with"]),
        "switchWhenDisagree": _ratio(toward, disagreements),
        "followWhenWrong": _ratio(int(followed_wrong), ai_wrong),
        "agreeWhenRight": _ratio(int(followed_right), ai_right),
    }
    complementarity = None
    if n["with"] > 0:
        complementarity = accuracy["withFinal"] - max(accuracy["withInitial"], accuracy["checker"])
    confidence = {
        "before": _confidence_stats([(t["initial"], t["truth"]) for t in by["before"]]),
        "withInitial": _confidence_stats([(t["initial"], t["truth"]) for t in w]),
        "withFinal": _confidence_stats([(t["final"], t["truth"]) for t in w]),
        "after": _confidence_stats([(t["initial"], t["truth"]) for t in by["after"]]),
    }
    change = None
    if accuracy["before"] is not None and accuracy["after"] is not None:
        change = accuracy["after"] - accuracy["before"]
    return {
        "n": n,
        "correct": correct,
        "accuracy": accuracy,
        "reliance": reliance,
        "complementarity": complementarity,
        "confidence": confidence,
        "change": change,
        "profile": profile_for(rair, rsr, cells["checkerRight"]["n"], cells["checkerWrong"]["n"]),
        "complete": n["total"] == len(all_trials) and n["total"] > 0,
    }


def validate_session(obj):
    """Return a list of problems (at most five); an empty list means the session is usable."""
    if not isinstance(obj, dict):
        return ["The file does not contain a session."]
    problems = []
    if obj.get("format") != FORMAT:
        problems.append("This is not a Second opinion results file.")
    version = obj.get("version")
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version > VERSION:
        problems.append("The file was made by a newer, unknown version.")
    trials = obj.get("trials")
    if not isinstance(trials, list) or not trials:
        problems.append("The file has no answers in it.")
        return problems
    for i, t in enumerate(trials):
        where = "Answer %d" % (i + 1)
        if not isinstance(t, dict):
            problems.append(where + " is unreadable.")
            continue
        if t.get("phase") not in PHASES:
            problems.append(where + " has an unknown part.")
        if t.get("truth") not in ("scam", "genuine"):
            problems.append(where + " has no correct answer recorded.")
        for r in (t.get("initial"), t.get("final")):
            if r is None:
                continue
            if not isinstance(r, dict) or r.get("answer") not in ("scam", "genuine"):
                problems.append(where + " has an unreadable answer.")
            if not isinstance(r, dict) or r.get("confidence") not in CONFIDENCE_LEVELS or isinstance(r.get("confidence"), bool):
                problems.append(where + " has an unreadable confidence.")
        if t.get("phase") == "with":
            ai = t.get("ai")
            if not isinstance(ai, dict) or ai.get("verdict") not in ("scam", "genuine"):
                problems.append(where + " is missing the checker's verdict.")
    return problems[:5]
