"""Plain-text and self-contained HTML reports. Standard library only."""

from __future__ import annotations

import html
import math
from typing import List, Optional, Sequence

from .analysis import LeverEffect
from .robustness import RobustnessReport
from .model import BARRIERS, IN_PROGRESS, KILLED, OUTCOMES, PURGATORY, SCALED, Summary

OUTCOME_COLOURS = {SCALED: "#2e7d4f", KILLED: "#8a8f98", PURGATORY: "#d9822b", IN_PROGRESS: "#7fa7d9"}
SERIES_COLOURS = ("#c2571a", "#2b5fab", "#6b4fa8", "#2e7d4f")


def money(k: float) -> str:
    """Format GBP thousands as GBP millions, e.g. 1234 -> '£1.2m'."""
    sign = "-" if k < 0 else ""
    return f"{sign}£{abs(k) / 1000:.1f}m"


def signed_money(k: float) -> str:
    return ("+" if k >= 0 else "") + money(k)


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def points(change: float) -> str:
    """Describe a percentage-point change in words, e.g. -6.2 -> 'down 6 points'."""
    n = round(abs(change))
    if n == 0:
        return "no change"
    return f"{'up' if change > 0 else 'down'} {n} point{'s' if n != 1 else ''}"


def payback(summary: Summary) -> str:
    q = summary.payback_quarter
    return f"Q{q}" if q is not None else "Not within horizon"


def _short(name: str) -> str:
    return name.split(" (")[0]


# ---------------------------------------------------------------- text report


def text_report(
    summaries: Sequence[Summary],
    effects: List[LeverEffect],
    seed: int,
    robustness: Optional[RobustnessReport] = None,
) -> str:
    first = summaries[0]
    names = [_short(s.strategy.name) for s in summaries]
    spreads = [f"{money(s.net_value.p10)} to {money(s.net_value.p90)}" for s in summaries]
    paybacks = [payback(s) for s in summaries]
    w = max(16, *(len(n) + 3 for n in names), *(len(x) + 3 for x in spreads + paybacks))
    label_w = 36

    def row(label: str, values: Sequence[str]) -> str:
        return label.ljust(label_w) + "".join(v.rjust(w) for v in values)

    lines = [
        f"Pilot purgatory simulator  |  {first.runs} runs, {first.quarters} quarters, seed {seed}",
        "",
        row("", names),
        row("Pilots launched (mean)", [f"{s.pilots_launched:.1f}" for s in summaries]),
        row("Scaled", [pct(s.outcome_share[SCALED]) for s in summaries]),
        row("Stopped", [pct(s.outcome_share[KILLED]) for s in summaries]),
        row("Stuck in pilot purgatory", [pct(s.outcome_share[PURGATORY]) for s in summaries]),
        row("Still in progress", [pct(s.outcome_share[IN_PROGRESS]) for s in summaries]),
        row("Value captured (mean)", [money(s.value_captured) for s in summaries]),
        row("Pilot spend (mean)", [money(s.pilot_spend) for s in summaries]),
        row("Spend on pilots that never scaled", [money(s.wasted_spend) for s in summaries]),
        row("Net value (mean)", [money(s.net_value.mean) for s in summaries]),
        row("  10th to 90th percentile", spreads),
        row("Payback quarter", paybacks),
        row("Good pilots that never scaled", [f"{s.missed_opportunities:.1f}" for s in summaries]),
        row(
            "Median quarter of scaling",
            ["n/a" if s.median_quarters_to_scale != s.median_quarters_to_scale else f"Q{s.median_quarters_to_scale:g}" for s in summaries],
        ),
        "",
        "Why pilots stall (share of pilots that never scaled)",
    ]
    for barrier in BARRIERS:
        lines.append(row(f"  {barrier}", [pct(s.barrier_share[barrier]) for s in summaries]))

    if effects:
        lines += ["", f"Single fixes for '{names[0]}', ranked by net value"]
        for i, e in enumerate(effects, 1):
            lines.append(
                f"  {i}. {e.lever.ljust(38)}{signed_money(e.net_value_change).rjust(9)} net value, "
                f"{e.scaled_change:+.0f} pts scaled, {e.purgatory_change:+.0f} pts in purgatory"
            )
    if robustness is not None:
        n = len(robustness.results)
        lines += [
            "",
            f"Robustness: strategy first beats pilots first in {robustness.strategy_first_wins} of {n} scenarios",
            f"  {'Scenario'.ljust(24)}{'Pilots first'.rjust(14)}{'Strategy first'.rjust(16)}   Best single fix",
        ]
        for r in robustness.results:
            lines.append(
                f"  {r.scenario.name.ljust(24)}{money(r.pilots_first_net).rjust(14)}"
                f"{money(r.strategy_first_net).rjust(16)}   {r.top_lever}"
            )
        counts = ", ".join(f"{k} ({v})" for k, v in robustness.top_lever_counts.items())
        lines.append(f"  Best single fix across scenarios: {counts}")
    lines += ["", "Illustrative model with assumed parameters. Change them in pilot_purgatory/strategies.py."]
    return "\n".join(lines)


