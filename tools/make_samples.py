"""Write the invented sample data in data/ from a fixed seed.

Everything here is made up: the town of Kestleford, its repair network, the
University of Eastmoor, the people, the journals, the AI tools (Orrery Chat
and Fernwrite) and the firm Halden & Pike. DOIs use 10.5555, the prefix set
aside for examples, so none of them points at a real paper.

The generator builds one AI-drafted essay section from a table of facts. The
seed decides how the "AI" gets four facts and a quotation wrong (digits
swapped, a year moved, an amount inflated, a quotation sharpened); three
facts it gets right. The student's notes always
hold the true values, so the checker has something real to catch. It also
writes the student's edited final version, the prompt, a reference list with
good, malformed and made-up-looking entries, a session log, a deliberately
messy paste, a short workplace briefing, three team members' logs for the
companion's merge command, and the sample project the app opens with.

Run:  python tools/make_samples.py              (seed 2611, into data/)
      python tools/make_samples.py --seed 7     (another set of mistakes)
      python tools/make_samples.py --out DIR    (somewhere else)
"""

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = DATA

ASSIGNMENT = "MGT2207 Essay 2"
TITLE = "Repair cafés and the circular high street"

# Each fact: its true value (in the notes) and the ways the AI draft may get it wrong.
FACTS = {
    "tonnes": {"true": "14", "wrong": ["41", "140", "24"]},
    "volunteers": {"true": "85", "wrong": None},
    "first_year": {"true": "2014", "wrong": ["2011", "2012", "2009"]},
    "survey_n": {"true": "1,200", "wrong": None},
    "survey_pct": {"true": "36", "wrong": ["63", "68", "56"]},
    "saving": {"true": "120", "wrong": ["320", "210", "420"]},
    "footfall": {"true": "9", "wrong": None},
}

QUOTE_TRUE = "repair is one of the most practical things a consumer can do"
QUOTE_WRONG = [
    "repair is the most radical thing a consumer can do",
    "repair is the most powerful thing a consumer can do",
]


def choose(rng):
    """Pick the AI's version of every fact: the seed decides how each corruptible one goes wrong."""
    picked = {}
    for key, fact in FACTS.items():
        picked[key] = rng.choice(fact["wrong"]) if fact["wrong"] else fact["true"]
    picked["quote"] = rng.choice(QUOTE_WRONG)
    return picked


def draft_text(f):
    return f"""## 2. {TITLE}

Repair cafés have become one of the most visible parts of the circular economy on the British high street. In a repair café, volunteers help visitors fix broken household items for free, from toasters and lamps to bicycles and clothing. As of my last update, there were more than 2,000 repair cafés operating worldwide.

In Kestleford, the Kestleford Repair Network runs three monthly repair cafés. According to the network's annual report, its cafés diverted {f['tonnes']} tonnes of electrical waste from landfill in 2023, and the network had {f['volunteers']} volunteers by the end of that year (Kestleford Repair Network, 2024). The first repair café in the county opened in Brinmouth in {f['first_year']}, and the model has since spread to every market town in the region.

Repair cafés always reduce waste and are proven to strengthen local communities. A 2019 survey of {f['survey_n']} households found that {f['survey_pct']}% would choose to repair an item rather than replace it if free help were available (Hartwell et al., 2019). Studies show that repair skills are disappearing among young people, which makes these events especially valuable for students.

The economic case is equally strong. Households save an average of £{f['saving']} a year by repairing rather than replacing electrical items (Eastmoor Institute for Circular Practice, 2022). Footfall on Market Street rose by {f['footfall']}% on repair café Saturdays, which suggests that independent shops benefit from the extra visitors (Brinmouth Borough Council, 2022). As Dr Maren Haldane of the Eastmoor Institute put it, "{f['quote']}" (Haldane, 2021, p. 14).

There are practical issues to manage. Volunteers are not legally liable for faults in items they repair, as long as they follow the venue's safety checklist. Soldering fumes are harmless in short sessions, so no special ventilation is needed. Lindqvist (2020) argues that the biggest barrier is not safety but the lack of spare parts, and Pemberton (2031) predicts that this will change once manufacturers are required to publish repair manuals.

Overall, repair cafés are the single most effective way for a town to cut electrical waste, and they offer a clear model for a circular high street.

## References

{REFERENCES}
"""


