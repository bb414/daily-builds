"""Write the synthetic sample exports in data/ from a fixed seed.

Everything here is invented: the trading-challenge team, its two accounts,
the tickers, the index future and every fill. The three exports are laid out
the way trading platforms and brokers lay out their own:

  challenge-equities.csv  a challenge platform's trade history (one row per
                          fill, Buy / Sell / Sell Short / Buy to Cover,
                          cancelled and rejected orders listed too)
  futures-messy.csv       a futures platform's fills, deliberately messy:
                          US dates with AM/PM, partial fills split across
                          rows, fees with dollar signs, exchange fees in
                          rows of their own, cancelled orders, a byte order
                          mark, blank lines, a repeated header and a total row
  dealing-account.csv     a UK share-dealing account's trade history: day
                          first dates, prices in pence, commission and stamp
                          duty in separate columns, no account column, and a
                          first sale of shares bought before the export

It also writes sample-journal.json (the journal notes, stops and settings the
app opens with) and template.csv.

Run:  python tools/make_samples.py
"""

import json
import math
import os
import random
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SEED = 20261128

START = date(2026, 9, 21)   # a Monday: ten weeks to Friday 27 November
END = date(2026, 11, 27)
FUTURES_START = date(2026, 10, 19)
CLOSED = {date(2026, 11, 26)}             # Thanksgiving: the US markets are shut
EARLY_CLOSE = {date(2026, 11, 27): 13 * 3600}

EQ_ACCOUNT = "KES-EQ-0417"
FUT_ACCOUNT = "KES-FUT-0233"
UK_ACCOUNT = "Dealing account"            # the app names the account after the file

# Invented tickers and starting prices.
EQUITIES = [("HGRB", 41.20), ("PLMB", 18.60), ("THBF", 72.40), ("ORSM", 126.50), ("GLBM", 9.85), ("QLSW", 233.10), ("SMSH", 27.30)]
UK_SHARES = [("WMRU", "Whinmoor Utilities plc, Ord 10p", 412.5), ("CPFB", "Copperfold Brewing plc, Ord 5p", 186.0),
             ("THLM", "Thornhallam Mills plc, Ord 25p", 1244.0), ("BRSK", "Bracken & Rook Holdings plc, Ord 1p", 73.4)]

# Setups: (name, chance of a win, smallest and largest winning R, entry window in minutes after 9:30, hold minutes).
EQ_SETUPS = [
    ("Opening range break", 0.56, 1.0, 2.6, (2, 55), (6, 95), 0.30),
    ("Pullback", 0.50, 0.8, 2.0, (35, 330), (10, 120), 0.27),
    ("Gap fade", 0.36, 0.5, 1.3, (1, 25), (2, 22), 0.20),
    ("Breakout", 0.43, 1.2, 3.0, (60, 350), (15, 190), 0.17),
    ("News", 0.45, 0.6, 2.4, (5, 300), (4, 80), 0.06),
]
FUT_SETUPS = [
    ("Opening range break", 0.52, 1.0, 2.2, (1, 50), (5, 80), 0.40),
    ("Pullback", 0.47, 0.9, 2.0, (40, 330), (10, 110), 0.35),
    ("Reversal", 0.35, 1.0, 2.8, (20, 340), (6, 90), 0.25),
]


