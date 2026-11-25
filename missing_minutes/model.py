"""The simulation model, a line-for-line port of the browser app's model.

Time is measured in working minutes: a working day is 7.5 hours (450 minutes)
and a week is five working days, so nights and weekends are skipped.

Every random number comes from 32-bit integer generators that the JavaScript
version reproduces exactly, so both versions give the same results for the
same configuration and seed (tests/test_agreement.py checks this).
"""

import copy
import heapq
import json
import math

DAY = 450
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
ARRIVE, DONE, BATCH = 0, 1, 2
MASK = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Random numbers
# ---------------------------------------------------------------------------

def mix(h, v):
    """Mix a 32-bit value into a 32-bit hash (same as the JavaScript mix)."""
    h = ((h ^ v) & MASK) * 0x85EBCA6B & MASK
    h ^= h >> 13
    h = h * 0xC2B2AE35 & MASK
    h ^= h >> 16
    return h


class Rng:
    """mulberry32, returning floats strictly between 0 and 1."""

    __slots__ = ("s",)

    def __init__(self, seed):
        self.s = seed & MASK

    def next(self):
        self.s = (self.s + 0x6D2B79F5) & MASK
        t = self.s
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK
        t = (t ^ (t >> 14)) & MASK
        return (t + 0.5) / 4294967296


def visit_rng(seed, case_id, step, visit):
    """One stream per visit of a case to a step (common random numbers)."""
    return Rng(mix(mix(mix(mix(seed & MASK, 0xCA5E), case_id), step), visit))


def spread(cv, u1, u2):
    """Lognormal multiplier with mean 1 and coefficient of variation cv."""
    if cv <= 0:
        return 1
    s2 = math.log(1 + cv * cv)
    z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    return math.exp(-s2 / 2 + math.sqrt(s2) * z)


# ---------------------------------------------------------------------------
# Presets (invented processes; none describes a real organisation)
# ---------------------------------------------------------------------------

PRESETS = {
    "claims": {
        "name": "Home insurance claims",
        "blurb": "An invented insurer. The AI drafts the claim assessment for the handler; a quality check sends some claims back.",
        "arrivalsPerDay": 40, "slaDays": 5,
        "steps": [
            {"name": "Register claim", "kind": "team", "staff": 2, "minutes": 9, "cv": 0.5},
            {"name": "Assess claim", "kind": "team", "staff": 5, "minutes": 50, "cv": 0.7},
            {"name": "Quality check", "kind": "team", "staff": 2, "minutes": 15, "cv": 0.6, "reworkTo": 1, "reworkRate": 0.08},
            {"name": "Await repair quote", "kind": "delay", "share": 0.6, "minutes": 675, "cv": 0.8},
            {"name": "Payment run", "kind": "batch", "batchDays": [0, 1, 2, 3, 4], "capacity": 200, "minutes": 1, "cv": 0},
            {"name": "Write to customer", "kind": "team", "staff": 2, "minutes": 10, "cv": 0.5},
        ],
        "ai": {"step": 1, "saving": 0.4, "adoption": 0.75, "checkMinutes": 5, "errorRate": 0.06, "catchRate": 0.9},
    },
    "loans": {
        "name": "Small business loans",
        "blurb": "An invented lender. The AI summarises the accounts for the credit analyst; the credit committee meets on Tuesdays and Thursdays.",
        "arrivalsPerDay": 12, "slaDays": 8,
        "steps": [
            {"name": "Check documents", "kind": "team", "staff": 2, "minutes": 25, "cv": 0.6},
            {"name": "Await missing documents", "kind": "delay", "share": 0.4, "minutes": 1350, "cv": 0.7},
            {"name": "Analyse credit", "kind": "team", "staff": 4, "minutes": 95, "cv": 0.6},
            {"name": "Credit committee", "kind": "batch", "batchDays": [1, 3], "capacity": 40, "minutes": 6, "cv": 0.4, "reworkTo": 2, "reworkRate": 0.08},
            {"name": "Issue offer", "kind": "team", "staff": 2, "minutes": 20, "cv": 0.5},
        ],
        "ai": {"step": 2, "saving": 0.45, "adoption": 0.85, "checkMinutes": 10, "errorRate": 0.05, "catchRate": 0.9},
    },
    "complaints": {
        "name": "Customer complaints",
        "blurb": "An invented utility company. The AI drafts the reply to the customer; one team leader signs every reply off.",
        "arrivalsPerDay": 30, "slaDays": 8,
        "steps": [
            {"name": "Log and acknowledge", "kind": "team", "staff": 2, "minutes": 8, "cv": 0.5},
            {"name": "Investigate", "kind": "team", "staff": 6, "minutes": 60, "cv": 0.9},
            {"name": "Await customer evidence", "kind": "delay", "share": 0.35, "minutes": 1800, "cv": 0.8},
            {"name": "Draft reply", "kind": "team", "staff": 3, "minutes": 30, "cv": 0.6},
            {"name": "Team leader sign-off", "kind": "team", "staff": 1, "minutes": 12, "cv": 0.5, "reworkTo": 3, "reworkRate": 0.1},
            {"name": "Send and close", "kind": "team", "staff": 1, "minutes": 6, "cv": 0.4},
        ],
        "ai": {"step": 3, "saving": 0.5, "adoption": 0.8, "checkMinutes": 4, "errorRate": 0.08, "catchRate": 0.9},
    },
}

