"""Plain-text reports."""

import math

from .model import MONTH_STARTS, MONTHS, PRESETS, RULE_NAMES, RULES, money


def whole(x):
    """Round to a whole number, halves up (as the app's Math.round does)."""
    return int(math.floor(x + 0.5))


def percent(x):
    return whole(x * 100)


def summary_report(s, summary, years):
    label = PRESETS.get(s.get("preset"), {}).get("label", "Custom settings")
    rescue = {"overdrawn": "as soon as they are overdrawn", "near-limit": "only when within £100 of the limit",
              "never": "never"}[s["rescue"]]
    lines = [
        "Save or sink: %s, %s simulated years" % (label, "{:,}".format(years)),
        "Interest-free overdraft %s; the student moves money back from savings %s." % (
            money(s["overdraftLimit"] * 100), rescue),
        "",
        "  %-46s %12s %12s %10s %12s %12s" % ("Rule", "Set aside", "Moved in", "Raids", "Past limit", "Better off"),
    ]
    for r in RULES:
        x = summary[r]
        lines.append("  %-46s %12s %12s %10s %11d%% %12s" % (
            RULE_NAMES[r], money(x["endPot"]["p50"]), money(x["savedIn"]["p50"]),
            "n/a" if r == "none" else "%d/yr" % whole(x["meanRescues"]),
            percent(x["beyondChance"]), "n/a" if r == "none" else money(x["net"]["p50"], signed=True)))
    lines += ["", "Set aside, moved in and better off are typical years (medians); raids are a yearly average;",
              "past limit is the share of years that go beyond the interest-free overdraft at least once."]
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
    lines += ["", "Set aside on 31 August %s; lowest balance %s; %d days past the overdraft limit." % (
        money(res["endPot"]), money(res["lowest"]), res["daysBeyond"])]
    return "\n".join(lines)
