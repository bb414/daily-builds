"""Proves the Python companion and the browser model give exactly the same answers.

Every check runs the same inputs through both: the browser model (taken from
the built app/index.html) through tests/js_bridge.js under Node, and the
Python package directly. Exported files are compared byte for byte. The tests
are skipped, with a message, when Node is not installed.
"""

import json
import random
import unittest

from helpers import AS_OF, M, NODE, first_difference, run_bridge, run_python, sample, sample_input

FRAGMENTS = [
    "In 2019, 45% of 3,000 firms (Smith & Jones, 2020a; Brown et al., 2018, p. 4) said 'it is by far the best option'.",
    "See https://example.com/a_b_c for the data, or www.kestleford-repair.org.uk/report.",
    "The Data Protection Act 2018 applies, and GDPR fines reach \u20ac20 million or 4% of turnover.",
    "Dr. A. B. Smith said: \u201cnever again will we do it this way\u201d.",
    "U.K. sales rose 3.5 times between the 1990s and the 21st century.",
    "Great results \U0001F680 here, with caf\u00e9 \ufb01nances in \u0130stanbul and \u017f.",
    "As shown\u00b9 in the m\u00b2 units, the figure rose in 2021\u00b2.",
    "**Bold claim** with _italics_, `code`, a [link](http://x.org/page) and ![an image](a.png).",
    "<p>A paragraph with <em>markup</em> and &amp; entities &#169; here.</p><br>",
    "Sure! Here's the revised version of your paragraph:",
    "About XX% of people agree [Insert citation here], as of my last update.",
    "The constructor of hasOwnProperty toString valueOf is __proto__ prototype.",
    "Costs fell from \u00a31.5bn to $3 million, or 1,2345 units at 0.50 each and 12.0% interest.",
    "Studies show that everyone always benefits; it is widely accepted that it is proven.",
    "Lindqvist (2020) argues that repair is the only answer, according to experts.",
    "Households save an average of \u00a3320 a year (Eastmoor Institute for Circular Practice, 2022).",
    "One in five students said the dose of 20 mg was harmless for patients with anxiety.",
    "The University of Eastmoor and the Kestleford Borough Council signed a contract in March 2024.",
    "Prof Maren Haldane noted that the tax returns were recently audited [2, 4-6].",
    "It doubled, then halved; a third of the 1,200 households (n.d.) replied.",
    "\u2014 an em dash line \u2014 and \u2013 an en dash, plus \u2026 an ellipsis.",
    "As Ms Rowan Tilsley put it, \"repair is one of the most practical things a consumer can do\" (Haldane, 2021, p. 14).",
    "The first repair caf\u00e9 in the county opened in Brinmouth in 2014.",
    "Short.",
    "e.g. this starts lower case and i.e. continues, etc. Then it ends.",
    "Footfall on Market Street rose by 9% on repair caf\u00e9 Saturdays (Brinmouth Borough Council, 2022).",
    "\t  Tabs\tand\u00a0non-breaking\u2009spaces\u200b and soft\u00adhyphens.  ",
    "Volunteers are not legally liable under the Consumer Rights Act, the Court said in 2031.",
]

REF_LINES = [
    "Smith, J. and Jones, K. (2020a) 'A title here', Journal of Things, 3(2), pp. 10-20. doi:10.5555/jot.2020.3",
    "Brown, A. et al. (2018). Another title. International Journal of Research Studies.",
    "Haldane, M. (2021) *Mending the market*. Kestleford: Wren Lane Press.",
    "[3] Kestleford Repair Network (2024) Annual report. Available at: htps://kestleford.example/report",
    "4. Vance, E. (n.d.) Community repair. [Author, Year].",
    "Pemberton, L. (2031) Right to repair. London: Fallow Books. https://www.fallow books.co.uk/rtr",
    "Quinlan, R. (1750) 'Old trade', Review of Community Enterprise, 7(1), 61-45. DOI: 10.1234/xxxx",
    "Lindqvist, A. (2020) 'Spare parts', Journal of Household Material Flows, 15, 1-9.",
    "- Osei, P. (2019) Waste. Report for the Council. www.example.org/waste",
]

