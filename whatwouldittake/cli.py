"""Command-line companion: explain one applicant, write routes and notices for
a whole CSV of applicants, audit recourse burden across a cohort, and check
whether routes survive retraining.

Run from the repository root:
    python3 -m whatwouldittake --help
"""

import argparse
import csv
import json
import math
import os
import re
import sys

from . import model as M

DEGREE_NAMES = {"third": 1, "2:2": 2, "2:1": 3, "first": 4}
GROUP_NAMES = ["Others", "First in family at university"]


class World:
    """The trained model and everything derived from it, built once."""

    def __init__(self):
        self.train = M.generate_cohort(M.DEFAULTS["nTrain"], M.DEFAULTS["trainSeed"])
        self.model = M.train_model(self.train)
        self.tables = M.cost_tables(self.train)
        self.background = M.background_sample(self.train, 64)
        self.prep = M.shapley_prep(self.model, self.background)


def feature_index(name):
    for j, f in enumerate(M.FEATURES):
        if name.strip().lower() in (f["key"], f["short"].lower()):
            return j
    raise SystemExit("Unknown feature '%s'. Use one of: %s" % (name, ", ".join(f["key"] for f in M.FEATURES)))


def whole_number(text):
    """The whole number in text, or None if it is not one (so 2.5, nan and inf are refused)."""
    try:
        v = float(str(text).strip())
    except ValueError:
        return None
    if not math.isfinite(v) or not v.is_integer():
        return None
    return int(v)


def parse_degree(text):
    t = str(text).strip().lower()
    if t in DEGREE_NAMES:
        return DEGREE_NAMES[t]
    v = whole_number(t)
    if v is None or not 1 <= v <= 4:
        raise SystemExit("Degree must be First, 2:1, 2:2, Third or a whole number from 1 (Third) to 4 (First), not '%s'" % text)
    return v


def parse_value(j, text):
    f = M.FEATURES[j]
    if f["key"] == "degree":
        return parse_degree(text)
    v = whole_number(text)
    if v is None:
        raise SystemExit("%s must be a whole number, not '%s'" % (f["label"], text))
    if not f["min"] <= v <= f["max"]:
        raise SystemExit("%s must be between %d and %d, not %d" % (f["label"], f["min"], f["max"], v))
    return v