DEFAULTS = {"warmupDays": 20, "measureDays": 120, "drainDays": 80, "reworkEffort": 0.5}


def _num(v, d):
    if v is None or v == "" or isinstance(v, bool):
        return d
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    if not math.isfinite(x):
        return d
    return int(x) if x == int(x) else x


def _round(x):
    """JavaScript's Math.round: halves round up."""
    return int(math.floor(x + 0.5))


def preset_config(key):
    if key not in PRESETS:
        raise KeyError("Unknown preset: " + str(key))
    c = copy.deepcopy(PRESETS[key])
    c.pop("blurb", None)
    c["preset"] = key
    return normalise(c)


def normalise(cfg):
    """Fill in defaults so both languages always work from the same full config."""
    c = copy.deepcopy(cfg or {})
    name = c.get("name")
    out = {
        "name": name.strip() if isinstance(name, str) and name.strip() else "Custom process",
        "arrivalsPerDay": _num(c.get("arrivalsPerDay"), 20),
        "slaDays": _num(c.get("slaDays"), 10),
        "warmupDays": _num(c.get("warmupDays"), DEFAULTS["warmupDays"]),
        "measureDays": _num(c.get("measureDays"), DEFAULTS["measureDays"]),
        "drainDays": _num(c.get("drainDays"), DEFAULTS["drainDays"]),
        "reworkEffort": _num(c.get("reworkEffort"), DEFAULTS["reworkEffort"]),
        "steps": [],
        "ai": {},
    }
    if isinstance(c.get("preset"), str):
        out["preset"] = c["preset"]
    steps = c.get("steps") if isinstance(c.get("steps"), list) else []
    for i, s in enumerate(steps):
        s = s or {}
        kind = s.get("kind") if s.get("kind") in ("batch", "delay") else "team"
        sname = s.get("name")
        st = {
            "name": sname.strip() if isinstance(sname, str) and sname.strip() else "Step " + str(i + 1),
            "kind": kind,
            "staff": _round(_num(s.get("staff"), 1)) if kind == "team" else 0,
            "minutes": _num(s.get("minutes"), 10),
            "cv": _num(s.get("cv"), 0.5),
            "reworkTo": _round(_num(s.get("reworkTo"), -1)),
            "reworkRate": _num(s.get("reworkRate"), 0),
        }
        if st["reworkTo"] < 0:
            st["reworkTo"] = -1
            st["reworkRate"] = 0
        if kind == "batch":
            days = s.get("batchDays") if isinstance(s.get("batchDays"), list) else [2]
            clean = []
            for d in days:
                d = _round(_num(d, -1))
                if 0 <= d <= 4 and d not in clean:
                    clean.append(d)
            st["batchDays"] = sorted(clean)
            st["capacity"] = _round(_num(s.get("capacity"), 30))
        if kind == "delay":
            st["share"] = _num(s.get("share"), 1)
        out["steps"].append(st)
    a = c.get("ai") or {}
    out["ai"] = {
        "step": _round(_num(a.get("step"), -1)),
        "saving": _num(a.get("saving"), 0.3),
        "adoption": _num(a.get("adoption"), 0.8),
        "checkMinutes": _num(a.get("checkMinutes"), 0),
        "errorRate": _num(a.get("errorRate"), 0),
        "catchRate": _num(a.get("catchRate"), 0.9),
    }
    if out["ai"]["step"] < 0:
        out["ai"]["step"] = -1
    return out


