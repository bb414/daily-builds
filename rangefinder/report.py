"""Plain-text reports."""

from .model import drivers_of, format_driver, format_value, percent


def text_report(model, res):
    """A readable summary of one analysed model."""
    def fv(x):
        return format_value(x, model["unit"], model["unitPosition"])

    lines = [
        model["title"] or "Untitled estimate",
        "",
        "%s: most likely between %s and %s (10th to 90th percentile)" % (
            model["outputName"] or "Estimate", fv(res["p10"]), fv(res["p90"])),
        "  Median %s, average %s, 5th to 95th percentile %s to %s" % (
            fv(res["p50"]), fv(res["mean"]), fv(res["p5"]), fv(res["p95"])),
        "  Plugging in the middle of every range gives %s" % fv(res["atMidpoints"]),
    ]
    if res["threshold"] is not None:
        lines.append("  Chance of clearing %s: %d%%" % (fv(res["threshold"]), percent(res["probAbove"])))
    lines += ["", "Which ranges matter most (estimate at each driver's 10th and 90th percentile):"]
    drv = drivers_of(model)
    width = max(len(d["name"]) for _, _, d in drv)
    fixed = []
    for i in res["tornado"]:
        r = res["drivers"][i]
        d = drv[i][2]
        if d["dist"] == "fixed":
            fixed.append(r["name"])
            continue
        lines.append("  %-*s  %10s to %-10s  range %s to %s, %2d%% of the spread" % (
            width, r["name"], fv(r["lowOut"]), fv(r["highOut"]),
            format_driver(r["p10"], d), format_driver(r["p90"], d), percent(max(0, r["varShare"]))))
    lines.append("  %-*s  %2d%% of the spread" % (width + 44, "Drivers combining (interactions)", percent(res["interaction"])))
    if fixed:
        lines.append("  Fixed, so not part of the spread: %s" % ", ".join(fixed))
    v = res.get("voi")
    if v:
        lines += ["", "The decision: on the expected value the call is to %s; there is a %d%% chance that is wrong." % (
            "go ahead" if v["decision"] == "go" else "hold off", percent(v["wrongChance"]))]
        if v["evpi"] <= 0:
            lines.append("Whatever the true values turn out to be, the call would not change: nothing is worth checking first.")
        else:
            lines.append("Knowing every driver exactly would be worth up to %s. Check first:" % fv(v["evpi"]))
            shown = [i for i in v["order"] if drv[i][2]["dist"] != "fixed"][:3]
            for i in shown:
                x = v["drivers"][i]
                lines.append("  %-*s  worth up to %s, changes the call %d%% of the time" % (
                    width, res["drivers"][i]["name"], fv(x["evppi"]), percent(x["flip"])))
    lines += ["", "{:,} Latin hypercube samples.".format(res["n"])]
    return "\n".join(lines)
