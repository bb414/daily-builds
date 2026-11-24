"""Score sessions exported from the browser app ("Download results").

``score_session`` and ``counterfactuals`` are ports of the functions of the same name in the
browser app's MODEL block, and the agreement tests check they give identical answers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .model import DEFAULTS, clamp, logit, norm_inv, normalise

LABELS = ("fraud", "genuine")
FORMAT = "reliance-lab-session"


class SessionError(ValueError):
    """A session file is missing something or has a value out of range."""


def _check_trial(t: dict, i: int) -> None:
    if not isinstance(t, dict):
        raise SessionError(f"Trial {i + 1}: must be an object")
    for key in ("truth", "initial", "ai", "final"):
        if t.get(key) not in LABELS:
            raise SessionError(f'Trial {i + 1}: {key} must be "fraud" or "genuine"')
    c = t.get("initialConfidence")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not (0.5 <= c <= 1):
        raise SessionError(f"Trial {i + 1}: initialConfidence must be between 0.5 and 1")
    a = t.get("aiConfidence")
    if a is not None and (isinstance(a, bool) or not isinstance(a, (int, float)) or not (0 <= a <= 1)):
        raise SessionError(f"Trial {i + 1}: aiConfidence must be between 0 and 1, or null")


def auroc(scores: list[float], outcomes: list[bool]) -> float | None:
    """Area under the ROC curve: how well a score separates correct from incorrect answers."""
    pos = [s for s, o in zip(scores, outcomes) if o]
    neg = [s for s, o in zip(scores, outcomes) if not o]
    if not pos or not neg:
        return None
    wins = 0.0
    for a in pos:
        for b in neg:
            wins += 1.0 if a > b else (0.5 if a == b else 0.0)
    return wins / (len(pos) * len(neg))


OUTCOMES = {
    "agreedRight": "Agreed, both right",
    "sharedMiss": "Agreed, both wrong",
    "goodSwitch": "Switched to a right AI",
    "underRelied": "Overrode a right AI",
    "heldFirm": "Held firm against a wrong AI",
    "overRelied": "Followed a wrong AI",
    "changedAfterAgreeing": "Changed after agreeing",
}


def classify_trial(t: dict) -> str:
    """Which of the seven possible outcomes a single case had."""
    if t["initial"] == t["ai"]:
        if t["final"] != t["initial"]:
            return "changedAfterAgreeing"
        return "agreedRight" if t["initial"] == t["truth"] else "sharedMiss"
    if t["ai"] == t["truth"]:
        return "goodSwitch" if t["final"] == t["ai"] else "underRelied"
    return "heldFirm" if t["final"] == t["initial"] else "overRelied"


def _naive_sum(values) -> float:
    """Left-to-right float sum, like JavaScript's reduce (Python's sum() compensates rounding)."""
    total = 0.0
    for v in values:
        total += v
    return total


def _ratio(num: int, den: int) -> float | None:
    return num / den if den > 0 else None


def score_session(trials: list[dict]) -> dict:
    """Accuracy, reliance and confidence measures for one person's session."""
    if not isinstance(trials, list) or not trials:
        raise SessionError("A session needs at least one trial")
    for i, t in enumerate(trials):
        _check_trial(t, i)
    n = len(trials)
    initial_right = sum(t["initial"] == t["truth"] for t in trials)
    ai_right = sum(t["ai"] == t["truth"] for t in trials)
    final_right = sum(t["final"] == t["truth"] for t in trials)
    agree = sum(t["initial"] == t["ai"] for t in trials)
    switched = sum(t["final"] != t["initial"] for t in trials)
    ai_only_right = [t for t in trials if t["initial"] != t["truth"] and t["ai"] == t["truth"]]
    you_only_right = [t for t in trials if t["initial"] == t["truth"] and t["ai"] != t["truth"]]
    switched_to_ai = sum(t["final"] == t["ai"] for t in ai_only_right)
    kept_own = sum(t["final"] == t["initial"] for t in you_only_right)
    mean_conf = _naive_sum(t["initialConfidence"] for t in trials) / n
    shown = all(isinstance(t.get("aiConfidence"), (int, float)) for t in trials)
    rair = _ratio(switched_to_ai, len(ai_only_right))
    rsr = _ratio(kept_own, len(you_only_right))
    initial_acc = initial_right / n
    ai_acc = ai_right / n
    outcomes = {key: 0 for key in OUTCOMES}
    for t in trials:
        outcomes[classify_trial(t)] += 1
    final_acc = final_right / n
    return {
        "n": n,
        "initialAccuracy": initial_acc,
        "aiAccuracy": ai_acc,
        "finalAccuracy": final_acc,
        "agreeRate": agree / n,
        "switchRate": switched / n,
        "disagreements": n - agree,
        "aiOnlyRight": len(ai_only_right),
        "switchedToAI": switched_to_ai,
        "youOnlyRight": len(you_only_right),
        "keptOwn": kept_own,
        "rair": rair,
        "rsr": rsr,
        "overRelianceRate": None if rsr is None else 1 - rsr,
        "underRelianceRate": None if rair is None else 1 - rair,
        "helpfulSwitches": sum(t["initial"] != t["truth"] and t["final"] == t["truth"] for t in trials),
        "harmfulSwitches": sum(t["initial"] == t["truth"] and t["final"] != t["truth"] for t in trials),
        "meanConfidence": mean_conf,
        "overconfidence": mean_conf - initial_acc,
        "confidenceAuroc": auroc([t["initialConfidence"] for t in trials],
                                 [t["initial"] == t["truth"] for t in trials]),
        "aiConfidenceAuroc": auroc([t["aiConfidence"] for t in trials],
                                   [t["ai"] == t["truth"] for t in trials]) if shown else None,
        "gainOverAI": final_acc - ai_acc,
        "gainOverYou": final_acc - initial_acc,
        "complementarity": final_acc - max(initial_acc, ai_acc),
        "outcomes": outcomes,
    }