def validate(cfg):
    """Return a list of plain-English problems; an empty list means it can run."""
    e = []

    def check(v, lo, hi, label):
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi
        if not ok:
            e.append("%s must be between %s and %s." % (label, _fmt_num(lo), _fmt_num(hi)))

    check(cfg["arrivalsPerDay"], 0.5, 400, "Cases per day")
    check(cfg["slaDays"], 0.5, 200, "Target days")
    check(cfg["warmupDays"], 0, 200, "Warm-up days")
    check(cfg["measureDays"], 10, 500, "Measured days")
    check(cfg["drainDays"], 0, 500, "Drain days")
    check(cfg["reworkEffort"], 0.05, 2, "Rework effort")
    if not cfg["steps"]:
        e.append("Add at least one step.")
    if len(cfg["steps"]) > 8:
        e.append("Use at most eight steps.")
    if cfg["arrivalsPerDay"] * (cfg["warmupDays"] + cfg["measureDays"]) > 60000:
        e.append("That is too many cases to simulate quickly: lower the cases per day or the number of days.")
    for i, s in enumerate(cfg["steps"]):
        label = s["name"]
        if s["kind"] == "team":
            check(s["staff"], 1, 60, label + ": people")
        if s["kind"] == "delay":
            check(s["minutes"], 0, 45000, label + ": length of the wait (minutes)")
        else:
            check(s["minutes"], 0.1, 2400, label + ": minutes per case")
        check(s["cv"], 0, 3, label + ": variability")
        if s["reworkTo"] >= 0:
            if s["reworkTo"] >= i:
                e.append(label + ": cases can only be sent back to an earlier step.")
            elif s["kind"] == "delay":
                e.append(label + ": a wait cannot send cases back.")
            check(s["reworkRate"], 0, 0.6, label + ": share sent back")
        if s["kind"] == "batch":
            if not s["batchDays"]:
                e.append(label + ": pick at least one day.")
            check(s["capacity"], 1, 2000, label + ": cases per session")
        if s["kind"] == "delay":
            check(s["share"], 0, 1, label + ": share of cases that wait")
    a = cfg["ai"]
    if a["step"] >= len(cfg["steps"]):
        e.append("The AI must sit on one of the steps.")
    elif a["step"] >= 0 and cfg["steps"][a["step"]]["kind"] == "delay":
        e.append("The AI cannot sit on a wait for someone outside the team.")
    check(a["saving"], 0, 0.95, "Time the AI saves")
    check(a["adoption"], 0, 1, "Share of cases that use the AI")
    check(a["checkMinutes"], 0, 600, "Minutes spent checking the AI")
    check(a["errorRate"], 0, 0.5, "AI error rate")
    check(a["catchRate"], 0, 1, "Share of AI errors caught")
    return e


def _fmt_num(x):
    return str(int(x)) if x == int(x) else str(x)


def next_batch_day(days, after):
    d = after + 1
    while (d % 5) not in days:
        d += 1
    return d


def quantile(sorted_values, p):
    """Nearest-rank quantile of an already sorted list."""
    if not sorted_values:
        return 0
    i = int(math.floor(p * len(sorted_values)))
    return sorted_values[min(i, len(sorted_values) - 1)]


# ---------------------------------------------------------------------------
# The discrete-event simulation
# ---------------------------------------------------------------------------

class _Case:
    __slots__ = ("id", "arr", "tracked", "enq", "reworking", "rework_check", "reworks",
                 "defect", "ai", "u_back", "u_catch", "visits", "touch", "wait")

    def __init__(self, cid, arr, tracked, n):
        self.id = cid
        self.arr = arr
        self.tracked = tracked
        self.enq = arr
        self.reworking = False
        self.rework_check = -1
        self.reworks = 0
        self.defect = False
        self.ai = False
        self.u_back = 0
        self.u_catch = 0
        self.visits = [0] * n
        self.touch = [0] * n
        self.wait = [0] * n


