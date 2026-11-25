"""Plain-text and Markdown reports for plans and portfolios."""

from . import model

DISCLAIMER = "Simplified and illustrative, not legal advice. Costs, durations and coverages are illustrative judgements."
PNAME = {p["id"]: p["name"] for p in model.DATA["principles"]}
PSHORT = {p["id"]: p["short"] for p in model.DATA["principles"]}
STAGE = {s["id"]: s["label"] for s in model.DATA["stages"]}


def money(k):
    return "£{:,}k".format(int(round(k)))


def sc(x):
    """One decimal place, rounding halves up like the app's Math.round."""
    return "%.1f" % (model.js_round(x * 10) / 10)


def pct(x):
    v = x * 100
    if 0 < v < 1:
        return "<1%"
    return "%d%%" % model.js_round(v)


def weeks_text(w):
    return "1 week" if w == 1 else "%s weeks" % model.js_num_str(w)


def plural(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def _table(headers, rows, markdown, align=None):
    align = align or ["l"] * len(headers)
    if markdown:
        out = ["| " + " | ".join(headers) + " |",
               "|" + "|".join("---:" if a == "r" else "---" for a in align) + "|"]
        out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
        return "\n".join(out)
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]

    def fmt(r):
        return "  ".join(str(c).rjust(w) if a == "r" else str(c).ljust(w) for c, w, a in zip(r, widths, align)).rstrip()
    return "\n".join([fmt(headers), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows])


def why_text(plan, m):
    if m.get("locked"):
        return "Required"
    also = ""
    if m["alsoDrops"]:
        also = " (and " + ", ".join(model.TECHNIQUES[x]["name"].lower() for x in m["alsoDrops"]) + ")"
    if not m["meetsWithout"] and plan["meets"]:
        return "Without it%s, %s rises to %s, above appetite" % (also, PSHORT[m["worstIdWithout"]], sc(m["worstWithout"]))
    if m["meetsWithout"] and plan["meets"]:
        return "Not needed: dropping it%s saves %s and still meets appetite" % (also, money(m["saves"]))
    return "Without it%s, the worst principle goes from %s to %s" % (also, sc(plan["worst"]), sc(m["worstWithout"]))


def _plan_block(title, plan, res, markdown):
    h = "### " if markdown else ""
    lines = []
    if plan is None:
        return lines
    status = []
    status.append("meets appetite" if plan["meets"] else "above appetite")
    status.append("within budget" if plan["withinBudget"] else "%s over budget" % money(plan["cost"] - res["input"]["budget"]))
    lines.append("%s%s: %s, %s, live in %s (%s)" % (h, title, money(plan["cost"]), plural(len(plan["ids"]), "technique", "techniques"),
                                                     weeks_text(plan["weeks"]), ", ".join(status)))
    lines.append("")
    marg = {m["id"]: m for m in plan.get("marginal", [])}
    rows = []
    for tid in plan["ids"]:
        t = model.TECHNIQUES[tid]
        rows.append([t["name"] + (" (independent)" if t["independent"] and not t["name"].startswith("Independent") else ""), STAGE[t["stage"]], money(t["cost"]),
                     why_text(plan, marg[tid]) if tid in marg else ""])
    if rows:
        lines.append(_table(["Technique", "Stage", "Cost", "Why it is there"], rows, markdown, ["l", "l", "r", "l"]))
    else:
        lines.append("No techniques needed.")
    lines.append("")
    rrows = []
    for r0, r in zip(res["risk"], plan["residual"]):
        rrows.append([PSHORT[r["id"]], sc(r0["score"]), sc(r["score"]), r["band"], pct(r0["prob"]) + " to " + pct(r["prob"]),
                      "yes" if r["meets"] else "NO"])
    lines.append(_table(["Principle", "Before", "After", "Band", "Problem slips through", "Within appetite"], rrows, markdown,
                        ["l", "r", "r", "l", "l", "l"]))
    lines.append("")
    return lines


STAGE_NAME = {"pilot": "Pilot", "rollout": "Limited roll-out", "scale": "Full scale"}


