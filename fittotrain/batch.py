"""Batch runs the browser app is too slow for: many worlds, and sweeps of one habit."""

import sys

from . import model


def _progress(done, total, quiet):
    if not quiet:
        sys.stderr.write("\r  %d of %d runs" % (done, total))
        if done == total:
            sys.stderr.write("\n")
        sys.stderr.flush()


def robust(settings, n_worlds=12, quiet=True):
    """The headline numbers on n other worlds, plus how often each habit comes
    out as the one to fix first (for live accuracy and for honesty)."""
    s = model.normalise_settings(settings)
    rb = model.robustness(s, n_worlds)
    best_live, best_honest = {}, {}
    total = len(rb["worlds"])
    for i, w in enumerate(rb["worlds"]):
        sk = dict(s)
        sk["seed"] = w["seed"]
        r = model.run_lab(sk)
        rows = r["fixes"]["rows"]
        if rows:
            best_live[rows[0]["key"]] = best_live.get(rows[0]["key"], 0) + 1
            honest = max(rows, key=lambda row: (row["illusionDrop"], -row["order"]))
            best_honest[honest["key"]] = best_honest.get(honest["key"], 0) + 1
        _progress(i + 1, total, quiet)
    rb["fixWinners"] = {"live": best_live, "honest": best_honest}
    return rb


def sweep(settings, key, levels=6, n_worlds=5, quiet=True):
    """Run one habit from zero to its maximum, everything else fixed, on several worlds."""
    if key not in model.DEFECT_KEYS:
        raise ValueError("unknown habit %r" % key)
    s = model.normalise_settings(settings)
    top = [d for d in model.DEFECTS if d["key"] == key][0]["max"]
    levels = max(2, int(levels))
    n_worlds = max(1, int(n_worlds))
    points = [round(top * i / (levels - 1), 6) for i in range(levels)]
    rows = []
    total = levels * n_worlds
    done = 0
    for level in points:
        for k in range(n_worlds):
            sk = dict(s)
            sk[key] = level
            sk["seed"] = (s["seed"] + 1 + k) % 4294967296
            r = model.run_lab(sk, fixes=False)
            rows.append({
                "habit": key, "level": level, "seed": sk["seed"],
                "backtest": r["backtest"]["auc"], "live": r["live"]["auc"], "ceiling": r["ceiling"]["auc"],
                "illusion": r["illusion"],
                "repaired_backtest": r["repaired"]["backtest"]["auc"], "repaired_live": r["repaired"]["live"]["auc"],
                "bias": r["live"]["meanPredicted"] - r["live"]["winRate"],
                "repaired_bias": r["repaired"]["live"]["meanPredicted"] - r["repaired"]["live"]["winRate"],
            })
            done += 1
            _progress(done, total, quiet)
    means = []
    for level in points:
        group = [r for r in rows if r["level"] == level]
        m = {"level": level}
        for col in ("backtest", "live", "ceiling", "illusion", "repaired_backtest", "repaired_live", "bias", "repaired_bias"):
            m[col] = model.summarise([g[col] for g in group])["mean"]
        means.append(m)
    return {"settings": s, "habit": key, "levels": points, "worlds": n_worlds, "rows": rows, "means": means}


SWEEP_COLUMNS = ["habit", "level", "seed", "backtest", "live", "ceiling", "illusion", "repaired_backtest",
                 "repaired_live", "bias", "repaired_bias"]