def trading_days(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5 and d not in CLOSED:
            yield d
        d += timedelta(days=1)


def pick_weighted(rng, items):
    total = sum(i[-1] for i in items)
    x = rng.random() * total
    for item in items:
        x -= item[-1]
        if x <= 0:
            return item
    return items[-1]


def iso_stamp(day, sec):
    return "%s%s" % (day.isoformat(), "" if sec is None else "T%02d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60))


def round_to(x, tick):
    return round(round(x / tick) * tick, 6)


def money(x):
    return "%.2f" % (math.floor(x * 100 + 0.5) / 100)


def price_text(x, dp=2):
    return ("%." + str(dp) + "f") % x


class Book:
    """Collects the generated trades and the journal entries that go with them."""

    def __init__(self):
        self.journal = []

    def note(self, trade_id, setup="", stop="", risk="", mistakes=(), notes=""):
        entry = {"id": trade_id, "setup": setup, "stop": stop, "risk": risk, "target": "", "mistakes": list(mistakes), "notes": notes}
        if setup or stop or risk or mistakes or notes:
            self.journal.append(entry)


def outcome_r(rng, setup, afternoon, mistakes):
    """The R multiple the final exit reaches: wins and losses by setup, made worse by mistakes."""
    p_win, lo, hi = setup[1], setup[2], setup[3]
    p = p_win - (0.10 if afternoon else 0.0)
    if "Chased entry" in mistakes:
        p -= 0.15
    if "Revenge trade" in mistakes:
        p -= 0.12
    if "Added to a loser" in mistakes or "Moved stop" in mistakes:
        return -rng.uniform(1.15, 1.6) if rng.random() < 0.82 else rng.uniform(0.3, 1.0)
    if rng.random() < p:
        r = rng.uniform(lo, hi)
        if "Early exit" in mistakes:
            r = rng.uniform(0.3, 0.6)
        return r
    if rng.random() < 0.18:
        return rng.uniform(-0.25, 0.15)   # scratched near the entry
    return -rng.uniform(0.85, 1.08)


def split_fill(rng, qty, lot):
    """Split an order's quantity into partial fills (whole lots)."""
    if qty < 2 * lot or rng.random() > 0.22:
        return [qty]
    parts = 2 if rng.random() < 0.7 else 3
    cuts = sorted(rng.sample(range(1, qty // lot), min(parts - 1, qty // lot - 1)))
    sizes, last = [], 0
    for c in cuts + [qty // lot]:
        sizes.append((c - last) * lot)
        last = c
    return [s for s in sizes if s > 0]


def equities(rng, book, account=EQ_ACCOUNT, first=START, last=END, over_n=6, tilt_n=3, mistake_scale=1.0, open_at_end=True):
    """A challenge account's equity fills. The defaults make the main sample; the team members use other settings."""
    rows = []
    prices = {s: p for s, p in EQUITIES}
    order_no = [100230]
    busy_until = {}
    equity = 100000.0
    over_days = set(rng.sample(list(trading_days(first, last)), over_n))
    tilt_days = set(rng.sample([d for d in trading_days(first, last) if d not in over_days], tilt_n))

    def next_order():
        order_no[0] += rng.randint(1, 9)
        return "EQ-%d" % order_no[0]

    def commission(q):
        return max(0.35, q * 0.0035)

    def fill_rows(day, sec, symbol, action, qty, price, oid):
        out = []
        parts = split_fill(rng, qty, 10)
        for i, part in enumerate(parts):
            p = price if i == 0 else round_to(price + rng.choice([-0.01, 0.0, 0.01]), 0.01)
            s = sec + (0 if i == 0 else rng.randint(0, 2))
            status = "Filled" if i == len(parts) - 1 else "Partially Filled"
            out.append([account, day, s, symbol, action, part, p, commission(part), oid, status])
        return out

    for day in trading_days(first, last):
        for s in prices:
            prices[s] = round(prices[s] * math.exp(rng.gauss(0.0004, 0.017)), 2)
        close = EARLY_CLOSE.get(day, 16 * 3600)
        n = rng.choice([2, 3, 3, 4, 4, 5])
        if day in over_days:
            n = rng.randint(7, 9)
        if day in tilt_days:
            n = rng.randint(5, 7)
        clock = 9 * 3600 + 30 * 60 + rng.randint(30, 200)
        day_loss = 0
        for k in range(n):
            setup = pick_weighted(rng, EQ_SETUPS)
            lo, hi = setup[4]
            start_sec = 9 * 3600 + 30 * 60 + rng.randint(lo, hi) * 60 + rng.randint(0, 59)
            sec = max(clock, start_sec)
            if sec > close - 20 * 60:
                break
            symbol = rng.choice([s for s, _ in EQUITIES])
            if busy_until.get(symbol, (day, 0)) > (day, sec):
                continue
            mistakes = []
            roll = rng.random()
            if roll < 0.07 * mistake_scale:
                mistakes.append("Added to a loser")
            elif roll < 0.12 * mistake_scale:
                mistakes.append("Moved stop")
            elif roll < 0.20 * mistake_scale:
                mistakes.append("Chased entry")
            elif roll < 0.25 * mistake_scale:
                mistakes.append("Early exit")
            if day in tilt_days and day_loss < -900 and rng.random() < 0.8:
                mistakes.append("Revenge trade")
            oversized = rng.random() < 0.05 or "Revenge trade" in mistakes
            if oversized:
                mistakes.append("Oversized")
            direction = 1 if rng.random() < (0.35 if setup[0] == "Gap fade" else 0.66) else -1
            ref = prices[symbol]
            entry = round_to(ref * (1 + rng.gauss(0, 0.006)), 0.01)
            stop_dist = round_to(max(0.05, entry * rng.uniform(0.004, 0.011)), 0.01)
            risk_cash = equity * 0.01 * (rng.uniform(1.6, 2.3) if oversized else rng.uniform(0.55, 0.98))
            qty = int(risk_cash / stop_dist / 10) * 10
            qty = min(qty, int(70000 / entry / 10) * 10)
            if qty < 10:
                continue
            afternoon = sec >= 14 * 3600
            r = outcome_r(rng, setup, afternoon, mistakes)
            hold = rng.randint(setup[5][0], setup[5][1]) * 60 + rng.randint(0, 59)
            swing = setup[0] in ("Breakout", "Pullback") and rng.random() < 0.05 and r > 0
            open_side = "Buy" if direction > 0 else "Sell Short"
            close_side = "Sell" if direction > 0 else "Buy to Cover"
            stop = round_to(entry - direction * stop_dist, 0.01)
            oid = next_order()
            trade_rows = fill_rows(day, sec, symbol, open_side, qty, entry, oid)
            trade_id = "%s|%s|%s" % (account, symbol, iso_stamp(day, trade_rows[0][2]))
            t = trade_rows[-1][2] + rng.randint(20, 240)
            total_in = qty
            avg_in = entry
            # Scale in: to a winner normally, against the position for the "added to a loser" mistake.
            if "Added to a loser" in mistakes or rng.random() < 0.12:
                add_q = int(qty * rng.uniform(0.3, 0.6) / 10) * 10
                if add_q >= 10:
                    move = -0.55 if "Added to a loser" in mistakes else 0.45
                    add_price = round_to(entry + direction * move * stop_dist, 0.01)
                    trade_rows += fill_rows(day, t, symbol, open_side, add_q, add_price, next_order())
                    avg_in = (entry * qty + add_price * add_q) / (qty + add_q)
                    total_in = qty + add_q
                    t = trade_rows[-1][2] + rng.randint(60, 600)
            final = round_to(entry + direction * r * stop_dist, 0.01)
            exit_day = day
            exit_sec = min(close - 60, sec + hold)
            if exit_sec <= t:
                exit_sec = t + rng.randint(30, 200)
            if swing:
                later = [d for d in trading_days(day + timedelta(days=1), END)][:3]
                if later:
                    exit_day = later[rng.randint(0, len(later) - 1)]
                    exit_sec = rng.randint(10 * 3600, 15 * 3600)
            # Scale out on some winners: half at +1R, the rest at the final price.
            if r > 1.1 and rng.random() < 0.45 and total_in >= 20:
                half = int(total_in / 2 / 10) * 10
                part_price = round_to(entry + direction * stop_dist, 0.01)
                mid_sec = t + max(60, (exit_sec - t) // 2 if exit_day == day else rng.randint(600, 3600))
                trade_rows += fill_rows(day, min(mid_sec, close - 120), symbol, close_side, half, part_price, next_order())
                rest = total_in - half
            else:
                rest = total_in
            trade_rows += fill_rows(exit_day, exit_sec, symbol, close_side, rest, final, next_order())
            rows += trade_rows
            pnl = direction * (final - avg_in) * total_in
            day_loss += pnl
            equity += pnl
            busy_until[symbol] = (exit_day, exit_sec + 60)
            clock = sec + rng.randint(4, 40) * 60
            # Journal: most trades have a setup and a stop; a few gaps, and more in the latest week.
            latest = day >= date(2026, 11, 23)
            tagged = rng.random() < (0.72 if latest else 0.93)
            has_stop = "Moved stop" in mistakes or rng.random() < (0.7 if latest else 0.9)
            notes = ""
            if "Added to a loser" in mistakes:
                notes = rng.choice(["Averaged down instead of taking the stop.", "Thought it would bounce. It did not.", "Added below my entry; should have cut it."])
            elif "Moved stop" in mistakes:
                notes = rng.choice(["Moved the stop when it got close.", "Widened the stop after entry."])
            elif "Revenge trade" in mistakes:
                notes = "Trying to win back the morning's loss."
            elif r > 2:
                notes = rng.choice(["Clean break with volume.", "Held for the target as planned.", ""])
            if not tagged:
                book.note(trade_id, stop=price_text(stop) if has_stop else "")
            else:
                use_money = has_stop and rng.random() < 0.08
                book.note(trade_id, setup=setup[0], stop="" if use_money or not has_stop else price_text(stop),
                          risk=money(stop_dist * qty) if use_money else "", mistakes=mistakes, notes=notes)
        # A cancelled or rejected order most days.
        if rng.random() < 0.55:
            symbol = rng.choice([s for s, _ in EQUITIES])
            sec = rng.randint(9 * 3600 + 40 * 60, 15 * 3600)
            status = "Rejected" if rng.random() < 0.15 else "Cancelled"
            rows.append([account, day, sec, symbol, rng.choice(["Buy", "Sell Short"]), rng.randint(1, 30) * 10, round_to(prices[symbol] * 0.99, 0.01), 0.0, next_order(), status])
    if open_at_end:
        # One position is still open when the export ends: bought on the last afternoon, held over the weekend.
        symbol = "GLBM"
        entry = round_to(prices[symbol] * 1.004, 0.01)
        sec = 12 * 3600 + 41 * 60 + 7
        rows += fill_rows(END, sec, symbol, "Buy", 2000, entry, next_order())
        book.note("%s|%s|%s" % (account, symbol, iso_stamp(END, sec)), setup="Breakout", stop=price_text(round_to(entry - 0.22, 0.01)),
                  notes="Holding over the weekend; stop stays in.")
    rows.sort(key=lambda r: (r[1], r[2]))
    lines = ["Account,Trade Date,Time (ET),Symbol,Action,Quantity,Price,Commission,Currency,Order ID,Status"]
    for r in rows:
        acct, day, sec, symbol, action, qty, price, comm, oid, status = r
        filled = status in ("Filled", "Partially Filled")
        lines.append(",".join([acct, day.isoformat(), "%02d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60), symbol, action, str(qty),
                               price_text(price), money(comm) if filled else "0.00", "USD", oid, status]))
    return "\n".join(lines) + "\n"


def futures(rng, book):
    rows = []
    level = 5112.25
    order_no = [50010]
    busy = (FUTURES_START, 0)
    equity = 50000.0
    tilt_days = set(rng.sample(list(trading_days(FUTURES_START, END)), 2))

    def next_order():
        order_no[0] += rng.randint(1, 4)
        return "F-%d" % order_no[0]

    def fills(day, sec, symbol, side, qty, price, oid, mult):
        out = []
        parts = [qty]
        if qty >= 2 and rng.random() < 0.3:
            a = rng.randint(1, qty - 1)
            parts = [a, qty - a]
        for i, part in enumerate(parts):
            p = price if i == 0 else round_to(price + rng.choice([-0.25, 0.0, 0.25]), 0.25)
            s = sec + (0 if i == 0 else rng.randint(0, 3))
            status = "Filled" if i == len(parts) - 1 else "Partially Filled"
            out.append(("fill", oid, day, s, symbol, side, part, p, 2.04 * part if mult == 20 else 0.62 * part, status))
        # Exchange fees come through as rows of their own for some orders.
        if rng.random() < 0.5:
            out.append(("fee", oid, day, sec + 1, symbol, "", "", "", (1.20 if mult == 20 else 0.35) * qty, ""))
        return out

    for day in trading_days(FUTURES_START, END):
        level = round_to(level * math.exp(rng.gauss(0.0003, 0.011)), 0.25)
        close = EARLY_CLOSE.get(day, 16 * 3600) - 15 * 60
        n = rng.choice([1, 2, 2, 3, 3, 4])
        if day in tilt_days:
            n = 6
        clock = 9 * 3600 + 30 * 60 + rng.randint(20, 120)
        day_pnl = 0
        for k in range(n):
            setup = pick_weighted(rng, FUT_SETUPS)
            lo, hi = setup[4]
            sec = max(clock, 9 * 3600 + 30 * 60 + rng.randint(lo, hi) * 60 + rng.randint(0, 59))
            if sec > close - 30 * 60 or (day, sec) < busy:
                continue
            micro = rng.random() < 0.3
            symbol, mult = ("MLKZ6", 2) if micro else ("LKFZ6", 20)
            mistakes = []
            if rng.random() < 0.09:
                mistakes.append("Moved stop")
            elif rng.random() < 0.08:
                mistakes.append("Added to a loser")
            if day in tilt_days and day_pnl < -400:
                mistakes.append("Revenge trade")
            direction = 1 if rng.random() < 0.55 else -1
            entry = round_to(level + rng.gauss(0, 9), 0.25)
            stop_pts = round_to(rng.uniform(6, 16), 0.25)
            risk_cash = equity * 0.01 * (rng.uniform(1.5, 2.2) if "Revenge trade" in mistakes else rng.uniform(0.6, 0.98))
            qty = max(1, int(risk_cash / (stop_pts * mult)))
            r = outcome_r(rng, setup, sec >= 14 * 3600, mistakes)
            hold = rng.randint(setup[5][0], setup[5][1]) * 60 + rng.randint(0, 59)
            open_side, close_side = ("Buy", "Sell") if direction > 0 else ("Sell", "Buy")
            oid = next_order()
            trade = fills(day, sec, symbol, open_side, qty, entry, oid, mult)
            trade_id = "%s|%s|%s" % (FUT_ACCOUNT, symbol, iso_stamp(day, trade[0][3]))
            t = trade[-1][3] + rng.randint(30, 300)
            total, avg = qty, entry
            if "Added to a loser" in mistakes:
                add_q = max(1, qty // 2)
                add_price = round_to(entry - direction * 0.5 * stop_pts, 0.25)
                trade += fills(day, t, symbol, open_side, add_q, add_price, next_order(), mult)
                avg = (entry * qty + add_price * add_q) / (qty + add_q)
                total = qty + add_q
            final = round_to(entry + direction * r * stop_pts, 0.25)
            exit_sec = min(close, sec + hold)
            if exit_sec <= t:
                exit_sec = t + rng.randint(60, 400)
            trade += fills(day, exit_sec, symbol, close_side, total, final, next_order(), mult)
            rows += trade
            pnl = direction * (final - avg) * total * mult
            day_pnl += pnl
            equity += pnl
            busy = (day, exit_sec + 90)
            clock = exit_sec + rng.randint(5, 45) * 60
            stop = round_to(entry - direction * stop_pts, 0.25)
            latest = day >= date(2026, 11, 23)
            if rng.random() < (0.75 if latest else 0.92):
                book.note(trade_id, setup=setup[0], stop=price_text(stop) if rng.random() < 0.9 else "", mistakes=mistakes,
                          notes="Gave back the morning." if "Revenge trade" in mistakes else "")
        if rng.random() < 0.5:
            sec = rng.randint(9 * 3600 + 35 * 60, 15 * 3600)
            rows.append(("cancel", next_order(), day, sec, "LKFZ6", rng.choice(["Buy", "Sell"]), 0, "", 0, "Canceled"))
    rows.sort(key=lambda r: (r[2], r[3], 0 if r[0] != "fee" else 1))

    def us_stamp(day, sec):
        h = sec // 3600
        ap = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return "%d/%d/%d %d:%02d:%02d %s" % (day.month, day.day, day.year, h12, sec // 60 % 60, sec % 60, ap)

    def q(text):
        return '"%s"' % text

    header = ",".join(q(h) for h in ["Order #", "Fill Time", "Instrument", "Description", "B/S", "Type", "Filled Qty", "Avg Fill Price", "Fees", "Account", "Status"])
    lines = ["\ufeff" + header]
    total_qty, total_fees = 0, 0.0
    for i, r in enumerate(rows):
        kind, oid, day, sec, symbol, side, qty, price, fee, status = r
        desc = ("Larkfield 50 Index, Dec 2026" if symbol == "LKFZ6" else "Micro Larkfield 50, Dec 2026")
        if kind == "fill":
            total_qty += qty
            total_fees += fee
            price_cell = "{:,.2f}".format(price)
            cells = [oid, us_stamp(day, sec), symbol, desc, side, "Trade", str(qty), price_cell, "$" + money(fee), FUT_ACCOUNT, status]
        elif kind == "fee":
            total_fees += fee
            cells = [oid, us_stamp(day, sec), symbol, desc, "", "Exchange fee", "", "", "$" + money(fee), FUT_ACCOUNT, ""]
        else:
            cells = [oid, us_stamp(day, sec), symbol, desc, side, "Trade", "0", "", "$0.00", FUT_ACCOUNT, status]
        lines.append(",".join(q(c) for c in cells))
        if i == len(rows) // 2:
            lines.append("")
            lines.append(header)       # the export was saved in two pages
        elif rng.random() < 0.02:
            lines.append("")
    lines.append(",".join(q(c) for c in ["Total", "", "", "", "", "", str(total_qty), "", "$" + money(total_fees), "", ""]))
    return "\r\n".join(lines) + "\r\n"


def dealing(rng, book):
    rows = []
    ref_no = [0]

    def ref():
        ref_no[0] += 1
        return "D%05d" % (31000 + ref_no[0] * 7)

    def row(day, sec, code, side, qty, pence):
        consideration = qty * pence / 100.0
        commission = 5.95
        stamp = math.floor(consideration * 0.005 * 100 + 0.5) / 100 if side == "Bought" else 0.0
        total = consideration + commission + stamp if side == "Bought" else consideration - commission
        settle = day + timedelta(days=2 if day.weekday() < 3 else 4)
        name = [n for c, n, _ in UK_SHARES if c == code][0]
        return [day, sec, settle, ref(), name, code, side, qty, pence, consideration, commission, stamp, total]

    # The first line sells shares bought before this export starts.
    rows.append(row(date(2026, 9, 23), 10 * 3600 + 14 * 60, "WMRU", "Sold", 150, 418.0))
    days = list(trading_days(START + timedelta(days=4), END - timedelta(days=3)))
    starts = sorted(rng.sample(days, 13))
    free = {}
    for d in starts:
        code, _, base = rng.choice(UK_SHARES)
        if free.get(code, START) > d:
            continue
        sec = rng.randint(8 * 3600 + 15 * 60, 16 * 3600) // 60 * 60
        pence = round(base * rng.uniform(0.92, 1.08), 1)
        stop_pct = rng.uniform(0.045, 0.08)
        qty = max(20, int(55 / (pence / 100.0 * stop_pct) / 10) * 10)
        rows.append(row(d, sec, code, "Bought", qty, pence))
        trade_id = "%s|%s|%s" % (UK_ACCOUNT, code, iso_stamp(d, sec))
        hold = rng.randint(3, 24)
        exit_day = d + timedelta(days=hold)
        while exit_day.weekday() >= 5:
            exit_day += timedelta(days=1)
        r = rng.uniform(0.8, 2.6) if rng.random() < 0.55 else -rng.uniform(0.7, 1.05)
        exit_p = round(pence * (1 + r * stop_pct), 1)
        if exit_day <= END:
            if rng.random() < 0.3:
                part = qty // 2
                mid = d + timedelta(days=max(1, hold // 2))
                while mid.weekday() >= 5:
                    mid += timedelta(days=1)
                rows.append(row(mid, rng.randint(9 * 3600, 16 * 3600) // 60 * 60, code, "Sold", part, round(pence * (1 + stop_pct), 1)))
                qty -= part
            rows.append(row(exit_day, rng.randint(9 * 3600, 16 * 3600) // 60 * 60, code, "Sold", qty, exit_p))
        free[code] = exit_day + timedelta(days=1)
        stop = round(pence * (1 - stop_pct) / 100.0, 3)
        book.note(trade_id, setup="Swing", stop="%.3f" % stop, notes=rng.choice(["Weekly chart breakout.", "Bought the pullback to the 50-day average.", ""]))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)    # this broker lists the newest first
    lines = ["Trade date,Settlement date,Reference,Description,Symbol,Buy/Sell,Quantity,Price (p),Consideration (£),Commission (£),Stamp duty (£),Total (£)"]
    for r in rows:
        day, sec, settle, reference, name, code, side, qty, pence, cons, comm, stamp, total = r
        lines.append(",".join([
            "%02d/%02d/%d %02d:%02d" % (day.day, day.month, day.year, sec // 3600, sec // 60 % 60), settle.strftime("%d/%m/%Y"), reference,
            '"%s"' % name, code, side, str(qty), "%.1f" % pence, money(cons), money(comm), money(stamp), money(total)]))
    return "\n".join(lines) + "\n"


def settings():
    return {
        "base": "USD", "dateOrder": "auto",
        "fx": [{"currency": "GBP", "rate": "1.27"}],
        "multipliers": [{"symbol": "LKF", "value": "20"}, {"symbol": "MLK", "value": "2"}],
        "accounts": [
            {"name": EQ_ACCOUNT, "start": "100000", "currency": "USD", "longOnly": False},
            {"name": FUT_ACCOUNT, "start": "50000", "currency": "USD", "longOnly": False},
            {"name": UK_ACCOUNT, "start": "5000", "currency": "GBP", "longOnly": True},
        ],
        "rules": {
            "maxRiskPct": {"on": True, "value": "1", "unit": ""},
            "maxDailyLoss": {"on": True, "value": "2", "unit": "pct"},
            "maxDrawdown": {"on": True, "value": "6", "unit": "pct"},
            "maxTradesPerDay": {"on": True, "value": "6", "unit": ""},
            "tradingWindow": {"on": True, "value": "09:35-15:45", "unit": ""},
            "coolOff": {"on": True, "value": "3", "unit": ""},
            "noAddingToLoser": {"on": True, "value": "", "unit": ""},
            "maxLossR": {"on": True, "value": "1.5", "unit": ""},
            "needPlannedRisk": {"on": True, "value": "", "unit": ""},
        },
        "setups": ["Opening range break", "Pullback", "Gap fade", "Breakout", "Reversal", "News", "Swing"],
        "mistakes": ["Chased entry", "Moved stop", "Added to a loser", "Oversized", "Early exit", "Revenge trade", "No plan"],
    }


def template_csv():
    """The template, exactly as the app's model writes it."""
    rows = [
        ["Date", "Time", "Account", "Symbol", "Side", "Quantity", "Price", "Commission", "Currency", "Order ID"],
        ["2026-11-23", "09:41:05", "Challenge", "HGRB", "Buy", "300", "41.27", "1.50", "USD", "A-1001"],
        ["2026-11-23", "09:41:06", "Challenge", "HGRB", "Buy", "200", "41.28", "1.00", "USD", "A-1001"],
        ["2026-11-23", "10:12:44", "Challenge", "HGRB", "Sell", "500", "41.90", "2.50", "USD", "A-1002"],
        ["2026-11-23", "11:02:10", "Challenge", "PLMB", "Sell Short", "400", "18.62", "2.00", "USD", "A-1003"],
        ["2026-11-23", "11:40:31", "Challenge", "PLMB", "Buy to Cover", "400", "18.31", "2.00", "USD", "A-1004"],
        ["2026-11-24", "14:30:00", "Futures", "LKFZ6", "Buy", "2", "5112.25", "4.10", "USD", "F-2001"],
        ["2026-11-24", "14:55:12", "Futures", "LKFZ6", "Sell", "2", "5120.50", "4.10", "USD", "F-2002"],
    ]
    return "\ufeff" + "\r\n".join(",".join(r) for r in rows) + "\r\n"


def write(name, text):
    with open(os.path.join(DATA, name), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


# Three invented team members, four weeks each, for the companion's team review.
TEAM = [
    ("priya", "KES-EQ-0418", 20, dict(over_n=0, tilt_n=0, mistake_scale=0.3)),
    ("tom", "KES-EQ-0419", 13, dict(over_n=7, tilt_n=2, mistake_scale=1.3)),
    ("kasia", "KES-EQ-0420", 16, dict(over_n=1, tilt_n=1, mistake_scale=1.6)),
]
TEAM_START = date(2026, 11, 2)


def team_samples():
    for folder, account, seed, cfg in TEAM:
        book = Book()
        text = equities(random.Random(SEED + seed), book, account=account, first=TEAM_START, last=END, open_at_end=False, **cfg)
        os.makedirs(os.path.join(DATA, "team", folder), exist_ok=True)
        write(os.path.join("team", folder, "fills.csv"), text)
        st = settings()
        st["accounts"] = [{"name": account, "start": "100000", "currency": "USD", "longOnly": False}]
        st["fx"], st["multipliers"] = [], []
        project = {"app": "round-trips", "version": 1, "saved": "2026-11-28", "settings": st, "sources": [],
                   "journal": sorted(book.journal, key=lambda e: e["id"]), "fills": [], "feeRows": [], "seq": 0}
        write(os.path.join("team", folder, "journal.json"), json.dumps(project, indent=1, ensure_ascii=False) + "\n")


def weekly_samples(text):
    """Two overlapping exports of the equities account, as a weekly job would receive them."""
    lines = text.splitlines(keepends=True)
    head, body = lines[0], lines[1:]
    os.makedirs(os.path.join(DATA, "weekly"), exist_ok=True)
    first = [l for l in body if l.split(",")[1] <= "2026-11-20"]
    second = [l for l in body if "2026-11-16" <= l.split(",")[1]]
    write(os.path.join("weekly", "export-2026-11-20.csv"), head + "".join(first))
    write(os.path.join("weekly", "export-2026-11-27.csv"), head + "".join(second))


def main():
    os.makedirs(DATA, exist_ok=True)
    rng = random.Random(SEED)
    book = Book()
    eq_text = equities(rng, book)
    fut_text = futures(random.Random(SEED + 1), book)
    uk_text = dealing(random.Random(SEED + 2), book)
    write("challenge-equities.csv", eq_text)
    write("futures-messy.csv", fut_text)
    write("dealing-account.csv", uk_text)
    write("template.csv", template_csv())
    team_samples()
    weekly_samples(eq_text)
    journal = sorted(book.journal, key=lambda e: e["id"])
    project = {"app": "round-trips", "version": 1, "saved": "2026-11-28", "settings": settings(), "sources": [], "journal": journal,
               "fills": [], "feeRows": [], "seq": 0}
    write("sample-journal.json", json.dumps(project, indent=1, ensure_ascii=False) + "\n")
    print("Wrote the samples to data/ (%d journal entries)" % len(journal))


if __name__ == "__main__":
    sys.exit(main())
