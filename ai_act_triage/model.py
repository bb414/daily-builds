"""The classification rules: a line-by-line port of the MODEL block in app/index.html.

Simplified and illustrative, not legal advice. The rules data lives in
rules.json, which the browser app embeds; the tests check that both copies,
and both implementations, agree.
"""

import datetime
import decimal
import json
import math
import pathlib
import re

RULES = json.loads(pathlib.Path(__file__).with_name("rules.json").read_text(encoding="utf-8"))

ROLES = ["provider", "deployer", "both"]
EXCLUSIONS = ["none", "military", "research", "personal"]
GPAI = ["none", "gpai", "systemic"]
DEPLOYER_TYPES = ["private", "publicAuthority", "publicService"]
TIERS = {
    "outOfScope": "Outside the AI Act",
    "prohibited": "Banned practice",
    "highRisk": "High-risk",
    "gpaiSystemic": "General-purpose AI model with systemic risk",
    "gpai": "General-purpose AI model",
    "exempt63": "Annex III use, but not high-risk",
    "transparency": "Transparency duties",
    "minimal": "Minimal risk",
}
TIER_ORDER = ["prohibited", "highRisk", "gpaiSystemic", "gpai", "exempt63", "transparency", "minimal"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

_MISSING = object()
_JS_DECIMAL = re.compile(r"[+-]?(Infinity|([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?)")
_JS_PREFIXED = re.compile(r"0([xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)")


# The characters JavaScript's Number() and trim() treat as white space.
_JS_SPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def _to_float(n):
    """float(n), but a huge integer becomes infinity, as it does in JavaScript, instead of raising OverflowError."""
    try:
        return float(n)
    except OverflowError:
        return math.inf if n > 0 else -math.inf


def js_number_string(x):
    """JavaScript's String(x) for a number."""
    x = _to_float(x)
    if x != x:
        return "NaN"
    if x in (math.inf, -math.inf):
        return "Infinity" if x > 0 else "-Infinity"
    if x < 0:
        return "-" + js_number_string(-x)
    r = repr(x)  # the shortest digits that read back as x, which is what JavaScript prints too
    if r.endswith(".0"):
        return r[:-2]
    if "e" in r:
        if 1e-6 <= x < 1e21:
            return format(decimal.Decimal(r), "f")
        mantissa, exponent = r.split("e")
        return mantissa + "e" + ("-" if exponent.startswith("-") else "+") + exponent.lstrip("+-").lstrip("0")
    return r


def _js_string(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return js_number_string(value)
    if isinstance(value, list):
        return ",".join(_js_string(v) for v in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


def js_number(value):
    """JavaScript's Number(value) for anything a JSON file can hold. NaN if not a number."""
    if value is _MISSING:
        return math.nan
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return _to_float(value)
    if isinstance(value, list):
        return js_number(_js_string(value))
    if isinstance(value, str):
        text = value.strip(_JS_SPACE)
        if not text:
            return 0.0
        if _JS_PREFIXED.fullmatch(text):
            return _to_float(int(text, 0))
        if _JS_DECIMAL.fullmatch(text):
            return float(text.replace("Infinity", "inf"))
    return math.nan


def js_round(x):
    """JavaScript's Math.round: halves round up."""
    return math.floor(x + 0.5)


def _ids(items):
    return [x["id"] for x in items]


def _by_id(items, item_id):
    return next((x for x in items if x["id"] == item_id), None)


def _pick(value, allowed, fallback):
    return value if isinstance(value, str) and value in allowed else fallback


def _flag(value):
    return value is True


def normalise(a=None):
    """Fill in defaults and drop anything that is not a valid answer, as the browser app does."""
    if not isinstance(a, dict):
        a = {}
    turnover = js_number(a.get("turnover", _MISSING))
    prohibited = a.get("prohibited")
    name = a.get("name")
    return {
        "name": name[:120] if isinstance(name, str) else "",
        "role": _pick(a.get("role"), ROLES, "deployer"),
        "takeover": _flag(a.get("takeover")),
        "eu": a.get("eu") is not False,
        "excluded": _pick(a.get("excluded"), EXCLUSIONS, "none"),
        "prohibited": [i for i in _ids(RULES["prohibitions"]) if isinstance(prohibited, list) and i in prohibited],
        "annex1": _flag(a.get("annex1")),
        "annex3": _pick(a.get("annex3"), [""] + _ids(RULES["annex3"]), ""),
        "derogation": _pick(a.get("derogation"), [""] + _ids(RULES["derogations"]), ""),
        "profiling": _flag(a.get("profiling")),
        "interacts": _flag(a.get("interacts")),
        "generates": _flag(a.get("generates")),
        "generatedBefore": _flag(a.get("generatedBefore")),
        "emotionBiocat": _flag(a.get("emotionBiocat")),
        "deepfake": _flag(a.get("deepfake")),
        "gpai": _pick(a.get("gpai"), GPAI, "none"),
        "gpaiBefore": _flag(a.get("gpaiBefore")),
        "gpaiOpen": _flag(a.get("gpaiOpen")),
        "deployerType": _pick(a.get("deployerType"), DEPLOYER_TYPES, "private"),
        "workplace": _flag(a.get("workplace")),
        "turnover": min(turnover, 1e7) if math.isfinite(turnover) and turnover >= 0 else 0,
        "sme": _flag(a.get("sme")),
    }


def valid_iso(s):
    """A real calendar date written as YYYY-MM-DD."""
    if not isinstance(s, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", s):
        return False
    if int(s[:4]) < 100:
        return False  # JavaScript's Date.UTC reads years 0 to 99 as 1900 to 1999, so the app rejects them too
    try:
        datetime.date(int(s[:4]), int(s[5:7]), int(s[8:]))
    except ValueError:
        return False
    return True


def days_between(from_iso, to_iso):
    return (datetime.date.fromisoformat(to_iso) - datetime.date.fromisoformat(from_iso)).days


def long_date(iso):
    """2027-12-02 -> "2 December 2027"."""
    return "%d %s %s" % (int(iso[8:10]), MONTHS[int(iso[5:7]) - 1], iso[:4])


def _lower(s):
    return s[:1].lower() + s[1:]


def classify(answers_in, as_of=None):
    """Classify one AI system. Returns the tier, the reasoning, the duties with dates, the fine tier and UK notes."""
    a = normalise(answers_in)
    as_of = as_of if valid_iso(as_of) else RULES["checked"]
    trace, tags = [], []

    def step(text, article=""):
        trace.append({"text": text, "article": article})

    res = {"answers": a, "asOf": as_of, "inScope": True, "route": None, "highRisk": False, "exempt": False, "stopped": False, "trace": trace}

    if not a["eu"]:
        res["inScope"] = False
        step("The system is not placed on the EU market or put into service there, and its output is not used in the EU.", "Art 2(1)")
    elif a["excluded"] == "military":
        res["inScope"] = False
        step("Used exclusively for military, defence or national security purposes, which are excluded.", "Art 2(3)")
    elif a["excluded"] == "research":
        res["inScope"] = False
        step("Developed and put into service only for scientific research and development.", "Art 2(6)")
    elif a["excluded"] == "personal" and a["role"] == "deployer":
        res["inScope"] = False
        step("Used by an individual for purely personal, non-professional purposes, so deployer duties do not apply.", "Art 2(10)")
    else:
        step("In scope: placed on the EU market, put into service there, or used in a way whose output reaches the EU.", "Art 2(1)")
        if a["excluded"] == "personal":
            step("Purely personal use by an individual removes only the deployer's duties; the provider's duties still apply.", "Art 2(10)")

    roles = ["provider", "deployer"] if a["role"] == "both" else [a["role"]]
    if res["inScope"] and a["excluded"] == "personal":
        roles = ["provider"]
    if not res["inScope"]:
        res["tier"] = "outOfScope"
        return _finish(res, a, roles, ["outOfScope"])

    if a["prohibited"]:
        live = 0
        for pid in a["prohibited"]:
            p = _by_id(RULES["prohibitions"], pid)
            start = RULES["dates"][p["dateKey"]]["amended"]
            later = days_between(as_of, start) > 0
            live += 0 if later else 1
            step("Banned practice: %s. Banned from %s%s" % (_lower(p["label"]), long_date(start), ", after the chosen date." if later else "."), p["point"])
        if live:
            step("A banned practice cannot be placed on the market, put into service or used in the EU, so the other tests are not run until it is removed.", "Art 5")
            res["tier"] = "prohibited"
            res["stopped"] = True
            return _finish(res, a, roles, ["prohibited"])
        step("Until the ban applies, the other tests still run, so the duties that apply in the meantime are listed too.", "Art 113")
        tags.append("prohibited")

    if a["annex1"]:
        res["highRisk"], res["route"] = True, "annex1"
        step("A product, or a safety component of a product, covered by EU product law in Annex I that needs a third-party conformity assessment, so it is high-risk.", "Art 6(1)")
    if a["annex3"]:
        area = _by_id(RULES["annex3"], a["annex3"])
        step("Intended for a use listed in Annex III: %s." % _lower(area["label"]), area["point"])
        if a["derogation"] and a["profiling"]:
            step("The exemption for systems that do not pose a significant risk is not available, because the system profiles people.", "Art 6(3), last subparagraph")
            res["highRisk"], res["route"] = True, "annex3"
        elif a["derogation"]:
            d = _by_id(RULES["derogations"], a["derogation"])
            if res["highRisk"]:
                step("An exemption applies to the Annex III use (%s), but it only removes the Annex III route: the system stays high-risk as an Annex I product." % _lower(d["label"]), d["point"])
            else:
                step("Not high-risk under the exemption: %s. The provider must document this assessment and register the system." % _lower(d["label"]),
                     d["point"] + ", Art 6(4)")
                res["exempt"] = True
        else:
            step("None of the exemptions applies, so it is high-risk.", "Art 6(2)")
            res["highRisk"], res["route"] = True, "annex3"
    if res["highRisk"]:
        tags.append("highRisk")
        if a["takeover"] and "provider" not in roles:
            roles = ["provider", "deployer"]
            step("You put your name on the system, changed it substantially or changed its intended purpose, so you take on the provider's duties as well.", "Art 25(1)")
        d = RULES["dates"][res["route"]]
        step("High-risk rules apply from %s (originally %s, before the Digital Omnibus)." % (long_date(d["amended"]), long_date(d["original"])), d["basis"])
        step("A high-risk system already on the market before then is generally caught only if its design changes significantly afterwards, but systems for public authorities must comply by 2 August 2030.", "Art 111(2)")
    elif res["exempt"]:
        tags.append("exempt63")

    t = []
    if a["interacts"] and "provider" in roles:
        t.append(("It interacts directly with people.", "Art 50(1)"))
    if a["generates"] and "provider" in roles:
        t.append(("It generates audio, images, video or text" + (", and was on the market before 2 August 2026, so marking is due by 2 December 2026." if a["generatedBefore"] else "."), "Art 50(2)"))
    if a["emotionBiocat"] and "deployer" in roles:
        t.append(("You use it for emotion recognition or biometric categorisation.", "Art 50(3)"))
    if a["deepfake"] and "deployer" in roles:
        t.append(("You publish deepfakes, or generated text on matters of public interest.", "Art 50(4)"))
    for text, art in t:
        step("Transparency duty: " + _lower(text), art)
    if t:
        tags.append("transparency")

    if a["gpai"] != "none" and "provider" in roles:
        if a["gpai"] == "systemic":
            step("You provide a general-purpose AI model with systemic risk (presumed above 10^25 floating-point operations of training compute).", "Art 51")
        else:
            step("You provide a general-purpose AI model" + (" under a free and open-source licence, so some documentation duties fall away." if a["gpaiOpen"] else "."),
                 "Art 53(1), (2)" if a["gpaiOpen"] else "Art 53(1)")
        if a["gpaiBefore"]:
            step("The model was on the market before 2 August 2025, so it must comply by 2 August 2027.", "Art 111(3)")
        tags.append("gpaiSystemic" if a["gpai"] == "systemic" else "gpai")

    if not tags:
        step("No banned practice, high-risk use, transparency trigger or general-purpose model: minimal risk. Only the AI literacy duty applies.", "Art 4")
        tags.append("minimal")
    tags = [k for k in TIER_ORDER if k in tags]  # most serious first
    res["tier"] = tags[0]
    return _finish(res, a, roles, tags)


def _triggered(trigger, res, a):
    area = a["annex3"]
    annex3_hr = res["highRisk"] and res["route"] == "annex3"
    return {
        "inScope": res["inScope"],
        "highRisk": res["highRisk"],
        "annex3": annex3_hr,
        "highRiskWorkplace": res["highRisk"] and a["workplace"],
        # Critical infrastructure (Annex III, point 2) is registered nationally and has no right to an explanation.
        "annex3EU": annex3_hr and area != "infrastructure",
        "annex3National": annex3_hr and area == "infrastructure",
        "annex3PublicAuthority": annex3_hr and area != "infrastructure" and a["deployerType"] == "publicAuthority",
        "fria": annex3_hr and area != "infrastructure" and (a["deployerType"] != "private" or area in ("credit", "insurance")),
        "exempt63": res["exempt"],
        "interacts": a["interacts"],
        "generates": a["generates"],
        "emotionBiocat": a["emotionBiocat"],
        "deepfake": a["deepfake"],
        "gpai": a["gpai"] != "none",
        "gpaiSystemic": a["gpai"] == "systemic",
        "gpaiClosedOrSystemic": a["gpai"] != "none" and (not a["gpaiOpen"] or a["gpai"] == "systemic"),
    }.get(trigger, False)


def _date_key(o, res, a):
    if o["id"] == "t_mark" and a["generatedBefore"]:
        return "transparencyLegacy"
    if o["id"].startswith("g_") and a["gpaiBefore"]:
        return "gpaiLegacy"
    if o.get("dateKey"):
        return o["dateKey"]
    if o["trigger"] == "exempt63":
        return "annex3"
    return res["route"]


def _finish(res, a, roles, tags):
    res["roles"], res["tags"] = roles, tags
    suffix = (" (product under Annex I)" if res["route"] == "annex1" else " (Annex III use)") if res["tier"] == "highRisk" else ""
    res["tierLabel"] = TIERS[res["tier"]] + suffix
    obligations = []
    if "prohibited" in tags:
        for pid in a["prohibited"]:
            p = _by_id(RULES["prohibitions"], pid)
            obligations.append({"id": "ban_" + pid, "role": "both", "article": p["point"], "text": "Stop: " + _lower(p["label"]), "dateKey": p["dateKey"]})
    if res["inScope"]:
        for o in RULES["obligations"]:
            if res["stopped"] and o["id"] != "literacy":
                continue
            if o["role"] != "both" and o["role"] not in roles:
                continue
            if not _triggered(o["trigger"], res, a):
                continue
            obligations.append({"id": o["id"], "role": o["role"], "article": o["article"], "text": o["text"], "dateKey": _date_key(o, res, a)})
    for o in obligations:
        d = RULES["dates"][o["dateKey"]]
        o["date"], o["originalDate"] = d["amended"], d["original"]
        o["daysUntil"] = days_between(res["asOf"], o["date"])
        o["status"] = "applies" if o["daysUntil"] <= 0 else "upcoming"
    # A ban that has not started yet: duties starting on or after the ban date can never apply, so drop them,
    # and drop any tag whose duties have all gone.
    if not res["stopped"] and "prohibited" in tags:
        ban_start = min(o["date"] for o in obligations if o["id"].startswith("ban_"))
        obligations = [o for o in obligations if o["id"] == "literacy" or o["id"].startswith("ban_") or o["date"] < ban_start]
        family = {"highRisk": ("p_", "d_"), "exempt63": ("e_",), "transparency": ("t_",), "gpai": ("g_",), "gpaiSystemic": ("g_",)}
        tags = [t for t in tags if t not in family or any(o["id"].startswith(family[t]) for o in obligations)]
        res["tags"] = tags
    obligations.sort(key=lambda o: o["date"])  # stable, like Array.prototype.sort in modern JavaScript
    res["obligations"] = obligations
    upcoming = [o for o in obligations if o["status"] == "upcoming"]
    res["nextDeadline"] = ({"date": upcoming[0]["date"], "dateKey": upcoming[0]["dateKey"],
                            "count": sum(1 for o in upcoming if o["date"] == upcoming[0]["date"])} if upcoming else None)
    res["penalty"] = _penalty(res, a)
    res["uk"] = _uk_notes(res, a)
    res["omnibus"] = omnibus_changes(obligations)
    return res


def omnibus_changes(obligations):
    """What the Digital Omnibus changed for these duties: moved dates and new duties."""
    seen, out = {}, []
    for o in obligations:
        if o["originalDate"] == o["date"]:
            continue
        if o["dateKey"] not in seen:
            seen[o["dateKey"]] = {"dateKey": o["dateKey"], "label": RULES["dateLabels"][o["dateKey"]], "original": o["originalDate"],
                                  "amended": o["date"], "daysGained": days_between(o["originalDate"], o["date"]) if o["originalDate"] else None,
                                  "duties": 0}
            out.append(seen[o["dateKey"]])
        seen[o["dateKey"]]["duties"] += 1
    return out


def roadmap(results):
    """Milestones across a register of classified systems: when duties start and which systems they reach."""
    by_date = {}
    for k, r in enumerate(results):
        for o in r["obligations"]:
            m = by_date.setdefault(o["date"], {"date": o["date"], "systems": [], "duties": 0, "dateKeys": []})
            m["duties"] += 1
            if k not in m["systems"]:
                m["systems"].append(k)
            if o["dateKey"] not in m["dateKeys"]:
                m["dateKeys"].append(o["dateKey"])
    out = []
    for d in sorted(by_date):
        m = by_date[d]
        m["labels"] = [RULES["dateLabels"][k] for k in m["dateKeys"]]
        m["status"] = "applies" if results and days_between(results[0]["asOf"], d) <= 0 else "upcoming"
        out.append(m)
    return out


def _penalty(res, a):
    """The highest fine that could apply. With duties under both Art 99(4) and Art 101, the larger cap is shown."""
    # Operator duties under Art 99(4) are the provider's and deployer's high-risk and transparency duties; an exempt
    # system's duties (documenting and registering) are the provider's alone.
    keys = []
    if "prohibited" in res["tags"]:
        keys.append("prohibited")
    if "highRisk" in res["tags"] or ("exempt63" in res["tags"] and "provider" in res["roles"]) or "transparency" in res["tags"]:
        keys.append("operator")
    if "gpai" in res["tags"] or "gpaiSystemic" in res["tags"]:
        keys.append("gpai")
    best = None
    for key in keys:
        p = RULES["penalties"][key]
        share = p["share"] * a["turnover"] * 1e6
        sme_rule = a["sme"] and key != "gpai"
        # With no turnover given, only the fixed amount is known, so that is shown.
        top = (min(p["amount"], share) if sme_rule else max(p["amount"], share)) if a["turnover"] > 0 else p["amount"]
        c = {"key": key, "article": p["article"], "amount": p["amount"], "share": p["share"], "sme": sme_rule,
             "turnoverKnown": a["turnover"] > 0, "max": js_round(top)}
        if best is None or c["max"] > best["max"]:
            best = c
    if best:
        best["publicAuthority"] = a["deployerType"] == "publicAuthority"  # national rules decide, Art 99(8)
    return best


def _list_and(items):
    """['a', 'b', 'c'] -> 'a, b and c'."""
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _uk_notes(res, a):
    notes = list(RULES["ukBaseline"])
    if a["annex3"]:
        area = _by_id(RULES["annex3"], a["annex3"])
        notes.append("For this use (%s), regulators whose remits are likely to be engaged include %s." % (_lower(area["label"].split(":")[0]), _list_and(area["uk"])))
    if a["annex1"]:
        notes.append(RULES["ukAnnex1"])
    if "transparency" in res["tags"]:
        notes.append(RULES["ukTransparency"])
    return notes


def euros(x):
    """Euros, rounded to the nearest €10,000 above a million: 15000000 -> "€15m", 1250000 -> "€1.25m"."""
    def hundredths(n):
        whole, frac = n // 100, n % 100
        return str(whole) + ("." + str(100 + frac)[1:].rstrip("0") if frac else "")
    if x >= 1e9 or js_round(x / 1e4) >= 100000:
        return "€%sbn" % hundredths(js_round(x / 1e7))
    if x >= 1e6:
        return "€%sm" % hundredths(js_round(x / 1e4))
    return "€{:,}".format(js_round(x))


# ---------- Checking answers read from a file ----------
BOOL_FIELDS = ["takeover", "eu", "annex1", "profiling", "interacts", "generates", "generatedBefore", "emotionBiocat",
               "deepfake", "gpaiBefore", "gpaiOpen", "workplace", "sme"]
_INDEX_KEY = re.compile(r"0|[1-9][0-9]*")


def _js_key_order(keys):
    """The order JavaScript's Object.keys gives: array-index keys in numeric order, then the rest as written."""
    index = [k for k in keys if len(k) <= 10 and _INDEX_KEY.fullmatch(k) and int(k) < 4294967295]
    return sorted(index, key=int) + [k for k in keys if k not in index]


def show_value(v):
    """A value as it should appear in a note: text in quotes, numbers as JavaScript writes them."""
    if isinstance(v, str):
        return '"%s"' % v
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "an object"
    return js_number_string(v)


def input_notes(raw):
    """Everything normalise() had to ignore or change in answers read from a JSON file, in words."""
    if not isinstance(raw, dict):
        return ["the answers are not an object, so the defaults were used"]
    a, notes = normalise(raw), []
    choices = {"role": ROLES, "excluded": EXCLUSIONS, "annex3": _ids(RULES["annex3"]), "derogation": _ids(RULES["derogations"]),
               "gpai": GPAI, "deployerType": DEPLOYER_TYPES}
    for k in _js_key_order(list(raw)):
        v = raw[k]
        if k == "id":
            continue
        if k not in a:
            notes.append('unknown answer "%s" was ignored' % k)
        elif k == "name":
            if not isinstance(v, str):
                notes.append("name %s is not text, so it was left blank" % show_value(v))
            elif len(v) > 120:
                notes.append("name was cut to 120 characters")
        elif k in choices:
            if v != a[k] or type(v) is not str:
                if not (v == "" and k in ("annex3", "derogation")):
                    notes.append("%s %s is not one of: %s" % (k, show_value(v), ", ".join(choices[k])))
        elif k in BOOL_FIELDS:
            if v is not True and v is not False:
                notes.append("%s %s is not true or false, so it was treated as %s" % (k, show_value(v), "true" if a[k] else "false"))
        elif k == "prohibited":
            if not isinstance(v, list):
                notes.append("prohibited %s is not a list, so it was ignored" % show_value(v))
            else:
                notes += ["prohibited %s is not a known banned practice" % show_value(x) for x in v if not (isinstance(x, str) and x in _ids(RULES["prohibitions"]))]
        elif k == "turnover":
            n = js_number(v)
            if not math.isfinite(n) or n < 0:
                notes.append("turnover %s is not a number of euro millions, so 0 was used" % show_value(v))
            elif n > 1e7:
                notes.append("turnover %s was capped at 10000000 (euro millions)" % show_value(v))
    return notes


# ---------- What would change the result ----------
# The answers worth testing one at a time. Scope answers are only tested when the system is out of scope.
PIVOT_FIELDS = ["role", "takeover", "prohibited", "annex1", "annex3", "derogation", "profiling", "interacts", "generates",
                "generatedBefore", "emotionBiocat", "deepfake", "gpai", "gpaiOpen", "gpaiBefore", "deployerType", "workplace", "sme"]
SEVERITY = TIER_ORDER + ["outOfScope"]


def _choice_label(field, item_id):
    c = _by_id(RULES["choices"][field], item_id)
    return c["label"] if c else item_id


def answer_label(field, value):
    """A short, readable version of one answer."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if field == "annex3":
        return _by_id(RULES["annex3"], value)["label"].split(":")[0] if value else "none"
    if field == "derogation":
        return _by_id(RULES["derogations"], value)["point"] if value else "none"
    return _choice_label(field, value)


def _candidates(a, base):
    """Every single-answer change worth trying: (field, option or None, new value, label for the new value)."""
    out = []

    def other(field, values):
        out.extend((field, None, v, answer_label(field, v)) for v in values if v != a[field])

    if base["tier"] == "outOfScope":
        if not a["eu"]:
            out.append(("eu", None, True, "yes"))
        if a["excluded"] != "none":
            out.append(("excluded", None, "none", _choice_label("excluded", "none")))
    elif a["excluded"] == "personal":
        out.append(("excluded", None, "none", _choice_label("excluded", "none")))
    for field in PIVOT_FIELDS:
        v = a[field]
        if field == "role":
            other(field, ROLES)
        elif field == "gpai":
            other(field, GPAI)
        elif field == "deployerType":
            other(field, DEPLOYER_TYPES)
        elif field == "prohibited":
            out.extend((field, i, [x for x in v if x != i], "no") for i in v)
        elif field == "annex3":
            if v:
                out.append((field, None, "", "none"))
        elif field == "derogation":
            if v:
                out.append((field, None, "", "none"))
            elif a["annex3"]:
                out.append((field, None, RULES["derogations"][0]["id"], "any of the four"))
        else:
            out.append((field, None, not v, "no" if v else "yes"))
    return out


def _effect(from_tier, to_tier, net_duties, from_fine, to_fine, moved, from_stopped, to_stopped):
    """Is the result after a change lighter or heavier? By tier, then the number of duties, the fine and the dates."""
    if from_stopped != to_stopped:
        d = 1 if from_stopped else -1  # lifting a ban that is in force is lighter, however many duties then appear
    else:
        d = SEVERITY.index(to_tier) - SEVERITY.index(from_tier)
    if not d:
        d = -net_duties
    if not d and from_fine != to_fine:
        d = 1 if (to_fine or 0) < (from_fine or 0) else -1
    if not d:
        for m in moved:
            d += 1 if m["to"] > m["from"] else -1
    return "lighter" if d > 0 else "heavier" if d < 0 else "different"


def pivots(answers_in, as_of=None):
    """Which single answers, if they were different, would change the classification, the duties, their dates or the fine."""
    a = normalise(answers_in)
    base = classify(a, as_of)
    base_dates = {o["id"]: o["date"] for o in base["obligations"]}
    base_fine = base["penalty"]["max"] if base["penalty"] else None
    cands = _candidates(a, base)
    found = []
    for k, (field, option, value, to_label) in enumerate(cands):
        changed = dict(a)
        changed[field] = value
        res = classify(changed, base["asOf"])
        dates = {o["id"]: o["date"] for o in res["obligations"]}
        added = [o["id"] for o in res["obligations"] if o["id"] not in base_dates]
        removed = [o["id"] for o in base["obligations"] if o["id"] not in dates]
        moved = [{"id": o["id"], "from": base_dates[o["id"]], "to": o["date"]} for o in res["obligations"]
                 if o["id"] in base_dates and base_dates[o["id"]] != o["date"]]
        fine = res["penalty"]["max"] if res["penalty"] else None
        tier_changed = res["tier"] != base["tier"]
        if not tier_changed and not added and not removed and not moved and fine == base_fine:
            continue
        question = RULES["questions"][field] + (" (%s)" % _by_id(RULES["prohibitions"], option)["point"] if option else "")
        found.append({"field": field, "option": option, "value": value, "question": question,
                      "from": "yes" if option else answer_label(field, a[field]), "to": to_label,
                      "tier": res["tier"], "tierLabel": res["tierLabel"], "tierChanged": tier_changed,
                      "added": added, "removed": removed, "moved": moved,
                      "fine": None if fine == base_fine else {"from": base_fine, "to": fine},
                      "effect": _effect(base["tier"], res["tier"], len(added) - len(removed), base_fine, fine, moved,
                                        base["stopped"], res["stopped"]),
                      "order": k})
    found.sort(key=lambda p: (0 if p["tierChanged"] else 1, -(len(p["added"]) + len(p["removed"]) + len(p["moved"])), p["order"]))
    for p in found:
        del p["order"]
    return {"tier": base["tier"], "tested": len(cands), "pivots": found}
