"""A self-contained HTML class report: open it in any browser, no internet needed."""

from __future__ import annotations

import html

from .report import MISTAKE_NAMES, STYLE_NAMES, class_rows, interval, pct, pts
from .sessions import bootstrap, bootstrap_mean

STYLE_COLOURS = {"calibrated": "#2a78d6", "confident": "#eb6834", "hidden": "#1baf7a"}

CSS = """
:root { color-scheme: light; --bg:#f6f5f1; --surface:#fcfcfb; --ink:#16181d; --ink-2:#4a4945; --muted:#6b6963;
  --line:#e1e0d9; --line-strong:#c3c2b7; --good:#0a6b1f; --bad:#b42323; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --bg:#111110; --surface:#1a1a19; --ink:#f0efec;
  --ink-2:#c9c8c0; --muted:#a3a29a; --line:#2f2f2c; --line-strong:#46463f; --good:#5fd07a; --bad:#ff8a80; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; } h2 { font-size: 1.15rem; margin: 0 0 8px; }
.lede { color: var(--ink-2); margin: 0 0 18px; max-width: 70ch; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:16px; }
.tiles { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:16px; }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
.tile .k { font-size:.8125rem; color:var(--muted); } .tile .v { font-size:1.6rem; font-weight:700; }
.tile .s { font-size:.8125rem; color:var(--ink-2); }
@media (max-width: 700px) { .tiles { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.875rem; font-variant-numeric:tabular-nums; }
th, td { padding:6px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align:left; }
thead th { color:var(--muted); }
.good { color:var(--good); } .bad { color:var(--bad); }
svg text { fill: var(--ink-2); font: 12px system-ui,-apple-system,"Segoe UI",sans-serif; }
.legend { display:flex; gap:16px; flex-wrap:wrap; font-size:.875rem; color:var(--ink-2); margin-bottom:8px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }
.note { color: var(--muted); font-size: .875rem; }
"""


def _e(text) -> str:
    return html.escape(str(text))


