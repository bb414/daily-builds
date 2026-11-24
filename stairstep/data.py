"""Reading and writing weekly sales as CSV, so the same analysis runs on your own data.

Format: one row per product, store and week.

    week,store,product,units[,promo][,event_<name>...]

- week: whole numbers 1, 2, 3 ... with no gaps; at least 112 weeks (two years of
  history plus the 52 weeks being tested, plus a few weeks of warm-up).
- promo: 1 in a week the product is on promotion (optional).
- event_<name>: 1 in weeks affected by a festival or event (optional, as many as
  you like). Each becomes a feature of the AI model.

The last 52 weeks are the test year.
"""

import csv

from .model import YEAR

MIN_WEEKS = 2 * YEAR + 8


class DataError(ValueError):
    pass


def write_csv(data, path):
    """Write a dataset (for example a synthetic one) in the format above."""
    event_cols = ["event_" + e["id"] for e in data["events"]]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["week", "store", "product", "units", "promo"] + event_cols)
        for p, sku in enumerate(data["skus"]):
            for s, store in enumerate(data["stores"]):
                for t in range(data["weeks"]):
                    w.writerow([t + 1, store["id"], sku["id"], data["sales"][p][s][t], data["promo"][p][t]]
                               + [e["flags"][t] for e in data["events"]])


def _whole(value, what, line):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DataError("Line %d: %s should be a number, not %r." % (line, what, value)) from None
    if number != int(number) or number < 0:
        raise DataError("Line %d: %s should be a whole number of 0 or more, not %r." % (line, what, value))
    return int(number)


def read_csv(path):
    """Read weekly sales in the format above into the dataset structure the model uses."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        missing = [c for c in ("week", "store", "product", "units") if c not in columns]
        if missing:
            raise DataError("The file needs these columns: %s." % ", ".join(missing))
        event_cols = [c for c in columns if c.startswith("event_") and len(c) > 6]
        rows = list(reader)
    if not rows:
        raise DataError("The file has no rows.")
    skus, stores, cells, weeks_seen = [], [], {}, set()
    promo, flags = {}, {c: {} for c in event_cols}
    for i, r in enumerate(rows, start=2):
        week = _whole(r["week"], "week", i)
        if week < 1:
            raise DataError("Line %d: weeks start at 1." % i)
        store, product = (r["store"] or "").strip(), (r["product"] or "").strip()
        if not store or not product:
            raise DataError("Line %d: store and product cannot be empty." % i)
        if product not in skus:
            skus.append(product)
        if store not in stores:
            stores.append(store)
        key = (product, store, week)
        if key in cells:
            raise DataError("Line %d: a second row for %s in %s, week %d." % (i, product, store, week))
        cells[key] = _whole(r["units"], "units", i)
        weeks_seen.add(week)
        if r.get("promo") not in (None, "") and _whole(r["promo"], "promo", i):
            promo[(product, week)] = 1
        for c in event_cols:
            if r.get(c) not in (None, "") and _whole(r[c], c, i):
                flags[c][week] = 1
    weeks = max(weeks_seen)
    if weeks < MIN_WEEKS:
        raise DataError("The file has %d weeks; at least %d are needed (two years of history and a test year)."
                        % (weeks, MIN_WEEKS))
    if len(weeks_seen) != weeks:
        raise DataError("Weeks must run from 1 to %d with no gaps." % weeks)
    expected = len(skus) * len(stores) * weeks
    if len(cells) != expected:
        raise DataError("Every product needs a row for every store and week: %d rows are missing."
                        % (expected - len(cells)))
    return {
        "weeks": weeks,
        "testStart": weeks - YEAR,
        "skus": [{"id": p, "name": p} for p in skus],
        "stores": [{"id": s, "name": s} for s in stores],
        "sales": [[[cells[(p, s, t + 1)] for t in range(weeks)] for s in stores] for p in skus],
        "promo": [[promo.get((p, t + 1), 0) for t in range(weeks)] for p in skus],
        "events": [{"id": c[6:], "event": c[6:], "offset": 0, "weight": 1,
                    "flags": [flags[c].get(t + 1, 0) for t in range(weeks)]} for c in event_cols],
        "synthetic": False,
    }
