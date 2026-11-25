"""Command-line companion to the Mislabelled browser app.

    python -m mislabelled sample      write an invented statement as CSV
    python -m mislabelled compare     replay the five strategies over many statements
    python -m mislabelled weekly      a few checks each week: month-by-month results
    python -m mislabelled categorise  run the app's model on your own CSV
"""

import argparse
import csv
import datetime
import json
import os
import sys

from . import model as M
from . import report


def _seed_list(text):
    """'20' means seeds 1 to 20; '5-9' means 5 to 9; '3,7,11' is a list."""
    text = str(text).strip()
    if "," in text:
        seeds = [int(s) for s in text.split(",") if s.strip()]
    elif "-" in text:
        a, b = text.split("-", 1)
        seeds = list(range(int(a), int(b) + 1))
    else:
        seeds = list(range(1, int(text) + 1))
    if not seeds or any(s < 1 for s in seeds):
        raise argparse.ArgumentTypeError("seeds must be positive whole numbers")
    return seeds


def _personas(text):
    if text == "all":
        return [p["id"] for p in M.DATA["personas"]]
    ids = [t.strip() for t in text.split(",") if t.strip()]
    for pid in ids:
        if pid not in M.PERSONAS:
            raise argparse.ArgumentTypeError(
                "unknown persona %r (choose from %s or all)" % (pid, ", ".join(M.PERSONAS)))
    return ids


def _money(pennies):
    """Plain amount for CSV files, such as 12.50."""
    return "%.2f" % (pennies / 100)


def _pounds(pennies):
    """Amount for people to read, such as £1,234.50."""
    return "£{:,.2f}".format(pennies / 100)


# ---------- sample ----------

def cmd_sample(args, out):
    st = M.generate_statement(args.persona, args.weeks, args.seed)
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "description", "amount", "category"])
        for tx in st["tx"]:
            w.writerow([tx["date"], tx["desc"], _money(tx["pennies"]), M.CATS[tx["cat"]]])
    out.write("Wrote %d invented payments for %s to %s\n" % (
        len(st["tx"]), M.PERSONAS[args.persona]["label"], args.output))
    return 0


# ---------- compare ----------

def run_batch(personas, seeds, weeks, checks, target, slip, weight):
    """Replay every strategy on every statement. Returns (rows, summary)."""
    rows = []
    for pid in personas:
        for seed in seeds:
            st = M.generate_statement(pid, weeks, seed)
            results = M.compare_strategies(st, checks=checks, target=target, slip=slip, weight=weight)
            won = M.winners(results)
            for res in results:
                rows.append({"persona": pid, "seed": seed, "strategy": res["strategy"],
                             "points": res["points"], "toTarget": res["toTarget"], "n": len(st["tx"]),
                             "win": 1 / len(won) if res["strategy"] in won else 0})
    summary = summarise_batch(rows, personas, checks)
    return rows, summary


def summarise_batch(rows, personas, checks):
    summary = []
    for pid in personas:
        for s in M.STRATEGIES:
            mine = [r for r in rows if r["persona"] == pid and r["strategy"] == s["id"]]
            if not mine:
                continue
            reached = [r["toTarget"] for r in mine if r["toTarget"] is not None]
            # unreached runs count as "more than checks" so the median stays honest
            padded = [r["toTarget"] if r["toTarget"] is not None else checks + 1 for r in mine]
            curve = []
            for k in range(checks + 1):
                vals = [r["points"][min(k, len(r["points"]) - 1)]["misPct"] for r in mine]
                curve.append((M.quantile(vals, 0.1), M.quantile(vals, 0.5), M.quantile(vals, 0.9)))
            med = M.quantile(padded, 0.5)
            summary.append({
                "persona": pid,
                "strategy": s["id"],
                "label": s["label"],
                "runs": len(mine),
                "reachedShare": len(reached) / len(mine),
                "wins": sum(r["win"] for r in mine),
                "medianChecks": None if med > checks else med,
                "dayOne": M.quantile([r["points"][0]["misPct"] for r in mine], 0.5),
                "curve": curve,
            })
    return summary


