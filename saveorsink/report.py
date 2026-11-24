"""Plain-text reports."""

import math

from .model import MONTH_STARTS, MONTHS, PRESETS, RULE_NAMES, RULES, money


def whole(x):
    """Round to a whole number, halves up (as the app's Math.round does)."""
    return int(math.floor(x + 0.5))


def percent(x):
    return whole(x * 100)


def plural(n, word, words=None):
    """'1 day', '2 days'; n is shown with thousands separators."""
    return "%s %s" % ("{:,}".format(n), word if n == 1 else (words or word + "s"))


def pounds(v):
    """A setting in pounds: whole pounds without pence."""
    return "£{:,}".format(int(v)) if v == int(v) else money(v * 100)


def setting_line(s):
    """The overdraft and the raiding habit, as one sentence."""
    limit = s["overdraftLimit"]
    overdraft = "No interest-free overdraft" if limit == 0 else "Interest-free overdraft %s" % pounds(limit)
    habit = s["rescue"]
    if habit == "near-limit" and limit < 100:
        rescue = "moves money back from savings as soon as they are overdrawn (the limit is under £100)"
    else:
        rescue = {"overdrawn": "moves money back from savings as soon as they are overdrawn",
                  "near-limit": "moves money back from savings only when within £100 of the limit",
                  "never": "never moves money back from savings"}[habit]
    return "%s; the student %s." % (overdraft, rescue)


def preset_label(s):
    preset = s.get("preset")
    return PRESETS[preset]["label"] if isinstance(preset, str) and preset in PRESETS else "Custom settings"


def summary_report(s, summary, years):
    label = preset_label(s)
    lines = [
        "Save or sink: %s, %s" % (label, plural(years, "simulated year")),
        setting_line(s),
        "",
        "  %-48s %10s %10s %8s %11s %11s %11s" % ("Rule", "Set aside", "Moved in", "Raids", "Came back", "Past limit",
                                                     "Better off"),
    ]
    for r in RULES:
        if r not in summary:
            continue
        x = summary[r]
        saving = r != "none"
        lines.append("  %-48s %10s %10s %8s %11s %10d%% %11s" % (
            RULE_NAMES[r], money(x["endPot"]["p50"]), money(x["savedIn"]["p50"]),
            "%d/yr" % whole(x["meanRescues"]) if saving else "n/a",
            "%d%%" % percent(x["cameBack"]) if saving else "n/a",
            percent(x["beyondChance"]), money(x["net"]["p50"], signed=True) if saving else "n/a"))
    lines += ["", "Set aside, moved in and better off are typical years (medians); raids are a yearly average;",
              "came back is the share of what went into savings (including interest) that was moved back out;",
              "past limit is the share of years that go beyond the interest-free overdraft at least once."]
    return "\n".join(lines)


DIAL_LABELS = {"horizon": "Looks ahead", "buffer": "Safety buffer", "aggressiveness": "Share saved", "cap": "Daily cap"}


def dial_text(key, value):
    if key == "horizon":
        return plural(int(value), "day")
    if key in ("buffer", "cap"):
        return pounds(value)
    return "%d%%" % percent(value)


def sweep_report(s, result):
    """The sweep as a table, best off first, with the frontier marked."""
    ka, kb = result["dials"]
    label = preset_label(s)
    lines = [
        "Tuning the %s: %s, %s per row" % (
            RULE_NAMES[result["rule"]].split(" (")[0].lower(), label, plural(result["years"], "simulated year")),
        setting_line(s),
        "Without any saving, %d%% of years go past the overdraft limit, for %s a year on average." % (
            percent(result["beyondWithoutSaving"]), plural(whole(result["daysBeyondWithoutSaving"]), "day")),
        "",
        "  %-14s %-14s %10s %8s %10s %11s %10s %11s  %s" % (DIAL_LABELS[ka], DIAL_LABELS[kb], "Set aside", "Raids",
                                                            "Came back", "Past limit", "Days past", "Better off",
                                                            "Frontier"),
    ]
    rows = sorted(result["rows"], key=lambda r: (-r["net"], r["beyondChance"], r["meanRescues"]))
    for r in rows:
        lines.append("  %-14s %-14s %10s %8s %9d%% %10d%% %10d %11s  %s" % (
            dial_text(ka, r[ka]), dial_text(kb, r[kb]), money(r["endPot"]), "%.1f/yr" % r["meanRescues"],
            percent(r["cameBack"]), percent(r["beyondChance"]), whole(r["meanDaysBeyond"]),
            money(r["net"], signed=True), "yes" if r["frontier"] else ""))
    best = [r for r in rows if r["frontier"]]
    lines += ["", "%s %s on the frontier: no other setting leaves the student better off without" % (
              "%d of %d settings" % (len(best), len(rows)) if len(rows) > 1 else "The one setting",
              "is" if len(best) == 1 else "are"),
              "also going past the overdraft limit in more years or being raided more often.",
              "Days past is the average number of days a year spent beyond the interest-free overdraft."]
    return "\n".join(lines)


def year_report(s, days, res, rule):
    """Month by month for one simulated year."""
    lines = ["One year with: %s" % RULE_NAMES[rule], "",
             "  %-5s %12s %12s %14s %12s %8s" % ("Month", "Money in", "Money out", "End balance", "Savings", "Raids")]
    daily = res["daily"]
    for i, (name, length) in enumerate(MONTHS):
        start = MONTH_STARTS[i]
        money_in = sum(a for d in range(start, start + length) for _, a in days[d]["in"])
        money_out = sum(a for d in range(start, start + length) for _, a, _ in days[d]["out"])
        raids = sum(1 for d in range(start, start + length) if daily[d]["rescued"] > 0)
        end = daily[start + length - 1]
        lines.append("  %-5s %12s %12s %14s %12s %8d" % (name, money(money_in), money(money_out), money(end["balance"]),
                                                       money(end["pot"]), raids))
    lines += ["", "Set aside on 31 August %s; lowest balance %s; %s past the overdraft limit." % (
        money(res["endPot"]), money(res["lowest"]), plural(res["daysBeyond"], "day"))]
    return "\n".join(lines)
