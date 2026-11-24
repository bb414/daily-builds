"""Command-line interface: python -m reliance_lab <command> [options]."""

import argparse
import csv
import json
import sys

from . import model
from .experiment import power_curve, run_experiment


def pct(x, dp=0):
    return "n/a" if x is None else "%.*f%%" % (dp, x * 100)


def pts(x):
    return "%+.1f pts" % (x * 100)


def speed(saved):
    v = int(round(abs(saved) * 100))
    if v == 0:
        return "the same as working alone"
    return "%d%% %s than working alone" % (v, "faster" if saved > 0 else "slower")


def parse_sets(pairs):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("--set expects key=value, got %r" % pair)
        key, value = pair.split("=", 1)
        known = [name for name, *_rest in model.PARAMS] + ["workflow", "showConfidence"]
        if key not in known:
            raise SystemExit("Unknown setting %r. Known settings: %s" % (key, ", ".join(known)))
        out[key] = value
    return out


def load_config(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return model.read_settings_file(json.load(fh))
    except OSError as err:
        raise SystemExit("Could not read %s: %s" % (path, err.strerror))
    except json.JSONDecodeError:
        raise SystemExit("%s is not valid JSON" % path)
    except ValueError as err:
        raise SystemExit("%s: %s" % (path, err))


def build_params(args):
    if args.config:
        params = load_config(args.config)
    elif args.preset not in model.PRESETS:
        raise SystemExit("Unknown preset %r. Choose from: %s" % (args.preset, ", ".join(model.PRESETS)))
    else:
        params = model.preset_params(args.preset)
    params.update(parse_sets(args.set))
    if getattr(args, "workflow", None):
        params["workflow"] = args.workflow
    return model.normalise_params(params)


def format_run(a):
    r, c, v = a["result"], a["control"], a["verdict"]
    p = r["params"]
    lines = [
        "Reliance Lab: %s, %d people, %d cases each" % (model.WORKFLOW_LABELS[p["workflow"]], p["people"], p["rounds"]),
        "",
        "Verdict: %s" % v["label"],
        "",
        "  Accuracy with the AI        %s   (working alone: %s, AI alone: %s)" % (
            pct(r["teamAccuracy"], 1), pct(c["teamAccuracy"], 1), pct(r["aiRealisedAccuracy"], 1)),
        "  Own judgement before        %s" % pct(r["skillBefore"], 1),
        "  Own judgement after         %s   (practising without AI: %s)" % (pct(r["skillAfter"], 1), pct(c["skillAfter"], 1)),
        "  Misled by wrong AI advice   %s" % pct(r["misledRate"], 1),
        "  Rescued by right AI advice  %s" % pct(r["rescueRate"], 1),
        "  Accepted without thinking   %s of cases" % pct(r["deferralRate"], 1),
        "  Trust in the AI             %s -> %s" % (pct(r["trustStart"]), pct(r["trustEnd"])),
    ]
    lines.append("  Time per case               %.2f min (%s)" % (r["minutesPerCase"], speed(v["timeSaved"])))
    if v["key"] != "baseline":
        lines += ["", "  Lift versus working alone: %s. Own judgement versus practising alone: %s." % (
            pts(v["lift"]), pts(v["skillGap"]))]
    reasons = model.explain(a)
    if reasons:
        lines += ["", "Why:"] + ["  - " + text for text in reasons]
    sh = r["shock"]
    if sh:
        lines += ["", "Stress test: from case %d the AI is right %s of the time (before: %s)." % (
            sh["at"], pct(sh["aiAfter"]), pct(sh["aiBefore"]))]
        if v["shock"] and p["workflow"] != "none":
            lines.append("  After the change, with the AI: %s; working alone: %s (%s)." % (
                pct(v["shock"]["teamAfter"], 1), pct(v["shock"]["aloneAfter"], 1), pts(v["shock"]["gap"])))
            lines.append("  Followed its wrong answers %s of the time; trust %s -> %s." % (
                pct(sh["misledAfter"]), pct(sh["trustAtShock"]), pct(sh["trustEnd"])))
    return "\n".join(lines)


def format_compare(rows):
    p = rows[0]["result"]["params"]
    lines = [
        "All four workflows, same people and cases (%d people, %d cases each)" % (p["people"], p["rounds"]),
        "",
        "  %-12s %10s %10s %8s %10s  %s" % ("Workflow", "With AI", "Own after", "Misled", "Min/case", "Verdict"),
    ]
    for row in rows:
        r = row["result"]
        lines.append("  %-12s %10s %10s %8s %10.2f  %s" % (
            model.WORKFLOW_LABELS[row["workflow"]], pct(r["teamAccuracy"], 1), pct(r["skillAfter"], 1),
            pct(r["misledRate"]), r["minutesPerCase"], row["verdict"]["label"]))
    if rows[0]["result"]["shock"]:
        lines += ["", "  After the AI gets worse at case %d:" % rows[0]["result"]["shock"]["at"]]
        for row in rows:
            lines.append("  %-12s %10s" % (model.WORKFLOW_LABELS[row["workflow"]], pct(row["result"]["shock"]["teamAfter"], 1)))
    return "\n".join(lines)


def format_experiment(e):
    lines = [
        "Virtual experiment: %d participants per arm, %d-item tests before and after, %d training cases" % (
            e["n"], e["items"], e["params"]["rounds"]),
        "",
        "  %-12s %8s %8s %8s %9s %9s" % ("Arm", "Pre", "Post", "Change", "With AI", "Deferred"),
    ]
    for arm in e["arms"]:
        s = e["summary"][arm]
        lines.append("  %-12s %8s %8s %8s %9s %9s" % (
            model.WORKFLOW_LABELS[arm], pct(s["pre"], 1), pct(s["post"], 1), pts(s["change"]),
            pct(s["withAi"], 1), pct(s["deferral"], 1)))
    lines += ["", "Compared with %s (change in own test score):" % model.WORKFLOW_LABELS[e["control"]]]
    for arm, comp in e["comparisons"].items():
        t = comp["change"]
        lines.append("  %-12s %s (95%% CI %s to %s), d = %.2f, p = %.3f" % (
            model.WORKFLOW_LABELS[arm], pts(t["diff"]), pts(t["low"]), pts(t["high"]), t["d"], t["p"]))
    return "\n".join(lines)


def format_robustness(sens, measure="skillGap"):
    names = {"skillGap": "own judgement versus practising alone", "lift": "accuracy with the AI versus working alone"}
    base = sens["base"]
    if sens["workflow"] == "none":
        return "The comparison group has no verdict to test. Pick a workflow that uses the AI."
    rows = sorted(sens["rows"], key=lambda r: -abs(r["high"][measure] - r["low"][measure]))
    lines = [
        "Robustness check: each assumption moved down and up, one at a time",
        "Measure: %s. Current result %s, verdict %s." % (names[measure], pts(base[measure]),
                                                        model.VERDICTS[base["verdict"]]["label"]),
        "",
        "  %-30s %10s %10s %10s %10s" % ("Assumption", "Lower", "Result", "Higher", "Result"),
    ]
    flips = 0
    for row in rows:
        lo, hi = row["low"], row["high"]
        marks = []
        for end in (lo, hi):
            if end["verdict"] != base["verdict"]:
                flips += 1
                marks.append("%s -> %s" % (end["value"], model.VERDICTS[end["verdict"]]["label"]))
        lines.append(("  %-30s %10s %10s %10s %10s  %s" % (
            model.PARAM_LABELS[row["key"]], "%g" % lo["value"], pts(lo[measure]), "%g" % hi["value"], pts(hi[measure]),
            "; ".join(marks))).rstrip())
    total = 2 * len(rows)
    lines += ["", "The verdict held in %d of %d tests." % (total - flips, total)]
    return "\n".join(lines)


def markdown_experiment(e):
    p = e["params"]
    lines = [
        "# Reliance Lab: virtual experiment",
        "",
        "Synthetic data generated by the Reliance Lab model. Not real participants.",
        "",
        "## Design",
        "",
        "- Participants per arm: %d (different simulated people in each arm)" % e["n"],
        "- Pre-test and post-test without the AI: %d items each" % e["items"],
        "- Training cases with the AI: %d" % p["rounds"],
        "- Starting accuracy %s, AI accuracy %s, feedback on %s of cases, seed %d" % (
            pct(p["humanAccuracy"]), pct(p["aiAccuracy"]), pct(p["feedbackRate"]), p["seed"]),
        "",
        "## Results by arm",
        "",
        "| Arm | Pre-test | Post-test | Change | Accuracy during training | Accepted without thinking |",
        "|---|---|---|---|---|---|",
    ]
    for arm in e["arms"]:
        s = e["summary"][arm]
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            model.WORKFLOW_LABELS[arm], pct(s["pre"], 1), pct(s["post"], 1), pts(s["change"]),
            pct(s["withAi"], 1), pct(s["deferral"], 1)))
    lines += ["", "## Effects compared with %s" % model.WORKFLOW_LABELS[e["control"]], "",
              "| Arm | Measure | Difference | 95% CI | Cohen's d | p |", "|---|---|---|---|---|---|"]
    for arm, comp in e["comparisons"].items():
        for key, name in (("change", "Change in own test score"), ("withAi", "Accuracy during training")):
            t = comp[key]
            lines.append("| %s | %s | %s | %s to %s | %.2f | %.3f |" % (
                model.WORKFLOW_LABELS[arm], name, pts(t["diff"]), pts(t["low"]), pts(t["high"]), t["d"], t["p"]))
    lines += ["", "Welch's t-test on participant-level scores. \"pts\" means percentage points.", ""]
    return "\n".join(lines)