def simulate(cfg_in, seed=1, no_ai=False, keep_lead_times=False):
    """Run one process for one seed and return summary statistics."""
    cfg = normalise(cfg_in)
    seed = seed & MASK
    steps = cfg["steps"]
    n = len(steps)
    ai = cfg["ai"]
    ai_step = -1 if no_ai else ai["step"]
    lam = cfg["arrivalsPerDay"] / DAY
    W = cfg["warmupDays"] * DAY
    E = W + cfg["measureDays"] * DAY
    CAP = E + cfg["drainDays"] * DAY
    rework_effort = cfg["reworkEffort"]

    heap = []
    seq = [0]

    def push(t, typ, a, b):
        heapq.heappush(heap, (t, seq[0], typ, a, b))
        seq[0] += 1

    busy = [0] * n
    queues = [[] for _ in range(n)]
    heads = [0] * n
    busy_min = [0] * n
    max_q = [0] * n
    sessions = [0] * n
    cleared = [0] * n
    entries = [0] * n
    cases = []
    st_ = {"tracked": 0, "open": 0, "within": 0, "reworked": 0, "ai_back": 0, "base_back": 0,
           "escaped": 0, "ai_used": 0, "ai_saved": 0, "ai_lost": 0, "ai_check": 0}
    lead = []
    touch_sum = [0] * n
    wait_sum = [0] * n
    visit_sum = [0] * n
    sla_min = cfg["slaDays"] * DAY

    def in_window(t):
        return W <= t < E

    def overlap(s, e):
        a = s if s > W else W
        b = e if e < E else E
        return b - a if b > a else 0

    def enter(c, k, t):
        c.enq = t
        if c.reworking and k == c.rework_check:
            c.reworking = False
        if in_window(t):
            entries[k] += 1
        st = steps[k]
        if st["kind"] == "delay":
            start_delay(c, k, t)
            return
        if st["kind"] == "team" and busy[k] < st["staff"]:
            start(c, k, t)
            return
        queues[k].append(c)
        ql = len(queues[k]) - heads[k]
        if in_window(t) and ql > max_q[k]:
            max_q[k] = ql

    def service_time(c, k, t):
        st = steps[k]
        v = c.visits[k]
        c.visits[k] += 1
        r = visit_rng(seed, c.id, k, v)
        u1 = r.next()
        u2 = r.next()
        u_adopt = r.next()
        u_err = r.next()
        c.u_back = r.next()
        c.u_catch = r.next()
        base = st["minutes"] * spread(st["cv"], u1, u2)
        dur = base
        if c.reworking:
            dur = base * rework_effort
        elif k == ai_step:
            potential = base * ai["saving"]
            if u_adopt < ai["adoption"]:
                dur = base - potential + ai["checkMinutes"]
                if u_err < ai["errorRate"]:
                    c.defect = True
                if c.tracked:
                    st_["ai_saved"] += potential
                    st_["ai_check"] += ai["checkMinutes"]
                    c.ai = True
            elif c.tracked:
                st_["ai_lost"] += potential
        if c.tracked:
            c.wait[k] += t - c.enq
            c.touch[k] += dur
        return dur

    def start_delay(c, k, t):
        st = steps[k]
        v = c.visits[k]
        c.visits[k] += 1
        r = visit_rng(seed, c.id, k, v)
        u1 = r.next()
        u2 = r.next()
        u_share = r.next()
        dur = st["minutes"] * spread(st["cv"], u1, u2) if u_share < st["share"] else 0
        if c.tracked:
            c.wait[k] += dur
        push(t + dur, DONE, c.id, k)

    def start(c, k, t):
        busy[k] += 1
        dur = service_time(c, k, t)
        busy_min[k] += overlap(t, t + dur)
        push(t + dur, DONE, c.id, k)

    def finish(c, k, t):
        st = steps[k]
        if st["reworkTo"] >= 0:
            catchable = c.defect and st["reworkTo"] <= ai_step < k
            back = False
            if catchable and c.u_catch < ai["catchRate"]:
                c.defect = False
                back = True
                if c.tracked:
                    st_["ai_back"] += 1
            elif c.u_back < st["reworkRate"]:
                back = True
                if c.tracked:
                    st_["base_back"] += 1
            if back:
                c.reworking = True
                c.rework_check = k
                c.reworks += 1
                enter(c, st["reworkTo"], t)
                return
        if k == n - 1:
            leave(c, t)
        else:
            enter(c, k + 1, t)

    def leave(c, t):
        if not c.tracked:
            return
        st_["open"] -= 1
        lt = t - c.arr
        lead.append(lt)
        if lt <= sla_min:
            st_["within"] += 1
        for j in range(n):
            touch_sum[j] += c.touch[j]
            wait_sum[j] += c.wait[j]
            visit_sum[j] += c.visits[j]
        if c.reworks > 0:
            st_["reworked"] += 1
        if c.defect:
            st_["escaped"] += 1
        if c.ai:
            st_["ai_used"] += 1

    def compact(k):
        if heads[k] > 1024 and heads[k] * 2 > len(queues[k]):
            queues[k] = queues[k][heads[k]:]
            heads[k] = 0

    def start_next(k, t):
        st = steps[k]
        while busy[k] < st["staff"] and heads[k] < len(queues[k]):
            c = queues[k][heads[k]]
            queues[k][heads[k]] = None
            heads[k] += 1
            start(c, k, t)
        compact(k)

    def session(k, t):
        st = steps[k]
        if in_window(t):
            sessions[k] += 1
        clock = t
        count = 0
        while count < st["capacity"] and heads[k] < len(queues[k]):
            c = queues[k][heads[k]]
            queues[k][heads[k]] = None
            heads[k] += 1
            dur = service_time(c, k, clock)
            busy_min[k] += overlap(clock, clock + dur)
            clock += dur
            push(clock, DONE, c.id, k)
            count += 1
        if in_window(t):
            cleared[k] += count
        compact(k)

    arrivals_done = False
    arr_rng = Rng(mix(mix(seed, 0xA77), 1))
    t0 = -math.log(arr_rng.next()) / lam
    if t0 < E:
        push(t0, ARRIVE, 0, 0)
    else:
        arrivals_done = True
    for k in range(n):
        if steps[k]["kind"] == "batch":
            push(next_batch_day(steps[k]["batchDays"], -1) * DAY, BATCH, k, 0)

    while heap:
        t, _q, typ, a, b = heapq.heappop(heap)
        if t > CAP:
            break
        now = t
        if typ == ARRIVE:
            c = _Case(len(cases), now, in_window(now), n)
            cases.append(c)
            if c.tracked:
                st_["tracked"] += 1
                st_["open"] += 1
            enter(c, 0, now)
            nt = now - math.log(arr_rng.next()) / lam
            if nt < E:
                push(nt, ARRIVE, 0, 0)
            else:
                arrivals_done = True
        elif typ == DONE:
            kind = steps[b]["kind"]
            if kind == "team":
                busy[b] -= 1
            finish(cases[a], b, now)
            if kind == "team":
                start_next(b, now)
        else:
            session(a, now)
            push(next_batch_day(steps[a]["batchDays"], _round(now / DAY)) * DAY, BATCH, a, 0)
        if arrivals_done and st_["open"] == 0:
            break

    done = len(lead)
    srt = sorted(lead)
    lead_total = 0
    for x in lead:
        lead_total += x
    step_out = []
    span = E - W
    touch_total = 0
    wait_total = 0
    for k in range(n):
        st = steps[k]
        tm = touch_sum[k] / done if done else 0
        wm = wait_sum[k] / done if done else 0
        touch_total += tm
        wait_total += wm
        util = 0
        if st["kind"] == "team":
            util = busy_min[k] / (st["staff"] * span)
        elif st["kind"] == "batch":
            util = cleared[k] / (sessions[k] * st["capacity"]) if sessions[k] else 0
        step_out.append({
            "name": st["name"], "kind": st["kind"], "staff": st["staff"],
            "touch": tm, "wait": wm, "visits": visit_sum[k] / done if done else 0,
            "utilisation": util, "maxQueue": max_q[k], "perDay": entries[k] / cfg["measureDays"],
            "busyHoursPerDay": busy_min[k] / 60 / cfg["measureDays"],
        })
    lead_mean = lead_total / done if done else 0
    tracked = st_["tracked"]
    return {
        "seed": seed, "aiStep": ai_step,
        "tracked": tracked, "done": done, "open": st_["open"],
        "leadMean": lead_mean,
        "leadP50": quantile(srt, 0.5), "leadP85": quantile(srt, 0.85), "leadP95": quantile(srt, 0.95),
        "leadMax": srt[-1] if done else 0,
        "withinSla": st_["within"] / tracked if tracked else 0,
        "touchTotal": touch_total, "waitTotal": wait_total,
        "flowEfficiency": touch_total / lead_mean if lead_mean > 0 else 0,
        "throughputPerDay": done / cfg["measureDays"],
        "reworkedShare": st_["reworked"] / done if done else 0,
        "aiSendBacksPer100": 100 * st_["ai_back"] / done if done else 0,
        "baseSendBacksPer100": 100 * st_["base_back"] / done if done else 0,
        "escapedPer100": 100 * st_["escaped"] / done if done else 0,
        "aiUsedShare": st_["ai_used"] / done if done else 0,
        "aiSavedPerCase": st_["ai_saved"] / done if done else 0,
        "aiLostPerCase": st_["ai_lost"] / done if done else 0,
        "aiCheckPerCase": st_["ai_check"] / done if done else 0,
        "steps": step_out,
        "leadDays": [x / DAY for x in srt] if keep_lead_times else None,
    }


