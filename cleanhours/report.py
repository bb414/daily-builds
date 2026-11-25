"""Text, Markdown and CSV output for a Clean hours run."""

import csv
import os

from . import model

VERDICTS = {
    "backfires": "looks greener on paper but raises real emissions",
    "worse": "raises real emissions",
    "overstates": "overstates its benefit",
    "understates": "does more good than the report shows",
    "matches": "roughly delivers what it reports",
    "nothing": "changes little",
}


def tonnes(x):
    v = round(x)
    sign = "+" if v > 0 else ("-" if v < 0 else "")
    return "%s%s t" % (sign, format(abs(v), ","))


def pct(x):
    v = x * 100
    if abs(v) < 0.05:
        return "0.0%"
    return "%+.1f%%" % v


def describe_config(cfg):
    p = model.PRESETS[cfg["preset"]]
    return ("%s, weather year %d, wind fleet x%g, solar fleet x%g, forecast error x%g, flexibility x%g, %d job(s)"
            % (p["label"], cfg["seed"], cfg["windScale"], cfg["solarScale"], cfg["forecastError"],
               cfg["slack"], len(cfg["jobs"])))


def grid_line(result):
    s = result["summary"]
    return ("Grid: spare clean power in %.0f%% of hours, average intensity %d g/kWh, "
            "marginal intensity %d g/kWh on average, wind and solar meet %.0f%% of demand."
            % (100 * s["curtailShare"], round(s["weightedAvg"]), round(s["meanMarg"]), 100 * s["renewableShare"]))


def policy_rows(result):
    rows = []
    for p in model.POLICIES:
        R = result["policies"][p["key"]]
        rows.append({
            "scheduler": p["label"], "key": p["key"],
            "energy_mwh": R["mwh"], "reported_t": R["reported"], "real_t": R["real"],
            "reported_saved_t": R["reportedSavedT"], "real_saved_t": R["realSavedT"],
            "reported_saving": R["reportedSaving"], "real_saving": R["realSaving"],
            "mean_wait_h": R["meanDelay"], "verdict": R["verdict"],
        })
    return rows


def text_table(result):
    head = "%-32s %12s %12s %16s %16s %9s" % ("Scheduler", "Reported t", "Real t", "Reported saved", "Real saved", "Wait")
    lines = [head, "-" * len(head)]
    for r in policy_rows(result):
        if r["key"] == "now":
            rep = real = "baseline"
        else:
            rep, real = tonnes(r["reported_saved_t"]), tonnes(r["real_saved_t"])
        lines.append("%-32s %12s %12s %16s %16s %8.1fh" % (
            r["scheduler"], format(round(r["reported_t"]), ","), format(round(r["real_t"]), ","), rep, real, r["mean_wait_h"]))
    return "\n".join(lines)


def headline(result, key="avg"):
    R = result["policies"][key]
    label = next(p["label"] for p in model.POLICIES if p["key"] == key)
    return "%s %s: %s reported, %s real." % (label, VERDICTS[R["verdict"]], tonnes(R["reportedSavedT"]), tonnes(R["realSavedT"]))


def markdown(result):
    cfg = result["config"]
    p = model.PRESETS[cfg["preset"]]
    out = ["# Clean hours run", "", describe_config(cfg) + ".", "", grid_line(result)]
    out += ["", "## Schedulers", "",
            "| Scheduler | Reported t CO2 | Real t CO2 | Reported saving | Real saving | Mean wait | Verdict |",
            "|---|---:|---:|---:|---:|---:|---|"]
    for r in policy_rows(result):
        if r["key"] == "now":
            rep = real = "baseline"
            verdict = ""
        else:
            rep = "%s (%s)" % (tonnes(r["reported_saved_t"]), pct(r["reported_saving"]))
            real = "%s (%s)" % (tonnes(r["real_saved_t"]), pct(r["real_saving"]))
            verdict = VERDICTS[r["verdict"]]
        out.append("| %s | %s | %s | %s | %s | %.1f h | %s |" % (
            r["scheduler"], format(round(r["reported_t"]), ","), format(round(r["real_t"]), ","), rep, real, r["mean_wait_h"], verdict))
    out += ["", "## What was on the margin when the jobs ran", "",
            "| Scheduler | " + " | ".join(model.margin_labels(p)) + " |",
            "|---|" + "---:|" * len(model.margin_labels(p))]
    for pol in model.POLICIES:
        mix = result["policies"][pol["key"]]["mix"]
        tot = sum(mix) or 1
        out.append("| %s | %s |" % (pol["label"], " | ".join("%.1f%%" % (100 * v / tot) for v in mix)))
    out += ["", "Simplified and illustrative: an invented grid and an invented fleet of jobs, not a carbon accounting tool.", ""]
    return "\n".join(out)


def write_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r.get(k)) for k in columns})


def _cell(v):
    if isinstance(v, float):
        return "%.6g" % v if abs(v) < 1e-3 and v != 0 else round(v, 4)
    return v


def write_run(result, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cols = ["scheduler", "key", "energy_mwh", "reported_t", "real_t", "reported_saved_t", "real_saved_t",
            "reported_saving", "real_saving", "mean_wait_h", "verdict"]
    write_csv(os.path.join(out_dir, "schedulers.csv"), policy_rows(result), cols)

    job_rows = []
    for pol in model.POLICIES:
        R, B = result["policies"][pol["key"]], result["policies"]["now"]
        for j, J, JB in zip(result["config"]["jobs"], R["perJob"], B["perJob"]):
            job_rows.append({
                "scheduler": pol["key"], "job": j["name"], "runs": J["n"], "energy_mwh": J["mwh"],
                "reported_t": J["reported"], "real_t": J["real"],
                "reported_saved_t": JB["reported"] - J["reported"], "real_saved_t": JB["real"] - J["real"],
                "mean_wait_h": J["delay"] / J["n"] if J["n"] else 0,
            })
    write_csv(os.path.join(out_dir, "jobs.csv"), job_rows,
              ["scheduler", "job", "runs", "energy_mwh", "reported_t", "real_t", "reported_saved_t", "real_saved_t", "mean_wait_h"])

    g = result["grid"]
    labels = model.margin_keys(g["preset"])
    hours = []
    for t in range(len(g["avg"])):
        hours.append({"hour": t, "week": t // 168 + 1, "weekday": (t // 24) % 7, "hour_of_day": t % 24,
                      "demand_gw": g["demand"][t], "wind_gw": g["wind"][t], "solar_gw": g["solar"][t],
                      "curtailed_gw": g["curtail"][t], "average_g_per_kwh": g["avg"][t],
                      "marginal_g_per_kwh": g["marg"][t], "marginal_plant": labels[g["code"][t]]})
    write_csv(os.path.join(out_dir, "grid_hours.csv"), hours, list(hours[0].keys()))

    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(result))
    return ["summary.md", "schedulers.csv", "jobs.csv", "grid_hours.csv"]
