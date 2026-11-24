"""Drives the browser app in headless Chromium. Skipped if Playwright for Python is not installed."""

import json
import tempfile
import unittest
from pathlib import Path

from reliance_lab.sessions import load_session, score_session

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

APP = (Path(__file__).resolve().parent.parent / "app" / "index.html").as_uri()


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - no browser available
            cls.pw.stop()
            raise unittest.SkipTest(f"No Chromium available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height}, accept_downloads=True)
        self.problems = []
        page.on("console", lambda m: self.problems.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.problems.append(str(e)))
        page.on("request", lambda r: self.problems.append("network: " + r.url)
                if not r.url.startswith(("file:", "data:", "blob:")) else None)
        page.goto(APP)
        return page

    def play(self, page, n_cases, final_rule):
        """Play a whole session with the keyboard only."""
        for i in range(n_cases):
            page.keyboard.press("f" if i % 3 else "g")
            page.keyboard.press(str(1 + i % 4))
            page.keyboard.press("Enter")
            page.keyboard.press(final_rule(i))
            page.keyboard.press("Enter")

    def test_a_full_session_by_keyboard_then_download(self):
        page = self.open()
        page.check("input[name=cases][value='12']")
        page.fill("#session-code", "TEST1")
        page.click("text=Start reviewing")
        self.assertEqual(page.inner_text("#case-title"), "Payment 1 of 12")
        self.assertTrue(page.is_disabled("#reveal-btn"))
        self.play(page, 12, lambda i: "f" if i % 2 else "g")
        self.assertTrue(page.is_visible("#try-debrief"))
        self.assertEqual(page.locator("#debrief-tiles .tile").count(), 4)
        self.assertEqual(page.locator("#trial-table tbody tr").count(), 12)
        self.assertEqual(page.locator("#cf-chart svg rect").count() >= 5, True)
        with page.expect_download() as info:
            page.click("#download-btn")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            info.value.save_as(path)
            data = load_session(path)
            self.assertEqual(len(data["trials"]), 12)
            self.assertEqual(data["settings"]["code"], "TEST1")
            summary = json.loads(path.read_text())["summary"]
            expected = score_session(data["trials"])
            self.assertEqual(sorted(summary), sorted(expected))
            for key, value in expected.items():
                if isinstance(value, float):
                    self.assertAlmostEqual(summary[key], value, places=12, msg=key)
                else:
                    self.assertEqual(summary[key], value, key)
        self.assertEqual(self.problems, [])

    def test_feedback_mode_locks_the_final_answer(self):
        page = self.open()
        page.check("#feedback")
        page.click("text=Start reviewing")
        page.click("[data-initial=fraud]")
        page.click("[data-conf='0.7']")
        page.click("#reveal-btn")
        page.click("[data-final=genuine]")
        self.assertTrue(page.is_visible("#feedback-box"))
        self.assertTrue(page.is_disabled("[data-final=fraud]"))
        self.assertIn("This payment was", page.inner_text("#feedback-box"))

    def test_same_code_gives_same_payments(self):
        facts = []
        for _ in range(2):
            page = self.open()
            page.fill("#session-code", "SAME")
            page.click("text=Start reviewing")
            facts.append(page.inner_text("#case-facts"))
            page.close()
        self.assertEqual(facts[0], facts[1])

    def test_model_tab_reacts_and_fits_a_phone(self):
        page = self.open(390, 844)
        page.click("#tab-model")
        before = page.inner_text("#model-tiles")
        page.focus("#s-aiSignal")
        for _ in range(10):
            page.keyboard.press("ArrowLeft")
        self.assertNotEqual(page.inner_text("#model-tiles"), before)
        self.assertEqual(page.get_attribute("#s-aiSignal", "aria-valuetext"), "0.5 (weak)")
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        self.assertEqual(self.problems, [])

    def test_presets_and_settings_link(self):
        page = self.open()
        page.click("#tab-model")
        page.select_option("#preset", label="Two equals with honest confidence")
        self.assertIn("Equally accurate", page.inner_text("#preset-hint"))
        self.assertEqual(page.input_value("#s-human"), "0.8")
        url = page.url
        self.assertIn("#model?human=0.8&ai=0.8", url)
        self.assertIn("Biggest gains", page.inner_text("#lever-note"))
        other = self.browser.new_page()
        other.goto(url)
        self.assertEqual(other.get_attribute("#tab-model", "aria-selected"), "true")
        self.assertEqual(other.input_value("#s-humanSignal"), "2")
        other.close()
        page.click("#tab-try")
        self.assertNotIn("#model?", page.url)
        self.assertEqual(self.problems, [])

    def test_opening_a_saved_results_file(self):
        page = self.open()
        sample = Path(__file__).resolve().parent.parent / "examples" / "sessions" / "P01.json"
        page.set_input_files("#open-file", str(sample))
        self.assertTrue(page.is_visible("#try-debrief"))
        self.assertEqual(page.locator("#trial-table tbody tr").count(), 20)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"format": "something else"}')
            page.click("#again-btn")
            page.set_input_files("#open-file", str(bad))
            self.assertIn("not a Reliance lab results file", page.inner_text("#open-status"))
            self.assertTrue(page.is_visible("#try-setup"))

    def test_tabs_work_from_the_keyboard(self):
        page = self.open()
        page.focus("#tab-try")
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.get_attribute("#tab-model", "aria-selected"), "true")
        self.assertFalse(page.is_hidden("#panel-model"))
        page.keyboard.press("End")
        self.assertFalse(page.is_hidden("#panel-about"))
        self.assertTrue(page.is_hidden("#panel-try"))


if __name__ == "__main__":
    unittest.main()