REFERENCES = """Brinmouth Borough Council (2022) *Market Street footfall monitor 2022*. Available at: https://www.brinmouth-bc.org.uk/footfall data (Accessed: 3 November 2026).
Eastmoor Institute for Circular Practice (2022) *The household value of repair*. Eastmoor: EICP. doi:10.5555/eicp 2022.07
Haldane, M. (2021) *Mending the market: repair and the everyday economy*. Kestleford: Wren Lane Press.
Hartwell, M., Osei, P. and Lindqvist, A. (2019) 'Repair intentions in UK households', *Journal of Household Material Flows*, 14(2), pp. 113-129. doi:10.5555/jhmf.2019.0142
Hartwell, M., Osei, P. & Lindqvist, A. (2019). Repair intentions in UK households. Journal of Household Material Flows, 14(2), 113-129.
Kestleford Repair Network (2024) *Annual report 2023*. Available at: htps://kestleford-repair-network.org.uk/annual-report-2023
Morrow, J. (2021) 'The economics of fixing things', *Journal of Research Studies*.
Pemberton, L. (2031) *Right to repair: the next decade*. London: Fallow Books.
Quinlan, R. and Oduya, T. (2018) 'Volunteering and local trade', *Review of Community Enterprise*, 7(1), pp. 45-61. doi:10.555/rce.7.1"""


def final_text(f):
    t = FACTS
    return f"""## 2. {TITLE}

Repair cafés are one of the easiest parts of the circular economy to see on a high street. Volunteers help visitors fix broken household items for free, from toasters and lamps to bicycles and clothing.

In Kestleford, the Kestleford Repair Network runs three monthly repair cafés. According to the network's annual report, its cafés diverted {t['tonnes']['true']} tonnes of electrical waste from landfill in 2023, and the network had {f['volunteers']} volunteers by the end of that year (Kestleford Repair Network, 2024). The first repair café in the county opened in Brinmouth in {t['first_year']['true']}, and the model has since spread to most market towns in the region.

When I visited the Market Street café in October, most of the twenty or so visitors had brought small kitchen appliances, and about half of the repairs I watched were finished on the day. Repair cafés often reduce waste and may strengthen local communities. A 2019 survey of {f['survey_n']} households found that {f['survey_pct']}% would choose to repair an item rather than replace it if free help were available (Hartwell et al., 2019). Younger respondents were more likely to say they lacked the skills to repair things themselves (Hartwell et al., 2019).

The economic case is equally strong. Households save an average of £{f['saving']} a year by repairing rather than replacing electrical items (Eastmoor Institute for Circular Practice, 2022). Footfall on Market Street rose by {f['footfall']}% on repair café Saturdays, which suggests that independent shops benefit from the extra visitors (Brinmouth Borough Council, 2022). As Dr Maren Haldane of the Eastmoor Institute put it, "{f['quote']}" (Haldane, 2021, p. 14).

There are practical issues to manage. Volunteers are not legally liable for faults in items they repair, as long as they follow the venue's safety checklist. Lindqvist (2020) argues that the biggest barrier is not safety but the lack of spare parts.

Overall, repair cafés are a promising and low-cost way for a town to cut electrical waste, and they offer a useful model for a circular high street.

## References

{REFERENCES}
"""


