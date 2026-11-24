"""Analysing a whole study: many sessions, some with the checker and some without."""

from . import stats
from .model import BY_ID, PROFILES, STRATEGIES, score_session

PROFILE_ORDER = ["calibrated", "over_reliant", "under_reliant", "mixed", "few_disagreements"]


def participant_summary(session):
    res = score_session(session)
    r1, r2, r3 = res["rounds"]
    a = res["assisted"] or {}
    dis = a.get("disagreements") or 0
    switched = (a["cases"]["switchedToRight"] + a["cases"]["switchedToWrong"]) if a else 0
    return {
        "participant": session.get("participant", ""),
        "study": session.get("study", ""),
        "arm": session["arm"],
        "complete": res["complete"],
        "pre": r1["accuracy"],
        "during": r2["accuracy"],
        "post": r3["accuracy"],
        "gain": res["change"]["accuracy"],
        "brierPre": r1["brier"],
        "brierPost": r3["brier"],
        "initial": a.get("initialAccuracy"),
        "checker": a.get("checkerAccuracy"),
        "final": a.get("finalAccuracy"),
        "rair": a.get("rair"),
        "rsr": a.get("rsr"),
        "overReliance": a.get("overReliance"),
        "underReliance": a.get("underReliance"),
        "switchRate": (switched / dis) if dis else None,
        "profile": res["profile"],
        "cPre": res["sdt"]["round1"] and res["sdt"]["round1"]["c"],
        "cPost": res["sdt"]["round3"] and res["sdt"]["round3"]["c"],
        "dPre": res["sdt"]["round1"] and res["sdt"]["round1"]["dPrime"],
        "dPost": res["sdt"]["round3"] and res["sdt"]["round3"]["dPrime"],
        "strategies": {x["key"]: x["accuracy"] for x in res["strategies"]} if res["strategies"] else None,
    }


def _vals(rows, key):
    return [r[key] for r in rows if r[key] is not None]


def _describe(rows, key):
    xs = _vals(rows, key)
    return {"n": len(xs), "mean": stats.mean(xs), "sd": stats.sd(xs)}


def _compare(a_rows, b_rows, key, n_perm, n_boot, seed):
    a, b = _vals(a_rows, key), _vals(b_rows, key)
    if len(a) < 2 or len(b) < 2:
        return None
    welch = stats.welch_t(a, b)
    return {
        "difference": stats.mean(a) - stats.mean(b),
        "ci": stats.bootstrap_ci(a, b, n_boot=n_boot, seed=seed),
        "p": stats.permutation_test(a, b, n_perm=n_perm, seed=seed + 1),
        "welchP": welch[2] if welch else None,
        "g": stats.hedges_g(a, b),
    }


def item_table(sessions):
    """Per-message results: how often people got it right alone, and with the checker."""
    items = {}
    for s in sessions:
        for t in s["trials"]:
            if not t.get("final"):
                continue
            row = items.setdefault(t["messageId"], {
                "messageId": t["messageId"], "truth": t["truth"], "difficulty": t["difficulty"],
                "aloneN": 0, "aloneCorrect": 0, "assistedN": 0, "assistedCorrect": 0,
                "checkerWrongN": 0, "followedWrong": 0})
            right = t["final"]["verdict"] == t["truth"]
            if t.get("checker"):
                row["assistedN"] += 1
                row["assistedCorrect"] += right
                if not t["checker"]["correct"]:
                    row["checkerWrongN"] += 1
                    row["followedWrong"] += t["final"]["verdict"] == t["checker"]["verdict"]
            else:
                row["aloneN"] += 1
                row["aloneCorrect"] += right
    out = []
    for row in items.values():
        row["aloneAccuracy"] = row["aloneCorrect"] / row["aloneN"] if row["aloneN"] else None
        row["assistedAccuracy"] = row["assistedCorrect"] / row["assistedN"] if row["assistedN"] else None
        m = BY_ID[row["messageId"]]
        row["label"] = "%s from %s" % (m["channel"], m["from"])
        out.append(row)
    out.sort(key=lambda r: (r["aloneAccuracy"] if r["aloneAccuracy"] is not None else 2, r["messageId"]))
    return out


