"""Plain-text and CSV reports for the command-line tool."""

from __future__ import annotations

import csv
import io

from .model import POLICIES, analyse
from .sessions import counterfactuals, score_session

MISTAKE_NAMES = {
    "random": "mistakes anywhere",
    "hard": "mistakes on tricky payments",
    "easy": "mistakes on obvious payments",
}

STYLE_NAMES = {
    "calibrated": "honest confidence",
    "confident": "always sounds sure",
    "hidden": "confidence hidden",
}


def pct(v: float | None, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def pts(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:+.1f} pts"


def model_report(params: dict | None = None) -> str:
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
    ]
    return "\n".join(lines)


def session_report(session: dict, threshold: float = 0.8) -> str:
    trials = session["trials"]
    m = score_session(trials)
    s = session.get("settings", {})
    style = STYLE_NAMES.get(s.get("aiStyle"), "unknown advisor")
    if s.get("mistakes") in MISTAKE_NAMES:
        style += ", " + MISTAKE_NAMES[s["mistakes"]]
    tag = " (synthetic)" if session.get("synthetic") else ""
    lines = [
        f"{session.get('label', 'session')}{tag}: {m['n']} cases, advisor {style}",
        f"  First calls {pct(m['initialAccuracy'], 0)}, AI {pct(m['aiAccuracy'], 0)}, "
        f"final {pct(m['finalAccuracy'], 0)} ({pts(m['complementarity'])} on the better of the two)",
        f"  Switched to a right AI {m['switchedToAI']} of {m['aiOnlyRight']} times; "
        f"held firm against a wrong AI {m['keptOwn']} of {m['youOnlyRight']} times",
        f"  Confidence: mean {pct(m['meanConfidence'], 0)}, overconfidence {pts(m['overconfidence'])}, "
        f"separates right from wrong with AUROC "
        + ("n/a" if m["confidenceAuroc"] is None else f"{m['confidenceAuroc']:.2f}"),
        "  Same cases, other strategies:",
    ]
    for cf in counterfactuals(trials, threshold):
        value = pct(cf["accuracy"], 0) if cf["available"] else "n/a (AI confidence hidden)"
        lines.append(f"    {cf['label']:<48}{value}")
    return "\n".join(lines)


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def class_rows(sessions: list[dict]) -> list[dict]:
    rows = []
    for session in sessions:
        m = score_session(session["trials"])
        rows.append({
            "label": session.get("label", ""),
            "habit": session.get("habit", ""),
            "aiStyle": session.get("settings", {}).get("aiStyle", ""),
            **m,
        })
    return rows


def class_report(sessions: list[dict]) -> str:
    rows = class_rows(sessions)
    lines = [
        f"Class summary: {len(rows)} sessions",
        "",
        f"  {'Who':<8}{'Advisor':<22}{'First':>7}{'AI':>7}{'Final':>7}{'RAIR':>7}{'RSR':>7}{'vs best':>11}",
    ]
    for r in rows:
        lines.append(
            f"  {r['label'][:7]:<8}{STYLE_NAMES.get(r['aiStyle'], r['aiStyle'] or 'unknown'):<22}"
            f"{pct(r['initialAccuracy'], 0):>7}{pct(r['aiAccuracy'], 0):>7}{pct(r['finalAccuracy'], 0):>7}"
            f"{pct(r['rair'], 0):>7}{pct(r['rsr'], 0):>7}{pts(r['complementarity']):>11}")
    lines.append("")
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["aiStyle"] or "unknown", []).append(r)
    for style, group in sorted(groups.items()):
        beat = sum(r["complementarity"] > 0 for r in group)
        lines.append(
            f"  Advisor {STYLE_NAMES.get(style, style)} ({len(group)} sessions): final {pct(_mean([r['finalAccuracy'] for r in group]))}, "
            f"RAIR {pct(_mean([r['rair'] for r in group]), 0)}, RSR {pct(_mean([r['rsr'] for r in group]), 0)}, "
            f"{beat} of {len(group)} beat both the AI and their own first call")
    return "\n".join(lines)


CSV_FIELDS = ["label", "habit", "aiStyle", "n", "initialAccuracy", "aiAccuracy", "finalAccuracy",
              "agreeRate", "switchRate", "rair", "rsr", "overRelianceRate", "underRelianceRate",
              "helpfulSwitches", "harmfulSwitches", "meanConfidence", "overconfidence",
              "confidenceAuroc", "aiConfidenceAuroc", "complementarity"]


def class_csv(sessions: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in class_rows(sessions):
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in CSV_FIELDS})
    return buf.getvalue()
