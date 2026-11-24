"""Plain-text report of the model for the command line."""

from __future__ import annotations

from .model import OUTCOME_KEYS, OUTCOME_LABELS, POLICIES, POLICY_LABELS, analyse, per_100


def pct(v: float | None, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def pts(v: float | None) -> str:
    if v is None:
        return "n/a"
    r = round(v * 100, 1)
    return "0.0 pts" if r == 0 else f"{r:+.1f} pts"


def model_report(params: dict | None = None, rule: str = "surer") -> str:
    a = analyse(params)
    p = a["params"]
    lines = [
        "Reliance model",
        "",
        f"  Person alone {pct(p['human'])}   AI alone {pct(p['ai'])}   "
        f"Error overlap {a['cells']['rho']:.2f}"
        + ("  (clamped to what the two accuracies allow)" if a["cells"]["clamped"] else ""),
        f"  The person also gets {pct(a['sharedMistakeShare'], 0)} of the AI's mistakes wrong; "
        f"they disagree on {pct(a['cells']['p01'] + a['cells']['p10'], 0)} of cases.",
        f"  AI confidence signal d'={p['aiSignal']:.2f}, bias {p['aiBias']:+.2f}; "
        f"person's confidence signal d'={p['humanSignal']:.2f}, bias {p['humanBias']:+.2f}",
        "",
        f"  {'Rule':<44}{'Team':>8}{'vs best solo':>15}{'Over-rely':>12}{'Under-rely':>12}",
    ]
    for key in POLICIES:
        r = a["policies"][key]
        label = r["label"]
        if key == "fixed":
            label += f" ({p['deferRate'] * 100:.0f}%)"
        if key == "threshold":
            label += f" ({p['threshold'] * 100:.0f}%)"
        lines.append(f"  {label:<44}{pct(r['team']):>8}{pts(r['gain']):>15}"
                     f"{pct(r['overRelianceRate'], 0):>12}{pct(r['underRelianceRate'], 0):>12}")
    lines += [
        "",
        f"  Shared blind spots (no rule can fix these): {pct(a['cells']['p00'])} of cases",
        f"  Best possible team accuracy: {pct(a['ceiling'])} ({pts(a['ceiling'] - a['best'])} on the better solo)",
        "",
        f"  Out of every 100 cases, with \"{POLICY_LABELS[rule].lower()}\":",
    ]
    counts = per_100(p, rule)["counts"]
    for key in OUTCOME_KEYS:
        lines.append(f"    {counts[key]:>3}  {OUTCOME_LABELS[key]}")
    return "\n".join(lines)