def format_power(pw):
    eff = pw["effect"]
    lines = [
        "Power to detect the effect of %s versus %s on the change in own test score" % (
            model.WORKFLOW_LABELS[pw["arm"]], model.WORKFLOW_LABELS[pw["control"]]),
        "  Effect in a large pool: %s (Cohen's d = %.2f), %d-item tests, %d replications per size" % (
            pts(eff["diff"]), eff["d"], pw["items"], pw["reps"]),
        "",
        "  %-22s %s" % ("Participants per arm", "Power (significant, right direction)"),
    ]
    for row in pw["results"]:
        bar = "#" * int(round(row["rightWay"] * 30))
        lines.append("  %-22d %5s  %s" % (row["n"], pct(row["rightWay"]), bar))
    if pw["needed"] is None:
        lines += ["", "  80% power is not reached at the sizes tested. Try larger --sizes."]
    else:
        lines += ["", "  About %d participants per arm give 80%% power." % pw["needed"]]
    return "\n".join(lines)


def write_csv(e, path):
    fields = ["arm", "participant", "pre", "post", "change", "withAi", "deferral", "trust", "trueBefore", "trueAfter"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for arm in e["arms"]:
            for j, row in enumerate(e["data"][arm]):
                w.writerow([arm, j + 1] + ["%.4f" % row[f] for f in fields[2:]])


def make_parser():
    parser = argparse.ArgumentParser(prog="python -m reliance_lab",
                                     description="Reliance Lab: does AI advice make people sharper or more dependent?")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--preset", default="scam_teens", help="Starting scenario: " + ", ".join(model.PRESETS))
        sp.add_argument("--config", help="Settings file downloaded from the browser app (overrides --preset)")
        sp.add_argument("--set", action="append", metavar="KEY=VALUE", help="Override one setting (repeatable)")

    sp = sub.add_parser("run", help="Simulate one workflow against the no-AI comparison group")
    common(sp)
    sp.add_argument("--workflow", choices=model.WORKFLOW_KEYS)
    sp.add_argument("--json", action="store_true", help="Print the full result as JSON")

    sp = sub.add_parser("compare", help="Compare all four workflows on the same people and cases")
    common(sp)
    sp.add_argument("--json", action="store_true", help="Print the summary as JSON")

    sp = sub.add_parser("robustness", help="Which assumptions could change the verdict?")
    common(sp)
    sp.add_argument("--workflow", choices=model.WORKFLOW_KEYS)
    sp.add_argument("--measure", choices=["skillGap", "lift"], default="skillGap")

    sp = sub.add_parser("experiment", help="Run a virtual randomised experiment with noisy tests")
    common(sp)
    sp.add_argument("--arms", default="none,ai_first,human_first", help="Comma-separated workflows")
    sp.add_argument("--n", type=int, default=60, help="Participants per arm")
    sp.add_argument("--items", type=int, default=20, help="Items in each test")
    sp.add_argument("--csv", help="Write participant-level data to this CSV file")
    sp.add_argument("--markdown", help="Write a Markdown report to this file")

    sp = sub.add_parser("power", help="How many participants would a study need?")
    common(sp)
    sp.add_argument("--arm", default="ai_first", choices=model.WORKFLOW_KEYS)
    sp.add_argument("--control", default="none", choices=model.WORKFLOW_KEYS)
    sp.add_argument("--sizes", default="20,40,80,160,320", help="Comma-separated participants per arm")
    sp.add_argument("--reps", type=int, default=400)
    sp.add_argument("--pool", type=int, default=800)
    sp.add_argument("--items", type=int, default=20)
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    params = build_params(args)
    try:
        if args.command == "run":
            a = model.analyse(params)
            print(json.dumps(a, indent=2) if args.json else format_run(a))
        elif args.command == "compare":
            rows = model.compare_workflows(params)
            if args.json:
                print(json.dumps([{"workflow": r["workflow"], "verdict": r["verdict"],
                                   **{k: v for k, v in r["result"].items() if k not in ("series", "params")}}
                                  for r in rows], indent=2))
            else:
                print(format_compare(rows))
        elif args.command == "robustness":
            print(format_robustness(model.sensitivity(params), args.measure))
        elif args.command == "experiment":
            arms = [x.strip() for x in args.arms.split(",") if x.strip()]
            e = run_experiment(params, arms=arms, n=args.n, items=args.items)
            print(format_experiment(e))
            if args.csv:
                write_csv(e, args.csv)
                print("\nWrote %s" % args.csv)
            if args.markdown:
                with open(args.markdown, "w", encoding="utf-8") as fh:
                    fh.write(markdown_experiment(e))
                print("Wrote %s" % args.markdown)
        elif args.command == "power":
            try:
                sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
            except ValueError:
                raise SystemExit("--sizes expects whole numbers separated by commas")
            pw = power_curve(params, args.arm, args.control, sizes=sizes, reps=args.reps, pool=args.pool, items=args.items)
            print(format_power(pw))
    except ValueError as err:
        raise SystemExit("Error: %s" % err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
