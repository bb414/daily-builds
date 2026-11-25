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


# ---------- checking a real leaderboard ----------

def chance(p: float) -> str:
    """A small probability in words-friendly form: "fewer than 0.1%" rather than "0.0%"."""
    return "fewer than 0.1%" if p < 0.0005 else pct(p)


def verdict_text(r: dict) -> str:
    """The headline sentence, as in the browser app."""
    tail = f"a field with no skill at all spreads out this much in {chance(r['pSpread'])} of challenges."
    if r["verdict"] == "skill":
        return "Real skill shows: " + tail
    if r["verdict"] == "some":
        return "Possibly some skill: " + tail
    return "Luck alone could easily have produced this table: " + tail


def edge_text(row: dict, r: dict, minus: str = "-") -> str:
    def s(v):
        text = fixed(v, 2)
        if float(text) == 0:
            return fixed(0, 2)
        return ("+" if v > 0 else minus) + text.lstrip("-")
    if r["edgeSd"] == 0:
        return s(row["edge"])
    return f"{s(row['edge'])} ({s(row['edgeLow'])} to {s(row['edgeHigh'])})"


UNIT_WORDS = {"percent": "percentages", "fraction": "fractions"}


def check_report(table: dict, r: dict, source: str) -> str:
    o = r["options"]
    basis = r["basis"]
    used = [f"{label} for {basis[key]} team{'' if basis[key] == 1 else 's'}" for key, label in
            (("sharpe", "Sharpe ratio"), ("vol", "volatility"), ("assumed", f"an assumed {pct(o['assumedVol'], 0)} volatility"))
            if basis[key]]
    read = {key: table["units"].get(key) for key in ("ret", "vol")}
    if read["ret"] and read["ret"] == read["vol"]:
        units = [f"returns and volatility as {UNIT_WORDS[read['ret']]}"]
    else:
        units = [f"{name} as {UNIT_WORDS[read[key]]}" for key, name in (("ret", "returns"), ("vol", "volatility"))
                 if read[key]]
    lines = [f"Leaderboard check: {source}", "",
             f"  {r['teams']} teams, {o['days']} trading days, market correlation {o['correlation']:.2f}",
             f"  Ranked on {'Sharpe ratio' if r['rankedOn'] == 'sharpe' else 'return'}"
             + (f"; read {' and '.join(units)}" if units else ""),
             "  Luck-adjusted scores from " + ", ".join(used)]
    if table["skipped"]:
        lines.append(f"  Skipped {table['skipped']} row{'' if table['skipped'] == 1 else 's'} without a number to rank on")
    best = r["rows"][r["best"]]
    lines += ["", "  " + verdict_text(r),
              f"  Share of the spread down to luck   {pct(r['luckShare'], 0)}",
              f"  Estimated skill spread             {fixed(r['skillSpread'], 2)} (90% range {fixed(r['skillSpreadLow'], 2)}"
              f" to {fixed(r['skillSpreadHigh'], 2)})",
              f"  Best luck-adjusted lead            {best['name']} ({ordinal(best['place'])}), {fixed(best['lead'], 2)}: "
              f"a field with no skill does this well in {chance(r['pBest'])} of challenges"]
    if r["truthCorrelation"] is not None:
        lines.append(f"  Scores against true skill          correlation {fixed(r['truthCorrelation'], 2)}")
    if r["edgeSd"] == 0:
        lines.append("  No sign that teams differ in skill, so every team's best estimate is the field's average.")
    has = {key: any(row[key] is not None for row in r["rows"]) for key in ("ret", "vol", "sharpe", "truth")}
    name_width = max(12, min(28, max(len(row["name"]) for row in r["rows"]) + 2))
    head = f"  {'Place':<7}{'Team':<{name_width}}"
    head += f"{'Return':>9}" if has["ret"] else ""
    head += f"{'Volatility':>12}" if has["vol"] else ""
    head += f"{'Sharpe':>8}" if has["sharpe"] else ""
    head += f"{'Lead':>7}{'Luck alone':>12}   Estimated edge (90% range)"
    head += "   True skill" if has["truth"] else ""
    lines += ["", head]
    for row in r["rows"]:
        line = f"  {ordinal(row['place']):<7}{row['name'][:name_width - 2]:<{name_width}}"
        if has["ret"]:
            line += f"{signed(row['ret']) if row['ret'] is not None else '':>9}"
        if has["vol"]:
            line += f"{pct(row['vol']) if row['vol'] is not None else '':>12}"
        if has["sharpe"]:
            line += f"{fixed(row['sharpe'], 2) if row['sharpe'] is not None else '':>8}"
        line += f"{fixed(row['lead'], 2):>7}{chance(row['pLuck']):>12}   {edge_text(row, r):<27}"
        if has["truth"]:
            line += f"{fixed(row['truth'], 2):>11}"
        lines.append(line.rstrip())
    lines += ["",
              "  Lead: how far ahead of the field's average a team finished, in units of the spread luck alone",
              "  produces. Luck alone: how often a single team with no skill does at least this well (in a whole",
              "  field, someone usually does). Estimated edge: the team's likely true Sharpe ratio relative to the",
              "  field's average, allowing for luck."]
    return "\n".join(lines)


def calibration_report(rows: list[dict], challenges: int) -> str:
    lines = ["Does the leaderboard check work?", "",
             f"  {challenges:,} simulated challenges per setting, each checked as if it were a real table.",
             "  Flagged: the check finds more spread than luck alone would give (5% and 10% levels).", "",
             f"  {'Setting':<32}{'Flagged 5%':>11}{'10%':>7}{'Winner 5%':>11}{'Spread est.':>13}{'Range covers':>14}"
             f"{'vs truth':>10}"]
    for c in rows:
        truth = fixed(c["truthCorrelation"], 2) if c["skillSpread"] > 0 else "-"
        lines.append(f"  {c['label']:<32}{pct(c['flagged5'], 0):>11}{pct(c['flagged10'], 0):>7}"
                     f"{pct(c['bestFlagged5'], 0):>11}{fixed(c['meanSkillSpread'], 2):>13}"
                     f"{pct(c['rangeCovers'], 0):>14}{truth:>10}")
    lines += ["",
              "  With no skill anywhere, a fair check flags about 5% and 10% of tables by chance alone.",
              "  Spread est.: the average estimated skill spread (the true spread is 0 or 0.75).",
              "  Range covers: how often the 90% range contains the true spread. vs truth: average correlation",
              "  between the luck-adjusted scores and the teams' true skill."]
    return "\n".join(lines)