# ---------------------------------------------------------------- SVG charts


def _svg_outcome_mix(summaries: Sequence[Summary]) -> str:
    width, label_w, bar_h, gap = 720, 230, 34, 18
    bar_w = width - label_w - 20
    height = len(summaries) * (bar_h + gap) + 40
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Outcome mix by strategy">']
    for i, s in enumerate(summaries):
        y = 10 + i * (bar_h + gap)
        parts.append(
            f'<text x="0" y="{y + bar_h / 2 + 5}" class="lbl">{html.escape(_short(s.strategy.name))}</text>'
        )
        x = label_w
        for outcome in OUTCOMES:
            share = s.outcome_share[outcome]
            seg = bar_w * share
            if seg <= 0:
                continue
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{seg:.1f}" height="{bar_h}" fill="{OUTCOME_COLOURS[outcome]}">'
                f"<title>{html.escape(outcome)}: {pct(share)}</title></rect>"
            )
            if seg > 44:
                parts.append(
                    f'<text x="{x + seg / 2:.1f}" y="{y + bar_h / 2 + 5}" class="inbar" text-anchor="middle">{pct(share)}</text>'
                )
            x += seg
    ly = height - 14
    lx = label_w
    step = (width - label_w) / len(OUTCOMES)
    for outcome in OUTCOMES:
        parts.append(f'<rect x="{lx:.0f}" y="{ly - 10}" width="12" height="12" fill="{OUTCOME_COLOURS[outcome]}"/>')
        parts.append(f'<text x="{lx + 18:.0f}" y="{ly}" class="leg">{html.escape(outcome)}</text>')
        lx += step
    parts.append("</svg>")
    return "".join(parts)