def load_setup(path):
    """Read a setup file saved by the browser app (or by --save-setup)."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except OSError as e:
        raise SystemExit("Cannot open %s: %s" % (path, e))
    except ValueError:
        raise SystemExit("%s is not valid JSON" % path)
    try:
        return M.parse_setup(obj)
    except M.SetupError as e:
        raise SystemExit("%s: %s" % (path, e))


def resolve(args):
    """Rules, margin, lever limit and retrain settings: the setup file first, then any flags."""
    setup = load_setup(args.setup) if getattr(args, "setup", None) else None
    settings = settings_from_args(args, setup["settings"] if setup else None)
    margin = args.margin if args.margin is not None else (setup["margin"] if setup else 0)
    max_levers = args.max_levers if args.max_levers is not None else (setup["maxLevers"] if setup else M.D)
    if max_levers < 1:
        raise SystemExit("--max-levers must be at least 1")
    if not 0 <= margin <= 0.5:
        raise SystemExit("--margin must be from 0 to 0.5")
    return {"setup": setup, "settings": settings, "margin": margin, "maxLevers": max_levers,
            "points": setup["points"] if setup else 0, "retrain": setup["retrain"] if setup else 1}


def settings_from_args(args, base=None):
    settings = [dict(s) for s in base] if base else M.default_settings()
    for name in args.allow or []:
        settings[feature_index(name)]["actionable"] = True
    for name in args.fix or []:
        settings[feature_index(name)]["actionable"] = False
    for item in args.cap or []:
        name, _, val = item.partition("=")
        j = feature_index(name)
        try:
            cap = int(val)
        except ValueError:
            raise SystemExit("--cap needs feature=number, for example test=15")
        span = M.FEATURES[j]["max"] - M.FEATURES[j]["min"]
        if not 0 <= cap <= span:
            raise SystemExit("--cap for %s must be from 0 to %d" % (M.FEATURES[j]["key"], span))
        settings[j]["cap"] = cap
    for item in args.weight or []:
        name, _, val = item.partition("=")
        j = feature_index(name)
        try:
            w = float(val)
        except ValueError:
            raise SystemExit("--weight needs feature=number, for example experience=2")
        if not 0 < w <= 10:
            raise SystemExit("Effort weights must be above 0 and at most 10")
        settings[j]["weight"] = w
    return settings


def fmt_value(j, v):
    f = M.FEATURES[j]
    if "levels" in f:
        return f["levels"][v - f["min"]]
    unit = f["unit"]
    if v == 1 and unit.endswith("s"):
        unit = unit[:-1]
    return "%d %s" % (v, unit) if unit else str(v)


def fmt_score(s):
    """Two decimals, except that a score just under the line never shows as 0.50."""
    if s < 0:
        return "below 0"
    if s < M.THRESHOLD and "%.2f" % s == "%.2f" % M.THRESHOLD:
        return "%.3f" % (math.floor(s * 1000) / 1000)
    return "%.2f" % s


def describe_changes(plan):
    return "; ".join("%s %s to %s" % (M.FEATURES[c["j"]]["short"], fmt_value(c["j"], c["from"]), fmt_value(c["j"], c["to"]))
                     for c in plan["changes"])


def explain_one(world, x, settings, margin=0.0, max_levers=M.D):
    score = M.predict(world.model, x)
    sh = M.shapley(world.model, x, world.background, world.prep)
    res = M.recourse_options(world.model, world.tables, x, settings, margin=margin, max_levers=max_levers)
    return score, sh, res


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def change_phrase(j, frm, to):
    key = M.FEATURES[j]["key"]
    if key == "test":
        return "an aptitude test score of %d instead of %d" % (to, frm)
    if key == "experience":
        return "%s of relevant work experience instead of %d" % (plural(to, "month"), frm)
    if key == "projects":
        return "%s or leadership role%s instead of %d" % (plural(to, "project"), "" if to == 1 else "s", frm)
    if key == "certs":
        return "%s instead of %d" % (plural(to, "professional certificate"), frm)
    if key == "degree":
        lv = M.FEATURES[j]["levels"]
        return "a %s instead of a %s" % (lv[to - 1], lv[frm - 1])
    return "a gap of %s since last study or work instead of %d" % (plural(to, "month"), frm)


def changes_sentence(plan):
    return ", and ".join(change_phrase(c["j"], c["from"], c["to"]) for c in plan["changes"])


def notice_text(x, score, sh, res, settings, margin, next_model):
    """The plain-English notice an applicant would receive (same wording as the app)."""
    L = []
    yes = score >= M.THRESHOLD
    L.append("Outcome: %s. The screening model gave a score of %s; 0.50 or more is needed."
             % ("shortlisted" if yes else "not shortlisted", fmt_score(score)))
    L.append("")
    phi = sh["phi"]
    if not yes:
        order = sorted(range(M.D), key=lambda j: (phi[j], j))
        against = [j for j in order if phi[j] <= -0.01][:3]
        if against:
            L.append("What counted most against the application, compared with a typical applicant:")
            for j in against:
                L.append("- %s (%s) lowered the score by %.2f.%s" % (M.FEATURES[j]["label"], fmt_value(j, x[j]), -phi[j],
                                                                     "" if settings[j]["actionable"] else " This cannot be changed now."))
        else:
            L.append("No single factor stood out: this application scored close to a typical applicant, "
                     "and a typical applicant is not shortlisted.")
        L.append("")
        if res["options"]:
            L.append("What would have changed the outcome (the smallest realistic changes under the current rules):")
            for k, o in enumerate(res["options"]):
                L.append("- Route %s: %s." % (chr(65 + k), changes_sentence(o)))
            kept = sum(1 for o in res["options"] if M.predict(next_model, o["values"]) >= next_model["threshold"])
            L.append("")
            L.append("How firm this is: these routes are worked out on this year\u2019s model%s. Checked against next "
                     "year\u2019s retrained model, %d of %d would still be enough."
                     % (", aiming %g above the line" % margin if margin else ", aiming just over the line", kept, len(res["options"])))
        else:
            L.append("No change allowed under the current rules would have changed the outcome.")
    else:
        order = sorted(range(M.D), key=lambda j: (-phi[j], j))
        for_it = [j for j in order if phi[j] >= 0.01][:3]
        if for_it:
            L.append("What counted most in favour, compared with a typical applicant:")
            for j in for_it:
                L.append("- %s (%s) raised the score by %.2f." % (M.FEATURES[j]["label"], fmt_value(j, x[j]), phi[j]))
    L.append("")
    L.append("You can ask for a person to review this decision and to correct any information that is wrong.")
    return "\n".join(L)


def cmd_explain(args):
    cfg = resolve(args)
    settings = cfg["settings"]
    if args.preset:
        match = [p for p in M.PRESETS if p["name"].lower() == args.preset.strip().lower()]
        if not match:
            raise SystemExit("Unknown example '%s'. Choose from: %s" % (args.preset, "; ".join(p["name"] for p in M.PRESETS)))
        x = list(match[0]["x"])
    elif cfg["setup"]:
        x = list(cfg["setup"]["x"])
    else:
        x = [None] * M.D
    for j, f in enumerate(M.FEATURES):
        given = getattr(args, f["key"])
        if given is not None:
            x[j] = parse_value(j, given)
        elif x[j] is None:
            raise SystemExit("Give --%s (or start from an example with --preset or a saved --setup)" % f["key"])
    world = World()
    score, sh, res = explain_one(world, x, settings, cfg["margin"], cfg["maxLevers"])
    if args.save_setup:
        with open(args.save_setup, "w", encoding="utf-8") as fh:
            json.dump(M.make_setup(x, settings, cfg["maxLevers"], cfg["margin"], cfg["points"], cfg["retrain"]), fh, indent=2)
            fh.write("\n")
    out = []
    out.append("Applicant: " + ", ".join("%s %s" % (f["short"], fmt_value(j, x[j])) for j, f in enumerate(M.FEATURES)))
    out.append("Decision:  %s (score %s; %.2f needed)" % ("Shortlisted" if score >= world.model["threshold"] else "Not shortlisted",
                                                     fmt_score(score), world.model["threshold"]))
    out.append("")
    out.append("Why the model scored them this way (exact Shapley values, reference average %.2f):" % sh["base"])
    order = sorted(range(M.D), key=lambda j: -abs(sh["phi"][j]))
    for j in order:
        fixed = "" if settings[j]["actionable"] else "  (fixed)"
        out.append("  %-13s %+.3f%s" % (M.FEATURES[j]["short"], sh["phi"][j], fixed))
    out.append("")
    if res["status"] == "already":
        out.append("Already shortlisted: nothing to change.")
    elif not res["options"]:
        out.append("No route within these limits.")
    else:
        out.append("Ways to get shortlisted (effort in percentile points):")
        for k, o in enumerate(res["options"]):
            out.append("  Route %s  effort %5.1f  new score %s  %s" % (chr(65 + k), o["cost"], fmt_score(o["score"]), describe_changes(o)))
    if args.notice:
        nxt = M.next_model(cfg["points"] / 6, cfg["retrain"])
        out += ["", "Notice to the applicant:", "", notice_text(x, score, sh, res, settings, cfg["margin"], nxt)]
    if args.save_setup:
        out += ["", "Saved the setup to " + args.save_setup]
    print("\n".join(out))
    return 0


def read_applicants(path):
    try:
        fh = open(path, newline="", encoding="utf-8-sig")
    except OSError as e:
        raise SystemExit("Cannot open %s: %s" % (path, e))
    with fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise SystemExit("%s is empty" % path)
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        missing = [f["key"] for f in M.FEATURES if f["key"] not in cols]
        if missing:
            raise SystemExit("%s is missing column(s): %s" % (path, ", ".join(missing)))
        people = []
        for n, row in enumerate(reader, start=2):
            try:
                x = [parse_value(j, row[cols[f["key"]]]) for j, f in enumerate(M.FEATURES)]
            except SystemExit as e:
                raise SystemExit("%s line %d: %s" % (path, n, e))
            pid = row[cols["id"]] if "id" in cols else str(n - 1)
            g = None
            if "first_in_family" in cols:
                g = 1 if str(row[cols["first_in_family"]]).strip().lower() in ("1", "yes", "y", "true") else 0
            people.append({"id": pid, "x": x, "g": g})
    if not people:
        raise SystemExit("%s has a header but no applicants" % path)
    return people


def safe_name(text, used):
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text)).strip("_") or "applicant"
    name, n = base, 2
    while name.lower() in used:  # some file systems ignore case
        name = "%s_%d" % (base, n)
        n += 1
    used.add(name.lower())
    return name


def cmd_plans(args):
    cfg = resolve(args)
    settings = cfg["settings"]
    people = read_applicants(args.csv)
    world = World()
    nxt = M.next_model(cfg["points"] / 6, cfg["retrain"]) if args.notices else None
    if args.notices:
        os.makedirs(args.notices, exist_ok=True)
    used = set()
    fields = ["id", "score", "decision", "biggest_drag", "drag_value", "drag_fixed", "route_status", "routes",
              "cheapest_effort", "cheapest_changes", "cheapest_new_score"]
    rows = []
    for p in people:
        score, sh, res = explain_one(world, p["x"], settings, cfg["margin"], cfg["maxLevers"])
        worst = M.biggest_drag(sh["phi"])
        if args.notices:
            with open(os.path.join(args.notices, safe_name(p["id"], used) + ".txt"), "w", encoding="utf-8") as fh:
                fh.write(notice_text(p["x"], score, sh, res, settings, cfg["margin"], nxt) + "\n")
        row = {"id": p["id"], "score": "%.4f" % score,
               "decision": "shortlisted" if score >= world.model["threshold"] else "not shortlisted",
               "biggest_drag": M.FEATURES[worst]["short"] if worst >= 0 else "",
               "drag_value": "%.4f" % sh["phi"][worst] if worst >= 0 else "",
               "drag_fixed": ("yes" if not settings[worst]["actionable"] else "no") if worst >= 0 else "",
               "route_status": res["status"] if res["status"] != "found" or res["options"] else "none",
               "routes": len(res["options"]), "cheapest_effort": "", "cheapest_changes": "", "cheapest_new_score": ""}
        if res["options"]:
            best = res["options"][0]
            row["cheapest_effort"] = "%.2f" % best["cost"]
            row["cheapest_changes"] = describe_changes(best)
            row["cheapest_new_score"] = "%.4f" % best["score"]
        rows.append(row)
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    finally:
        if args.out:
            out.close()
    if args.out:
        rejected = sum(1 for r in rows if r["decision"] != "shortlisted")
        routed = sum(1 for r in rows if r["routes"])
        print("Wrote %d applicants to %s: %d not shortlisted, %d of them with a route." % (len(rows), args.out, rejected, routed))
    if args.notices:
        # Keep stdout clean when the CSV itself goes there.
        print("Wrote %d notices to %s" % (len(rows), args.notices), file=sys.stdout if args.out else sys.stderr)
    return 0


def pct(v):
    """Whole percentages rounded half up, like the browser app."""
    return "n/a" if v is None else "%d%%" % math.floor(v * 100 + 0.5)


def audit_markdown(a, gap, settings, title):
    lines = ["# " + title, ""]
    lines.append("Rules: " + "; ".join(
        "%s %s" % (f["short"], ("up to %s%d, weight %g" % ("+" if f["dir"] > 0 else "-", settings[j]["cap"], settings[j]["weight"]))
                   if settings[j]["actionable"] else "fixed") for j, f in enumerate(M.FEATURES)))
    lines.append("")
    lines.append("| Measure | " + " | ".join(GROUP_NAMES) + " |")
    lines.append("|---|" + "---|" * len(GROUP_NAMES))

    def num(v):
        return "n/a" if v is None else "%.1f" % v

    G = a["groups"]
    lines.append("| Applicants | %d | %d |" % (G[0]["n"], G[1]["n"]))
    lines.append("| Shortlisted | %s | %s |" % (pct(G[0]["shortlistRate"]), pct(G[1]["shortlistRate"])))
    lines.append("| Rejected with a route within the limits | %s | %s |" % (pct(G[0]["feasibleShare"]), pct(G[1]["feasibleShare"])))
    lines.append("| Mean effort of the cheapest route | %s | %s |" % (num(G[0]["meanCost"]), num(G[1]["meanCost"])))
    lines.append("| Median effort of the cheapest route | %s | %s |" % (num(G[0]["medianCost"]), num(G[1]["medianCost"])))
    lines.append("| Average extra months of experience asked for | %s | %s |" % (num(G[0]["meanExpAdded"]), num(G[1]["meanExpAdded"])))
    lines.append("")
    lines.append("Share of cheapest routes that change each feature:")
    lines.append("")
    lines.append("| Feature | " + " | ".join(GROUP_NAMES) + " |")
    lines.append("|---|" + "---|" * len(GROUP_NAMES))
    for j, f in enumerate(M.FEATURES):
        lines.append("| %s | %s | %s |" % (f["short"], pct(G[0]["leverShare"][j]) if G[0]["feasible"] else "n/a",
                                           pct(G[1]["leverShare"][j]) if G[1]["feasible"] else "n/a"))
    lines.append("")
    lines.append("## Explanation versus advice")
    lines.append("")
    lines.append("| Measure | " + " | ".join(GROUP_NAMES) + " |")
    lines.append("|---|" + "---|" * len(GROUP_NAMES))
    lines.append("| Biggest drag (by Shapley value) is something they cannot change | %s | %s |"
                 % (pct(gap[0]["dragFixedShare"]), pct(gap[1]["dragFixedShare"])))
    lines.append("| Cheapest route never touches the biggest drag | %s | %s |"
                 % (pct(gap[0]["mismatchShare"]), pct(gap[1]["mismatchShare"])))
    lines.append("")
    lines.append("Biggest drag (rows) against the feature carrying most of the cheapest route's effort (columns), "
                 "all rejected applicants:")
    lines.append("")
    names = [f["short"] for f in M.FEATURES]
    cols = [j for j in range(M.D) if any(row[j] for row in gap[2]["matrix"])] + [M.D]
    rows = [j for j in range(M.D + 1) if any(gap[2]["matrix"][j])]
    lines.append("| Biggest drag | " + " | ".join("No route" if c == M.D else names[c] for c in cols) + " |")
    lines.append("|---|" + "---|" * len(cols))
    for r in rows:
        label = "None (average is below the line)" if r == M.D else names[r] + ("" if settings[r]["actionable"] else " (fixed)")
        lines.append("| %s | %s |" % (label, " | ".join(str(gap[2]["matrix"][r][c]) for c in cols)))
    lines.append("")
    return "\n".join(lines)


def cmd_audit(args):
    cfg = resolve(args)
    settings = cfg["settings"]
    if args.csv:
        people = read_applicants(args.csv)
        if any(p["g"] is None for p in people):
            raise SystemExit("An audit needs a first_in_family column (yes/no) to compare groups")
        cohort = [{"x": p["x"], "g": p["g"]} for p in people]
        title = "Recourse audit of " + args.csv
    else:
        cohort = M.generate_cohort(args.n, args.seed)
        title = "Recourse audit of %d synthetic applicants (seed %d)" % (args.n, args.seed)
    world = World()
    a = M.audit(world.model, world.tables, cohort, settings, margin=cfg["margin"], max_levers=cfg["maxLevers"])
    gap = M.explain_gap(world.model, cohort, a["rows"], world.background, settings, world.prep)
    text = audit_markdown(a, gap, settings, title)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("Wrote " + args.out)
    else:
        print(text)
    return 0


def hold_analysis(world, cohort, settings, points_list, retrains, max_levers=M.D):
    """Check every rejected applicant's cheapest route against many retrained models."""
    table = M.route_table(world.model, world.tables, cohort, settings, M.MARGINS, max_levers=max_levers)
    results = []
    for points in points_list:
        runs = [M.hold_summary(M.next_model(points / 6, r), cohort, table, M.MARGINS) for r in range(1, retrains + 1)]
        rows = []
        for k, m in enumerate(M.MARGINS):
            kept = [run[k]["all"]["keptShare"] for run in runs if run[k]["all"]["keptShare"] is not None]
            by_group = []
            for g in (0, 1):
                vals = [run[k]["groups"][g]["keptShare"] for run in runs if run[k]["groups"][g]["keptShare"] is not None]
                by_group.append(M.mean(vals))
            first = runs[0][k]["all"]
            rows.append({"margin": m, "routeShare": first["routeShare"], "medianCost": first["medianCost"],
                         "keptMean": M.mean(kept), "keptMin": min(kept) if kept else None,
                         "keptMax": max(kept) if kept else None, "keptGroups": by_group})
        results.append({"points": points, "rows": rows, "runs": runs})
    return results


