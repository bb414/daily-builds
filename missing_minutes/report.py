"""Text and HTML reports for the command line."""

import html as html_lib

from .model import DAY, OVERLOAD, WEEKDAYS, fmt_duration


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
    lines.append("Reaching the customer:    %.2f end-to-end minutes for every minute saved at the desk" % r["leverage"])
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
    lines.append("  %-32s %-16s %-24s %s" % ("Step", "Busy", "Waiting a case", "Hands-on a case"))
    for i, (s, t) in enumerate(zip(b["steps"], a["steps"])):
        if s["kind"] == "team":
            busy = "%s -> %s" % (_pct(s["utilisation"]), _pct(t["utilisation"]))
        elif s["kind"] == "batch":
            busy = "%s -> %s full" % (_pct(s["utilisation"]), _pct(t["utilisation"]))
        else:
            busy = "outside"
        mark = " *" if i == k else ""
        lines.append("  %-32s %-16s %-24s %s" % (
            (str(i + 1) + ". " + s["name"])[:30] + mark, busy,
            "%s -> %s" % (_dur(s["wait"]), _dur(t["wait"])),
            "none" if s["kind"] == "delay" else "%s -> %s" % (_dur(s["touch"]), _dur(t["touch"]))))
    lines.append("  (* = the step the AI helps with)")
    lines.append("")
    lines.append("Cases (working days)       Without AI   With AI")
    for label, key in (("Average", "leadMean"), ("Median", "leadP50"), ("85th percentile", "leadP85"), ("95th percentile", "leadP95")):
        lines.append("  %-24s %10.2f %9.2f" % (label, b[key] / DAY, a[key] / DAY))
    lines.append("  %-24s %10s %9s" % ("Within %s days" % _fmt(cfg["slaDays"]), _pct(b["withinSla"], 1), _pct(a["withinSla"], 1)))
    lines.append("")
    lines.append("Staff time freed:         %.2f full-time people" % r["fteFreed"])
    lines.append("Flow efficiency:          %s -> %s of the time a case is open, someone works on it" % (
        _pct(b["flowEfficiency"], 1), _pct(a["flowEfficiency"], 1)))
    lines.append("Cases sent back per 100:  %.1f -> %.1f (%.1f from AI errors)" % (
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
    if bank["freedPeople"] >= 0.05:
        lines.append("The pilot's business case frees %.1f people at %s; in practice the AI frees %.1f." % (
            bank["claimedPeople"], st["name"], bank["freedPeople"]))
    else:
        lines.append("The pilot's business case frees %.1f people at %s; in practice the AI frees no time there." % (
            bank["claimedPeople"], st["name"]))
    if not bank["possible"]:
        lines.append(bank["reason"])
        return "\n".join(lines)
    lines.append("Cut %d of %d people: cases take %s on average (%s against no AI, %s against keeping everyone)." % (
        bank["cut"], st["staff"], _dur(bank["leadMean"]), _signed(bank["vsBase"]), _signed(bank["vsAi"])))
    lines.append("%s would be %s busy and %s of cases close within %s days%s" % (
        st["name"], _pct(bank["utilisation"]), _pct(bank["withinSla"], 1), _fmt(cfg["slaDays"]),
        "; its queue keeps growing." if bank["utilisation"] >= OVERLOAD else "." if bank["stable"] else "; a queue elsewhere keeps growing."))
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


def robust_text(r, seeds, sens):
    """Robustness to luck and to each assumption."""
    cfg = r["config"]
    lines = ["How robust is it? (%s, seed %d)" % (cfg["name"], r["base"]["seed"]), ""]
    lines.append("With %d runs of different luck (seeds %d to %d):" % (seeds["n"], seeds["runs"][0]["seed"], seeds["runs"][-1]["seed"]))
    lines.append("  the AI made cases faster in %d, slower in %d; change from %s to %s, average %s." % (
        seeds["helped"], seeds["hurt"], _signed(seeds["min"]), _signed(seeds["max"]), _signed(seeds["mean"])))
    for run in seeds["runs"]:
        lines.append("    seed %-8d %10s  (%.2f minutes reach the customer per minute saved)%s" % (
            run["seed"], _signed(run["total"]), run["leverage"], "" if run["stable"] else "  queue grows"))
    lines.append("")
    lines.append("What moves the answer (your setting: %s)" % _signed(r["total"]))
    lines.append("  %-28s %-18s %10s   %-18s %10s" % ("Assumption", "Lower", "", "Higher", ""))
    for t in sens:
        lines.append("  %-28s %-18s %10s   %-18s %10s%s" % (
            t["label"], t["lowLabel"], _signed(t["low"]), t["highLabel"], _signed(t["high"]),
            "" if t["stable"] else "  queue grows"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _e(text):
    return html_lib.escape(str(text), quote=True)


def _minus(text):
    return "−" + text[1:] if text.startswith("-") else text


def _bar_rows(rows, total_row=None):
    """rows: (label, note, value, start, end) in minutes; draws bars on a shared scale."""
    lo = min([0] + [min(r[3], r[4]) for r in rows] + ([min(0, total_row[2])] if total_row else []))
    hi = max([0] + [max(r[3], r[4]) for r in rows] + ([max(0, total_row[2])] if total_row else []))
    span = (hi - lo) or 1

    def x(v):
        return (v - lo) / span * 100

    out = []
    for label, note, value, a, b in rows + ([(total_row[0], "", total_row[2], 0, total_row[2])] if total_row else []):
        left, width = min(x(a), x(b)), max(abs(x(b) - x(a)), 0.4)
        cls = "save" if value < 0 else "cost"
        out.append('<div class="row%s"><div class="lab">%s%s</div><div class="track"><div class="zero" style="left:%.2f%%"></div>'
                   '<div class="bar %s" style="left:%.2f%%;width:%.2f%%"></div></div><div class="val %s">%s</div></div>' % (
                       " total" if total_row and label == total_row[0] else "", _e(label),
                       '<div class="note">%s</div>' % _e(note) if note else "", x(0), cls, left, width, cls, _e(_minus(_signed(value)))))
    return "\n".join(out)


def html_report(r, bank, options, seeds=None, sens=None):
    """A self-contained HTML report (no external requests) for one comparison."""
    cfg = r["config"]
    k = cfg["ai"]["step"]
    step = cfg["steps"][k]
    b, a = r["base"], r["ai"]
    parts = []
    cum = 0
    for p in r["parts"]:
        if p["key"].startswith("wait") and abs(p["value"]) < 0.5:
            continue
        parts.append((p["label"], "", p["value"], cum, cum + p["value"]))
        cum += p["value"]
    other = r["total"] - cum
    if abs(other) >= 0.05:
        parts.append(("Waiting elsewhere", "", other, cum, cum + other))
    waterfall = _bar_rows(parts, ("Change in end-to-end time", "", r["total"]))

    steps_rows = []
    for i, (s, t) in enumerate(zip(b["steps"], a["steps"])):
        if s["kind"] == "team":
            busy = "%s to %s" % (_pct(s["utilisation"]), _pct(t["utilisation"]))
        elif s["kind"] == "batch":
            days = ", ".join(WEEKDAYS[d] for d in cfg["steps"][i]["batchDays"])
            busy = "%s; sessions %s to %s full" % (days, _pct(s["utilisation"]), _pct(t["utilisation"]))
        else:
            busy = "outside the team"
        hands_on = "none" if s["kind"] == "delay" else "%s to %s" % (_dur(s["touch"]), _dur(t["touch"]))
        steps_rows.append("<tr><td>%d. %s%s</td><td>%s</td><td>%s to %s</td><td>%s</td></tr>" % (
            i + 1, _e(s["name"]), ' <span class="tag">AI</span>' if i == k else "", busy,
            _minus(_dur(s["wait"])), _minus(_dur(t["wait"])), hands_on))

    opt_rows = [(o["label"] + (" (current)" if o["current"] else ""),
                 ("saves %s at the desk; %.1f errors per 100 cases reach customers" % (_dur(o["atDesk"]), o["escapedPer100"]))
                 if o["kind"] == "ai" else "one extra full-time person", o["total"], 0, o["total"]) for o in options]

    lead_rows = "".join("<tr><td>%s</td><td>%.2f days</td><td>%.2f days</td></tr>" % (lab, b[key] / DAY, a[key] / DAY)
                        for lab, key in (("Average", "leadMean"), ("Median", "leadP50"), ("85th percentile", "leadP85"), ("95th percentile", "leadP95")))
    lead_rows += "<tr><td>Closed within %s days</td><td>%s</td><td>%s</td></tr>" % (_fmt(cfg["slaDays"]), _pct(b["withinSla"], 1), _pct(a["withinSla"], 1))

    robust_html = ""
    if seeds is not None:
        robust_html = "<h2>How robust is it?</h2><p>With %d runs of different luck, the AI made cases faster in %d and slower in %d. The change ranged from %s to %s (average %s).</p>" % (
            seeds["n"], seeds["helped"], seeds["hurt"], _minus(_signed(seeds["min"])), _minus(_signed(seeds["max"])), _minus(_signed(seeds["mean"])))
    tornado_html = ""
    if sens is not None:
        rows = "".join("<tr><td>%s</td><td>%s: %s</td><td>%s: %s</td><td>%s</td></tr>" % (
            _e(t["label"]), _e(t["lowLabel"]), _minus(_signed(t["low"])), _e(t["highLabel"]), _minus(_signed(t["high"])), _dur(t["swing"]))
            for t in sens)
        tornado_html = "<h2>What moves the answer</h2><table><thead><tr><th>Assumption</th><th>Lower</th><th>Higher</th><th>Gap</th></tr></thead><tbody>%s</tbody></table>" % rows

    warn = ""
    if not r["stable"]:
        over = sorted(set(b["overloaded"]) | set(a["overloaded"]))
        warn = '<p class="warn">%s cannot keep up, so a queue keeps growing and the averages depend on how long the simulation runs.</p>' % _e(
            ", ".join(cfg["steps"][j]["name"] for j in over) or "A step")

    bank_html = "<h2>Bank the saving as a headcount cut?</h2><p>%s</p>" % _e(bank_text(r, bank).split("\n", 2)[2].replace("\n", " "))

    return """<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Missing minutes: %(name)s</title>
<style>
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #17202b; max-width: 920px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 28px 0 8px; }
.muted, .note { color: #5b6775; } .note { font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 16px 0; }
.card { border: 1px solid #dde2e8; border-radius: 9px; padding: 12px 14px; }
.card .k { font-size: 13px; color: #5b6775; font-weight: 600; } .card .v { font-size: 24px; font-weight: 700; }
.row { display: grid; grid-template-columns: minmax(140px, 260px) minmax(0, 1fr) 90px; gap: 10px; align-items: center; padding: 4px 0; }
.row.total { font-weight: 700; border-top: 1px solid #dde2e8; padding-top: 8px; }
.track { position: relative; height: 16px; } .zero { position: absolute; top: -3px; bottom: -3px; width: 1px; background: #5b6775; }
.bar { position: absolute; top: 2px; bottom: 2px; border-radius: 3px; } .bar.save { background: #1f6fb2; } .bar.cost { background: #c2541b; }
.val { text-align: right; font-variant-numeric: tabular-nums; } .val.save { color: #1f6fb2; } .val.cost { color: #c2541b; }
table { border-collapse: collapse; width: 100%%; font-size: 14px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #dde2e8; } th { color: #5b6775; font-size: 13px; }
.tag { background: #d7ecee; color: #0f6e78; font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 999px; }
.warn { background: #fff4e0; color: #7a4a00; padding: 10px 12px; border-radius: 8px; }
@media (max-width: 560px) { .row { grid-template-columns: minmax(0, 1fr) 80px; } .row .lab { grid-column: 1 / -1; } }
</style></head><body>
<h1>Missing minutes: %(name)s</h1>
<p class="muted">The AI helps with step %(k1)d, %(step)s: it saves %(saving)s of the hands-on time on %(adoption)s of cases, takes %(check)s minutes to check and is wrong on %(err)s of cases (%(catch)s of errors caught later). %(arr)s cases a day, %(days)d measured working days, seed %(seed)d. Invented process, synthetic data.</p>
%(warn)s
<div class="cards">
<div class="card"><div class="k">The pilot's promise</div><div class="v">%(claim)s</div><div class="note">saved on each case at %(step)s</div></div>
<div class="card"><div class="k">End to end</div><div class="v">%(total)s</div><div class="note">%(lb)s without the AI, %(la)s with it</div></div>
<div class="card"><div class="k">Minutes that reached the customer</div><div class="v">%(lev)s&times;</div><div class="note">for each minute saved at the desk</div></div>
</div>
<h2>Where the minutes went</h2><p class="note">Average change per case. Blue saves time; orange adds it.</p>
%(waterfall)s
<h2>Step by step</h2>
<table><thead><tr><th>Step</th><th>Busy</th><th>Waiting a case</th><th>Hands-on a case</th></tr></thead><tbody>%(steps)s</tbody></table>
<h2>How long cases take</h2>
<table><thead><tr><th>Cases</th><th>Without the AI</th><th>With the AI</th></tr></thead><tbody>%(lead)s</tbody></table>
<p class="note">Staff time freed: %(fte).2f full-time people. Cases sent back: %(sb).1f to %(sa).1f per 100. AI errors reaching customers: %(esc).1f per 100 cases.</p>
<h2>Where else could the time come from?</h2><p class="note">The same AI on each other step against one more person at each team step; change in end-to-end time against no AI.</p>
%(options)s
%(bank)s
%(robust)s
%(tornado)s
<p class="note" style="margin-top:32px">Made with Missing minutes, a discrete-event simulation of a process with and without an AI assistant. A thinking tool, not a forecast.</p>
</body></html>
""" % {
        "name": _e(cfg["name"]), "k1": k + 1, "step": _e(step["name"]), "saving": _pct(cfg["ai"]["saving"]),
        "adoption": _pct(cfg["ai"]["adoption"]), "check": _fmt(cfg["ai"]["checkMinutes"]), "err": _pct(cfg["ai"]["errorRate"]),
        "catch": _pct(cfg["ai"]["catchRate"]), "arr": _fmt(cfg["arrivalsPerDay"]), "days": cfg["measureDays"], "seed": b["seed"],
        "warn": warn, "claim": _dur(r["pilotClaim"]),
        "total": _e(_minus(_signed(r["total"]))), "lb": _dur(b["leadMean"]), "la": _dur(a["leadMean"]),
        "lev": _minus("%.2f" % r["leverage"]), "waterfall": waterfall, "steps": "".join(steps_rows), "lead": lead_rows,
        "fte": r["fteFreed"], "sb": b["aiSendBacksPer100"] + b["baseSendBacksPer100"], "sa": a["aiSendBacksPer100"] + a["baseSendBacksPer100"],
        "esc": a["escapedPer100"], "options": _bar_rows(opt_rows), "bank": bank_html, "robust": robust_html, "tornado": tornado_html,
    }
