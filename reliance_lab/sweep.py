"""Sweep the model across a grid of assumptions and summarise where pairing pays.

The browser app shows one set of assumptions at a time. This runs every combination in a grid
(3,888 by default) and asks which conditions make a person-plus-AI team beat both members.
"""

from __future__ import annotations

import csv
import io
import itertools

from .model import DEFAULTS, POLICIES, POLICY_LABELS, analyse

GRID = {
    "human": (0.6, 0.7, 0.8, 0.9),
    "ai": (0.6, 0.7, 0.8, 0.9),
    "overlap": (0.0, 0.2, 0.4),
    "aiSignal": (0.0, 1.0, 2.0),
    "humanSignal": (0.0, 1.0, 2.0),
    "aiBias": (0.0, 0.5, 1.0),
    "humanBias": (0.0, 0.5, 1.0),
}

FACTOR_NAMES = {
    "human": "Person's accuracy",
    "ai": "AI's accuracy",
    "overlap": "Error overlap",
    "aiSignal": "AI confidence signal (d')",
    "humanSignal": "Person's confidence signal (d')",
    "aiBias": "AI overconfidence",
    "humanBias": "Person's overconfidence",
    "biasGap": "Overconfidence gap (AI minus person)",
}


def run_sweep(grid: dict | None = None, base: dict | None = None) -> list[dict]:
    """One row per combination: the assumptions plus each rule's accuracy and gain."""
    g = grid or GRID
    keys = list(g)
    rows = []
    for combo in itertools.product(*(g[k] for k in keys)):
        params = {**(base or {}), **dict(zip(keys, combo))}
        a = analyse(params)
        row = {k: a["params"][k] for k in keys}
        row["biasGap"] = round(a["params"]["aiBias"] - a["params"]["humanBias"], 9)
        row["bestSolo"] = a["best"]
        for key in POLICIES:
            row[f"{key}Team"] = a["policies"][key]["team"]
            row[f"{key}Gain"] = a["policies"][key]["gain"]
        rows.append(row)
    return rows


def summarise(rows: list[dict], margin: float = 0.005, grid: dict | None = None) -> dict:
    """Share of scenarios where each rule beats the better solo by more than ``margin``,
    and how the best possible gain moves with each assumption (main effects)."""
    g = grid or GRID
    n = len(rows)
    rules = {}
    for key in POLICIES:
        gains = [r[f"{key}Gain"] for r in rows]
        rules[key] = {
            "label": POLICY_LABELS[key],
            "shareBeatsBoth": sum(v > margin for v in gains) / n,
            "shareWorse": sum(v < -margin for v in gains) / n,
            "meanGain": sum(gains) / n,
        }
    effects = {}
    factors = dict(g)
    factors["biasGap"] = tuple(sorted({r["biasGap"] for r in rows}))
    for factor, levels in factors.items():
        effects[factor] = []
        for level in levels:
            sel = [r for r in rows if abs(r[factor] - level) < 1e-9]
            effects[factor].append({
                "level": level,
                "meanBestGain": sum(r["optimalGain"] for r in sel) / len(sel),
                "shareSurerBeatsBoth": sum(r["surerGain"] > margin for r in sel) / len(sel),
            })
    return {"scenarios": n, "margin": margin, "rules": rules, "effects": effects}


def sweep_report(summary: dict) -> str:
    m = summary["margin"] * 100
    lines = [
        f"Sweep: {summary['scenarios']} combinations of assumptions",
        "",
        f"  {'Rule':<44}{'Beats both':>12}{'Worse than best solo':>23}{'Mean gain':>12}",
    ]
    suffix = {"fixed": f" ({DEFAULTS['deferRate'] * 100:.0f}%)", "threshold": f" ({DEFAULTS['threshold'] * 100:.0f}%)"}
    for key in POLICIES:
        r = summary["rules"][key]
        label = r["label"] + suffix.get(key, "")
        lines.append(f"  {label:<44}{r['shareBeatsBoth'] * 100:>11.0f}%{r['shareWorse'] * 100:>22.0f}%"
                     f"{r['meanGain'] * 100:>+9.1f} pts")
    lines += ["", f"  ('Beats both' means more than {m:.1f} pts above the better of the two.)", "",
              "  What drives the gain (mean gain of the best possible rule; share where 'whoever is surer' beats both):"]
    for factor, levels in summary["effects"].items():
        cells = "   ".join(f"{e['level']:g}: {e['meanBestGain'] * 100:+.1f} / {e['shareSurerBeatsBoth'] * 100:.0f}%"
                           for e in levels)
        lines.append(f"    {FACTOR_NAMES[factor]:<38}{cells}")
    return "\n".join(lines)


def sweep_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: round(v, 6) if isinstance(v, float) else v for k, v in row.items()})
    return buf.getvalue()
