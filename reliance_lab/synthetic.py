"""Synthetic participants, for demos and for testing the class report.

Each virtual participant has a solo accuracy, a confidence that partly tracks whether they are
right, and a reliance habit. They "play" the same kind of session as the browser app and the
result is written in the app's session format, clearly labelled as synthetic.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .model import logit, sigmoid
from .sessions import FORMAT

CONFIDENCE_LEVELS = (0.55, 0.7, 0.85, 0.95)

MISTAKES = ("random", "hard", "easy")

HABITS = {
    "rubber-stamper": "Switches to the AI in 90% of disagreements, whatever it says",
    "sceptic": "Switches to the AI in only 15% of disagreements",
    "confidence-follower": "Switches when the AI shows 85% or more",
    "weigher": "Switches when the AI sounds surer than they feel",
}


def _nearest_level(c: float) -> float:
    return min(CONFIDENCE_LEVELS, key=lambda lvl: abs(lvl - c))


def simulate_session(rng: random.Random, *, habit: str, n: int = 20, ai_accuracy: float = 0.8,
                     ai_style: str = "calibrated", ai_signal: float = 1.5,
                     human_accuracy: float = 0.7, human_signal: float = 1.0,
                     mistakes: str = "random", label: str = "synthetic") -> dict:
    """One virtual participant's session.

    ``mistakes`` mirrors the browser app's setting: "hard" makes the advisor's mistakes three
    times as likely to land on payments this participant also gets wrong, "easy" on payments
    they get right.
    """
    if habit not in HABITS:
        raise ValueError(f"Unknown habit: {habit}")
    if mistakes not in MISTAKES:
        raise ValueError(f"Unknown mistakes setting: {mistakes}")
    truths = ["fraud" if i < n // 2 else "genuine" for i in range(n)]
    rng.shuffle(truths)
    you_right_all = [rng.random() < human_accuracy for _ in range(n)]

    def weight(k: int) -> float:
        if mistakes == "hard":
            return 3.0 if not you_right_all[k] else 1.0
        if mistakes == "easy":
            return 3.0 if you_right_all[k] else 1.0
        return 1.0

    keys = sorted(range(n), key=lambda k: -(rng.random() ** (1 / weight(k))))
    wrong = set(keys[:n - round(n * ai_accuracy)])
    ai_right = [k not in wrong for k in range(n)]
    trials = []
    for k, truth in enumerate(truths):
        other = "genuine" if truth == "fraud" else "fraud"
        you_right = you_right_all[k]
        initial = truth if you_right else other
        t = rng.gauss(human_signal / 2 if you_right else -human_signal / 2, 1)
        conf = _nearest_level(max(0.5, sigmoid(logit(human_accuracy) + human_signal * t)))
        ai = truth if ai_right[k] else other
        s = rng.gauss(ai_signal / 2 if ai_right[k] else -ai_signal / 2, 1)
        if ai_style == "calibrated":
            ai_conf = round(max(0.5, sigmoid(logit(ai_accuracy) + ai_signal * s)), 2)
        elif ai_style == "confident":
            ai_conf = round(0.9 + 0.09 * rng.random(), 2)
        else:
            ai_conf = None
        final = initial
        if initial != ai:
            if habit == "rubber-stamper":
                follow = rng.random() < 0.9
            elif habit == "sceptic":
                follow = rng.random() < 0.15
            elif habit == "confidence-follower":
                follow = ai_conf is not None and ai_conf >= 0.85
            else:
                follow = ai_conf is not None and ai_conf > conf
            final = ai if follow else initial
        trials.append({
            "id": k + 1, "truth": truth, "initial": initial, "initialConfidence": conf,
            "ai": ai, "aiConfidence": ai_conf, "final": final,
        })
    return {
        "format": FORMAT,
        "version": 1,
        "synthetic": True,
        "label": label,
        "habit": habit,
        "settings": {"cases": n, "aiAccuracy": ai_accuracy, "aiStyle": ai_style,
                     "mistakes": mistakes, "feedback": False, "code": "synthetic"},
        "trials": trials,
    }


def make_class(participants: int = 24, seed: int = 7, n: int = 20, mistakes: str = "random") -> list[dict]:
    """A synthetic class: habits rotate, half see an honest AI and half an always-sure one."""
    rng = random.Random(seed)
    habits = list(HABITS)
    sessions = []
    for i in range(participants):
        habit = habits[i % len(habits)]
        style = "calibrated" if (i // len(habits)) % 2 == 0 else "confident"
        sessions.append(simulate_session(
            rng, habit=habit, n=n, ai_accuracy=0.8, ai_style=style,
            human_accuracy=round(rng.uniform(0.62, 0.82), 2),
            human_signal=round(rng.uniform(0.4, 1.6), 2),
            mistakes=mistakes, label=f"P{i + 1:02d}",
        ))
    return sessions


def write_class(out_dir: str | Path, participants: int = 24, seed: int = 7, n: int = 20,
                mistakes: str = "random") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for session in make_class(participants, seed, n, mistakes):
        path = out / f"{session['label']}.json"
        path.write_text(json.dumps(session, indent=1) + "\n", encoding="utf-8")
        paths.append(path)
    return paths