def write_batch(rows, summary, outdir, meta):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "curves.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["persona", "seed", "strategy", "checks", "wrong_pot_pct", "filed_right_pct"])
        for r in rows:
            for k, p in enumerate(r["points"]):
                w.writerow([r["persona"], r["seed"], r["strategy"], k,
                            "%.4f" % p["misPct"], "%.4f" % (p["accuracy"] * 100)])
    with open(os.path.join(outdir, "summary.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["persona", "strategy", "runs", "fastest_on", "day_one_wrong_pot_pct", "share_reaching_target",
                    "median_checks_to_target", "median_wrong_pot_pct_after_10", "median_wrong_pot_pct_at_end"])
        for s in summary:
            w.writerow([s["persona"], s["strategy"], s["runs"], "%.2f" % s["wins"], "%.2f" % s["dayOne"],
                        "%.3f" % s["reachedShare"],
                        "" if s["medianChecks"] is None else "%g" % s["medianChecks"],
                        "%.2f" % s["curve"][min(10, len(s["curve"]) - 1)][1], "%.2f" % s["curve"][-1][1]])
    report.write_compare_report(os.path.join(outdir, "report.html"), summary, meta)


def format_summary(summary, target, checks):
    lines = []
    current = None
    for s in summary:
        if s["persona"] != current:
            current = s["persona"]
            lines.append("")
            lines.append("%s: on day one a median %.1f%% of spending is in the wrong pot" % (
                M.PERSONAS[current]["label"], s["dayOne"]))
            head = ("Strategy", "fastest", "median checks to", "share reaching", "median after")
            lines.append("  %-30s %10s %18s %16s %14s" % head)
            lines.append("  %-30s %10s %18s %16s %14s" % ("", "on", "%g%% target" % target, "target", "10 checks"))
        med = "not reached" if s["medianChecks"] is None else "%g" % s["medianChecks"]
        wins = report.fmt_count(s["wins"]) + "/" + str(s["runs"])
        lines.append("  %-30s %10s %18s %15.0f%% %13.1f%%" % (
            s["label"], wins, med, s["reachedShare"] * 100, s["curve"][min(10, checks)][1]))
    lines.append("")
    lines.append("  Fastest on: statements where the strategy reached the target in the fewest checks (ties shared).")
    return "\n".join(lines) + "\n"


def cmd_compare(args, out):
    rows, summary = run_batch(args.persona, args.seeds, args.weeks, args.checks, args.target,
                              args.slip / 100, args.weight)
    meta = {"weeks": args.weeks, "seeds": args.seeds, "checks": args.checks, "target": args.target,
            "slip": args.slip, "weight": args.weight}
    out.write("Replayed 5 strategies on %s per person, %d weeks each, up to %d checks.\n" % (
        report.plural(len(args.seeds), "statement"), args.weeks, args.checks))
    out.write(format_summary(summary, args.target, args.checks))
    if args.out:
        write_batch(rows, summary, args.out, meta)
        out.write("\nWrote curves.csv, summary.csv and report.html to %s\n" % args.out)
    return 0


# ---------- weekly ----------

def run_weekly_batch(personas, seeds, weeks, per_week, slip, weight):
    rows = []
    for pid in personas:
        for seed in seeds:
            st = M.generate_statement(pid, weeks, seed)
            for r in M.compare_weekly(st, per_week=per_week, slip=slip, weight=weight):
                for m in r["months"]:
                    rows.append({"persona": pid, "seed": seed, "strategy": r["strategy"], "label": r["label"],
                                 "month": m["month"], "name": m["name"], "partial": m["partial"],
                                 "misPct": m["misPct"], "checks": m["checks"], "n": m["n"]})
    return rows


