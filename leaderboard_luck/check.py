"""Checking a real leaderboard: how much of a final table could luck alone explain?

A line-for-line port of the leaderboard check in the MODEL block of ``app/index.html``, so the
same table and settings give the same answer in both (``tests/test_agreement.py`` checks).

Each team's result becomes a luck-adjusted score z: its Sharpe ratio times sqrt(days / 252), or
its return divided by its volatility over the challenge. With no skill anywhere, z is the market
move everyone shares plus a standard normal of the team's own scaled by sqrt(1 - correlation), so
the spread of z around the field's average tells luck and skill apart.
"""

from __future__ import annotations

import math
import re

from .model import DAYS_PER_YEAR, Rng, clamp, correlation, norm_cdf, round_half_up, sample_competition

CHECK_DEFAULTS = {"days": 20, "correlation": 0.3, "assumedVol": 0.2, "sims": 10000, "seed": 1}
CHECK_RANGES = {
    "days": (5, 250, True),
    "correlation": (0, 0.9, False),
    "assumedVol": (0.02, 1, False),
    "sims": (1000, 100000, True),
    "seed": (0, 4294967295, True),
}
CHECK_MAX_TEAMS = 500
Z90 = 1.6448536269514722
LOG_FLOOR = 0.001


def normalise_check(options: dict | None = None) -> dict:
    src = options or {}
    out = {}
    for key, default in CHECK_DEFAULTS.items():
        v = src.get(key)
        if v is None:
            v = default
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{key} must be a finite number")
        lo, hi, whole = CHECK_RANGES[key]
        v = clamp(v, lo, hi)
        out[key] = round_half_up(v) if whole else v
    return out


def split_row(line: str, delim: str) -> list[str]:
    """Splits one line of a table, allowing "quoted, fields"."""
    cells = []
    cell = ""
    quoted = False
    i = 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == '"' and line[i + 1:i + 2] == '"':
                cell += '"'
                i += 1
            elif ch == '"':
                quoted = False
            else:
                cell += ch
        elif ch == '"':
            quoted = True
        elif ch == delim:
            cells.append(cell.strip())
            cell = ""
        else:
            cell += ch
        i += 1
    cells.append(cell.strip())
    return cells


NUMBER = re.compile(r"[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)(e[+-]?[0-9]+)?", re.IGNORECASE)


def read_number(text: str) -> dict | None:
    """"+8.4%", "-3", "(2.1)", "12,5" and a typographic minus all read as numbers."""
    s = re.sub(r"\s+", "", str(text).replace("−", "-"))
    negative = False
    if re.fullmatch(r"\(.*\)", s):
        negative = True
        s = s[1:-1]
    percent = "%" in s
    s = s.replace("%", "")
    if "," in s:
        s = s.replace(",", "") if "." in s else s.replace(",", ".")
    if not NUMBER.fullmatch(s):
        return None
    v = float(s)
    return {"value": -v if negative else v, "percent": percent}


def column_role(label: str) -> str | None:
    h = label.lower()
    if re.search(r"true|skill", h):
        return "truth"
    if re.search(r"sharpe", h):
        return "sharpe"
    if re.search(r"vol|risk|std|deviation", h):
        return "vol"
    if re.search(r"return|p&l|pnl|profit|perf|gain|result", h):
        return "ret"
    if re.search(r"team|name|player|entrant|fund|portfolio", h):
        return "name"
    return None


PLACE_LABEL = re.compile(r"(place|rank|position|pos|#|no\.?)", re.IGNORECASE)


