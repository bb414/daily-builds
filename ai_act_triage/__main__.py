"""Command-line interface. Simplified and illustrative, not legal advice.

    python -m ai_act_triage classify system.json          # one system, answers in a JSON file
    python -m ai_act_triage classify system.json --as-of 2027-06-01
"""

import argparse
import json
import sys

from . import model


def text_table(headers, rows):
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def euros(x):
    if x >= 1e9:
        return "€%sbn" % ("%.2f" % (x / 1e9)).rstrip("0").rstrip(".")
    if x >= 1e6:
        return "€%sm" % ("%.1f" % (x / 1e6)).rstrip("0").rstrip(".")
    return "€{:,}".format(int(x))


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


def build_parser():
    p = argparse.ArgumentParser(prog="python -m ai_act_triage", description="Where does an AI system sit under the EU AI Act? Simplified and illustrative, not legal advice.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("classify", help="classify one system from a JSON file of answers")
    c.add_argument("file")
    c.add_argument("--as-of", help="check dates as of this day (YYYY-MM-DD); defaults to when the rules were last checked")
    c.set_defaults(func=cmd_classify)
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