def ladder_lines(L, current, weeks, markdown=False):
    """The pilot-to-scale comparison as report lines."""
    h2 = "## " if markdown else ""
    lines = [h2 + "From pilot to scale", ""]
    rows = []
    cum = 0
    for st in L["stepwise"]["steps"]:
        cum += st["cost"]
        name = STAGE_NAME[st["stage"]] + (" (now)" if st["stage"] == current else "")
        if not st["fits"]:
            rows.append([name, "-", "-", "-", "No plan goes live within %s" % weeks_text(weeks)])
            continue
        added = ", ".join(model.TECHNIQUES[i]["name"] for i in st["added"]) or "nothing new"
        rows.append([name, "+" + money(st["cost"]), money(cum), sc(st["worst"]) + ("" if st["reachable"] else " (above appetite)"),
                     added])
    lines.append(_table(["Stage", "Adds", "Total so far", "Worst after", "Techniques added"], rows, markdown,
                        ["l", "r", "r", "r", "l"]))
    lines.append("")
    steps = L["stepwise"]["steps"]
    total = L["stepwise"]["total"]
    if steps[0]["fits"] and total > 0:
        if steps[0]["cost"] == 0:
            lines.append("The pilot needs no extra assurance, but full scale needs %s." % money(total))
        else:
            ratio = total / steps[0]["cost"]
            lines.append("The pilot needs %s of assurance; full scale needs %s in all%s." % (
                money(steps[0]["cost"]), money(total), ", %s times as much" % model.js_num_str(model.js_round(ratio * 10) / 10) if ratio >= 1.5 else ""))
    if L["planned"]:
        if L["premium"] > 0:
            extra = " and ".join(model.TECHNIQUES[i]["name"].lower() for i in L["extra"])
            lines.append("Planning each stage on its own costs %s more than planning for full scale first%s." % (
                money(L["premium"]), (": it buys " + extra + ", which the cheapest full-scale plan does without") if extra else ""))
        else:
            lines.append("Planning each stage on its own costs nothing extra here.")
    lines.append("")
    return lines


def robustness_lines(rob, markdown=False):
    """How sure the key plans are, as report lines."""
    h2 = "## " if markdown else ""
    sp = rob["spread"]
    lines = [h2 + "How sure is this plan?", "",
             "%d draws, each scaling every technique's coverage by up to %d%% either way (%d%% for independent assurers)."
             % (rob["draws"], model.js_round(sp["internal"] * 100), model.js_round(sp["independent"] * 100)), ""]
    rows = []
    for label, p in (("Cheapest that meets appetite", rob["cheapest"]), ("Lowest risk within budget", rob["inBudget"]),
                     ("Cheapest that clears %d%% of draws" % model.js_round(rob["confidence"] * 100), rob["robust"])):
        if p is None:
            rows.append([label, "-", "-", "-", "none found"])
            continue
        r = p["robustness"]
        rows.append([label, money(p["cost"]), pct(r["pAll"]), "%s to %s" % (sc(r["low"]), sc(r["high"])),
                     ", ".join(model.TECHNIQUES[i]["name"] for i in p["ids"]) or "(none)"])
    lines.append(_table(["Plan", "Cost", "Draws within appetite", "Worst score, middle 80%", "Techniques"], rows, markdown,
                        ["l", "r", "r", "l", "l"]))
    lines.append("")
    if rob["cheapest"] and rob["robust"] and rob["robust"]["cost"] > rob["cheapest"]["cost"]:
        lines.append("Clearing %s of draws costs %s more than the cheapest plan." % (
            pct(rob["confidence"]), money(rob["robust"]["cost"] - rob["cheapest"]["cost"])))
        lines.append("")
    return lines