TRICKY = "\u00a0\u200b\t\r\n\u2028\u201c\u201d\u2018\u2019*_#>|[]()-\u00e9\u00b9\U0001F600"


def mutate(rng, text):
    out = []
    for ch in text:
        r = rng.random()
        if ch.isdigit() and r < 0.15:
            out.append(str(rng.randint(0, 9)))
        elif r < 0.01:
            out.append(rng.choice(TRICKY))
        elif r < 0.015:
            continue
        else:
            out.append(ch)
    return "".join(out)


def make_doc(rng, n_min=4, n_max=22):
    pool = FRAGMENTS + [s for s in M.split_sentences(sample("ai-draft.md").replace("\n", " "))]
    sents = [rng.choice(pool) for _ in range(rng.randint(n_min, n_max))]
    parts, para = [], []
    for s in sents:
        para.append(mutate(rng, s) if rng.random() < 0.4 else s)
        if rng.random() < 0.3:
            parts.append((rng.choice(["", "", "## ", "- ", "> ", "1. "])) + " ".join(para))
            para = []
    if para:
        parts.append(" ".join(para))
    text = "\n\n".join(parts)
    if rng.random() < 0.6:
        refs = rng.sample(REF_LINES, rng.randint(1, len(REF_LINES)))
        text += "\n\n" + rng.choice(["## References", "Bibliography", "**References**", "Sources:"]) + "\n\n" + "\n".join(
            mutate(rng, r) if rng.random() < 0.3 else r for r in refs)
    if rng.random() < 0.3:
        text += "\n\n[^1]: Smith, J. (2020) A footnote source.\n[^2]: Brown (2018) Another."
    return text


def edit_doc(rng, text):
    lines = text.split("\n")
    out = []
    for ln in lines:
        r = rng.random()
        if r < 0.15:
            continue
        if r < 0.45:
            ws = ln.split(" ")
            for _ in range(rng.randint(1, 4)):
                if ws:
                    ws[rng.randrange(len(ws))] = rng.choice(["new", "own", "words", "here", "14", "often", "may"])
            ln = " ".join(ws)
        out.append(ln)
        if rng.random() < 0.15:
            out.append(rng.choice(FRAGMENTS))
    return "\n".join(out)