def notes_text():
    t = FACTS
    return f"""# Notes for Essay 2 (MGT2207)

## Kestleford Repair Network, Annual report 2023 (published 2024)
- Three cafés, monthly, in Kestleford.
- Diverted {t['tonnes']['true']} tonnes of electrical waste from landfill in 2023.
- {t['volunteers']['true']} volunteers at the end of 2023.
- First repair café in the county: Brinmouth, {t['first_year']['true']}.

## Hartwell, Osei and Lindqvist (2019), Journal of Household Material Flows 14(2) 113-129
- Survey of {t['survey_n']['true']} households in three UK regions.
- {t['survey_pct']['true']}% said they would choose to repair rather than replace if free help were available.
- Younger respondents more likely to say they lacked the skills (no trend data, so not "disappearing").

## Eastmoor Institute for Circular Practice (2022), The household value of repair
- Households that repair save about £{t['saving']['true']} a year on electrical items.

## Brinmouth Borough Council, Market Street footfall monitor 2022
- Market Street footfall up {t['footfall']['true']}% on repair café Saturdays compared with other Saturdays.

## Haldane (2021) Mending the market, p. 14
- Quote: "{QUOTE_TRUE}"

## Seminar 6: safety and liability
- Volunteers should not assume they are covered: ask the venue about insurance and liability.
- Soldering: use extraction or good ventilation, because the fumes irritate the lungs.
"""


PROMPT = """I'm writing section 2 of my MGT2207 essay on repair cafés and the circular high street (about 700 words, UK spelling). Use Kestleford as the case study. Include statistics and academic references in Harvard style, and a quote from an expert if you can."""

SESSIONS = [
    # date, assignment, tool, purpose, prompt summary, used, changed, checked, minutes
    ("02/11/2026", ASSIGNMENT, "Orrery Chat", "Brainstorm the structure",
     "Asked for three angles on repair cafés and the high street", "Two of the three angles as section headings",
     "Dropped the third angle (tourism)", "", "10"),
    ("2026-11-05", ASSIGNMENT, "Orrery Chat", "Draft section 2",
     "Asked for a 700-word section on Kestleford's repair cafés with statistics, Harvard references and an expert quote",
     "The draft of section 2", "Rewrote the opening, added my site visit, cut the soldering advice",
     "Waste figure and opening year against my notes", "35"),
    ("9 Nov 2026", ASSIGNMENT, "Fernwrite", "Tighten the conclusion",
     "Asked for a shorter, less absolute conclusion", "One sentence of the suggested conclusion",
     "Changed 'the single most effective' to 'a promising and low-cost'", "", "5"),
    ("12/11/2026", ASSIGNMENT, "Orrery Chat", "Explain a reading",
     "Asked for a plain-English summary of the Hartwell et al. survey method", "Nothing directly",
     "", "Read the paper's method section myself", "15"),
    ("14/11/2026", "MGT2210 Group report", "Fernwrite", "Grammar and spelling check",
     "Pasted my two paragraphs and asked for spelling corrections only", "Spelling fixes", "", "", "5"),
    ("", "", "", "", "", "", "", "", ""),
    ("31/13/2026", ASSIGNMENT, "Orrery Chat", "Format the reference list",
     "Asked it to put my references into Harvard style", "The formatted list", "", "", "ten"),
]

SESSION_HEADER = ["Date", "Assignment", "Tool", "Purpose", "Prompt summary", "What I used", "What I changed",
                  "What I checked", "Minutes"]

TEMPLATE_ROWS = [
    ("2026-11-02", "Module code and assignment", "The AI tool you used", "What you used it for",
     "Your prompt in one line", "What you kept from its answer", "What you changed", "What you checked, and against what", "15"),
]


def csv_line(cells):
    out = []
    for c in cells:
        c = str(c)
        if any(ch in c for ch in ',"\n\r') or c != c.strip():
            c = '"' + c.replace('"', '""') + '"'
        out.append(c)
    return ",".join(out)