def hold_markdown(results, retrains, target, title):
    lines = ["# " + title, ""]
    lines.append("Each rejected applicant's cheapest route is checked against %d retrained models (fresh samples of "
                 "1,600 applicants, same 38%% quota). A safety margin makes routes aim above 0.50." % retrains)
    for res in results:
        p = res["points"]
        pool = "a fresh sample of the same kind of pool" if p == 0 else \
            "+%g test point%s and +%g month%s of experience on average" % (p, "" if p == 1 else "s", p / 2, "" if p == 2 else "s")
        lines += ["", "## Next year's applicants: %s" % pool, ""]
        lines.append("| Safety margin | Rejected with a route | Median effort | Still working (mean) | Lowest | Highest | "
                     + " | ".join(GROUP_NAMES) + " |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in res["rows"]:
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                "None" if r["margin"] == 0 else "+%g" % r["margin"], pct(r["routeShare"]),
                "n/a" if r["medianCost"] is None else "%.1f" % r["medianCost"], pct(r["keptMean"]), pct(r["keptMin"]),
                pct(r["keptMax"]), pct(r["keptGroups"][0]), pct(r["keptGroups"][1])))
        lines.append("")
        if all(not r["routeShare"] for r in res["rows"]):
            lines.append("- No rejected applicant has a route under these rules, so there is nothing to check.")
            continue
        on_average = [r for r in res["rows"] if r["keptMean"] is not None and r["keptMean"] >= target]
        worst_case = [r for r in res["rows"] if r["keptMin"] is not None and r["keptMin"] >= target]
        if on_average:
            r = on_average[0]
            lines.append("- Smallest margin keeping %s of routes on average: **+%g**, at a median effort of %.1f "
                         "(%+.1f on no margin) and leaving %s of rejected applicants with no route."
                         % (pct(target), r["margin"], r["medianCost"], r["medianCost"] - res["rows"][0]["medianCost"],
                            pct(1 - r["routeShare"])))
        else:
            lines.append("- No margin up to +%g keeps %s of routes on average." % (M.MARGINS[-1], pct(target)))
        if worst_case:
            lines.append("- Smallest margin keeping %s even in the worst of the %d retrains: **+%g**."
                         % (pct(target), retrains, worst_case[0]["margin"]))
        else:
            lines.append("- No margin keeps %s in every one of the %d retrains." % (pct(target), retrains))
    lines.append("")
    return "\n".join(lines)


