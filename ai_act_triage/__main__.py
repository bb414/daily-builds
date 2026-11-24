"""Command-line interface. Simplified and illustrative, not legal advice.

    python -m ai_act_triage classify system.json          # one system, answers in a JSON file
    python -m ai_act_triage classify system.json --as-of 2027-06-01
    python -m ai_act_triage register examples/register.csv  # a whole AI register, with a roadmap
"""

import argparse
import json
import sys

from . import model, register


text_table, euros = register.text_table, register.euros


def describe(res):
    a = res["answers"]
    out = ["%s: %s" % (a["name"] or "This system", res["tierLabel"]), "Simplified and illustrative, not legal advice. Dates as of %s." % model.long_date(res["asOf"]), "", "Why:"]
    out += ["  %d. %s [%s]" % (k, s["text"], s["article"]) for k, s in enumerate(res["trace"], 1)]
    out.append("")
    if res["obligations"]:
        rows = [[o["text"], "all" if o["role"] == "both" else o["role"], o["article"], model.long_date(o["date"]),
                 "applies" if o["status"] == "applies" else "in %d days" % o["daysUntil"]] for o in res["obligations"]]
        out.append(text_table(["Duty", "Who", "Article", "From", "Status"], rows))
    else:
        out.append("No duties under the AI Act.")
    p = res["penalty"]
    if p:
        out += ["", "Maximum fine: %s (%s of %s and %d%% of worldwide turnover, %s)." % (
            euros(p["max"]), "the lower" if p["sme"] else "the higher", euros(p["amount"]), round(p["share"] * 100), p["article"])]
    out += ["", "The UK view:"] + ["  - " + n for n in res["uk"]]
    return "\n".join(out)


def cmd_classify(args):
    try:
        with open(args.file, encoding="utf-8-sig") as f:
            answers = json.load(f)
    except (OSError, ValueError) as exc:
        print("Could not read %s: %s" % (args.file, exc), file=sys.stderr)
        return 2
    if args.as_of and not model.valid_iso(args.as_of):
        print("--as-of must be a date written as YYYY-MM-DD", file=sys.stderr)
        return 2
    print(describe(model.classify(answers, args.as_of)))
    return 0


def cmd_register(args):
    if args.as_of and not model.valid_iso(args.as_of):
        print("--as-of must be a date written as YYYY-MM-DD", file=sys.stderr)
        return 2
    try:
        rows, warnings = register.load(args.file)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print("Could not read the register: %s" % exc, file=sys.stderr)
        return 2
    results = [model.classify(r["answers"], args.as_of) for r in rows]
    notes = ["%s: %s" % (r["answers"]["name"] or "(unnamed)", n) for r in rows for n in r["notes"]]
    print(register.render_text(results, warnings, notes))
    try:
        if args.markdown:
            with open(args.markdown, "w", encoding="utf-8") as f:
                f.write(register.render_markdown(results))
            print("\nWrote %s" % args.markdown)
        if args.csv:
            with open(args.csv, "w", encoding="utf-8", newline="") as f:
                f.write(register.duties_csv(results))
            print("Wrote %s" % args.csv)
    except OSError as exc:
        print("Could not write the output: %s" % exc, file=sys.stderr)
        return 2
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="python -m ai_act_triage", description="Where does an AI system sit under the EU AI Act? Simplified and illustrative, not legal advice.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("classify", help="classify one system from a JSON file of answers")
    c.add_argument("file")
    c.add_argument("--as-of", help="check dates as of this day (YYYY-MM-DD); defaults to when the rules were last checked")
    c.set_defaults(func=cmd_classify)
    r = sub.add_parser("register", help="classify every system in a CSV register and plan the work by date")
    r.add_argument("file")
    r.add_argument("--as-of", help="check dates as of this day (YYYY-MM-DD)")
    r.add_argument("--markdown", help="also write a Markdown roadmap report to this file")
    r.add_argument("--csv", help="also write every duty, with dates, to this CSV file")
    r.set_defaults(func=cmd_register)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(0)
