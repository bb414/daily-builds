"""Make the sample inputs in data/ for fictional final-year students.

Everything here is invented: the students, Brackenmoor University, its module
codes and titles, the cafe, the bar and the rugby club. The generator is
seeded, so it writes the same files every time.

Run:  python tools/make_samples.py

It writes, in the shapes real students have them:

  data/alex/                  one student's own files, ready for --folder
    exam-timetable.csv        a student-portal export (one row per exam)
    topics.csv                40 topics with confidence and size
    availability.csv          a weekly template of hours plus blocked days
    busy-calendar.ics         lectures, seminars, cafe shifts and rugby (weekly
                              repeats, a cancelled event, a moved lecture, a
                              skipped date, all-day entries and a UTC time)
  data/exam-timetable.ics     Alex's exams as a personal exam calendar
  data/exam-timetable.html    the same exams as the portal page, saved from a
                              browser (dates and times in one cell)
  data/messy-timetable.txt    a timetable pasted from a web page: mixed date
                              formats, a room column, a repeated header, a
                              resit still to be confirmed and a blank row
  data/topics-pasted.txt      two modules' topics as a pasted bullet list
  data/template-exams.csv, data/template-topics.csv
  data/sample-project.json    the plan the app opens with: Alex's files planned
                              from Mon 30 Nov 2026, with ten days ticked off
                              (one day missed) as if today were Thu 10 Dec
  data/group/                 a study group of three: Alex, Sam and Priya, each
                              with their own files and plan file (Sam's bar
                              shifts come as a rota CSV, some past midnight)
"""

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.join(ROOT, "companion"))

SEED = 20270111

ALEX_EXAMS = [
    # code, title, date (d, m, y), start, minutes, venue, seat
    ("MGT3104", "Strategic Management", (11, 1, 2027), "09:30", 120, "Great Hall", "G-114"),
    ("ECO3112", "Behavioural Economics", (13, 1, 2027), "14:00", 120, "Sports Centre, Hall B", "B-027"),
    ("FIN3020", "Corporate Finance", (15, 1, 2027), "09:30", 180, "Great Hall", "G-086"),
    ("LAW3207", "Competition and Consumer Law", (19, 1, 2027), "14:00", 120, "Wren Building 1.12", "41"),
    ("DAT3301", "Business Analytics", (22, 1, 2027), "09:30", 150, "Computer Lab 3", "PC-19"),
]
SAM_EXAMS = [
    ("ECO3112", "Behavioural Economics", (13, 1, 2027), "14:00", 120, "Sports Centre, Hall B", "B-131"),
    ("ECO3150", "Econometrics II", (14, 1, 2027), "09:30", 120, "Great Hall", "G-201"),
    ("FIN3020", "Corporate Finance", (15, 1, 2027), "09:30", 180, "Great Hall", "G-090"),
    ("ECO3160", "Development Economics", (18, 1, 2027), "14:00", 120, "Wren Building 1.12", "17"),
]
PRIYA_EXAMS = [
    ("FIN3020", "Corporate Finance", (15, 1, 2027), "09:30", 180, "Great Hall", "G-044"),
    ("LAW3207", "Competition and Consumer Law", (19, 1, 2027), "14:00", 120, "Wren Building 1.12", "8"),
    ("DAT3320", "Machine Learning for Business", (20, 1, 2027), "09:30", 120, "Computer Lab 1", "PC-07"),
    ("DAT3301", "Business Analytics", (22, 1, 2027), "09:30", 150, "Computer Lab 3", "PC-02"),
]

TOPICS = {
    "MGT3104": ["Porter's five forces", "Resource-based view", "Dynamic capabilities", "Corporate strategy and diversification",
                "Mergers and acquisitions", "Strategy in emerging markets", "Blue ocean strategy", "Business models and platforms"],
    "ECO3112": ["Prospect theory", "Mental accounting", "Present bias and discounting", "Nudges and choice architecture",
                "Social preferences and fairness", "Heuristics and biases", "Behavioural finance", "Field experiments"],
    "FIN3020": ["Capital budgeting and NPV", "Cost of capital (WACC)", "Capital structure", "Dividend policy",
                "Real options", "DCF valuation", "Working capital", "Leveraged buyouts"],
    "LAW3207": ["Anti-competitive agreements", "Abuse of dominance", "Merger control", "Market definition",
                "Consumer rights and remedies", "Unfair contract terms", "Digital markets regulation", "Enforcement and fines"],
    "DAT3301": ["Linear regression", "Logistic regression", "Decision trees and forests", "Clustering",
                "Time series forecasting", "Model evaluation", "Data visualisation", "A/B testing"],
    "ECO3150": ["Panel data", "Instrumental variables", "Difference in differences", "Time series and unit roots", "Limited dependent variables", "Maximum likelihood"],
    "ECO3160": ["Growth theories", "Poverty traps", "Microfinance", "Aid effectiveness", "Institutions", "Randomised trials in development"],
    "DAT3320": ["Supervised learning", "Feature engineering", "Overfitting and validation", "Neural networks", "Explainability (SHAP)", "Recommender systems"],
}