def cmd_hold(args):
    if args.retrains < 1 or args.retrains > 200:
        raise SystemExit("--retrains must be between 1 and 200")
    if not 0 < args.target <= 1:
        raise SystemExit("--target must be above 0 and at most 1")
    for p in args.points:
        if not 0 <= p <= 6:
            raise SystemExit("--points must be between 0 and 6")
    cfg = resolve(args)
    settings = cfg["settings"]
    world = World()
    if args.csv:
        people = read_applicants(args.csv)
        cohort = [{"x": p["x"], "g": p["g"] if p["g"] is not None else 0} for p in people]
        title = "Will the routes hold? %s" % args.csv
        if any(p["g"] is None for p in people):
            title += " (no first_in_family column, so everyone is counted under Others)"
    else:
        cohort = M.generate_cohort(M.DEFAULTS["nAudit"], M.DEFAULTS["auditSeed"])
        title = "Will the routes hold? %d synthetic applicants" % len(cohort)
    results = hold_analysis(world, cohort, settings, args.points, args.retrains, max_levers=cfg["maxLevers"])
    text = hold_markdown(results, args.retrains, args.target, title)
    if args.raw:
        with open(args.raw, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["points", "retrain", "margin", "group", "rejected", "routes", "kept", "kept_share", "median_effort"])
            for res in results:
                for r, run in enumerate(res["runs"], start=1):
                    for row in run:
                        for name, part in (("all", row["all"]), ("others", row["groups"][0]),
                                           ("first_in_family", row["groups"][1])):
                            w.writerow([res["points"], r, row["margin"], name, part["rejected"], part["routes"], part["kept"],
                                        "" if part["keptShare"] is None else "%.4f" % part["keptShare"],
                                        "" if part["medianCost"] is None else "%.2f" % part["medianCost"]])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("Wrote " + args.out + (" and " + args.raw if args.raw else ""))
    else:
        print(text)
    return 0


