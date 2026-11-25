"""Share one assurance budget across a whole inventory of AI systems.

Each system's efficient frontier (from the model) lists the plans that no
cheaper plan beats. Choosing one plan per system so the total stays within a
shared budget is a multiple-choice knapsack, solved exactly here by dynamic
programming over whole thousands of pounds. The goal is, first, as few systems
as possible above the risk appetite and, second, the lowest total of each
system's worst-principle risk.
"""

import csv
import io

from . import model

COLUMNS = [q["id"] for q in model.DATA["questions"]]


def read_inventory(path_or_text, is_text=False):
    """Read an inventory CSV: one system per row. Returns (systems, notes)."""
    if is_text:
        text = path_or_text
    else:
        with open(path_or_text, encoding="utf-8-sig", newline="") as f:
            text = f.read()
    reader = csv.DictReader(io.StringIO(text))
    notes = []
    systems = []
    if not reader.fieldnames:
        return systems, ["The inventory is empty."]
    fields = {f.strip().lower(): f for f in reader.fieldnames if f is not None}
    known = set(COLUMNS) | {"name", "weeks", "must", "exclude"}
    unknown = [f for f in fields if f not in known]
    if unknown:
        notes.append("Ignored unknown column(s): %s." % ", ".join(sorted(unknown)))
    for n, row in enumerate(reader, start=2):
        def get(col):
            f = fields.get(col)
            v = row.get(f) if f else None
            return v.strip() if isinstance(v, str) else ""
        name = get("name") or "System on line %d" % n
        if not any(get(c) for c in COLUMNS) and not get("name"):
            continue
        raw = {"answers": {c: get(c) for c in COLUMNS if get(c)}, "must": get("must"), "exclude": get("exclude")}
        if get("weeks"):
            raw["weeks"] = get("weeks")
        systems.append({"name": name, "raw": raw, "line": n})
    if not systems:
        notes.append("No systems found in the inventory.")
    return systems, notes


def allocate(systems, budget, appetite, weeks=None, legal_must=True):
    """Allocate a shared budget (in £ thousands) across systems.

    Returns a dict with the optimal allocation and three simple baselines.
    """
    budget = int(round(budget))
    rows = []
    notes = []
    for s in systems:
        raw = dict(s["raw"])
        raw["appetite"] = appetite
        raw["legalMust"] = legal_must
        if weeks is not None and "weeks" not in raw:
            raw["weeks"] = weeks
        res = model.analyse(raw)
        for note in res["notes"]:
            notes.append("%s: %s" % (s["name"], note))
        rows.append({"name": s["name"], "analysis": res, "frontier": res["frontier"]})
    usable = [r for r in rows if r["frontier"]]
    for r in rows:
        if not r["frontier"]:
            notes.append("%s: no plan goes live in time, so it was left out of the allocation." % r["name"])

    optimal = _knapsack(usable, budget, appetite)
    if optimal is None:
        need = sum(r["frontier"][0]["cost"] for r in usable)
        notes.append("The budget of £%dk does not cover the techniques that must be included (£%dk)." % (budget, need))
    baselines = {
        "equal": _equal_split(usable, budget, appetite),
        "riskiest_first": _riskiest_first(usable, budget, appetite),
        "proportional": _proportional(usable, budget, appetite),
    }
    return {"budget": budget, "appetite": appetite, "systems": rows, "optimal": optimal,
            "baselines": baselines, "notes": notes}


def _score(choices, appetite):
    above = sum(1 for c in choices if c["worst"] > appetite + model.EPS)
    total = sum(c["worst"] for c in choices)
    cost = sum(c["cost"] for c in choices)
    return above, total, cost


def _summary(rows, picks, appetite, label):
    choices = []
    for r, p in zip(rows, picks):
        if p is None:
            return None
        choices.append({"name": r["name"], "cost": p["cost"], "worst": p["worst"], "ids": p["ids"],
                        "inherent": r["analysis"]["inherentWorst"],
                        "meets": p["worst"] <= appetite + model.EPS})
    above, total, cost = _score(choices, appetite)
    return {"label": label, "choices": choices, "within": len(choices) - above, "above": above,
            "totalWorst": total, "cost": cost}


def _knapsack(rows, budget, appetite):
    """Exact multiple-choice knapsack over whole £k."""
    INF = (float("inf"), float("inf"), float("inf"))
    best = [(0, 0.0, 0)] * (budget + 1)
    back = []
    for r in rows:
        new = [INF] * (budget + 1)
        pick = [None] * (budget + 1)
        pts = r["frontier"]
        for b in range(budget + 1):
            for j, p in enumerate(pts):
                c = int(p["cost"])
                if c > b or best[b - c][0] == INF[0]:
                    continue
                prev = best[b - c]
                cand = (prev[0] + (1 if p["worst"] > appetite + model.EPS else 0), prev[1] + p["worst"], prev[2] + c)
                if cand < new[b]:
                    new[b] = cand
                    pick[b] = j
        best = new
        back.append(pick)
    if best[budget][0] == INF[0]:
        return None
    # Walk back through the choices.
    picks = []
    b = budget
    for r, pick in zip(reversed(rows), reversed(back)):
        j = pick[b]
        p = r["frontier"][j]
        picks.append(p)
        b -= int(p["cost"])
    picks.reverse()
    return _summary(rows, picks, appetite, "Optimised")


def _best_within(frontier, money):
    """Lowest-risk frontier plan costing no more than money (frontier is sorted by cost)."""
    best = None
    for p in frontier:
        if p["cost"] <= money + model.EPS:
            best = p
    return best


def _equal_split(rows, budget, appetite):
    if not rows:
        return None
    share = budget / len(rows)
    return _summary(rows, [_best_within(r["frontier"], share) for r in rows], appetite, "Equal shares")


def _proportional(rows, budget, appetite):
    if not rows:
        return None
    weights = [r["analysis"]["inherentWorst"] for r in rows]
    total = sum(weights)
    return _summary(rows, [_best_within(r["frontier"], budget * w / total) for r, w in zip(rows, weights)],
                    appetite, "Shares by inherent risk")


def _riskiest_first(rows, budget, appetite):
    """Fund the riskiest system's cheapest appetite-meeting plan first, then the next, and so on;
    systems that cannot be brought within appetite, or no longer fit, get the cheapest possible plan."""
    if not rows:
        return None
    floor = [r["frontier"][0] for r in rows]
    left = budget - sum(p["cost"] for p in floor)
    if left < 0:
        return None
    picks = list(floor)
    order = sorted(range(len(rows)), key=lambda i: -rows[i]["analysis"]["inherentWorst"])
    for i in order:
        target = next((p for p in rows[i]["frontier"] if p["worst"] <= appetite + model.EPS), None)
        if target is None:
            continue
        extra = target["cost"] - picks[i]["cost"]
        if extra <= left:
            picks[i] = target
            left -= extra
    return _summary(rows, picks, appetite, "Riskiest first")