def plan_report(res, title="Assurance mix", markdown=False, ladder=None, robust=None):
    """A full report on one system's analysis."""
    inp = res["input"]
    h1, h2 = ("# ", "## ") if markdown else ("", "")
    lines = [h1 + title, "", DISCLAIMER, ""]
    lines.append(h2 + "The system")
    lines.append("")
    qrows = []
    for q in model.DATA["questions"]:
        o = next(x for x in q["options"] if x["id"] == inp["answers"][q["id"]])
        qrows.append([q["label"], o["label"]])
    lines.append(_table(["Question", "Answer"], qrows, markdown))
    lines.append("")
    lines.append("Appetite %s, budget %s, deadline %s. %s valid combinations of %s usable techniques searched."
                 % (sc(inp["appetite"]), money(inp["budget"]), weeks_text(inp["weeks"]),
                    "{:,}".format(res["plansSearched"]), len(res["usable"])))
    lines.append("")
    lines.append(h2 + "Risk before assurance")
    lines.append("")
    rows = [[PNAME[r["id"]], sc(r["L"]), sc(r["I"]), sc(r["score"]), r["band"]] for r in res["risk"]]
    lines.append(_table(["Principle", "Likelihood", "Impact", "Score", "Band"], rows, markdown, ["l", "r", "r", "r", "l"]))
    lines.append("")
    lines.append(h2 + "Plans")
    lines.append("")
    if res["cheapest"]:
        lines += _plan_block("Cheapest plan that meets your appetite", res["cheapest"], res, markdown)
    elif res["best"]:
        b = res["best"]
        lines.append("No plan meets your appetite of %s: even the lowest-risk plan leaves %s at %s." % (
            sc(inp["appetite"]), PSHORT[b["worstId"]], sc(b["worst"])))
        lines.append("")
        lines += _plan_block("Lowest-risk plan at any cost", b, res, markdown)
    if res["inBudget"]:
        lines += _plan_block("Lowest risk within %s" % money(inp["budget"]), res["inBudget"], res, markdown)
    else:
        lines.append("No plan fits within %s and the deadline." % money(inp["budget"]))
        lines.append("")
    lines.append(h2 + "What each extra pound buys")
    lines.append("")
    lines.append("Every plan that no cheaper plan beats:")
    lines.append("")
    frows = [[money(p["cost"]), sc(p["worst"]), ", ".join(model.TECHNIQUES[i]["name"] for i in p["ids"]) or "(none)"]
             for p in res["frontier"]]
    lines.append(_table(["Cost", "Worst score", "Techniques"], frows, markdown, ["r", "r", "l"]))
    lines.append("")
    if robust is not None:
        lines += robustness_lines(robust, markdown)
    if ladder is not None:
        lines += ladder_lines(ladder, inp["answers"]["stage"], inp["weeks"], markdown)
    unusable = [s for s in res["techniques"] if not s["available"]]
    if unusable:
        lines.append(h2 + "Techniques that cannot be used here")
        lines.append("")
        for s in unusable:
            lines.append("- %s: %s." % (model.TECHNIQUES[s["id"]]["name"], s["reason"]))
        lines.append("")
    if res["notes"]:
        lines.append(h2 + "Notes on the input")
        lines.append("")
        for n in res["notes"]:
            lines.append("- " + n)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def portfolio_report(alloc, markdown=False):
    h1, h2 = ("# ", "## ") if markdown else ("", "")
    lines = [h1 + "Assurance mix: sharing one budget across an AI inventory", "", DISCLAIMER, ""]
    opt = alloc["optimal"]
    lines.append("Budget %s across %s, appetite %s." % (money(alloc["budget"]), plural(len(alloc["systems"]), "system", "systems"),
                                                       sc(alloc["appetite"])))
    lines.append("")
    lines.append(h2 + "How the approaches compare")
    lines.append("")
    rows = []
    for s in [opt] + [alloc["baselines"][k] for k in ("riskiest_first", "proportional", "equal")]:
        if s is None:
            continue
        rows.append([s["label"], "%d of %d" % (s["within"], len(s["choices"])), sc(s["totalWorst"] / len(s["choices"])),
                     money(s["cost"])])
    if rows:
        lines.append(_table(["Approach", "Systems within appetite", "Average worst score", "Spent"], rows, markdown,
                            ["l", "r", "r", "r"]))
    else:
        lines.append("No allocation is possible.")
    lines.append("")
    if opt:
        lines.append(h2 + "Optimised allocation")
        lines.append("")
        rows = []
        for c in opt["choices"]:
            rows.append([c["name"], sc(c["inherent"]), money(c["cost"]), sc(c["worst"]), "yes" if c["meets"] else "NO",
                         ", ".join(model.TECHNIQUES[i]["name"] for i in c["ids"]) or "(none)"])
        lines.append(_table(["System", "Before", "Spend", "After", "Within appetite", "Techniques"], rows, markdown,
                            ["l", "r", "r", "r", "l", "l"]))
        lines.append("")
    if alloc["notes"]:
        lines.append(h2 + "Notes")
        lines.append("")
        for n in alloc["notes"]:
            lines.append("- " + n)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def portfolio_csv_rows(alloc):
    header = ["system", "approach", "spend_k", "worst_before", "worst_after", "within_appetite", "techniques"]
    rows = []
    for s in [alloc["optimal"]] + [alloc["baselines"][k] for k in ("riskiest_first", "proportional", "equal")]:
        if s is None:
            continue
        for c in s["choices"]:
            rows.append([c["name"], s["label"], int(c["cost"]), sc(c["inherent"]), sc(c["worst"]),
                         "yes" if c["meets"] else "no", ";".join(c["ids"])])
    return header, rows