def cmd_sample(args):
    rows = M.generate_cohort(args.n, args.seed)
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        w = csv.writer(out)
        w.writerow(["id"] + [f["key"] for f in M.FEATURES] + ["first_in_family"])
        for i, r in enumerate(rows):
            w.writerow(["A%03d" % (i + 1)] + r["x"] + ["yes" if r["g"] else "no"])
    finally:
        if args.out:
            out.close()
    if args.out:
        print("Wrote %d synthetic applicants to %s" % (len(rows), args.out))
    return 0


def add_rules(p):
    g = p.add_argument_group("rules for realistic changes")
    g.add_argument("--allow", action="append", metavar="FEATURE", help="let a normally fixed feature change (degree or gap)")
    g.add_argument("--fix", action="append", metavar="FEATURE", help="stop a feature from changing")
    g.add_argument("--cap", action="append", metavar="FEATURE=N", help="largest change allowed, for example test=15")
    g.add_argument("--weight", action="append", metavar="FEATURE=W", help="effort weight, for example experience=2")
    g.add_argument("--setup", metavar="FILE", help="start from a setup saved by the browser app (flags still win)")
    g.add_argument("--max-levers", type=int, help="most features changed at once (default: no limit)")
    g.add_argument("--margin", type=float, help="extra score above 0.50 a route must reach (default 0)")