# How confident each student feels about each module: lower is weaker.
FEEL = {
    "alex": {"MGT3104": 3.6, "ECO3112": 3.2, "FIN3020": 2.2, "LAW3207": 3.0, "DAT3301": 3.5},
    "sam": {"ECO3112": 3.8, "ECO3150": 2.4, "FIN3020": 2.8, "ECO3160": 3.4},
    "priya": {"FIN3020": 3.6, "LAW3207": 2.4, "DAT3320": 3.0, "DAT3301": 4.0},
}


def write(name, text, newline="\n"):
    path = os.path.join(DATA, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)
    return path


def ddmmyyyy(d):
    return "%02d/%02d/%04d" % d


def exam_csv(exams, candidate):
    rows = ["Candidate Number,Module Code,Module Title,Assessment Type,Exam Date,Start Time,Duration (mins),Venue,Seat Number"]
    for code, title, date, start, mins, venue, seat in exams:
        venue_cell = '"%s"' % venue if "," in venue else venue
        rows.append("%s,%s,%s,Unseen examination,%s,%s,%d,%s,%s" % (candidate, code, title, ddmmyyyy(date), start, mins, venue_cell, seat))
    return "\r\n".join(rows) + "\r\n"


def ics_stamp(d, hhmm):
    return "%04d%02d%02dT%s00" % (d[2], d[1], d[0], hhmm.replace(":", ""))


