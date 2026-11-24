"""Power analysis by simulation: how many participants would a study need?

For each group size, simulate many complete studies under a scenario, analyse
each one, and count how often the difference between the groups comes out
statistically significant (Welch's t-test, two-sided). Under the "none" and
"mixed" scenarios the true average effect is zero or close to it, so the
detection rate should stay near the significance level: a useful check that
the test is not crying wolf.
"""

from . import stats
from .cohort import SCENARIOS, simulate_cohort
from .model import points


def expected_gain_difference(scenario):
    """True average difference in round 1 to round 3 change (checker minus control).

    Reliance is drawn from a Beta(2, 2) distribution, whose mean is 0.5.
    """
    e = SCENARIOS[scenario]
    return e["helper"] - e["crutch"] * 0.5 - e["practice"]


def _accuracies(session):
    """Share right in each round (a fast path: power analysis scores many thousands of sessions)."""
    right = [0, 0, 0]
    total = [0, 0, 0]
    for t in session["trials"]:
        i = t["round"] - 1
        total[i] += 1
        right[i] += t["final"]["verdict"] == t["truth"]
    return [r / n for r, n in zip(right, total)]


def power_curve(scenario="crutch", sizes=(20, 40, 80, 160), sims=100, alpha=0.05, seed=1, design=None,
                progress=None):
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario %r" % scenario)
    if sims < 1:
        raise ValueError("sims must be at least 1")
    rows = []
    for n in sorted(sizes):
        if n < 2:
            raise ValueError("each group needs at least 2 participants")
        hits_gain = hits_during = 0
        diffs = []
        for k in range(sims):
            sessions = simulate_cohort(n, scenario, seed=seed * 1000003 + n * 7919 + k, design=design)
            acc = [(s["arm"], _accuracies(s)) for s in sessions]
            gain = {arm: [a[2] - a[0] for g, a in acc if g == arm] for arm in ("checker", "control")}
            during = {arm: [a[1] for g, a in acc if g == arm] for arm in ("checker", "control")}
            w = stats.welch_t(gain["checker"], gain["control"])
            if w and w[2] < alpha:
                hits_gain += 1
            w = stats.welch_t(during["checker"], during["control"])
            if w and w[2] < alpha:
                hits_during += 1
            diffs.append(stats.mean(gain["checker"]) - stats.mean(gain["control"]))
        rows.append({
            "n": n,
            "sims": sims,
            "afterPower": hits_gain / sims,
            "duringPower": hits_during / sims,
            "meanDifference": stats.mean(diffs),
            "spread": stats.sd(diffs),
        })
        if progress:
            progress(n)
    return {"scenario": scenario, "alpha": alpha, "expected": expected_gain_difference(scenario), "rows": rows}


def power_report(result):
    lines = [
        "Power analysis: scenario '%s'" % result["scenario"],
        "  %s" % SCENARIOS[result["scenario"]]["about"],
        "  True average difference in change from round 1 to 3 (with checker minus without): %+.1f pts"
        % (result["expected"] * 100),
        "",
        "  %-16s %-26s %-26s %s" % ("Per group", "Detects the after effect", "Detects the during effect",
                                    "Estimated after effect (spread)"),
    ]
    for r in result["rows"]:
        lines.append("  %-16d %-26s %-26s %+.1f pts (sd %.1f)" % (
            r["n"], "%d%%" % points(r["afterPower"]), "%d%%" % points(r["duringPower"]),
            r["meanDifference"] * 100, (r["spread"] or 0) * 100))
    enough = [r["n"] for r in result["rows"] if r["afterPower"] >= 0.8]
    lines.append("")
    if abs(result["expected"]) < 0.01:
        lines.append("  There is little or no true average effect here, so detection rates near %d%% are "
                     "false alarms at the chosen significance level." % round(result["alpha"] * 100))
    elif enough:
        lines.append("  About %d per group is enough to detect the after effect 80%% of the time." % min(enough))
    else:
        lines.append("  None of these group sizes detects the after effect 80%% of the time. Try larger groups.")
    lines.append("  Each row is %d simulated studies; significance level %.2f, Welch's t-test." % (
        result["rows"][0]["sims"] if result["rows"] else 0, result["alpha"]))
    return "\n".join(lines)