def messy_text(f):
    # A paste straight out of a chat window: assistant chatter, Markdown left in, smart quotes,
    # non-breaking and zero-width spaces, footnote markers, a placeholder and a broken reference list.
    nb = " "
    zw = "​"
    return (
        "Sure! Here’s a polished version of your essay section, with statistics and references:\n\n"
        "### **Repair cafés and the circular high street**\n\n"
        f"Repair cafés are *quietly* changing how a town deals with broken things. In Kestleford, the network’s{nb}cafés "
        f"diverted **{f['tonnes']} tonnes** of electrical waste in 2023[^1], and the first one in the county opened in Brinmouth in {f['first_year']}¹.\n\n"
        f"* A 2019 survey found that {f['survey_pct']}% of households would rather repair than replace (Hartwell et al, 2019).\n"
        "* Experts agree that repair cafés are the best way to teach young people practical skills.\n"
        f"* Households save £{f['saving']} a year on average{zw} by repairing [Insert source here].\n\n"
        f"> “{f['quote']}” – Dr Maren Haldane, Eastmoor Institute\n\n"
        "It is legally required for every repair café to carry public liability insurance of at least £5 million.\n\n"
        "I hope this helps! Let me know if you’d like a shorter version.\n\n"
        "---\n\n"
        "**References**\n\n"
        "1. Hartwell, M., Osei, P. and Lindqvist, A. (2019) ‘Repair intentions in UK households’, *Journal of Household\n"
        "Material Flows*, 14(2), pp. 113–129. doi: 10.5555/jhmf.2019.0142\n"
        "2. Kestleford Repair Network (2024) *Annual report 2023*. Available at: https://kestleford-repair-\n"
        "network.org.uk/annual-report-2023\n"
        "3. Morrow, J. (2021) ‘The economics of fixing things’, *Journal of Research Studies*. Morrow, J. (2021) ‘The economics of fixing things’, *Journal of Research Studies*.\n"
        "4. Vance, E. et al (n.d.) *Community repair: a global review*. [Author, Year].\n\n"
        "[^1]: Kestleford Repair Network (2024) Annual report 2023.\n"
    )


BRIEFING = """# Briefing: refurbished laptops for the Halden & Pike office

**To:** Operations committee
**From:** Facilities

Halden & Pike replaces about 40 laptops a year. Refurbished business laptops cost 35% less than new ones and come with a 12-month warranty from most refurbishers, so the switch would save roughly £18,000 a year at current prices.

Refurbished laptops are always just as reliable as new ones. According to a 2022 report by the Lowfield Centre for IT Reuse, refurbishing a laptop avoids around 250 kg of carbon emissions compared with buying new. The Lowfield Centre's director, Priya Castellan, said that "every refurbished laptop is a laptop that never has to be mined for".

Under UK data protection law, the refurbisher becomes the data controller for anything left on the old drives, so we would not be responsible for wiping them. All of the suppliers we spoke to are certified to the highest data-erasure standard.

We recommend a pilot with ten machines in the finance team from January 2027. See https://lowfield-itreuse.org.uk/carbon-2022 for the full report.
"""

TEAM = {
    "team-log-ana.csv": (["Date", "Project", "Tool", "Purpose", "Prompt", "Kept", "Changed", "Checked", "Mins"], [
        ["03/11/2026", "MGT2210 Group report", "Orrery Chat", "Plan the report structure", "Asked for a structure for a circular procurement report", "Section headings", "Merged two sections", "", "20"],
        ["10/11/2026", "MGT2210 Group report", "Orrery Chat", "Draft the method section", "Asked for a first draft of our interview method", "About half the draft", "Rewrote the sampling paragraph", "Interview numbers against our spreadsheet", "30"],
    ]),
    "team-log-dev.csv": (["Person", "When", "AI tool", "What for", "What I asked", "What I used", "What I changed", "What I checked", "Duration"], [
        ["Dev Okonedo", "2026-11-06", "Fernwrite", "Summarise supplier documents", "Pasted three supplier sustainability statements and asked for a comparison table", "The comparison table layout", "Corrected two supplier names", "Every figure against the original statements", "25"],
        ["Dev Okonedo", "2026-11-10", "Orrery Chat", "Draft the method section", "Asked for a first draft of our interview method", "About half the draft", "Rewrote the sampling paragraph", "Interview numbers against our spreadsheet", "30"],
    ]),
    "team-log-sam.csv": (["Date;Assignment;Tool;Purpose;Prompt summary;What I used;What I changed;What I checked;Minutes"], [
        ["14 Nov 2026;MGT2210 Group report;Fernwrite;Grammar and spelling check;Asked for spelling corrections only;Spelling fixes;;;5"],
        ["18 Nov 2026;MGT2210 Group report;Orrery Chat;Executive summary ideas;\"Asked for three ways to open the summary; used none\";Nothing;Wrote our own;;10"],
    ]),
}