@unittest.skipUnless(NODE, "Node.js is not installed, so the browser model cannot be run")
class Agreement(unittest.TestCase):
    def compare(self, jobs):
        js = run_bridge(jobs)
        py = run_python(jobs)
        for i, (a, b) in enumerate(zip(js, py)):
            self.assertNotIn("error", a, a.get("error"))
            diff = first_difference(a, b)
            self.assertIsNone(diff, "job %d (%s): %s" % (i, jobs[i]["fn"], diff))
        return js

    def test_samples_give_identical_analyses(self):
        inputs = [
            sample_input(),
            sample_input(final=False),
            sample_input(notes=False, prompt=False),
            {"draft": sample("messy-paste.txt"), "notes": sample("notes.md"), "asOf": AS_OF},
            {"draft": sample("drafts/refurbished-laptops-briefing.md"), "asOf": AS_OF},
            dict(sample_input(), references=sample("references.txt")),
            {"draft": "", "final": "", "asOf": AS_OF},
            {"draft": "", "final": sample("final-version.md"), "asOf": AS_OF},
        ]
        self.compare([{"fn": "analyse", "args": [x]} for x in inputs])

    def test_exported_files_are_byte_identical(self):
        project = json.loads(sample("sample-project.json"))
        state = {"project": project["project"], "sessions": project["sessions"], "checks": project["checks"],
                 "refChecks": project["refChecks"], "asOf": AS_OF}
        inp = dict(project["texts"], asOf=AS_OF)
        all_checked = dict(state, checks={c["key"]: {"status": "verified", "note": 'Seen, p. 4, "quoted"'} for c in M.analyse(inp)["claims"]})
        jobs = [{"fn": "outputs", "args": [inp, state]}, {"fn": "outputs", "args": [inp, all_checked]},
                {"fn": "outputs", "args": [inp, {"project": {}, "sessions": [], "asOf": AS_OF}]},
                {"fn": "outputs", "args": [{"draft": sample("messy-paste.txt"), "asOf": AS_OF}, {"project": {"person": "=cmd|' /C calc'!A0"}}]}]
        js = self.compare(jobs)
        # the project file a Python user builds opens in the app unchanged
        self.assertEqual(js[0]["ok"]["projectFile"], sample("sample-project.json"))

    def test_random_documents(self):
        rng = random.Random(2611)
        jobs = []
        for i in range(70):
            draft = make_doc(rng)
            final = edit_doc(rng, draft) if rng.random() < 0.7 else ""
            notes = make_doc(rng, 2, 8) if rng.random() < 0.5 else ""
            prompt = rng.choice(["", "Write with statistics and Harvard references and a quote.", "Summarise this."])
            refs = "\n".join(rng.sample(REF_LINES, 3)) if rng.random() < 0.2 else ""
            jobs.append({"fn": "analyse", "args": [{"draft": draft, "final": final, "notes": notes, "prompt": prompt,
                                                   "references": refs, "asOf": AS_OF}]})
        self.compare(jobs)

    def test_random_documents_exports(self):
        rng = random.Random(7)
        jobs = []
        for i in range(15):
            draft = make_doc(rng)
            inp = {"draft": draft, "final": edit_doc(rng, draft), "notes": "", "prompt": "", "references": "", "asOf": AS_OF}
            claims = M.analyse(inp)["claims"]
            checks = {c["key"]: {"status": rng.choice(M.STATUSES), "note": rng.choice(["", "p. 2", "x,y \"z\""])} for c in claims}
            sessions = [{"date": rng.choice(["2026-11-0%d" % rng.randint(1, 9), "5/11/2026", "nonsense", ""]), "tool": rng.choice(["A", "B, C", ""]),
                         "purpose": rng.choice(["Draft", "=SUM(A1)", "Check \"this\""]), "prompt": "p", "used": "u", "changed": "", "checked": "",
                         "minutes": rng.choice(["5", "", 7]), "person": rng.choice(["", "Ana"]), "assignment": rng.choice(["", "Essay"])} for _ in range(rng.randint(0, 4))]
            state = {"project": {"title": "T", "assignment": rng.choice(["", "Essay"]), "person": rng.choice(["", "Ana"]),
                                 "level": rng.choice(["none", "assisted", "bogus"]), "date": rng.choice(["", "3 Dec 2026", "soon"])},
                     "sessions": sessions, "checks": checks, "refChecks": {}, "asOf": AS_OF}
            jobs.append({"fn": "outputs", "args": [inp, state]})
        self.compare(jobs)

    def test_dates(self):
        dates = ["2026-11-05", "05/11/2026", "5/11/26", "11/25/2026", "31/13/2026", "29/02/2028", "29/02/2027", "5 Nov 2026",
                 "5th November 2026", "Thursday, 5 November 2026", "Nov 5, 2026", "November 5th 2026", "2026/11/05", "05.11.2026",
                 "05-11-2026 14:03:11", "2026-11-05T10:00:00Z", "5 Sept 2026", "5 Noo 2026", "", "  ", "soon", "1/1/70", "1/1/69",
                 "0/1/2026", "2026-02-30", "\u0665/11/2026", "5\n11\n2026", "3,Dec,2026"]
        self.compare([{"fn": "parseDate", "args": [d]} for d in dates])

    def test_sentence_splitting_and_words(self):
        texts = [f for f in FRAGMENTS] + ["A. B. Smith et al. (2019) found it. Then (p. 4) more.", "Ends with no stop", "Wait... What? Yes!",
                                          "In 2023. 85 volunteers.", "Mr Brown vs. Mrs Green. No. 5 is next.", "x" * 300, ""]
        self.compare([{"fn": "splitSentences", "args": [t]} for t in texts] + [{"fn": "words", "args": [t]} for t in texts]
                     + [{"fn": "scanSentence", "args": [t]} for t in texts] + [{"fn": "contentWords", "args": [t]} for t in texts])

    def test_session_logs(self):
        logs = [sample("session-log.csv"), sample("session-log-template.csv"), sample("team/team-log-ana.csv"),
                sample("team/team-log-dev.csv"), sample("team/team-log-sam.csv"),
                "\ufeffDate;Tool;Purpose\r\n1/2/2026;\"A; B\";\"multi\nline\"\r\n\r\n",
                "When\tAI\tWhy\tMins\n2026-01-01\tTool X\tDraft\t1:30\n,,,\n2026-13-01\tY\t\tabc\n",
                "Name,Age\nAna,20\n", "", "\n\n\n", "Date,Tool\n\"unterminated,quote\n", "date,tool,purpose,minutes,extra,extra\n5/11/2026,A,B,12 mins,x,y\n"]
        self.compare([{"fn": "parseSessions", "args": [t]} for t in logs])

    def test_projects(self):
        texts = [sample("sample-project.json"), "", "{}", "[]", "not json", '{"format": "checked-by-me project", "version": 99}',
                 '{"format": "checked-by-me project", "version": 1, "sessions": [[1], {"date": 5, "tool": true, "minutes": 1.5}, {"date": "3/4/2026"}],'
                 ' "checks": {"q12345678": {"status": "verified", "note": 3}, "q1234567": {"status": "verified"}, "qabcdef01": {"status": "unchecked", "note": "n"},'
                 ' "qabcdef02": {"status": "nope"}, "__proto__": {"status": "verified"}}, "texts": {"draft": 4}}',
                 '\ufeff{"format": "checked-by-me project", "version": 1, "project": {"title": ["x"]}}']
        self.compare([{"fn": "readProject", "args": [t]} for t in texts])

    def test_reference_entries(self):
        lines = REF_LINES + [r for r in sample("references.txt").split("\n") if r.strip()] + [
            "Ng, T. (2022) 'Title', Review, e12345.", "", "(2020)", "Anon. (2019) Untitled.", "Smith, J. (2019b) Book. 2nd edn. Leeds: Press.",
            "Smith J, Jones K. Title of article. J Things. 2020;3(2):10-20. doi: 10.5555/abc", "https://only.a.url/here"]
        self.compare([{"fn": "parseEntry", "args": [r, ""]} for r in lines] + [{"fn": "splitEntries", "args": [sample("messy-paste.txt").split("\n")]}])

    def test_word_files(self):
        doc = ('<w:document><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Repair &amp; reuse</w:t></w:r></w:p>'
               '<w:p><w:r><w:t xml:space="preserve">It cut 14 tonnes </w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r>'
               '<w:r><w:tab/><w:t>in 2023&#8212;&#x00E9;&#128512;.</w:t></w:r></w:p><w:p/><w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr>'
               '<w:r><w:t>A bullet</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>T</w:t></w:r></w:p></w:body></w:document>')
        notes = ('<w:footnotes><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:t>sep</w:t></w:r></w:p></w:footnote>'
                 '<w:footnote w:id="1"><w:p><w:r><w:t>Kestleford Repair Network (2024) Annual report.</w:t></w:r></w:p></w:footnote></w:footnotes>')
        self.compare([{"fn": "docxText", "args": [doc, notes]}, {"fn": "docxText", "args": [doc, ""]}, {"fn": "docxText", "args": ["", ""]}])


if __name__ == "__main__":
    unittest.main()