def analyse(sessions, n_perm=5000, n_boot=2000, seed=1):
    """Compare the checker and control arms, and describe how the checker arm used it."""
    seen = set()
    unique, duplicates = [], 0
    for s in sessions:
        key = (s.get("study", ""), s.get("participant", ""), s.get("seed"))
        if s.get("participant") and key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(s)
    rows = [participant_summary(s) for s in unique]
    complete = [r for r in rows if r["complete"]]
    used = [s for s, r in zip(unique, rows) if r["complete"]]
    chk = [r for r in complete if r["arm"] == "checker"]
    ctl = [r for r in complete if r["arm"] == "control"]

    arms = {}
    for name, group in (("checker", chk), ("control", ctl)):
        arms[name] = {"n": len(group)}
        for key in ("pre", "during", "post", "gain", "brierPre", "brierPost", "cPre", "cPost", "dPre", "dPost"):
            arms[name][key] = _describe(group, key)

    reliance = None
    if chk:
        profiles = {p: sum(r["profile"] == p for r in chk) for p in PROFILE_ORDER}
        beat = sum(1 for r in chk if r["final"] is not None and r["final"] > r["checker"])
        reliance = {
            "rair": _describe(chk, "rair"),
            "rsr": _describe(chk, "rsr"),
            "overReliance": _describe(chk, "overReliance"),
            "underReliance": _describe(chk, "underReliance"),
            "initial": _describe(chk, "initial"),
            "final": _describe(chk, "final"),
            "checker": _describe(chk, "checker"),
            "profiles": profiles,
            "beatChecker": beat,
            "switchGainR": stats.pearson([r["switchRate"] for r in chk], [r["gain"] for r in chk]),
            "switchGainN": sum(1 for r in chk if r["switchRate"] is not None),
            "strategies": [{"key": k, "label": label,
                            "mean": stats.mean([r["strategies"][k] for r in chk if r["strategies"]])}
                           for k, label in STRATEGIES],
        }

    return {
        "sessions": len(sessions),
        "duplicates": duplicates,
        "incomplete": len(rows) - len(complete),
        "complete": len(complete),
        "arms": arms,
        "during": _compare(chk, ctl, "during", n_perm, n_boot, seed),
        "gain": _compare(chk, ctl, "gain", n_perm, n_boot, seed + 10),
        "reliance": reliance,
        "items": item_table(used),
        "participants": complete,
    }


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def _p(x):
    return "n/a" if x is None else "%d%%" % round(x * 100)


def _pts(x, signed=True):
    if x is None:
        return "n/a"
    v = x * 100
    return ("%+.1f" if signed else "%.1f") % v + " pts"


def _pval(p):
    if p is None:
        return "n/a"
    return "< 0.001" if p < 0.001 else "%.3f" % p


def _pair(arm, k1, k2):
    x, y = arm[k1]["mean"], arm[k2]["mean"]
    return "n/a" if x is None or y is None else "%.2f to %.2f" % (x, y)


def _effect_line(label, cmp):
    if cmp is None:
        return "  %s: needs at least two complete sessions in each group." % label
    lo, hi = cmp["ci"]
    return "  %s: %s (95%% CI %s to %s, permutation p = %s, Hedges' g = %s)" % (
        label, _pts(cmp["difference"]), _pts(lo), _pts(hi), _pval(cmp["p"]),
        "n/a" if cmp["g"] is None else "%.2f" % cmp["g"])


def study_report(an, top_items=8):
    a, c = an["arms"]["checker"], an["arms"]["control"]
    lines = [
        "Crutch check: study analysis",
        "",
        "Sessions: %d complete (%d with the checker, %d without). Left out: %d incomplete, %d duplicate."
        % (an["complete"], a["n"], c["n"], an["incomplete"], an["duplicates"]),
        "",
        "  %-34s %14s %10s" % ("Share judged correctly", "With checker", "Without"),
    ]
    for key, label in (("pre", "Round 1 (before)"), ("during", "Round 2"), ("post", "Round 3 (after)")):
        lines.append("  %-34s %14s %10s" % (label, _p(a[key]["mean"]), _p(c[key]["mean"])))
    lines.append("  %-34s %14s %10s" % ("Change, round 1 to round 3", _pts(a["gain"]["mean"]),
                                         _pts(c["gain"]["mean"])))
    lines.append("  %-34s %14s %10s" % ("Sensitivity d', round 1 then 3", _pair(a, "dPre", "dPost"),
                                         _pair(c, "dPre", "dPost")))
    lines.append("  %-34s %14s %10s" % ("Leaning c, round 1 then 3", _pair(a, "cPre", "cPost"),
                                         _pair(c, "cPre", "cPost")))
    lines += [
        "",
        "Differences between the groups (with the checker minus without)",
        _effect_line("While using it (round 2)", an["during"]),
        _effect_line("Afterwards (change from round 1 to 3)", an["gain"]),
    ]
    r = an["reliance"]
    if r:
        lines += [
            "",
            "How the checker group used it",
            "  Took good advice when they were wrong (RAIR):   %s" % _p(r["rair"]["mean"]),
            "  Held firm when the checker was wrong (RSR):     %s" % _p(r["rsr"]["mean"]),
            "  Followed the checker when it was wrong:         %s" % _p(r["overReliance"]["mean"]),
            "  Accuracy: first answers %s, checker alone %s, final answers %s" % (
                _p(r["initial"]["mean"]), _p(r["checker"]["mean"]), _p(r["final"]["mean"])),
            "  Beat the checker on its own: %d of %d" % (r["beatChecker"], a["n"]),
            "  Patterns: " + ", ".join("%s %d" % (PROFILES[k], v) for k, v in r["profiles"].items() if v),
        ]
        lines.append("  What if everyone had used one simple rule in round 2 (average accuracy):")
        for st in r["strategies"]:
            lines.append("    %-48s %s" % (st["label"], _p(st["mean"])))
        if r["switchGainR"] is not None:
            lines.append("  Reliance and learning: correlation between how often people switched to the")
            lines.append("  checker and their change from round 1 to 3 is r = %.2f (n = %d)." % (
                r["switchGainR"], r["switchGainN"]))
    items = [i for i in an["items"] if i["aloneN"]]
    if items:
        lines += ["", "Hardest messages without the checker"]
        for i in items[:top_items]:
            lines.append("  %-4s %-7s %3s right (n=%d)  %s" % (
                i["messageId"], i["truth"], _p(i["aloneAccuracy"]), i["aloneN"], i["label"][:60]))
    return "\n".join(lines)
