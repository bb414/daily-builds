"""Tests of the Python companion: reading files, every command, and the repository itself."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

from helpers import AS_OF, DATA, M, ROOT, sample, sample_input

from checkedbyme import cli
from checkedbyme.files import ReadError, final_pairs, read_text

DOCX_DOC = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="x"><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Repair caf\u00e9s</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Kestleford diverted 140 tonnes of waste in 2023</w:t></w:r>'
            '<w:r><w:footnoteReference w:id="1"/></w:r><w:r><w:t>. As of my last update, it is the best.</w:t></w:r></w:p>'
            '</w:body></w:document>')
DOCX_NOTES = ('<w:footnotes xmlns:w="x"><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:t>-</w:t></w:r></w:p></w:footnote>'
              '<w:footnote w:id="1"><w:p><w:r><w:t>Kestleford Repair Network (2024) Annual report 2023.</w:t></w:r></w:p></w:footnote></w:footnotes>')


def make_docx(path, doc=DOCX_DOC, notes=DOCX_NOTES):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)
        if notes:
            z.writestr("word/footnotes.xml", notes)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
            err.write(str(exc.code))
    return code, out.getvalue(), err.getvalue()


class Files(unittest.TestCase):
    def test_text_encodings_and_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with open(p, "wb") as fh:
                fh.write("\ufeffCaf\u00e9 \u00a3320".encode("utf-8"))
            self.assertEqual(read_text(p), "Caf\u00e9 \u00a3320")
            with open(p, "wb") as fh:
                fh.write("Caf\u00e9 \u00a3320".encode("cp1252"))
            self.assertEqual(read_text(p), "Caf\u00e9 \u00a3320")
            b = os.path.join(d, "b.md")
            with open(b, "wb") as fh:
                fh.write(b"\x00\x01binary")
            with self.assertRaises(ReadError):
                read_text(b)
            with self.assertRaises(ReadError):
                read_text(os.path.join(d, "essay.pdf"))
            bad = os.path.join(d, "bad.docx")
            with open(bad, "w") as fh:
                fh.write("not a zip")
            with self.assertRaisesRegex(ReadError, "not a valid .docx"):
                read_text(bad)

    def test_word_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "essay.docx")
            make_docx(p)
            text = read_text(p)
            self.assertTrue(text.startswith("# Repair caf\u00e9s\n\nKestleford diverted 140 tonnes of waste in 2023[^1]."))
            self.assertIn("[^1]: Kestleford Repair Network (2024) Annual report 2023.", text)
            a = M.analyse({"draft": text, "asOf": AS_OF})
            self.assertEqual(a["refs"]["entries"][0]["cited"], 1)
            self.assertTrue(any("leftover" in c["kinds"] for c in a["claims"]))

    def test_final_versions_are_paired_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("essay.md", "essay-final.md", "brief.txt", "notes.final.txt", "x.csv"):
                open(os.path.join(d, name), "w").close()
            pairs = [(n, os.path.basename(f) if f else None) for n, _, f in final_pairs(d)]
            self.assertEqual(pairs, [("brief.txt", None), ("essay.md", "essay-final.md"), ("notes.final.txt", None)])


class Commands(unittest.TestCase):
    def test_check_lists_the_conflicts_and_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run("check", os.path.join(DATA, "ai-draft.md"), "--final", os.path.join(DATA, "final-version.md"),
                               "--notes", os.path.join(DATA, "notes.md"), "--prompt", os.path.join(DATA, "prompt.txt"),
                               "--csv", os.path.join(d, "c.csv"), "--refs-csv", os.path.join(d, "r.csv"), "--json", os.path.join(d, "a.json"),
                               "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            self.assertIn("11 statements worth checking (5 high, 3 medium, 3 low)", out)
            self.assertIn("! Your notes: 36% said they would choose", out)
            self.assertIn("Cited but not listed: Lindqvist (2020)", out)
            self.assertIn("Nothing was checked online", out)
            a = M.analyse(sample_input())
            with open(os.path.join(d, "c.csv"), encoding="utf-8", newline="") as fh:
                self.assertEqual(fh.read(), M.claims_csv(a, {}))
            with open(os.path.join(d, "a.json"), encoding="utf-8") as fh:
                self.assertEqual(len(json.load(fh)["claims"]), 11)

    def test_check_reads_a_reference_manager_export(self):
        code, out, _ = run("check", os.path.join(DATA, "ai-draft.md"), "--references", os.path.join(DATA, "references.bib"), "--as-of", "2026-11-28")
        self.assertEqual(code, 0)
        self.assertIn("References: 9 entries, 7 flagged, 1 look made up, 1 cited but not listed.", out)
        self.assertIn("The web address contains a space", out)

    def test_batch_report_covers_every_file_and_explains_bad_ones(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("ai-draft.md", "messy-paste.txt"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write(sample(name))
            with open(os.path.join(d, "ai-draft-final.md"), "w", encoding="utf-8") as fh:
                fh.write(sample("final-version.md"))
            make_docx(os.path.join(d, "word-essay.docx"))
            with open(os.path.join(d, "broken.docx"), "w") as fh:
                fh.write("nope")
            out_html, out_csv = os.path.join(d, "report.html"), os.path.join(d, "summary.csv")
            code, out, _ = run("batch", d, "--out", out_html, "--csv", out_csv, "--notes", os.path.join(DATA, "notes.md"), "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            with open(out_html, encoding="utf-8") as fh:
                page = fh.read()
            for name in ("ai-draft.md + ai-draft-final.md", "messy-paste.txt", "word-essay.docx", "broken.docx", "not a valid .docx"):
                self.assertIn(name, page)
            self.assertNotIn("<script", page)
            self.assertNotIn("<link", page)
            self.assertNotIn("\u2014", page)
            rows = M.parse_csv(open(out_csv, encoding="utf-8").read())["rows"]
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[1][0], "ai-draft.md + ai-draft-final.md")
            self.assertEqual(rows[1][7], "74")

    def test_gate_holds_until_high_risk_claims_are_marked(self):
        code, out, _ = run("gate", os.path.join(DATA, "sample-project.json"), "--as-of", "2026-11-28")
        self.assertEqual(code, 1)
        self.assertIn("HOLD", out)
        self.assertIn("4 statements unchecked at high risk", out)
        p = M.read_project(sample("sample-project.json"))
        a = M.analyse(dict(p["texts"], asOf=AS_OF))
        with tempfile.TemporaryDirectory() as d:
            for c in a["claims"]:
                if c["level"] == "high":
                    p["checks"][c["key"]] = {"status": "corrected", "note": "fixed"}
            done = os.path.join(d, "done.json")
            with open(done, "w", encoding="utf-8") as fh:
                fh.write(M.project_file(dict(p, asOf=AS_OF)))
            self.assertEqual(run("gate", done, "--as-of", "2026-11-28")[0], 0)
            code, out, _ = run("gate", done, "--level", "medium", "--as-of", "2026-11-28")
            self.assertEqual(code, 1)
            self.assertEqual(run("gate", d, "--as-of", "2026-11-28")[0], 0, "a folder of projects")
            code, out, _ = run("gate", done, "--refs", "--as-of", "2026-11-28")
            self.assertEqual(code, 1)
            self.assertIn("references to look at", out)
            junk = os.path.join(d, "junk.json")
            with open(junk, "w") as fh:
                fh.write("{}")
            code, out, _ = run("gate", junk)
            self.assertEqual(code, 2)
            self.assertIn("not a Checked by me project", out)

    def test_gate_reads_marks_from_a_checklist_csv(self):
        with tempfile.TemporaryDirectory() as d:
            draft = os.path.join(DATA, "ai-draft.md")
            a = M.analyse({"draft": sample("ai-draft.md"), "asOf": AS_OF})
            checks = {c["key"]: {"status": "verified", "note": "seen"} for c in a["claims"] if c["level"] == "high"}
            csv_path = os.path.join(d, "checklist.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(M.claims_csv(a, checks))
            self.assertEqual(run("gate", draft, "--as-of", "2026-11-28")[0], 1)
            self.assertEqual(run("gate", draft, "--checklist", csv_path, "--as-of", "2026-11-28")[0], 0)

    def test_gate_as_a_separate_process_sets_the_exit_code(self):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "companion", "checked_by_me.py"), "gate",
                               os.path.join(DATA, "sample-project.json"), "--as-of", "2026-11-28"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("HOLD", proc.stdout)

    def test_merge_joins_three_logs_into_one(self):
        with tempfile.TemporaryDirectory() as d:
            logs = [os.path.join(DATA, "team", n) for n in ("team-log-ana.csv", "team-log-dev.csv", "team-log-sam.csv")]
            code, out, _ = run("merge", *logs, "--assignment", "MGT2210 Group report", "--title", "Circular procurement",
                               "--out-csv", os.path.join(d, "m.csv"), "--out-md", os.path.join(d, "m.md"), "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            self.assertIn("Merged 5 sessions from 3 logs.", out)
            merged = M.parse_sessions(open(os.path.join(d, "m.csv"), encoding="utf-8").read())["sessions"]
            self.assertEqual([s["person"] for s in merged], ["Ana", "Dev Okonedo", "Ana, Dev Okonedo", "Sam", "Sam"])
            md = open(os.path.join(d, "m.md"), encoding="utf-8").read()
            self.assertIn("**Team:** Ana, Dev Okonedo and Sam", md)
            self.assertIn("about 90 minutes in all", md)
            self.assertIn("| 10 November 2026 | Ana, Dev Okonedo | Orrery Chat |", md)

    def test_cohort_overview_of_a_class(self):
        with tempfile.TemporaryDirectory() as d:
            out, csv_path = os.path.join(d, "o.html"), os.path.join(d, "o.csv")
            with open(os.path.join(d, "junk.json"), "w") as fh:
                fh.write("[]")
            code, text, _ = run("cohort", os.path.join(DATA, "class"), os.path.join(d, "junk.json"), "--out", out, "--csv", csv_path,
                                "--label", "MGT2207", "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            text = " ".join(text.split())
            self.assertIn("Read 8 projects", text)
            self.assertIn("Not read: junk.json", text)
            self.assertIn("1 still contains text from the chat window", text)
            self.assertIn("declared less AI use than the comparison with their AI draft shows (Hana Ellery, Jude Fairweather)", text)
            page = open(out, encoding="utf-8").read()
            self.assertIn("median AI wording kept", page)
            self.assertNotIn("Repair caf\u00e9s have become", page, "nobody's text is shown")
            self.assertNotIn("<script", page)
            rows = M.parse_csv(open(csv_path, encoding="utf-8").read())["rows"]
            self.assertEqual(len(rows), 9)
            by = {r[0]: r for r in rows[1:]}
            self.assertEqual(by["Ewan Castell"][7], "")
            self.assertEqual(by["Hana Ellery"][-1], "yes")
            self.assertEqual(by["Tomas Brightwater"][-2], "yes")
            run("cohort", os.path.join(DATA, "class"), "--out", out, "--csv", csv_path, "--anonymise", "--as-of", "2026-11-28")
            page = open(out, encoding="utf-8").read()
            self.assertNotIn("Hana Ellery", page)
            self.assertIn("Person 1", page)

    def test_declaration_warns_when_the_declared_level_does_not_match(self):
        p = M.read_project(open(os.path.join(DATA, "class", "hana-ellery.checked-by-me.json"), encoding="utf-8").read())
        a = M.analyse(dict(p["texts"], asOf=AS_OF))
        d = M.declaration(a, {"project": p["project"], "sessions": p["sessions"], "checks": p["checks"], "asOf": AS_OF})
        self.assertTrue(any("ideas and planning only" in w and "98%" in w for w in d["warnings"]), d["warnings"])

    def test_declare_gives_the_same_text_as_the_model(self):
        p = M.read_project(sample("sample-project.json"))
        a = M.analyse(dict(p["texts"], asOf=AS_OF))
        state = {"project": p["project"], "sessions": p["sessions"], "checks": p["checks"], "refChecks": p["refChecks"], "asOf": AS_OF}
        code, out, err = run("declare", os.path.join(DATA, "sample-project.json"), "--as-of", "2026-11-28")
        self.assertEqual(code, 0)
        self.assertEqual(out, M.declaration_text(M.declaration(a, state)))
        self.assertIn("high-risk statements are still unchecked", err)
        with tempfile.TemporaryDirectory() as d:
            md = os.path.join(d, "d.md")
            run("declare", os.path.join(DATA, "sample-project.json"), "--template", "work", "--md", md, "--as-of", "2026-11-28")
            self.assertTrue(open(md, encoding="utf-8").read().startswith("# Note on AI use"))

    def test_recheck_shows_what_changed_and_records_the_version(self):
        with tempfile.TemporaryDirectory() as d:
            new = os.path.join(d, "v3.md")
            with open(new, "w", encoding="utf-8") as fh:
                fh.write(sample("final-version.md").replace("56%", "36%").replace("Overall, repair caf\u00e9s", "Overall, as the 2023 figures show, repair caf\u00e9s"))
            out = os.path.join(d, "updated.json")
            code, text, _ = run("recheck", os.path.join(DATA, "sample-project.json"), new, "--out", out, "--record", "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            self.assertIn("Compared with the version checked on 2026-11-20", text)
            self.assertIn("[-56%-] {+36%+}", text)
            self.assertIn("GONE    (was removed)", text)
            p = M.read_project(open(out, encoding="utf-8").read())
            self.assertEqual(p["baseline"]["on"], "2026-11-28")
            self.assertIn("36%", p["texts"]["final"])
            code, text, _ = run("recheck", out, new, "--as-of", "2026-11-28")
            self.assertIn("0 new statements, 0 edited statements, 0 statements gone", text)

    def test_annotate_writes_a_proof_copy(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "proof.md")
            code, text, _ = run("annotate", os.path.join(DATA, "sample-project.json"), "--out", out, "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            md = open(out, encoding="utf-8").read()
            self.assertTrue(md.startswith("# Proof copy: Repair caf\u00e9s and the circular high street"))
            self.assertIn("**[Qy 5: high, open]**", md)
            self.assertIn("### Qy 9 (high risk, score 16, open)", md)
            self.assertIn("- **Status:** verified (Brinmouth footfall monitor 2022, table 2)", md)
            self.assertIn("- Cited in the text but not in the list: Lindqvist (2020)", md)
            code, text, _ = run("annotate", os.path.join(DATA, "drafts", "chat-paste.txt"), "--as-of", "2026-11-28")
            self.assertIn("# Proof copy: chat-paste", text)

    def test_diff_and_project(self):
        code, out, _ = run("diff", os.path.join(DATA, "ai-draft.md"), os.path.join(DATA, "final-version.md"), "--as-of", "2026-11-28")
        self.assertEqual(code, 0)
        self.assertIn("74% of the 314 words in the final text appear word for word", out)
        self.assertIn("CUT        Soldering fumes", out)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            code, out, _ = run("project", "--draft", os.path.join(DATA, "ai-draft.md"), "--final", os.path.join(DATA, "final-version.md"),
                               "--sessions", os.path.join(DATA, "session-log.csv"), "--title", "Essay", "--out", path, "--as-of", "2026-11-28")
            self.assertEqual(code, 0)
            p = M.read_project(open(path, encoding="utf-8").read())
            self.assertTrue(p["ok"])
            self.assertEqual(len(p["sessions"]), 6)
            self.assertEqual(p["project"]["title"], "Essay")

    def test_bad_arguments_say_what_is_wrong(self):
        code, _, err = run("check", os.path.join(DATA, "nope.md"))
        self.assertNotEqual(code, 0)
        self.assertIn("Could not open", err)
        code, _, err = run("check", os.path.join(DATA, "ai-draft.md"), "--as-of", "someday")
        self.assertIn('Could not read the date "someday"', err)


@unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed")
class Spreadsheets(unittest.TestCase):
    def test_exported_csv_files_open_in_libreoffice(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is not installed")
        p = M.read_project(sample("sample-project.json"))
        a = M.analyse(dict(p["texts"], asOf=AS_OF))
        with tempfile.TemporaryDirectory() as d:
            files = {"claims": M.claims_csv(a, p["checks"]), "refs": M.refs_csv(a, p["refChecks"]), "sessions": M.sessions_csv(p["sessions"])}
            for name, text in files.items():
                with open(os.path.join(d, name + ".csv"), "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--infilter=CSV:44,34,76,1", "--outdir", d]
                           + [os.path.join(d, n + ".csv") for n in files], capture_output=True, timeout=180)
            for name, text in files.items():
                rows = list(openpyxl.load_workbook(os.path.join(d, name + ".xlsx")).active.iter_rows(values_only=True))
                self.assertEqual(len(rows), len(M.parse_csv(text)["rows"]), name)
            claims = list(openpyxl.load_workbook(os.path.join(d, "claims.xlsx")).active.iter_rows(values_only=True))
            self.assertEqual(claims[0][4], "Sentence")
            self.assertTrue(any("caf\u00e9s" in str(r[4]) for r in claims[1:]))


class Repository(unittest.TestCase):
    def test_sample_data_is_reproducible_from_the_seed(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_samples.py"), "--out", d], check=True, capture_output=True)
            for folder, _, files in os.walk(d):
                for name in files:
                    rel = os.path.relpath(os.path.join(folder, name), d)
                    with open(os.path.join(folder, name), encoding="utf-8") as a, open(os.path.join(DATA, rel), encoding="utf-8") as b:
                        self.assertEqual(a.read(), b.read(), rel)

    def test_the_built_app_is_current(self):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_app.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_no_em_dashes_or_assistant_names_in_any_file(self):
        bad = []
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "node_modules")]
            for name in files:
                if name.endswith((".png", ".woff2")):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    text = fh.read()
                if "\u2014" in text:
                    bad.append(name + ": em dash")
                low = text.lower()
                for word in ("cla" + "ude", "anth" + "ropic"):
                    if word in low:
                        bad.append(name + ": " + word)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
