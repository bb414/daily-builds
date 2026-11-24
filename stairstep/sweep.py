"""Robustness: do the conclusions hold across many synthetic worlds?

One world is one random seed: the same chain and the same kinds of effect, but
different promotion weeks and different random sales. A conclusion that holds in
one world might be luck; the sweep shows how often each one holds.
"""

import statistics

from . import model

PILOT_LENGTH = 13
MEASURES = [
    ("aiGain", "AI's gain over the best simple method (points)"),
    ("plannerEffect", "Change from planners' overrides (points, negative is worse)"),
    ("downOnlyGain", "Gain from keeping only downward overrides, against the AI alone (points)"),
    ("mixVsAi", "Choosing in advance, against the AI everywhere (points, negative is worse)"),
    ("deployOn", "Products where the AI is worth it, with hindsight"),
    ("chosenAi", "Products where it is chosen in advance"),
    ("pilotLow", "Lowest gain a 13-week pilot in all stores would measure (points)"),
    ("pilotHigh", "Highest gain a 13-week pilot in all stores would measure (points)"),
]


def world(settings):
    """The headline numbers for one world."""
    r = model.run(settings)
    res = r["results"]
    methods = res["methods"]
    best = min(methods[:4], key=lambda m: m["wape"])
    ai, planner = methods[4], methods[5]
    windows = model.pilot_windows(r["data"], r["forecasts"], settings, PILOT_LENGTH, list(range(len(r["data"]["stores"]))))
    gains = [w["gain"] for w in windows if w["gain"] is not None]
    return {
        "seed": res["settings"]["seed"],
        "aiGain": (best["wape"] - ai["wape"]) * 100,
        "plannerEffect": (ai["wape"] - planner["wape"]) * 100,
        "downOnlyGain": (ai["wape"] - res["downOnly"]["wape"]) * 100,
        "mixVsAi": (ai["wape"] - res["mix"]["wape"]) * 100,
        "deployOn": res["deployOn"],
        "chosenAi": res["chosenAi"],
        "pilotLow": min(gains) * 100,
        "pilotHigh": max(gains) * 100,
        "threshold": res["settings"]["threshold"] * 100,
    }


def sweep(settings, worlds=20, first_seed=1, progress=None):
    rows = []
    for k in range(worlds):
        s = dict(settings or {})
        s["seed"] = first_seed + k
        rows.append(world(s))
        if progress:
            progress(k + 1, worlds)
    return rows


def summary_text(rows):
    n = len(rows)
    threshold = rows[0]["threshold"]
    lines = ["Stairstep robustness check: %d worlds (seeds %d to %d)" % (n, rows[0]["seed"], rows[-1]["seed"]), "",
             "  %-76s %8s %8s %8s" % ("Measure", "Lowest", "Median", "Highest")]
    for key, label in MEASURES:
        values = [r[key] for r in rows]
        if key in ("deployOn", "chosenAi"):
            cells = "%8d %8s %8d" % (min(values), ("%g" % statistics.median(values)), max(values))
        else:
            cells = "%8.1f %8.1f %8.1f" % (min(values), statistics.median(values), max(values))
        lines.append("  %-76s %s" % (label, cells))

    def share(test):
        k = sum(1 for r in rows if test(r))
        return "%d of %d worlds" % (k, n)

    lines += ["", "How often each conclusion holds:",
              "  The AI beats the best simple method by at least %.1f points: %s" % (threshold, share(lambda r: r["aiGain"] >= threshold)),
              "  Planners' overrides make the AI worse: %s" % share(lambda r: r["plannerEffect"] < 0),
              "  Keeping only downward overrides beats the AI alone: %s" % share(lambda r: r["downOnlyGain"] > 0),
              "  Choosing in advance does worse than the AI everywhere: %s" % share(lambda r: r["mixVsAi"] < 0),
              "  Some 13-week pilot would measure under half the full-year gain: %s" % share(lambda r: r["pilotLow"] < r["aiGain"] / 2),
              "  Some 13-week pilot would measure over 1.5 times the full-year gain: %s" % share(lambda r: r["pilotHigh"] > r["aiGain"] * 1.5)]
    return "\n".join(lines) + "\n"


def write_csv(rows, path):
    keys = ["seed"] + [k for k, _ in MEASURES]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(str(r[k]) if k in ("seed", "deployOn", "chosenAi") else "%.4f" % r[k] for k in keys) + "\n")
