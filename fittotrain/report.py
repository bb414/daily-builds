"""Plain-text reports for the command line."""

from . import model
from .audit import MIN_CLOSED

LIGHT_WORDS = {"green": "OK", "amber": "Watch", "red": "Fix", "na": "n/a"}


def f2(x):
    return "n/a" if x is None else "%.2f" % x


def pct(x, dp=0):
    return "n/a" if x is None else "%.*f%%" % (dp, x * 100)


def signed(x, dp=2):
    if x is None:
        return "n/a"
    text = "%.*f" % (dp, x)
    if float(text) == 0:
        return "%.*f" % (dp, 0)
    return ("+" if x > 0 else "") + text


def money(x):
    if x is None:
        return "n/a"
    if abs(x) >= 1e6:
        return "GBP %.1fm" % (x / 1e6)
    return "GBP %dk" % round(x / 1000)


def table(headers, rows, align=None):
    """A simple fixed-width text table."""
    align = align or ["<"] * len(headers)
    cells = [[str(h) for h in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = []
    for k, r in enumerate(cells):
        lines.append("  ".join(("{:%s%d}" % (align[i], widths[i])).format(r[i]) for i in range(len(r))).rstrip())
        if k == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def settings_line(s):
    parts = ["%s %s" % (d["label"].lower(), pct(s[d["key"]])) for d in model.DEFECTS]
    return "World %d, %d deals. %s." % (s["seed"], s["deals"], "; ".join(parts).capitalize())


def lab_text(r):
    s = r["settings"]
    out = ["FIT TO TRAIN: lab run", settings_line(s), ""]
    out.append(table(
        ["", "Pilot back-test", "Live after go-live", "Clean ceiling"],
        [["Ranking score (AUC)", f2(r["backtest"]["auc"]), f2(r["live"]["auc"]), f2(r["ceiling"]["auc"])],
         ["Wins in top 20% of scores", pct(r["backtest"]["capture20"]), pct(r["live"]["capture20"]), pct(r["ceiling"]["capture20"])],
         ["Mean predicted win chance", pct(r["backtest"]["meanPredicted"]), pct(r["live"]["meanPredicted"]), pct(r["ceiling"]["meanPredicted"])],
         ["Actual win rate", pct(r["backtest"]["winRate"]), pct(r["live"]["winRate"]), pct(r["ceiling"]["winRate"])],
         ["Deals scored", r["backtest"]["n"], r["live"]["n"], r["ceiling"]["n"]]],
        ["<", ">", ">", ">"]))
    out.append("")
    out.append("Pilot illusion (back-test minus live): %s" % signed(r["illusion"]))
    out.append("Data debt (clean ceiling minus live):  %s" % signed(r["debt"]))
    out.append("Live bookings forecast: %s expected against %s actual (%s%%; clean model %s%%)" % (
        money(r["live"]["forecast"]), money(r["live"]["actual"]),
        signed(r["live"]["forecastError"] * 100, 0), signed(r["ceiling"]["forecastError"] * 100, 0)))
    rep = r["repaired"]
    out.append("")
    out.append("Honest back-test: the same CRM repaired before testing")
    out.append(steps_text(rep["steps"]))
    out.append(table(["", "Back-test", "Live", "Gap", "Predicted win rate live"],
                     [["As exported", f2(r["backtest"]["auc"]), f2(r["live"]["auc"]), signed(r["illusion"]), pct(r["live"]["meanPredicted"])],
                      ["Repaired first", f2(rep["backtest"]["auc"]), f2(rep["live"]["auc"]),
                       signed(rep["backtest"]["auc"] - rep["live"]["auc"]), pct(rep["live"]["meanPredicted"])]],
                     ["<", ">", ">", ">", ">"]))
    out.append("Actual live win rate: %s. Meetings logged by hand cannot be repaired from the history." % pct(r["live"]["winRate"]))
    if r.get("fixes"):
        out.append("")
        out.append(fix_text(r))
    out.append("")
    out.append("Data-quality audit (visible without the truth)")
    out.append(audit_table(r["audit"]["rows"]))
    return "\n".join(out)


def steps_text(st):
    return "\n".join([
        "  1. Blanked champion, stakeholder and competitor fields on %d closed deals edited after closing" % st["edited"],
        "  2. Closed out %d open deals more than 30 days past their close date, as losses" % st["zombies"],
        "  3. Dropped %d lost deals that look like re-entered copies of a win" % st["duplicates"],
        "  4. Treated %d round amounts as unknown (segment median instead)" % st["amounts"],
    ])


def fix_text(r):
    f = r["fixes"]
    if not f["rows"]:
        return "Which habit to fix first: every habit is already at zero."
    lines = ["Which habit to fix first (each fixed on its own, everything else unchanged)",
             table(["Habit", "Live if fixed", "Gain", "Illusion removed", "Win-rate bias after"],
                   [[row["label"], f2(row["liveAuc"]), signed(row["gain"]), signed(row["illusionDrop"]),
                     signed(row["calibration"] * 100, 0) + " pts"] for row in f["rows"]],
                   ["<", ">", ">", ">", ">"]),
             "Fixing them in that order, live score: " + " > ".join(f2(p["liveAuc"]) for p in f["path"]) +
             " (clean ceiling %s)" % f2(r["ceiling"]["auc"])]
    return "\n".join(lines)


def audit_value(row):
    if row["value"] is None:
        return "n/a"
    if row["key"] == "loggingShift":
        return signed(row["value"] * 100, 0) + "%"
    return pct(row["value"])


def audit_table(rows):
    return table(["Check", "Result", "Flag", "What it means"],
                 [[row["check"], audit_value(row), LIGHT_WORDS[row["light"]], row["detail"]] for row in rows],
                 ["<", ">", "<", "<"])


def export_audit_text(a, path):
    out = ["FIT TO TRAIN: readiness audit of %s" % path,
           "%d records, %d closed, win rate among closed %s. Extract date taken as %s." % (
               a["records"], a["closed"], pct(a["winRate"]), a["asOf"]), ""]
    out.append(audit_table(a["rows"]))
    if a["missingFields"]:
        out.append("")
        out.append("Scoring fields not in the file (treated as blank): " + ", ".join(a["missingFields"]))
    bt = a["backtests"]
    out.append("")
    out.append("Back-tests of a win-probability model on the closed deals")
    if bt["random"] is None and bt["time"] is None:
        out.append("  Not enough closed deals with both wins and losses to fit a model (%d closed; need %d)." % (
            bt["closed"], MIN_CLOSED))
    else:
        rows = []
        for name, ev in (("Random 25% hold-out", bt["random"]), ("Newest 25% of closed deals", bt["time"])):
            if ev is None:
                rows.append([name, "n/a", "n/a", "n/a", "n/a"])
            else:
                rows.append([name, f2(ev["auc"]), pct(ev["capture20"]), pct(ev["meanPredicted"]), pct(ev["winRate"])])
        ev = bt.get("repaired")
        rows.append(["Random hold-out, repaired first"] + (["n/a"] * 4 if ev is None else
                    [f2(ev["auc"]), pct(ev["capture20"]), pct(ev["meanPredicted"]), pct(ev["winRate"])]))
        out.append(table(["Hold-out", "AUC", "Wins in top 20%", "Predicted", "Actual"], rows, ["<", ">", ">", ">", ">"]))
        if bt["random"] and bt["time"] and bt["random"]["auc"] is not None and bt["time"]["auc"] is not None:
            gap = bt["random"]["auc"] - bt["time"]["auc"]
            if gap > 0.03:
                out.append("  The random hold-out beats the time-ordered one by %.2f: expect live results nearer the lower figure." % gap)
            elif gap < -0.03:
                out.append("  The newest deals score %.2f better than the random hold-out; with hold-outs this small that can be chance." % -gap)
            else:
                out.append("  The two hold-outs agree within 0.03.")
        out.append("  Repairs made before the last row:")
        out.append(steps_text(bt["steps"]))
        if bt["random"] and ev and bt["random"]["auc"] is not None and ev["auc"] is not None and bt["random"]["auc"] - ev["auc"] > 0.03:
            out.append("  Repairing the export lowers the back-test by %.2f: the raw figure is likely to overpromise." % (bt["random"]["auc"] - ev["auc"]))
    if a["fieldSignal"] is not None:
        out.append("")
        out.append("Leak check: each field alone, on records edited after closing vs untouched (AUC; 0.5 = no signal)")
        rows = []
        for fs in a["fieldSignal"]:
            rows.append([fs["label"], f2(fs["edited"]), f2(fs["untouched"]), "suspect" if fs["suspect"] else ""])
        out.append(table(["Field", "Edited", "Untouched", ""], rows, ["<", ">", ">", "<"]))
        if any(fs["suspect"] for fs in a["fieldSignal"]):
            out.append("  Fields marked suspect predict far better once a deal has closed: train on their values at the scoring point.")
    return "\n".join(out)


def robust_text(rb):
    n = len(rb["worlds"])
    sm = rb["summary"]
    out = ["FIT TO TRAIN: the same settings on %d other worlds" % n, settings_line(rb["settings"]).replace(
        "World %d" % rb["settings"]["seed"], "Worlds %d to %d" % (rb["worlds"][0]["seed"], rb["worlds"][-1]["seed"])), ""]
    rows = []
    for key, name in (("backtest", "Pilot back-test"), ("live", "Live after go-live"), ("ceiling", "Clean-data ceiling"),
                      ("illusion", "Pilot illusion"), ("repairedBacktest", "Back-test after repairs"),
                      ("repairedLive", "Live, repaired model"), ("repairedGap", "Gap after repairs")):
        fmt = signed if key in ("illusion", "repairedGap") else f2
        rows.append([name, fmt(sm[key]["mean"]), fmt(sm[key]["low"]), fmt(sm[key]["high"])])
    for key, name in (("bias", "Win-rate bias live (pts)"), ("repairedBias", "Same, repaired model (pts)")):
        rows.append([name] + [signed(sm[key][c] * 100, 0) for c in ("mean", "low", "high")])
    out.append(table(["", "Average", "Lowest", "Highest"], rows, ["<", ">", ">", ">"]))
    out.append("")
    out.append("The pilot overpromised by more than 0.05 in %d of %d worlds." % (rb["overpromised"], n))
    out.append("Repaired first, %d of %d back-tests landed within 0.05 of live; the repaired model beat the unrepaired one in %d." % (
        rb["repairedHonest"], n, rb["repairHelped"]))
    fw = rb.get("fixWinners")
    if fw and (fw["live"] or fw["honest"]):
        labels = {d["key"]: d["label"] for d in model.DEFECTS}
        out.append("")
        out.append("Which habit came out as the one to fix first")
        keys = [d["key"] for d in model.DEFECTS if d["key"] in fw["live"] or d["key"] in fw["honest"]]
        out.append(table(["Habit", "Most live accuracy", "Most overpromise removed"],
                         [[labels[k], "%d of %d" % (fw["live"].get(k, 0), n), "%d of %d" % (fw["honest"].get(k, 0), n)] for k in keys],
                         ["<", ">", ">"]))
    return "\n".join(out)


def sweep_text(res):
    label = [d["label"] for d in model.DEFECTS if d["key"] == res["habit"]][0]
    out = ["FIT TO TRAIN: sweep of %s (%d worlds per level, averages)" % (label.lower(), res["worlds"]), ""]
    out.append(table(["Level", "Back-test", "Live", "Illusion", "Repaired back-test", "Repaired live", "Ceiling", "Bias", "Repaired bias"],
                     [[pct(m["level"]), f2(m["backtest"]), f2(m["live"]), signed(m["illusion"]), f2(m["repaired_backtest"]),
                       f2(m["repaired_live"]), f2(m["ceiling"]), signed(m["bias"] * 100, 0) + " pts",
                       signed(m["repaired_bias"] * 100, 0) + " pts"] for m in res["means"]],
                     ["<"] + [">"] * 8))
    return "\n".join(out)
