"""Make the synthetic sample statements in data/.

Everything here is invented: the account holder, every company and every
amount. The files are laid out the way real bank exports are (a signed amount
column, separate money out and money in columns, a few lines of account
details before the header, ISO timestamps with a byte order mark) so the
import is tested on the shapes people actually download. One file is
deliberately messy.

Run:  python tools/make_samples.py
The random seed is fixed, so the files come out the same every time.
"""

import csv
import datetime as dt
import io
import json
import os
import random

SEED = 20261128
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")

# England and Wales bank holidays over the sample period.
HOLIDAYS = {dt.date(2025, 12, 25), dt.date(2025, 12, 26), dt.date(2026, 1, 1), dt.date(2026, 4, 3),
            dt.date(2026, 4, 6), dt.date(2026, 5, 4), dt.date(2026, 5, 25), dt.date(2026, 8, 31),
            dt.date(2026, 12, 25), dt.date(2026, 12, 28)}

START = dt.date(2025, 12, 1)
END = dt.date(2026, 11, 27)


def working(d):
    while d.weekday() >= 5 or d in HOLIDAYS:
        d += dt.timedelta(days=1)
    return d


def month_days(start, end, dom, roll):
    """Dates on a day of the month from start to end, rolled to working days if asked."""
    out = []
    y, m = start.year, start.month
    while True:
        last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
        d = dt.date(y, m, min(dom, last))
        if roll:
            d = working(d)
        if d > end:
            break
        if d >= start:
            out.append(d)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def every(start, end, days):
    out, d = [], start
    while d <= end:
        out.append(d)
        d += dt.timedelta(days=days)
    return out