def write(name, text):
    path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv):
    global OUT
    seed = 2611
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    if "--out" in argv:
        OUT = os.path.abspath(argv[argv.index("--out") + 1])
    rng = random.Random(seed)
    f = choose(rng)

    write("ai-draft.md", draft_text(f).replace("{REFERENCES}", REFERENCES))
    write("final-version.md", final_text(f).replace("{REFERENCES}", REFERENCES))
    write("notes.md", notes_text())
    write("prompt.txt", PROMPT + "\n")
    write("references.txt", REFERENCES + "\n")
    write("messy-paste.txt", messy_text(f))
    # A folder of drafts for the companion's batch command: a final version sits beside its draft as "-final".
    write("drafts/repair-cafes.md", draft_text(f).replace("{REFERENCES}", REFERENCES))
    write("drafts/repair-cafes-final.md", final_text(f).replace("{REFERENCES}", REFERENCES))
    write("drafts/chat-paste.txt", messy_text(f))
    write("drafts/refurbished-laptops-briefing.md", BRIEFING)

    lines = [csv_line(SESSION_HEADER)] + [csv_line(r) for r in SESSIONS]
    write("session-log.csv", "\n".join(lines) + "\n")
    lines = [csv_line(SESSION_HEADER)] + [csv_line(r) for r in TEMPLATE_ROWS]
    write("session-log-template.csv", "\n".join(lines) + "\n")

    for name, (header, rows) in TEAM.items():
        if len(header) == 1:
            text = "\n".join([header[0]] + [r[0] for r in rows]) + "\n"
        else:
            text = "\n".join([csv_line(header)] + [csv_line(r) for r in rows]) + "\n"
        write(os.path.join("team", name), text)

    truth = {
        "seed": seed,
        "aiValues": f,
        "trueValues": {k: v["true"] for k, v in FACTS.items()},
        "trueQuote": QUOTE_TRUE,
        "wrongInDraft": sorted(k for k in FACTS if f[k] != FACTS[k]["true"]) + ["quote"],
        "fixedInFinal": ["first_year", "tonnes"],
        "referenceProblems": {
            "Brinmouth Borough Council (2022)": "space inside the URL",
            "Eastmoor Institute for Circular Practice (2022)": "space inside the DOI",
            "Hartwell et al. (2019), second entry": "duplicate of the first Hartwell entry",
            "Kestleford Repair Network (2024)": "URL scheme misspelt (htps)",
            "Morrow (2021)": "generic journal name, no volume or pages, never cited",
            "Pemberton (2031)": "year in the future",
            "Quinlan and Oduya (2018)": "malformed DOI prefix, never cited",
            "Lindqvist (2020)": "cited in the text but missing from the list",
        },
    }
    write("sample-truth.json", json.dumps(truth, indent=1, ensure_ascii=False) + "\n")

    # The sample project the app opens with needs the companion (it works out the claim keys).
    sys.path.insert(0, os.path.join(ROOT, "companion"))
    try:
        from checkedbyme import sample as sample_project
    except ImportError:
        print("Companion not found: skipped data/sample-project.json")
    else:
        write("sample-project.json", sample_project.build(OUT))
    print("Wrote the sample data to %s (seed %d)" % (os.path.relpath(OUT, ROOT), seed))


if __name__ == "__main__":
    main(sys.argv[1:])