def _scatter(rows: list[dict]) -> str:
    """Relative AI reliance (x) against relative self-reliance (y), one dot per session."""
    w, h, m = 520, 400, {"l": 52, "r": 16, "t": 16, "b": 46}
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]

    def sx(v):
        return m["l"] + pw * v

    def sy(v):
        return m["t"] + ph * (1 - v)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" '
             f'aria-label="Each session plotted by how often it switched to a right AI and held firm against a wrong one">']
    for v in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f'<line x1="{sx(v)}" x2="{sx(v)}" y1="{m["t"]}" y2="{m["t"] + ph}" stroke="var(--line)"/>')
        parts.append(f'<line x1="{m["l"]}" x2="{m["l"] + pw}" y1="{sy(v)}" y2="{sy(v)}" stroke="var(--line)"/>')
        parts.append(f'<text x="{sx(v)}" y="{m["t"] + ph + 16}" text-anchor="middle">{v * 100:.0f}%</text>')
        parts.append(f'<text x="{m["l"] - 6}" y="{sy(v) + 4}" text-anchor="end">{v * 100:.0f}%</text>')
    parts.append(f'<text x="{m["l"] + pw / 2}" y="{h - 6}" text-anchor="middle" style="font-weight:600">'
                 'Switched to a right AI</text>')
    parts.append(f'<text transform="translate(14 {m["t"] + ph / 2}) rotate(-90)" text-anchor="middle" '
                 'style="font-weight:600">Held firm against a wrong AI</text>')
    for x, y, anchor, label in [(0.98, 0.97, "end", "Appropriate reliance"), (0.98, 0.03, "end", "Over-reliance"),
                                (0.02, 0.97, "start", "Under-reliance"), (0.02, 0.03, "start", "Neither")]:
        parts.append(f'<text x="{sx(x)}" y="{sy(y) + (12 if y > 0.5 else -4)}" text-anchor="{anchor}" '
                     f'style="font-weight:600;fill:var(--muted)">{label}</text>')
    for r in rows:
        if r["rair"] is None or r["rsr"] is None:
            continue
        colour = STYLE_COLOURS.get(r["aiStyle"], "#898781")
        parts.append(f'<circle cx="{sx(r["rair"]):.1f}" cy="{sy(r["rsr"]):.1f}" r="6" fill="{colour}" '
                     f'stroke="var(--surface)" stroke-width="2" fill-opacity="0.85"><title>{_e(r["label"])}: '
                     f'switched {pct(r["rair"], 0)}, held firm {pct(r["rsr"], 0)}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def class_html(sessions: list[dict], title: str = "Reliance lab: class report") -> str:
    rows = class_rows(sessions)
    n = len(rows)
    comp = [r["complementarity"] for r in rows]
    beat = sum(c > 0 for c in comp)
    synthetic = sum(bool(s.get("synthetic")) for s in sessions)

    def mean(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return sum(vals) / len(vals) if vals else None

    styles = sorted({r["aiStyle"] for r in rows if r["aiStyle"]})
    legend = "".join(f'<span><i style="background:{STYLE_COLOURS.get(st, "#898781")}"></i>'
                     f'Advisor: {_e(STYLE_NAMES.get(st, st))}</span>' for st in styles)
    missing = sum(r["rair"] is None or r["rsr"] is None for r in rows)
    body = []
    for s, r in zip(sessions, rows):
        ci = bootstrap(s["trials"])
        cls = "good" if r["complementarity"] > 0 else ("bad" if r["complementarity"] < 0 else "")
        mistakes = MISTAKE_NAMES.get(s.get("settings", {}).get("mistakes"), "")
        body.append(
            f"<tr><td>{_e(r['label'])}</td><td>{_e(STYLE_NAMES.get(r['aiStyle'], r['aiStyle'] or 'unknown'))}"
            f"{'<br><span class=note>' + _e(mistakes) + '</span>' if mistakes else ''}</td>"
            f"<td>{pct(r['initialAccuracy'], 0)}</td><td>{pct(r['aiAccuracy'], 0)}</td>"
            f"<td>{pct(r['finalAccuracy'], 0)}</td><td>{pct(r['rair'], 0)}</td><td>{pct(r['rsr'], 0)}</td>"
            f"<td class='{cls}'>{pts(r['complementarity'])}</td><td>{interval(ci['complementarity'], points=True)}</td></tr>")
    note = (f"{synthetic} of these {n} sessions are synthetic (generated, not real people)." if synthetic else "")
    return f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{_e(title)}</h1>
<p class="lede">{n} sessions scored. Each person made their own call on every payment, saw the advisor's view, then made a final call. {_e(note)}</p>
<div class="tiles">
<div class="tile"><div class="k">First calls (mean)</div><div class="v">{pct(mean('initialAccuracy'), 0)}</div></div>
<div class="tile"><div class="k">Advisor (mean)</div><div class="v">{pct(mean('aiAccuracy'), 0)}</div></div>
<div class="tile"><div class="k">Final calls (mean)</div><div class="v">{pct(mean('finalAccuracy'), 0)}</div></div>
<div class="tile"><div class="k">Beat both</div><div class="v">{beat} of {n}</div>
<div class="s">Mean gain {pts(sum(comp) / n)}, 95% interval {interval(bootstrap_mean(comp), points=True)}</div></div>
</div>
<div class="card"><h2>How each person used the advice</h2>
<p class="note">Right is better on both axes. Sessions with no disagreement of one kind cannot be placed{f' ({missing} left out)' if missing else ''}.</p>
<div class="legend">{legend}</div>{_scatter(rows)}</div>
<div class="card"><h2>Every session</h2><div class="wrap"><table>
<thead><tr><th>Who</th><th>Advisor</th><th>First</th><th>AI</th><th>Final</th><th>Switched to right AI</th>
<th>Held firm</th><th>On better of two</th><th>95% interval</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
<p class="note">Intervals are percentile bootstraps over each session's payments (1,000 resamples). With 20 payments they are wide: treat single sessions as a conversation starter.</p></div>
</main></body></html>
"""