def last_friday(y, m):
    d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    while d.weekday() != 4:
        d -= dt.timedelta(days=1)
    while d in HOLIDAYS or d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def money(pence):
    return "%d.%02d" % (abs(pence) // 100, abs(pence) % 100)


class Account:
    def __init__(self, name):
        self.name = name
        self.rows = []  # (date, pence, description, type, category, note)

    def add(self, date, pence, desc, kind="", category="", note=""):
        self.rows.append((date, pence, desc, kind, category, note))

    def sorted(self):
        return sorted(self.rows, key=lambda r: (r[0], -r[1] if r[1] > 0 else 0, r[2]))


def build(rng):
    truth = {"series": [], "candidates": [], "income": []}
    cur = Account("Current account")
    card = Account("Credit card")
    app = Account("Spending app")

    def plant(acc, dates, amounts, desc, kind, expect=None, category=""):
        for d, a in zip(dates, amounts):
            acc.add(d, -a, desc(d) if callable(desc) else desc, kind, category)
        if expect:
            expect = dict(expect)
            expect.setdefault("count", len(dates))
            expect["account"] = acc.name
            truth["series"].append(expect)

    # ---- Current account: bills, subscriptions and a few traps ----
    rent = month_days(START, END, 1, True)
    plant(cur, rent, [52500] * len(rent), "HARBOUR LETTINGS RENT FLAT 2", "Standing order",
          {"name": "Harbour Lettings Rent", "cadence": "monthly", "typical": 52500, "kind": "fixed", "category": "housing"})

    energy_dates = month_days(START, END, 12, True)
    energy = []
    for d in energy_dates:
        winter = {12: 7140, 1: 7410, 2: 6980, 3: 5820, 4: 4730, 5: 3990, 6: 3810, 7: 3810, 8: 3810, 9: 4260, 10: 5310, 11: 6420}[d.month]
        energy.append(winter + rng.randint(-60, 60))
    plant(cur, energy_dates, energy, "BRIGHTSPARK ENERGY", "Direct debit",
          {"name": "Brightspark Energy", "cadence": "monthly", "kind": "variable", "category": "energy"})

    bb = month_days(START, END, 20, True)
    plant(cur, bb, [2400 if d < dt.date(2026, 4, 1) else 2640 for d in bb], "HILLTOP BROADBAND", "Direct debit",
          {"name": "Hilltop Broadband", "cadence": "monthly", "typical": 2640, "kind": "stepped", "category": "telecoms", "flags": ["rise"]})

    sim = month_days(START, END, 5, True)
    plant(cur, sim, [1200] * len(sim), "MOBI-MOTO SIM ONLY", "Direct debit",
          {"name": "Mobi-moto Sim Only", "cadence": "monthly", "typical": 1200, "kind": "fixed", "category": "telecoms"})

    gym = month_days(START, END, 3, False)
    plant(cur, gym, [2499] * len(gym), lambda d: "CARD PAYMENT TO IRONWORKS GYM ON %02d %s" % (d.day, d.strftime("%b").upper()), "Card payment",
          {"name": "Ironworks Gym", "cadence": "monthly", "typical": 2499, "kind": "fixed", "category": "gym", "flags": ["double"], "count": len(gym) + 1})
    cur.add(dt.date(2026, 3, 4), -2499, "CARD PAYMENT TO IRONWORKS GYM ON 04 MAR", "Card payment")  # charged twice

    cover = month_days(START, END, 8, False)
    plant(cur, cover, [499] * len(cover), "GADGETGUARD PHONE COVER", "Card payment",
          {"name": "Gadgetguard Phone Cover", "cadence": "monthly", "typical": 499, "kind": "fixed", "category": "insurance"})

    cur.add(dt.date(2026, 2, 18), -8640, "FENWICK MUTUAL INSURANCE", "Direct debit")
    truth["candidates"].append({"name": "Fenwick Mutual Insurance", "amount": 8640, "cadence": "yearly"})

    savings = month_days(START, END, 28, True)
    plant(cur, savings, [5000] * len(savings), "SAVINGS TRANSFER", "Standing order",
          {"name": "Savings Transfer", "cadence": "monthly", "typical": 5000, "kind": "fixed", "category": "savings"})

    charity = month_days(START, END, 15, True)
    plant(cur, charity, [500] * len(charity), "RIVERWATCH TRUST", "Direct debit",
          {"name": "Riverwatch Trust", "cadence": "monthly", "typical": 500, "kind": "fixed", "category": "charity"})

    prime = month_days(START, END, 23, False)
    plant(cur, prime, [899] * len(prime), lambda d: "PARCELPOINT PRIME*%s" % "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5)), "Card payment",
          {"name": "Parcelpoint Prime", "cadence": "monthly", "typical": 899, "kind": "fixed", "category": "memberships"})
    for _ in range(9):
        d = START + dt.timedelta(days=rng.randint(0, (END - START).days))
        cur.add(d, -rng.randint(699, 4599), "PARCELPOINT MKTPLACE*%s" % "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5)), "Card payment")

    cloud = month_days(dt.date(2026, 1, 1), END, 11, False)
    plant(cur, cloud, [299] * len(cloud), "APPHAVEN.COM/BILL", "Card payment",
          {"name": "Apphaven.com/bill", "cadence": "monthly", "typical": 299, "kind": "fixed", "category": "other", "flags": ["same-payee"]})
    puzzle = month_days(dt.date(2026, 6, 1), END, 26, False)
    plant(cur, puzzle, [999] * len(puzzle), "APPHAVEN.COM/BILL", "Card payment",
          {"name": "Apphaven.com/bill", "cadence": "monthly", "typical": 999, "kind": "fixed", "category": "other", "flags": ["same-payee"]})

    tv = month_days(START, dt.date(2026, 7, 31), 17, False)
    plant(cur, tv, [699] * len(tv), "PIXELBOX TV", "Card payment",
          {"name": "Pixelbox TV", "cadence": "monthly", "typical": 699, "kind": "fixed", "category": "tv", "status": "stopped"})

    music = month_days(START, END, 9, False)
    plant(cur, music, [1099 if d < dt.date(2026, 6, 1) else 1199 for d in music], "TUNEWAVE MUSIC", "Card payment",
          {"name": "Tunewave Music", "cadence": "monthly", "typical": 1199, "kind": "stepped", "category": "music", "flags": ["rise"]})

    veg = [d for d in every(dt.date(2026, 9, 3), END, 7) if d != dt.date(2026, 10, 22)]
    plant(cur, veg, [1550] * len(veg), "FIELDFARE VEG BOX", "Card payment",
          {"name": "Fieldfare Veg Box", "cadence": "weekly", "typical": 1550, "kind": "fixed", "category": "food", "flags": ["new"]})

    clean = every(dt.date(2026, 1, 9), END, 14)
    plant(cur, clean, [1800] * len(clean), "TIDYUP CLEANING", "Card payment",
          {"name": "Tidyup Cleaning", "cadence": "fortnightly", "typical": 1800, "kind": "fixed", "category": "household"})

    bike = every(dt.date(2026, 1, 14), END, 28)
    plant(cur, bike, [900] * len(bike), "CAMPUS BIKE HIRE", "Card payment",
          {"name": "Campus Bike Hire", "cadence": "four-weekly", "typical": 900, "kind": "fixed", "category": "transport"})

    cur.add(dt.date(2026, 3, 9), -7188, "QUILLHOST ANNUAL PLAN", "Card payment")
    truth["candidates"].append({"name": "Quillhost Annual Plan", "amount": 7188, "cadence": "yearly"})

    # Income.
    for y, m in [(2025, 12)] + [(2026, k) for k in range(1, 12)]:
        d = last_friday(y, m)
        if START <= d <= END:
            cur.add(d, rng.randint(34000, 42000), "CAMPUS CAFE PAYROLL", "Bank credit")
    truth["income"].append({"name": "Campus Cafe Payroll", "cadence": "monthly"})
    for d, a in [(dt.date(2026, 1, 12), 160233), (dt.date(2026, 4, 20), 160233), (dt.date(2026, 9, 21), 165010)]:
        cur.add(d, a, "MAINTENANCE LOAN INSTALMENT", "Bank credit")

    # Everyday spending that must not be mistaken for regular payments.
    day = START
    while day <= END:
        if rng.random() < 0.35:
            cur.add(day, -rng.choice([280, 320, 320, 340, 365, 420]), "BEAN AND BARLEY", "Card payment")
        if rng.random() < 0.28:
            cur.add(day, -rng.randint(450, 4800), "GREENGATE SUPERMARKET", "Card payment")
        if rng.random() < 0.06:
            cur.add(day, -rng.choice([250, 250, 500]), "CITYLINK BUSES", "Card payment")
        if rng.random() < 0.04:
            cur.add(day, -rng.randint(1100, 2600), "NOODLE NOOK TAKEAWAY", "Card payment")
        if rng.random() < 0.03:
            cur.add(day, -rng.choice([2000, 3000, 4000]), "CASH WITHDRAWAL", "Cash machine")
        if rng.random() < 0.025:
            cur.add(day, -rng.randint(800, 6400), "RAILWAY TICKETS ONLINE", "Card payment")
        if rng.random() < 0.05:
            cur.add(day, -rng.choice([1500, 2000, 2500, 3000]), "TO SPENDING APP", "Transfer")
        day += dt.timedelta(days=1)

    # ---- Credit card (paid out / paid in, details above the header) ----
    cstart, cend = dt.date(2026, 6, 1), dt.date(2026, 11, 25)
    sc = month_days(dt.date(2026, 9, 1), cend, 22, False)
    plant(card, sc, [899] * len(sc), "STREAMCRATE.TV LONDON GB", "",
          {"name": "Streamcrate.tv", "cadence": "monthly", "typical": 899, "kind": "fixed", "category": "tv", "flags": ["overlap", "new"]})
    cl = month_days(cstart, cend, 7, False)
    plant(card, cl, [179] * len(cl), "CLOUDLOCKER STORAGE", "",
          {"name": "Cloudlocker Storage", "cadence": "monthly", "typical": 179, "kind": "fixed", "category": "software"})
    news = month_days(cstart, cend, 14, False)
    plant(card, news, [100 if d < dt.date(2026, 9, 1) else 899 for d in news], "THE DAILY LANTERN DIGITAL", "",
          {"name": "The Daily Lantern", "cadence": "monthly", "typical": 899, "kind": "stepped", "category": "news", "flags": ["intro"]})
    card.add(dt.date(2026, 7, 14), -3999, "CHESSMATE PREMIUM ANNUAL", "")
    truth["candidates"].append({"name": "Chessmate Premium Annual", "amount": 3999, "cadence": "yearly"})
    d = cstart
    while d <= cend:
        if rng.random() < 0.08:
            card.add(d, -rng.randint(900, 8900), rng.choice(["NORTHLINE RAIL", "PAGEFOLD BOOKS", "THREADWORK CLOTHING", "SKYLARK HOSTELS"]), "")
        d += dt.timedelta(days=1)
    # Monthly repayment by Direct Debit from the current account.
    month_spend = {}
    for r in card.rows:
        month_spend[(r[0].year, r[0].month)] = month_spend.get((r[0].year, r[0].month), 0) - r[1]
    for (y, m), spend in sorted(month_spend.items()):
        pay_day = working(dt.date(y + (m == 12), m % 12 + 1, 25))
        if pay_day > END:
            continue
        cur.add(pay_day, -spend, "STUDENT CARD REPAYMENT", "Direct debit")
        if pay_day <= cend:
            card.add(pay_day, spend, "PAYMENT RECEIVED - THANK YOU", "")

    # ---- Spending app (Money Out / Money In, ISO dates, notes) ----
    astart, aend = dt.date(2026, 8, 1), END
    rh = month_days(dt.date(2026, 8, 1), aend, 2, False)
    plant(app, rh, [599] * len(rh), "Reelhouse+", "",
          {"name": "Reelhouse+", "cadence": "monthly", "typical": 599, "kind": "fixed", "category": "tv", "flags": ["overlap"]}, "Entertainment")
    ll = month_days(dt.date(2026, 9, 1), aend, 1, False)
    plant(app, ll, [100, 1199, 1199][:len(ll)], "LingoLeap Language", "",
          {"name": "Lingoleap Language", "cadence": "monthly", "typical": 1199, "kind": "stepped", "category": "learning", "flags": ["intro", "new"]}, "Education")
    for r in list(cur.rows):
        if r[2] == "TO SPENDING APP" and r[0] >= astart:
            app.add(r[0], -r[1], "Top up from current account", "", "Transfers", "")
    d = astart
    notes = ["Lunch with team, split later", "", "", "Birthday present", "", "Society social, paid for 3"]
    while d <= aend:
        if rng.random() < 0.3:
            app.add(d, -rng.randint(250, 1650), rng.choice(["Corner Deli", "The Rusty Kettle", "Campus Union Shop", "Fold & Press Printing"]), "", "Eating out", rng.choice(notes))
        d += dt.timedelta(days=1)
    return cur, card, app, truth


def write_current(cur, path):
    bal = 64215
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Date", "Type", "Description", "Amount", "Balance"])
    for d, p, desc, kind, _, _ in cur.sorted():
        bal += p
        w.writerow([d.strftime("%d/%m/%Y"), kind, desc, ("-" if p < 0 else "") + money(p), ("-" if bal < 0 else "") + money(bal)])
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(out.getvalue())


def write_card(card, path):
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    out.write("Account name:,Student credit card\r\n")
    out.write("Card number:,************4417\r\n")
    out.write("Statement period:,01/06/2026 to 25/11/2026\r\n")
    out.write("\r\n")
    w.writerow(["Date", "Description", "Card member", "Paid out", "Paid in"])
    for d, p, desc, _, _, _ in card.sorted():
        w.writerow([d.strftime("%d %b %Y"), desc, "A HOLDER", "£" + money(p) if p < 0 else "", "£" + money(p) if p > 0 else ""])
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(out.getvalue())


def write_app(app, path, rng):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Date", "Time", "Name", "Category", "Money Out", "Money In", "Notes"])
    for d, p, desc, _, cat, note in app.sorted():
        t = "%02d:%02d:%02d" % (rng.randint(7, 22), rng.randint(0, 59), rng.randint(0, 59))
        w.writerow([d.isoformat(), t, desc, cat or "General", "-" + money(p) if p < 0 else "", money(p) if p > 0 else "", note])
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("﻿" + out.getvalue())


def write_messy(cur, path, rng):
    """The current account again, exported from somewhere else and then mangled."""
    rows = [r for r in cur.sorted() if r[0] >= dt.date(2026, 10, 1)]
    lines = ["Statement export generated 28/11/2026,,,,", ",,,,", "Posted,Details,Ref,Amount,Extra"]
    fmts = ["%d/%m/%Y", "%-d %b %Y", "%Y-%m-%d", "%d/%m/%y"]
    for i, (d, p, desc, kind, _, _) in enumerate(rows):
        date_text = d.strftime(rng.choice(fmts))
        style = i % 5
        a = money(p)
        if p < 0:
            amount = ["-" + a, "(" + a + ")", a + " DR", "£" + a + "-", "-£" + a][style]
        else:
            amount = [a, "+" + a, a + " CR", "£" + a, a][style]
        if "," in amount:
            amount = '"' + amount + '"'
        details = desc.lower() if i % 7 == 3 else desc
        if desc == "BEAN AND BARLEY" and i % 4 == 0:
            details = '"BEAN AND\nBARLEY"'
        elif "," in details:
            details = '"' + details + '"'
        lines.append(",".join([date_text, details, kind.upper()[:3] if kind else "", amount, ""]))
        if i == 12:
            lines.append("")
        if i == 30:
            lines.append("Posted,Details,Ref,Amount,Extra")
    lines.insert(9, "TBC,PENDING CARD PAYMENT,,-12.00,")
    lines.insert(20, "14/10/2026,REFUND QUERY,,n/a,")
    lines.insert(25, '32/10/2026,"CORRUPT, ROW",,-1.00,')
    lines.append(",Total,,,")
    lines.append(",,,,")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("﻿" + "\r\n".join(lines) + "\r\n")


def write_ofx(cur, path, rng):
    """A savings account as an OFX download (the older SGML form, as most banks still send it)."""
    rows = []
    for d, p, desc, kind, _, _ in cur.sorted():
        if desc == "SAVINGS TRANSFER":
            rows.append((d, -p, "SAVINGS TRANSFER FROM CURRENT", "XFER"))
    month = dt.date(2025, 12, 31)
    balance = 120000
    while month <= END:
        interest = max(1, balance * 3 // 1200)
        rows.append((month, interest, "INTEREST PAID", "INT"))
        balance += interest + 5000
        nxt = month + dt.timedelta(days=1)
        month = dt.date(nxt.year + (nxt.month == 12), nxt.month % 12 + 1, 1) - dt.timedelta(days=1)
    rows.append((dt.date(2026, 1, 19), -20000, "TRANSFER TO CURRENT", "XFER"))
    rows.sort()
    out = ["OFXHEADER:100", "DATA:OFXSGML", "VERSION:102", "SECURITY:NONE", "ENCODING:USASCII", "CHARSET:1252",
           "COMPRESSION:NONE", "OLDFILEUID:NONE", "NEWFILEUID:NONE", "",
           "<OFX>", "<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20261128090000<LANGUAGE>ENG</SONRS></SIGNONMSGSRSV1>",
           "<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS>",
           "<STMTRS><CURDEF>GBP<BANKACCTFROM><BANKID>000000<ACCTID>00004417<ACCTTYPE>SAVINGS</BANKACCTFROM>",
           "<BANKTRANLIST><DTSTART>20251201<DTEND>20261127"]
    for i, (d, p, desc, kind) in enumerate(rows):
        out += ["<STMTTRN>", "<TRNTYPE>" + kind, "<DTPOSTED>" + d.strftime("%Y%m%d") + "000000[0:GMT]",
                "<TRNAMT>" + ("-" if p < 0 else "") + money(p), "<FITID>%08d" % (i + 1), "<NAME>" + desc, "</STMTTRN>"]
    out += ["</BANKTRANLIST>", "<LEDGERBAL><BALAMT>%s<DTASOF>20261127</LEDGERBAL>" % money(balance), "</STMTRS></STMTTRNRS></BANKMSGSRSV1>", "</OFX>"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(out) + "\r\n")


def write_qif(path, rng):
    """A joint bills account kept by housemates, as a QIF file with Quicken's apostrophe years."""
    rows = []
    for d in month_days(dt.date(2026, 4, 1), END, 1, True):
        rows.append((d, -11800, "DOWNSHIRE COUNCIL TAX", "DD"))
    for d in month_days(dt.date(2026, 2, 1), END, 6, True):
        rows.append((d, -3140, "WESTWATER WATER SERVICES", "DD"))
    for d in month_days(dt.date(2026, 2, 1), END, 1, False):
        rows.append((d - dt.timedelta(days=rng.randint(1, 4)), 7500, "FROM HOUSEMATES BILLS POT", ""))
    rows.sort()
    out = ["!Type:Bank"]
    for d, p, desc, num in rows:
        out += ["D%02d/%02d'%02d" % (d.day, d.month, d.year % 100), "T" + ("-" if p < 0 else "") + money(p), "P" + desc]
        if num:
            out.append("N" + num)
        out.append("^")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(out) + "\r\n")


TEMPLATE = [
    ["Date", "Description", "Type", "Amount", "Balance"],
    ["01/11/2026", "HARBOUR LETTINGS RENT", "Standing order", "-525.00", "812.40"],
    ["03/11/2026", "IRONWORKS GYM", "Card payment", "-24.99", "787.41"],
    ["12/11/2026", "BRIGHTSPARK ENERGY", "Direct debit", "-58.20", "729.21"],
    ["27/11/2026", "CAMPUS CAFE PAYROLL", "Bank credit", "412.50", "1141.71"],
]


def main():
    os.makedirs(DATA, exist_ok=True)
    rng = random.Random(SEED)
    cur, card, app, truth = build(rng)
    write_current(cur, os.path.join(DATA, "current-account.csv"))
    write_card(card, os.path.join(DATA, "credit-card.csv"))
    write_app(app, os.path.join(DATA, "spending-app.csv"), rng)
    write_messy(cur, os.path.join(DATA, "messy-export.csv"), rng)
    # A second random stream, so adding these files leaves the ones above unchanged.
    rng2 = random.Random(SEED + 1)
    write_ofx(cur, os.path.join(DATA, "savings-account.ofx"), rng2)
    write_qif(os.path.join(DATA, "bills-account.qif"), rng2)
    with open(os.path.join(DATA, "template.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("﻿" + "\r\n".join(",".join(r) for r in TEMPLATE) + "\r\n")
    with open(os.path.join(DATA, "sample-truth.json"), "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=1)
        f.write("\n")
    print("Wrote sample statements to", DATA)


if __name__ == "__main__":
    main()
