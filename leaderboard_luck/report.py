"""Plain-text reports for the command line."""

from __future__ import annotations

from .model import RULE_LABELS, checkpoint_day, sample_competition


def pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def signed(v: float, digits: int = 1) -> str:
    r = round(v * 100, digits)
    return f"{0:.{digits}f}%" if r == 0 else f"{r:+.{digits}f}%"


SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{SUFFIXES.get(n % 10, 'th')}"


def describe(p: dict) -> list[str]:
    n_gamblers = int(p["gamblers"] * (p["teams"] - 1) + 0.5)
    lines = [
        f"  {p['teams']} teams, {p['days']} trading days, ranked on: {RULE_LABELS[p['rule']].lower()}"
        + (f" ({pct(p['drawdownLimit'], 0)})" if p["rule"] == "drawdown" else ""),
        f"  Your team: true Sharpe {p['yourSharpe']:.2f} at {pct(p['yourVol'], 0)} volatility",
        f"  Rivals: skill spread {p['skillSpread']:.2f}, typical risk {pct(p['fieldVol'], 0)}, "
        f"{n_gamblers} gamblers at {p['gamblerMultiple']:g}x risk, market correlation {p['correlation']:.2f}"
        + (", fat tails" if p["fatTails"] else ""),
    ]
    if p["catchUp"] or p["rivalsCatchUp"] > 0:
        lines.append(f"  Going for broke at the checkpoint (day {checkpoint_day(p)}): your team "
                     + (f"switches to {pct(p['catchUpVol'], 0)} if outside the top 3" if p["catchUp"] else "does not")
                     + f"; {pct(p['rivalsCatchUp'], 0)} of steady rivals switch to {p['gamblerMultiple']:g}x their risk")
    return lines


def simulate_report(r: dict) -> str:
    p = r["params"]
    you = r["you"]
    w = r["winners"]
    lines = ["Leaderboard luck", ""] + describe(p) + [
        f"  {r['sims']:,} simulated challenges, luck number {p['seed']}",
        "",
        f"  Your team is better than {pct(r['skillPercentile'], 0)} of the field.",
        f"  Chance of winning       {pct(you['pWin']):>7}   (fair share {pct(1 / p['teams'])})",
        f"  Chance of a top 3       {pct(you['pTop3']):>7}",
        f"  Average finishing place {you['meanRank']:>7.1f}",
    ]
    if you["pOut"] > 0:
        lines.append(f"  Knocked out             {pct(you['pOut']):>7}")
    if p["catchUp"]:
        lines.append(f"  Went for broke          {pct(you['pSwitched']):>7}")
    lines += ["", "  Who wins:",
              f"    your team {pct(w['you'])}, a gambler {pct(w['gambler'])}, a steady team {pct(w['steady'])}"
              + (f", nobody {pct(w['none'])}" if w["none"] > 0 else ""),
              f"    the most skilled team wins {pct(w['mostSkilled'])}; the winner has no real edge in {pct(w['noEdge'])}"
              + (f"; the winner went for broke in {pct(w['switched'])}" if p["catchUp"] or p["rivalsCatchUp"] > 0 else ""),
              "", "  Your chances at other levels of risk (same luck):",
              f"    {'Volatility':>10}{'Win':>9}{'Top 3':>9}{'Avg place':>11}{'Out':>8}"]
    for c in r["curve"]:
        lines.append(f"    {pct(c['vol'], 0):>10}{pct(c['pWin']):>9}{pct(c['pTop3']):>9}{c['meanRank']:>11.1f}{pct(c['pOut']):>8}")
    lines.append(f"  Best chance of winning: {pct(r['bestPWin'])} at {pct(r['bestVol'], 0)} volatility")
    return "\n".join(lines)


def sample_report(params: dict, k: int, top: int = 10) -> str:
    teams = sample_competition(params, k)
    lines = [f"Challenge number {k + 1}", "",
             f"  {'Place':<7}{'Team':<12}{'Type':<9}{'Skill':>7}{'Risk':>7}{'Return':>9}{'Drawdown':>10}  Status"]
    shown = [t for t in teams if t["rank"] <= top]
    you = next(t for t in teams if t["you"])
    if you["rank"] > top:
        shown.append(you)
    for t in shown:
        kind = "You" if t["you"] else ("Gambler" if t["gambler"] else "Steady")
        status = "Blown up" if t["bust"] else ("Out: drawdown" if t["out"] else "")
        if t["switchDay"] is not None:
            status = (status + "; " if status else "") + f"went for broke on day {t['switchDay']}"
        place = "-" if t["out"] else ordinal(t["rank"])
        lines.append(f"  {place:<7}{t['name']:<12}{kind:<9}{t['sharpe']:>7.2f}{pct(t['vol'], 0):>7}"
                     f"{signed(t['ret']):>9}{pct(t['maxDD']):>10}  {status}")
    return "\n".join(lines)
