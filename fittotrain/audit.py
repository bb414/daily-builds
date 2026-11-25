"""Readiness audit for a real (anonymised) CRM export.

Without knowing the truth, it runs the same checks as the browser app, then
fits the same win-probability model three ways (a random hold-out, the newest
closed deals, and a random hold-out after the four repairs in
model.repair_crm) and looks for fields that only predict well on records
edited after the deal closed.
"""

from datetime import timedelta

from . import model

MIN_CLOSED = 60


def _fit_and_score(train, test):
    if len(train) < 20 or len(test) < 10:
        return None
    ytr = [1 if r["status"] == "won" else 0 for r in train]
    yte = [1 if r["status"] == "won" else 0 for r in test]
    if len(set(ytr)) < 2 or len(set(yte)) < 2:
        return None
    means = model.field_means(train)
    fit = model.fit_logistic([model.feature_row(r, means) for r in train], ytr)
    p = model.predict(fit["beta"], [model.feature_row(r, means) for r in test])
    amt = [r["amount"] for r in test]
    ev = model.evaluate(p, yte, amt, amt)
    ev["trainSize"] = len(train)
    ev["beta"] = fit["beta"]
    return ev


def backtests(records, seed, as_of_day):
    """Random and time-ordered hold-outs on the export as it stands, and the
    random hold-out again after the four repairs in model.repair_crm."""
    closed = [r for r in records if model.labelled(r)]
    rep = model.repair_crm({"history": records, "live": []}, as_of_day)
    if len(closed) < MIN_CLOSED:
        return {"random": None, "time": None, "repaired": None, "closed": len(closed), "steps": rep["steps"]}
    train, test = model.split_closed(records, seed)
    by_time = sorted(closed, key=lambda r: (r["close"], r["id"]))
    cut = int(len(by_time) * (1 - model.TEST_SHARE))
    rtrain, rtest = model.split_closed(rep["history"], seed)
    return {
        "random": _fit_and_score(train, test),
        "time": _fit_and_score(by_time[:cut], by_time[cut:]),
        "repaired": _fit_and_score(rtrain, rtest),
        "closed": len(closed),
        "steps": rep["steps"],
    }


def field_signal(records):
    """How well each scoring field alone separates wins from losses, on records
    edited after closing versus records left untouched."""
    closed = [r for r in records if model.labelled(r)]
    out = []
    for f in model.FIELDS:
        row = {"field": f, "label": model.FIELD_LABELS[f]}
        for name, group in (("all", closed),
                            ("edited", [r for r in closed if r["editedAfterClose"]]),
                            ("untouched", [r for r in closed if not r["editedAfterClose"]])):
            pairs = [(r[f], 1 if r["status"] == "won" else 0) for r in group if r[f] is not None]
            row[name] = model.auc([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 20 else None
            row[name + "N"] = len(pairs)
        a, b = row["edited"], row["untouched"]
        row["gap"] = abs(a - 0.5) - abs(b - 0.5) if (a is not None and b is not None) else None
        row["suspect"] = row["gap"] is not None and row["gap"] > 0.1
        out.append(row)
    return out


def audit_export(records, info, as_of=None, seed=2026):
    """Run every check on records read by crmcsv.read_export."""
    if as_of is None:
        as_of_day = (info["latest"] - info["origin"]).days + 1
        as_of_date = info["latest"] + timedelta(days=1)
    else:
        as_of_day = (as_of - info["origin"]).days
        as_of_date = as_of
    crm = {"history": records, "live": []}
    checks = model.audit_crm(crm, as_of=as_of_day)
    rows = list(checks["rows"])
    if info.get("bad_amounts"):
        share = info["bad_amounts"] / len(records)
        rows.insert(0, {"key": "amounts", "check": "Missing or zero amounts", "value": share,
                        "light": model.light(share, 0.02, 0.1),
                        "detail": "of records have no usable amount (the median stands in for the model)"})
    if not info.get("has_edit_flag"):
        for row in rows:
            if row["key"] == "retrofill":
                row["value"] = None
                row["light"] = "na"
                row["detail"] = "add an edited_after_close column from field history to run this check"
    missing_fields = [model.FIELD_LABELS[f] for f, ok in info["fields_present"].items() if not ok]
    closed = sum(1 for r in records if model.labelled(r))
    wins = sum(1 for r in records if r["status"] == "won")
    return {
        "asOf": as_of_date.isoformat(),
        "rows": rows,
        "blankByField": checks["blankByField"],
        "records": len(records),
        "closed": closed,
        "winRate": wins / closed if closed else None,
        "missingFields": missing_fields,
        "backtests": backtests(records, seed, as_of_day),
        "fieldSignal": field_signal(records) if info.get("has_edit_flag") else None,
        "hasEditFlag": bool(info.get("has_edit_flag")),
    }