def build_parser():
    p = argparse.ArgumentParser(prog="python3 -m whatwouldittake",
                                description="Counterfactual routes to 'yes' for an invented shortlisting model.")
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("explain", help="explain one applicant and list routes to being shortlisted")
    e.add_argument("--preset", help="start from an example applicant, for example \"Near miss\"")
    e.add_argument("--test", help="aptitude test score, 0 to 100")
    e.add_argument("--experience", help="months of relevant work experience, 0 to 36")
    e.add_argument("--projects", help="projects and leadership roles, 0 to 6")
    e.add_argument("--certs", help="professional certificates, 0 to 4")
    e.add_argument("--degree", help="First, 2:1, 2:2 or Third")
    e.add_argument("--gap", help="months since last study or work, 0 to 24")
    e.add_argument("--notice", action="store_true", help="also print the plain-English notice to the applicant")
    e.add_argument("--save-setup", metavar="FILE", help="save the applicant and rules as a setup the browser app can load")
    add_rules(e)
    e.set_defaults(func=cmd_explain)

    pl = sub.add_parser("plans", help="write each applicant's decision, biggest drag and cheapest route to CSV")
    pl.add_argument("csv", help="CSV with columns test, experience, projects, certs, degree, gap (id optional)")
    pl.add_argument("--out", help="output CSV (default: print)")
    pl.add_argument("--notices", metavar="DIR", help="also write one plain-English notice per applicant into this folder")
    add_rules(pl)
    pl.set_defaults(func=cmd_plans)

    a = sub.add_parser("audit", help="compare recourse burden between groups")
    a.add_argument("--csv", help="your own applicants, with a first_in_family column (default: synthetic cohort)")
    a.add_argument("--n", type=int, default=M.DEFAULTS["nAudit"], help="synthetic applicants (default 500)")
    a.add_argument("--seed", type=int, default=M.DEFAULTS["auditSeed"], help="seed for the synthetic cohort (default 29)")
    a.add_argument("--out", help="write the Markdown report here (default: print)")
    add_rules(a)
    a.set_defaults(func=cmd_audit)

    h = sub.add_parser("hold", help="check whether routes survive retraining, by safety margin")
    h.add_argument("--retrains", type=int, default=20, help="retrained models to test against (default 20)")
    h.add_argument("--points", type=float, nargs="+", default=[0.0],
                   help="how much stronger next year's pool is, in average test points from 0 to 6 (default 0)")
    h.add_argument("--target", type=float, default=0.9, help="share of routes that should survive (default 0.9)")
    h.add_argument("--csv", help="your own applicants instead of the synthetic cohort")
    h.add_argument("--out", help="write the Markdown report here (default: print)")
    h.add_argument("--raw", help="also write every retrain's results to this CSV")
    add_rules(h)
    h.set_defaults(func=cmd_hold)

    s = sub.add_parser("sample", help="write synthetic applicants to CSV, to try the other commands")
    s.add_argument("--n", type=int, default=40, help="how many (default 40)")
    s.add_argument("--seed", type=int, default=101, help="seed (default 101)")
    s.add_argument("--out", help="output CSV (default: print)")
    s.set_defaults(func=cmd_sample)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "n", 1) < 1:
        raise SystemExit("--n must be at least 1")
    return args.func(args)
