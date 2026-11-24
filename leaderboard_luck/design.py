"""The organiser's view: which scoring rule, and how long a challenge, lets skill show?

Runs ``skill_by_length`` (every scoring rule at every length from one week to a year) and writes
it as text, CSV or a self-contained HTML report.
"""

from __future__ import annotations

import csv
import html
import io

from .model import DURATIONS, RULE_LABELS, RULES
from .report import describe, pct

RULE_COLOURS = {"return": "#6250d6", "sharpe": "#008300", "drawdown": "#e87ba4"}
SHORT_NAMES = {"return": "Return", "sharpe": "Sharpe ratio", "drawdown": "Return with drawdown limit"}
IN_A_SENTENCE = {"return": "return", "sharpe": "Sharpe ratio", "drawdown": "return with a drawdown limit"}


def _by(rows: list[dict]) -> dict:
    return {(r["rule"], r["days"]): r for r in rows}


def length_label(days: int) -> str:
    return {5: "1 week", 10: "2 weeks", 20: "4 weeks", 40: "8 weeks", 60: "12 weeks", 120: "6 months",
            250: "1 year"}.get(days, f"{days} days")


def findings(rows: list[dict]) -> list[str]:
    """Plain-English conclusions, worked out from the numbers rather than assumed."""
    by = _by(rows)
    out = []
    best_rule_each = []
    for days in DURATIONS:
        best_rule_each.append(max(RULES, key=lambda rule: (by[(rule, days)]["pBestWins"], -RULES.index(rule))))
    winners = {rule: best_rule_each.count(rule) for rule in RULES}
    top = max(RULES, key=lambda rule: winners[rule])
    out.append(f"Ranking on {IN_A_SENTENCE[top]} picked out the most skilled team most often at "
               f"{winners[top]} of the {len(DURATIONS)} lengths tested.")
    year = {rule: by[(rule, DURATIONS[-1])] for rule in RULES}
    best_year = max(RULES, key=lambda rule: year[rule]["pBestWins"])
    share = year[best_year]["pBestWins"]
    out.append(f"Over {length_label(DURATIONS[-1])}, the most skilled team won {'only ' if share < 0.5 else ''}"
               f"{pct(share, 0)} of challenges under the best rule, and final places matched true skill with a "
               f"rank correlation of {year[best_year]['rankCorr']:.2f} (1 would be perfect).")
    month = {rule: by[(rule, 20)] for rule in RULES}
    out.append(f"Over four weeks, gamblers won {pct(month['return']['pGamblerWins'], 0)} of return-ranked "
               f"challenges against {pct(month['sharpe']['pGamblerWins'], 0)} ranked on Sharpe ratio, and the winner "
               f"had no real edge in {pct(month['return']['pNoEdgeWins'], 0)} of return-ranked ones.")
    return out


def design_report(params: dict, rows: list[dict], sims_each: int) -> str:
    by = _by(rows)
    lines = ["Leaderboard luck: how long before skill shows?", ""] + describe(params) + [
        f"  {sims_each:,} simulated challenges for each rule and length", "",
        "  Chance the most skilled team wins (rank correlation between true skill and final place):",
        "  " + f"{'Length':<10}" + "".join(f"{SHORT_NAMES[r]:>30}" for r in RULES)]
    for days in DURATIONS:
        cells = "".join(f"{pct(by[(r, days)]['pBestWins']) + ' (' + format(by[(r, days)]['rankCorr'], '.2f') + ')':>30}"
                        for r in RULES)
        lines.append(f"  {length_label(days):<10}{cells}")
    lines += [""] + [f"  {f}" for f in findings(rows)]
    return "\n".join(lines)


def design_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["rule", "days", "pBestWins", "rankCorr", "pNoEdgeWins", "pGamblerWins"],
                            lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: round(v, 6) if isinstance(v, float) else v for k, v in r.items()})
    return buf.getvalue()


CSS = """
:root { color-scheme: light; --bg:#f5f5f2; --surface:#fcfcfb; --ink:#15171c; --ink-2:#4a4945; --muted:#6b6963;
  --line:#e1e0d9; --line-strong:#c3c2b7; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --bg:#111110; --surface:#1a1a19; --ink:#f0efec;
  --ink-2:#c9c8c0; --muted:#a3a29a; --line:#2f2f2c; --line-strong:#46463f; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.6rem; margin: 0 0 6px; } h2 { font-size: 1.15rem; margin: 0 0 8px; }
.lede { color: var(--ink-2); max-width: 72ch; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:16px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:16px; }
.legend { display:flex; gap:16px; flex-wrap:wrap; font-size:.875rem; color:var(--ink-2); margin-bottom:8px; }
.legend i { display:inline-block; width:16px; height:3px; border-radius:2px; margin-right:6px; vertical-align:middle; }
svg text { fill: var(--ink-2); font: 11px system-ui,-apple-system,"Segoe UI",sans-serif; }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.875rem; font-variant-numeric:tabular-nums; }
th, td { padding:6px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
thead th { color:var(--muted); }
li { margin-bottom: 6px; }
.note { color: var(--muted); font-size: .875rem; }
"""


