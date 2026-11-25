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
    return ("+" if x > 0 else "") + "%.*f" % (dp, x)


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
    out.append("")
    out.append("Data-quality audit (visible without the truth)")
    out.append(audit_table(r["audit"]["rows"]))
    return "\n".join(out)


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
        out.append(table(["Hold-out", "AUC", "Wins in top 20%", "Predicted", "Actual"], rows, ["<", ">", ">", ">", ">"]))
        if bt["random"] and bt["time"] and bt["random"]["auc"] is not None and bt["time"]["auc"] is not None:
            gap = bt["random"]["auc"] - bt["time"]["auc"]
            if gap > 0.03:
                out.append("  The random hold-out beats the time-ordered one by %.2f: expect live results nearer the lower figure." % gap)
            elif gap < -0.03:
                out.append("  The newest deals score %.2f better than the random hold-out; with hold-outs this small that can be chance." % -gap)
            else:
                out.append("  The two hold-outs agree within 0.03.")
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