def counterfactuals(trials: list[dict], threshold: float = 0.8) -> list[dict]:
    """What simple strategies would have scored on exactly the same cases."""
    for i, t in enumerate(trials):
        _check_trial(t, i)
    n = len(trials)
    shown = all(isinstance(t.get("aiConfidence"), (int, float)) for t in trials)

    def acc(choose) -> float:
        return sum(choose(t) == t["truth"] for t in trials) / n

    return [
        {"key": "you", "label": "Your first call, ignoring the AI", "available": True,
         "accuracy": acc(lambda t: t["initial"])},
        {"key": "ai", "label": "Always take the AI’s answer", "available": True,
         "accuracy": acc(lambda t: t["ai"])},
        {"key": "threshold",
         "label": f"Take the AI’s answer when it shows {round(threshold * 100)}% or more",
         "available": shown,
         "accuracy": acc(lambda t: t["ai"] if t["aiConfidence"] >= threshold else t["initial"])
         if shown else None},
        {"key": "surer", "label": "Go with whoever is surer", "available": shown,
         "accuracy": acc(lambda t: t["ai"] if t["aiConfidence"] > t["initialConfidence"] else t["initial"])
         if shown else None},
        {"key": "final", "label": "What you actually did", "available": True,
         "accuracy": acc(lambda t: t["final"])},
    ]


def d_prime_from_auroc(auc: float | None) -> float | None:
    """Convert an AUROC into the equivalent signal detection d' (equal-variance model)."""
    if auc is None:
        return None
    return math.sqrt(2) * norm_inv(clamp(auc, 0.01, 0.99))


def estimate_params(trials: list[dict]) -> dict:
    """Rough model settings implied by one session (a port of estimateParams in the app)."""
    s = score_session(trials)
    n = len(trials)
    mh = s["initialAccuracy"]
    ma = s["aiAccuracy"]
    both = sum(t["initial"] == t["truth"] and t["ai"] == t["truth"] for t in trials) / n
    den = math.sqrt(mh * (1 - mh) * ma * (1 - ma))
    shown = all(isinstance(t.get("aiConfidence"), (int, float)) for t in trials)
    mean_ai = _naive_sum(t["aiConfidence"] for t in trials) / n if shown else None
    disagreements = [t for t in trials if t["initial"] != t["ai"]]
    followed = sum(t["final"] == t["ai"] for t in disagreements)

    def capped(v: float) -> float:
        return clamp(v, 0.5, 0.99)

    return normalise({
        "human": capped(mh),
        "ai": capped(ma),
        "overlap": clamp((both - mh * ma) / den, -1, 1) if den > 0 else 0.0,
        "humanSignal": DEFAULTS["humanSignal"] if s["confidenceAuroc"] is None
        else clamp(d_prime_from_auroc(s["confidenceAuroc"]), 0, 4),
        "aiSignal": 0.0 if s["aiConfidenceAuroc"] is None
        else clamp(d_prime_from_auroc(s["aiConfidenceAuroc"]), 0, 4),
        "humanBias": clamp(logit(capped(s["meanConfidence"])) - logit(capped(mh)), -2, 2),
        "aiBias": clamp(logit(capped(mean_ai)) - logit(capped(ma)), -2, 2) if shown else 0.0,
        "threshold": DEFAULTS["threshold"],
        "deferRate": followed / len(disagreements) if disagreements else DEFAULTS["deferRate"],
    })


def load_session(path: str | Path) -> dict:
    """Read and check one session file written by the browser app."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionError(f"{path}: not valid JSON ({exc.msg})") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise SessionError(f'{path}: not a session file (expected "format": "{FORMAT}")')
    trials = data.get("trials")
    if not isinstance(trials, list) or not trials:
        raise SessionError(f"{path}: has no trials")
    for i, t in enumerate(trials):
        try:
            _check_trial(t, i)
        except SessionError as exc:
            raise SessionError(f"{path}: {exc}") from exc
    data.setdefault("label", Path(path).stem)
    data.setdefault("settings", {})
    return data
