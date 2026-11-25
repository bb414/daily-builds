"""Command-line companion to the Mislabelled browser app.

    python -m mislabelled sample      write an invented statement as CSV
    python -m mislabelled compare     replay the five strategies over many statements
    python -m mislabelled categorise  run the app's model on your own CSV
"""

import argparse
import csv
import datetime
import os
import sys

from . import model as M
from . import report


def _quantile(values, q):
    """Linear-interpolation quantile (the common 'type 7' definition)."""
    xs = sorted(values)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


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
    return "%.2f" % (pennies / 100)


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
            for res in M.compare_strategies(st, checks=checks, target=target, slip=slip, weight=weight):
                rows.append({"persona": pid, "seed": seed, "strategy": res["strategy"],
                             "points": res["points"], "toTarget": res["toTarget"], "n": len(st["tx"])})
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
                curve.append((_quantile(vals, 0.1), _quantile(vals, 0.5), _quantile(vals, 0.9)))
            med = _quantile(padded, 0.5)
            summary.append({
                "persona": pid,
                "strategy": s["id"],
                "label": s["label"],
                "runs": len(mine),
                "reachedShare": len(reached) / len(mine),
                "medianChecks": None if med > checks else med,
                "dayOne": _quantile([r["points"][0]["misPct"] for r in mine], 0.5),
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
        w.writerow(["persona", "strategy", "runs", "day_one_wrong_pot_pct", "share_reaching_target",
                    "median_checks_to_target", "median_wrong_pot_pct_after_10", "median_wrong_pot_pct_at_end"])
        for s in summary:
            w.writerow([s["persona"], s["strategy"], s["runs"], "%.2f" % s["dayOne"], "%.3f" % s["reachedShare"],
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
            lines.append("%s  (day one: %.1f%% of spending in the wrong pot, median)" % (
                M.PERSONAS[current]["label"], s["dayOne"]))
            lines.append("  %-30s %18s %16s %14s" % ("Strategy", "median checks to", "share reaching", "median after"))
            lines.append("  %-30s %18s %16s %14s" % ("", "%g%% target" % target, "target", "10 checks"))
        med = "not reached" if s["medianChecks"] is None else "%g" % s["medianChecks"]
        lines.append("  %-30s %18s %15.0f%% %13.1f%%" % (
            s["label"], med, s["reachedShare"] * 100, s["curve"][min(10, checks)][1]))
    return "\n".join(lines) + "\n"


def cmd_compare(args, out):
    rows, summary = run_batch(args.persona, args.seeds, args.weeks, args.checks, args.target,
                              args.slip / 100, args.weight)
    meta = {"weeks": args.weeks, "seeds": args.seeds, "checks": args.checks, "target": args.target,
            "slip": args.slip, "weight": args.weight}
    out.write("Replayed 5 strategies on %d statement(s) per person, %d weeks each, up to %d checks.\n" % (
        len(args.seeds), args.weeks, args.checks))
    out.write(format_summary(summary, args.target, args.checks))
    if args.out:
        write_batch(rows, summary, args.out, meta)
        out.write("\nWrote curves.csv, summary.csv and report.html to %s\n" % args.out)
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
        out.write("Day one: the generic model files %.0f%% of your %d payments correctly; "
                  "%.1f%% of your spending is in the wrong pot.\n" % (day1["accuracy"] * 100, len(st["tx"]),
                                                                       day1["misPct"]))
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
        out.write("  %-14s %10s\n" % (name, "£" + _money(totals[c])))
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
    return p


def _check_ranges(args):
    for name, lo, hi in (("weeks", 1, 52), ("checks", 1, 2000), ("weight", 1, 1000)):
        if hasattr(args, name) and not lo <= getattr(args, name) <= hi:
            return "--%s must be between %d and %d" % (name, lo, hi)
    if hasattr(args, "slip") and not 0 <= args.slip <= 100:
        return "--slip must be between 0 and 100"
    if hasattr(args, "target") and not 0 <= args.target <= 100:
        return "--target must be between 0 and 100"
    return None


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    problem = _check_ranges(args)
    if problem:
        parser.error(problem)
    if args.command == "sample":
        return cmd_sample(args, out)
    if args.command == "compare":
        return cmd_compare(args, out)
    return cmd_categorise(args, out)
