"""Pooling many sessions: per-person scores, group summaries with uncertainty, and tests.

A single person's test has only a handful of moments where reliance matters, so
the interesting questions (does showing a reason make people follow wrong advice
more?) need many people. This module loads saved sessions, scores each one, and
compares groups with bootstrap confidence intervals and permutation tests.
"""

import csv
import json
import os
import random

from .metrics import score, validate_session

# Per-person measures used in group summaries: (key, label, higher is better?)
MEASURES = [
    ("rair", "Took good advice (RAIR)", True),
    ("rsr", "Resisted bad advice (RSR)", True),
    ("appropriate", "Appropriate reliance", True),
    ("followWhenWrong", "Followed the checker when it was wrong", False),
    ("withInitial", "First answers right", True),
    ("withFinal", "Final answers right", True),
    ("complementarity", "Gain over the better of person or checker", True),
    ("change", "Solo change, after minus before", True),
    ("brierFinal", "Confidence error (Brier, final answers)", False),
]


class SessionFileError(ValueError):
    pass


def _session_from_csv_rows(rows):
    first = rows[0]
    trials = []
    for r in rows:
        def resp(prefix):
            if not r.get(prefix + "_answer"):
                return None
            out = {"answer": r[prefix + "_answer"], "confidence": int(r[prefix + "_confidence"])}
            if r.get(prefix + "_ms"):
                out["ms"] = int(r[prefix + "_ms"])
            return out
        trial = {"item": r["item"], "phase": r["phase"], "position": int(r["position"]),
                 "truth": r["truth"], "initial": resp("initial")}
        if r["phase"] == "with":
            trial["ai"] = {"verdict": r["ai_verdict"], "confidence": int(r["ai_confidence"])}
            trial["final"] = resp("final")
        trials.append(trial)
    trials.sort(key=lambda t: t["position"])
    return {
        "format": "second-opinion-session", "version": 1, "id": first["session"],
        "condition": {"advice": first["advice"], "feedback": first["feedback"].lower() == "true",
                      "assignment": first.get("assignment") or "fixed"},
        "trials": trials,
    }


def load_file(path):
    """Load the sessions in one .json or .csv file (a CSV may hold several sessions)."""
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise SessionFileError("%s has no rows." % path)
        groups = {}
        for r in rows:
            groups.setdefault(r.get("session", ""), []).append(r)
        try:
            sessions = [_session_from_csv_rows(g) for g in groups.values()]
        except (KeyError, ValueError, TypeError) as exc:
            raise SessionFileError("%s is not a Second opinion CSV (%s)." % (path, exc)) from None
    else:
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                raise SessionFileError("%s is not valid JSON." % path) from None
        sessions = data if isinstance(data, list) else [data]
    for s in sessions:
        problems = validate_session(s)
        if problems:
            raise SessionFileError("%s: %s" % (path, " ".join(problems)))
    return sessions


def load_sessions(paths):
    """Load sessions from files and folders (folders are searched for .json and .csv files)."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith((".json", ".csv")):
                    files.append(os.path.join(p, name))
        else:
            files.append(p)
    sessions = []
    for f in files:
        sessions.extend(load_file(f))
    return sessions


def condition_label(condition, by="condition"):
    condition = condition or {}
    advice = condition.get("advice", "reason")
    feedback = "feedback on" if condition.get("feedback") else "feedback off"
    if by == "advice":
        return "advice: " + advice
    if by == "feedback":
        return feedback
    return "advice: %s, %s" % (advice, feedback)


def person_row(session, by="condition"):
    s = score(session)
    r = s["reliance"]
    return {
        "id": session.get("id", ""),
        "group": condition_label(session.get("condition"), by),
        "profile": s["profile"]["key"],
        "rair": r["rair"],
        "rsr": r["rsr"],
        "appropriate": r["appropriate"],
        "followWhenWrong": r["followWhenWrong"],
        "withInitial": s["accuracy"]["withInitial"],
        "withFinal": s["accuracy"]["withFinal"],
        "complementarity": s["complementarity"],
        "change": s["change"],
        "brierFinal": s["confidence"]["withFinal"]["brier"],
    }


def _mean(values):
    return sum(values) / len(values) if values else None


def bootstrap_ci(values, resamples=2000, seed=7, level=0.95):
    """Percentile bootstrap interval for the mean."""
    if len(values) < 2:
        return (None, None)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo = means[int((1 - level) / 2 * resamples)]
    hi = means[min(resamples - 1, int((1 + level) / 2 * resamples))]
    return (lo, hi)


def permutation_test(a, b, permutations=5000, seed=11):
    """Two-sided permutation test for a difference in means. Returns (difference, p-value)."""
    if len(a) < 2 or len(b) < 2:
        return (None, None)
    observed = _mean(a) - _mean(b)
    pooled = list(a) + list(b)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(permutations):
        rng.shuffle(pooled)
        diff = _mean(pooled[:len(a)]) - _mean(pooled[len(a):])
        if abs(diff) >= abs(observed) - 1e-12:
            extreme += 1
    return (observed, (extreme + 1) / (permutations + 1))


def summarise(sessions, by="condition", resamples=2000):
    """Group summary: for each group and measure, n, mean and a 95% bootstrap interval."""
    rows = [person_row(s, by) for s in sessions]
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    summary = {"by": by, "people": len(rows), "groups": [], "measures": MEASURES}
    for name in sorted(groups):
        members = groups[name]
        stats = {}
        for key, _, _ in MEASURES:
            values = [m[key] for m in members if m[key] is not None]
            lo, hi = bootstrap_ci(values, resamples=resamples)
            stats[key] = {"n": len(values), "mean": _mean(values), "low": lo, "high": hi}
        profiles = {}
        for m in members:
            profiles[m["profile"]] = profiles.get(m["profile"], 0) + 1
        summary["groups"].append({"name": name, "people": len(members), "stats": stats,
                                  "profiles": profiles, "rows": members})
    return summary


def compare_groups(summary, key, permutations=5000):
    """Compare every group with the first one on one measure."""
    groups = summary["groups"]
    if len(groups) < 2:
        return []
    ref = groups[0]
    ref_values = [r[key] for r in ref["rows"] if r[key] is not None]
    out = []
    for g in groups[1:]:
        values = [r[key] for r in g["rows"] if r[key] is not None]
        diff, p = permutation_test(values, ref_values, permutations=permutations)
        out.append({"group": g["name"], "reference": ref["name"], "measure": key, "difference": diff, "p": p})
    return out