# Axis tops and how many gridlines they split into, chosen so every tick is a round number.
AXES = [(0.05, 5), (0.1, 5), (0.2, 4), (0.25, 5), (0.4, 4), (0.5, 5), (0.6, 6), (0.8, 4), (1.0, 5)]


def nice_axis(v: float) -> tuple:
    for top, ticks in AXES:
        if v <= top:
            return top, ticks
    return 1.0, 5


def _chart(rows: list[dict], key: str, label: str) -> str:
    by = _by(rows)
    w, h = 460, 240
    m = {"l": 46, "r": 22, "t": 12, "b": 36}
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]
    y_max, ticks = nice_axis(max(0.05, max(r[key] for r in rows)) * 1.05)

    def sx(i):
        return m["l"] + pw * i / (len(DURATIONS) - 1)

    def sy(v):
        return m["t"] + ph * (1 - v / y_max)

    desc = "; ".join(f"{SHORT_NAMES[r]}: " + ", ".join(f"{length_label(d)} {by[(r, d)][key]:.2f}" for d in DURATIONS)
                     for r in RULES)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{html.escape(label + ". " + desc)}">']
    for k in range(ticks + 1):
        v = y_max * k / ticks
        parts.append(f'<line x1="{m["l"]}" x2="{w - m["r"]}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="var(--line)"/>')
        text = pct(v, 0) if key != "rankCorr" else f"{v:.2f}".rstrip("0").rstrip(".")
        parts.append(f'<text x="{m["l"] - 6}" y="{sy(v) + 4:.1f}" text-anchor="end">{text}</text>')
    for i, d in enumerate(DURATIONS):
        anchor = "start" if i == 0 else ("end" if i == len(DURATIONS) - 1 else "middle")
        parts.append(f'<text x="{sx(i):.1f}" y="{h - 18}" text-anchor="{anchor}">{html.escape(length_label(d))}</text>')
    for rule in RULES:
        pts = " ".join(f"{'M' if i == 0 else 'L'}{sx(i):.1f} {sy(by[(rule, d)][key]):.1f}" for i, d in enumerate(DURATIONS))
        parts.append(f'<path d="{pts}" fill="none" stroke="{RULE_COLOURS[rule]}" stroke-width="2.5"/>')
        for i, d in enumerate(DURATIONS):
            parts.append(f'<circle cx="{sx(i):.1f}" cy="{sy(by[(rule, d)][key]):.1f}" r="3.5" fill="{RULE_COLOURS[rule]}">'
                         f'<title>{html.escape(SHORT_NAMES[rule])}, {html.escape(length_label(d))}: '
                         f'{by[(rule, d)][key]:.3f}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def design_html(params: dict, rows: list[dict], sims_each: int) -> str:
    by = _by(rows)
    legend = "".join(f'<span><i style="background:{RULE_COLOURS[r]}"></i>{html.escape(SHORT_NAMES[r])}</span>' for r in RULES)
    head = "".join(f"<th>{html.escape(SHORT_NAMES[r])}</th>" for r in RULES)
    body = "".join(
        f"<tr><td>{html.escape(length_label(d))}</td>"
        + "".join(f"<td>{pct(by[(r, d)]['pBestWins'])} <span class='note'>({by[(r, d)]['rankCorr']:.2f})</span></td>"
                  for r in RULES) + "</tr>" for d in DURATIONS)
    setting_lines = "".join(f"<li>{html.escape(line.strip())}</li>" for line in describe(params)[:1] + describe(params)[2:])
    found = "".join(f"<li>{html.escape(f)}</li>" for f in findings(rows))
    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Leaderboard luck: how long before skill shows?</title><style>{CSS}</style></head>
<body><main>
<h1>How long before skill shows?</h1>
<p class="lede">Each scoring rule simulated {sims_each:,} times at seven lengths, from one week to a year of trading days.
"Most skilled team wins" is how often the team with the highest true Sharpe ratio finishes first. Rank correlation
measures how closely the whole final table follows true skill: 0 is pure luck, 1 is perfectly.</p>
<div class="card"><h2>What the numbers say</h2><ul>{found}</ul></div>
<div class="card"><div class="legend">{legend}</div>
<div class="grid"><div><h2>Most skilled team wins</h2>{_chart(rows, "pBestWins", "Chance the most skilled team wins")}</div>
<div><h2>Rank correlation with true skill</h2>{_chart(rows, "rankCorr", "Rank correlation between true skill and final place")}</div></div></div>
<div class="card"><h2>Every rule and length</h2><div class="wrap"><table>
<thead><tr><th>Length</th>{head}</tr></thead><tbody>{body}</tbody></table></div>
<p class="note">Each cell: chance the most skilled team wins (rank correlation in brackets).</p></div>
<div class="card"><h2>The field simulated</h2><ul>{setting_lines}</ul>
<p class="note">Rule names: {html.escape("; ".join(f"{SHORT_NAMES[r]}: {RULE_LABELS[r]}" for r in RULES))}.</p></div>
</main></body></html>
"""
