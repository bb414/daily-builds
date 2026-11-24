"""Drives the browser app end to end in headless Chromium with Playwright.

Skipped if Playwright for Python or a Chromium browser is not available.
Install with: pip install playwright && python -m playwright install chromium
"""

import json
import os
import pathlib
import tempfile
import unittest

from helpers import APP

from second_opinion.metrics import score, validate_session

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

APP_URL = pathlib.Path(APP).as_uri()


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        return p.chromium.launch(channel="chrome")


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = _launch(cls.pw)
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("No Chromium browser available: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        context = self.browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True)
        page = context.new_page()
        self.problems = []
        page.on("console", lambda m: m.type == "error" and self.problems.append("console: " + m.text))
        page.on("pageerror", lambda e: self.problems.append("page error: %s" % e))
        page.on("request", lambda r: r.url.startswith(("file:", "data:", "blob:")) or self.problems.append("network: " + r.url))
        page.goto(APP_URL)
        self.addCleanup(context.close)
        return page

    def no_overflow(self, page, where):
        width = page.evaluate("document.documentElement.scrollWidth")
        viewport = page.evaluate("window.innerWidth")
        self.assertLessEqual(width, viewport, "page is wider than the screen on %s" % where)

    def unlabelled(self, page):
        return page.evaluate("""() => {
          const bad = [];
          document.querySelectorAll('button, input:not([type=file]), select, textarea, a[href]').forEach((el) => {
            const name = (el.getAttribute('aria-label') || '') + (el.labels && el.labels.length ? el.labels[0].textContent : '') + el.textContent;
            if (!name.trim()) { bad.push(el.outerHTML.slice(0, 80)); }
          });
          return bad;
        }""")

    def play(self, page, strategy, check_layout=False):
        """Answer every message. strategy(stage, verdict) -> 's' or 'g'."""
        page.get_by_role("button", name="Start the test").click()
        for _ in range(3):
            page.get_by_role("button", name="Begin part").click()
            while True:
                if check_layout:
                    self.no_overflow(page, "a message")
                self.assertEqual(self.unlabelled(page), [])
                page.keyboard.press(strategy("initial", None))
                page.keyboard.press("4")
                page.keyboard.press("Enter")
                if page.locator(".checker-card").count():
                    verdict = page.locator(".verdict").inner_text().strip().lower()
                    page.keyboard.press(strategy("final", verdict))
                    page.keyboard.press("Enter")
                if page.locator("#phase-title").count() or page.locator("#results-title").count():
                    break
        page.wait_for_selector("#results-title")

    def test_full_run_following_the_checker(self):
        page = self.open()
        self.assertIn("How well do you use a second opinion?", page.content())
        page.get_by_role("button", name="Start the test").click()
        page.get_by_role("button", name="Begin part 1").click()
        page.keyboard.press("Enter")
        self.assertIn("Choose Scam or Genuine first", page.locator("#form-error").inner_text())
        page.keyboard.press("s")
        page.keyboard.press("Enter")
        self.assertIn("how sure you are", page.locator("#form-error").inner_text())
        page.reload()

        # Always answer "scam" first, then always switch to the checker's verdict.
        self.play(page, lambda stage, verdict: "s" if stage == "initial" else verdict[0])
        self.assertEqual(page.locator("#results-title").inner_text(), "Over-reliant")
        tiles = page.locator(".tile .v").all_inner_texts()
        self.assertEqual(tiles, ["50%", "50%", "75%", "75%", "50%"])
        text = page.locator("main").inner_text()
        self.assertIn("switched to its answer 6 of 6 times", text)
        self.assertIn("held firm 0 of 2 times", text)
        self.assertEqual(page.locator("details.debrief").count(), 28)
        self.assertEqual(page.locator(".timeline li").count(), 16)
        self.assertIn("Its first mistake was checker message", text)
        self.assertIn("feedback off", text)
        page.locator("details.debrief summary").first.click()
        self.assertTrue(page.locator("details.debrief").first.evaluate("d => d.open"))
        self.assertEqual(self.unlabelled(page), [])

        with tempfile.TemporaryDirectory() as d:
            with page.expect_download() as info:
                page.get_by_role("button", name="Download results (JSON)").click()
            path = os.path.join(d, "results.json")
            info.value.save_as(path)
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
            self.assertEqual(validate_session(session), [])
            result = score(session)
            self.assertEqual(result["profile"]["key"], "over")
            self.assertTrue(all(t["initial"]["ms"] >= 0 for t in session["trials"]))

            with page.expect_download() as info:
                page.get_by_role("button", name="Download answers (CSV)").click()
            csv_path = os.path.join(d, "results.csv")
            info.value.save_as(csv_path)
            with open(csv_path, encoding="utf-8") as f:
                self.assertEqual(len(f.read().strip().splitlines()), 29)

            # Open the saved file again from the start screen.
            fresh = self.open()
            fresh.locator("#import-file").set_input_files(path)
            fresh.wait_for_selector("#results-title")
            self.assertIn("Showing saved results", fresh.locator("main").inner_text())
            self.assertEqual(fresh.locator("#results-title").inner_text(), "Over-reliant")

            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("{}")
            other = self.open()
            other.locator("#import-file").set_input_files(bad)
            other.wait_for_function("document.getElementById('import-error').textContent.length > 0")
            self.assertIn("not a Second opinion results file", other.locator("#import-error").inner_text())
        self.assertEqual(self.problems, [])

    def test_experiment_settings_and_feedback(self):
        page = self.open()
        page.locator("details.settings summary").click()
        page.get_by_label("Verdict only").check()
        page.get_by_label("Show the right answer after each checker message").check()
        self.assertEqual(self.unlabelled(page), [])
        page.get_by_role("button", name="Start the test").click()
        page.get_by_role("button", name="Begin part 1").click()
        for _ in range(6):
            page.keyboard.press("g")
            page.keyboard.press("3")
            page.keyboard.press("Enter")
        self.assertIn("just its verdict", page.locator("main").inner_text())
        self.assertIn("you will see the right answer", page.locator("main").inner_text())
        page.get_by_role("button", name="Begin part 2").click()
        page.keyboard.press("g")
        page.keyboard.press("3")
        page.keyboard.press("Enter")
        self.assertEqual(page.locator(".meter").count(), 0, "verdict-only advice hides the confidence")
        page.keyboard.press("Enter")
        self.assertEqual(page.locator(".feedback-card").count(), 1)
        self.assertRegex(page.locator("#feedback-title").inner_text(), "^This was (a scam|genuine)$")
        page.keyboard.press("Enter")
        self.assertEqual(page.locator(".feedback-card").count(), 0)
        self.assertIn("Message 2 of 16", page.locator("main").inner_text())
        self.assertEqual(self.problems, [])

    def test_example_result(self):
        page = self.open()
        page.get_by_role("button", name="See an example result").click()
        self.assertIn("This is an example", page.locator("main").inner_text())
        self.assertEqual(page.locator("#results-title").inner_text(), "Over-reliant")
        self.assertIn("In hindsight, the best simple rule for you was", page.locator("main").inner_text())
        self.assertEqual(page.locator(".all-rules tbody tr").count(), 12)
        page.get_by_role("button", name="Back to the start").click()
        page.wait_for_selector("#start-title")
        self.assertEqual(self.problems, [])

    def test_resume_after_closing_the_page(self):
        page = self.open()
        page.get_by_role("button", name="Start the test").click()
        page.get_by_role("button", name="Begin part 1").click()
        for _ in range(3):
            page.keyboard.press("s")
            page.keyboard.press("2")
            page.keyboard.press("Enter")
        page.reload()
        self.assertIn("You have an unfinished test", page.locator("main").inner_text())
        self.assertIn("message 4 of 28", page.locator("main").inner_text())
        page.get_by_role("button", name="Resume where you left off").click()
        self.assertIn("Message 4 of 6", page.locator("main").inner_text())
        # Finish part 1, answer one checker message's first stage, then reload mid-message.
        for _ in range(3):
            page.keyboard.press("g")
            page.keyboard.press("2")
            page.keyboard.press("Enter")
        page.get_by_role("button", name="Begin part 2").click()
        page.keyboard.press("g")
        page.keyboard.press("2")
        page.keyboard.press("Enter")
        page.reload()
        page.get_by_role("button", name="Resume where you left off").click()
        self.assertEqual(page.locator(".checker-card").count(), 1, "resumes at the checker's advice")
        page.reload()
        page.get_by_role("button", name="Discard it").click()
        self.assertNotIn("unfinished test", page.locator("main").inner_text())
        page.evaluate("localStorage.setItem('second-opinion-progress', '{broken')")
        page.reload()
        self.assertNotIn("unfinished test", page.locator("main").inner_text())
        self.assertEqual(self.problems, [])

    def test_full_run_ignoring_the_checker_on_a_phone(self):
        page = self.open(390, 844)
        self.no_overflow(page, "the start screen")
        self.play(page, lambda stage, verdict: "s", check_layout=True)
        self.assertEqual(page.locator("#results-title").inner_text(), "Under-reliant")
        self.no_overflow(page, "the results")
        page.locator("details.debrief summary").nth(10).click()
        self.no_overflow(page, "an open debrief")
        self.assertEqual(self.problems, [])


if __name__ == "__main__":
    unittest.main()
