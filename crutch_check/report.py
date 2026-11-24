"""Plain-text reports."""

from .model import BY_ID, ROUND_LABELS, CONTROL_ROUND_LABELS, score_session


def pct(x):
    return "n/a" if x is None else "%d%%" % round(x * 100)


def session_report(session):
    """A readable summary of one participant's session."""
    res = score_session(session)
    labels = ROUND_LABELS if session["arm"] == "checker" else CONTROL_ROUND_LABELS
    who = session.get("participant") or "session %s" % session["seed"]
    lines = ["Crutch check: %s (%s arm)" % (who, session["arm"]), ""]
    for st in res["rounds"]:
        lines.append("  Round %d, %-26s %2d of %2d right (%s)" % (
            st["round"], labels[st["round"]] + ":", st["correct"], st["n"], pct(st["accuracy"])))
    ch = res["change"]["accuracy"]
    if ch is not None:
        lines.append("  Change from round 1 to round 3: %+d percentage points" % round(ch * 100))
    a = res["assisted"]
    if a:
        c = a["cases"]
        lines += [
            "",
            "  With the checker (round 2)",
            "    Your first answers      %s" % pct(a["initialAccuracy"]),
            "    The checker on its own  %s" % pct(a["checkerAccuracy"]),
            "    Your final answers      %s" % pct(a["finalAccuracy"]),
            "    Good switches %d, missed help %d, talked out of it %d, held firm %d" % (
                c["switchedToRight"], c["stayedWrong"], c["switchedToWrong"], c["keptRight"]),
            "    Followed the checker when it was wrong: %d of %d" % (a["followedWrong"], a["checkerWrong"]),
        ]
    lines += ["", "  Pattern: %s" % res["profileTitle"]]
    missed = [t for t in session["trials"] if t.get("final") and t["final"]["verdict"] != t["truth"]]
    if missed:
        lines += ["", "  Messages judged wrongly:"]
        for t in missed:
            m = BY_ID[t["messageId"]]
            lines.append("    Round %d  %-7s  %s from %s" % (t["round"], t["truth"], m["channel"], m["from"]))
    return "\n".join(lines)