def exam_ics(exams):
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Brackenmoor University//Exam timetable//EN", "CALSCALE:GREGORIAN"]
    for code, title, date, start, mins, venue, seat in exams:
        h, m = int(start[:2]), int(start[3:])
        end = h * 60 + m + mins
        out += [
            "BEGIN:VEVENT",
            "UID:exam-%s-2027@brackenmoor.example" % code.lower(),
            "DTSTAMP:20261102T090000Z",
            "DTSTART;TZID=Europe/London:%s" % ics_stamp(date, start),
            "DTEND;TZID=Europe/London:%s" % ics_stamp(date, "%02d:%02d" % (end // 60, end % 60)),
            "SUMMARY:%s %s - Examination" % (code, title),
            "LOCATION:%s" % venue.replace(",", "\\,"),
            "DESCRIPTION:Seat %s. Bring your student card." % seat,
            "CATEGORIES:EXAM",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def exam_html(exams):
    """The exam timetable page as a student would save it from the portal ("Save page as")."""
    rows = []
    for code, title, date, start, mins, venue, seat in exams:
        h, m = int(start[:2]), int(start[3:])
        end = h * 60 + m + mins
        rows.append('      <tr class="exam-row"><td><strong>%s</strong></td><td>%s</td><td>%s %02d:%02d&ndash;%02d:%02d</td><td>%s</td><td>%s</td></tr>' % (
            code, title.replace('&', '&amp;'), ddmmyyyy(date), h, m, end // 60, end % 60, venue, seat))
    return "\n".join([
        '<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8"><title>My examinations | Brackenmoor student portal</title>',
        '<style>table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px}</style></head>',
        '<body><nav><a href="#">Home</a> &gt; <a href="#">Assessment</a> &gt; My examinations</nav>',
        '<h1>Examination timetable: January 2027</h1>',
        '<p>Candidate number 2210457. Please arrive 30&nbsp;minutes before the start.</p>',
        '<!-- <tr><td>Old draft row</td></tr> -->',
        '<table id="exams">', '  <thead><tr><th>Module</th><th>Title</th><th>Date and time</th><th>Venue</th><th>Seat</th></tr></thead>', '  <tbody>',
    ] + rows + ['  </tbody>', '</table>', '<footer>Brackenmoor University (invented)</footer></body></html>', ''])


def sam_rota():
    """Sam's bar shifts, exported from the pub's rota app as CSV (some shifts finish after midnight)."""
    rows = ["Shift date,Start,Finish,Role,Hours"]
    shifts = [("04/12/2026", "18:00", "23:30"), ("05/12/2026", "19:00", "01:00"), ("11/12/2026", "18:00", "23:30"), ("12/12/2026", "19:00", "01:00"),
              ("18/12/2026", "17:00", "23:00"), ("19/12/2026", "19:00", "00:30"), ("23/12/2026", "12:00", "18:00"), ("31/12/2026", "20:00", "02:00"),
              ("08/01/2027", "18:00", "23:30"), ("09/01/2027", "19:00", "01:00"), ("16/01/2027", "19:00", "01:00")]
    for d, a, b in shifts:
        h = ((int(b[:2]) * 60 + int(b[3:]) - int(a[:2]) * 60 - int(a[3:])) % 1440) / 60.0
        rows.append("%s,%s,%s,Bar (Fox and Lantern),%s" % (d, a, b, ("%.1f" % h).rstrip("0").rstrip(".")))
    return "\r\n".join(rows) + "\r\n"


def messy_timetable():
    t = "\t"
    lines = [
        "Brackenmoor University  Examination timetable, January 2027",
        "Candidate 2210457    BSc Management and Economics, final year",
        "",
        t.join(["Module", "Title", "Date", "Time", "Length", "Room"]),
        t.join(["MGT3104", "Strategic Management", "Mon 11 Jan 2027", "9.30am", "2 hrs", "Great Hall"]),
        t.join(["ECO3112", "Behavioural Economics", "13/01/2027", "14:00", "2h", "Sports Centre, Hall B"]),
        t.join(["Module", "Title", "Date", "Time", "Length", "Room"]),
        t.join(["FIN3020", "Corporate Finance", "2027-01-15", "09:30", "3 hours", "Great Hall"]),
        "",
        t.join(["LAW3207", "Competition and Consumer Law", "19-Jan-27", "2pm", "120 mins", "Wren Building 1.12"]),
        t.join(["DAT3301", "Business Analytics", "Friday 22nd January 2027", "09:30", "2:30", "Computer Lab 3"]),
        t.join(["MKT2210", "Marketing Research (resit)", "TBC", "TBC", "", "TBC"]),
        "",
    ]
    return "\n".join(lines)


def topics_csv(rng, exams, feel):
    rows = ["Module,Topic,Confidence,Size,Notes"]
    for code, *_rest in exams:
        for name in TOPICS[code]:
            conf = int(min(5, max(1, round(rng.gauss(feel[code], 0.9)))))
            size = rng.choices(["S", "M", "L"], weights=[5, 4, 1])[0]
            note = ""
            if conf <= 1:
                note = "missed the lectures"
            elif size == "L" and conf <= 2:
                note = "long reading list"
            name_cell = '"%s"' % name if "," in name else name
            rows.append("%s,%s,%d,%s,%s" % (code, name_cell, conf, size, note))
    return "\r\n".join(rows) + "\r\n"


def topics_pasted():
    return "\n".join([
        "MGT3104 Strategic Management",
        "- Porter's five forces (4, M)",
        "- Resource-based view (3, M)",
        "- Dynamic capabilities [2/5] [L]",
        "- Blue ocean strategy - conf 4 - small",
        "- Business models and platforms",
        "",
        "Behavioural Economics:",
        "* Prospect theory (2, L)",
        "* Mental accounting (3)",
        "* Nudges and choice architecture, 4, S",
        "* Present bias and discounting (red, 3h)",
        "",
    ]) + "\n"


def availability_csv(rows):
    return "\r\n".join(["Day,From,To,Hours,Note"] + rows) + "\r\n"


ALEX_AVAILABILITY = [
    "Mon,09:00,21:00,6,", "Tue,09:00,21:00,6,", "Wed,09:00,21:00,6,", "Thu,09:00,21:00,6,", "Fri,09:00,21:00,5,",
    "Sat,10:00,20:00,3,cafe shift in the morning", "Sun,10:00,19:00,5,",
    "19/12/2026,14:00,20:00,2,Travelling home", "24/12/2026,,,0,Christmas Eve", "25/12/2026,,,0,Christmas Day",
    "26/12/2026,,,0,Boxing Day", "31/12/2026,10:00,16:00,2,New Year's Eve", "01/01/2027,,,0,New Year's Day",
    "03/01/2027,15:00,21:00,2,Travelling back",
]
SAM_AVAILABILITY = [
    "Weekdays,10:00,22:00,5,", "Sat,12:00,18:00,3,", "Sun,11:00,19:00,4,",
    "24/12/2026 - 27/12/2026,,,0,Family visit", "01/01/2027,,,0,New Year's Day",
]
PRIYA_AVAILABILITY = [
    "Mon,13:30,20:00,4,office job in the morning", "Tue,09:00,20:00,6,", "Wed,13:30,20:00,4,office job in the morning",
    "Thu,09:00,20:00,6,", "Fri,09:00,18:00,5,", "Weekends,10:00,18:00,4,",
    "25/12/2026 - 26/12/2026,,,0,Christmas", "01/01/2027,,,0,New Year's Day",
]


class Cal:
    """A tiny .ics writer for the sample calendars."""

    def __init__(self, name):
        self.name = name
        self.lines = []

    def event(self, uid, start, end, summary, extra=(), tz=True):
        lines = ["BEGIN:VEVENT", "UID:%s@calendar.example" % uid, "DTSTAMP:20261120T120000Z"]
        if tz:
            lines += ["DTSTART;TZID=Europe/London:%s" % start, "DTEND;TZID=Europe/London:%s" % end]
        else:
            lines += ["DTSTART:%s" % start, "DTEND:%s" % end]
        lines.append("SUMMARY:%s" % summary)
        lines += list(extra)
        lines.append("END:VEVENT")
        self.lines.extend(lines)

    def all_day(self, uid, start, end, summary, extra=()):
        self.lines.extend(["BEGIN:VEVENT", "UID:%s@calendar.example" % uid, "DTSTAMP:20261120T120000Z",
                           "DTSTART;VALUE=DATE:%s" % start, "DTEND;VALUE=DATE:%s" % end, "SUMMARY:%s" % summary] + list(extra) + ["END:VEVENT"])

    def text(self):
        head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Example Calendar//Personal//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:%s" % self.name]
        return "\r\n".join(head + self.lines + ["END:VCALENDAR"]) + "\r\n"


UNTIL_TERM = "RRULE:FREQ=WEEKLY;UNTIL=20261211T235959Z"


def alex_calendar():
    c = Cal("Alex (personal)")
    # Weekly teaching from the start of term (Mon 28 Sep 2026) to Fri 11 Dec.
    c.event("lec-mgt3104", "20260928T100000", "20260928T120000", "MGT3104 Lecture", [UNTIL_TERM, "LOCATION:Lecture Theatre A"])
    c.event("lec-eco3112", "20260929T140000", "20260929T160000", "ECO3112 Lecture", [UNTIL_TERM, "LOCATION:Lecture Theatre C"])
    c.event("lec-fin3020", "20260930T090000", "20260930T110000", "FIN3020 Lecture", [UNTIL_TERM, "EXDATE;TZID=Europe/London:20261202T090000", "LOCATION:Lecture Theatre A"])
    c.event("sem-fin3020", "20261001T130000", "20261001T140000", "FIN3020 Seminar", [UNTIL_TERM, "LOCATION:Wren Building 2.04"])
    c.event("lec-law3207", "20261001T100000", "20261001T120000", "LAW3207 Lecture", [UNTIL_TERM, "LOCATION:Law School 1"])
    c.event("lab-dat3301", "20261002T110000", "20261002T130000", "DAT3301 Computer lab", [UNTIL_TERM, "LOCATION:Computer Lab 3"])
    # One lecture moved: the LAW3207 lecture on Thu 3 Dec moves to Fri 4 Dec 14:00.
    c.event("lec-law3207", "20261204T140000", "20261204T160000", "LAW3207 Lecture (moved)", ["RECURRENCE-ID;TZID=Europe/London:20261203T100000", "LOCATION:Law School 1"])
    # Rugby: training on Tuesday evenings until the end of term, and two Wednesday fixtures.
    c.event("rugby-training", "20261006T180000", "20261006T200000", "Rugby training", ["RRULE:FREQ=WEEKLY;COUNT=11", "LOCATION:Brackenmoor playing fields"])
    c.event("rugby-match-1", "20261202T130000", "20261202T180000", "Rugby: away fixture", ["LOCATION:Coach from the sports centre"])
    c.event("rugby-match-2", "20261209T130000", "20261209T173000", "Rugby: home fixture")
    # Cafe shifts: every Saturday morning, except Boxing Day and 2 January.
    c.event("cafe-sat", "20261107T080000", "20261107T140000", "Shift at Wren Lane Coffee",
            ["RRULE:FREQ=WEEKLY;UNTIL=20270116T235959Z", "EXDATE;TZID=Europe/London:20261226T080000,20270102T080000"])
    for i, d in enumerate(["20261203", "20261210", "20261217", "20270107", "20270114"]):
        c.event("cafe-eve-%d" % i, d + "T170000", d + "T210000", "Shift at Wren Lane Coffee (evening)")
    # A careers fair that was cancelled, and a dentist appointment written in UTC.
    c.event("careers-fair", "20261208T100000", "20261208T160000", "Careers fair", ["STATUS:CANCELLED"])
    c.event("dentist", "20270106T110000Z", "20270106T120000Z", "Dentist", tz=False)
    c.event("society-agm", "20270107T180000", "20270107T200000", "Consulting Society AGM", ["LOCATION:Students' Union"])
    # All-day entries: not counted as busy unless you block the day.
    c.all_day("home-xmas", "20261219", "20270104", "Home for Christmas")
    c.all_day("gran-bday", "20261229", "20261230", "Gran's birthday", ["TRANSP:TRANSPARENT"])
    return c.text()


def sam_calendar():
    c = Cal("Sam")
    c.event("sam-eco3150", "20260929T110000", "20260929T130000", "ECO3150 Lecture", [UNTIL_TERM])
    c.event("sam-eco3160", "20261001T150000", "20261001T170000", "ECO3160 Lecture", [UNTIL_TERM])
    c.event("sam-football", "20261007T140000", "20261007T170000", "Football", ["RRULE:FREQ=WEEKLY;UNTIL=20261216T235959Z"])
    return c.text()


def priya_calendar():
    c = Cal("Priya")
    c.event("priya-office", "20261102T090000", "20261102T130000", "Office job", ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20270115T235959Z", "EXDATE;TZID=Europe/London:20261228T090000,20261230T090000"])
    c.event("priya-dat3320", "20260930T140000", "20260930T160000", "DAT3320 Lecture", [UNTIL_TERM])
    c.event("priya-choir", "20261008T190000", "20261008T210000", "Choir", ["RRULE:FREQ=WEEKLY;UNTIL=20270114T235959Z"])
    return c.text()


def main():
    rng = random.Random(SEED)
    os.makedirs(DATA, exist_ok=True)
    # Alex: the student the app opens with.
    write("alex/exam-timetable.csv", exam_csv(ALEX_EXAMS, "2210457"), newline="")
    write("alex/topics.csv", topics_csv(rng, ALEX_EXAMS, FEEL["alex"]), newline="")
    write("alex/availability.csv", availability_csv(ALEX_AVAILABILITY), newline="")
    write("alex/busy-calendar.ics", alex_calendar(), newline="")
    write("exam-timetable.ics", exam_ics(ALEX_EXAMS), newline="")
    write("exam-timetable.html", exam_html(ALEX_EXAMS))
    write("messy-timetable.txt", messy_timetable())
    write("topics-pasted.txt", topics_pasted())
    # The study group: Sam and Priya share some of Alex's modules.
    for who, exams, avail, cal, cand in [("sam", SAM_EXAMS, SAM_AVAILABILITY, sam_calendar(), "2210913"),
                                         ("priya", PRIYA_EXAMS, PRIYA_AVAILABILITY, priya_calendar(), "2211288")]:
        write("group/%s/exam-timetable.csv" % who, exam_csv(exams, cand), newline="")
        write("group/%s/topics.csv" % who, topics_csv(rng, exams, FEEL[who]), newline="")
        write("group/%s/availability.csv" % who, availability_csv(avail), newline="")
        write("group/%s/busy-calendar.ics" % who, cal, newline="")
    write("group/sam/shift-rota.csv", sam_rota(), newline="")
    try:
        import examseason as es
    except ImportError:
        print("Wrote the raw samples; the companion is not available, so the plan files were not made.")
        return
    write("template-exams.csv", es.exam_template(), newline="")
    write("template-topics.csv", es.topic_template(), newline="")
    write("sample-project.json", es.sample_project(DATA), newline="")
    for who, name, student in [("alex", None, None), ("sam", "Sam's January exams", "Sam Okafor (invented), final year economics"),
                               ("priya", "Priya's January exams", "Priya Nandakumar (invented), final year business analytics")]:
        folder = os.path.join(DATA, "alex") if who == "alex" else os.path.join(DATA, "group", who)
        write("group/%s.json" % who, es.member_project(folder, name, student), newline="")
    print("Wrote the samples to data/")


if __name__ == "__main__":
    main()
