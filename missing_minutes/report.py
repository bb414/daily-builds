"""Plain-text reports for the command line."""

from .model import DAY, fmt_duration


def _pct(x, d=0):
    return ("%." + str(d) + "f%%") % (x * 100)


def _signed(minutes):
    if abs(minutes) < 0.5:
        return "0 min"
    return ("+" if minutes > 0 else "") + fmt_duration(minutes)


def _dur(minutes):
    return "0 min" if abs(minutes) < 0.5 else fmt_duration(minutes)


def comparison_text(r, bank=None):
    """Describe one comparison (the output of model.compare) as plain text."""
    cfg = r["config"]
    k = cfg["ai"]["step"]
    step = cfg["steps"][k]
    b, a = r["base"], r["ai"]
    lines = []
    lines.append("Missing minutes: " + cfg["name"])
    lines.append("=" * len(lines[0]))
    lines.append("")
    lines.append("AI on step %d, %s: saves %s of %s a case, used on %s of cases," % (
        k + 1, step["name"], _pct(cfg["ai"]["saving"]), _dur(step["minutes"]), _pct(cfg["ai"]["adoption"])))
    lines.append("%s minutes to check, wrong on %s of cases, %s of errors caught later." % (
        _fmt(cfg["ai"]["checkMinutes"]), _pct(cfg["ai"]["errorRate"]), _pct(cfg["ai"]["catchRate"])))
    lines.append("%s cases a day, %d measured working days, seed %d." % (_fmt(cfg["arrivalsPerDay"]), cfg["measureDays"], b["seed"]))
    lines.append("")
    if not r["complete"]:
        lines.append("WARNING: some cases never finished. At least one step has more work than people,")
        lines.append("so its queue keeps growing and the averages below only cover finished cases.")
        lines.append("")
    lines.append("The pilot's promise:      %s saved on each case at %s" % (_dur(r["pilotClaim"]), step["name"]))
    lines.append("End-to-end time:          %s without the AI, %s with it (%s)" % (
        _dur(b["leadMean"]), _dur(a["leadMean"]), _signed(r["total"])))
    lines.append("Minutes reaching customer: %.2f for every minute saved at the desk" % r["leverage"])
    lines.append("")
    lines.append("Where the minutes went (average per case)")
    lines.append("-" * 41)
    for p in r["parts"]:
        if p["key"].startswith("wait") and abs(p["value"]) < 0.5:
            continue
        lines.append("  %-44s %10s" % (p["label"], _signed(p["value"])))
    lines.append("  %-44s %10s" % ("Change in end-to-end time", _signed(r["total"])))
    lines.append("")
    lines.append("Step by step (without AI -> with AI)")
    lines.append("-" * 36)
    lines.append("  %-26s %-16s %-24s %s" % ("Step", "Busy", "Waiting a case", "Hands-on a case"))
    for i, (s, t) in enumerate(zip(b["steps"], a["steps"])):
        if s["kind"] == "team":
            busy = "%s -> %s" % (_pct(s["utilisation"]), _pct(t["utilisation"]))
        elif s["kind"] == "batch":
            busy = "%s -> %s full" % (_pct(s["utilisation"]), _pct(t["utilisation"]))
        else:
            busy = "outside"
        mark = " *" if i == k else ""
        lines.append("  %-26s %-16s %-24s %s" % (
            (str(i + 1) + ". " + s["name"])[:24] + mark, busy,
            "%s -> %s" % (_dur(s["wait"]), _dur(t["wait"])),
            "%s -> %s" % (_dur(s["touch"]), _dur(t["touch"]))))
    lines.append("  (* = the step the AI helps with)")
    lines.append("")
    lines.append("Cases (working days)       Without AI   With AI")
    for label, key in (("Average", "leadMean"), ("Median", "leadP50"), ("85th percentile", "leadP85"), ("95th percentile", "leadP95")):
        lines.append("  %-24s %10.2f %9.2f" % (label, b[key] / DAY, a[key] / DAY))
    lines.append("  %-24s %10s %9s" % ("Within %s days" % _fmt(cfg["slaDays"]), _pct(b["withinSla"], 1), _pct(a["withinSla"], 1)))
    lines.append("")
    lines.append("Staff time freed:          %.2f full-time people" % r["fteFreed"])
    lines.append("Cases sent back per 100:   %.1f -> %.1f (%.1f from AI errors)" % (
        b["aiSendBacksPer100"] + b["baseSendBacksPer100"], a["aiSendBacksPer100"] + a["baseSendBacksPer100"], a["aiSendBacksPer100"]))
    lines.append("AI errors reaching customers per 100 cases: %.1f" % a["escapedPer100"])
    if not r["stable"]:
        over = sorted(set(b["overloaded"]) | set(a["overloaded"]))
        lines.append("")
        lines.append("WARNING: %s cannot keep up, so its queue keeps growing; averages depend on the run length."
                     % (", ".join(cfg["steps"][j]["name"] for j in over) or "a step"))
    if bank is not None:
        lines.append("")
        lines.append(bank_text(r, bank))
    return "\n".join(lines)


def bank_text(r, bank):
    """Describe what happens if the saving is banked as fewer people."""
    cfg = r["config"]
    lines = ["Bank the saving as a headcount cut?", "-" * 35]
    if bank["step"] < 0 or cfg["steps"][bank["step"]]["kind"] != "team":
        lines.append(bank["reason"])
        return "\n".join(lines)
    st = cfg["steps"][bank["step"]]
    lines.append("The pilot's business case frees %.1f people at %s; in practice the AI frees %.1f." % (
        bank["claimedPeople"], st["name"], bank["freedPeople"]))
    if not bank["possible"]:
        lines.append(bank["reason"])
        return "\n".join(lines)
    lines.append("Cut %d of %d people: cases take %s on average (%s against no AI, %s against keeping everyone)." % (
        bank["cut"], st["staff"], _dur(bank["leadMean"]), _signed(bank["vsBase"]), _signed(bank["vsAi"])))
    lines.append("%s would be %s busy and %s of cases close within %s days%s" % (
        st["name"], _pct(bank["utilisation"]), _pct(bank["withinSla"], 1), _fmt(cfg["slaDays"]),
        "." if bank["stable"] else "; its queue keeps growing."))
    return "\n".join(lines)


def options_text(r, rows):
    """The options appraisal as a table."""
    cfg = r["config"]
    lines = ["Where else could the time come from? (%s, seed %d)" % (cfg["name"], r["base"]["seed"]), ""]
    lines.append("  %-44s %12s %12s %10s" % ("Option", "At the desk", "End to end", "Errors/100"))
    for o in rows:
        label = o["label"] + (" (current)" if o["current"] else "")
        lines.append("  %-44s %12s %12s %10s%s" % (
            label[:44], _dur(o["atDesk"]) if o["kind"] == "ai" else "+1 person", _signed(o["total"]),
            "%.1f" % o["escapedPer100"] if o["kind"] == "ai" else "-", "" if o["stable"] else "  queue grows"))
    lines.append("")
    lines.append("End to end is the change in average time from arrival to close against the process without the AI.")
    return "\n".join(lines)


def _fmt(x):
    return str(int(x)) if float(x) == int(x) else str(x)