def format_weekly(rows, personas, per_week):
    lines = []
    for pid in personas:
        mine = [r for r in rows if r["persona"] == pid]
        months = []
        for r in mine:
            if (r["month"], r["name"], r["partial"]) not in months:
                months.append((r["month"], r["name"], r["partial"]))
        p = M.PERSONAS[pid]
        lines.append("")
        lines.append("%s, %d check%s a week (median %% of each month's spending in the wrong pot)" % (
            p["label"], per_week, "" if per_week == 1 else "s"))
        if p.get("change"):
            lines.append("  Habits change in week %d: %s." % (p["change"]["week"] + 1, p["change"]["text"]))
        header = "  %-30s" % "Checks chosen by" + "".join(
            "%10s" % (name + ("*" if partial else "")) for _, name, partial in months)
        lines.append(header)
        for sid, label in [("none", "Never checks")] + [(s["id"], s["label"]) for s in M.STRATEGIES]:
            cells = []
            for key, _, _ in months:
                # a part month with no payments says nothing about the app, so it is left out
                vals = [r["misPct"] for r in mine if r["strategy"] == sid and r["month"] == key and r["n"] > 0]
                cells.append("%10s" % "-" if not vals else "%9.1f%%" % M.quantile(vals, 0.5))
            lines.append("  %-30s" % label + "".join(cells))
    lines.append("")
    lines.append("  * part month: the statement starts or ends partway through it.")
    return "\n".join(lines) + "\n"


def cmd_weekly(args, out):
    rows = run_weekly_batch(args.persona, args.seeds, args.weeks, args.per_week, args.slip / 100, args.weight)
    out.write("Each Sunday the person answers up to %s about that week's payments; %s per person, %d weeks each.\n" % (
        report.plural(args.per_week, "check"), report.plural(len(args.seeds), "statement"), args.weeks))
    out.write(format_weekly(rows, args.persona, args.per_week))
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["persona", "seed", "strategy", "month", "part_month", "payments", "wrong_pot_pct",
                        "checks_so_far"])
            for r in rows:
                w.writerow([r["persona"], r["seed"], r["strategy"], r["month"], "yes" if r["partial"] else "no",
                            r["n"], "%.4f" % r["misPct"] if r["n"] > 0 else "", r["checks"]])
        out.write("\nWrote %s\n" % args.out)
    return 0


# ---------- categorise ----------

def _parse_date(text):
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("could not read the date %r (use YYYY-MM-DD or DD/MM/YYYY)" % text)


def _parse_amount(text):
    cleaned = text.strip().replace("£", "").replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1]
    value = abs(float(cleaned))
    return int(value * 100 + 0.5)


