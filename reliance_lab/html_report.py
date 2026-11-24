"""A self-contained HTML report of the sweep: open it in any browser, no internet needed."""

from __future__ import annotations

import html

from .model import DEFAULTS, POLICIES
from .sweep import FACTOR_NAMES

CSS = """
:root { color-scheme: light; --bg:#f6f5f1; --surface:#fcfcfb; --surface-2:#f0efea; --ink:#16181d; --ink-2:#4a4945;
  --muted:#6b6963; --line:#e1e0d9; --bar:#1baf7a; --bar-2:#0d6b60; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --bg:#111110; --surface:#1a1a19; --surface-2:#232321;
  --ink:#f0efec; --ink-2:#c9c8c0; --muted:#a3a29a; --line:#2f2f2c; --bar:#199e70; --bar-2:#3fb8a5; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; } h2 { font-size: 1.15rem; margin: 0 0 8px; } h3 { font-size: .95rem; margin: 0 0 6px; min-height: 2.6em; }
.lede { color: var(--ink-2); margin: 0 0 18px; max-width: 72ch; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:16px; }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.9rem; font-variant-numeric:tabular-nums; }
th, td { padding:6px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; white-space:normal; }
thead th { color:var(--muted); }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(230px, 1fr)); gap:14px; }
.mini { background:var(--surface-2); border-radius:10px; padding:12px; }
svg text { fill: var(--ink-2); font: 11px system-ui,-apple-system,"Segoe UI",sans-serif; }
.note { color: var(--muted); font-size: .875rem; }
.legend { display:flex; gap:16px; flex-wrap:wrap; font-size:.875rem; color:var(--ink-2); margin-bottom:10px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }
"""


def _e(text) -> str:
    return html.escape(str(text))


def _mini_chart(levels: list[dict]) -> str:
    """Bars: mean gain of the best possible rule at each level. Labels: share where 'surer' beats both."""
    w, h = 220, 120
    top, bottom, left = 16, 30, 4
    n = len(levels)
    peak = max(max(e["meanBestGain"] for e in levels), 0.01)
    slot = (w - left * 2) / n
    bar_w = min(34, slot * 0.6)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="'
             + _e("; ".join(f"level {e['level']:g}: best rule gains {e['meanBestGain'] * 100:.1f} points, "
                            f"whoever is surer beats both in {e['shareSurerBeatsBoth'] * 100:.0f}%" for e in levels))
             + '">']
    base = h - bottom
    parts.append(f'<line x1="0" x2="{w}" y1="{base}" y2="{base}" stroke="var(--line)"/>')
    for i, e in enumerate(levels):
        x = left + slot * i + (slot - bar_w) / 2
        bh = (base - top) * max(e["meanBestGain"], 0) / peak
        parts.append(f'<rect x="{x:.1f}" y="{base - bh:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="3" fill="var(--bar)"/>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{base - bh - 4:.1f}" text-anchor="middle">'
                     f'+{e["meanBestGain"] * 100:.1f}</text>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{base + 13}" text-anchor="middle" style="font-weight:600">'
                     f'{e["level"]:g}</text>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{base + 26}" text-anchor="middle" style="fill:var(--bar-2)">'
                     f'{e["shareSurerBeatsBoth"] * 100:.0f}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def sweep_html(summary: dict, title: str = "Reliance lab: where does human review pay?") -> str:
    margin = summary["margin"] * 100
    suffix = {"fixed": f" ({DEFAULTS['deferRate'] * 100:.0f}%)", "threshold": f" ({DEFAULTS['threshold'] * 100:.0f}%)"}
    rows = "".join(
        f"<tr><td>{_e(summary['rules'][k]['label'] + suffix.get(k, ''))}</td>"
        f"<td>{summary['rules'][k]['shareBeatsBoth'] * 100:.0f}%</td>"
        f"<td>{summary['rules'][k]['shareWorse'] * 100:.0f}%</td>"
        f"<td>{summary['rules'][k]['meanGain'] * 100:+.1f} pts</td></tr>" for k in POLICIES)
    minis = "".join(
        f'<div class="mini"><h3>{_e(FACTOR_NAMES[factor])}</h3>{_mini_chart(levels)}</div>'
        for factor, levels in summary["effects"].items())
    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{_e(title)}</h1>
<p class="lede">The reliance model run across {summary['scenarios']:,} combinations of assumptions: two accuracies, how often
the person and the AI get the same cases wrong, how much each side's confidence tells you, and whether either is
overconfident. "Beats both" means the team is more than {margin:.1f} points above the better of the person and the AI alone.</p>
<div class="card"><h2>How often each rule beats both</h2><div class="wrap"><table>
<thead><tr><th>Rule for settling disagreements</th><th>Beats both</th><th>Worse than the better one</th><th>Mean gain</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="note">A fixed deferral rate can never beat both: in a yes or no decision exactly one side is right in a
disagreement, so a habit that ignores which disagreement it is lands between the two solo accuracies.</p></div>
<div class="card"><h2>What drives the gain</h2>
<div class="legend"><span><i style="background:var(--bar)"></i>Mean gain of the best possible rule (points)</span>
<span><i style="background:var(--bar-2)"></i>Share of scenarios where "go with whoever is surer" beats both</span></div>
<div class="grid">{minis}</div>
<p class="note">Each panel averages over every other assumption. Overconfidence never changes the best possible rule,
which reads both confidences correctly; it only hurts rules that take the shown confidence at face value, which is why the
gap between the two sides' overconfidence matters more than either on its own.</p></div>
</main></body></html>
"""