def _svg_barriers(summaries: Sequence[Summary]) -> str:
    width, label_w, bar_h, inner_gap, group_gap = 720, 230, 14, 3, 16
    bar_w = width - label_w - 70
    n = len(summaries)
    group_h = n * bar_h + (n - 1) * inner_gap
    height = len(BARRIERS) * (group_h + group_gap) + 30
    top = max((s.barrier_share[b] for s in summaries for b in BARRIERS), default=0.0) or 1.0
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Why pilots stall, by strategy">']
    for gi, barrier in enumerate(BARRIERS):
        gy = 6 + gi * (group_h + group_gap)
        parts.append(f'<text x="0" y="{gy + group_h / 2 + 5}" class="lbl">{html.escape(barrier)}</text>')
        for si, s in enumerate(summaries):
            share = s.barrier_share[barrier]
            y = gy + si * (bar_h + inner_gap)
            w = bar_w * share / top
            colour = SERIES_COLOURS[si % len(SERIES_COLOURS)]
            parts.append(
                f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="2" fill="{colour}">'
                f"<title>{html.escape(_short(s.strategy.name))}: {pct(share)}</title></rect>"
            )
            parts.append(f'<text x="{label_w + w + 6:.1f}" y="{y + bar_h - 3}" class="val">{pct(share)}</text>')
    ly = height - 8
    lx = label_w
    for si, s in enumerate(summaries):
        colour = SERIES_COLOURS[si % len(SERIES_COLOURS)]
        parts.append(f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{colour}"/>')
        parts.append(f'<text x="{lx + 18}" y="{ly}" class="leg">{html.escape(_short(s.strategy.name))}</text>')
        lx += 190
    parts.append("</svg>")
    return "".join(parts)


def _svg_levers(effects: List[LeverEffect]) -> str:
    width, label_w, bar_h, gap = 720, 290, 22, 12
    plot_w = width - label_w - 90
    height = len(effects) * (bar_h + gap) + 10
    biggest = max((abs(e.net_value_change) for e in effects), default=0.0) or 1.0
    has_negative = any(e.net_value_change < 0 for e in effects)
    zero_x = label_w + (plot_w / 2 if has_negative else 0)
    scale = (plot_w / 2 if has_negative else plot_w) / biggest
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Change in net value from each single fix">']
    for i, e in enumerate(effects):
        y = 5 + i * (bar_h + gap)
        w = e.net_value_change * scale
        x = zero_x if w >= 0 else zero_x + w
        colour = "#2e7d4f" if w >= 0 else "#b23b3b"
        parts.append(f'<text x="0" y="{y + bar_h / 2 + 5}" class="lbl">{html.escape(e.lever)}</text>')
        parts.append(
            f'<rect x="{x:.1f}" y="{y}" width="{abs(w):.1f}" height="{bar_h}" rx="2" fill="{colour}">'
            f"<title>{html.escape(e.lever)}: {signed_money(e.net_value_change)}</title></rect>"
        )
        tx = zero_x + w + (6 if w >= 0 else -6)
        anchor = "start" if w >= 0 else "end"
        parts.append(
            f'<text x="{tx:.1f}" y="{y + bar_h / 2 + 5}" class="val" text-anchor="{anchor}">{signed_money(e.net_value_change)}</text>'
        )
    parts.append(f'<line x1="{zero_x}" y1="0" x2="{zero_x}" y2="{height}" stroke="#555" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_timeline(summaries: Sequence[Summary]) -> str:
    width, height, left, right, top, bottom = 720, 300, 66, 150, 16, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [snap.net_value for s in summaries for snap in s.timeline] + [0.0]
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    step = _nice_step(hi - lo)
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    quarters = max(len(s.timeline) for s in summaries)

    def x(q: int) -> float:
        return left + (q - 1) / max(1, quarters - 1) * plot_w

    def y(v: float) -> float:
        return top + (hi - v) / (hi - lo) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Cumulative net value by quarter">']
    v = lo
    while v <= hi + 1e-6:
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e3e6eb"/>')
        label = money(v) if step < 1000 else f"{'-' if v < 0 else ''}£{abs(v) / 1000:.0f}m"
        parts.append(f'<text x="{left - 8}" y="{y(v) + 4:.1f}" class="val" text-anchor="end">{label}</text>')
        v += step
    parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#555"/>')
    for q in range(1, quarters + 1):
        if quarters <= 12 or q % 2 == 0:
            parts.append(f'<text x="{x(q):.1f}" y="{height - bottom + 18}" class="val" text-anchor="middle">Q{q}</text>')
    for si, s in enumerate(summaries):
        colour = SERIES_COLOURS[si % len(SERIES_COLOURS)]
        pts = " ".join(f"{x(t.quarter):.1f},{y(t.net_value):.1f}" for t in s.timeline)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="3"/>')
        last = s.timeline[-1]
        parts.append(
            f'<text x="{x(last.quarter) + 10:.1f}" y="{y(last.net_value) + 4:.1f}" class="lbl" fill="{colour}">'
            f"{html.escape(_short(s.strategy.name))}: {money(last.net_value)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _nice_step(span: float) -> float:
    raw = span / 4
    mag = 10 ** math.floor(math.log10(raw))
    n = raw / mag
    return (1 if n <= 1 else 2 if n <= 2 else 2.5 if n <= 2.5 else 5 if n <= 5 else 10) * mag


def _robustness_table(robustness: RobustnessReport) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(r.scenario.name)}<br><span class=\"muted\">{html.escape(r.scenario.description)}</span></td>"
        f"<td>{money(r.pilots_first_net)}</td><td>{money(r.strategy_first_net)}</td>"
        f"<td class=\"l\">{html.escape(r.top_lever)}</td></tr>"
        for r in robustness.results
    )
    n = len(robustness.results)
    counts = "; ".join(f"{html.escape(k)} in {v}" for k, v in robustness.top_lever_counts.items())
    return (
        "<h2>Do the conclusions survive different assumptions?</h2>"
        f"<p>Strategy first beats pilots first in <strong>{robustness.strategy_first_wins} of {n}</strong> scenarios. "
        f"The best single fix is less settled: {counts}.</p>"
        "<table><thead><tr><th>Scenario</th><th>Pilots first</th><th>Strategy first</th><th class=\"l\">Best single fix</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# ---------------------------------------------------------------- HTML report

_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
max-width:820px;margin:40px auto;padding:0 20px;color:#1d2430;line-height:1.5}
h1{font-size:1.7rem;margin-bottom:.2rem}h2{font-size:1.15rem;margin-top:2.2rem}
.sub{color:#5a6372;margin-top:0}
table{border-collapse:collapse;width:100%;font-size:.93rem}
th,td{padding:6px 8px;border-bottom:1px solid #e3e6eb;text-align:right}
th:first-child,td:first-child{text-align:left}
svg{width:100%;height:auto;margin-top:.5rem}
.lbl{font-size:13px;fill:#1d2430}.val{font-size:12px;fill:#1d2430}
.inbar{font-size:12px;fill:#fff;font-weight:600}.leg{font-size:12px;fill:#3a4350}
.muted{color:#5a6372;font-size:.85rem}
th.l,td.l{text-align:left}
.note{font-size:.85rem;color:#5a6372;margin-top:2.5rem;border-top:1px solid #e3e6eb;padding-top:1rem}
"""


def html_report(
    summaries: Sequence[Summary],
    effects: List[LeverEffect],
    seed: int,
    robustness: Optional[RobustnessReport] = None,
) -> str:
    first = summaries[0]
    heads = "".join(f"<th>{html.escape(_short(s.strategy.name))}</th>" for s in summaries)

    def tr(label: str, values: Sequence[str]) -> str:
        return f"<tr><td>{html.escape(label)}</td>" + "".join(f"<td>{html.escape(v)}</td>" for v in values) + "</tr>"

    rows = [
        tr("Pilots launched (mean)", [f"{s.pilots_launched:.1f}" for s in summaries]),
        tr("Scaled", [pct(s.outcome_share[SCALED]) for s in summaries]),
        tr("Stuck in pilot purgatory", [pct(s.outcome_share[PURGATORY]) for s in summaries]),
        tr("Value captured (mean)", [money(s.value_captured) for s in summaries]),
        tr("Spend on pilots that never scaled", [money(s.wasted_spend) for s in summaries]),
        tr("Net value (mean)", [money(s.net_value.mean) for s in summaries]),
        tr("Net value, 10th to 90th percentile", [f"{money(s.net_value.p10)} to {money(s.net_value.p90)}" for s in summaries]),
        tr("Payback quarter", [payback(s) for s in summaries]),
        tr("Good pilots that never scaled (per portfolio)", [f"{s.missed_opportunities:.1f}" for s in summaries]),
    ]

    lever_section = ""
    if effects:
        best = effects[0]
        org = _short(first.strategy.name).lower().replace(" ", "-")
        twist = ""
        if best.scaled_change < -0.5:
            twist = (
                " Notice that it actually scales fewer pilots. The gain comes from no longer paying, quarter"
                " after quarter, for pilots that were never going to make it."
            )
        lever_section = (
            f"<h2>Which single fix helps a {html.escape(org)} organisation most?</h2>"
            f"<p>Each bar applies one governance practice on its own and leaves everything else unchanged. "
            f"In this run the biggest single gain comes from <strong>{html.escape(best.lever.lower())}</strong> "
            f"({html.escape(signed_money(best.net_value_change))} net value, {html.escape(points(best.scaled_change))} "
            f"in the share of pilots scaled).{twist}</p>"
            + _svg_levers(effects)
        )

    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pilot purgatory simulator report</title><style>{_CSS}</style></head>
<body>
<h1>Pilot purgatory simulator</h1>
<p class="sub">{first.runs} simulated portfolios per strategy, {first.quarters} quarters each, seed {seed}</p>
<p>Why do so many AI pilots never make it to production? This report compares two ways of running an AI pilot
portfolio and traces every pilot that did not scale back to the main thing that stopped it.</p>
<h2>Where the pilots end up</h2>
{_svg_outcome_mix(summaries)}
<table><thead><tr><th></th>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Cumulative net value over time</h2>
<p>Mean benefit captured minus everything spent so far, quarter by quarter.</p>
{_svg_timeline(summaries)}
<h2>Why pilots stall</h2>
<p>Share of pilots that never scaled, by the main barrier that held each one back.</p>
{_svg_barriers(summaries)}
{lever_section}
{_robustness_table(robustness) if robustness else ""}
<p class="note">Illustrative model. Every parameter is an assumption chosen to be plausible and easy to change,
not an estimate from real company data. Use it to reason about mechanisms and trade-offs, not to forecast.</p>
</body></html>
"""