def read_statement_csv(path):
    """Read date, description, amount and an optional category column into a statement."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("the file is empty")
        cols = {name.strip().lower(): name for name in reader.fieldnames if name}
        missing = [c for c in ("date", "description", "amount") if c not in cols]
        if missing:
            raise ValueError("missing column(s): %s" % ", ".join(missing))
        lookup = {c.lower(): i for i, c in enumerate(M.CATS)}
        tx = []
        for line_no, row in enumerate(reader, start=2):
            desc = (row.get(cols["description"]) or "").strip()
            if not desc:
                continue
            try:
                d = _parse_date(row.get(cols["date"]) or "")
                pennies = _parse_amount(row.get(cols["amount"]) or "")
            except ValueError as exc:
                raise ValueError("line %d: %s" % (line_no, exc))
            cat = -1
            if "category" in cols:
                raw = (row.get(cols["category"]) or "").strip()
                if raw:
                    if raw.lower() not in lookup:
                        raise ValueError("line %d: unknown category %r (use one of: %s)" % (
                            line_no, raw, ", ".join(M.CATS)))
                    cat = lookup[raw.lower()]
            tx.append({"id": len(tx), "day": len(tx), "wd": d.weekday(), "date": d.isoformat(),
                       "month": d.isoformat()[:7], "desc": desc, "pennies": pennies, "cat": cat,
                       "merchant": ""})
    if not tx:
        raise ValueError("no payments found")
    return {"persona": "csv", "weeks": 0, "seed": 1, "tx": tx}


def cmd_categorise(args, out):
    try:
        st = read_statement_csv(args.input)
    except (OSError, ValueError) as exc:
        out.write("Could not read %s: %s\n" % (args.input, exc))
        return 2
    labelled = [t for t, tx in enumerate(st["tx"]) if tx["cat"] >= 0]
    if args.replay:
        if len(labelled) != len(st["tx"]):
            out.write("--replay needs a category on every row (%d of %d have one).\n" % (
                len(labelled), len(st["tx"])))
            return 2
        st["seed"] = args.seed
        results = M.compare_strategies(st, checks=args.checks, target=args.target,
                                       slip=args.slip / 100, weight=args.weight)
        day1 = results[0]["points"][0]
        bands = M.confidence_bands(M.Session(st, weight=args.weight))
        figures = (day1["accuracy"] * 100, len(st["tx"]), day1["misPct"])
        out.write("Day one: the generic model files %.0f%% of your %d payments correctly; "
                  "%.1f%% of your spending is in the wrong pot.\n" % figures)
        if bands["wrongP"] > 0:
            out.write("Of the %s in misfiled payments, %.0f%% was filed with at least 80%% confidence.\n" % (
                _pounds(bands["wrongP"]), bands["sureShare"] * 100))
        for r in results:
            if r["toTarget"] is None:
                to = "never under %g%%" % args.target
            else:
                to = "under %g%% after %d check%s" % (args.target, r["toTarget"], "" if r["toTarget"] == 1 else "s")
            out.write("  %-30s %-28s %.1f%% after %d\n" % (
                r["label"], to + ";", r["points"][-1]["misPct"], len(r["points"]) - 1))
        if args.output:
            report.write_replay_report(args.output, results, {"target": args.target, "n": len(st["tx"]),
                                                              "file": os.path.basename(args.input)})
            out.write("Wrote %s\n" % args.output)
        return 0

    session = M.Session(st, weight=args.weight)
    day_one = list(session.model.pred)
    for t in labelled:
        session.correct(t, st["tx"][t]["cat"])
    output = args.output or "categorised.csv"
    with open(output, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "description", "amount", "pot", "source", "app_confidence", "app_day_one_guess"])
        for t, tx in enumerate(st["tx"]):
            source = "you" if tx["cat"] >= 0 else "app"
            conf = "" if source == "you" else "%.2f" % session.model.conf[t]
            w.writerow([tx["date"], tx["desc"], _money(tx["pennies"]), M.CATS[session.reported(t)], source, conf,
                        M.CATS[day_one[t]]])
    totals = [0] * M.C
    for t, tx in enumerate(st["tx"]):
        totals[session.reported(t)] += tx["pennies"]
    out.write("Read %d payments (%d with your own category). Wrote %s\n" % (len(st["tx"]), len(labelled), output))
    if labelled:
        agree = sum(1 for t in labelled if day_one[t] == st["tx"][t]["cat"])
        out.write("Before learning from you, the generic model agreed with %d of your %d labels.\n" % (
            agree, len(labelled)))
    unsure = sum(1 for t in range(len(st["tx"])) if st["tx"][t]["cat"] < 0 and session.model.conf[t] < 0.5)
    out.write("Payments the app is unsure about (under 50%%): %d\n" % unsure)
    out.write("Pots:\n")
    for c, name in enumerate(M.CATS):
        out.write("  %-14s %12s\n" % (name, _pounds(totals[c])))
    return 0


# ---------- entry point ----------

def build_parser():
    p = argparse.ArgumentParser(prog="python -m mislabelled",
                                description="How wrong is a budgeting app's AI, and which corrections fix it fastest? "
                                            "Invented data; educational, not financial advice.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sample", help="write an invented, fully labelled statement as CSV")
    s.add_argument("--persona", choices=list(M.PERSONAS), default="student")
    s.add_argument("--weeks", type=int, default=13)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("-o", "--output", default="sample.csv")

    c = sub.add_parser("compare", help="replay the five strategies over many invented statements")
    c.add_argument("--persona", type=_personas, default=_personas("all"),
                   help="student, graduate, sixthformer, a comma list, or all (default)")
    c.add_argument("--seeds", type=_seed_list, default=_seed_list("20"),
                   help="'20' for seeds 1-20, '5-9', or '3,7,11' (default 20)")
    c.add_argument("--weeks", type=int, default=13)
    c.add_argument("--checks", type=int, default=60)
    c.add_argument("--target", type=float, default=5.0, help="target %% of spending in the wrong pot")
    c.add_argument("--slip", type=float, default=0.0, help="%% of corrections filed in the wrong pot")
    c.add_argument("--weight", type=int, default=M.DATA["model"]["weight"])
    c.add_argument("--out", help="folder for curves.csv, summary.csv and report.html")
    c.add_argument("--settings", help="a file saved by the browser app; its settings become the defaults")

    k = sub.add_parser("weekly", help="a few checks each week: how each month looks as the app learns")
    k.add_argument("--persona", type=_personas, default=_personas("all"))
    k.add_argument("--seeds", type=_seed_list, default=_seed_list("20"))
    k.add_argument("--weeks", type=int, default=13)
    k.add_argument("--per-week", type=int, default=3, help="checks answered each Sunday (default 3)")
    k.add_argument("--slip", type=float, default=0.0)
    k.add_argument("--weight", type=int, default=M.DATA["model"]["weight"])
    k.add_argument("--out", help="CSV file for every month of every run")
    k.add_argument("--settings", help="a file saved by the browser app; its settings become the defaults")

    g = sub.add_parser("categorise", help="run the app's model on your own CSV (date, description, amount, category)")
    g.add_argument("input")
    g.add_argument("-o", "--output", help="output CSV (or HTML report with --replay)")
    g.add_argument("--weight", type=int, default=M.DATA["model"]["weight"])
    g.add_argument("--replay", action="store_true",
                   help="every row has a category: replay the five strategies on your statement")
    g.add_argument("--checks", type=int, default=60)
    g.add_argument("--target", type=float, default=5.0)
    g.add_argument("--slip", type=float, default=0.0)
    g.add_argument("--seed", type=int, default=1, help="seed for the random strategy")
    p.subcommands = {"sample": s, "compare": c, "weekly": k, "categorise": g}
    return p


def _check_ranges(args):
    for name, lo, hi in (("weeks", 1, 52), ("checks", 1, 2000), ("weight", 1, 1000), ("per_week", 0, 500)):
        if hasattr(args, name) and not lo <= getattr(args, name) <= hi:
            return "--%s must be between %d and %d" % (name.replace("_", "-"), lo, hi)
    if hasattr(args, "slip") and not 0 <= args.slip <= 100:
        return "--slip must be between 0 and 100"
    if hasattr(args, "target") and not 0 <= args.target <= 100:
        return "--target must be between 0 and 100"
    return None


SETTING_FLAGS = {"weeks": "weeks", "weight": "weight", "target": "target", "checks": "checks", "slip": "slip",
                 "perweek": "per_week"}


def load_settings(path):
    """Read a file saved by the browser app ('Save file') and return its settings."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("app") != "mislabelled" or not isinstance(data.get("settings"), dict):
        raise ValueError("not a file saved by Mislabelled")
    return data["settings"]


def apply_settings(parser, argv, command):
    """Use the app's saved settings as defaults; anything typed on the command line still wins."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--settings")
    known, _ = pre.parse_known_args(argv)
    if not known.settings:
        return
    try:
        settings = load_settings(known.settings)
    except (OSError, ValueError) as exc:
        parser.error("could not read --settings: %s" % exc)
    sub = parser.subcommands[command]
    defaults = {}
    if settings.get("persona") in M.PERSONAS:
        defaults["persona"] = [settings["persona"]]
    for key, dest in SETTING_FLAGS.items():
        if key in settings and isinstance(settings[key], (int, float)) and not isinstance(settings[key], bool):
            defaults[dest] = settings[key]
    sub.set_defaults(**defaults)


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("compare", "weekly"):
        apply_settings(parser, argv[1:], argv[0])
    args = parser.parse_args(argv)
    problem = _check_ranges(args)
    if problem:
        parser.error(problem)
    if args.command == "sample":
        return cmd_sample(args, out)
    if args.command == "compare":
        return cmd_compare(args, out)
    if args.command == "weekly":
        return cmd_weekly(args, out)
    return cmd_categorise(args, out)