def bottleneck(result):
    best, bu = -1, -1
    for k, s in enumerate(result["steps"]):
        if s["kind"] == "team" and s["utilisation"] > bu:
            bu = s["utilisation"]
            best = k
    return best


def compare(cfg_in, seed=1, keep_lead_times=False):
    """Without the AI against with it, and where the saved minutes went."""
    cfg = normalise(cfg_in)
    base = simulate(cfg, seed, no_ai=True, keep_lead_times=keep_lead_times)
    with_ai = simulate(cfg, seed, keep_lead_times=keep_lead_times)
    potential = -(with_ai["aiSavedPerCase"] + with_ai["aiLostPerCase"])
    lost = with_ai["aiLostPerCase"]
    check = with_ai["aiCheckPerCase"]
    d_touch = with_ai["touchTotal"] - base["touchTotal"]
    rework = d_touch - (potential + lost + check)
    total = with_ai["leadMean"] - base["leadMean"]
    parts = [
        {"key": "saved", "label": "Time the AI saves if everyone uses it", "value": potential},
        {"key": "lost", "label": "Cases where it is not used", "value": lost},
        {"key": "check", "label": "Checking the AI's work", "value": check},
        {"key": "rework", "label": "Reworking cases sent back", "value": rework},
    ]
    for k, s in enumerate(base["steps"]):
        parts.append({"key": "wait%d" % k, "label": ("" if s["kind"] == "delay" else "Waiting at ") + s["name"],
                      "value": with_ai["steps"][k]["wait"] - s["wait"], "step": k})
    ai = cfg["ai"]
    return {
        "config": cfg, "base": base, "ai": with_ai,
        "pilotClaim": cfg["steps"][ai["step"]]["minutes"] * ai["saving"] if ai["step"] >= 0 else 0,
        "parts": parts, "total": total,
        "complete": base["open"] == 0 and with_ai["open"] == 0,
        "leverage": total / potential if potential < 0 else 0,
        "netTouch": d_touch,
        "fteFreed": -d_touch * cfg["arrivalsPerDay"] / DAY,
        "bottleneckBefore": bottleneck(base), "bottleneckAfter": bottleneck(with_ai),
    }


def fmt_duration(minutes):
    """Same rounding as the app: minutes, hours or working days."""
    a = abs(minutes)
    sign = "-" if minutes < 0 else ""
    if a < 59.5:
        return "%s%d min" % (sign, _round(a))
    if a < DAY - 0.5:
        return "%s%.1f h" % (sign, a / 60)
    return "%s%.1f days" % (sign, a / DAY)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return normalise(json.load(f))
