"""Tests of the Python companion: reading files, every command, and the repository itself."""

import io
import json
import os
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
            self.assertEqual(rows[1][7], "76")

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

    def test_diff_and_project(self):
        code, out, _ = run("diff", os.path.join(DATA, "ai-draft.md"), os.path.join(DATA, "final-version.md"), "--as-of", "2026-11-28")
        self.assertEqual(code, 0)
        self.assertIn("76% of the 342 words in the final text appear word for word", out)
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
