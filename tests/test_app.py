"""Browser tests of app/index.html with Playwright (Chromium, headless).

They open the built page from disk, use it the way a person would (marking
claims, uploading good and bad files, downloading every export and opening it,
saving and reopening a project) and check it works inside an iframe and at
phone width without sending a single request. Skipped when Playwright or its
browser is not installed.
"""

import datetime
import json
import os
import tempfile
import unittest
import zipfile

from helpers import DATA, M, ROOT, sample

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

PAGE = "file://" + os.path.join(ROOT, "app", "index.html")
VIEWS = ["copy", "check", "refs", "changes", "declare", "how"]


def today():
    d = datetime.date.today()
    return M.days_from_civil(d.year, d.month, d.day)


@unittest.skipUnless(sync_playwright, "Playwright is not installed")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as err:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("Chromium is not available: %s" % err)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, width=1280, url=PAGE):
        ctx = self.browser.new_context(viewport={"width": width, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(url)
        page.wait_for_selector(".slip")
        self.addCleanup(ctx.close)
        return page

    def assert_quiet(self):
        self.assertEqual(self.errors, [])
        outside = [u for u in self.requests if not u.startswith(("file:", "data:", "blob:"))]
        self.assertEqual(outside, [], "the page must not make network requests")

    def download(self, page, click):
        with page.expect_download() as info:
            click()
        path = os.path.join(self.tmp.name, info.value.suggested_filename)
        info.value.save_as(path)
        with open(path, encoding="utf-8", newline="") as fh:
            return info.value.suggested_filename, fh.read()

    def pick(self, page, button, path):
        with page.expect_file_chooser() as fc:
            page.click(button)
        fc.value.set_files(path)

    # ---------------------------------------------------------------- tests

    def test_opens_with_the_sample_worked_through(self):
        page = self.open()
        self.assertEqual(page.inner_text(".slip:nth-child(1) .slip-v").split()[0], "7")
        self.assertEqual(page.locator("#view-check li.query").count(), 11)
        self.assertEqual(page.locator("#view-check li.query.st-verified").count(), 4)
        self.assertIn("notes disagree", page.inner_text("#view-check").lower())
        self.assertTrue(page.locator("#hero-art svg").is_visible())
        self.assertIn("checks nothing online", page.inner_text(".labels").lower())
        self.assertIn("not a plagiarism detector", page.inner_text(".labels").lower())
        for v in VIEWS:
            page.click("#tab-" + v)
            self.assertTrue(page.locator("#view-" + v).is_visible())
        self.assert_quiet()

    def test_marking_a_claim_updates_figures_and_declaration(self):
        page = self.open()
        first = page.locator("#view-check li.query").first
        first.locator("button[data-status=verified]").click()
        self.assertEqual(page.inner_text(".slip:nth-child(1) .slip-v").split()[0], "6")
        page.fill("#view-check li.query >> nth=0 >> input", "Haldane 2021, p. 14, library copy")
        page.click("#tab-declare")
        self.assertIn("5 verified against a source", page.inner_text(".proof"))
        page.click("#tab-check")
        first = page.locator("#view-check li.query").first
        self.assertEqual(first.locator("button[data-status=verified]").get_attribute("aria-pressed"), "true")
        self.assertEqual(first.locator("input").input_value(), "Haldane 2021, p. 14, library copy")
        self.assert_quiet()

    def test_signing_off_shows_the_stamp(self):
        page = self.open()
        for _ in range(20):
            btn = page.locator("#view-check li.query.st-unchecked button[data-status=verified]")
            if btn.count() == 0:
                break
            btn.first.click()
        page.click("#tab-refs")
        for _ in range(20):
            btn = page.locator("#view-refs button[data-status=checked][aria-pressed=false]")
            if btn.count() == 0:
                break
            btn.first.click()
        self.assertIn("passed for press", page.inner_html("#hero-art").lower())
        page.click("#tab-declare")
        self.assertEqual(page.locator(".proof svg.stamp").count(), 1)
        self.assertIn("None is left unchecked.", page.inner_text(".proof"))
        self.assert_quiet()

    def test_own_text_by_upload_including_bad_and_word_files(self):
        page = self.open()
        page.click("#btn-own")
        self.assertEqual(page.input_value("#in-draft"), "")
        bad = os.path.join(self.tmp.name, "essay.pdf")
        with open(bad, "wb") as fh:
            fh.write(b"%PDF-1.4 binary")
        self.pick(page, "button[data-pick=draft]", bad)
        page.wait_for_function("document.getElementById('msg-draft').textContent.length > 0")
        self.assertIn("not a text file", page.inner_text("#msg-draft"))
        docx = os.path.join(self.tmp.name, "essay.docx")
        with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", '<w:document><w:body><w:p><w:r><w:t>In 2019, 63% of firms said it was the best (Smith, 2020).</w:t></w:r></w:p>'
                                            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>References</w:t></w:r></w:p>'
                                            '<w:p><w:r><w:t>Smith, J. (2020) Title. London: Press.</w:t></w:r></w:p></w:body></w:document>')
        self.pick(page, "button[data-pick=draft]", docx)
        page.wait_for_function("document.getElementById('in-draft').value.indexOf('63%') >= 0")
        page.click("#tab-check")
        self.assertIn("63%", page.inner_text("#view-check"))
        page.click("#tab-refs")
        self.assertIn("Smith, J. (2020)", page.inner_text("#view-refs"))
        final = os.path.join(DATA, "final-version.md")
        page.click("#tab-copy")
        self.pick(page, "button[data-pick=final]", final)
        page.wait_for_function("document.getElementById('in-final').value.length > 100")
        self.assert_quiet()

    def test_session_log_import_explains_bad_rows(self):
        page = self.open()
        page.click("#tab-copy")
        log = os.path.join(self.tmp.name, "log.csv")
        with open(log, "w", encoding="utf-8") as fh:
            fh.write("\ufeffWhen;AI tool;What for;Mins\n2026-11-20;Fernwrite;Rewrite the intro;12\n32/11/2026;Orrery Chat;Plan;lots\n;;;\n")
        self.pick(page, "button[data-pick=sessions]", log)
        page.wait_for_selector("#msg-sessions li")
        msgs = page.inner_text("#msg-sessions")
        self.assertIn('Read 2 sessions from "log.csv"', msgs)
        self.assertIn('could not read the date "32/11/2026"', msgs)
        self.assertIn('"lots" is not a number of minutes', msgs)
        notlog = os.path.join(self.tmp.name, "people.csv")
        with open(notlog, "w") as fh:
            fh.write("Name,Age\nAna,20\n")
        self.pick(page, "button[data-pick=sessions]", notlog)
        page.wait_for_function("document.getElementById('msg-sessions').textContent.indexOf('people.csv') >= 0")
        self.assertIn("does not look like a session log", page.inner_text("#msg-sessions"))
        self.assert_quiet()

    def test_every_download_opens_and_matches_the_companion(self):
        page = self.open()
        p = M.read_project(sample("sample-project.json"))
        a = M.analyse(dict(p["texts"], asOf=today()))
        name, text = self.download(page, lambda: page.click("button[data-act=csv-claims]"))
        self.assertTrue(name.endswith("-checklist.csv"))
        self.assertEqual(text, M.claims_csv(a, p["checks"]))
        rows = M.parse_csv(text)["rows"]
        self.assertEqual(rows[0][0], "Query")
        self.assertEqual(len(rows), 12)
        page.click("#tab-refs")
        name, text = self.download(page, lambda: page.click("button[data-act=csv-refs]"))
        self.assertEqual(text, M.refs_csv(a, p["refChecks"]))
        page.click("#tab-declare")
        state = {"project": p["project"], "sessions": p["sessions"], "checks": p["checks"], "refChecks": p["refChecks"], "asOf": today()}
        d = M.declaration(a, state)
        name, text = self.download(page, lambda: page.click("button[data-act=md-decl]"))
        self.assertTrue(name.endswith(".md"))
        self.assertEqual(text, M.declaration_markdown(d))
        name, text = self.download(page, lambda: page.click("button[data-act=txt-decl]"))
        self.assertEqual(text, M.declaration_text(d))
        name, text = self.download(page, lambda: page.click("button[data-act=csv-sessions]"))
        self.assertEqual(text, M.sessions_csv(p["sessions"]))
        self.assertEqual(len(M.parse_sessions(text)["sessions"]), 6)
        name, text = self.download(page, lambda: page.click("button[data-act=template]"))
        self.assertEqual(text, M.SESSION_TEMPLATE)
        name, text = self.download(page, lambda: page.click("#btn-save"))
        self.assertTrue(name.endswith(".checked-by-me.json"))
        self.assertEqual(text, M.project_file(dict(state, texts=p["texts"])))
        self.assert_quiet()

    def test_save_and_reopen_a_project(self):
        page = self.open()
        page.locator("#view-check li.query").first.locator("button[data-status=removed]").click()
        _, saved = self.download(page, lambda: page.click("#btn-save"))
        path = os.path.join(self.tmp.name, "reopen.checked-by-me.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(saved)
        page.click("#btn-new")
        self.assertEqual(page.input_value("#in-draft"), "")
        self.pick(page, "#btn-open", path)
        page.wait_for_function("document.getElementById('in-draft').value.length > 100")
        self.assertIn("Opened", page.inner_text("#notice"))
        page.click("#tab-check")
        self.assertEqual(page.locator("#view-check li.query.st-removed").count(), 1)
        junk = os.path.join(self.tmp.name, "junk.json")
        with open(junk, "w") as fh:
            fh.write('{"hello": 1}')
        self.pick(page, "#btn-open", junk)
        page.wait_for_function("document.getElementById('notice').textContent.indexOf('not a Checked by me project') >= 0")
        self.assert_quiet()

    def test_work_is_kept_in_the_browser_and_offered_back(self):
        page = self.open()
        page.click("#btn-own")
        page.fill("#in-draft", "Studies show that 87% of students always use AI (Smith, 2031).")
        page.wait_for_timeout(700)
        page.reload()
        page.wait_for_selector(".slip")
        self.assertIn("Welcome back", page.inner_text("#notice"))
        page.click("button[data-act=restore]")
        self.assertIn("87%", page.input_value("#in-draft"))
        page.click("#tab-check")
        self.assertIn("Vague source", page.inner_text("#view-check"))
        page.evaluate("localStorage.clear()")
        self.assert_quiet()

    def test_print_report_has_the_declaration_and_checklist(self):
        page = self.open()
        page.evaluate("window.print = function () {}")
        page.click("button[data-act=print]")
        sheet = page.inner_text("#print-sheet")
        self.assertIn("Declaration of AI use", sheet)
        self.assertIn("Claims checklist", sheet)
        self.assertIn("References to look at", sheet)
        page.emulate_media(media="print")
        self.assertFalse(page.locator(".desk").is_visible())
        self.assertTrue(page.locator("#print-sheet").is_visible())
        self.assert_quiet()

    def test_works_inside_an_iframe(self):
        host = os.path.join(self.tmp.name, "host.html")
        with open(host, "w") as fh:
            fh.write('<!doctype html><title>Host</title><iframe src="%s" style="width:1000px;height:800px" title="app"></iframe>' % PAGE)
        ctx = self.browser.new_context(viewport={"width": 1100, "height": 900})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("file://" + host)
        frame = page.frame_locator("iframe")
        frame.locator(".slip").first.wait_for()
        frame.locator("#tab-changes").click()
        self.assertIn("word for word", frame.locator("#view-changes").inner_text())
        self.assertEqual(errors, [])

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(width=390)
        for v in VIEWS:
            page.click("#tab-" + v)
            page.wait_for_timeout(80)
            width = page.evaluate("document.documentElement.scrollWidth")
            self.assertLessEqual(width, 390, "view %s scrolls sideways (%d px)" % (v, width))
        self.assert_quiet()

    def test_keyboard_moves_between_views(self):
        page = self.open()
        page.focus("#tab-check")
        page.keyboard.press("ArrowRight")
        self.assertTrue(page.locator("#view-refs").is_visible())
        self.assertEqual(page.evaluate("document.activeElement.id"), "tab-refs")
        page.keyboard.press("End")
        self.assertTrue(page.locator("#view-how").is_visible())
        page.keyboard.press("Home")
        self.assertTrue(page.locator("#view-copy").is_visible())

    def test_every_control_has_a_name(self):
        page = self.open()
        missing = []
        for v in VIEWS:
            page.click("#tab-" + v)
            missing += page.evaluate("""() => Array.from(document.querySelectorAll('button, input, select, textarea'))
                .filter(el => el.offsetParent !== null && el.type !== 'hidden')
                .filter(el => {
                  const name = (el.getAttribute('aria-label') || '') + (el.labels && el.labels.length ? el.labels[0].textContent : '')
                    + (el.tagName === 'BUTTON' ? el.textContent : '') + (el.getAttribute('title') || '');
                  return name.trim() === '';
                }).map(el => el.outerHTML.slice(0, 80))""")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