def parse_table(text: str) -> dict:
    """Reads a final table: one row per team, with a header row naming the columns (team, return,
    volatility, Sharpe ratio); without one, the columns are team, return and, if present,
    volatility. Returns and volatilities are read as percentages unless every value in the column
    lies between -1 and 1 with no % sign, when they are read as fractions."""
    text = re.sub(r"^﻿", "", str(text or ""))
    lines = [line.strip() for line in re.sub(r"\r\n?", "\n", text).split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("The table is empty.")
    first = lines[0]
    delim = "\t" if "\t" in first else (";" if ";" in first else ",")
    rows = [split_row(line, delim) for line in lines]
    roles = [column_role(c) for c in rows[0]]
    header = any(r is not None for r in roles) and all(
        c == "" or read_number(c) is None or column_role(c) is not None for c in rows[0])
    col = {"name": -1, "ret": -1, "vol": -1, "sharpe": -1, "truth": -1}
    if header:
        for i, role in enumerate(roles):
            if role and col[role] < 0:
                col[role] = i
        if col["name"] < 0:
            for c, role in enumerate(roles):
                if role is None and not PLACE_LABEL.fullmatch(rows[0][c]):
                    col["name"] = c
                    break
        if col["ret"] < 0 and col["sharpe"] < 0:
            raise ValueError("No return or Sharpe ratio column found. Name the columns in a header row, "
                             "for example: Team, Return, Volatility.")
    else:
        col["name"] = 0
        col["ret"] = 1
        if len(rows[0]) > 2:
            col["vol"] = 2
        if len(rows[0]) < 2:
            raise ValueError("Each row needs at least a team name and a return.")
    labels = {key: (rows[0][c] if c >= 0 and header else None) for key, c in col.items()}
    body = rows[1:] if header else rows
    key = "ret" if col["ret"] >= 0 else "sharpe"

    def cell(r, c):
        return read_number(r[c]) if 0 <= c < len(r) else None

    kept = []
    skipped = 0
    for i, r in enumerate(body):
        parsed = {k: cell(r, col[k]) for k in ("ret", "vol", "sharpe", "truth")}
        if parsed[key] is None:
            skipped += 1
            continue
        name = r[col["name"]] if 0 <= col["name"] < len(r) else ""
        kept.append({"name": name or f"Row {i + 1}", "raw": parsed})
    units = {}
    for k in ("ret", "vol"):
        values = [t["raw"][k] for t in kept if t["raw"][k] is not None]
        percent = "%" in (labels[k] or "") or any(x["percent"] or abs(x["value"]) > 1 for x in values)
        units[k] = ("percent" if percent else "fraction") if values else None

    def read(t, k, scaled):
        x = t["raw"][k]
        if x is None:
            return None
        return x["value"] / 100 if scaled and units[k] == "percent" else x["value"]

    teams = []
    for t in kept:
        vol = read(t, "vol", True)
        teams.append({"name": t["name"], "ret": read(t, "ret", True), "vol": vol if vol is not None and vol > 0 else None,
                      "sharpe": read(t, "sharpe", False), "truth": read(t, "truth", False)})
    return {"teams": teams, "columns": labels, "header": header, "units": units, "skipped": skipped, "rankedOn": key}


# Natural log of the gamma function (Lanczos), for the chi-square distribution.
LANCZOS = (76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155,
           0.1208650973866179e-2, -0.5395239384953e-5)


def log_gamma(x: float) -> float:
    y = x
    tmp = x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for c in LANCZOS:
        y += 1
        ser += c / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def gamma_q(a: float, x: float) -> float:
    """Upper regularised incomplete gamma function Q(a, x)."""
    if x <= 0:
        return 1.0
    front = math.exp(-x + a * math.log(x) - log_gamma(a))
    if x < a + 1:
        ap = a
        term = 1 / a
        total = term
        for _ in range(10000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return 1 - total * front
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return front * h


def chi_square_tail(x: float, df: int) -> float:
    """P(chi-square with df degrees of freedom > x)."""
    return gamma_q(df / 2, x / 2)


def chi_square_quantile(p: float, df: int) -> float:
    lo = 0.0
    hi = df + 10 * math.sqrt(2 * df) + 10
    while 1 - chi_square_tail(hi, df) < p:
        hi *= 2
    for _ in range(200):
        mid = (lo + hi) / 2
        if 1 - chi_square_tail(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def check_leaderboard(table: dict, options: dict | None = None) -> dict:
    o = normalise_check(options)
    teams = table["teams"]
    n = len(teams)
    if n < 3:
        raise ValueError(f"At least three teams are needed; this table has {n}.")
    if n > CHECK_MAX_TEAMS:
        raise ValueError(f"At most {CHECK_MAX_TEAMS} teams can be checked; this table has {n}.")
    k = math.sqrt(o["days"] / DAYS_PER_YEAR)
    luck = 1 - o["correlation"]
    basis = {"sharpe": 0, "vol": 0, "assumed": 0}
    rows = []
    for i, t in enumerate(teams):
        how = "sharpe" if t["sharpe"] is not None else ("vol" if t["vol"] is not None else "assumed")
        basis[how] += 1
        if how == "sharpe":
            # A Sharpe ratio from daily returns is a t statistic: rescaled to unit variance.
            z = t["sharpe"] * k * math.sqrt(max(1, o["days"] - 3) / max(3, o["days"] - 1))
        else:
            # Log returns, so a lucky gamble compounding upwards is not mistaken for skill. With no
            # skill, a log return has mean -(sd squared)/2 over the challenge.
            sd = (t["vol"] if how == "vol" else o["assumedVol"]) * k
            z = (math.log(max(LOG_FLOOR, 1 + t["ret"])) + sd * sd / 2) / sd
        rows.append({"index": i, "name": t["name"], "ret": t["ret"], "vol": t["vol"], "sharpe": t["sharpe"],
                     "truth": t["truth"], "basis": how, "z": z})
    # Places follow the table's ranking column, highest first; ties keep the table's order.
    rank_key = "sharpe" if table["rankedOn"] == "sharpe" else "ret"
    order = sorted(range(n), key=lambda i: (-rows[i][rank_key], i))
    rows = [rows[i] for i in order]
    for pos, r in enumerate(rows):
        r["place"] = pos + 1

    mean = 0.0
    for r in rows:
        mean += r["z"]
    mean /= n
    ss = 0.0
    for r in rows:
        ss += (r["z"] - mean) * (r["z"] - mean)
    spread = ss / (n - 1)
    df = n - 1
    p_spread = chi_square_tail(ss / luck, df)
    skill_var = max(0.0, (spread - luck) / (k * k))

    def range_var(q):
        return max(0.0, (ss / q - luck) / (k * k))

    shrink = k * skill_var / (k * k * skill_var + luck)
    edge_sd = math.sqrt(skill_var * luck / (k * k * skill_var + luck))
    best = 0
    for i, r in enumerate(rows):
        r["lead"] = (r["z"] - mean) / math.sqrt(luck)
        r["pLuck"] = 1 - norm_cdf(r["lead"] / math.sqrt(1 - 1 / n))
        r["edge"] = shrink * (r["z"] - mean)
        r["edgeLow"] = r["edge"] - Z90 * edge_sd
        r["edgeHigh"] = r["edge"] + Z90 * edge_sd
        if r["lead"] > rows[best]["lead"]:
            best = i

    # How often a field of n teams with no skill at all produces a best luck-adjusted lead at
    # least as large as this table's.
    rng = Rng(o["seed"])
    beaten = 0
    target = rows[best]["lead"]
    for _ in range(o["sims"]):
        total = 0.0
        top = -math.inf
        for _ in range(n):
            d = rng.normal()
            total += d
            if d > top:
                top = d
        if top - total / n >= target:
            beaten += 1

    truth_correlation = None
    if all(r["truth"] is not None for r in rows):
        truth_correlation = correlation([r["z"] for r in rows], [r["truth"] for r in rows])
        truth_mean = 0.0
        for r in rows:
            truth_mean += r["truth"]
        truth_mean /= n
        for r in rows:
            r["truthEdge"] = r["truth"] - truth_mean

    return {
        "options": o,
        "teams": n,
        "rankedOn": rank_key,
        "basis": basis,
        "spread": spread,
        "luckSpread": luck,
        "luckShare": min(1.0, luck / spread) if spread > 0 else 1.0,
        "pSpread": p_spread,
        "verdict": "skill" if p_spread < 0.01 else ("some" if p_spread < 0.1 else "luck"),
        "skillSpread": math.sqrt(skill_var),
        "skillSpreadLow": math.sqrt(range_var(chi_square_quantile(0.95, df))),
        "skillSpreadHigh": math.sqrt(range_var(chi_square_quantile(0.05, df))),
        "shrink": shrink,
        "edgeSd": edge_sd,
        "best": best,
        "pBest": beaten / o["sims"],
        "truthCorrelation": truth_correlation,
        "rows": rows,
    }


# Two worked examples, made by this simulator so that every team's true skill is known. Team
# names are invented.
EXAMPLE_NAMES = ("Alder", "Aspen", "Beech", "Birch", "Cedar", "Damson", "Elm", "Fir", "Gorse", "Hazel", "Holly",
                 "Ivy", "Juniper", "Larch", "Laurel", "Maple", "Myrtle", "Nettle", "Oak", "Pine", "Poplar", "Quince",
                 "Rowan", "Sorrel", "Spruce", "Thistle", "Walnut", "Willow", "Yarrow", "Yew")
EXAMPLES = {"month": {"days": 20, "params": {}}, "year": {"days": 250, "params": {"days": 250}}}


def example_table(kind: str) -> dict:
    from .report import fixed

    if kind not in EXAMPLES:
        raise ValueError(f"Unknown example: {kind}")
    ex = EXAMPLES[kind]
    lines = ["Team,Return,Volatility,True skill (known only because this is simulated)"]
    for t in sample_competition(ex["params"], 0):
        number = 1 if t["you"] else int(t["name"][5:])
        lines.append(f"Team {EXAMPLE_NAMES[number - 1]},{fixed(t['ret'] * 100, 2)}%,{fixed(t['vol'] * 100, 1)}%,"
                     f"{fixed(t['sharpe'], 2)}")
    return {"text": "\n".join(lines) + "\n", "days": ex["days"]}


# ---------- does the check work? ----------

# Simulated challenges whose true skill is known, checked as if they were real tables.
CALIBRATION_SETTINGS = (
    ("No skill anywhere, four weeks", {"skillSpread": 0, "yourSharpe": 0}),
    ("No skill anywhere, a year", {"skillSpread": 0, "yourSharpe": 0, "days": 250}),
    ("Default field, four weeks", {}),
    ("Default field, twelve weeks", {"days": 60}),
    ("Default field, a year", {"days": 250}),
)


def calibration_job(params: dict, k: int, sims: int) -> tuple:
    teams = sample_competition(params, k)
    days = params.get("days", 20)
    table = {"teams": [{"name": t["name"], "ret": t["ret"], "vol": t["vol"], "sharpe": None, "truth": t["sharpe"]}
                       for t in teams], "rankedOn": "ret"}
    r = check_leaderboard(table, {"days": days, "sims": sims, "seed": k + 1})
    spread = params.get("skillSpread", 0.75)
    return (r["pSpread"], r["pBest"], r["skillSpread"], r["skillSpreadLow"] <= spread <= r["skillSpreadHigh"],
            r["truthCorrelation"])


def calibrate(challenges: int = 300, sims: int = 1000, workers: int = 1) -> list[dict]:
    """For each setting, how often the check flags skill, and how well it recovers the true spread."""
    out = []
    for label, params in CALIBRATION_SETTINGS:
        jobs = [(params, k, sims) for k in range(challenges)]
        if workers > 1:
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(max_workers=workers) as ex:
                res = list(ex.map(calibration_job, *zip(*jobs), chunksize=8))
        else:
            res = [calibration_job(*job) for job in jobs]
        n = len(res)
        out.append({
            "label": label,
            "days": params.get("days", 20),
            "skillSpread": params.get("skillSpread", 0.75),
            "flagged5": sum(1 for r in res if r[0] < 0.05) / n,
            "flagged10": sum(1 for r in res if r[0] < 0.1) / n,
            "bestFlagged5": sum(1 for r in res if r[1] < 0.05) / n,
            "meanSkillSpread": sum(r[2] for r in res) / n,
            "rangeCovers": sum(1 for r in res if r[3]) / n,
            "truthCorrelation": sum(r[4] for r in res) / n,
        })
    return out
