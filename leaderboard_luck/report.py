"""Plain-text reports for the command line."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .model import RULE_LABELS, checkpoint_day, normalise, sample_competition


def fixed(x: float, digits: int) -> str:
    """Like JavaScript's toFixed: rounds the exact binary value, halves away from zero, so the
    reports print the same figures as the browser app (Python's format rounds halves to even)."""
    q = Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{q:.{digits}f}"


def pct(v: float, digits: int = 1) -> str:
    return fixed(v * 100, digits) + "%"


def signed(v: float, digits: int = 1) -> str:
    text = fixed(v * 100, digits)
    if float(text) == 0:
        return fixed(0, digits) + "%"
    return ("+" if v > 0 else "-") + text.lstrip("-") + "%"


SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{SUFFIXES.get(n % 10, 'th')}"


def standing(p: dict, share: float) -> str:
    """Where your team's skill stands against the rivals', in words (as in the browser app)."""
    if p["skillSpread"] == 0:
        if p["yourSharpe"] > 0:
            return "better than every rival"
        return "weaker than every rival" if p["yourSharpe"] < 0 else "exactly as skilled as every rival"
    if share >= 0.5:
        return "better than " + ("over 99%" if share >= 0.995 else pct(share, 0)) + " of the field"
    return "weaker than " + ("over 99%" if share <= 0.005 else pct(1 - share, 0)) + " of the field"


def rule_words(p: dict) -> str:
    """The scoring rule in the middle of a sentence, e.g. "highest Sharpe ratio"."""
    label = RULE_LABELS[p["rule"]]
    return label[0].lower() + label[1:] + (f" ({pct(p['drawdownLimit'], 0)})" if p["rule"] == "drawdown" else "")


def describe(p: dict, every_length: bool = False) -> list[str]:
    """The settings, one line each. ``every_length`` is for the design report, which runs every
    scoring rule at every length, so the length and rule settings do not apply."""
    n_gamblers = int(p["gamblers"] * (p["teams"] - 1) + 0.5)
    if every_length:
        first = (f"  {p['teams']} teams, every length from 1 week to 1 year, every scoring rule "
                 f"(drawdown limit {pct(p['drawdownLimit'], 0)})")
    else:
        first = f"  {p['teams']} teams, {p['days']} trading days, ranked on: {rule_words(p)}"
    lines = [
        first,
        f"  Your team: true Sharpe {p['yourSharpe']:.2f} at {pct(p['yourVol'], 0)} volatility",
        f"  Rivals: skill spread {p['skillSpread']:.2f}, typical risk {pct(p['fieldVol'], 0)}, "
        + (f"{n_gamblers} gambler{'' if n_gamblers == 1 else 's'} at {p['gamblerMultiple']:g}x risk, " if n_gamblers
           else "no gamblers, ")
        + f"market correlation {p['correlation']:.2f}" + (", fat tails" if p["fatTails"] else ""),
    ]
    if p["catchUp"] or p["rivalsCatchUp"] > 0:
        when = f"{pct(p['checkpoint'], 0)} of the way through" if every_length else f"day {checkpoint_day(p)}"
        rivals = (f"{pct(p['rivalsCatchUp'], 0)} of steady rivals switch to {p['gamblerMultiple']:g}x their risk"
                  if p["rivalsCatchUp"] > 0 else "no steady rivals switch")
        lines.append(f"  Going for broke at the checkpoint ({when}): your team "
                     + (f"switches to {pct(p['catchUpVol'], 0)} if outside the top 3" if p["catchUp"] else "does not")
                     + f"; {rivals}")
    return lines


def simulate_report(r: dict) -> str:
    p = r["params"]
    you = r["you"]
    w = r["winners"]
    lines = ["Leaderboard luck", ""] + describe(p) + [
        f"  {r['sims']:,} simulated challenges, luck number {p['seed']}",
        "",
        f"  Your team is {standing(p, r['skillPercentile'])}.",
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
    chances = [c["pWin"] for c in r["curve"]]
    if max(chances) - min(chances) < 1e-9:
        lines.append(f"  Your chance of winning is the same at every level of risk: {pct(r['bestPWin'])}")
    else:
        lines.append(f"  Best chance of winning: {pct(r['bestPWin'])} at {pct(r['bestVol'], 0)} volatility")
    return "\n".join(lines)


def sample_report(params: dict, k: int, top: int = 10) -> str:
    """One challenge's final table: the first ``top`` places and your team (every team if top is 0)."""
    p = normalise(params)
    teams = sample_competition(p, k)
    top = top if top > 0 else len(teams)
    lines = [f"Challenge number {k + 1}", "", *describe(p), f"  Luck number {p['seed']}", "",
             f"  {'Place':<7}{'Team':<12}{'Type':<9}{'Skill':>7}{'Risk':>9}{'Return':>9}{'Drawdown':>10}  Status"]
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
        risk = pct(t["vol"], 0)
        if t["switchDay"] is not None:
            after = p["catchUpVol"] if t["you"] else t["vol"] * p["gamblerMultiple"]
            risk += f">{pct(after, 0)}"
        lines.append(f"  {place:<7}{t['name']:<12}{kind:<9}{t['sharpe']:>7.2f}{risk:>9}"
                     f"{signed(t['ret']):>9}{pct(t['maxDD']):>10}  {status}")
    return "\n".join(lines)
